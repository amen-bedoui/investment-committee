"""Long-history real-data study: the committee's price agents as a timing overlay on the US equity market.

Data: SteelCerberus/us-market-data (MIT), daily total-return index since 1885 with a risk-free series.
Single asset, so the committee decides each month between 100 % invested and cash: this tests the
trend/momentum rules (Faber 2007; Jegadeesh-Titman 1993 for momentum) with the committee's own
risk veto, costs and execution lag. Protocol fixed before any result (docs/REAL_WORLD_STUDY.md).
"""
from __future__ import annotations

import os
from dataclasses import replace

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .backtest import metrics, rf_to_daily, run  # noqa: E402
from .portfolio import Config  # noqa: E402
from .study import bootstrap_active  # noqa: E402
from .walkforward import walk_forward  # noqa: E402

ASSET = "US_EQUITY"
ERAS = {  # fixed in advance; PRIMARY is the highest-quality segment (index prices from Yahoo)
    "1886-2025 (Dow composite before 1928)": ("1880-01-01", "2100-01-01"),
    "1928-2025 (S&P 500 index)": ("1928-01-01", "2100-01-01"),
    "1962-2025 (S&P 500, Yahoo prices) PRIMARY": ("1962-06-18", "2100-01-01"),
}
PRIMARY = "1962-2025 (S&P 500, Yahoo prices) PRIMARY"
WINDOWS = {  # stress windows fixed in advance
    "1929 crash (3 Sep 1929 - 1 Jun 1932)": ("1929-09-03", "1932-06-01"),
    "1973-74 bear market (1 Jan 1973 - 1 Oct 1974)": ("1973-01-01", "1974-10-01"),
    "Dot-com bust (1 Sep 2000 - 1 Oct 2002)": ("2000-09-01", "2002-10-01"),
    "Global financial crisis (31 Oct 2007 - 9 Mar 2009)": ("2007-10-31", "2009-03-09"),
    "COVID crash (19 Feb - 23 Mar 2020)": ("2020-02-19", "2020-03-23"),
}
MANDATE = Config(max_position=1.0)  # single asset: 100 % invested or cash (default cap would cap exposure at 25 %)
pct = lambda v: "n/a" if v is None or not np.isfinite(v) else f"{v:+.1%}"  # noqa: E731
pc0 = lambda v: "n/a" if v is None or not np.isfinite(v) else f"{v:.1%}"   # noqa: E731
num = lambda v: "n/a" if v is None or not np.isfinite(v) else f"{v:.2f}"   # noqa: E731


def load_us_market(path: str) -> tuple[pd.DataFrame, pd.Series]:
    """Returns (prices with one column = total-return index, annual risk-free rate as decimals)."""
    df = pd.read_csv(path, parse_dates=["Date"]).set_index("Date").sort_index()
    need = {"Adjusted Close", "Risk Free Rate"}
    if not need <= set(df.columns):
        raise ValueError(f"unexpected format, need columns {sorted(need)}")
    prices = df[["Adjusted Close"]].rename(columns={"Adjusted Close": ASSET}).astype(float)
    if prices.index.has_duplicates or (prices <= 0).any().any():
        raise ValueError("prices: duplicates or non-positive values")
    return prices, (df["Risk Free Rate"].astype(float) / 100.0)


def _slice(eq: pd.Series, a: str, b: str) -> pd.Series | None:
    s = eq.loc[a:b]
    return None if len(s) < 60 else s / s.iloc[0]


def _table(header, rows):
    return ("| " + " | ".join(header) + " |\n|" + "---|" * len(header) + "\n"
            + "\n".join("| " + " | ".join(r) + " |" for r in rows) + "\n")


def _style(ax, title):
    ax.set_title(title, loc="left", fontsize=11, fontweight="bold")
    ax.grid(alpha=.25); ax.spines[["top", "right"]].set_visible(False)


def run_timing_study(prices: pd.DataFrame, rf: pd.Series, out: str, cfg: Config | None = None,
                     source: str = "SteelCerberus/us-market-data") -> dict:
    cfg = cfg or MANDATE
    os.makedirs(out, exist_ok=True)
    cache: dict = {}
    res = run(prices, {}, cfg, benchmark=ASSET, rf=rf, cache=cache)
    eq, bh = res.equity, res.benchmark
    rfd = rf_to_daily(rf, prices.index)
    cash = (1 + rfd.reindex(eq.index)).cumprod()
    invested = res.weights.sum(axis=1)

    def block(a, b):
        e, h, c = _slice(eq, a, b), _slice(bh, a, b), _slice(cash, a, b)
        if e is None:
            return None
        return {"Committee": metrics(e, rfd), "Buy & hold": metrics(h, rfd), "Cash": metrics(c, rfd),
                "first": str(e.index[0].date()), "last": str(e.index[-1].date())}

    eras = {k: block(*v) for k, v in ERAS.items()}
    windows = {}
    for k, (a, b) in WINDOWS.items():
        e, h = eq.loc[a:b], bh.loc[a:b]
        if len(e) > 5:
            windows[k] = {n: (s.iloc[-1] / s.iloc[0] - 1, (s / s.cummax() - 1).min())
                          for n, s in (("Committee", e), ("Buy & hold", h))}
    primary_key = PRIMARY if eras[PRIMARY] else next(k for k, v in eras.items() if v)
    primary_a = ERAS[primary_key][0]
    boots = {"Full sample": bootstrap_active(eq, bh),
             "Primary era": bootstrap_active(eq.loc[primary_a:], bh.loc[primary_a:])}

    abl = {}
    for name, w in (("Committee (momentum + trend)", {"momentum": 1.0, "trend": 1.0}),
                    ("Momentum only", {"momentum": 1.0, "trend": 0.0}),
                    ("Trend only", {"momentum": 0.0, "trend": 1.0})):
        r = run(prices, {}, replace(cfg, weights={**cfg.weights, **w}), benchmark=ASSET, rf=rf, cache=cache)
        e = _slice(r.equity, primary_a, "2100-01-01")
        abl[name] = metrics(e, rfd)
    costs = []
    for c in (0.0, 10.0, 25.0, 50.0, 100.0):
        r = run(prices, {}, replace(cfg, cost_bps=c), benchmark=ASSET, rf=rf, cache=cache)
        e = _slice(r.equity, primary_a, "2100-01-01")
        costs.append((c, metrics(e, rfd)))
    grid = []
    for ms in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5):
        r = run(prices, {}, replace(cfg, min_score=ms), benchmark=ASSET, rf=rf, cache=cache)
        e = _slice(r.equity, primary_a, "2100-01-01")
        grid.append((ms, metrics(e, rfd)))
    wf = walk_forward(prices, {}, cfg, min_scores=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5), caps=(1.0,), train_years=10,
                      test_months=12, rf=rf, cache=cache, benchmark=ASSET)

    dec = []
    for d0 in range(1890, 2030, 10):
        a, b = f"{d0}-01-01", f"{d0 + 9}-12-31"
        e, h = _slice(eq, a, b), _slice(bh, a, b)
        if e is not None and len(e) > 500:
            inv = invested.loc[a:b]
            dec.append((f"{d0}s", metrics(e, rfd)["CAGR"], metrics(h, rfd)["CAGR"], metrics(e, rfd)["MaxDD"],
                        metrics(h, rfd)["MaxDD"], float((inv > 0).mean())))

    # ---- charts ----
    wk = eq.index[::21]
    fig, ax = plt.subplots(figsize=(8, 3.8))
    ax.plot(bh.loc[wk], color="#8a8f98", lw=1.2, label="Buy & hold (total return)")
    ax.plot(eq.loc[wk], color="#2563eb", lw=1.5, label="Committee timing")
    ax.set_yscale("log"); ax.legend(frameon=False); _style(ax, "Growth of 1 (log scale, after costs)")
    fig.tight_layout(); fig.savefig(f"{out}/equity.png", dpi=130); plt.close(fig)
    fig, ax = plt.subplots(figsize=(8, 3.0))
    for s, c, n, al in ((bh, "#8a8f98", "Buy & hold", .35), (eq, "#2563eb", "Committee", .45)):
        ss = s.loc[wk]
        ax.fill_between(ss.index, ss / ss.cummax() - 1, 0, color=c, alpha=al, label=n)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}"); ax.legend(frameon=False, loc="lower left")
    _style(ax, "Drawdown (monthly sampling)"); fig.tight_layout(); fig.savefig(f"{out}/drawdown.png", dpi=130)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(8, 2.6))
    ax.fill_between(invested.index, invested.values, 0, step="post", color="#2563eb", alpha=.6)
    ax.set_ylim(0, 1.05); _style(ax, "Exposure (1 = invested, 0 = cash)")
    fig.tight_layout(); fig.savefig(f"{out}/exposure.png", dpi=130); plt.close(fig)

    best_ms = max(grid, key=lambda g: g[1]["Sharpe"])[0]
    # ---- report ----
    P = eras[primary_key]
    c, b = P["Committee"], P["Buy & hold"]
    lo, hi = boots["Primary era"]["ci05"], boots["Primary era"]["ci95"]
    sig = ("statistically distinguishable from zero" if (lo > 0 or hi < 0)
           else "NOT statistically distinguishable from zero")
    better_dd = c["MaxDD"] > b["MaxDD"]
    head = (f"Primary era {P['first']} to {P['last']}: committee {pct(c['CAGR'])} a year (Sharpe {num(c['Sharpe'])}, "
            f"max drawdown {pc0(c['MaxDD'])}) versus buy-and-hold {pct(b['CAGR'])} (Sharpe {num(b['Sharpe'])}, "
            f"max drawdown {pc0(b['MaxDD'])}). Excess return {pct(boots['Primary era']['mean_ann'])} a year, "
            f"90% bootstrap interval {pct(lo)} to {pct(hi)}: {sig}. The timing overlay "
            f"{'reduced' if better_dd else 'did not reduce'} the worst drawdown.")
    L = ["# Real-data study: committee timing on 140 years of US equities", "",
         f"_Data: {source} (MIT), daily total-return index and risk-free series, "
         f"{prices.index[0].date()} to {prices.index[-1].date()}. Config `{cfg.fingerprint()}`._", "",
         "> **Disclaimer.** Educational research, not investment advice; a backtest is not a forecast. The data source "
         "itself states it is only suited to crude buy-and-hold backtests: results are indicative, not precise.", "",
         "## Headline", head, "",
         "## Protocol (fixed before looking at results)",
         "- Asset: US equity total-return index (Dow composite 1885-1927, S&P 500 from 1928; dividends added, 0.09% "
         "annual expense drag in the source). Cash earns the source's risk-free series.",
         "- Committee: momentum (12-1 month) and trend (price vs 200-day average) agents with the default entry score "
         "0.10, -30% drawdown veto, 10 bps one-way cost, decision at month-end close, execution one trading day later. "
         "Single asset, so the position cap is 100%: the committee is either fully invested or in cash.",
         f"- Primary era (highest data quality): {primary_key.split(' PRIMARY')[0]}; other eras shown for context. "
         "Nothing tuned on the sample.", "",
         "## Performance by era",
         _table(["Era", "", "CAGR", "Vol", "Sharpe", "Max DD", "Calmar"],
                [[k if n == "Committee" else "", n, pct(v[n]["CAGR"]), pc0(v[n]["Vol"]), num(v[n]["Sharpe"]),
                  pc0(v[n]["MaxDD"]), "n/a" if n == "Cash" else num(v[n]["Calmar"])]
                 for k, v in eras.items() if v for n in ("Committee", "Buy & hold", "Cash")]),
         "Sharpe and Sortino are on returns in excess of the risk-free series.", "",
         "![equity](equity.png)", "![drawdown](drawdown.png)", "![exposure](exposure.png)", "",
         "## Statistical significance (moving-block bootstrap of monthly excess returns)",
         _table(["Sample", "Months", "Excess (ann.)", "90% interval", "P(excess > 0)"],
                [[k, str(v["months"]), pct(v["mean_ann"]), f"{pct(v['ci05'])} to {pct(v['ci95'])}",
                  f"{v['p_positive']:.0%}"] for k, v in boots.items()]), "",
         "Excess return here is the annualised arithmetic mean of monthly differences, so it can differ from the gap "
         "between the two compound growth rates (lower volatility lowers the arithmetic mean less than the geometric "
         "one is lifted).", "",
         "## Stress windows (fixed in advance)",
         _table(["Window", "Committee", "Buy & hold"],
                [[k, f"{pct(v['Committee'][0])} (DD {pc0(v['Committee'][1])})",
                  f"{pct(v['Buy & hold'][0])} (DD {pc0(v['Buy & hold'][1])})"] for k, v in windows.items()]), "",
         "## By decade",
         _table(["Decade", "CAGR committee", "CAGR buy & hold", "Max DD committee", "Max DD buy & hold",
                 "Time invested"],
                [[d, pct(a), pct(bb), pc0(c1), pc0(c2), f"{inv:.0%}"] for d, a, bb, c1, c2, inv in dec]), "",
         "## What drives the result (primary era)",
         _table(["Variant", "CAGR", "Sharpe", "Max DD"],
                [[n, pct(m["CAGR"]), num(m["Sharpe"]), pc0(m["MaxDD"])] for n, m in abl.items()]), "",
         "**Costs** (one-way, per switch):",
         _table(["bps", "CAGR", "Sharpe", "Max DD"],
                [[f"{c0:.0f}", pct(m["CAGR"]), num(m["Sharpe"]), pc0(m["MaxDD"])] for c0, m in costs]),
         ("**Entry threshold** (min score). Caution: the default (0.10) was set in advance, but it happens to be the "
          "best cell of this table; its neighbours are weaker, so read the headline Sharpe as an optimistic estimate "
          "and prefer the walk-forward figures below:" if best_ms == cfg.min_score else
          "**Entry threshold** (min score). The default was set in advance; a different cell scores higher here, which "
          "is exactly why parameters should not be picked on the full sample (see walk-forward below):"),
         _table(["min_score", "CAGR", "Sharpe", "Max DD"],
                [[num(ms), pct(m["CAGR"]), num(m["Sharpe"]), pc0(m["MaxDD"])] for ms, m in grid]), "",
         "## Walk-forward (out-of-sample parameter choice)",
         f"Each year the entry threshold with the best Sharpe over the previous {wf['train_years']} years is applied "
         f"to the next year. Span {wf['span'][0]} to {wf['span'][1]}, {wf['n_folds']} folds, "
         f"{wf['switches']} switches.", "",
         _table(["", "CAGR", "Vol", "Sharpe", "Max DD"],
                [[n, pct(m["CAGR"]), pc0(m["Vol"]), num(m["Sharpe"]), pc0(m["MaxDD"])]
                 for n, m in (("Walk-forward", wf["adaptive"]), ("Fixed default", wf["fixed_default"]),
                              ("Buy & hold", wf["benchmark"]))]), "",
         ("Re-choosing the threshold each year on the past did **not** beat the fixed default out-of-sample: "
          "adaptive tuning added noise, not value." if wf["adaptive"]["Sharpe"] <= wf["fixed_default"]["Sharpe"] else
          "Re-choosing the threshold each year on the past improved the Sharpe ratio versus the fixed default."), "",
         "## Limits",
         "- Data quality: daily series with interpolated values, a Dow composite before 1928, and approximated "
         "risk-free rates before 1926; early costs and liquidity were very different from 10 bps.",
         "- A total-return index is not directly investable; no taxes, no spreads or market impact.",
         "- One history: the bootstrap interval measures sampling noise, not regime change.",
         "- Data ends at the source snapshot date shown above, not today.", "",
         "## References",
         "- Faber, M. (2007). A Quantitative Approach to Tactical Asset Allocation. Journal of Wealth Management.",
         "- Jegadeesh, N. and Titman, S. (1993). Returns to Buying Winners and Selling Losers. "
         "Journal of Finance, 48(1).", ""]
    path = f"{out}/report.md"
    with open(path, "w") as fh:
        fh.write("\n".join(L))
    return {"report": path, "headline": head, "eras": eras, "boots": boots, "walk_forward": wf}
