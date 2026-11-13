"""Consistency check for the report; exits non-zero on any violation.

1. Every number in report/generated/*.tex is a value recorded in provenance.json
   for that asset, and the asset and its input files are listed in SOURCES.md.
2. No banned wording anywhere under report/ ("formally verified", "proved", "guarantee").
3. No numeric literal in report/sections/*.tex (numbers come only from macros).
4. Numbers in the generated README regions equal the macros (and the regions are current).
Run after scripts/report/build_assets.py (it is run by `--check`).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from report_common import GENERATED, REPORT, ROOT  # noqa: E402
import report_readme  # noqa: E402

NUMBER = re.compile(r"(?<![\w.])-?\d+(?:,\d{3})*(?:\.\d+)?(?!\w)")
BANNED = re.compile(r"formally verified|\bproved\b|\bguarantee\w*", re.I)
TEXT_SUFFIXES = {".tex", ".md", ".json", ".bib", ".txt"}


def numbers(text: str) -> set[str]:
    return set(NUMBER.findall(text))


def check_provenance(errors: list[str]) -> None:
    prov_path = GENERATED / "provenance.json"
    if not prov_path.exists():
        errors.append("report/generated/provenance.json missing; run build_assets.py first")
        return
    prov = {p["asset"]: p for p in json.loads(prov_path.read_text())}
    sources = (REPORT / "SOURCES.md").read_text()
    rows = {m.group(1): m.group(0) for m in re.finditer(r"^\| `([^`]+)` \|.*$", sources, re.M)}
    for tex in sorted(GENERATED.glob("*.tex")):
        asset = f"generated/{tex.name}"
        if asset not in prov or asset not in rows:
            errors.append(f"{asset}: not listed in SOURCES.md/provenance.json")
            continue
        for src in prov[asset]["inputs"]:
            if f"`{src}`" not in rows[asset]:
                errors.append(f"{asset}: input {src} missing from its SOURCES.md row")
        allowed = set().union(*(numbers(v["text"]) for v in prov[asset]["values"]))
        body = re.sub(r"(?<!\\)%.*", "", tex.read_text())
        for n in sorted(numbers(body) - allowed):
            errors.append(f"{asset}: number {n} does not trace to a recorded source value")


def check_banned(errors: list[str]) -> None:
    for path in sorted(REPORT.rglob("*")):
        if path.is_file() and path.suffix in TEXT_SUFFIXES:
            for i, line in enumerate(path.read_text().splitlines(), 1):
                for m in BANNED.finditer(line):
                    errors.append(f"{path.relative_to(ROOT)}:{i}: banned wording '{m.group(0)}'")


def check_sections(errors: list[str]) -> None:
    for path in sorted((REPORT / "sections").glob("*.tex")):
        for i, line in enumerate(path.read_text().splitlines(), 1):
            code = re.sub(r"(?<!\\)%.*", "", line)
            if re.search(r"\d", code):
                errors.append(f"{path.relative_to(ROOT)}:{i}: numeric literal outside a macro: {code.strip()}")


def check_readme(errors: list[str]) -> None:
    if not (GENERATED / "macros.tex").exists():
        errors.append("report/generated/macros.tex missing")
        return
    macros = report_readme.read_macros()
    allowed = set().union(*(numbers(v) for v in macros.values()))
    readme = (ROOT / "README.md").read_text()
    for name, expected in report_readme.regions(macros).items():
        actual = report_readme.region_text(readme, name)
        if actual is None:
            errors.append(f"README.md: generated region '{name}' missing")
            continue
        visible = re.sub(r"\]\([^)]*\)", "]", actual)  # link targets are paths, not claims
        for n in sorted(numbers(visible) - allowed):
            errors.append(f"README.md region '{name}': number {n} is not a report macro value")
        if actual != expected:
            errors.append(f"README.md region '{name}' is stale; run build_assets.py --update-readme")


def main() -> int:
    errors: list[str] = []
    for check in (check_provenance, check_banned, check_sections, check_readme):
        check(errors)
    for e in errors:
        print(f"CHECK FAIL {e}")
    print(f"check_report: {'FAILED, ' + str(len(errors)) + ' violation(s)' if errors else 'all checks passed'}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
