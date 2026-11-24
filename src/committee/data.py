"""Data loading and a synthetic market generator.

The synthetic universe is a *null world*: returns do not depend on the
fundamentals. A sound pipeline must therefore show no durable edge on it,
which makes it a useful sanity check (see docs/METHODOLOGY.md).
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

FUND_COLS = ["pe", "pb", "fcf_yield", "roe", "net_margin", "debt_ebitda", "rev_growth"]


def validate_prices(df: pd.DataFrame) -> pd.DataFrame:
    """Fail loudly on data problems that silently corrupt a backtest."""
    if df.empty or df.shape[1] == 0:
        raise ValueError("prices: empty table")
    if not df.index.is_monotonic_increasing:
        raise ValueError("prices: dates are not sorted")
    if df.index.has_duplicates:
        raise ValueError("prices: duplicate dates")
    bad = [c for c in df.columns if df[c].notna().sum() == 0]
    if bad:
        raise ValueError(f"prices: columns with no data: {bad}")
    if (df <= 0).any().any():
        raise ValueError("prices: non-positive values (use adjusted close)")
    jumps = df.pct_change(fill_method=None).abs().max()
    if (jumps > 0.6).any():
        names = list(jumps[jumps > 0.6].index)
        warnings.warn(f"prices: daily move above 60% in {names} (unadjusted split?)", stacklevel=2)
    return df


def load_prices(path: str) -> pd.DataFrame:
    """CSV with a `date` column and one column per ticker (adjusted close)."""
    df = pd.read_csv(path, parse_dates=["date"]).set_index("date").sort_index()
    return validate_prices(df.astype(float))


def load_rf(path: str) -> pd.Series:
    """Risk-free rate CSV: `date` + one column of annual rates in PERCENT (e.g. Yahoo ^IRX). Returns decimals."""
    df = pd.read_csv(path, parse_dates=["date"]).set_index("date").sort_index()
    col = df.columns[0]
    s = pd.to_numeric(df[col], errors="coerce").dropna() / 100.0
    if s.empty or (s < -0.05).any() or (s > 0.5).any():
        raise ValueError("rf: values must be annual rates in percent between -5 and 50")
    return s


def load_fundamentals(path: str) -> dict[str, pd.DataFrame]:
    """Long CSV: date, ticker, then FUND_COLS. Dates are the *publication* dates."""
    df = pd.read_csv(path, parse_dates=["date"]).sort_values("date")
    missing = [c for c in FUND_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"missing fundamentals columns: {missing}")
    return {t: g.set_index("date")[FUND_COLS] for t, g in df.groupby("ticker")}


def asof(frame: pd.DataFrame, date: pd.Timestamp) -> pd.Series | None:
    """Latest row published on or before `date` (point-in-time, no look-ahead)."""
    sub = frame.loc[:date]
    return None if sub.empty else sub.iloc[-1]


def synthetic_market(n_tickers: int = 12, years: int = 8, seed: int = 7):
    """Seeded synthetic prices and quarterly fundamentals (fictitious tickers)."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2016-01-04", periods=years * 252)
    tickers = [f"SYN{i:02d}" for i in range(1, n_tickers + 1)]
    market = rng.normal(0.0003, 0.008, len(dates))
    prices = {}
    for t in tickers:
        beta = rng.uniform(0.6, 1.4)
        idio = rng.normal(0.0, rng.uniform(0.008, 0.016), len(dates))
        r = 0.0001 + beta * market + idio
        prices[t] = 100 * np.exp(np.cumsum(r))
    prices = pd.DataFrame(prices, index=dates)

    qdates = pd.date_range(dates[0], dates[-1], freq="QS") + pd.Timedelta(days=45)
    rows = []
    for t in tickers:
        base = dict(pe=rng.uniform(8, 35), pb=rng.uniform(0.8, 6), fcf=rng.uniform(0.01, 0.09),
                    roe=rng.uniform(0.04, 0.30), nm=rng.uniform(0.02, 0.25),
                    lev=rng.uniform(0.2, 4.0), g=rng.uniform(-0.02, 0.25))
        for d in qdates:
            rows.append(dict(
                date=d, ticker=t,
                pe=max(base["pe"] * rng.uniform(0.9, 1.1), 3),
                pb=max(base["pb"] * rng.uniform(0.9, 1.1), 0.3),
                fcf_yield=base["fcf"] * rng.uniform(0.85, 1.15),
                roe=base["roe"] * rng.uniform(0.9, 1.1),
                net_margin=base["nm"] * rng.uniform(0.9, 1.1),
                debt_ebitda=max(base["lev"] * rng.uniform(0.85, 1.15), 0),
                rev_growth=base["g"] + rng.normal(0, 0.02)))
    fdf = pd.DataFrame(rows)
    fund = {t: g.set_index("date")[FUND_COLS] for t, g in fdf.groupby("ticker")}
    return prices, fund, fdf
