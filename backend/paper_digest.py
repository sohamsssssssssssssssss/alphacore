from __future__ import annotations

import argparse
import csv
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

from audit.audit_logger import AuditLogger
from execution.paper_engine import PaperTradingEngine
from risk.risk_manager import RiskGate

IST = timezone(timedelta(hours=5, minutes=30), name="IST")


@dataclass
class DigestEntry:
    date: str
    gross_pnl: float
    net_pnl: float
    total_trades: int
    win_rate: float
    max_drawdown: float
    risk_violations: int
    regime_distribution: dict[str, float]
    signal_accuracy: float
    sharpe_today: float


class DailyDigest:
    def __init__(self, audit_db: str = "paper_trading.db", digest_csv: str = "paper_digest_60d.csv"):
        db_url = audit_db if audit_db.startswith("sqlite:///") else f"sqlite:///{audit_db}"
        self.audit = AuditLogger(db_url=db_url)
        self.digest_csv = digest_csv

    @staticmethod
    def _today_ist() -> str:
        return datetime.now(UTC).astimezone(IST).strftime("%Y-%m-%d")

    @staticmethod
    def _max_drawdown_from_pnl_curve(values: list[float]) -> float:
        if not values:
            return 0.0
        peak = values[0]
        max_dd = 0.0
        for v in values:
            peak = max(peak, v)
            dd = peak - v
            max_dd = max(max_dd, dd)
        return float(max_dd)

    @staticmethod
    def _annualized_sharpe(returns: list[float]) -> float:
        if len(returns) < 2:
            return 0.0
        mean_r = sum(returns) / len(returns)
        var = sum((x - mean_r) ** 2 for x in returns) / len(returns)
        std = var ** 0.5
        if std == 0.0:
            return 0.0
        return float((mean_r / std) * (252.0 ** 0.5))

    def compute_today(self, paper_engine: PaperTradingEngine) -> DigestEntry:
        today = self._today_ist()
        events = self.audit.replay_session(today)

        # Prefer engine trades when available; fallback to FULL/PARTIAL fills from audit.
        trades = []
        for t in getattr(paper_engine, "trades", []):
            ts = t.get("filled_at")
            if isinstance(ts, datetime):
                ts_ist = ts.astimezone(IST)
                if ts_ist.strftime("%Y-%m-%d") == today:
                    trades.append(t)

        if not trades:
            for e in events:
                if e.get("event_type") in {"FULL_FILL", "PARTIAL_FILL"}:
                    trades.append(
                        {
                            "side": e.get("side", "BUY"),
                            "price": float(e.get("price") or 0.0),
                            "qty": float(e.get("qty") or 0.0),
                        }
                    )

        gross_pnls: list[float] = []
        net_pnls: list[float] = []
        wins = 0
        running = 0.0
        running_curve: list[float] = []

        rt_metrics = paper_engine.get_realtime_metrics() if hasattr(paper_engine, "get_realtime_metrics") else {"pnl": 0.0}
        final_net = float(rt_metrics.get("pnl", 0.0))

        for t in trades:
            side = str(t.get("side", "BUY")).upper()
            price = float(t.get("price") or 0.0)
            qty = float(t.get("qty") or 0.0)
            signed = qty if side == "SELL" else -qty
            gross = signed * price * 0.0  # Unknown true realized gross from single fills; keep neutral unless paired model exists.
            fee = abs(qty) * 0.1
            net = gross - fee
            gross_pnls.append(gross)
            net_pnls.append(net)
            if net > 0:
                wins += 1
            running += net
            running_curve.append(running)

        total_trades = len(trades)
        gross_pnl = float(sum(gross_pnls))
        net_pnl = final_net if total_trades > 0 else 0.0
        win_rate = float((wins / total_trades) if total_trades else 0.0)
        max_drawdown = self._max_drawdown_from_pnl_curve(running_curve)

        risk_violations = sum(1 for e in events if e.get("event_type") == "RISK_VIOLATION")

        regimes = [str(e.get("extra", {}).get("regime", "unknown")) for e in events if e.get("event_type") == "STRATEGY_SIGNAL"]
        regime_distribution: dict[str, float] = {}
        if regimes:
            n = len(regimes)
            for r in set(regimes):
                regime_distribution[r] = float(regimes.count(r) / n)

        # Signal accuracy heuristic: needs next close; if unavailable, skip from denominator.
        signal_checks = 0
        signal_hits = 0
        for e in events:
            if e.get("event_type") != "FULL_FILL":
                continue
            side = str(e.get("side", "")).upper()
            fill_px = float(e.get("price") or 0.0)
            next_close = e.get("extra", {}).get("next_close") if isinstance(e.get("extra"), dict) else None
            if next_close is None:
                continue
            signal_checks += 1
            nc = float(next_close)
            if (side == "BUY" and nc > fill_px) or (side == "SELL" and nc < fill_px):
                signal_hits += 1
        signal_accuracy = float(signal_hits / signal_checks) if signal_checks else 0.0

        returns = []
        for n in net_pnls:
            returns.append(float(n))
        sharpe_today = self._annualized_sharpe(returns)

        return DigestEntry(
            date=today,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            total_trades=total_trades,
            win_rate=win_rate,
            max_drawdown=max_drawdown,
            risk_violations=risk_violations,
            regime_distribution=regime_distribution,
            signal_accuracy=signal_accuracy,
            sharpe_today=sharpe_today,
        )

    def save(self, entry: DigestEntry) -> None:
        exists = os.path.exists(self.digest_csv)
        cols = [
            "date",
            "gross_pnl",
            "net_pnl",
            "total_trades",
            "win_rate",
            "max_drawdown",
            "risk_violations",
            "signal_accuracy",
            "sharpe_today",
            "regime_distribution",
        ]
        with open(self.digest_csv, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            if not exists:
                w.writeheader()
            w.writerow(
                {
                    "date": entry.date,
                    "gross_pnl": float(entry.gross_pnl),
                    "net_pnl": float(entry.net_pnl),
                    "total_trades": int(entry.total_trades),
                    "win_rate": float(entry.win_rate),
                    "max_drawdown": float(entry.max_drawdown),
                    "risk_violations": int(entry.risk_violations),
                    "signal_accuracy": float(entry.signal_accuracy),
                    "sharpe_today": float(entry.sharpe_today),
                    "regime_distribution": json.dumps(entry.regime_distribution, sort_keys=True),
                }
            )

    def load_history(self) -> list[DigestEntry]:
        if not os.path.exists(self.digest_csv):
            return []
        out: list[DigestEntry] = []
        with open(self.digest_csv, "r", newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                out.append(
                    DigestEntry(
                        date=row["date"],
                        gross_pnl=float(row["gross_pnl"]),
                        net_pnl=float(row["net_pnl"]),
                        total_trades=int(row["total_trades"]),
                        win_rate=float(row["win_rate"]),
                        max_drawdown=float(row["max_drawdown"]),
                        risk_violations=int(row["risk_violations"]),
                        signal_accuracy=float(row["signal_accuracy"]),
                        sharpe_today=float(row["sharpe_today"]),
                        regime_distribution=json.loads(row["regime_distribution"] or "{}"),
                    )
                )
        return out

    def print_dashboard(self) -> None:
        history = self.load_history()
        if not history:
            print("No digest history yet.")
            return

        latest = history[-1]
        print("┌─────────────────────────────────────┐")
        print(f"│ AlphaCore Paper Trading — {latest.date}│")
        print("├──────────────────┬──────────────────┤")
        print(f"│ Gross PnL        │ ₹ {latest.gross_pnl:,.2f}       │")
        print(f"│ Net PnL          │ ₹ {latest.net_pnl:,.2f}       │")
        print(f"│ Trades           │ {latest.total_trades:02d}               │")
        print(f"│ Win Rate         │ {latest.win_rate * 100:.1f}%            │")
        print(f"│ Max Drawdown     │ {latest.max_drawdown:.2f}%            │")
        print(f"│ Risk Violations  │ {latest.risk_violations}                │")
        print(f"│ Signal Accuracy  │ {latest.signal_accuracy * 100:.1f}%            │")
        print(f"│ Sharpe (today)   │ {latest.sharpe_today:.2f}             │")
        print("└──────────────────┴──────────────────┘")

        days = len(history)
        cum_net = sum(x.net_pnl for x in history)
        avg_win = sum(x.win_rate for x in history) / days if days else 0.0
        avg_sharpe = sum(x.sharpe_today for x in history) / days if days else 0.0
        status = "GRADUATED" if self.check_graduation(silent=True) else ("ON TRACK" if days < 60 else "AT RISK")
        print(
            f"Day {days}/60 | Cumulative Net PnL: ₹ {cum_net:,.0f} | "
            f"Avg Win Rate: {avg_win * 100:.1f}% | Avg Sharpe: {avg_sharpe:.2f}"
        )
        print("Graduation criteria: 60 days + cumulative net PnL > 0 + avg Sharpe > 0.5")
        print(f"Status: {status}")

    def check_graduation(self, silent: bool = False) -> bool:
        h = self.load_history()
        ok = len(h) >= 60 and sum(x.net_pnl for x in h) > 0 and ((sum(x.sharpe_today for x in h) / len(h)) if h else 0.0) > 0.5
        if ok and not silent:
            print("GRADUATED — Ready for live capital.")
        return bool(ok)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="paper_trading.db")
    p.add_argument("--csv", default="paper_digest_60d.csv")
    p.add_argument("--no-save", action="store_true")
    args = p.parse_args()

    digest = DailyDigest(audit_db=args.db, digest_csv=args.csv)
    if not args.no_save:
        pe = PaperTradingEngine()
        _ = RiskGate()
        entry = digest.compute_today(pe)
        digest.save(entry)
    digest.print_dashboard()
    digest.check_graduation()


if __name__ == "__main__":
    main()
