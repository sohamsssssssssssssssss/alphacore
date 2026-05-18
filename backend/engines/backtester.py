from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import logging
import math
import random

from engines.backtest_metrics import full_metrics
from engines.cost_model import CostModel

SYMBOLS = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]
STRATEGIES = ["momentum", "mean_reversion", "ofi", "combined"]
SYMBOL_PARAMS = {
    "RELIANCE": {"sigma": 0.20, "mu": 0.0002, "spread_mean": 5.0},
    "TCS": {"sigma": 0.18, "mu": 0.0001, "spread_mean": 4.0},
    "INFY": {"sigma": 0.22, "mu": -0.0001, "spread_mean": 6.0},
    "HDFCBANK": {"sigma": 0.16, "mu": 0.0003, "spread_mean": 3.5},
    "ICICIBANK": {"sigma": 0.25, "mu": -0.0002, "spread_mean": 7.0},
}


@dataclass
class Snapshot:
    timestamp: str
    symbol: str
    bid_price: float
    ask_price: float
    bid_volume: float
    ask_volume: float
    mid_price: float
    spread_bps: float


@dataclass
class BacktestConfig:
    symbol: str = "RELIANCE"
    strategy: str = "combined"
    n_snapshots: int = 500
    hold_periods: int = 10
    stop_loss_pct: float = 0.005
    position_size_pct: float = 0.1
    initial_capital: float = 100000.0
    seed: int = 42


@dataclass
class Trade:
    symbol: str
    strategy: str
    direction: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    return_pct: float
    entry_period: int
    exit_period: int
    hold_periods: int
    exit_reason: str


def generate_snapshots(symbol: str, n: int, seed: int = 42) -> list[Snapshot]:
    random.seed(seed)

    base_prices = {
        "RELIANCE": 2500.0,
        "TCS": 3800.0,
        "INFY": 1500.0,
        "HDFCBANK": 1600.0,
        "ICICIBANK": 1100.0,
    }
    base_volumes = {
        "RELIANCE": 50000.0,
        "TCS": 20000.0,
        "INFY": 30000.0,
        "HDFCBANK": 40000.0,
        "ICICIBANK": 35000.0,
    }

    sym = symbol.upper()
    price = base_prices.get(sym, 1000.0)
    base_volume = base_volumes.get(sym, 25000.0)

    params = SYMBOL_PARAMS.get(sym, {"sigma": 0.20, "mu": 0.0, "spread_mean": 5.0})
    mu = float(params["mu"])
    sigma = float(params["sigma"])
    dt = 1.0 / 252.0

    spread_mean = float(params["spread_mean"])
    spread_bps = spread_mean
    start = datetime(2025, 1, 1, 9, 15)
    snapshots: list[Snapshot] = []

    for i in range(n):
        z = random.gauss(0.0, 1.0)
        if i > 0:
            price = price * math.exp(mu * dt + sigma * math.sqrt(dt) * z)

        spread_bps = spread_bps * 0.9 + spread_mean * 0.1 + random.gauss(0, 1)
        spread_bps = max(1.0, min(20.0, spread_bps))

        mid = float(price)
        spread_abs = (spread_bps / 10000.0) * mid
        bid = mid - spread_abs / 2.0
        ask = mid + spread_abs / 2.0
        if bid >= ask:
            ask = bid + 1e-6

        vol_factor = abs(z) + 0.5
        drift = math.sin(i * 0.05) * 0.4
        bid_volume = base_volume * vol_factor * random.uniform(0.8, 1.2) * (1 + drift)
        ask_volume = base_volume * vol_factor * random.uniform(0.8, 1.2) * (1 - drift)

        snapshots.append(
            Snapshot(
                timestamp=(start + timedelta(minutes=i)).isoformat(),
                symbol=sym,
                bid_price=float(bid),
                ask_price=float(ask),
                bid_volume=float(bid_volume),
                ask_volume=float(ask_volume),
                mid_price=float(mid),
                spread_bps=float(spread_bps),
            )
        )

    return snapshots


def _momentum_signal(snapshots: list[Snapshot], idx: int) -> float:
    if idx <= 0:
        return 0.0

    def comp(window: int) -> float:
        if idx - window < 0:
            return 0.0
        prev = snapshots[idx - window].mid_price
        cur = snapshots[idx].mid_price
        if prev == 0:
            return 0.0
        return ((cur - prev) / prev) * 10000.0

    m1 = comp(1)
    m5 = comp(5)
    m15 = comp(15)
    return float(0.2 * m1 + 0.5 * m5 + 0.3 * m15)


def _mean_reversion_signal(snapshots: list[Snapshot], idx: int, window: int = 20) -> float:
    n = min(idx + 1, window)
    if n < 2:
        return 0.0
    prices = [snapshots[j].mid_price for j in range(idx - n + 1, idx + 1)]
    mean = sum(prices) / n
    var = sum((x - mean) ** 2 for x in prices) / n
    std = math.sqrt(var)
    if std == 0:
        return 0.0
    return float((prices[-1] - mean) / std)


def _ofi_signal(snapshot: Snapshot) -> float:
    denom = snapshot.bid_volume + snapshot.ask_volume
    if denom == 0:
        return 0.0
    return float((snapshot.bid_volume - snapshot.ask_volume) / denom)


def _combined_signal(snapshots: list[Snapshot], idx: int) -> float:
    mom = _momentum_signal(snapshots, idx)
    mr = _mean_reversion_signal(snapshots, idx)
    ofi = _ofi_signal(snapshots[idx])

    mom_n = max(-1.0, min(1.0, mom / 10.0))
    mr_n = max(-1.0, min(1.0, mr / 3.0))
    ofi_n = max(-1.0, min(1.0, ofi))

    val = (mom_n + mr_n + ofi_n) / 3.0
    return float(max(-1.0, min(1.0, val)))


def _get_direction(signal_value: float, strategy: str) -> str | None:
    if strategy == "momentum":
        if signal_value > 2.0:
            return "LONG"
        if signal_value < -2.0:
            return "SHORT"
        return None

    if strategy == "mean_reversion":
        if signal_value < -1.5:
            return "LONG"
        if signal_value > 1.5:
            return "SHORT"
        return None

    if strategy == "ofi":
        if signal_value > 0.2:
            return "LONG"
        if signal_value < -0.2:
            return "SHORT"
        return None

    if signal_value > 0.15:
        return "LONG"
    if signal_value < -0.15:
        return "SHORT"
    return None


class Backtester:
    def __init__(self, config: BacktestConfig):
        self.config = config
        self._cost_model = CostModel()
        self._log = logging.getLogger(__name__)

    def _signal(self, snapshots: list[Snapshot], idx: int) -> float:
        if self.config.strategy == "momentum":
            return _momentum_signal(snapshots, idx)
        if self.config.strategy == "mean_reversion":
            return _mean_reversion_signal(snapshots, idx)
        if self.config.strategy == "ofi":
            return _ofi_signal(snapshots[idx])
        return _combined_signal(snapshots, idx)

    def run(self, snapshots: list[Snapshot] = None) -> dict:
        cfg = self.config
        snaps = snapshots if snapshots is not None else generate_snapshots(cfg.symbol, cfg.n_snapshots, cfg.seed)

        trades: list[Trade] = []
        current_capital = float(cfg.initial_capital)
        gross_pnl_total = 0.0
        total_costs = 0.0

        in_position = False
        direction: str | None = None
        entry_price = 0.0
        quantity = 0.0
        entry_period = -1

        for idx, snap in enumerate(snaps):
            if not in_position:
                signal = self._signal(snaps, idx)
                direction = _get_direction(signal, cfg.strategy)
                if direction is None:
                    continue

                entry_price = snap.ask_price if direction == "LONG" else snap.bid_price
                if entry_price <= 0:
                    continue
                quantity = (cfg.position_size_pct * current_capital) / entry_price if current_capital > 0 else 0.0
                if quantity <= 0:
                    continue
                entry_period = idx
                in_position = True
                continue

            hold = idx - entry_period
            exit_reason = None

            if direction == "LONG" and snap.mid_price < entry_price * (1 - cfg.stop_loss_pct):
                exit_reason = "STOP_LOSS"
            elif direction == "SHORT" and snap.mid_price > entry_price * (1 + cfg.stop_loss_pct):
                exit_reason = "STOP_LOSS"
            elif hold >= cfg.hold_periods:
                exit_reason = "SIGNAL"

            if exit_reason is not None:
                exit_price = snap.bid_price if direction == "LONG" else snap.ask_price
                if direction == "LONG":
                    gross_pnl = (exit_price - entry_price) * quantity
                    ret = ((exit_price - entry_price) / entry_price) * 100.0 if entry_price else 0.0
                    side = "SELL"
                else:
                    gross_pnl = (entry_price - exit_price) * quantity
                    ret = ((entry_price - exit_price) / entry_price) * 100.0 if entry_price else 0.0
                    side = "BUY"

                adv = self._cost_model.adv_lookup.get(cfg.symbol.upper())
                trade_cost = self._cost_model.total_cost(
                    price=exit_price,
                    qty=quantity,
                    adv=adv,
                    spread_bps=snap.spread_bps,
                    side=side,
                )
                pnl = gross_pnl - trade_cost

                trade = Trade(
                    symbol=cfg.symbol.upper(),
                    strategy=cfg.strategy,
                    direction=direction,
                    entry_price=float(entry_price),
                    exit_price=float(exit_price),
                    quantity=float(quantity),
                    pnl=float(pnl),
                    return_pct=float(ret),
                    entry_period=int(entry_period),
                    exit_period=int(idx),
                    hold_periods=int(hold),
                    exit_reason=exit_reason,
                )
                trades.append(trade)
                gross_pnl_total += float(gross_pnl)
                total_costs += float(trade_cost)
                current_capital = max(0.0, current_capital + pnl)
                in_position = False

        if in_position and snaps:
            idx = len(snaps) - 1
            snap = snaps[idx]
            exit_price = snap.bid_price if direction == "LONG" else snap.ask_price
            if direction == "LONG":
                gross_pnl = (exit_price - entry_price) * quantity
                ret = ((exit_price - entry_price) / entry_price) * 100.0 if entry_price else 0.0
                side = "SELL"
            else:
                gross_pnl = (entry_price - exit_price) * quantity
                ret = ((entry_price - exit_price) / entry_price) * 100.0 if entry_price else 0.0
                side = "BUY"

            adv = self._cost_model.adv_lookup.get(cfg.symbol.upper())
            trade_cost = self._cost_model.total_cost(
                price=exit_price,
                qty=quantity,
                adv=adv,
                spread_bps=snap.spread_bps,
                side=side,
            )
            pnl = gross_pnl - trade_cost

            trade = Trade(
                symbol=cfg.symbol.upper(),
                strategy=cfg.strategy,
                direction=direction,
                entry_price=float(entry_price),
                exit_price=float(exit_price),
                quantity=float(quantity),
                pnl=float(pnl),
                return_pct=float(ret),
                entry_period=int(entry_period),
                exit_period=int(idx),
                hold_periods=int(idx - entry_period),
                exit_reason="END_OF_DATA",
            )
            trades.append(trade)
            gross_pnl_total += float(gross_pnl)
            total_costs += float(trade_cost)
            current_capital = max(0.0, current_capital + pnl)

        trades_dict = [asdict(t) for t in trades]
        net_pnl = float(sum(float(t["pnl"]) for t in trades_dict))
        denom = abs(float(gross_pnl_total))
        cost_drag_pct = float((total_costs / denom) * 100.0) if denom > 0 else 0.0
        if cost_drag_pct > 80.0:
            self._log.warning("Strategy not viable after costs")

        return {
            "config": asdict(cfg),
            "metrics": full_metrics(trades_dict, cfg.initial_capital),
            "gross_pnl": float(gross_pnl_total),
            "total_costs": float(total_costs),
            "net_pnl": float(net_pnl),
            "cost_drag_pct": float(cost_drag_pct),
            "trades": trades_dict,
        }


def run_strategy_comparison(
    symbol: str = "RELIANCE",
    n_snapshots: int = 500,
    hold_periods: int = 10,
    stop_loss_pct: float = 0.005,
    position_size_pct: float = 0.1,
    initial_capital: float = 100000.0,
    seed: int = 42,
) -> dict:
    symbol = symbol.upper()
    snapshots = generate_snapshots(symbol, n_snapshots, seed)

    details: dict[str, dict] = {}
    entries: list[dict] = []

    for strategy in STRATEGIES:
        cfg = BacktestConfig(
            symbol=symbol,
            strategy=strategy,
            n_snapshots=n_snapshots,
            hold_periods=hold_periods,
            stop_loss_pct=stop_loss_pct,
            position_size_pct=position_size_pct,
            initial_capital=initial_capital,
            seed=seed,
        )
        result = Backtester(cfg).run(snapshots=snapshots)
        details[strategy] = result
        m = result["metrics"]
        entries.append(
            {
                "strategy": strategy,
                "sharpe": float(m["sharpe"]),
                "total_pnl": float(m["total_pnl"]),
                "win_rate": float(m["win_rate"]),
                "max_drawdown": float(m["max_drawdown"]),
                "total_trades": int(m["total_trades"]),
                "calmar": float(m["calmar"]),
            }
        )

    entries.sort(key=lambda x: x["sharpe"], reverse=True)
    for i, row in enumerate(entries, start=1):
        row["rank"] = i

    return {
        "symbol": symbol,
        "leaderboard": entries,
        "details": details,
    }
