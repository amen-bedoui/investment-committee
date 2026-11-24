"""Analyst agents. Each one returns a bounded, explainable Signal.

Agents are deterministic rules (transparent, testable, free to run). The
`Agent` protocol is deliberately small so an LLM-backed agent can be dropped
in later without touching the portfolio or backtest code.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Signal:
    agent: str
    ticker: str
    score: float        # -1 (avoid) .. +1 (attractive)
    confidence: float   # 0 .. 1
    rationale: str


@dataclass(frozen=True)
class Context:
    ticker: str
    prices: pd.Series          # history up to and including the decision date ONLY
    fundamentals: pd.Series | None


class Agent(Protocol):
    name: str
    def analyse(self, ctx: Context) -> Signal: ...


def _clip(x: float) -> float:
    return float(np.clip(x, -1.0, 1.0))


def _mean(parts: list[float]):
    """Mean of the finite parts; None if nothing usable (missing data is tolerated)."""
    vals = [x for x in parts if x is not None and np.isfinite(x)]
    return float(np.mean(vals)) if vals else None


def _need(f) -> bool:
    return f is not None


class ValueAgent:
    name = "value"

    def analyse(self, ctx: Context) -> Signal:
        f = ctx.fundamentals
        if f is None:
            return Signal(self.name, ctx.ticker, 0.0, 0.0, "no fundamentals")
        parts = [_clip((15 - f.pe) / 10), _clip((2.5 - f.pb) / 2), _clip((f.fcf_yield - 0.04) / 0.04)]
        s = _mean(parts)
        if s is None:
            return Signal(self.name, ctx.ticker, 0.0, 0.0, "fundamentals unavailable")
        return Signal(self.name, ctx.ticker, s, 0.8,
                      f"PER {f.pe:.1f}, P/B {f.pb:.1f}, FCF yield {f.fcf_yield:.1%}")


class QualityAgent:
    name = "quality"

    def analyse(self, ctx: Context) -> Signal:
        f = ctx.fundamentals
        if f is None:
            return Signal(self.name, ctx.ticker, 0.0, 0.0, "no fundamentals")
        parts = [_clip((f.roe - 0.15) / 0.10), _clip((f.net_margin - 0.10) / 0.10),
                 _clip((2.5 - f.debt_ebitda) / 2.0)]
        s = _mean(parts)
        if s is None:
            return Signal(self.name, ctx.ticker, 0.0, 0.0, "fundamentals unavailable")
        return Signal(self.name, ctx.ticker, s, 0.8,
                      f"ROE {f.roe:.1%}, net margin {f.net_margin:.1%}, debt/EBITDA {f.debt_ebitda:.1f}x")


class GrowthAgent:
    name = "growth"

    def analyse(self, ctx: Context) -> Signal:
        f = ctx.fundamentals
        if f is None:
            return Signal(self.name, ctx.ticker, 0.0, 0.0, "no fundamentals")
        if not np.isfinite(f.rev_growth):
            return Signal(self.name, ctx.ticker, 0.0, 0.0, "fundamentals unavailable")
        s = _clip((f.rev_growth - 0.08) / 0.10)
        return Signal(self.name, ctx.ticker, s, 0.6, f"revenue growth {f.rev_growth:.1%}")


class MomentumAgent:
    """12-1 month momentum (skips the latest month to avoid short-term reversal)."""
    name = "momentum"

    def analyse(self, ctx: Context) -> Signal:
        p = ctx.prices.dropna()
        if len(p) < 253:
            return Signal(self.name, ctx.ticker, 0.0, 0.0, "not enough history")
        ret = p.iloc[-22] / p.iloc[-253] - 1
        return Signal(self.name, ctx.ticker, _clip(ret / 0.30), 0.7, f"12-1m return {ret:.1%}")


class TrendAgent:
    """Price versus its 200-day average (classic trend filter, price data only)."""
    name = "trend"

    def analyse(self, ctx: Context) -> Signal:
        p = ctx.prices.dropna()
        if len(p) < 200:
            return Signal(self.name, ctx.ticker, 0.0, 0.0, "not enough history")
        dev = p.iloc[-1] / p.iloc[-200:].mean() - 1
        return Signal(self.name, ctx.ticker, _clip(dev / 0.10), 0.7, f"{dev:+.1%} vs 200d average")


DEFAULT_AGENTS: list[Agent] = [ValueAgent(), QualityAgent(), GrowthAgent(), MomentumAgent(), TrendAgent()]


def risk_profile(prices: pd.Series) -> dict:
    """Risk inputs used for sizing and the drawdown veto (not a return signal)."""
    p = prices.dropna()
    if len(p) < 61:
        return {"vol": np.nan, "drawdown": np.nan}
    r = p.pct_change().dropna()
    vol = float(r.iloc[-60:].std() * np.sqrt(252))
    window = p.iloc[-252:]
    return {"vol": vol, "drawdown": float(window.iloc[-1] / window.max() - 1)}
