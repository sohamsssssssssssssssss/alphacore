# Incident Response Runbook

## On-call Contacts
- Primary on-call: _TBD_
- Secondary on-call: _TBD_
- Escalation manager: _TBD_

## Service Health Check Commands
```bash
python -m backend.monitoring.health_check
```

## Common Incidents

### Feed Down
- Symptom: gateway/feed status DOWN, missing order book updates.
- Immediate action: fail over feed source, pause live order emission.
- Root cause investigation: gateway logs, socket saturation, upstream disconnects.
- Resolution: restore feed connectivity, confirm sequence continuity, resume traffic.

### DB Unreachable
- Symptom: persistence failures, `check_db` returns DOWN/DEGRADED.
- Immediate action: switch to buffered mode, alert DBA.
- Root cause investigation: network path, connection pool exhaustion, DB failover state.
- Resolution: restore connectivity, replay buffered events, validate partition health.

### Broker API Timeout
- Symptom: order ACK delays, place/cancel failures.
- Immediate action: enable paper fallback, freeze new directional exposure.
- Root cause investigation: broker status page, API rate limits, auth token validity.
- Resolution: recover API session, replay pending intents safely.

### Risk Gate Firing
- Symptom: repeated `RiskViolationException` events.
- Immediate action: engage kill switch for affected strategy/user.
- Root cause investigation: position drift, PnL shocks, order burst behavior.
- Resolution: reduce sizing, tighten limits, validate model outputs before re-enable.

### EOD Flatten Failure
- Symptom: residual positions after 15:20 IST flatten job.
- Immediate action: manually send market flatten orders.
- Root cause investigation: scheduler status, pending-order cancellation path, broker rejects.
- Resolution: close exposure, reconcile fills, patch scheduler retry logic.

## Capacity Planning
- Order rate limits: enforce and monitor per-user/per-strategy burst ceilings.
- DB partition rotation: monthly audit/data partitions with retention checks.
- Paper-to-live graduation: require stable 60-day paper metrics and zero critical incidents.
