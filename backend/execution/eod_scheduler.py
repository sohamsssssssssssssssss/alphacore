from __future__ import annotations

import argparse
import logging
import time
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)


class EODScheduler:
    def __init__(self, broker, target_time: str = "15:20", timezone: str = "Asia/Kolkata", dry_run: bool = False):
        self.broker = broker
        self.target_time = target_time
        self.timezone = timezone
        self.dry_run = bool(dry_run)
        self._scheduler: BackgroundScheduler | None = None

    def start(self) -> None:
        hour_str, minute_str = self.target_time.split(":", 1)
        hour = int(hour_str)
        minute = int(minute_str)

        self._scheduler = BackgroundScheduler(timezone=self.timezone)
        self._scheduler.add_job(
            self.flatten_all_positions,
            trigger="cron",
            hour=hour,
            minute=minute,
            timezone=self.timezone,
            id="eod_flatten",
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info("EOD scheduler started. Will flatten at 15:20 IST.")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def flatten_all_positions(self) -> None:
        positions = self.broker.get_positions() or []

        # Optional pending order cancellation support (duck-typed).
        pending = []
        if hasattr(self.broker, "get_pending_orders"):
            try:
                pending = self.broker.get_pending_orders() or []
            except Exception:
                pending = []

        if self.dry_run:
            logger.info("DRY RUN: would flatten %s positions", len([p for p in positions if int(p.get("qty", 0)) != 0]))
            return

        for order in pending:
            order_id = order.get("order_id")
            if order_id:
                self.broker.cancel_order(order_id)

        for pos in positions:
            symbol = str(pos.get("symbol", ""))
            qty = int(pos.get("qty", 0) or 0)
            if qty == 0:
                continue
            if qty > 0:
                logger.info("Flattening %s: SELL %s @ MARKET", symbol, qty)
                self.broker.place_order(symbol, "SELL", qty, "MARKET", "MIS")
            else:
                logger.info("Flattening %s: BUY %s @ MARKET", symbol, abs(qty))
                self.broker.place_order(symbol, "BUY", abs(qty), "MARKET", "MIS")

    def stop(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.dry_run:
        print("Dry Run: Would trigger flatten_all_positions at 15:20 IST.")
        print("Currently simulating flattening of 0 positions.")


if __name__ == "__main__":
    main()
