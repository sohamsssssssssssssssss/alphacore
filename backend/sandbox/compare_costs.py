"""
Cost-comparison report — backtest-assumed vs sandbox-observed.

Reads the append-only JSONL logs written by harness.py
(logs/rebalance_*.jsonl) and produces:

  * per-leg table: assumed cost (INR + bps) vs observed slippage/fees/fill
  * aggregate totals and the verdict against the PRECOMMITTED HYPOTHESIS.

Observability note (honest): the Upstox sandbox currently exposes ONLY order
place/modify/cancel endpoints — order-history/trades are not sandbox-enabled.
So a leg's fill evidence is whatever the API returned (place response fields,
or history/trades poll responses if Upstox has enabled them by run time).
Legs with no fill data are reported as UNCONFIRMED and are excluded from
observed-cost totals; they are NEVER approximated.

Run from backend/:
    python3.11 -m sandbox.compare_costs [--logs-dir backend/sandbox/logs]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from datetime import datetime

# Make sibling modules importable when run as `python -m sandbox.compare_costs`
# from backend/ (mirrors conftest.py; keeps absolute imports consistent).
_SANDBOX_DIR = os.path.dirname(os.path.abspath(__file__))
if _SANDBOX_DIR not in sys.path:
    sys.path.insert(0, _SANDBOX_DIR)

from costs import BACKTEST_ASSUMED_COST_PARAMS, cost_in_bps, observed_slippage_bps
from basket_hypothesis import BASKET_HYPOTHESIS_HEADER

LOGS_DIR_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")


def load_records(logs_dir: str) -> list[dict]:
    records: list[dict] = []
    for path in sorted(glob.glob(os.path.join(logs_dir, "rebalance_*.jsonl"))):
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    print(f"[WARN] skipped malformed line in {path}: {exc}")
    return records


def build_report(records: list[dict]) -> str:
    legs = [r for r in records if r.get("event") == "order_leg"]
    sessions = [r for r in records if r.get("event") == "session"]

    lines: list[str] = []
    w = lines.append

    w(BASKET_HYPOTHESIS_HEADER)
    w("")
    w("# AlphaCore top-quartile basket (k=12) — Backtest-assumed vs Sandbox-observed execution costs")
    w("")
    w(f"Report generated: {datetime.now().astimezone().isoformat(timespec='seconds')}")
    w("")
    w(f"Rebalance sessions in log: {len(sessions)} | order legs logged: {len(legs)}")
    w("")
    w("## Backtest-assumed cost parameters (used by the Phase 1/2 basket backtest baseline)")
    w("")
    w("| parameter | value |")
    w("|---|---|")
    for k, v in BACKTEST_ASSUMED_COST_PARAMS.items():
        w(f"| {k} | {v} |")
    w("")
    w("> These mirror backend/engines/cost_model.py defaults (k_impact=0.0015, "
      "brokerage Rs 20/trade, STT 0.1% sell-side) plus the 10 bps assumed half-spread. "
      "They are printed on every run so drift is visible.")
    w("")

    if not legs:
        w("No order legs found in the logs. Run the harness (live-sandbox mode) first: ")
        w("`python3.11 -m sandbox.harness --rebalance-date YYYY-MM-DD`")
        return "\n".join(lines)

    w("## Per-leg comparison")
    w("")
    w("| rebalance | symbol | side | qty | ref_price | fill_price | fill_status | assumed INR | assumed bps | observed slip bps | observed fees INR |")
    w("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in legs:
        assumed_inr = float(r.get("assumed_cost_inr") or 0.0)
        assumed_bps = float(r.get("assumed_cost_bps") or 0.0)
        slip = r.get("observed_slippage_bps")
        slip_txt = f"{slip:.2f}" if slip is not None else "—"
        fees = r.get("observed_fees_inr")
        fees_txt = f"{fees:.2f}" if fees is not None else "—"
        fill_px = r.get("fill_price")
        fill_txt = f"{fill_px:.2f}" if fill_px is not None else "—"
        w(f"| {r.get('rebalance_date')} | {r.get('symbol')} | {r.get('side')} | {r.get('qty')} | "
          f"{r.get('ref_price')} | {fill_txt} | {r.get('fill_status')} | "
          f"{assumed_inr:.2f} | {assumed_bps:.2f} | {slip_txt} | {fees_txt} |")
    w("")

    confirmed = [r for r in legs if r.get("fill_price") is not None]
    unconfirmed = [r for r in legs if r.get("fill_price") is None]
    total_assumed = sum(float(r.get("assumed_cost_inr") or 0.0) for r in legs)
    total_assumed_bps = sum(float(r.get("assumed_cost_bps") or 0.0) for r in legs)
    observed_total_inr = 0.0
    observed_total_bps = 0.0
    for r in confirmed:
        price = float(r.get("ref_price") or 0.0)
        qty = float(r.get("qty") or 0.0)
        slip_bps = observed_slippage_bps(float(r["fill_price"]), price, r.get("side", "BUY"))
        observed_total_bps += slip_bps
        observed_total_inr += slip_bps / 10000.0 * price * qty
        if r.get("observed_fees_inr") is not None:
            observed_total_inr += float(r["observed_fees_inr"])

    w("## Aggregates")
    w("")
    w(f"- Legs with sandbox-observed fill evidence: **{len(confirmed)}** of {len(legs)}")
    w(f"- Legs with fill_status=UNCONFIRMED (sandbox returned no fill data): **{len(unconfirmed)}** "
      "(excluded from observed totals; their raw API responses are in the JSONL/raw logs)")
    w(f"- Total backtest-assumed cost: **{total_assumed:,.2f} INR** ({total_assumed_bps:.2f} bps)")
    w(f"- Total sandbox-observed cost (slippage+fees, confirmed legs only): **{observed_total_inr:,.2f} INR** "
      f"({observed_total_bps:.2f} bps)")
    if total_assumed > 0 and confirmed:
        ratio = observed_total_bps / total_assumed_bps if total_assumed_bps else float("nan")
        w(f"- Observed/assumed ratio (bps): **{ratio:.2f}x**")
    w("")

    w("## Verdict vs pre-committed hypothesis")
    w("")
    if not confirmed:
        w("**INCONCLUSIVE** — the sandbox exposed no fill data for any leg (order-history/trades are not "
          "yet sandbox-enabled). The hypothesis can only be evaluated once fills are observable. "
          "Nothing was synthesized to fill this gap.")
    else:
        higher = observed_total_bps > total_assumed_bps
        ratio = observed_total_bps / total_assumed_bps if total_assumed_bps else float("nan")
        w("- Basket hypothesis: sandbox-observed costs are expected to land **closer to backtest-assumed** "
          "than the K=1 case (fixed costs amortised across 12 equal-weighted names; ADV-scaled impact "
          "roughly unchanged per leg). Only a systematic EXCESS over assumed costs falsifies it.")
        w(f"- Observed: {observed_total_bps:.2f} bps vs assumed {total_assumed_bps:.2f} bps "
          f"({'HIGHER' if higher else 'LOWER'} on confirmed legs; {ratio:.2f}x assumed).")
        if higher:
            w("- **HYPOTHESIS FALSIFIED (on observed legs)** — sandbox costs came out systematically higher "
              "than assumed; execution-level costs erode even the diversified basket (the same "
              "cost-dominance pattern as K=1, just at smaller scale). Caveat: sandbox emulated fills do "
              "not include live adverse selection.")
        else:
            w("- **HYPOTHESIS SUPPORTED (on observed legs)** — sandbox-observed costs are within/near the "
              "backtest-assumed baseline, so the basket's assumed-cost estimate is a trustworthy proxy "
              "for execution reality. Caveat: sandbox emulated fills do not include live adverse "
              "selection.")
    w("")
    w("## Raw evidence")
    w("")
    w("Every order's verbatim request/response is in `logs/raw_api_*.txt` and the JSONL files "
      "(`logs/rebalance_*.jsonl`) — including rejected orders and any poll responses.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="AlphaCore top-quartile basket cost comparison report")
    p.add_argument("--logs-dir", default=LOGS_DIR_DEFAULT)
    p.add_argument("--out", default=None, help="Write the markdown report to this path too.")
    args = p.parse_args(argv)

    records = load_records(args.logs_dir)
    report = build_report(records)
    print(report)

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(report + "\n")
        print(f"\n[REPORT] written -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
