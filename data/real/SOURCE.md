# Source of `us_market_data.csv`

- Repository: https://github.com/SteelCerberus/us-market-data (MIT licence), file `data/us_market_data.csv`.
- Retrieved: 23 November 2026. Content: daily rows from 20 March 1885 to 19 December 2025 (35,254 rows).
- SHA-256 (first 16 hex): `dc6f17a6f51361f7`.
- Columns used here: `Adjusted Close` (total-return index) and `Risk Free Rate` (annual percent).
- Composition per the upstream README: Dow composite 1885-1927, S&P 500 1928-1962 (billschwert.com prices, Shiller dividends), S&P 500 1962-2023 (Yahoo ^GSPC), SPY from mid-2023; dividends added; expense drag about 0.09 % a year; pre-1926 risk-free rate approximated.
- Upstream caveat, kept here on purpose: the dataset is only good for crude buy-and-hold backtests. Holiday values are interpolated and Saturday trading before 1952 is dropped.
- Redistributed unchanged for reproducibility under the upstream MIT licence. Please credit the upstream author.

# Source of `etf_total_return.csv` and `rf_tbill.csv`

- Repository: https://github.com/rubetron/AssetAllocation (GPL >= 3, author Alexandre Rubesam), file `data/ETFs.rda` (retrieved 24 November 2026).
- Content: daily total returns of 37 ETFs (Yahoo Finance) and daily 3-month T-bill returns, 31 Dec 1999 to 9 Jun 2023.
- Derived here: 12 liquid ETFs (SPY, IWM, EFA, EEM, TLT, IEF, LQD, TIP, GLD, VNQ, DBC, HYG) compounded into total-return indices; T-bill daily return x 252 x 100 = annual percent. Derived files stay under the upstream GPL licence.
- Caveats: the ETF list was fixed by the author, knowing these funds survived (mild survivorship); data ends in June 2023 (not updated); several ETFs start late (e.g. HYG 2007), so early years use fewer assets.
