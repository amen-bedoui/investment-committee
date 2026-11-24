import json
import warnings

import numpy as np
import pandas as pd
import pytest

from committee import ledger
from committee.backtest import metrics, relative_metrics, run, sensitivity
from committee.cli import main
from committee.data import synthetic_market, validate_prices
from committee.portfolio import Config, decide

P, F, _ = synthetic_market(n_tickers=8, years=5, seed=3)


# ---- configuration ----
def test_config_roundtrip_and_unknown_key(tmp_path):
    good = tmp_path / "m.json"; good.write_text(json.dumps({"min_score": 0.2, "weights": {"value": 2}}))
    c = Config.from_json(str(good))
    assert c.min_score == 0.2 and c.weights["value"] == 2 and c.weights["quality"] == 1.0
    bad = tmp_path / "b.json"; bad.write_text(json.dumps({"min_scor": 0.2}))
    with pytest.raises(ValueError, match="unknown"):
        Config.from_json(str(bad))
    worse = tmp_path / "w.json"; worse.write_text(json.dumps({"max_position": 1.5}))
    with pytest.raises(ValueError):
        Config.from_json(str(worse))


def test_fingerprint_changes_with_config():
    assert Config().fingerprint() == Config().fingerprint()
    assert Config().fingerprint() != Config(min_score=0.3).fingerprint()


# ---- data validation ----
def test_validation_rejects_bad_prices():
    ok = P.copy()
    with pytest.raises(ValueError, match="non-positive"):
        neg = ok.copy(); neg.iloc[5, 0] = -1.0
        validate_prices(neg)
    with pytest.raises(ValueError, match="duplicate"):
        validate_prices(pd.concat([ok.iloc[:3], ok.iloc[:3]]).sort_index())
    with pytest.raises(ValueError, match="no data"):
        validate_prices(ok.assign(SYN01=np.nan))
    spike = ok.copy(); spike.iloc[10, 0] *= 3
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always"); validate_prices(spike)
    assert any("60%" in str(x.message) for x in w)


# ---- metrics ----
def test_metrics_known_values():
    idx = pd.bdate_range("2020-01-01", periods=253)
    flat = pd.Series(1.0, index=idx)
    up = pd.Series(np.linspace(1, 1.1, 253), index=idx)
    assert metrics(up)["CAGR"] > 0.09 and metrics(up)["MaxDD"] == 0
    rel = relative_metrics(up * 1.0, flat + 1e-9 * np.arange(253))
    assert set(rel) >= {"Beta", "Alpha (ann.)", "Information ratio", "Monthly hit rate"}


def test_beta_of_benchmark_against_itself_is_one():
    r = run(P, F)
    assert relative_metrics(r.benchmark, r.benchmark)["Beta"] == pytest.approx(1.0)


def test_annual_and_attribution_shapes():
    r = run(P, F)
    assert list(r.annual.columns) == ["Committee", "Benchmark"]
    assert set(r.contribution.index) == set(P.columns)
    assert (r.weights.sum(axis=1) <= 1 + 1e-9).all() and len(r.weights) == len(r.turnover_series)


def test_run_requires_history():
    with pytest.raises(ValueError, match="not enough history"):
        run(P.iloc[:200], F)


def test_sensitivity_grid_complete():
    s = sensitivity(P, F, min_scores=(0.0, 0.2), caps=(0.2, 0.3))
    assert len(s) == 4 and s["Sharpe"].notna().all()


# ---- ledger ----
def _entry(path, i):
    d = P.index[400 + 30 * i]
    return ledger.append(path, decide(P, F, d, Config()), d, Config())


def test_ledger_chain_and_verify(tmp_path):
    p = str(tmp_path / "l.jsonl")
    for i in range(3):
        _entry(p, i)
    ok, msg = ledger.verify(p)
    assert ok and "3 sessions" in msg


def test_ledger_detects_edit_and_deletion(tmp_path):
    p = str(tmp_path / "l.jsonl")
    for i in range(3):
        _entry(p, i)
    lines = open(p).read().splitlines()
    edited = json.loads(lines[1]); edited["weights"] = {"SYN01": 1.0}
    open(p, "w").write("\n".join([lines[0], json.dumps(edited, sort_keys=True), lines[2]]) + "\n")
    ok, msg = ledger.verify(p)
    assert not ok and "entry 2" in msg
    open(p, "w").write("\n".join([lines[0], lines[2]]) + "\n")      # delete the middle session
    assert not ledger.verify(p)[0]


def test_ledger_rejects_non_increasing_dates(tmp_path):
    p = str(tmp_path / "l.jsonl")
    _entry(p, 1)
    with pytest.raises(ValueError, match="already has"):
        _entry(p, 0)


def test_ledger_performance(tmp_path):
    p = str(tmp_path / "l.jsonl")
    for i in range(3):
        _entry(p, i)
    perf = ledger.performance(p, P)
    assert len(perf) == 3 and (perf["nav"] > 0).all()


# ---- CLI end to end ----
def test_cli_report_and_paper_flow(tmp_path, capsys):
    out = tmp_path / "rep"
    assert main(["report", "--out", str(out), "--seed", "3"]) == 0
    assert (out / "report.md").exists() and (out / "equity.png").exists()
    text = (out / "report.md").read_text()
    assert "Synthetic data" in text and "Sensitivity" in text
    pr, fu = tmp_path / "p.csv", tmp_path / "f.csv"
    P.rename_axis("date").to_csv(pr); _.to_csv(fu, index=False)
    led = tmp_path / "led.jsonl"
    assert main(["paper", "--prices", str(pr), "--fundamentals", str(fu), "--ledger", str(led)]) == 0
    assert main(["verify", "--ledger", str(led)]) == 0
    led.write_text(led.read_text().replace('"seq": 1', '"seq": 7'))
    assert main(["verify", "--ledger", str(led)]) == 1


def test_cli_reports_errors_cleanly(tmp_path, capsys):
    assert main(["analyze", "--prices", str(tmp_path / "missing.csv")]) == 2
    assert "error:" in capsys.readouterr().err


# ---- v1.1: lag, ragged data, benchmark ticker, cash yield, trend, study ----
def test_trend_agent_bounded_and_needs_history():
    from committee.agents import Context, TrendAgent
    assert TrendAgent().analyse(Context("X", P["SYN01"].iloc[:100], None)).confidence == 0
    s = TrendAgent().analyse(Context("X", P["SYN01"], None))
    assert -1 <= s.score <= 1 and s.confidence > 0


def test_exec_lag_changes_dates_not_validity():
    a, b = run(P, F, Config(exec_lag=0)), run(P, F, Config(exec_lag=1))
    assert not a.equity.equals(b.equity) and (b.equity > 0).all()
    with pytest.raises(ValueError):
        Config(exec_lag=9).validate()


def test_ragged_history_equal_weight_not_shrunk():
    Q = P.copy(); Q.loc[Q.index[:400], "SYN08"] = np.nan      # asset listed late
    r = run(Q, F)
    flat = Q.copy(); flat.iloc[:, :] = 100.0                   # flat market: benchmark must stay at 1
    assert run(flat, {}, Config()).benchmark.round(9).eq(1.0).all()
    assert r.benchmark.iloc[0] == 1.0 and (r.benchmark > 0.5).all()


def test_benchmark_ticker_and_validation():
    r = run(P, F, benchmark="SYN01")
    assert r.bench_label == "SYN01"
    with pytest.raises(ValueError):
        run(P, F, benchmark="NOPE")


def test_cash_rate_helps_when_in_cash():
    flat = P.copy(); flat.iloc[:, :] = 100.0
    base = run(flat, {}, Config(cash_rate=0.0)).equity.iloc[-1]
    paid = run(flat, {}, Config(cash_rate=0.05)).equity.iloc[-1]
    assert base == pytest.approx(1.0) and paid > 1.1


def test_study_bundle_is_json_serialisable_and_renders(tmp_path):
    import json

    from committee.study import run_study
    from committee.study_report import headline, render
    b = run_study(P, Config(), bench="SYN01", costs=(0.0, 10.0), grid=False)
    json.dumps(b)
    assert set(b["metrics"]) == {"Committee", "SYN01", "Equal-weight"} and b["bootstrap"]["SYN01"]["months"] > 12
    assert b["meta"]["source"] == "user-supplied prices CSV" and "Annualised excess return" in headline(b)
    path = render(b, str(tmp_path))
    assert (tmp_path / "equity.png").exists() and "Protocol" in open(path).read()


# ---- v1.2: signal cache, risk-free, walk-forward ----
def test_cache_gives_identical_results_and_is_filled():
    cache: dict = {}
    a, b = run(P, F, cache=cache), run(P, F)
    assert a.equity.equals(b.equity) and len(cache) > 20
    c = run(P, F, Config(min_score=0.3), cache=cache)           # reuse across a different mandate
    assert c.equity.equals(run(P, F, Config(min_score=0.3)).equity)


def test_rf_series_pays_cash_and_lowers_sharpe():
    from committee.data import load_rf
    flat = P.copy(); flat.iloc[:, :] = 100.0
    rf = pd.Series(0.05, index=flat.index)
    paid = run(flat, {}, rf=rf).equity.iloc[-1]
    assert paid > 1.1
    r0, r1 = run(P, F), run(P, F, rf=pd.Series(0.04, index=P.index))
    assert r1.metrics["Sharpe"] < r0.metrics["Sharpe"] or r1.metrics["CAGR"] > r0.metrics["CAGR"]
    assert callable(load_rf)


def test_load_rf_parses_percent_and_rejects_nonsense(tmp_path):
    from committee.data import load_rf
    ok = tmp_path / "rf.csv"; ok.write_text("date,^IRX\n2020-01-01,1.5\n2020-01-02,1.6\n")
    assert load_rf(str(ok)).iloc[0] == pytest.approx(0.015)
    bad = tmp_path / "bad.csv"; bad.write_text("date,x\n2020-01-01,150\n")
    with pytest.raises(ValueError):
        load_rf(str(bad))


def test_walk_forward_structure_and_no_lookahead():
    from committee.walkforward import walk_forward
    Pl, Fl, _ = synthetic_market(n_tickers=8, years=9, seed=4)
    wf = walk_forward(Pl, Fl, train_years=3, min_scores=(0.0, 0.2), caps=(0.2, 0.3))
    assert wf["n_folds"] >= 3 and np.isfinite(wf["adaptive"]["CAGR"])
    first = wf["folds"][0]
    # corrupt everything after the end of the first test window: the first fold's choice must not change
    cut = pd.Timestamp(first["end"])
    Pc = Pl.copy(); Pc.loc[Pc.index > cut] *= 3.0
    wf2 = walk_forward(Pc, Fl, train_years=3, min_scores=(0.0, 0.2), caps=(0.2, 0.3))
    pick = lambda f: (f["min_score"], f["max_position"])  # noqa: E731
    assert pick(wf2["folds"][0]) == pick(first)
    assert wf2["folds"][0]["oos_return"] == pytest.approx(first["oos_return"])


def test_study_includes_walk_forward_and_valid_json(tmp_path):
    import json

    from committee.study import run_study
    from committee.study_report import render
    Pl, _, _ = synthetic_market(n_tickers=8, years=9, seed=4)
    b = run_study(Pl, Config(), bench="SYN01", costs=(10.0,), grid=False,
                  rf=pd.Series(0.02, index=Pl.index))
    json.dumps(b, allow_nan=False)
    assert b["walk_forward"]["n_folds"] >= 3 and b["meta"]["rf"] is True
    assert "walk-forward" in open(render(b, str(tmp_path))).read()


# ---- v1.3: long-history timing study ----
def test_timing_study_on_short_synthetic_series(tmp_path):
    from committee.timing_study import ASSET, load_us_market, run_timing_study
    Ps, _, _ = synthetic_market(n_tickers=1, years=14, seed=2)
    prices = Ps.rename(columns={"SYN01": ASSET})
    rf = pd.Series(0.03, index=prices.index)
    out = run_timing_study(prices, rf, str(tmp_path))
    text = open(out["report"]).read()
    assert "Walk-forward" in text and "Protocol" in text and out["walk_forward"]["n_folds"] >= 1
    assert (tmp_path / "equity.png").exists() and callable(load_us_market)


def test_load_us_market_validates_format(tmp_path):
    from committee.timing_study import load_us_market
    bad = tmp_path / "bad.csv"; bad.write_text("Date,Close\n2020-01-01,1\n")
    with pytest.raises(ValueError, match="unexpected format"):
        load_us_market(str(bad))
    ok = tmp_path / "ok.csv"
    ok.write_text("Date,Adjusted Close,Risk Free Rate\n2020-01-01,1.0,2.0\n2020-01-02,1.01,2.0\n")
    prices, rf = load_us_market(str(ok))
    assert list(prices.columns) == ["US_EQUITY"] and rf.iloc[0] == pytest.approx(0.02)


def test_single_asset_mandate_is_all_or_nothing():
    from committee.timing_study import MANDATE
    one = P[["SYN01"]]
    w = run(one, {}, MANDATE).weights["SYN01"]
    assert set(np.round(w.unique(), 6)) <= {0.0, 1.0}


def test_anthropic_ask_against_local_server_with_real_sdk(monkeypatch):
    """Runs the real Anthropic SDK against a local fake /v1/messages endpoint (no network, no key)."""
    import json as _json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    import pytest
    pytest.importorskip("anthropic")
    seen = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["path"] = self.path
            seen["body"] = _json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            text = '{"score": 0.4, "confidence": 0.9, "rationale": "ok"}'
            out = _json.dumps({"id": "msg_1", "type": "message", "role": "assistant", "model": "m",
                               "content": [{"type": "text", "text": text}],
                               "stop_reason": "end_turn", "stop_sequence": None,
                               "usage": {"input_tokens": 1, "output_tokens": 1}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("ANTHROPIC_BASE_URL", f"http://127.0.0.1:{srv.server_port}")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from committee.llm_agent import anthropic_ask, parse_reply
    reply = anthropic_ask()("Rate this stock")
    srv.shutdown()
    assert seen["path"] == "/v1/messages" and seen["body"]["messages"][0]["content"] == "Rate this stock"
    assert parse_reply(reply)[0] == 0.4


def test_fetch_prices_handles_yfinance_multiindex(monkeypatch):
    import numpy as np
    import pandas as pd

    from committee import live
    idx = pd.date_range("2024-01-01", periods=5)
    cols = pd.MultiIndex.from_product([["Close", "Volume"], ["SPY", "TLT"]])
    fake = pd.DataFrame(np.arange(20, dtype=float).reshape(5, 4), index=idx, columns=cols)

    class FakeYF:
        @staticmethod
        def download(tickers, **kw):
            assert kw["auto_adjust"] is True
            return fake
    monkeypatch.setattr(live, "_yf", lambda: FakeYF)
    out = live.fetch_prices(["SPY", "TLT"])
    assert list(out.columns) == ["SPY", "TLT"] and len(out) == 5


def _fake_anthropic(monkeypatch, text):
    import json as _json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            out = _json.dumps({"id": "m", "type": "message", "role": "assistant", "model": "m",
                               "content": [{"type": "text", "text": text}], "stop_reason": "end_turn",
                               "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("ANTHROPIC_BASE_URL", f"http://127.0.0.1:{srv.server_port}")
    return srv


def test_llm_check_messages_and_success(monkeypatch, capsys):
    import pytest
    pytest.importorskip("anthropic")
    from committee.cli import main
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert main(["llm-check"]) == 2
    assert "ANTHROPIC_API_KEY is not set" in capsys.readouterr().err
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-xyz")
    srv = _fake_anthropic(monkeypatch, '{"score": 0.1, "confidence": 0.5, "rationale": "x"}')
    assert main(["llm-check"]) == 0
    srv.shutdown()
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9")  # nothing listens: network failure
    assert main(["llm-check"]) == 2
    err = capsys.readouterr().err
    assert "request failed" in err and "sk-ant-secret-xyz" not in err


def test_live_command_with_llm_and_stubbed_yahoo(monkeypatch, capsys):
    import pytest
    pytest.importorskip("anthropic")
    from committee import live
    from committee.cli import main
    from committee.data import synthetic_market
    prices = synthetic_market(seed=3)[0]
    monkeypatch.setattr(live, "fetch_prices", lambda tickers, start="2015-01-01": prices)
    monkeypatch.setattr(live, "fetch_snapshot", lambda tickers, on=None: {})
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    srv = _fake_anthropic(monkeypatch, '{"score": 0.3, "confidence": 0.9, "rationale": "fine"}')
    assert main(["live", "--tickers", "AAA", "--llm"]) == 0
    srv.shutdown()
    out = capsys.readouterr().out
    assert "snapshot" in out and "llm" in out.lower()
