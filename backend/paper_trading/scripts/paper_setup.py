"""One-time setup helper — credentials scaffold and instructions.

Does NOT touch the network and NEVER places orders. Creates:
  - backend/paper_trading/.env.example (if missing)
  - states/paper_trading/ directory structure

Then prints the exact steps Soham must follow to generate the sandbox token.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

ENV_EXAMPLE = """# AlphaCore paper-trading credentials — SANDBOX ONLY
# Copy this file to .env (same directory) and fill in the values.
# .env is gitignored. NEVER put live-trading credentials here.

# Sandbox token: account.upstox.com/developer/apps#sandbox -> Generate
# Valid 30 days. NO refresh flow exists for sandbox tokens (verified in
# Step 0) — when it expires the scheduler alerts and you regenerate.
PAPER_SANDBOX_TOKEN=
PAPER_SANDBOX_TOKEN_EXPIRY=        # optional ISO/epoch of generation+30d, for alerts

# Read-only market-data token (live host). Upstox sandbox provides NO market
# data. Options, in order of preference:
#   a) Analytics token from your LIVE app (account.upstox.com/developer/apps,
#      Analytics tab) — read-only, ~1yr validity. Recommended.
#   b) Live OAuth access token — expires daily 3:30 AM IST; tedious.
# Read-only quotes never touch capital and are explicitly allowed by the
# experiment design. NEVER used for orders.
PAPER_MARKETDATA_TOKEN=
PAPER_MARKETDATA_TOKEN_EXPIRY=

# Optional — do not change unless you know what you are doing
# PAPER_SANDBOX_URL=https://sandbox.upstox.com   (refuses anything else)
# PAPER_STATE_DIR=states/paper_trading

# Optional Slack alerts (repo convention: backend/monitoring/health_check.py)
# SLACK_WEBHOOK_URL=
"""


def main() -> int:
    env_dir = REPO_ROOT / "backend" / "paper_trading"
    example = env_dir / ".env.example"
    if not example.exists():
        example.write_text(ENV_EXAMPLE)
        print(f"Created {example}")
    else:
        print(f"{example} already exists — leaving it untouched")

    state_dir = REPO_ROOT / "states" / "paper_trading"
    for sub in ("logs",):
        (state_dir / sub).mkdir(parents=True, exist_ok=True)
    print(f"State dir ready: {state_dir}")

    print()
    print("NEXT STEPS (must be done by a human with the Upstox account):")
    print("  1. Visit https://account.upstox.com/developer/apps#sandbox")
    print("  2. Create the SANDBOX app (one per user; separate from live app)")
    print("  3. Click Generate to get the sandbox access token (30-day validity)")
    print("  4. Copy backend/paper_trading/.env.example -> .env and paste the")
    print("     sandbox token into PAPER_SANDBOX_TOKEN")
    print("  5. For market data: generate the Analytics token from your LIVE app")
    print("     page and paste into PAPER_MARKETDATA_TOKEN")
    print()
    print("  6. Verify:  python3.11 backend/paper_trading/scripts/verify_connectivity.py")
    print("  7. Run:     python3.11 backend/paper_trading/scheduler.py   (or --dry-run)")
    print("     Status:  python3.11 backend/paper_trading/scripts/paper_status.py")
    print("     Stop:    python3.11 backend/paper_trading/scripts/paper_stop.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
