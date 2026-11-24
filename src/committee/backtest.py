"""Monthly-rebalanced backtest: costs, benchmark, risk/return, attribution, sensitivity."""
from __future__ import annotations

import itertools
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from .portfolio import Config, allocate, analyse, weights_of


@dataclass
class Result:
    equity: pd.Series
    benchmark: pd.Series
    weights: pd.DataFrame          # target weights at each rebalance date
    turnover_series: pd.Series     # one-way turnover per rebalance
    contribution: pd.Series        # summed simple contribution per ticker (approximate, not compounded)
    metrics: dict
    bench_metrics: dict
    relative: dict
    annual: pd.DataFrame
    bench_label: str = "Equal-weight"

    @property
    def turnover(self) -> float:
        return float(self.turnover_series.mean())


def metrics(equity: pd.Series, rf_daily: pd.Series | None = None) -> dict:
    """Risk/return summary. With `rf_daily` (decimal per trading day), Sharpe and Sortino use excess returns."""
    r = equity.pct_change().dropna()
    ex = r - rf_daily.reindex(r.index).fillna(0.0) if rf_daily is not None else r
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1 if years > 0 else np.nan
    vol = r.std() * np.sqrt(252)
    down = ex[ex < 0].std() * np.sqrt(252)
    mdd = (equity / equity.cummax() - 1).min()
    return {"CAGR": float(cagr), "Vol": float(vol),
            "Sharpe": float(ex.mean() * 252 / vol) if vol > 0 else np.nan,
            "Sortino": float(ex.mean() * 252 / down) if down > 0 else np.nan,
            "MaxDD": float(mdd),
            "Calmar": float(cagr / abs(mdd)) if mdd < 0 else np.nan}


def relative_metrics(equity: pd.Series, bench: pd.Series) -> dict:
    r, b = equity.pct_change().dropna(), bench.pct_change().dropna()
    vb = np.var(b, ddof=1)
    beta = float(np.cov(r, b)[0, 1] / vb) if vb > 0 else float("nan")
    alpha = float((r.mean() - beta * b.mean()) * 252)
    active = r - b
    te = float(active.std() * np.sqrt(252))
    mr, mb = (equity.resample("ME").last().pct_change().dropna(),
              bench.resample("ME").last().pct_change().dropna())
    return {"Beta": beta, "Alpha (ann.)": alpha, "Tracking error": te,
            "Information ratio": float(active.mean() * 252 / te) if te > 0 else np.nan,
            "Monthly hit rate": float((mr > mb).mean())}


def annual_returns(equity: pd.Series, bench: pd.Series) -> pd.DataFrame:
    def yr(s):
        ye = s.groupby(s.index.year).last()
        out = ye / ye.shift(1).fillna(s.iloc[0]) - 1
        return out[s.groupby(s.index.year).size() >= 60]   # drop stub years (too few observations)
    return pd.DataFrame({"Committee": yr(equity), "Benchmark": yr(bench)})


def _period_path(prices: pd.DataFrame, start, end, w: pd.Series, cash_rate: float = 0.0,
                 rf_daily: pd.Series | None = None) -> pd.Series:
    seg = prices.loc[start:end]
    rel = seg / seg.iloc[0]
    if rf_daily is not None:
        growth = (1.0 + rf_daily.reindex(seg.index).fillna(0.0)).cumprod()
        cash = (1.0 - w.sum()) * growth / growth.iloc[0]
    else:
        years = (seg.index - seg.index[0]).days / 365.0
        cash = (1.0 - w.sum()) * (1.0 + cash_rate) ** years
    return (rel * w.reindex(rel.columns).fillna(0.0)).sum(axis=1) + cash


def rf_to_daily(rf: pd.Series | None, index: pd.DatetimeIndex) -> pd.Series | None:
    """Annual decimal rate series -> per-trading-day rate aligned on `index` (forward-filled, no look-ahead)."""
    if rf is None:
        return None
    r = rf.sort_index().reindex(rf.index.union(index)).ffill().reindex(index)
    return r.bfill().fillna(0.0) / 252.0


def _equal_weight(prices: pd.DataFrame, at) -> pd.Series:
    """Equal weight over the assets that have a price on `at` (handles late-listed assets)."""
    avail = prices.loc[at].notna()
    return pd.Series(np.where(avail, 1.0 / max(int(avail.sum()), 1), 0.0), index=prices.columns)


def run(prices: pd.DataFrame, fundamentals: dict, cfg: Config | None = None,
        cost_bps: float | None = None, warmup: int = 253, agents=None,
        benchmark: str | None = None, rf: pd.Series | None = None, cache: dict | None = None) -> Result:
    """Replay the committee. Decisions use data up to the month-end close; trades execute
    `cfg.exec_lag` trading days later at that day's close (default 1: no same-close trading).
    `benchmark`: a column of `prices` held buy-and-hold; default is the equal-weight universe.
    `rf`: annual risk-free rate (decimal) indexed by date; cash earns it and Sharpe uses excess returns.
    `cache`: dict reused across runs so signals are computed once per date (big speed-up for sweeps)."""
    cfg = cfg or Config()
    cost_bps = cfg.cost_bps if cost_bps is None else cost_bps
    idx = prices.index
    if benchmark is not None and benchmark not in prices.columns:
        raise ValueError(f"benchmark {benchmark!r} not in prices")
    month_ends = [d for d in prices.groupby([idx.year, idx.month]).tail(1).index
                  if idx.get_loc(d) >= warmup]
    if len(month_ends) < 3:
        raise ValueError(f"not enough history: need > {warmup} trading days plus 2 months")
    rfd = rf_to_daily(rf, idx)
    last = len(idx) - 1
    pos = [min(idx.get_loc(d) + cfg.exec_lag, last) for d in month_ends]
    eq, bench, dates = [1.0], [1.0], [idx[pos[0]]]
    prev_w = pd.Series(0.0, index=prices.columns)
    w_rows, turns, contrib = {}, {}, pd.Series(0.0, index=prices.columns)
    for k in range(len(month_ends) - 1):
        a, s0, e0 = month_ends[k], idx[pos[k]], idx[pos[k + 1]]
        if e0 <= s0:
            continue
        if cache is not None and a in cache:
            an = cache[a]
        else:
            an = analyse(prices, fundamentals, a, agents)
            if cache is not None:
                cache[a] = an
        w = weights_of(allocate(an, cfg))
        turnover = float((w - prev_w).abs().sum())
        cost = turnover * cost_bps / 1e4
        seg = prices.loc[s0:e0]
        contrib = contrib.add(w * (seg.iloc[-1] / seg.iloc[0] - 1), fill_value=0.0)
        path = _period_path(prices, s0, e0, w, cfg.cash_rate, rfd).iloc[1:]
        if benchmark is None:
            bpath = _period_path(prices, s0, e0, _equal_weight(prices, s0)).iloc[1:]
        else:
            bs = seg[benchmark]
            bpath = (bs / bs.iloc[0]).iloc[1:]
        e_start, b_start = eq[-1] * (1 - cost), bench[-1]
        for d, v, bv in zip(path.index, path.values, bpath.values, strict=True):
            eq.append(e_start * v); bench.append(b_start * bv); dates.append(d)
        w_rows[a], turns[a], prev_w = w, turnover, w
    equity, bm = pd.Series(eq, index=dates), pd.Series(bench, index=dates)
    return Result(equity, bm, pd.DataFrame(w_rows).T, pd.Series(turns), contrib,
                  metrics(equity, rfd), metrics(bm, rfd), relative_metrics(equity, bm), annual_returns(equity, bm),
                  benchmark or "Equal-weight")


def sensitivity(prices: pd.DataFrame, fundamentals: dict, cfg: Config | None = None,
                min_scores=(0.0, 0.1, 0.2, 0.3), caps=(0.15, 0.25, 0.35),
                rf: pd.Series | None = None, cache: dict | None = None) -> pd.DataFrame:
    """Sharpe over a parameter grid: shows how fragile (or not) the result is to our own choices."""
    cfg = cfg or Config()
    cache = {} if cache is None else cache
    rows = []
    for ms, cap in itertools.product(min_scores, caps):
        r = run(prices, fundamentals, replace(cfg, min_score=ms, max_position=cap), rf=rf, cache=cache)
        rows.append({"min_score": ms, "max_position": cap, "CAGR": r.metrics["CAGR"],
                     "Sharpe": r.metrics["Sharpe"], "MaxDD": r.metrics["MaxDD"]})
    return pd.DataFrame(rows)
