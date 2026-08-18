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

    _WAVE_POLL_SECONDS = 1.0
    _MAX_WAVE_WAIT_SECONDS = 300.0

    def __init__(self, launch_single_fn: Callable[[str, dict[str, Any] | None], dict[str, Any]]) -> None:
        self.launch_single_fn = launch_single_fn
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._cancelled = False
        self._cancel_event = threading.Event()
        self.queue: list[str] = []
        self.delay_seconds: float = 2.5
        self.wave_size: int = 0
        self.wave_pause_seconds: float = 0.0
        self.ready_check: Callable[[], dict[str, Any]] | None = None
        self.target: dict[str, Any] | None = None
        self.status: dict[str, Any] = {
            "in_progress": False,
            "total": 0,
            "launched": 0,
            "failed": 0,
            "current_account": None,
            "wave": 0,
            "waves": 0,
            "waiting_for_wave": False,
            "wave_reason": "",
        }

    def start_batch(
        self,
        account_ids: list[str],
        target: dict[str, Any] | None = None,
        delay_seconds: float = 2.5,
        *,
        wave_size: int = 0,
        wave_pause_seconds: float = 0.0,
        ready_check: Callable[[], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
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

            try:
                normalized_wave = int(wave_size or 0)
                normalized_pause = float(wave_pause_seconds or 0.0)
            except (TypeError, ValueError) as exc:
                raise ValidationError("Batch wave settings must be numbers.") from exc
            if not 0 <= normalized_wave <= 100:
                raise ValidationError("A launch wave must hold between 1 and 100 accounts.")
            if not math.isfinite(normalized_pause) or not 0 <= normalized_pause <= 3600:
                raise ValidationError("The pause between waves must be between 0 and 3600 seconds.")
            if ready_check is not None and not callable(ready_check):
                raise ValidationError("The launch readiness check is invalid.")

            self.queue = normalized
            self.target = dict(target) if target is not None else None
            self.delay_seconds = normalized_delay
            self.wave_size = normalized_wave
            self.wave_pause_seconds = normalized_pause
            self.ready_check = ready_check
            self._cancelled = False
            self._cancel_event.clear()
            self.status = {
                "in_progress": True,
                "total": len(self.queue),
                "launched": 0,
                "failed": 0,
                "current_account": None,
                "wave": 1 if normalized_wave else 0,
                "waves": math.ceil(len(self.queue) / normalized_wave) if normalized_wave else 1,
                "waiting_for_wave": False,
                "wave_reason": "",
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

    def _wait_for_wave(self, index: int) -> None:
        """Hold the queue between waves, then wait until the machine is ready.

        The fixed pause always applies.  When a readiness check is wired the
        launcher then polls it, but never for ever: after the bounded window it
        continues and says why, because a stuck probe must not strand a batch.
        """

        with self._lock:
            self.status["waiting_for_wave"] = True
            self.status["wave_reason"] = "Pausing between waves."
        pause = self.wave_pause_seconds if self.wave_pause_seconds else self.delay_seconds
        self._cancel_event.wait(pause)

        check = self.ready_check
        if check is not None:
            deadline = 0.0
            reason = ""
            while deadline < self._MAX_WAVE_WAIT_SECONDS and not self._cancel_event.is_set():
                try:
                    verdict = check() or {}
                except Exception:  # noqa: BLE001 - a probe must not break a batch
                    logger.warning("The launch readiness check failed", exc_info=True)
                    reason = "The readiness check failed, so the batch continued."
                    break
                if verdict.get("allowed", True):
                    reason = ""
                    break
                reason = str(verdict.get("reason") or "Waiting for the machine to free up.")
                with self._lock:
                    self.status["wave_reason"] = reason
                self._cancel_event.wait(self._WAVE_POLL_SECONDS)
                deadline += self._WAVE_POLL_SECONDS
            if reason and deadline >= self._MAX_WAVE_WAIT_SECONDS:
                logger.info("Wave gate timed out: %s", reason)

        with self._lock:
            self.status["waiting_for_wave"] = False
            self.status["wave_reason"] = ""
            if self.wave_size:
                self.status["wave"] = (index + 1) // self.wave_size + 1

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

            if idx >= len(self.queue) - 1:
                continue
            # A wave boundary is where the machine gets to breathe: the whole
            # point of launching 20 alts three at a time.
            if self.wave_size and (idx + 1) % self.wave_size == 0:
                self._wait_for_wave(idx)
            else:
                self._cancel_event.wait(self.delay_seconds)

        with self._lock:
            self.status["in_progress"] = False
            self.status["current_account"] = None
            logger.info("Batch launch completed.")
