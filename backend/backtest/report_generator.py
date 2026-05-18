from __future__ import annotations

from backtest.walk_forward import WalkForwardBacktester


def generate_comparison_report(results: dict) -> str:
    summary = WalkForwardBacktester.get_summary(results)
    view = summary[["model", "win_rate", "dsr", "purged_cv_acc", "total_net_pnl"]].copy()
    view.columns = ["Model", "Win Rate", "DSR", "Purged CV Acc", "Net PnL (INR)"]

    try:
        from tabulate import tabulate

        table = tabulate(view.values.tolist(), headers=list(view.columns), tablefmt="github", floatfmt=".4f")
    except Exception:
        lines = ["| " + " | ".join(view.columns) + " |", "|" + "|".join(["---"] * len(view.columns)) + "|"]
        for row in view.values.tolist():
            lines.append("| " + " | ".join(str(x) for x in row) + " |")
        table = "\n".join(lines)

    return "# AlphaCore Walk-Forward Report\n\n" + table + "\n"


def save_report(report_str: str, path: str = "report.md") -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(report_str)
