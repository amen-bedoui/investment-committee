# Activating the Claude analyst (optional)

The committee works without it. The analyst adds one more opinion per stock; its confidence is capped at 0.5 and it is **never used in backtests** (no look-ahead from a model trained on the past).

1. Create an account at https://console.anthropic.com, add a few dollars under *Billing*, then *API Keys > Create Key*. Never paste the key in a chat, an issue or a commit.
2. Double-click `run_live.bat` (Windows) or run `./run_live.sh` (Mac/Linux). It installs the package, asks for the key (hidden), checks it with `committee llm-check`, then prints live decisions.
3. By hand: `pip install ".[live,llm]"`, set `ANTHROPIC_API_KEY` for the current window, then `committee llm-check` and `committee live --tickers AAPL MSFT NVDA --llm`.

Cost: one short request per ticker, a few cents for a run. Fundamentals come from Yahoo's current snapshot (not point-in-time), so use `live` for today's view, not for backtests.

Troubleshooting: `llm-check` prints the cause (missing key, no credit, network). The key is never printed.
