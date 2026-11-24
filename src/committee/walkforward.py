"""Walk-forward (out-of-sample) evaluation of parameter choice.

Every parameter set in the grid is backtested once over the whole history. At each
fold start T, the set with the best Sharpe over the preceding `train_years` is selected
(using returns strictly before T only) and its returns over the next `test_months` are
the out-of-sample returns. Chained folds give a track record in which no parameter was
ever chosen with knowledge of the period it is applied to.

Simplification: runs are independent, so portfolio state is not carried across a
parameter switch; instead one full turnover of `cost_bps` is charged at each switch.
"""
from __future__ import annotations

import itertools
from dataclasses import replace

import numpy as np
import pandas as pd

from .backtest import metrics, rf_to_daily, run
from .portfolio import Config


def _sharpe(r: pd.Series) -> float:
    sd = r.std()
    return float(r.mean() / sd * np.sqrt(252)) if len(r) > 20 and sd > 0 else float("-inf")


def walk_forward(prices: pd.DataFrame, fundamentals: dict, cfg: Config | None = None,
                 min_scores=(0.0, 0.1, 0.2, 0.3), caps=(0.15, 0.25, 0.35), train_years: int = 4,
                 test_months: int = 12, rf: pd.Series | None = None, cache: dict | None = None,
                 benchmark: str | None = None) -> dict:
    cfg = cfg or Config()
    cache = {} if cache is None else cache
    grid = list(itertools.product(min_scores, caps))
    runs = {k: run(prices, fundamentals, replace(cfg, min_score=k[0], max_position=k[1]),
                   rf=rf, cache=cache, benchmark=benchmark) for k in grid}
    base = run(prices, fundamentals, cfg, rf=rf, cache=cache, benchmark=benchmark)
    ret = {k: r.equity.pct_change().dropna() for k, r in runs.items()}
    idx = base.equity.index
    t0 = idx[0] + pd.DateOffset(years=train_years)
    folds, pieces, prev = [], [], None
    T = t0
    while T < idx[-1]:
        T_next = T + pd.DateOffset(months=test_months)
        scores = {k: _sharpe(ret[k].loc[T - pd.DateOffset(years=train_years): T - pd.Timedelta(days=1)]) for k in grid}
        best = max(grid, key=lambda k: (scores[k], -grid.index(k)))
        oos = ret[best].loc[T: T_next - pd.Timedelta(days=1)].copy()
        if len(oos) < 5:
            break
        if prev is not None and best != prev:
            oos.iloc[0] -= cfg.cost_bps / 1e4
        folds.append({"start": str(oos.index[0].date()), "end": str(oos.index[-1].date()),
                      "min_score": best[0], "max_position": best[1], "train_sharpe": scores[best],
                      "oos_return": float((1 + oos).prod() - 1)})
        pieces.append(oos); prev = best; T = T_next
    if not pieces:
        raise ValueError(f"not enough history for walk-forward: need over {train_years} years plus a test window")
    oos = pd.concat(pieces)
    start = oos.index[0] - pd.Timedelta(days=1)
    eq = pd.concat([pd.Series([1.0], index=[start]), (1 + oos).cumprod()])
    span = slice(oos.index[0], oos.index[-1])
    fixed = base.equity.loc[span]
    bench = base.benchmark.loc[span]
    rfd = rf_to_daily(rf, idx)
    switches = sum(1 for a, b in zip(folds, folds[1:], strict=False)
                   if (a["min_score"], a["max_position"]) != (b["min_score"], b["max_position"]))
    return {"train_years": train_years, "test_months": test_months, "n_folds": len(folds), "switches": switches,
            "adaptive": metrics(eq, rfd), "fixed_default": metrics(fixed / fixed.iloc[0], rfd),
            "benchmark": metrics(bench / bench.iloc[0], rfd), "bench_label": base.bench_label,
            "span": [str(oos.index[0].date()), str(oos.index[-1].date())], "folds": folds}
