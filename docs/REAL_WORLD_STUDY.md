# Real-world study protocols

There are two studies. **Study A (done, reproducible offline):** `committee timing` on 140 years of US equities, bundled data in `data/real/`, report in `docs/real_world_us_equities/`. **Study B (run on your machine):** the multi-asset ETF study below, which needs Yahoo access.

## Study A: US equities since 1885 (single asset, timing overlay)
Fixed in advance: momentum (12-1 month) and trend (200-day) agents, default entry score 0.10, -30 % drawdown veto, 10 bps one-way cost, decision at month-end close and execution one trading day later, 100 % position cap (single asset), cash earning the source's risk-free series. Primary era 1962-2025 (highest data quality); other eras, stress windows, decades, ablation, cost and threshold sensitivity, walk-forward and a block-bootstrap interval are all reported whatever the outcome. Data caveats are listed in `data/real/SOURCE.md`.

# Study B protocol (ETF universe)
**Done on bundled data (2001-2023)** with `committee study --prices data/real/etf_total_return.csv --rf data/real/rf_tbill.csv --benchmark SPY --out docs/real_world_etf`. The script below re-runs it on fresh Yahoo data up to today.


The synthetic data proves the plumbing; this study asks the real question: does the committee add value on real prices?

## How to run (one command)
- Windows: double-click `run_real_study.bat` (or run it in a terminal from the project folder).
- macOS/Linux: `./run_real_study.sh`

It installs the package, downloads 19 ETFs from Yahoo Finance (adjusted close, 2005 to today), runs the study and writes `real_study/report.md` with charts and `real_study/bundle.json` (all numbers).

## Protocol, fixed before any result was seen
- **Universe**: SPY, QQQ, IWM, EFA, EEM, TLT, IEF, LQD, GLD, VNQ and the nine sector SPDRs (XLK, XLF, XLE, XLV, XLY, XLP, XLI, XLU, XLB). Chosen for breadth and for being listed before the sample starts: no survivorship in membership, no point-in-time fundamentals needed.
- **Agents**: momentum (12-1 month) and trend (price vs 200-day average). Value, quality and growth abstain.
- **Mandate**: the default `Config`, untouched: entry score 0.10, 25 % cap, -30 % drawdown veto, monthly rebalance, 10 bps one-way cost, decisions at the close and execution one trading day later, cash earning the 13-week T-bill rate (^IRX).
- **Benchmarks**: SPY buy-and-hold and the equal-weight basket.
- **Reported whatever the outcome**: walk-forward out-of-sample track record, full sample, two halves, three stress windows (2007-09, COVID 2020, 2022), calendar years, cost sensitivity (0 to 50 bps), parameter grid, and a block-bootstrap interval for the excess return.
- **No tuning**: no parameter is changed after seeing the result. A change would be a new, labelled study.

## How to read the output
- The headline sentence is generated from the numbers, including whether the excess return is statistically distinguishable from zero. With about twenty years of monthly data, an interval that includes zero is the normal outcome for most strategies, and it is the honest one to report.
- Tactical trend/momentum rules often show a *smaller drawdown* rather than a higher return. Judge the stress windows and Calmar ratio, not CAGR alone.
- Cash earns 0 % in the model, which penalises time spent in cash in high-rate years; the benchmarks are always invested.

## Background
Trend following with a moving average as a risk-management timing rule was popularised by Faber's tactical asset allocation paper (Journal of Wealth Management, 2007). Momentum (buying past winners) was documented by Jegadeesh and Titman (Journal of Finance, 1993). These are the ideas the two price agents implement in simple form; the study tests them, it does not assume they work.

## Limits
Single history, flat costs, no taxes, ETF list chosen by the author knowing these funds survive, Yahoo data quality (adjusted close) not independently audited.
