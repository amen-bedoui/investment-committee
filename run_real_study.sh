#!/usr/bin/env sh
# One-click real-data study (macOS/Linux). Needs Python 3.10+ and internet.
set -e
python3 -m pip install --quiet ".[live]"
committee fetch --tickers SPY QQQ IWM EFA EEM TLT IEF LQD GLD VNQ XLK XLF XLE XLV XLY XLP XLI XLU XLB --start 2005-01-01 --out etf_prices.csv
committee fetch --tickers "^IRX" --start 2005-01-01 --out rf.csv
committee study --prices etf_prices.csv --rf rf.csv --benchmark SPY --out real_study --source "Yahoo Finance"
echo "Done. Open real_study/report.md"
