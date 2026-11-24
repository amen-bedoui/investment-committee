"""Optional LLM analyst (qualitative second opinion).

Not used in backtests: a language model may have seen the future of any
historical date, so its signals cannot be replayed without look-ahead, and its
outputs are not deterministic. Use it for live `analyze` only.

The model call is injected (`ask: Callable[[str], str]`) so the agent is
testable offline. `anthropic_ask` builds one from the Anthropic SDK.
"""
from __future__ import annotations

import json
import re
from typing import Callable

import numpy as np

from .agents import Context, Signal

PROMPT = """You are an equity analyst on an investment committee. Educational exercise, not advice.
Ticker: {ticker}
Fundamentals (may be missing): {fund}
Price stats: last={last:.2f}, 12m return={ret12}.
Answer with ONLY a JSON object:
{{"score": number in [-1,1], "confidence": number in [0,1], "rationale": "one sentence"}}.
Base the answer on the numbers above; if they are insufficient, use confidence 0."""


def anthropic_ask(model: str = "claude-sonnet-5-5", max_tokens: int = 300) -> Callable[[str], str]:
    """Build `ask` from the Anthropic SDK (needs `pip install anthropic` and ANTHROPIC_API_KEY)."""
    import anthropic
    client = anthropic.Anthropic()

    def ask(prompt: str) -> str:
        msg = client.messages.create(model=model, max_tokens=max_tokens,
                                     messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    return ask


def parse_reply(text: str):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        score, conf = float(d["score"]), float(d["confidence"])
    except (ValueError, KeyError, TypeError):
        return None
    if not (np.isfinite(score) and np.isfinite(conf)):
        return None
    return float(np.clip(score, -1, 1)), float(np.clip(conf, 0, 1)), str(d.get("rationale", ""))[:200]


class LLMAgent:
    name = "llm"

    def __init__(self, ask: Callable[[str], str], max_confidence: float = 0.5):
        self.ask, self.cap = ask, max_confidence   # capped so it can't dominate quantitative agents

    def analyse(self, ctx: Context) -> Signal:
        p = ctx.prices.dropna()
        ret = f"{p.iloc[-1] / p.iloc[-253] - 1:.1%}" if len(p) >= 253 else "n/a"
        fund = ctx.fundamentals.round(4).to_dict() if ctx.fundamentals is not None else "n/a"
        try:
            parsed = parse_reply(self.ask(PROMPT.format(ticker=ctx.ticker, fund=fund,
                                                        last=float(p.iloc[-1]), ret12=ret)))
        except Exception as e:  # network/API failure must never crash a run
            return Signal(self.name, ctx.ticker, 0.0, 0.0, f"LLM unavailable ({type(e).__name__})")
        if parsed is None:
            return Signal(self.name, ctx.ticker, 0.0, 0.0, "unparseable LLM reply")
        s, c, why = parsed
        return Signal(self.name, ctx.ticker, s, min(c, self.cap), why)
