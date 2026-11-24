#!/usr/bin/env sh
# One-click live run with the optional Claude analyst. Needs Python 3.10+, internet and an Anthropic API key.
set -e
cd "$(dirname "$0")"
python3 -m pip install --quiet ".[live,llm]"
if [ -z "$ANTHROPIC_API_KEY" ]; then
  printf "Paste your Anthropic API key (hidden): "; stty -echo; read -r ANTHROPIC_API_KEY; stty echo; echo
  export ANTHROPIC_API_KEY
fi
echo "Step 1/2: checking the key..."; committee llm-check
echo "Step 2/2: live decisions with the Claude analyst..."
committee live --tickers AAPL MSFT NVDA GOOGL AMZN JPM XOM JNJ --llm
