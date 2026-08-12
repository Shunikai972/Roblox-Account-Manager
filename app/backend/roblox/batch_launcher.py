"""Roblox Batch Launcher with configurable join delays."""

from __future__ import annotations

import logging
import math
import threading
from typing import Any, Callable

from app.backend.core.errors import ConflictError, ValidationError

logger = logging.getLogger("astro.batch_launcher")


class BatchLauncher:
    """Orchestrates launching a queue of Roblox accounts with configured delays."""

    def __init__(self, launch_single_fn: Callable[[str, dict[str, Any] | None], dict[str, Any]]) -> None:
        self.launch_single_fn = launch_single_fn
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._cancelled = False
        self._cancel_event = threading.Event()
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
                raise ConflictError("A batch launch is already in progress.")

            if not isinstance(account_ids, list) or not account_ids or len(account_ids) > 100:
                raise ValidationError("Select between 1 and 100 accounts for a batch launch.")
            normalized = [str(account_id).strip() for account_id in account_ids]
            if any(not account_id or len(account_id) > 100 or any(ord(character) < 33 for character in account_id) for account_id in normalized):
                raise ValidationError("Batch account identifiers are invalid.")
            if len(normalized) != len(set(normalized)):
                raise ValidationError("A batch launch cannot contain duplicate accounts.")
            try:
                normalized_delay = float(delay_seconds)
            except (TypeError, ValueError) as exc:
                raise ValidationError("Batch launch delay must be a number.") from exc
            if not math.isfinite(normalized_delay) or not 0.5 <= normalized_delay <= 3600:
                raise ValidationError("Batch launch delay must be between 0.5 and 3600 seconds.")
            if target is not None and not isinstance(target, dict):
                raise ValidationError("Batch launch target is invalid.")

            self.queue = normalized
            self.target = dict(target) if target is not None else None
            self.delay_seconds = normalized_delay
            self._cancelled = False
            self._cancel_event.clear()
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
            self._cancel_event.set()
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
                logger.info("Launching queued Roblox account %d/%d", idx + 1, len(self.queue))
                result = self.launch_single_fn(account_id, self.target)
                with self._lock:
                    if isinstance(result, dict) and result.get("accepted") is False:
                        self.status["failed"] += 1
                    else:
                        self.status["launched"] += 1
            except Exception:
                logger.warning("Queued Roblox launch failed", exc_info=True)
                with self._lock:
                    self.status["failed"] += 1

            # Sleep delay between launches unless it's the last item
            if idx < len(self.queue) - 1:
                self._cancel_event.wait(self.delay_seconds)

        with self._lock:
            self.status["in_progress"] = False
            self.status["current_account"] = None
            logger.info("Batch launch completed.")
