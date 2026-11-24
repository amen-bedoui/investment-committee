"""Portfolio manager: aggregates signals, applies risk rules, outputs weights."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, fields

import numpy as np
import pandas as pd

from .agents import DEFAULT_AGENTS, Agent, Context, Signal, risk_profile
from .data import asof


@dataclass
class Config:
    weights: dict = field(default_factory=lambda: {
        "value": 1.0, "quality": 1.0, "growth": 0.5, "momentum": 1.0, "trend": 1.0})
    min_score: float = 0.10        # minimum composite score to be invested
    max_position: float = 0.25     # cap per name
    max_drawdown_veto: float = -0.30  # veto names more than 30 % below their 1y high
    target_vol_floor: float = 0.05    # avoids division blow-ups for very calm names
    cost_bps: float = 10.0            # one-way transaction cost on turnover
    cash_rate: float = 0.0            # annual yield on uninvested cash (0 = conservative)
    exec_lag: int = 1                 # trading days between decision (close) and execution (close)

    @classmethod
    def from_json(cls, path: str) -> "Config":
        """Load a mandate file; unknown keys are rejected so typos never pass silently."""
        with open(path) as fh:
            raw = json.load(fh)
        unknown = set(raw) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"unknown config keys: {sorted(unknown)}")
        base = cls()
        base.weights = {**base.weights, **raw.pop("weights", {})}
        for k, v in raw.items():
            setattr(base, k, v)
        base.validate()
        return base

    def validate(self) -> None:
        if not 0 < self.max_position <= 1:
            raise ValueError("max_position must be in (0, 1]")
        if not -1 < self.max_drawdown_veto < 0:
            raise ValueError("max_drawdown_veto must be in (-1, 0)")
        if self.cost_bps < 0 or self.cash_rate < 0:
            raise ValueError("cost_bps and cash_rate must be >= 0")
        if self.exec_lag not in (0, 1, 2, 3, 4, 5):
            raise ValueError("exec_lag must be an integer between 0 and 5")

    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:12]


@dataclass
class Decision:
    ticker: str
    composite: float
    weight: float
    vetoed: bool
    signals: list[Signal]
    vol: float
    drawdown: float


def composite_score(signals: list[Signal], weights: dict) -> float:
    num = sum(weights.get(s.agent, 1.0) * s.confidence * s.score for s in signals)
    den = sum(weights.get(s.agent, 1.0) * s.confidence for s in signals)
    return float(num / den) if den > 0 else 0.0


Analysis = tuple  # (ticker, list[Signal], risk dict) for one asset on one date


def analyse(prices: pd.DataFrame, fundamentals: dict, date: pd.Timestamp, agents: list[Agent] | None = None) -> list:
    """Run every agent on every asset using only data available on `date`. Independent of the mandate,
    so it can be computed once and re-used across parameter sweeps (see `cache` in backtest.run)."""
    agents = agents or DEFAULT_AGENTS
    hist = prices.loc[:date]
    out = []
    for t in prices.columns:
        ph = hist[t]
        f = asof(fundamentals[t], date) if t in fundamentals else None
        ctx = Context(t, ph, f)
        out.append((t, [a.analyse(ctx) for a in agents], risk_profile(ph)))
    return out


def allocate(analyses: list, cfg: Config | None = None) -> list[Decision]:
    """Aggregate signals into target weights under the mandate (cheap, pure function)."""
    cfg = cfg or Config()
    out: list[Decision] = []
    for t, sigs, risk in analyses:
        comp = composite_score(sigs, cfg.weights)
        veto = bool(np.isfinite(risk["drawdown"]) and risk["drawdown"] < cfg.max_drawdown_veto)
        out.append(Decision(t, comp, 0.0, veto, sigs, risk["vol"], risk["drawdown"]))
    eligible = [d for d in out if d.composite >= cfg.min_score and not d.vetoed and np.isfinite(d.vol)]
    raw = {d.ticker: d.composite / max(d.vol, cfg.target_vol_floor) for d in eligible}
    total = sum(raw.values())
    if total > 0:
        w = {t: v / total for t, v in raw.items()}
        for _ in range(10):  # iterative cap; the excess stays in cash
            if not any(x > cfg.max_position for x in w.values()):
                break
            w = {t: min(x, cfg.max_position) for t, x in w.items()}
        for d in out:
            d.weight = w.get(d.ticker, 0.0)
    return out


def decide(prices: pd.DataFrame, fundamentals: dict, date: pd.Timestamp,
           cfg: Config | None = None, agents: list[Agent] | None = None) -> list[Decision]:
    """Decisions at `date` using only information available on that date."""
    return allocate(analyse(prices, fundamentals, date, agents), cfg)


def weights_of(decisions: list[Decision]) -> pd.Series:
    return pd.Series({d.ticker: d.weight for d in decisions})
