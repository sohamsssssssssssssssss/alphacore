"""README regions rendered from report/generated/macros.tex.

Numbers in the marked README regions are filled from the report macros, so the
README and the report cannot drift; check_report.py verifies it. Update with
    python scripts/report/build_assets.py --update-readme
"""
from __future__ import annotations

import re

from report_common import GENERATED, ROOT

BEGIN = "<!-- BEGIN generated:{name} (scripts/report/build_assets.py --update-readme; do not edit) -->"
END = "<!-- END generated:{name} -->"

HEADLINE = """\
**Result: no tested configuration establishes a statistically significant,
cost-surviving edge in the frozen-data reruns.** Of {NumRerunConfigs} distinct re-run
configurations, {NumSigNegConfigs} have primary-convention {CILevel}% CIs entirely below zero.
Long/short K={UniverseK} on the expanded universe has zero-rf Sharpe **{UniverseSharpe}**,
CI **[{UniverseCILow}, {UniverseCIHigh}]**; with rf={RiskFreeAnnual} it is {UniverseSharpeExcess},
CI [{UniverseCILowExcess}, {UniverseCIHighExcess}] ([raw JSON](research/v2/experiment_7_universe_49.json)).
Post-earnings drift is inconclusive: zero-rf Sharpe {PeadSharpe}, CI [{PeadCILow}, {PeadCIHigh}],
on {PeadEvents} events, before explicit model fees ([raw JSON](research/v2/experiment_6_pead.json)).
The long-only K={BasketK} basket has excess-return Sharpe **{BasketSharpeExcess}**,
CI **[{BasketCILowExcess}, {BasketCIHighExcess}]** ([raw JSON](research/v2/k12_basket.json)), versus
{NiftySharpeExcess} for ^NSEI and {EqualWeightSharpeExcess} for equal-weight buy-and-hold (gross of
costs) under the same convention. Its CI includes zero, and its ADV cost lookahead remains.
Under zero-rf, which is not its primary convention, the basket CI is [{BasketCILow}, {BasketCIHigh}];
that convention also flatters buy-and-hold (^NSEI {NiftySharpe}, equal-weight {EqualWeightSharpe}).
Values are rounded to two decimals; full precision is in the linked JSON."""


def read_macros() -> dict[str, str]:
    text = (GENERATED / "macros.tex").read_text()
    out = {}
    for name, value in re.findall(r"\\newcommand\{\\(\w+)\}\{(.*)\}$", text, re.M):
        out[name] = re.sub(r"\\ensuremath\{(.*)\}", r"\1", value)
    return out


def tla_table(macros: dict[str, str]) -> str:
    from report_common import Asset
    from report_tables import tla_rows
    rows = tla_rows(Asset("README.md", "tla_table"))
    lines = ["| Spec | Config | States generated | Distinct states | Invariants checked | Result | Where run |",
             "|---|---|---:|---:|---|---|---|"]
    for r in rows:
        key = r["key"].replace("_", "")
        cfg = "not recorded" if r["cfg"] == "not recorded" else f'`{r["cfg"].split("/")[-1]}`'
        where = r["where"]
        if where.startswith("CI run"):
            where = where.replace(f"CI run {macros['TlaCIRun']}", f"[CI](report/data/ci_tlc.json)")
        lines.append(f'| `{r["spec"].replace("specs/", "")}` | {cfg} | {macros[f"Tla{key}Generated"]} | '
                     f'{macros[f"Tla{key}Distinct"]} | {", ".join(r["checks"])} | {r["result"]} | {where} |')
    return "\n".join(lines)


def regions(macros: dict[str, str]) -> dict[str, str]:
    return {"headline": HEADLINE.format(**macros), "tla": tla_table(macros)}


def replace_region(text: str, name: str, body: str) -> str:
    begin, end = BEGIN.format(name=name), END.format(name=name)
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.S)
    if not pattern.search(text):
        raise SystemExit(f"README.md has no '{name}' region markers")
    return pattern.sub(lambda _: f"{begin}\n{body}\n{end}", text)


def region_text(text: str, name: str) -> str | None:
    m = re.search(re.escape(BEGIN.format(name=name)) + r"\n(.*?)\n" + re.escape(END.format(name=name)), text, re.S)
    return m.group(1) if m else None


def update_readme() -> None:
    path = ROOT / "README.md"
    text = path.read_text()
    for name, body in regions(read_macros()).items():
        if BEGIN.format(name=name) in text:
            text = replace_region(text, name, body)
    path.write_text(text)
    print("updated README.md generated regions")
