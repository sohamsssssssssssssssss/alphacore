from __future__ import annotations

import math


def compute_pnl(trades: list[dict]) -> float:
    if not trades:
        return 0.0
    return float(sum(float(t.get("pnl", 0.0)) for t in trades))


def compute_returns_from_equity(equity_curve: list[float]) -> list[float]:
    if len(equity_curve) < 2:
        return []
    returns: list[float] = []
    for i in range(1, len(equity_curve)):
        prev = float(equity_curve[i - 1])
        cur = float(equity_curve[i])
        if prev == 0:
            returns.append(0.0)
        else:
            returns.append((cur - prev) / prev)
    return returns


def build_equity_curve(initial_capital: float, trades: list[dict]) -> list[float]:
    curve = [float(initial_capital)]
    capital = float(initial_capital)
    for trade in trades:
        capital += float(trade.get("pnl", 0.0))
        curve.append(float(capital))
    return curve


def compute_sharpe(returns: list[float], periods_per_year: int = 252, risk_free: float = 0.065) -> float:
    if len(returns) < 2:
        return 0.0

    rf_per_period = (1.0 + risk_free) ** (1.0 / periods_per_year) - 1.0
    excess = [float(r) - rf_per_period for r in returns]
    mean_excess = sum(excess) / len(excess)
    var = sum((x - mean_excess) ** 2 for x in excess) / len(excess)
    std = math.sqrt(var)
    if std == 0:
        return 0.0
    return float((mean_excess / std) * math.sqrt(periods_per_year))


def compute_max_drawdown(equity_curve: list[float]) -> float:
    if len(equity_curve) < 2:
        return 0.0

    peak = float(equity_curve[0])
    max_dd = 0.0
    for v in equity_curve:
        cur = float(v)
        if cur > peak:
            peak = cur
        if peak > 0:
            dd = (peak - cur) / peak
            if dd > max_dd:
                max_dd = dd
    return float(max_dd)


def compute_win_rate(trades: list[dict]) -> dict:
    if not trades:
        return {"win_rate": 0.0, "profit_factor": 0.0, "wins": 0, "losses": 0}

    pnls = [float(t.get("pnl", 0.0)) for t in trades]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x < 0]

    wins_count = len(wins)
    losses_count = len(losses)
    win_rate = wins_count / len(pnls) if pnls else 0.0

    sum_wins = sum(wins)
    sum_losses_abs = abs(sum(losses))
    profit_factor = (sum_wins / sum_losses_abs) if sum_losses_abs > 0 else 0.0

    return {
        "win_rate": float(win_rate),
        "profit_factor": float(profit_factor),
        "wins": int(wins_count),
        "losses": int(losses_count),
    }


def compute_calmar(total_pnl: float, initial_capital: float, max_drawdown: float) -> float:
    if max_drawdown == 0 or initial_capital == 0:
        return 0.0
    return float((total_pnl / initial_capital) / max_drawdown)


def full_metrics(trades: list[dict], initial_capital: float = 100000.0, periods_per_year: int = 252) -> dict:
    total_pnl = compute_pnl(trades)
    equity_curve = build_equity_curve(initial_capital, trades)
    returns = compute_returns_from_equity(equity_curve)
    sharpe = compute_sharpe(returns, periods_per_year=periods_per_year)
    max_drawdown = compute_max_drawdown(equity_curve)
    wr = compute_win_rate(trades)
    calmar = compute_calmar(total_pnl, initial_capital, max_drawdown)
    pnl_series = [float(t.get("pnl", 0.0)) for t in trades]

    return {
        "total_pnl": float(total_pnl),
        "sharpe": float(sharpe),
        "max_drawdown": float(max_drawdown),
        "win_rate": float(wr["win_rate"]),
        "profit_factor": float(wr["profit_factor"]),
        "wins": int(wr["wins"]),
        "losses": int(wr["losses"]),
        "calmar": float(calmar),
        "total_trades": int(len(trades)),
        "final_equity": float(equity_curve[-1] if equity_curve else initial_capital),
        "equity_curve": [float(x) for x in equity_curve],
        "pnl_series": [float(x) for x in pnl_series],
    }
