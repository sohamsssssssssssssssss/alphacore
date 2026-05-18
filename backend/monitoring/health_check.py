from __future__ import annotations

import json
import os
import socket
import urllib.request
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import UTC, datetime, timedelta
from enum import Enum

import sqlalchemy as sa


class ComponentStatus(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    DEGRADED = "DEGRADED"


class HealthChecker:
    def __init__(self, slack_webhook_url: str | None = None):
        self.slack_webhook_url = slack_webhook_url or os.getenv("SLACK_WEBHOOK_URL")

    def check_db(self, engine) -> ComponentStatus:
        def _probe() -> bool:
            with engine.connect() as conn:
                conn.execute(sa.text("SELECT 1"))
            return True

        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(_probe)
            try:
                ok = fut.result(timeout=2.0)
                return ComponentStatus.UP if ok else ComponentStatus.DOWN
            except FuturesTimeout:
                return ComponentStatus.DEGRADED
            except Exception:
                return ComponentStatus.DOWN

    def check_gateway(self, host: str, port: int, timeout: float = 1.0) -> ComponentStatus:
        try:
            with socket.create_connection((host, int(port)), timeout=float(timeout)):
                return ComponentStatus.UP
        except socket.timeout:
            return ComponentStatus.DEGRADED
        except Exception:
            return ComponentStatus.DOWN

    def check_feed(self, feed_instance) -> ComponentStatus:
        if not hasattr(feed_instance, "is_alive"):
            return ComponentStatus.DOWN
        try:
            return ComponentStatus.UP if bool(feed_instance.is_alive()) else ComponentStatus.DOWN
        except Exception:
            return ComponentStatus.DOWN

    def check_engine(self, engine_instance) -> ComponentStatus:
        if not hasattr(engine_instance, "is_running"):
            return ComponentStatus.DOWN
        try:
            return ComponentStatus.UP if bool(engine_instance.is_running()) else ComponentStatus.DOWN
        except Exception:
            return ComponentStatus.DOWN

    def check_broker(self, broker_instance) -> ComponentStatus:
        if not hasattr(broker_instance, "ping"):
            return ComponentStatus.DOWN
        try:
            return ComponentStatus.UP if bool(broker_instance.ping()) else ComponentStatus.DOWN
        except Exception:
            return ComponentStatus.DOWN

    def check_all(self, db_engine, gateway_host, gateway_port, feed, engine, broker) -> dict:
        status = {
            "db": self.check_db(db_engine),
            "gateway": self.check_gateway(gateway_host, gateway_port),
            "feed": self.check_feed(feed),
            "engine": self.check_engine(engine),
            "broker": self.check_broker(broker),
        }
        downs = [k for k, v in status.items() if v == ComponentStatus.DOWN]
        if downs:
            try:
                self._post_slack(f"Health check alert: DOWN components: {', '.join(downs)}")
            except Exception:
                pass
        return status

    def _post_slack(self, message: str) -> None:
        if not self.slack_webhook_url:
            return
        payload = json.dumps({"text": message}).encode("utf-8")
        req = urllib.request.Request(
            self.slack_webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=2.0):
            return


class UptimeTracker:
    def __init__(self):
        self._events: deque[tuple[datetime, str, ComponentStatus]] = deque()

    def record(self, component: str, status: ComponentStatus) -> None:
        self._events.append((datetime.now(UTC), str(component), ComponentStatus(status)))

    def uptime_pct(self, component: str, window_days: int = 30) -> float:
        cutoff = datetime.now(UTC) - timedelta(days=int(window_days))
        vals = [s for ts, c, s in self._events if c == component and ts >= cutoff]
        if not vals:
            return 100.0
        up = sum(1 for s in vals if s == ComponentStatus.UP)
        return float((up / len(vals)) * 100.0)

    def summary(self) -> dict[str, float]:
        components = {c for _ts, c, _s in self._events}
        return {c: self.uptime_pct(c) for c in sorted(components)}

    def is_meeting_sla(self, component: str, target_pct: float = 99.9) -> bool:
        return self.uptime_pct(component) >= float(target_pct)
