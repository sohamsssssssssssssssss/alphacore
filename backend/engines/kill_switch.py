"""Global kill switch to halt scheduler cycles."""

from __future__ import annotations

from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class KillSwitch:
    def __init__(self):
        self._active = False
        self._activated_at = None
        self._reason = None

    def activate(self, reason: str = "Manual trigger"):
        self._active = True
        self._activated_at = datetime.utcnow().isoformat()
        self._reason = reason
        logger.critical("KILL SWITCH ACTIVATED: %s", reason)

    def deactivate(self):
        self._active = False
        self._activated_at = None
        self._reason = None
        logger.info("Kill switch deactivated")

    @property
    def is_active(self) -> bool:
        return self._active

    def status(self) -> dict:
        return {
            "active": self._active,
            "activated_at": self._activated_at,
            "reason": self._reason,
        }


kill_switch = KillSwitch()
