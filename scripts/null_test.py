"""Null test: committee vs equal-weight basket on 30 synthetic markets that contain no edge.

Run: python scripts/null_test.py
"""
import warnings

import numpy as np

from committee.backtest import run
from committee.data import synthetic_market
from committee.portfolio import Config

warnings.filterwarnings("ignore")

excess = []
for seed in range(30):
    prices, fundamentals, _ = synthetic_market(seed=seed)
    res = run(prices, fundamentals, Config())
    excess.append(res.metrics["CAGR"] - res.bench_metrics["CAGR"])
x = np.array(excess)
print(f"mean excess CAGR {x.mean():.2%}  median {np.median(x):.2%}  std {x.std(ddof=1):.2%}  "
      f"wins {(x > 0).sum()}/30  min {x.min():.2%}  max {x.max():.2%}")
print(f"t-stat of mean: {x.mean() / (x.std(ddof=1) / np.sqrt(30)):.2f}")
