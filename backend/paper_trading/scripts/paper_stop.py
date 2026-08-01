"""Kill switch — stop the scheduler cleanly.

Writes states/paper_trading/KILL. The scheduler checks for this file every
cycle and shuts down gracefully (finishing nothing mid-order: it stops at the
next cycle boundary). Also safe to SIGTERM the scheduler process directly.

Restart afterwards by deleting the KILL file and re-running the scheduler.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from paper_trading import config  # noqa: E402


def main() -> int:
    state_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else config.STATE_DIR
    config.KILL_FILE = state_dir / "KILL"
    config.KILL_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.KILL_FILE.write_text("")
    print(f"Kill switch written to {config.KILL_FILE}")
    print("The scheduler will stop at its next cycle boundary.")
    print("To restart: delete the KILL file, then re-run the scheduler.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
