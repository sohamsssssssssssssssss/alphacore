#!/usr/bin/env python3
"""
Diagnostic: Verify NSGA-II vs Equal weights are actually applied differently.

For 2 of the "4 identical" symbols (TCS, INFY), prints raw signal values,
weights, combined values, and direction decisions for 30 consecutive days
side by side for both arms.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engines.backtester import (
    Snapshot,
    _get_direction,
    _mean_reversion_signal,
    _momentum_signal,
    _ofi_signal,
)

# ── Load data ──────────────────────────────────────────────────────────────

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "real_nse_data"
TEST_START_INDEX = 867  # 70% of 1239 rows

import pandas as pd

def load_test_snapshots(symbol: str) -> list[Snapshot]:
    path = DATA_DIR / f"{symbol}.csv"
    df = pd.read_csv(path, parse_dates=["Date"])
    df = df.sort_values("Date").reset_index(drop=True)
    test_raw = df.iloc[TEST_START_INDEX:]

    snaps = []
    for _, row in test_raw.iterrows():
        date = row["Date"]
        high = float(row["High"])
        low = float(row["Low"])
        close = float(row["Close"])
        volume = float(row["Volume"])

        if pd.isna(close) or close <= 0:
            continue

        mid = close
        daily_range = high - low if high > low and low > 0 else 0.0
        spread_bps = (daily_range / mid) * 10000.0 if mid > 0 else 5.0
        spread_bps = max(0.5, min(50.0, spread_bps))

        spread_abs = (spread_bps / 10000.0) * mid
        bid = mid - spread_abs / 2.0
        ask = mid + spread_abs / 2.0
        if bid >= ask:
            ask = bid + 1e-6

        bid_volume = volume * 0.5
        ask_volume = volume * 0.5

        snaps.append(Snapshot(
            timestamp=str(date),
            symbol=symbol.upper(),
            bid_price=round(bid, 2),
            ask_price=round(ask, 2),
            bid_volume=float(bid_volume),
            ask_volume=float(ask_volume),
            mid_price=float(mid),
            spread_bps=float(spread_bps),
        ))
    return snaps


# ── Weighted signal (exact copy from real_data_validation.py) ─────────────

def weighted_combined_signal(snapshots: list[Snapshot], idx: int, weights: list[float]) -> float:
    mom = _momentum_signal(snapshots, idx)
    mr = _mean_reversion_signal(snapshots, idx)
    ofi = _ofi_signal(snapshots[idx])

    mom_n = max(-1.0, min(1.0, mom / 10.0))
    mr_n = max(-1.0, min(1.0, mr / 3.0))
    ofi_n = max(-1.0, min(1.0, ofi))

    w = list(weights)
    w_sum = sum(w)
    if w_sum <= 0:
        w = [1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0]
        w_sum = 1.0

    val = (w[0] * mom_n + w[1] * mr_n + w[2] * ofi_n) / w_sum
    return float(max(-1.0, min(1.0, val))), {
        "mom_raw": mom,
        "mr_raw": mr,
        "ofi_raw": ofi,
        "mom_n": mom_n,
        "mr_n": mr_n,
        "ofi_n": ofi_n,
        "weights_used": w,
        "w_sum": w_sum,
    }


# ── Config ─────────────────────────────────────────────────────────────────

NSGAII_WEIGHTS = [0.5425832619873837, 3.520675273047467e-12, 0.45741673800909555]
EQUAL_WEIGHTS = [1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0]
N_DAYS = 30  # sample size
SYMBOLS_TO_CHECK = ["TCS", "INFY"]  # two of the "identical" symbols


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    print("=" * 100)
    print("DIAGNOSTIC: Are NSGA-II and Equal weights actually being applied differently?")
    print("=" * 100)

    for symbol in SYMBOLS_TO_CHECK:
        print(f"\n{'#' * 100}")
        print(f"# SYMBOL: {symbol}")
        print(f"{'#' * 100}")

        snaps = load_test_snapshots(symbol)
        print(f"Test snapshots loaded: {len(snaps)} days ({snaps[0].timestamp} to {snaps[-1].timestamp})")
        print()

        # Header
        hdr = (f"{'Day':>4} {'Date':>14} "
               f"{'mom_raw':>10} {'mr_raw':>10} {'ofi_raw':>10} "
               f"{'mom_n':>8} {'mr_n':>8} {'ofi_n':>8} "
               f"{'W_A[0]':>8} {'W_A[1]':>8} {'W_A[2]':>8} "
               f"{'W_B[0]':>8} {'W_B[1]':>8} {'W_B[2]':>8} "
               f"{'val_A':>8} {'val_B':>8} {'diff':>8} "
               f"{'dir_A':>6} {'dir_B':>6} {'match?':>6}")
        print(hdr)
        print("-" * len(hdr))

        diff_count = 0
        total = 0

        for day_idx in range(min(N_DAYS, len(snaps))):
            idx = day_idx + 20  # skip first 20 days so momentum/mean-rev windows are populated

            if idx >= len(snaps):
                break

            snap = snaps[idx]
            date = snap.timestamp[:10]

            # Arm A
            val_a, detail_a = weighted_combined_signal(snaps, idx, NSGAII_WEIGHTS)
            dir_a = _get_direction(val_a, "combined")

            # Arm B
            val_b, detail_b = weighted_combined_signal(snaps, idx, EQUAL_WEIGHTS)
            dir_b = _get_direction(val_b, "combined")

            # Extract details
            mom_raw = detail_a["mom_raw"]
            mr_raw = detail_a["mr_raw"]
            ofi_raw = detail_a["ofi_raw"]
            mom_n = detail_a["mom_n"]
            mr_n = detail_a["mr_n"]
            ofi_n = detail_a["ofi_n"]

            wa = detail_a["weights_used"]
            wb = detail_b["weights_used"]

            diff = val_a - val_b
            match = "YES" if dir_a == dir_b else "NO"
            if dir_a != dir_b:
                diff_count += 1
            total += 1

            # Print a blank line before the OBSERVATION header on first day
            if day_idx == 0:
                print()

            print(f"{day_idx:>4} {date:>14} "
                  f"{mom_raw:>10.4f} {mr_raw:>10.4f} {ofi_raw:>10.4f} "
                  f"{mom_n:>8.4f} {mr_n:>8.4f} {ofi_n:>8.4f} "
                  f"{wa[0]:>8.6f} {wa[1]:>8.6f} {wa[2]:>8.6f} "
                  f"{wb[0]:>8.6f} {wb[1]:>8.6f} {wb[2]:>8.6f} "
                  f"{val_a:>8.4f} {val_b:>8.4f} {diff:>+8.4f} "
                  f"{str(dir_a or 'NONE'):>6} {str(dir_b or 'NONE'):>6} {match:>6}")

            # Show computation details for first few days
            if day_idx < 3:
                print(f"       └─ Arm A: {wa[0]:.4f}*{mom_n:.4f} + {wa[1]:.4f}*{mr_n:.4f} + {wa[2]:.4f}*{ofi_n:.4f} = {val_a:.4f}")
                print(f"       └─ Arm B: {wb[0]:.4f}*{mom_n:.4f} + {wb[1]:.4f}*{mr_n:.4f} + {wb[2]:.4f}*{ofi_n:.4f} = {val_b:.4f}")
                print(f"       └─ Direction threshold: ±0.15. A={dir_a or 'NONE'}, B={dir_b or 'NONE'}")

        print("-" * len(hdr))
        print()
        print(f"OBSERVATION for {symbol}:")
        print(f"  Total days checked: {total}")
        print(f"  Days with DIFFERENT direction decisions: {diff_count} / {total}")
        print()

        # Count how many times pre-threshold combined values differ
        # Re-run to check numerical difference
        diff_vals = []
        for day_idx in range(min(N_DAYS, len(snaps))):
            idx = day_idx + 20
            if idx >= len(snaps):
                break
            val_a, _ = weighted_combined_signal(snaps, idx, NSGAII_WEIGHTS)
            val_b, _ = weighted_combined_signal(snaps, idx, EQUAL_WEIGHTS)
            diff_vals.append(val_a - val_b)

        nonzero_diffs = sum(1 for d in diff_vals if abs(d) > 1e-10)
        print(f"  Days where pre-threshold values differ (nonzero diff): {nonzero_diffs} / {len(diff_vals)}")
        print(f"  Mean pre-threshold absolute diff: {sum(abs(d) for d in diff_vals) / len(diff_vals):.6f}")
        print(f"  Max pre-threshold abs diff: {max(abs(d) for d in diff_vals):.6f}")
        print(f"  Min pre-threshold abs diff (non-zero only): {min(abs(d) for d in diff_vals if abs(d) > 1e-10):.8e}")

        # Bit-level identity check
        bit_identical = all(abs(d) < 1e-15 for d in diff_vals)
        if bit_identical:
            print(f"\n  ⚠ BIT-LEVEL IDENTITY DETECTED: All pre-threshold values match to machine precision.")
            print(f"     This would indicate the weights are NOT being applied differently.")
        else:
            print(f"\n  ✅ NUMERICALLY DIFFERENT: Pre-threshold values ARE different (weights are applied correctly).")
            print(f"     The threshold (±0.15) is simply too coarse to make the difference matter.")

    # ── Show the actual computation line-by-line for one specific day ──
    print()
    print("=" * 100)
    print("DETAILED COMPUTATION WALKTHROUGH (INFY, day 0)")
    print("=" * 100)
    print()

    snaps = load_test_snapshots("INFY")
    idx = 20
    snap = snaps[idx]

    # Raw signals
    mom = _momentum_signal(snaps, idx)
    mr = _mean_reversion_signal(snaps, idx)
    ofi = _ofi_signal(snaps[idx])

    print(f"Snapshot date: {snap.timestamp[:10]}")
    print(f"Mid price: {snap.mid_price:.2f}")
    print(f"Bid volume: {snap.bid_volume:.0f}, Ask volume: {snap.ask_volume:.0f}")
    print()
    print(f"Raw momentum:           {mom:.6f}")
    print(f"Raw mean-reversion:     {mr:.6f}")
    print(f"Raw OFI:                {ofi:.6f}")  # Will be 0.0
    print()
    print(f"Normalized momentum (clip(mom/10)):    {max(-1.0, min(1.0, mom/10.0)):.6f}")
    print(f"Normalized mean-rev (clip(mr/3)):      {max(-1.0, min(1.0, mr/3.0)):.6f}")
    print(f"Normalized OFI (clip(ofi)):            {max(-1.0, min(1.0, ofi)):.6f}")
    print()
    print(f"Arm A weights:    [{NSGAII_WEIGHTS[0]:.6f}, {NSGAII_WEIGHTS[1]:.6f}, {NSGAII_WEIGHTS[2]:.6f}]")
    print(f"Arm B weights:    [{EQUAL_WEIGHTS[0]:.6f}, {EQUAL_WEIGHTS[1]:.6f}, {EQUAL_WEIGHTS[2]:.6f}]")
    print()

    mom_n = max(-1.0, min(1.0, mom / 10.0))
    mr_n = max(-1.0, min(1.0, mr / 3.0))
    ofi_n = max(-1.0, min(1.0, ofi))

    val_a = (NSGAII_WEIGHTS[0] * mom_n + NSGAII_WEIGHTS[1] * mr_n + NSGAII_WEIGHTS[2] * ofi_n) / sum(NSGAII_WEIGHTS)
    val_b = (EQUAL_WEIGHTS[0] * mom_n + EQUAL_WEIGHTS[1] * mr_n + EQUAL_WEIGHTS[2] * ofi_n) / sum(EQUAL_WEIGHTS)

    print(f"Arm A combined: {NSGAII_WEIGHTS[0]:.4f} × {mom_n:.4f} + {NSGAII_WEIGHTS[1]:.4f} × {mr_n:.4f} + {NSGAII_WEIGHTS[2]:.4f} × {ofi_n:.4f}")
    print(f"              = {NSGAII_WEIGHTS[0] * mom_n:.6f} + {NSGAII_WEIGHTS[1] * mr_n:.6f} + {NSGAII_WEIGHTS[2] * ofi_n:.6f}")
    print(f"              = {val_a:.6f}")
    print(f"  Direction: {_get_direction(val_a, 'combined') or 'NONE'}")
    print()
    print(f"Arm B combined: {EQUAL_WEIGHTS[0]:.4f} × {mom_n:.4f} + {EQUAL_WEIGHTS[1]:.4f} × {mr_n:.4f} + {EQUAL_WEIGHTS[2]:.4f} × {ofi_n:.4f}")
    print(f"              = {EQUAL_WEIGHTS[0] * mom_n:.6f} + {EQUAL_WEIGHTS[1] * mr_n:.6f} + {EQUAL_WEIGHTS[2] * ofi_n:.6f}")
    print(f"              = {val_b:.6f}")
    print(f"  Direction: {_get_direction(val_b, 'combined') or 'NONE'}")
    print()
    diff = val_a - val_b
    print(f"Pre-threshold difference (A − B): {diff:.8e}")
    print(f"Direction threshold: ±0.15")
    if abs(diff) < 1e-15:
        print(f"\n⚠ DIFFERENCE IS ZERO TO MACHINE PRECISION → BUG: weights NOT being applied differently")
    elif abs(diff) < 0.30:
        print(f"\n✅ DIFFERENCE IS REAL but smaller than threshold range (0.30): both arms may cross threshold together")
    else:
        print(f"\n✅ DIFFERENCE IS REAL AND LARGE: threshold crossing should differ between arms")


if __name__ == "__main__":
    main()
