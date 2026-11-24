"""Out-of-the-box empirical study on real price data (ETF universe).

`run_study` produces a JSON-serialisable bundle (pure numbers); `render_study`
turns it into charts and a markdown report. They are split so the heavy part
can run anywhere (including a browser Python runtime) and rendering anywhere else.

Protocol (fixed BEFORE looking at any result, see docs/REAL_WORLD_STUDY.md):
default Config unchanged, price-only agents, benchmarks SPY and equal-weight,
no parameter is tuned on the sample.
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from .backtest import metrics, rf_to_daily, run, sensitivity
from .portfolio import Config, decide
from .walkforward import walk_forward

WINDOWS = {  # stress windows fixed in advance
    "Global financial crisis (31 Oct 2007 - 9 Mar 2009)": ("2007-10-31", "2009-03-09"),
    "COVID crash (19 Feb - 23 Mar 2020)": ("2020-02-19", "2020-03-23"),
    "2022 inflation / rate shock (calendar year)": ("2021-12-31", "2022-12-30"),
}


def _r(x, n=4):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), n)


def _mdict(m):
    return {k: _r(v) for k, v in m.items()}


def _window(eq: pd.Series, a: str, b: str) -> dict | None:
    s = eq.loc[a:b]
    if len(s) < 5:
        return None
    return {"return": _r(s.iloc[-1] / s.iloc[0] - 1), "maxdd": _r((s / s.cummax() - 1).min())}


def bootstrap_active(strat: pd.Series, bench: pd.Series, n: int = 4000, block: int = 6, seed: int = 11) -> dict:
    """Moving-block bootstrap of monthly active returns: CI of annualised excess return."""
    ms = strat.resample("ME").last().pct_change().dropna()
    mb = bench.resample("ME").last().pct_change().dropna()
    active = (ms - mb).dropna().values
    rng = np.random.default_rng(seed)
    T = len(active)
    starts = rng.integers(0, T - block + 1, size=(n, int(np.ceil(T / block))))
    samples = np.concatenate([active[s: s + block] for s in starts.reshape(-1)]).reshape(n, -1)[:, :T]
    ann = samples.mean(axis=1) * 12
    return {"months": int(T), "mean_ann": _r(active.mean() * 12), "ci05": _r(np.percentile(ann, 5)),
            "ci95": _r(np.percentile(ann, 95)), "p_positive": _r((ann > 0).mean(), 3)}


def run_study(prices: pd.DataFrame, cfg: Config | None = None, bench: str = "SPY",
              costs=(0.0, 10.0, 25.0, 50.0), grid: bool = True,
              source: str = "user-supplied prices CSV", rf: pd.Series | None = None) -> dict:
    cfg = cfg or Config()
    cache: dict = {}
    res = run(prices, {}, cfg, benchmark=bench, rf=rf, cache=cache)
    ew = run(prices, {}, cfg, rf=rf, cache=cache)
    eq, spy, ewe = res.equity, res.benchmark, ew.benchmark
    half = eq.index[len(eq) // 2]
    rfd = rf_to_daily(rf, eq.index)
    periods = {"Full sample": (eq.index[0], eq.index[-1]),
               "First half": (eq.index[0], half), "Second half": (half, eq.index[-1])}
    sub = {}

    def _m(series, a, b):
        return _mdict(metrics(series.loc[a:b], rfd.loc[a:b] if rfd is not None else None))

    for name, (a, b) in periods.items():
        sub[name] = {"range": [str(a.date()), str(b.date())],
                     "Committee": _m(eq, a, b), bench: _m(spy, a, b), "Equal-weight": _m(ewe, a, b)}
    windows = {k: {"Committee": _window(eq, *v), bench: _window(spy, *v), "Equal-weight": _window(ewe, *v)}
               for k, v in WINDOWS.items()}
    cost_tbl = []
    for c in costs:
        r = run(prices, {}, replace(cfg, cost_bps=c), benchmark=bench, rf=rf, cache=cache)
        cost_tbl.append({"cost_bps": c, **_mdict({k: r.metrics[k] for k in ("CAGR", "Sharpe", "MaxDD")})})
    ann = (res.annual.join(pd.DataFrame({"Equal-weight": ew.annual["Benchmark"]}))
           .rename(columns={"Benchmark": bench}))
    w = res.weights
    wk = eq.index[::5]
    final = decide(prices, {}, prices.index[-1], cfg)
    try:
        wf = walk_forward(prices, {}, cfg, rf=rf, cache=cache, benchmark=bench)
        wf_out = {**{k: wf[k] for k in ("train_years", "test_months", "n_folds", "switches", "bench_label", "span")},
                  **{k: _mdict(wf[k]) for k in ("adaptive", "fixed_default", "benchmark")},
                  "folds": [{**f, "train_sharpe": _r(f["train_sharpe"], 2), "oos_return": _r(f["oos_return"])}
                            for f in wf["folds"]]}
    except ValueError:
        wf_out = None   # history too short: the report says so instead of failing
    return {
        "meta": {"start": str(eq.index[0].date()), "end": str(eq.index[-1].date()), "tickers": list(prices.columns),
                 "bench": bench, "config": cfg.fingerprint(), "cost_bps": cfg.cost_bps, "exec_lag": cfg.exec_lag,
                 "cash_rate": cfg.cash_rate, "source": source, "rf": rf is not None},
        "metrics": {"Committee": _mdict(res.metrics), bench: _mdict(res.bench_metrics),
                    "Equal-weight": _mdict(ew.bench_metrics)},
        "relative": {bench: {k: _r(v) for k, v in res.relative.items()},
                     "Equal-weight": {k: _r(v) for k, v in ew.relative.items()}},
        "bootstrap": {bench: bootstrap_active(eq, spy), "Equal-weight": bootstrap_active(eq, ewe)},
        "walk_forward": wf_out, "subperiods": sub, "windows": windows, "cost_sensitivity": cost_tbl,
        "grid": ([{k: _r(v) for k, v in row.items()} for row in
                  sensitivity(prices, {}, cfg, rf=rf, cache=cache).to_dict("records")] if grid else []),
        "annual": {str(y): {c: _r(v) for c, v in row.items()} for y, row in ann.iterrows()},
        "turnover": _r(res.turnover), "invested": _r(w.sum(axis=1).mean()),
        "months_all_cash": _r((w.sum(axis=1) == 0).mean()),
        "avg_weights": {t: _r(v) for t, v in w.mean().sort_values(ascending=False).items()},
        "latest": [{"ticker": d.ticker, "score": _r(d.composite, 3), "weight": _r(d.weight), "vetoed": d.vetoed}
                   for d in sorted(final, key=lambda x: -x.composite)],
        "series": {"dates": [str(d.date()) for d in wk], "Committee": [_r(v) for v in eq.loc[wk]],
                   bench: [_r(v) for v in spy.loc[wk]], "Equal-weight": [_r(v) for v in ewe.loc[wk]]},
    }
