"""Run the test suites once and record their counts in report/data/test_counts.json.

Python suites use the same pytest command as `make py-test` (one run per suite
directory, counts from JUnit XML). C++ suites are the executables run by
`make engine-test`; each is recorded as pass/fail by exit code because the
binaries do not share a test-count format. Requires `make engine-build` first.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import reproduce  # noqa: E402  (shares RELEASE/TSAN paths and test lists with `make`)

OUT = ROOT / "report" / "data" / "test_counts.json"
PY_SUITES = ["tests/", "sandbox/tests/", "../scripts/tests/"]
CPP_RELEASE = ["engine_test", "replication_test", "gateway_test", "fault_test", "ha_chaos_test",
               "deterministic_replay_test", "split_brain_counterexample", "fencing_test"]
CPP_TSAN = ["mpsc_tsan_test", "fencing_tsan_test"]


def py_suite(path: str) -> dict:
    env = os.environ | {"PYTHONPATH": str(reproduce.RELEASE) + os.pathsep + str(ROOT / "backend")}
    with tempfile.TemporaryDirectory() as tmp:
        xml = Path(tmp) / "junit.xml"
        proc = subprocess.run([sys.executable, "-m", "pytest", path, "-m", "not benchmark", "-q",
                               f"--junitxml={xml}"], cwd=ROOT / "backend", env=env)
        suites = ET.parse(xml).getroot()
        s = suites if suites.tag == "testsuite" else suites.find("testsuite")
        tests, skipped = int(s.get("tests")), int(s.get("skipped"))
        failed = int(s.get("failures")) + int(s.get("errors"))
    return {"suite": f"backend/{path}".replace("backend/../", ""), "kind": "pytest",
            "passed": tests - skipped - failed, "skipped": skipped, "failed": failed,
            "exit_code": proc.returncode}


def cpp_suite(build: Path, name: str) -> dict:
    # Same environment as `make engine-test`: fault flags for the Release binaries only.
    faults = {"OB_FAULT_POOL_EXHAUSTION": "1", "OB_FAULT_QUEUE_FULL": "1"} if build == reproduce.RELEASE else {}
    env = os.environ | faults
    try:
        code = subprocess.run([build / name], cwd=reproduce.SCRATCH, env=env, timeout=300).returncode
    except subprocess.TimeoutExpired:
        return {"suite": name, "kind": "C++ executable", "exit_code": None, "result": "timeout (300 s)"}
    return {"suite": name, "kind": "C++ executable", "exit_code": code, "result": "pass" if code == 0 else "fail"}


def main() -> int:
    suites = [py_suite(p) for p in PY_SUITES]
    suites += [cpp_suite(reproduce.RELEASE, n) for n in CPP_RELEASE]
    suites += [cpp_suite(reproduce.TSAN, n) for n in CPP_TSAN]
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    OUT.write_text(json.dumps({
        "source": "fresh local run by scripts/report/record_test_counts.py",
        "recorded_at": datetime.now(timezone.utc).isoformat(), "commit": commit,
        "machine": platform.platform(), "python": platform.python_version(),
        "suites": suites,
    }, indent=2) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return int(any(s["exit_code"] != 0 for s in suites))


if __name__ == "__main__":
    sys.exit(main())
