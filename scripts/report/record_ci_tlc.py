"""Record TLC results from a GitHub Actions CI run into report/data/ci_tlc.json.

The report generator reads only tracked files, so CI model-checking output is
captured here once (with the run id and commit) rather than typed by hand.
Usage: python scripts/report/record_ci_tlc.py <run_id>
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "report" / "data" / "ci_tlc.json"
CMD = re.compile(r"cd (specs/\S+)|tlc2\.TLC (\S+\.tla) -config (\S+\.cfg)")
DONE = re.compile(r"(\d+) states generated, (\d+) distinct states found, (\d+) states left")


def ci_commands() -> list[dict]:
    """TLC invocations in .github/workflows/ci.yml, in execution order."""
    cwd, out = None, []
    for line in (ROOT / ".github/workflows/ci.yml").read_text().splitlines():
        for m in CMD.finditer(line):
            if m.group(1):
                cwd = m.group(1)
            else:
                out.append({"dir": cwd, "spec": m.group(2), "config": m.group(3)})
    return out


def main(run_id: str) -> None:
    meta = json.loads(subprocess.check_output(
        ["gh", "run", "view", run_id, "--json", "headSha,createdAt,url,conclusion,jobs"], cwd=ROOT))
    job = next(j for j in meta["jobs"] if j["name"] == "tla")
    log = subprocess.check_output(["gh", "run", "view", run_id, "--log", "--job", str(job["databaseId"])],
                                  cwd=ROOT, text=True)
    results = []
    for line in log.splitlines():
        if "Model checking completed. No error has been found." in line:
            results.append({"result": "no error"})
        elif "Error: Invariant" in line or "is violated" in line:
            results.append({"result": line.split("Z ", 1)[-1].strip()})
        m = DONE.search(line)
        if m and results:
            results[-1].update(generated=int(m.group(1)), distinct=int(m.group(2)), left=int(m.group(3)))
    cmds = ci_commands()
    if len(cmds) != len(results):
        raise SystemExit(f"{len(cmds)} TLC commands in ci.yml but {len(results)} results in the log")
    OUT.write_text(json.dumps({
        "source": "GitHub Actions tla job log, extracted by scripts/report/record_ci_tlc.py",
        "run_id": int(run_id), "url": meta["url"], "head_sha": meta["headSha"],
        "created_at": meta["createdAt"], "job_conclusion": job["conclusion"],
        "models": [{**c, **r} for c, r in zip(cmds, results)],
    }, indent=2) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(results)} models)")


if __name__ == "__main__":
    main(sys.argv[1])
