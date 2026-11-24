@echo off
REM One-click real-data study (Windows). Needs Python 3.10+ and internet.
REM 1) installs the package with the Yahoo downloader  2) downloads 19 ETFs (2005 -> today)  3) runs the study.
python -m pip install --quiet ".[live]" || goto :err
committee fetch --tickers SPY QQQ IWM EFA EEM TLT IEF LQD GLD VNQ XLK XLF XLE XLV XLY XLP XLI XLU XLB --start 2005-01-01 --out etf_prices.csv || goto :err
committee fetch --tickers "^IRX" --start 2005-01-01 --out rf.csv || goto :err
committee study --prices etf_prices.csv --rf rf.csv --benchmark SPY --out real_study --source "Yahoo Finance" || goto :err
echo.
echo Done. Open real_study\report.md (charts are next to it). Numbers: real_study\bundle.json
pause
exit /b 0
:err
echo Something failed, see the message above.
pause
exit /b 1
