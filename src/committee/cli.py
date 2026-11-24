"""Command line interface: `committee <command>`."""
from __future__ import annotations

import argparse
import json
import sys

from . import ledger
from .agents import DEFAULT_AGENTS
from .backtest import run
from .data import load_fundamentals, load_prices, load_rf, synthetic_market
from .portfolio import Config, decide

DISCLAIMER = ("Educational research tool. Not investment advice. No orders are ever placed. "
              "Results on synthetic data say nothing about real markets.")


def _table(decisions) -> str:
    head = "ticker   score  weight  veto  " + "  ".join(f"{s.agent:>8}" for s in decisions[0].signals)
    rows = [head]
    for d in sorted(decisions, key=lambda x: -x.composite):
        rows.append(f"{d.ticker:<8} {d.composite:+.2f}  {d.weight:6.1%}  {'yes' if d.vetoed else ' no'}  "
                    + "  ".join(f"{s.score:+8.2f}" for s in d.signals))
    return "\n".join(rows)


def _summary(res) -> str:
    def line(name, m):
        return (f"{name:<12} CAGR {m['CAGR']:+.1%}  Vol {m['Vol']:.1%}  Sharpe {m['Sharpe']:.2f}  "
                f"Sortino {m['Sortino']:.2f}  MaxDD {m['MaxDD']:.1%}  Calmar {m['Calmar']:.2f}")
    r = res.relative
    return "\n".join([line("Committee", res.metrics), line("Equal-weight", res.bench_metrics),
                      f"Beta {r['Beta']:.2f}  Alpha {r['Alpha (ann.)']:+.1%}  Info ratio "
                      f"{r['Information ratio']:.2f}  Monthly hit rate {r['Monthly hit rate']:.0%}  "
                      f"Turnover {res.turnover:.1%}/month"])


def _data(a):
    if a.cmd in ("demo", "report") and not getattr(a, "prices", None):
        prices, fund, _ = synthetic_market(seed=a.seed)
        return prices, fund, True
    prices = load_prices(a.prices)
    fund = load_fundamentals(a.fundamentals) if getattr(a, "fundamentals", None) else {}
    if getattr(a, "live", False):
        from .live import fetch_snapshot
        fund = fetch_snapshot(list(prices.columns))
    return prices, fund, False


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="committee", description=DISCLAIMER)
    sub = ap.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="download real adjusted-close prices (pip install .[live])")
    f.add_argument("--tickers", nargs="+", required=True)
    f.add_argument("--start", default="2015-01-01")
    f.add_argument("--out", required=True)

    st = sub.add_parser("study", help="full empirical study on a real prices CSV (benchmark + robustness)")
    st.add_argument("--prices", required=True)
    st.add_argument("--benchmark", default="SPY")
    st.add_argument("--config")
    st.add_argument("--out", default="study")
    st.add_argument("--rf", help="risk-free CSV (date + annual %% rate, e.g. ^IRX): cash earns it")
    st.add_argument("--source", default="user-supplied prices CSV", help="data provenance printed in the report")

    tm = sub.add_parser("timing", help="long-history real-data study (US equities since 1885)")
    tm.add_argument("--data", default="data/real/us_market_data.csv", help="CSV from SteelCerberus/us-market-data")
    tm.add_argument("--out", default="timing_study")

    lv = sub.add_parser("live", help="one command: fetch live prices + fundamentals, show decisions (needs yfinance)")
    lv.add_argument("--tickers", nargs="+", required=True)
    lv.add_argument("--start", default="2020-01-01")
    lv.add_argument("--config")
    lv.add_argument("--llm", action="store_true", help="add the Claude analyst (needs ANTHROPIC_API_KEY)")

    sub.add_parser("llm-check", help="check that your Anthropic API key and the SDK work (one tiny request)")

    v = sub.add_parser("verify", help="check a paper-trading ledger's integrity")
    v.add_argument("--ledger", required=True)

    for name, helptext in (("demo", "run on a synthetic market"), ("analyze", "decisions for the latest date"),
                           ("backtest", "historical replay"), ("report", "backtest + markdown report"),
                           ("paper", "append today's decisions to the ledger"),
                           ("performance", "realised performance of the ledger")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--prices", required=name not in ("demo", "report"))
        p.add_argument("--fundamentals", help="dated fundamentals CSV (price-only if omitted)")
        p.add_argument("--config", help="JSON mandate (see examples/mandate.json)")
        p.add_argument("--seed", type=int, default=7, help="synthetic market seed")
        if name in ("analyze", "paper"):
            p.add_argument("--live", action="store_true", help="current fundamentals snapshot (not point-in-time)")
        if name == "analyze":
            p.add_argument("--llm", action="store_true", help="add an LLM analyst (pip install .[llm])")
        if name == "report":
            p.add_argument("--out", default="report")
        if name in ("paper", "performance"):
            p.add_argument("--ledger", required=True)
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    try:
        return _run(a)
    except (ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


def _llm_check() -> int:
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. Create a key at console.anthropic.com, then set it for this window:\n"
              '  Windows PowerShell:  $env:ANTHROPIC_API_KEY = "sk-ant-..."\n'
              '  Mac/Linux:           export ANTHROPIC_API_KEY="sk-ant-..."', file=sys.stderr)
        return 2
    try:
        from .llm_agent import anthropic_ask, parse_reply
    except ImportError:
        print("The anthropic package is missing: pip install \".[llm]\"", file=sys.stderr)
        return 2
    try:
        reply = anthropic_ask()('Reply with exactly this JSON and nothing else: '
                                '{"score": 0.1, "confidence": 0.5, "rationale": "connection test"}')
    except ImportError:
        print("The anthropic package is missing: pip install \".[llm]\"", file=sys.stderr)
        return 2
    except Exception as e:  # SDK errors: bad key, no credit, network
        print(f"The request failed ({type(e).__name__}): {str(e)[:300]}\n"
              "Typical causes: wrong key, no credit on console.anthropic.com > Billing, or no internet.",
              file=sys.stderr)
        return 2
    ok = parse_reply(reply) is not None
    print("OK: the API key works and the analyst's answer was understood." if ok else
          f"The key works but the answer was not in the expected format: {reply[:120]!r}")
    return 0 if ok else 2


def _run(a) -> int:
    print(DISCLAIMER + "\n")
    if a.cmd == "fetch":
        from .live import fetch_prices
        fetch_prices(a.tickers, a.start).rename_axis("date").to_csv(a.out)
        print(f"saved {a.out}")
        return 0
    if a.cmd == "llm-check":
        return _llm_check()
    if a.cmd == "live":
        from .live import fetch_prices, fetch_snapshot
        cfg = Config.from_json(a.config) if a.config else Config()
        prices = fetch_prices(a.tickers, a.start)
        fund = fetch_snapshot(list(prices.columns))
        agents = list(DEFAULT_AGENTS)
        if a.llm:
            from .llm_agent import LLMAgent, anthropic_ask
            agents.append(LLMAgent(anthropic_ask()))
        print(f"Data to {prices.index[-1].date()}; fundamentals are today's snapshot (not point-in-time).\n")
        print(_table(decide(prices, fund, prices.index[-1], cfg, agents)))
        return 0
    if a.cmd == "verify":
        ok, msg = ledger.verify(a.ledger)
        print(("OK: " if ok else "FAILED: ") + msg)
        return 0 if ok else 1

    if a.cmd == "timing":
        from .timing_study import load_us_market, run_timing_study
        prices, rf = load_us_market(a.data)
        out = run_timing_study(prices, rf, a.out)
        print(out["headline"], "\n\nreport written:", out["report"])
        return 0
    if a.cmd == "study":
        from .study import run_study
        from .study_report import render
        cfg = Config.from_json(a.config) if a.config else Config()
        bundle = run_study(load_prices(a.prices), cfg, a.benchmark, source=a.source,
                           rf=load_rf(a.rf) if a.rf else None)
        path = render(bundle, a.out)
        with open(f"{a.out}/bundle.json", "w") as fh:
            json.dump(bundle, fh)
        print("report written:", path, "(numbers: bundle.json)")
        return 0
    cfg = Config.from_json(a.config) if a.config else Config()
    prices, fund, synthetic = _data(a)
    if not fund and a.cmd != "demo":
        print("No fundamentals: price-only mode (momentum + risk rules).\n")
    agents = list(DEFAULT_AGENTS)
    if a.cmd == "analyze" and a.llm:
        from .llm_agent import LLMAgent, anthropic_ask
        agents.append(LLMAgent(anthropic_ask()))

    if a.cmd in ("demo", "analyze"):
        print(_table(decide(prices, fund, prices.index[-1], cfg, agents)), "\n")
    if a.cmd in ("demo", "backtest"):
        print(_summary(run(prices, fund, cfg)))
    if a.cmd == "report":
        from .report import build
        res = run(prices, fund, cfg)
        print(_summary(res))
        title = "Investment committee: backtest report" + (" (synthetic data)" if synthetic else "")
        print("\nreport written:", build(res, prices, fund, cfg, a.out, title, synthetic))
    if a.cmd == "paper":
        e = ledger.append(a.ledger, decide(prices, fund, prices.index[-1], cfg, agents), prices.index[-1], cfg)
        print(f"session {e['seq']} recorded for {e['date']}: {len(e['weights'])} positions, hash {e['hash'][:12]}")
    if a.cmd == "performance":
        ok, msg = ledger.verify(a.ledger)
        print(("OK: " if ok else "WARNING: ") + msg)
        print(ledger.performance(a.ledger, prices).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
