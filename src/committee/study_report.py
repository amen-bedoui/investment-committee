"""Render a `run_study` bundle (pure JSON numbers) into charts + a markdown report."""
from __future__ import annotations

import os

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

BLUE, GREY, ORANGE = "#2563eb", "#8a8f98", "#f59e0b"
pct = lambda v: "n/a" if v is None else f"{v:+.1%}"   # noqa: E731
pc0 = lambda v: "n/a" if v is None else f"{v:.1%}"    # noqa: E731
num = lambda v: "n/a" if v is None else f"{v:.2f}"    # noqa: E731


def _table(header, rows):
    return ("| " + " | ".join(header) + " |\n|" + "---|" * len(header) + "\n"
            + "\n".join("| " + " | ".join(r) + " |" for r in rows) + "\n")


def _style(ax, title):
    ax.set_title(title, loc="left", fontsize=11, fontweight="bold")
    ax.grid(alpha=.25); ax.spines[["top", "right"]].set_visible(False)


def _charts(b, out):
    s, bench = b["series"], b["meta"]["bench"]
    idx = pd.to_datetime(s["dates"])
    cols = {"Committee": BLUE, bench: GREY, "Equal-weight": ORANGE}
    fig, ax = plt.subplots(figsize=(8, 3.8))
    for k, c in cols.items():
        ax.plot(idx, s[k], color=c, lw=1.7 if k == "Committee" else 1.2, label=k)
    ax.set_yscale("log"); _style(ax, "Growth of 1 (log scale, dividends reinvested, after costs)")
    ax.legend(frameon=False); ax.yaxis.set_major_formatter(lambda v, _: f"{v:g}")
    fig.tight_layout(); fig.savefig(f"{out}/equity.png", dpi=130); plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 3.0))
    for k, c in cols.items():
        v = pd.Series(s[k], index=idx)
        ax.fill_between(idx, v / v.cummax() - 1, 0, color=c, alpha=.35 if k == "Committee" else .18, label=k)
    _style(ax, "Drawdown (weekly sampling)"); ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.legend(frameon=False, loc="lower left"); fig.tight_layout()
    fig.savefig(f"{out}/drawdown.png", dpi=130); plt.close(fig)

    ann = pd.DataFrame(b["annual"]).T[["Committee", bench, "Equal-weight"]].astype(float)
    fig, ax = plt.subplots(figsize=(8, 3.2))
    ann.plot.bar(ax=ax, color=[BLUE, GREY, ORANGE], width=.8)
    _style(ax, "Calendar-year returns"); ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.legend(frameon=False, fontsize=8); ax.tick_params(axis="x", rotation=60, labelsize=7)
    fig.tight_layout(); fig.savefig(f"{out}/annual.png", dpi=130); plt.close(fig)

    w = pd.Series(b["avg_weights"]).sort_values()
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.barh(w.index, w.values, color=BLUE)
    _style(ax, "Average weight by ETF"); ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    fig.tight_layout(); fig.savefig(f"{out}/weights.png", dpi=130); plt.close(fig)


def headline(b) -> str:
    m, bench = b["metrics"], b["meta"]["bench"]
    c, s, e = m["Committee"], m[bench], m["Equal-weight"]
    bs = b["bootstrap"][bench]
    parts = [f"Over {b['meta']['start']} to {b['meta']['end']} the committee returned {pct(c['CAGR'])} a year "
             f"(Sharpe {num(c['Sharpe'])}, max drawdown {pc0(c['MaxDD'])}), against {pct(s['CAGR'])} "
             f"(Sharpe {num(s['Sharpe'])}, max drawdown {pc0(s['MaxDD'])}) for {bench} and {pct(e['CAGR'])} "
             f"(Sharpe {num(e['Sharpe'])}, max drawdown {pc0(e['MaxDD'])}) for the equal-weight basket."]
    lo, hi = bs["ci05"], bs["ci95"]
    if lo is not None and hi is not None:
        verdict = ("statistically distinguishable from zero at the 90% level" if lo > 0 or hi < 0
                   else "NOT statistically distinguishable from zero at the 90% level")
        parts.append(f"Annualised excess return versus {bench}: {pct(bs['mean_ann'])} "
                     f"(bootstrap 90% interval {pct(lo)} to {pct(hi)}): {verdict}.")
    return " ".join(parts)


def _walk_forward_section(b) -> list[str]:
    wf = b["walk_forward"]
    ad, fx, bm = wf["adaptive"], wf["fixed_default"], wf["benchmark"]
    rows = [[n, pct(m["CAGR"]), pc0(m["Vol"]), num(m["Sharpe"]), pc0(m["MaxDD"])]
            for n, m in (("Walk-forward (parameters re-chosen yearly)", ad), ("Fixed default mandate", fx),
                         (wf["bench_label"], bm))]
    better = ad["Sharpe"] is not None and fx["Sharpe"] is not None and ad["Sharpe"] > fx["Sharpe"]
    verdict = ("Re-choosing parameters on the past improved the Sharpe ratio versus the fixed default."
               if better else
               "Re-choosing parameters on the past did **not** improve the Sharpe ratio versus the fixed default: "
               "the default is at least as good as adaptive tuning, a sign that tuning adds noise, not value.")
    shown = wf["folds"]
    return ["## Out-of-sample parameter selection (walk-forward)",
            f"Each year the best of 12 parameter sets (entry threshold x position cap) over the previous "
            f"{wf['train_years']} years is applied to the next {wf['test_months']} months, so no parameter is "
            f"ever chosen with knowledge of the period it trades. Span {wf['span'][0]} to {wf['span'][1]}, "
            f"{wf['n_folds']} folds, "
            f"{wf['switches']} parameter switches (one full turnover of cost charged per switch).", "",
            _table(["", "CAGR", "Vol", "Sharpe", "Max DD"], rows), verdict, "",
            _table(["Fold start", "min_score", "max_position", "Train Sharpe", "OOS return"],
                   [[f["start"], num(f["min_score"]), f"{f['max_position']:.0%}", num(f["train_sharpe"]),
                     pct(f["oos_return"])] for f in shown]), ""]


def render(b: dict, out: str, title: str = "Real-data study: ETF tactical allocation") -> str:
    os.makedirs(out, exist_ok=True)
    _charts(b, out)
    meta, bench, m = b["meta"], b["meta"]["bench"], b["metrics"]
    names = ["Committee", bench, "Equal-weight"]
    L = [f"# {title}", "",
         f"_Data: {meta.get('source', 'user-supplied prices CSV')}, daily dividend-adjusted prices, "
         f"{len(meta['tickers'])} assets, "
         f"{meta['start']} to {meta['end']}. Config `{meta['config']}`._", "",
         "> **Disclaimer.** Educational research. Not investment advice. A backtest is not a forecast: "
         "past performance does not predict future results.", "",
         "## Headline", headline(b), "",
         "## Protocol (fixed before looking at results)",
         f"- Universe: {', '.join(meta['tickers'])} (as supplied; membership must be fixed in advance and free of "
         "survivorship for the result to mean anything).",
         "- Agents: momentum (12-1 month) and trend (price vs 200-day average). Value, quality and growth abstain "
         "because no point-in-time fundamentals exist for ETFs here.",
         f"- Default mandate, **nothing tuned on this sample**: min score 0.10, 25% position cap, -30% drawdown veto, "
         f"monthly rebalance, {meta['cost_bps']:.0f} bps one-way cost, {meta['exec_lag']}-day execution lag, "
         + ("cash earns the supplied short-term risk-free rate, Sharpe uses excess returns."
            if meta.get("rf") else f"cash earns {meta['cash_rate']:.0%}."),
         f"- Benchmarks: {bench} buy-and-hold and the equal-weight basket (monthly rebalanced, no cost).", "",
         "## Performance",
         _table(["", "CAGR", "Vol", "Sharpe", "Sortino", "Max DD", "Calmar"],
                [[n, pct(m[n]["CAGR"]), pc0(m[n]["Vol"]), num(m[n]["Sharpe"]), num(m[n]["Sortino"]),
                  pc0(m[n]["MaxDD"]), num(m[n]["Calmar"])] for n in names]),
         ("Sharpe and Sortino are computed on returns in excess of the 13-week T-bill rate." if meta.get("rf") else
          "Sharpe and Sortino use a 0% risk-free rate for all three, which understates the hurdle in high-rate "
          "years."), "", "![equity](equity.png)", "![drawdown](drawdown.png)", "",
         "## Relative to benchmarks",
         _table(["", "Beta", "Alpha (ann.)", "Tracking error", "Info ratio", "Monthly hit rate"],
                [[f"vs {k}", num(v["Beta"]), pct(v["Alpha (ann.)"]), pc0(v["Tracking error"]),
                  num(v["Information ratio"]), f"{v['Monthly hit rate']:.0%}"] for k, v in b["relative"].items()]),
         _table(["Excess return vs", "Months", "Mean (ann.)", "90% interval", "P(excess > 0)"],
                [[k, str(v["months"]), pct(v["mean_ann"]), f"{pct(v['ci05'])} to {pct(v['ci95'])}",
                  f"{v['p_positive']:.0%}"] for k, v in b["bootstrap"].items()]),
         "Interval from a moving-block bootstrap (6-month blocks, 4000 resamples) of monthly active returns.", "",
         ]
    L += _walk_forward_section(b) if b.get("walk_forward") else [
        "## Out-of-sample parameter selection (walk-forward)",
        "Not run: the history is too short for a 4-year training window plus a test year.", ""]
    L += ["## Sub-periods"]
    rows = []
    for name, d in b["subperiods"].items():
        for n in names:
            x = d[n]
            first = n == "Committee"
            rows.append([name if first else "", f"{d['range'][0]} to {d['range'][1]}" if first else "",
                         n, pct(x["CAGR"]), num(x["Sharpe"]), pc0(x["MaxDD"])])
    L += [_table(["Period", "Range", "", "CAGR", "Sharpe", "Max DD"], rows), "## Stress windows (fixed in advance)"]
    rows = []
    for k, d in b["windows"].items():
        rows.append([k] + [f"{pct(d[n]['return'])} (DD {pc0(d[n]['maxdd'])})" if d[n] else "n/a" for n in names])
    L += [_table(["Window"] + names, rows), "## Calendar years", "![annual](annual.png)", "",
          "## Robustness", "**Transaction costs** (committee only):",
          _table(["Cost (bps one-way)", "CAGR", "Sharpe", "Max DD"],
                 [[f"{r['cost_bps']:.0f}", pct(r["CAGR"]), num(r["Sharpe"]), pc0(r["MaxDD"])]
                  for r in b["cost_sensitivity"]])]
    if b["grid"]:
        L += ["**Parameter grid** (entry threshold x position cap). A result that only holds in one cell would be "
              "overfitted:", _table(["min_score", "max_position", "CAGR", "Sharpe", "Max DD"],
                                    [[num(r["min_score"]), f"{r['max_position']:.0%}", pct(r["CAGR"]),
                                      num(r["Sharpe"]), pc0(r["MaxDD"])] for r in b["grid"]])]
    L += ["## Positioning", f"Average invested fraction {b['invested']:.0%}; months fully in cash "
          f"{b['months_all_cash']:.0%}; average monthly turnover {b['turnover']:.0%}.", "",
          "![weights](weights.png)", "",
          f"Latest committee view (decision at the last close of the data, {meta['end']}; **not a recommendation**):",
          _table(["ETF", "Score", "Target weight", "Veto"],
                 [[r["ticker"], f"{r['score']:+.2f}", f"{r['weight']:.1%}", "yes" if r["vetoed"] else ""]
                  for r in b["latest"]]), "",
          "## Limits",
          ("- Cash earns the supplied risk-free series while the benchmarks are always fully invested."
           if meta.get("rf") else
           "- Without a risk-free series, cash earns 0%, which penalises the strategy in high-rate years; the "
           "benchmarks are always fully invested."),
          "- Walk-forward treats each parameter set as an independent run and charges one full turnover per switch: "
          "an approximation, not an exact replay.",
          "- The ETF list was chosen by the author knowing these funds still exist; mild selection effect remains.",
          "- Costs are a flat one-way rate on turnover (no spreads, taxes or market impact).",
          "- One path of history: statistical uncertainty is large (see the bootstrap interval).",
          "- Momentum and trend effects are documented in published research but may weaken once widely known.", "",
          "## References",
          "- Faber, M. (2007). A Quantitative Approach to Tactical Asset Allocation. Journal of Wealth Management.",
          "- Jegadeesh, N. and Titman, S. (1993). Returns to Buying Winners and Selling Losers: Implications for Stock "
          "Market Efficiency. Journal of Finance, 48(1), 65-91.", ""]
    path = f"{out}/report.md"
    with open(path, "w") as fh:
        fh.write("\n".join(L))
    return path
