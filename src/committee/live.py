"""Real market data via yfinance (optional dependency, lazy import).

IMPORTANT: Yahoo's fundamentals are a *current snapshot*, not point-in-time.
They are fine for `analyze` today, but must NOT be used in a historical
backtest (look-ahead). `backtest` therefore runs price-only (momentum + risk)
unless you supply your own dated fundamentals CSV.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _yf():
    try:
        import yfinance as yf
    except ImportError as e:  # pragma: no cover
        raise SystemExit("pip install yfinance  (optional, see requirements-optional.txt)") from e
    return yf


def fetch_prices(tickers: list[str], start: str = "2015-01-01") -> pd.DataFrame:
    """Adjusted close, one column per ticker."""
    df = _yf().download(tickers, start=start, auto_adjust=True, progress=False)["Close"]
    if isinstance(df, pd.Series):
        df = df.to_frame(tickers[0])
    return df.dropna(how="all").astype(float)


def snapshot_from_info(info: dict) -> dict:
    """Map a yfinance `info` dict to the committee's fundamentals fields (NaN when absent)."""
    def g(k):
        v = info.get(k)
        return float(v) if isinstance(v, (int, float)) and np.isfinite(v) else np.nan
    mcap, fcf, ebitda, debt = g("marketCap"), g("freeCashflow"), g("ebitda"), g("totalDebt")
    return dict(
        pe=g("trailingPE"), pb=g("priceToBook"),
        fcf_yield=fcf / mcap if np.isfinite(fcf) and np.isfinite(mcap) and mcap else np.nan,
        roe=g("returnOnEquity"), net_margin=g("profitMargins"),
        debt_ebitda=debt / ebitda if np.isfinite(debt) and np.isfinite(ebitda) and ebitda > 0 else np.nan,
        rev_growth=g("revenueGrowth"))


def fetch_snapshot(tickers: list[str], on: pd.Timestamp | None = None) -> dict[str, pd.DataFrame]:
    """Current fundamentals as a one-row frame per ticker, dated today (not point-in-time)."""
    yf, out = _yf(), {}
    on = on or pd.Timestamp.today().normalize()
    for t in tickers:
        try:
            out[t] = pd.DataFrame([snapshot_from_info(yf.Ticker(t).info)], index=[on])
        except Exception:
            continue  # ticker without data: agents report "unavailable"
    return out
