# Methodology

## Pipeline
```
prices + fundamentals --> agents (Signal) --> portfolio manager --> weights --> backtest / ledger / report
```

## Agents
| Agent | Inputs | Idea |
|---|---|---|
| value | P/E, P/B, FCF yield | cheap versus fixed reference levels (15x, 2.5x, 4 %) |
| quality | ROE, net margin, debt/EBITDA | profitable, low leverage (15 %, 10 %, 2.5x) |
| growth | revenue growth | above an 8 % reference |
| momentum | 12-1 month return | winners persist; the latest month is skipped (short-term reversal) |
| llm (optional) | the above, as text | qualitative second opinion, confidence capped at 0.5 |

Each signal is in [-1, 1] with a confidence in [0, 1] and a one-line rationale. Missing data gives confidence 0 (the agent abstains) instead of an error. Reference levels are the author's choices, not calibrated.

## Portfolio manager
1. Composite = confidence- and mandate-weighted average of signals.
2. Invest if composite >= `min_score`; veto if more than `max_drawdown_veto` below the 1-year high.
3. Raw weight = composite / 60-day volatility, normalised, capped at `max_position` (excess stays in cash). Long-only, no leverage.

## Backtest
- Month-end rebalance, weights held (buy-and-hold) until the next rebalance.
- One-way cost `cost_bps` on turnover; benchmark = equal-weight, monthly rebalanced, no cost.
- **Point-in-time**: fundamentals joined as of publication date; `test_no_lookahead_in_decisions` multiplies all future prices by 5 and requires identical decisions.
- Metrics: CAGR, volatility, Sharpe and Sortino (risk-free = 0), max drawdown, Calmar, beta, annualised alpha, tracking error, information ratio, monthly hit rate.
- Contribution by ticker is a simple sum of weight x period return (not compounded): good for ranking, not for exact attribution.

## Walk-forward
Every parameter set in a grid (entry threshold x position cap) is backtested once over the full history. At each yearly fold the set with the best Sharpe over the previous 4 years is selected, using returns strictly before the fold, and its next 12 months of returns are kept as out-of-sample. Chained folds form a track record in which no parameter was chosen with knowledge of the period it trades. Approximation: runs are independent, so one full turnover of costs is charged at each parameter switch. A test corrupts all data after the first fold and checks the first choice is unchanged. If adaptive tuning does not beat the fixed default out-of-sample, that is evidence the parameters are noise, and the report says so.

## Risk-free rate
With `--rf` (annual percent series such as ^IRX), uninvested cash accrues the rate (forward-filled, no look-ahead) and Sharpe/Sortino use excess returns. Without it cash earns `cash_rate` (default 0) and Sharpe uses raw returns.

## Sensitivity
`report` re-runs the backtest over a grid of `min_score` x `max_position`. Read it as a robustness check: a strategy that works in one cell only is overfitted. Note that higher thresholds mechanically hold more cash, which lowers volatility and drawdown whatever the signal quality, so compare Sharpe and CAGR together.

## Null-world check
The synthetic market draws returns independently of fundamentals. Over 30 seeds (v0.2 run) the committee averaged about -1.5 %/year versus the benchmark and won 8 times out of 30: costs and concentration, no manufactured edge. This validates the plumbing (no leak of the future), not the strategy.

## Paper ledger
`paper` appends the latest decisions to a JSON-lines file; each entry hashes its content plus the previous hash (SHA-256). `verify` detects edited, removed or reordered sessions. It proves record integrity only; it is not an audit trail and anyone with the file can rebuild a consistent chain from scratch.

## Limits
- No real-market performance claimed. With real data, survivorship bias, corporate actions and restated fundamentals are the user's responsibility.
- Yahoo fundamentals are a current snapshot: used for `analyze --live` only.
- Fixed thresholds; no out-of-sample parameter selection; no sector or factor constraints; no short selling.
- The yfinance download and the Anthropic call are covered by offline tests with injected clients and were not run against the live services by the author.
