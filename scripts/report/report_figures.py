"""Figure generators: vector PDFs in report/figures/ plus a LaTeX fragment per figure.

matplotlib only, grayscale-safe (black/gray, distinct marker shapes), labelled
axes, no titles inside the plot. Plotted values are read through Asset.val().
"""
from __future__ import annotations

import re

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

from report_common import FIGURES, ROOT, MissingSource, tex  # noqa: E402
from report_tables import CATEGORIES, HEADER, V2, primary_ci, primary_fields, v2_rows  # noqa: E402

plt.rcParams.update({"font.size": 8, "axes.spines.top": False, "axes.spines.right": False,
                     "pdf.fonttype": 42, "savefig.bbox": "tight"})
WIDTH = 6.3  # inches, A4 text width at the report's margins


def save(fig, name: str) -> None:
    fig.savefig(FIGURES / name, metadata={"CreationDate": None})
    plt.close(fig)


def fragment(pdf: str, caption: str, label: str) -> str:
    return (HEADER + "\\begin{figure}[htbp]\n\\centering\n"
            f"\\includegraphics[width=\\linewidth]{{figures/{pdf}}}\n"
            f"\\caption{{{caption}}}\\label{{{label}}}\n\\end{{figure}}\n")


# ── a) forest plot ─────────────────────────────────────────────────────

def fig_forest(a) -> str:
    rows = [r for r in v2_rows(a) if r["category"] != "not re-run"]
    fig, ax = plt.subplots(figsize=(WIDTH, 0.32 * (len(rows) + 2 * len(CATEGORIES)) + 0.6))
    y, ticks, labels, bench_done = 0.0, [], [], False
    for cat in CATEGORIES[:-1]:
        group = [r for r in rows if r["category"] == cat]
        if not group:
            continue
        y -= 0.6
        ticks.append(y)
        labels.append(cat.capitalize())
        for r in group:
            y -= 1
            d, rel = r["d"], r["rel"]
            sf, cf = primary_fields(d)
            s = float(a.val(d[sf], rel, sf, latex=False))
            lo, hi = (float(a.val(v, rel, f"{cf}[{i}]", latex=False)) for i, v in enumerate(primary_ci(d)))
            ax.plot([lo, hi], [y, y], color="black", lw=1.2, label=None)
            ax.plot([s], [y], "o", color="black", ms=4.5)
            ticks.append(y)
            labels.append(" / ".join(r["names"]) + f"  [{d['primary_convention']}]")
            if d.get("nifty50_buy_hold_sharpe") is not None:
                key = "nifty50_buy_hold_sharpe" if sf == "v2_sharpe" else "nifty50_buy_hold_sharpe_zero_rf"
                ew = key.replace("nifty50", "equal_weight")
                ax.plot([float(a.val(d[key], rel, key, latex=False))], [y], "^", mfc="white", mec="black", ms=5.5,
                        label="^NSEI buy-and-hold (gross)" if not bench_done else None)
                ax.plot([float(a.val(d[ew], rel, ew, latex=False))], [y], "s", mfc="white", mec="dimgray", ms=5,
                        label="Equal-weight buy-and-hold (gross)" if not bench_done else None)
                bench_done = True
        y -= 0.4
    ax.axvline(0, color="gray", ls="--", lw=0.8)
    ax.set_ylim(y + 0.2, 0)
    ax.set_yticks(ticks, labels)
    for t, lab in zip(ax.get_yticklabels(), labels):
        if lab.rstrip(".").lower() in CATEGORIES:
            t.set_fontweight("bold")
    ax.tick_params(axis="y", length=0)
    level = int(round(rows[0]["d"]["consistent_bootstrap"]["confidence"] * 100))
    ax.plot([], [], "o-", color="black", ms=4.5, lw=1.2, label=f"Sharpe and {level}% CI")
    ax.set_xlabel(f"Annualised Sharpe ratio, primary convention ({level}% stationary-bootstrap CI)")
    ax.legend(loc="upper right", frameon=False, fontsize=7)
    save(fig, "forest.pdf")
    return fragment("forest.pdf",
                    r"Primary-convention Sharpe ratio with \CILevel\% stationary-bootstrap interval for each distinct "
                    r"re-run configuration, grouped by category. For the K$=$\BasketK{} basket the hollow markers are "
                    r"buy-and-hold benchmarks in the same convention, gross of costs.", "fig:forest")


# ── b) split-brain trace ───────────────────────────────────────────────

TRACE = "specs/tla_engine_models/history/SinglePrimaryPerEpoch.txt"


def parse_trace(a) -> tuple[list[dict], str]:
    text = a.text(TRACE)
    states = []
    for m in re.finditer(r"State (\d+): <([^>]*)>\n((?:/\\ .*\n)+)", text):
        action = "Init" if m.group(2).startswith("Initial") else m.group(2).split()[0]
        vars_ = dict(re.findall(r"/\\ (\w+) = (.+)", m.group(3)))
        states.append({"n": int(m.group(1)), "action": action, **{k: v.strip('"') for k, v in vars_.items()}})
    inv = re.search(r"Invariant (\w+) is violated", text)
    if not states or not inv:
        raise MissingSource(f"no counterexample trace in {TRACE}")
    return states, inv.group(1)


def fig_split_brain(a) -> str:
    states, inv = parse_trace(a)
    fig, ax = plt.subplots(figsize=(WIDTH, 2.3))
    lanes = {"Primary node": 1.0, "Backup node": 0.0}
    for i, s in enumerate(states):
        a.val(s, TRACE, f"State {s['n']}: action, primaryEpoch, backupEpoch, backupRole, missedHeartbeats", latex=False)
        cells = {"Primary node": ("primary" if s["primaryAlive"] == "TRUE" else "down", s["primaryEpoch"], None),
                 "Backup node": (s["backupRole"], s["backupEpoch"], s["missedHeartbeats"])}
        for lane, yy in lanes.items():
            role, epoch, missed = cells[lane]
            text = f"{role}\nepoch {epoch}" + (f"\nmissed {missed}" if missed is not None else "")
            ax.add_patch(FancyBboxPatch((i - 0.38, yy - 0.3), 0.76, 0.6, boxstyle="round,pad=0.02",
                                        fc="0.8" if role == "primary" else "white", ec="black", lw=0.8))
            ax.text(i, yy, text, ha="center", va="center", fontsize=7)
        ax.text(i, 1.45, f"State {s['n']}\n" + re.sub(r"(?<=[a-z])(?=[A-Z])", "\n", s["action"], count=1), ha="center", va="bottom", fontsize=7)
        if i:
            for yy in lanes.values():
                ax.annotate("", (i - 0.4, yy), (i - 0.6, yy), arrowprops=dict(arrowstyle="->", lw=0.7))
    last = len(states) - 1
    ax.text(last + 0.5, 0.5, f"{inv}\nviolated", ha="left", va="center", fontsize=7, fontweight="bold")
    ax.set_xlim(-0.5, last + 2.1)
    ax.set_ylim(-0.45, 2.15)
    ax.set_yticks(list(lanes.values()), list(lanes.keys()))
    ax.set_xticks([])
    ax.set_xlabel("TLC counterexample, one column per state (grey box: node acts as primary)")
    ax.spines[["left", "bottom"]].set_visible(False)
    ax.tick_params(axis="y", length=0)
    save(fig, "split_brain.pdf")
    return fragment("split_brain.pdf",
                    r"The counterexample TLC found in the unfenced replication model (\texttt{history/}), drawn from "
                    r"the recorded trace: the backup misses heartbeats and promotes to the epoch the live primary "
                    r"already holds.", "fig:split-brain")


# ── c) architecture ────────────────────────────────────────────────────

ARCH = "report/architecture.json"


def fig_architecture(a) -> str:
    spec = a.json(ARCH)
    comps = {c["id"]: c for c in spec["components"]}
    headers = {}
    for c in spec["components"]:
        for f in c["files"]:
            if not a.exists(f):
                raise SystemExit(f"{ARCH}: component {c['id']!r} names missing file {f}")
            headers[f.split("/")[-1]] = c["id"]
    for src, dst in spec["edges"]:
        includes = {h for f in comps[src]["files"]
                    for h in re.findall(r'#include "([^"]+)"', (ROOT / f).read_text())}
        if not any(headers.get(h) == dst for h in includes):
            raise SystemExit(f"{ARCH}: edge {src} -> {dst} has no matching #include in {comps[src]['files']}")
        a.val(f"{src}->{dst}", ARCH, "edges (checked against #include)", latex=False)

    # Layout: column = longest path from a source; separate weakly connected groups stacked.
    rank = {cid: 0 for cid in comps}
    for _ in comps:
        for src, dst in spec["edges"]:
            rank[dst] = max(rank[dst], rank[src] + 1)
    group = {cid: cid for cid in comps}

    def find(x):
        while group[x] != x:
            x = group[x]
        return x
    for src, dst in spec["edges"]:
        group[find(src)] = find(dst)
    pos, top = {}, 0.0
    for g in dict.fromkeys(find(c) for c in comps):
        members = [c for c in comps if find(c) == g]
        rows = 0
        for col in sorted({rank[c] for c in members}):
            for i, c in enumerate(m for m in members if rank[m] == col):
                pos[c] = (col * 2.9, top - i * 1.1)
                rows = max(rows, i + 1)
        top -= rows * 1.1 + 0.5
    fig, ax = plt.subplots(figsize=(WIDTH, 0.62 * (-top)))
    for cid, (x, yy) in pos.items():
        c = comps[cid]
        ax.add_patch(FancyBboxPatch((x - 1.15, yy - 0.38), 2.3, 0.76, boxstyle="round,pad=0.02",
                                    fc="0.92", ec="black", lw=0.8))
        files = ", ".join(sorted({f.split("/")[-1].rsplit(".", 1)[0] for f in c["files"]}))
        ax.text(x, yy + 0.1, a.val(c["label"], ARCH, "components[].label", latex=False), ha="center", va="center",
                fontsize=7.5, fontweight="bold")
        ax.text(x, yy - 0.18, a.val(files, ARCH, "components[].files", latex=False), ha="center", va="center",
                fontsize=6.5, family="monospace")
    for src, dst in spec["edges"]:
        (x0, y0), (x1, y1) = pos[src], pos[dst]
        bend = 0.0 if x1 - x0 < 4 else (-0.55 if y0 == y1 else -0.3)  # edges that skip a column arc over it
        ax.annotate("", (x1 - 1.17, y1), (x0 + 1.17, y0),
                    arrowprops=dict(arrowstyle="->", lw=0.8, shrinkA=0, shrinkB=0,
                                    connectionstyle=f"arc3,rad={bend}"))
    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    ax.set_xlim(min(xs) - 1.25, max(xs) + 1.25)
    ax.set_ylim(min(ys) - 0.5, max(ys) + 1.0)
    ax.axis("off")
    save(fig, "architecture.pdf")
    return fragment("architecture.pdf",
                    r"Engine components in \texttt{engine/src/} and their include dependencies (arrow: uses), "
                    r"generated from \texttt{report/architecture.json}; every arrow is checked against an "
                    r"\texttt{\#include}. Components with no arrow between them share no include.",
                    "fig:architecture")


# ── d) cost drag vs K ──────────────────────────────────────────────────

def fig_cost_drag(a) -> str:
    rels = sorted((p.relative_to(ROOT).as_posix() for p in (ROOT / V2).glob("experiment_8_k*.json")),
                  key=lambda r: int(re.search(r"k(\d+)", r).group(1)))
    if not rels:
        raise MissingSource("no research/v2/experiment_8_k*.json (would fall back to v1 data)")
    ks, series = [], {"gross_pnl": [], "total_costs": [], "net_pnl": []}
    for rel in rels:
        d = a.json(rel)
        ks.append(int(a.val(d["parameters"]["k"], rel, "parameters.k", latex=False)))
        for key in series:
            series[key].append(float(a.val(d["raw_backtest"][key], rel, f"raw_backtest.{key}", latex=False)))
    fig, ax = plt.subplots(figsize=(WIDTH * 0.62, 2.4))
    styles = {"gross_pnl": ("o-", "black", "Gross P&L"), "total_costs": ("s--", "dimgray", "Modelled costs"),
              "net_pnl": ("^-", "black", "Net P&L")}
    for key, vals in series.items():
        fmt, color, label = styles[key]
        ax.plot(ks, vals, fmt, color=color, mfc="white" if key == "net_pnl" else color, ms=5, lw=1, label=label)
    ax.axhline(0, color="gray", lw=0.6)
    ax.set_xticks(ks)
    ax.set_xlabel("Positions per leg, K")
    ax.set_ylabel("Amount over test window\n(backtest currency units)")
    ax.legend(frameon=False, fontsize=7)
    save(fig, "cost_drag.pdf")
    files = ", ".join(r"\texttt{" + tex(r.split("/")[-1]) + "}" for r in rels)
    for r in rels:
        a.val(tex(r.split("/")[-1]), r, "file name", latex=False)
    return fragment("cost_drag.pdf",
                    r"Gross P\&L, modelled costs and net P\&L against positions per leg on the frozen-data rerun "
                    r"(not v1 data); from " + files + ".", "fig:cost-drag")


GENERATORS = [
    ("generated/fig_forest.tex", fig_forest),
    ("generated/fig_split_brain.tex", fig_split_brain),
    ("generated/fig_architecture.tex", fig_architecture),
    ("generated/fig_cost_drag.tex", fig_cost_drag),
]
