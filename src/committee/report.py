"""Self-contained backtest report: markdown + charts."""
from __future__ import annotations

import os
from datetime import date

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .backtest import Result, sensitivity  # noqa: E402
from .portfolio import Config  # noqa: E402

BLUE, GREY, RED = "#2563eb", "#8a8f98", "#dc2626"


def _style(ax, title):
    ax.set_title(title, loc="left", fontsize=11, fontweight="bold")
    ax.grid(alpha=.25); ax.spines[["top", "right"]].set_visible(False)


def _charts(res: Result, out: str, tag: str) -> list[str]:
    files = []
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.plot(res.equity, color=BLUE, lw=1.6, label="Committee")
    ax.plot(res.benchmark, color=GREY, lw=1.2, label=f"{res.bench_label} benchmark")
    _style(ax, f"Growth of 1 {tag}"); ax.legend(frameon=False)
    files.append("equity.png"); fig.tight_layout(); fig.savefig(f"{out}/equity.png", dpi=130); plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 3.0))
    for s, c, n in ((res.equity, BLUE, "Committee"), (res.benchmark, GREY, "Benchmark")):
        ax.fill_between(s.index, s / s.cummax() - 1, 0, color=c, alpha=.35, label=n)
    _style(ax, "Drawdown"); ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}"); ax.legend(frameon=False)
    files.append("drawdown.png"); fig.tight_layout(); fig.savefig(f"{out}/drawdown.png", dpi=130); plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 3.4))
    w = res.weights.loc[:, (res.weights > 0).any()]
    ax.stackplot(w.index, w.T.values, labels=w.columns, colors=plt.cm.tab20.colors[:w.shape[1]])
    ax.set_ylim(0, 1); _style(ax, "Target weights (remainder = cash)")
    ax.legend(ncol=6, fontsize=6, frameon=False, loc="upper center", bbox_to_anchor=(.5, -.12))
    files.append("weights.png"); fig.tight_layout(); fig.savefig(f"{out}/weights.png", dpi=130); plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 3.2))
    c = res.contribution.sort_values()
    ax.barh(c.index, c.values, color=[RED if v < 0 else BLUE for v in c.values])
    _style(ax, "Summed contribution by ticker (simple, not compounded)")
    files.append("contribution.png"); fig.tight_layout()
    fig.savefig(f"{out}/contribution.png", dpi=130); plt.close(fig)
    return files


def _md_table(df: pd.DataFrame, fmt: dict | None = None) -> str:
    fmt = fmt or {}
    head = "| " + " | ".join(df.columns) + " |\n|" + "---|" * len(df.columns) + "\n"
    rows = ["| " + " | ".join(fmt.get(c, str)(v) for c, v in r.items()) + " |" for _, r in df.iterrows()]
    return head + "\n".join(rows) + "\n"


pct = lambda v: f"{v:+.1%}"  # noqa: E731
num = lambda v: f"{v:.2f}"   # noqa: E731


def build(res: Result, prices: pd.DataFrame, fundamentals: dict, cfg: Config, out: str,
          title: str, synthetic: bool = False, with_sensitivity: bool = True) -> str:
    os.makedirs(out, exist_ok=True)
    _charts(res, out, "(synthetic data)" if synthetic else "")
    m, b = res.metrics, res.bench_metrics
    perf = pd.DataFrame({"": ["Committee", "Benchmark"],
                         **{k: [m[k], b[k]] for k in m}})
    fmt = {"CAGR": pct, "Vol": lambda v: f"{v:.1%}", "Sharpe": num, "Sortino": num,
           "MaxDD": lambda v: f"{v:.1%}", "Calmar": num}
    rel_fmt = {"Beta": "{:.2f}", "Alpha (ann.)": "{:+.1%}", "Tracking error": "{:.1%}",
               "Information ratio": "{:.2f}", "Monthly hit rate": "{:.0%}"}
    rel = pd.DataFrame({"Metric": list(res.relative),
                        "Value": [rel_fmt[k].format(v) for k, v in res.relative.items()]})
    ann = res.annual.reset_index().rename(columns={"index": "Year"})
    ann["Year"] = ann["Year"].astype(str)
    lines = [f"# {title}", "",
             f"_Generated {date.today().isoformat()} · {prices.shape[1]} tickers · "
             f"{prices.index[0].date()} → {prices.index[-1].date()} · config `{cfg.fingerprint()}`_", "",
             "> **Disclaimer.** Educational research output. Not investment advice. "
             + ("**Synthetic data: results say nothing about real markets.**" if synthetic else
                "Past performance does not predict future results."), "",
             "## Performance", _md_table(perf, fmt),
             f"Average monthly turnover **{res.turnover:.1%}**, one-way cost **{cfg.cost_bps:.0f} bps**.", "",
             "![equity](equity.png)", "", "## Relative to benchmark", _md_table(rel),
             "![drawdown](drawdown.png)", "", "## Calendar-year returns",
             _md_table(ann, {"Committee": pct, "Benchmark": pct}), "",
             "## Positioning", "![weights](weights.png)", "", "![contribution](contribution.png)", ""]
    if with_sensitivity:
        sens = sensitivity(prices, fundamentals, cfg)
        lines += ["## Sensitivity to our own parameters",
                  "Sharpe ratio over a grid of entry threshold and position cap. A result that only works "
                  "at one cell of this table is overfitted.", "",
                  _md_table(sens, {"CAGR": pct, "Sharpe": num, "MaxDD": lambda v: f"{v:.1%}",
                                   "min_score": num, "max_position": lambda v: f"{v:.0%}"}), ""]
    lines += ["## Method", "See `docs/METHODOLOGY.md`. Fundamentals are joined as of publication date; "
              "decisions use only data available on the decision date."]
    path = f"{out}/report.md"
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return path
