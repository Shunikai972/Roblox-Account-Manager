"""Roblox Batch Launcher with configurable join delays."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

logger = logging.getLogger("astro.batch_launcher")


class BatchLauncher:
    """Orchestrates launching a queue of Roblox accounts with configured delays."""

    def __init__(self, launch_single_fn: Callable[[str, dict[str, Any] | None], dict[str, Any]]) -> None:
        self.launch_single_fn = launch_single_fn
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._cancelled = False
        self.queue: list[str] = []
        self.delay_seconds: float = 2.5
        self.target: dict[str, Any] | None = None
        self.status: dict[str, Any] = {
            "in_progress": False,
            "total": 0,
            "launched": 0,
            "failed": 0,
            "current_account": None,
        }

    def start_batch(self, account_ids: list[str], target: dict[str, Any] | None = None, delay_seconds: float = 2.5) -> dict[str, Any]:
        with self._lock:
            if self.status["in_progress"]:
                raise RuntimeError("A batch launch is already in progress.")

            self.queue = list(account_ids)
            self.target = target
            self.delay_seconds = max(0.5, float(delay_seconds))
            self._cancelled = False
            self.status = {
                "in_progress": True,
                "total": len(self.queue),
                "launched": 0,
                "failed": 0,
                "current_account": None,
            }

            self._thread = threading.Thread(target=self._run_batch, daemon=True)
            self._thread.start()
            return dict(self.status)

    def cancel_batch(self) -> dict[str, Any]:
        with self._lock:
            self._cancelled = True
            self.status["in_progress"] = False
            return dict(self.status)

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self.status)

    def _run_batch(self) -> None:
        for idx, account_id in enumerate(self.queue):
            with self._lock:
                if self._cancelled:
                    logger.info("Batch launch cancelled by user.")
                    break
                self.status["current_account"] = account_id

            try:
                logger.info(f"Batch launching account {account_id} ({idx + 1}/{len(self.queue)})")
                self.launch_single_fn(account_id, self.target)
                with self._lock:
                    self.status["launched"] += 1
            except Exception as exc:
                logger.error(f"Batch launch failed for {account_id}: {exc}")
                with self._lock:
                    self.status["failed"] += 1

            # Sleep delay between launches unless it's the last item
            if idx < len(self.queue) - 1:
                end_time = time.time() + self.delay_seconds
                while time.time() < end_time:
                    if self._cancelled:
                        break
                    time.sleep(0.1)

        with self._lock:
            self.status["in_progress"] = False
            self.status["current_account"] = None
            logger.info("Batch launch completed.")
