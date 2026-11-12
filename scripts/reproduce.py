#!/usr/bin/env python3.11
"""Run unchanged experiments in disposable copies; never write research outputs."""
from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import pickle
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / ".reproduce"
RELEASE = SCRATCH / "engine-release"
TSAN = SCRATCH / "engine-tsan"
K12_INPUT = SCRATCH / "k12-input.pkl"
OUTPUTS = {
    "cross_sectional_experiment": "cross_sectional_results.json",
    "cross_sectional_diagnostic": "cross_sectional_diagnostic_results.json",
    "monthly_rebalance_test": "cross_sectional_monthly_results.json",
    "universe_expansion_experiment": "universe_expansion_results.json",
    "k_expansion_experiment": "k_expansion_results.json",
    "intraday_signal_experiment": "intraday_signal_results.json",
    "overnight_gap_experiment": "overnight_gap_results.json",
    "weight_comparison": "weight_comparison_results.json",
    "real_data_validation": "../backend/real_data_results.json",
}
BLOCKED = {
    "run_real_backtest": "driver reselects NSGA-II weights; prohibited by no-tuning rule",
    "run_real_data_experiment": "driver reselects NSGA-II weights; prohibited by no-tuning rule",
}
MODELS = [
    ("MpscQueue", "ModelMpsc_tiny"),
    ("MatchingEngine", "ModelMatching_small2"),
    ("OrderBook", "ModelOrderBook_small3"),
    ("PrimaryBackup", "ModelPrimaryBackup"),
]


def run(args, *, cwd=ROOT, **kwargs):
    return subprocess.run([str(x) for x in args], cwd=cwd, check=True, **kwargs)


def workspace(prefix):
    SCRATCH.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=prefix, dir=SCRATCH))
    shutil.copytree(ROOT / "backend", work / "backend", ignore=shutil.ignore_patterns(
        "__pycache__", ".pytest_cache", ".hypothesis", "venv", ".venv", "logs", "*.so", "*.pyc", "*.csv", "*.db"))
    shutil.copytree(ROOT / "research", work / "research")
    return work


def metric_values(value, path=()):
    """Select actual scalar metrics, excluding timestamps and raw return arrays."""
    result = {}
    if isinstance(value, dict):
        for key, child in value.items():
            result.update(metric_values(child, path + (key,)))
    elif isinstance(value, list):
        if path and ("ci" in path[-1].lower() or "confidence_interval" in path[-1].lower()):
            for i, child in enumerate(value):
                result.update(metric_values(child, path + (str(i),)))
    elif isinstance(value, (int, float)) and not isinstance(value, bool) and path:
        key = path[-1].lower()
        parent = path[-2].lower() if len(path) > 1 else ""
        if ("sharpe" in key or key in {"ci_lower", "ci_upper", "net_pnl", "total_pnl", "total_trades", "n_trades", "trades"}
                or (key.isdigit() and ("ci" in parent or "confidence_interval" in parent))):
            result[".".join(path)] = value
    return result


def basket_output(text):
    for line in text.splitlines():
        if line.startswith("[JSON] "):
            return json.loads(line.removeprefix("[JSON] "))
    raise ValueError("basket CLI produced no JSON summary")


def experiments():
    work = workspace("experiments-")
    for directory in (ROOT / "backend/data").iterdir():
        if directory.is_dir() and directory.name != "__pycache__":
            dest = work / "backend/data" / directory.name
            if dest.exists():
                shutil.rmtree(dest)
            dest.symlink_to(directory, target_is_directory=True)
    before = {p: p.read_bytes() for p in (ROOT / "research").rglob("*") if p.is_file()}
    data_hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in (ROOT / "backend/data").rglob("*.csv")}
    if K12_INPUT.exists():
        data_hashes[str(K12_INPUT.relative_to(ROOT))] = hashlib.sha256(K12_INPUT.read_bytes()).hexdigest()
    manifest = {"captured_at": datetime.now(timezone.utc).isoformat(), "python": sys.version,
                "packages": {name: metadata.version(name) for name in ["numpy", "pandas", "scipy", "yfinance"]},
                "data_sha256": data_hashes,
                "script_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in (work / "backend/experiments").glob("*.py")}}
    (work / "manifest.json").write_text(json.dumps(manifest, indent=2))
    rows = []
    scripts = sorted((work / "backend/experiments").glob("*.py"),
                     key=lambda p: (list(OUTPUTS).index(p.stem) if p.stem in OUTPUTS else len(OUTPUTS), p.name))
    print("experiment | committed | reproduced | match", flush=True)
    for script in scripts:
        name = script.stem
        if name == "fetch_nifty50_data":
            continue  # Data download has its own target; do not overwrite inputs mid-run.
        baseline = ROOT / "research" / OUTPUTS[name] if name in OUTPUTS else None
        expected = metric_values(json.loads(baseline.read_text())) if baseline and baseline.exists() else {}
        row = {"experiment": name, "committed": expected, "reproduced": {}, "status": "", "reason": ""}
        if name in BLOCKED:
            row.update(status="BLOCKED", reason=BLOCKED[name])
        elif name == "basket_backtest" and not K12_INPUT.exists():
            row.update(status="MISSING INPUT", reason="run fetch-data to obtain fresh inputs at the documented 2026-08-13 cutoff")
        else:
            output = work / "research" / OUTPUTS[name] if name in OUTPUTS else None
            if output and output.exists():
                output.unlink()
            log = work / (name + ".log")
            try:
                with log.open("w") as stream:
                    args = [sys.executable, script]
                    if name == "basket_backtest":
                        args += ["--frequency", "monthly", "--as-of", "2026-08-13", "--cache", str(K12_INPUT)]
                    run(args, cwd=work, stdout=stream, stderr=subprocess.STDOUT, timeout=1800)
                if name == "basket_backtest":
                    output = work / "basket_backtest_results.json"
                    output.write_text(json.dumps(basket_output(log.read_text()), indent=2))
                if output and output.exists():
                    actual = metric_values(json.loads(output.read_text()))
                    row["reproduced"] = actual
                    row["status"] = "MATCH" if expected and expected == actual else "MISMATCH" if expected else "NO BASELINE"
                else:
                    row.update(status="DIAGNOSTIC PASS" if not baseline else "NO METRIC ARTIFACT", reason="script completed but writes no comparable result JSON")
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as exc:
                row.update(status="ERROR", reason=f"{type(exc).__name__}; see {log.relative_to(ROOT)}")
        rows.append(row)
        keys = sorted(set(expected) | set(row["reproduced"]))
        if row["status"] in {"MATCH", "MISMATCH"}:
            for key in keys:
                left, right = expected.get(key), row["reproduced"].get(key)
                print(f"{name}:{key} | {left} | {right} | {'yes' if key in expected and key in row['reproduced'] and left == right else 'NO'}", flush=True)
        else:
            print(f"{name} | {json.dumps(expected, sort_keys=True)} | {json.dumps(row['reproduced'], sort_keys=True) if row['reproduced'] else row['reason']} | {row['status']}", flush=True)
    (work / "comparison.json").write_text(json.dumps(rows, indent=2, allow_nan=False))
    assert all(p.read_bytes() == content for p, content in before.items()), "research source changed"
    assert all(hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == digest
               for p, digest in data_hashes.items()), "input data changed during reproduction"
    print(f"\nScratch results: {work.relative_to(ROOT)}/comparison.json")
    print("Mismatches are not attributed to data revisions without original data hashes/snapshots.")
    return int(any(row["status"] not in {"MATCH", "DIAGNOSTIC PASS"} for row in rows))


def fetch_data():
    # Run the original fixed-window downloader in a copy, preserving tracked metadata.
    work = workspace("fetch-")
    run([sys.executable, work / "backend/experiments/fetch_nifty50_data.py"], cwd=work)
    source = work / "backend/data/nifty50_data"
    csvs = list(source.glob("*.csv"))
    if not csvs:
        raise RuntimeError("No daily CSVs fetched; historical inputs remain unavailable")
    for csv in csvs:
        shutil.copyfile(csv, ROOT / "backend/data/nifty50_data" / csv.name)
        if csv.stem in {"RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"}:
            shutil.copyfile(csv, ROOT / "backend/data/real_nse_data" / csv.name)

    if not K12_INPUT.exists():
        sys.path.insert(0, str(ROOT / "backend"))
        from experiments.basket_backtest import fetch_daily_bars, UNIVERSE_49, FETCH_PERIOD_DAYS
        closes, adv, opens = fetch_daily_bars(UNIVERSE_49, as_of=date(2026, 8, 13),
                                             fetch_period_days=FETCH_PERIOD_DAYS, include_open=True)
        with K12_INPUT.open("wb") as stream:
            pickle.dump({"closes": closes, "adv": adv, "opens": opens}, stream)
    import yfinance as yf
    import pandas as pd
    committed = json.loads((ROOT / "research/intraday_signal_results.json").read_text())
    dest = ROOT / "backend/data/nifty50_intraday_1h"
    dest.mkdir(exist_ok=True)
    missing = []
    for symbol in committed["data"]["symbols"]:
        # Same historical window and interval; no shift to fit provider retention limits.
        frame = yf.download(symbol + ".NS", start="2024-08-01", end="2026-07-31", interval="60m", auto_adjust=True, progress=False)
        if frame is None or frame.empty:
            missing.append(symbol)
            continue
        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = frame.columns.get_level_values(0)
        frame.index.name = "Datetime"
        frame.reset_index().to_csv(dest / (symbol + ".csv"), index=False)
    (work / "fetch-summary.json").write_text(json.dumps({"daily_symbols": [p.stem for p in csvs], "missing_hourly": missing}, indent=2))
    if missing:
        raise RuntimeError(f"Historical hourly data unavailable for {missing}; no replacement window used")
    return 0


def engine_build():
    run(["cmake", "-S", "engine", "-B", RELEASE, "-DCMAKE_BUILD_TYPE=Release", "-DPYBIND11_FINDPYTHON=ON", f"-DPython_EXECUTABLE={sys.executable}", f"-DPYTHON_EXECUTABLE={sys.executable}"])
    run(["cmake", "--build", RELEASE, "--parallel", "2"])
    run(["cmake", "-S", "engine", "-B", TSAN, "-DALPHACORE_TSAN=ON", "-DPYBIND11_FINDPYTHON=ON", f"-DPython_EXECUTABLE={sys.executable}", f"-DPYTHON_EXECUTABLE={sys.executable}"])
    run(["cmake", "--build", TSAN, "--parallel", "2", "--target", "mpsc_tsan_test"])
    run([sys.executable, "-c", "import alphacore_cpp; print('Python 3.11 bridge import OK')"], env=os.environ | {"PYTHONPATH": str(RELEASE)})
    return 0


def engine_test():
    env = os.environ | {"OB_FAULT_POOL_EXHAUSTION": "1", "OB_FAULT_QUEUE_FULL": "1"}
    for name in ["engine_test", "replication_test", "gateway_test", "fault_test", "ha_chaos_test", "deterministic_replay_test"]:
        run([RELEASE / name], cwd=SCRATCH, env=env, timeout=300)
    run([TSAN / "mpsc_tsan_test"], cwd=SCRATCH, timeout=300)
    return 0


def engine_bench():
    build = RELEASE
    compiler = next(line.split("=", 1)[1] for line in (build / "CMakeCache.txt").read_text().splitlines() if line.startswith("CMAKE_CXX_COMPILER:FILEPATH="))
    legacy = build / "legacy_bench"
    run([compiler, "-std=c++20", "-O3", "-DNDEBUG", "-Iengine/legacy/src", "engine/legacy/benchmarks/bench.cpp", "engine/legacy/src/orderbook.cpp", "-o", legacy])
    flat = run([build / "flat_price_map_bench"], capture_output=True, text=True).stdout
    old = run([legacy], capture_output=True, text=True).stdout
    flat_ns = re.search(r"Insert:\s*([\d.]+) ns/op", flat).group(1)
    old_ns = re.search(r"Per order\s*:\s*([\d.]+) ns", old).group(1)
    version = run([compiler, "--version"], capture_output=True, text=True).stdout.splitlines()[0]
    cpu = run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip() if sys.platform == "darwin" else platform.processor()
    report = f"\n## {datetime.now(timezone.utc).isoformat()}\n\nMachine: {platform.platform()} / {cpu}.\nCompiler: {version}. Build: Release; flat map uses CMake flags; legacy uses `-O3 -DNDEBUG -std=c++20`.\n\n| Benchmark | ns/op |\n|---|---:|\n| FlatPriceMap insert (1M) | {flat_ns} |\n| Legacy OrderBook add_order (1M) | {old_ns} |\n\nDifferent operations/workloads; these are not a like-for-like speedup measurement.\n"
    target = ROOT / "engine/benchmarks/RESULTS.md"
    if not target.exists():
        target.write_text("# Recorded local benchmark runs\n")
    with target.open("a") as stream:
        stream.write(report)
    print(report)
    return 0


def tla():
    scratch = SCRATCH / "tla"
    scratch.mkdir(parents=True, exist_ok=True)
    jar = scratch / "tla2tools.jar"
    if not jar.exists():
        run(["curl", "-sfL", "https://github.com/tlaplus/tlaplus/releases/download/v1.7.4/tla2tools.jar", "-o", jar])
    checks = [("tla", "MpscQueue", "MpscQueue"), ("tla", "PrimaryBackup", "PrimaryBackup")]
    checks += [("tla_engine_models", spec, cfg) for spec, cfg in MODELS]
    failed = False
    for directory, spec, cfg in checks:
        meta = Path(tempfile.mkdtemp(prefix=spec + "-", dir=scratch))
        try:
            run([os.environ.get("JAVA", "java"), "-Xmx2g", "-cp", jar, "tlc2.TLC", ROOT / "specs" / directory / (spec + ".tla"), "-config", ROOT / "specs" / directory / (cfg + ".cfg"), "-deadlock", "-metadir", meta], timeout=300)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            print(f"FAILED {directory}/{spec}: {exc}", flush=True)
            failed = True
    return int(failed)


def py_test():
    env = os.environ | {"PYTHONPATH": str(RELEASE) + os.pathsep + str(ROOT / "backend")}
    run([sys.executable, "-m", "pytest", "tests/", "sandbox/tests/", "../scripts/tests/", "-m", "not benchmark", "-q"], cwd=ROOT / "backend", env=env)
    return 0


TARGETS = {"engine-build": engine_build, "engine-test": engine_test, "engine-bench": engine_bench,
           "tla": tla, "py-test": py_test, "fetch-data": fetch_data, "experiments": experiments}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=[*TARGETS, "all"])
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 11):
        parser.error("Python 3.11 is required")
    SCRATCH.mkdir(exist_ok=True)
    names = ["fetch-data", "engine-build", "engine-test", "engine-bench", "tla", "py-test", "experiments"] if args.target == "all" else [args.target]
    failed = False
    for name in names:
        try:
            failed = bool(TARGETS[name]()) or failed
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, RuntimeError, OSError) as exc:
            print(f"FAILED {name}: {exc}", file=sys.stderr, flush=True)
            failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
