"""Shared helpers for the report generators: provenance-recording Asset and formatting."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "report"
GENERATED = REPORT / "generated"
FIGURES = REPORT / "figures"


class MissingSource(Exception):
    """A source file the asset needs is absent; the asset is emitted as n/a."""


LATEX_ESCAPES = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
                 "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
                 "→": r"$\rightarrow$", "–": "--", "≥": r"$\geq$", "≤": r"$\leq$", "`": ""}


def tex(text: str) -> str:
    return "".join(LATEX_ESCAPES.get(c, c) for c in str(text))


def fmt_sharpe(x: float) -> str:
    return f"{x:.2f}"


def fmt_count(n: int) -> str:
    return f"{int(n):,}"


class Asset:
    """One generated file plus the provenance of every value written into it."""

    def __init__(self, path: str, func: str):
        self.path = path            # relative to report/
        self.func = func
        self.inputs: list[str] = []
        self.fields: list[tuple[str, str]] = []
        self.values: list[dict] = []

    def _use(self, rel: str) -> Path:
        p = ROOT / rel
        if not p.exists():
            raise MissingSource(f"{rel} not found")
        if rel not in self.inputs:
            self.inputs.append(rel)
        return p

    def json(self, rel: str):
        return json.loads(self._use(rel).read_text())

    def text(self, rel: str) -> str:
        return self._use(rel).read_text()

    def exists(self, rel: str) -> bool:
        """Existence check counted as an input (the asset reports on it)."""
        if rel not in self.inputs:
            self.inputs.append(rel)
        return (ROOT / rel).exists()

    def val(self, value, rel: str, field: str, fmt=None, latex: bool = True) -> str:
        """Render a value read from `rel` and record where it came from."""
        if rel not in self.inputs:
            self.inputs.append(rel)
        if (rel, field) not in self.fields:
            self.fields.append((rel, field))
        out = fmt(value) if fmt else str(value)
        if latex:
            out = tex(out)
        self.values.append({"text": out, "source": rel, "field": field})
        return out


