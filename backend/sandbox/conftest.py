"""Pytest bootstrap: make the sandbox package importable from any cwd.

Tests use absolute imports (`from costs import ...`, `from harness import ...`),
which requires backend/sandbox/ on sys.path. This conftest guarantees that.
"""

import os
import sys

_SANDBOX_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_SANDBOX_DIR), "experiments"))
if _SANDBOX_DIR not in sys.path:
    sys.path.insert(0, _SANDBOX_DIR)
