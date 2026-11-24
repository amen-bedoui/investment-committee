@echo off
REM One-click live run with the optional Claude analyst. Needs Python 3.10+, internet, and an Anthropic API key
REM (console.anthropic.com > API Keys). The key is typed hidden and lives only in this window.
cd /d "%~dp0"
python -m pip install --quiet ".[live,llm]" || goto :err
if "%ANTHROPIC_API_KEY%"=="" (
  for /f "usebackq delims=" %%K in (`powershell -NoProfile -Command "$s=Read-Host 'Paste your Anthropic API key (hidden)' -AsSecureString; [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))"`) do set ANTHROPIC_API_KEY=%%K
)
echo.
echo Step 1/2: checking the key...
committee llm-check || goto :err
echo.
echo Step 2/2: live decisions with the Claude analyst...
committee live --tickers AAPL MSFT NVDA GOOGL AMZN JPM XOM JNJ --llm || goto :err
echo.
echo Done. Educational research only, not investment advice.
pause
exit /b 0
:err
echo.
echo Something failed. Copy the message above (NOT your key) and send it to Claude.
pause
exit /b 1
