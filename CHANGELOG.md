# Changelog

## 1.4.1
- `committee live --tickers ... [--llm]`: one command for live prices + fundamentals + decisions.
- `committee llm-check`: verifies the Anthropic key/SDK with one tiny request and explains failures (missing key, no credit, network) without ever printing the key.
- One-click scripts `run_live.bat/.sh` (hidden key prompt, key kept for that window only) and `docs/LLM_SETUP.md`.

## 1.4.0
- Real multi-asset ETF study (12 ETFs, 2001-2023, total returns and T-bill series) bundled in `data/real/`, report in `docs/real_world_etf/`.
- Fix: sub-period Sharpe now uses excess returns over the risk-free series, like the headline table (they were inconsistent).
- Report wording no longer hard-codes `^IRX` and states the cash assumption correctly when a risk-free series is supplied.
- Tests run the real Anthropic SDK against a local fake endpoint and check yfinance's multi-index output handling. Default model updated to `claude-sonnet-5-5`.

## 1.3.0
- `committee timing`: real-data study on 140 years of US equities (daily total-return index and risk-free series since 1885, bundled in `data/real/`): era split, stress windows (1929, 1973-74, 2000-02, 2008-09, 2020), decades, ablation (momentum vs trend), cost and threshold sensitivity, walk-forward, bootstrap interval. Report in `docs/real_world_us_equities/`.
- 41 tests.

## 1.2.0
- Walk-forward validation: parameters re-chosen each year on the previous 4 years only, applied out-of-sample; compared with the fixed default mandate (included in `committee study`).
- Real risk-free rate (`--rf`, e.g. Yahoo ^IRX): cash earns it, Sharpe/Sortino use excess returns; the one-click scripts download it.
- Signal cache: `analyse` (agents, mandate-independent) split from `allocate` (weights); sweeps reuse signals, study runs about 2x faster.
- Study degrades gracefully when history is too short for walk-forward. 38 tests.

## 1.1.0
- `committee study`: protocol-driven real-data study (benchmarks SPY and equal-weight, sub-periods, stress windows, cost sensitivity, parameter grid, block-bootstrap interval) with generated report; one-click `run_real_study.bat/.sh`.
- Trend agent (price vs 200-day average); price-only mode is now meaningful.
- Execution lag (default 1 trading day after the decision close), cash yield option, benchmark ticker option.
- Backtest handles late-listed assets (equal-weight basket no longer shrinks).
- 33 tests.

## 1.0.0
- Installable package (`pip install .`, `committee` command), `pyproject.toml`.
- Metrics: Sortino, Calmar, beta, annualised alpha, tracking error, information ratio, monthly hit rate, calendar-year returns, per-ticker contribution.
- Parameter sensitivity grid (entry threshold x position cap).
- `committee report`: markdown report with charts, generated from any run.
- Tamper-evident paper-trading ledger (`paper`, `verify`, `performance`), hash-chained.
- JSON mandate (`--config`) with strict validation; config fingerprint recorded in reports and ledger.
- Input validation for price files; clean CLI errors (exit codes 0/1/2).
- Real prices (yfinance) and optional LLM analyst, both excluded from backtests by design.
- 27 tests, ruff, CI.

## 0.x
Prototype: four agents, portfolio rules, monthly backtest on synthetic data.
