# Strategy Guide

## Implementing BaseStrategy
Implement all required hooks from `BaseStrategy`:
- `on_orderbook`
- `on_signal`
- `on_fill`
- `on_regime_change`

Use `emit_order(...)` to express order intent and let the executor consume queued orders.

## Available Signals (11 Factors)
- `momentum`
- `mean_reversion`
- `order_flow`
- `spread_momentum`
- `volume_surge`
- `iceberg_pressure`
- `spoof_reversal`
- `rsi_divergence`
- `amihud_illiquidity`
- `residual_reversal`
- `idiosyncratic_vol`

## Regime States (4 HMM States)
- State 0: low-volatility trend
- State 1: low-volatility mean reversion
- State 2: high-volatility directional
- State 3: high-volatility stress

## Risk Constraints
Enforced pre-trade through `RiskGate`:
- Max position: `50,000 INR`
- Max daily loss: `5,000 INR`
- Max drawdown: `5.0%`
- Max order rate: `10 orders/min`
- Max concentration: `30%`

## Paper Trading Gate (60-Day Rule)
Before live deployment, each strategy must complete at least 60 calendar days of paper trading with stable drawdown and no risk violations.

## Deployment Checklist
- Validate factor inputs and fallback paths.
- Confirm regime transition handling.
- Run walk-forward with net costs and DSR reporting.
- Complete 60-day paper trading gate.
- Verify EOD flatten path and broker connectivity.
- Enable production only after risk approval.
