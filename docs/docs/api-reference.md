# API Reference

## AuditLogger
Primary methods:
- `append(event)`
- `export_csv(start_date, end_date, path)`
- `replay_session(session_date)`

`append` is append-only and validates event taxonomy before persistence.

## UserManager
Primary methods:
- `create_user(id, name, capital, tier, risk_limits)`
- `get_user(user_id)`
- `set_kill_switch(user_id, active)`

User-level risk and execution factories are gated by kill-switch state.

## HealthChecker
Primary method:
- `check_all(db_engine, gateway_host, gateway_port, feed, engine, broker)`

Returns normalized component status map and emits Slack alert on DOWN status.

## RiskGate
Primary interfaces:
- `check_order` (mapped to implementation `evaluate_order`)
- `RiskViolationException`

`RiskViolationException` is raised on rule breach with rule/value/limit context.

## BaseStrategy Interface
Required hooks:
- `on_orderbook(symbol, bids, asks)`
- `on_signal(symbol, model_name, prediction, confidence)`
- `on_fill(symbol, qty, price, side)`
- `on_regime_change(old_regime, new_regime)`

Intent output is emitted through queue-based order helpers.
