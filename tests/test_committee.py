import numpy as np
import pandas as pd

from committee.agents import DEFAULT_AGENTS, Context, MomentumAgent
from committee.backtest import run
from committee.data import asof, synthetic_market
from committee.live import snapshot_from_info
from committee.llm_agent import LLMAgent, parse_reply
from committee.portfolio import Config, composite_score, decide, weights_of

P, F, _ = synthetic_market(n_tickers=8, years=5, seed=3)


def test_signals_bounded():
    d = P.index[400]
    for dec in decide(P, F, d):
        for s in dec.signals:
            assert -1 <= s.score <= 1 and 0 <= s.confidence <= 1


def test_no_lookahead_in_decisions():
    d = P.index[600]
    base = weights_of(decide(P, F, d))
    P2 = P.copy(); P2.loc[P2.index > d] *= 5.0          # corrupt the future
    assert np.allclose(base.values, weights_of(decide(P2, F, d)).values)


def test_asof_uses_only_published_data():
    frame = F["SYN01"]; d = frame.index[2] - pd.Timedelta(days=1)
    assert asof(frame, d).equals(frame.iloc[1])
    assert asof(frame, frame.index[0] - pd.Timedelta(days=1)) is None


def test_weights_respect_cap_and_long_only():
    cfg = Config(max_position=0.2)
    w = weights_of(decide(P, F, P.index[700], cfg))
    assert (w >= 0).all() and (w <= 0.2 + 1e-9).all() and w.sum() <= 1 + 1e-9


def test_drawdown_veto_zeroes_weight():
    P2 = P.copy(); P2.loc[P2.index > P.index[690], "SYN02"] *= 0.4
    dec = {x.ticker: x for x in decide(P2, F, P2.index[700], Config())}
    assert dec["SYN02"].vetoed and dec["SYN02"].weight == 0


def test_momentum_needs_history():
    s = MomentumAgent().analyse(Context("X", P["SYN01"].iloc[:100], None))
    assert s.confidence == 0


def test_composite_ignores_zero_confidence():
    sigs = [type("S", (), dict(agent="a", score=1, confidence=0))(),
            type("S", (), dict(agent="b", score=0.5, confidence=1))()]
    assert composite_score(sigs, {}) == 0.5


def test_backtest_deterministic_and_costs_hurt():
    r1, r2 = run(P, F, cost_bps=10), run(P, F, cost_bps=10)
    assert r1.equity.equals(r2.equity)
    assert run(P, F, cost_bps=100).equity.iloc[-1] < run(P, F, cost_bps=0).equity.iloc[-1]


def test_backtest_equity_positive_and_aligned():
    r = run(P, F)
    assert (r.equity > 0).all() and r.equity.index.equals(r.benchmark.index)


# ---- real-data mapping and LLM agent (offline, injected) ----


def test_snapshot_mapping_and_missing_fields():
    s = snapshot_from_info({"trailingPE": 20, "priceToBook": 3, "marketCap": 1000, "freeCashflow": 50,
                            "totalDebt": 200, "ebitda": 100, "returnOnEquity": 0.2,
                            "profitMargins": 0.1, "revenueGrowth": 0.05})
    assert s["fcf_yield"] == 0.05 and s["debt_ebitda"] == 2.0
    e = snapshot_from_info({})
    assert all(np.isnan(v) for v in e.values())


def test_agents_tolerate_nan_fundamentals():
    f = pd.Series(dict(pe=np.nan, pb=np.nan, fcf_yield=np.nan, roe=np.nan, net_margin=np.nan,
                       debt_ebitda=np.nan, rev_growth=np.nan))
    for a in DEFAULT_AGENTS[:3]:
        s = a.analyse(Context("X", P["SYN01"], f))
        assert s.confidence == 0 and s.score == 0


def test_price_only_backtest_runs_without_fundamentals():
    r = run(P, {}, cost_bps=10)
    assert (r.equity > 0).all()


def test_llm_agent_parsing_clipping_and_failure():
    ctx = Context("X", P["SYN01"], F["SYN01"].iloc[-1])
    ok = LLMAgent(lambda _: 'sure: {"score": 3, "confidence": 0.9, "rationale": "ok"}').analyse(ctx)
    assert ok.score == 1 and ok.confidence == 0.5          # clipped, confidence capped
    assert LLMAgent(lambda _: "no json").analyse(ctx).confidence == 0
    def boom(_): raise RuntimeError("api down")
    assert "unavailable" in LLMAgent(boom).analyse(ctx).rationale
    assert parse_reply('{"score": "x", "confidence": 1}') is None
