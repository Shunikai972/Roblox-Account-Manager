"""Fleet features: statistics, schedule, health, servers, comfort, alerts.

This mixin holds the v9 surfaces so the application service stays readable.
Every method here is defensive on purpose: it runs on a watcher tick or from
the UI thread, and a bad stored row must never take the app down.

Nothing in this file talks to Roblox directly.  It joins what the watcher
already knows with the bounded engines under ``app/backend``.
"""

from __future__ import annotations

from datetime import datetime
import time
from typing import Any, Mapping

from app.backend.automations.coordination import (
    follower_plan,
    party_plan,
    spread_plan,
    sync_plan,
)
from app.backend.automations.macro_studio import (
    apply_profile_and_variables,
    describe_versions,
    flatten_steps,
    profile_macro,
    push_version,
    rollback_version,
    validated_key_profile,
    validated_key_profiles,
    validated_variables,
)
from app.backend.automations.scheduler import (
    ScheduledTask,
    describe_schedule,
    due_tasks,
    validated_task,
    validated_tasks,
)
from app.backend.automations.launch_profiles import (
    MAX_PROFILES as MAX_LAUNCH_PROFILES,
    describe_profile,
    normalize_profiles,
    profile_target,
    upsert_profile,
    validated_profile,
)
from app.backend.core.account_health import (
    collect_tags,
    evaluate_account_health,
    matches_filters,
    normalize_tags,
    validated_custom_fields,
)
from app.backend.core.errors import (
    AppError,
    ConflictError,
    NotFoundError,
    StorageError,
    ValidationError,
)
from app.backend.integrations.alerts import (
    ALERT_EVENTS,
    DEFAULT_MIN_INTERVAL_SECONDS,
    build_event,
    daily_report,
    discord_payload,
    post_json,
    push_payload,
    redact,
    should_send,
    validated_webhook_url,
)
from app.backend.roblox.server_registry import (
    blacklist_add,
    blacklist_remove,
    coerce_history,
    inspect_history,
    normalize_blacklist,
    normalize_job_id,
    normalize_place_id,
    normalize_region,
    pick_server,
    record_visit,
)
from app.backend.watchers.comfort import (
    audio_plan,
    focus_plan,
    queue_gate,
    shutdown_plan,
    sleep_plan,
)
from app.backend.watchers.statistics import (
    DEFAULT_WINDOW_DAYS,
    MAX_RUNS,
    MAX_SESSIONS,
    MAX_WINDOW_DAYS,
    SessionRecord,
    build_statistics,
    compare_sessions,
)

# Stored under these keys as JSON.  None of them may contain a word the
# repository treats as a credential, or the write is refused outright.
KEY_TASKS = "fleet.schedule_tasks"
KEY_LEDGER = "fleet.instance_ledger"
KEY_MACRO_LEDGER = "fleet.macro_ledger"
KEY_SERVERS = "fleet.server_history"
KEY_BLACKLIST = "fleet.server_blacklist"
KEY_ALERTS = "fleet.alerts"
KEY_PROFILES = "fleet.key_profiles"
KEY_VERSIONS = "fleet.macro_versions"
KEY_VOLUMES = "fleet.audio_volumes"
KEY_LAUNCH_PROFILES = "launcher.profiles"

MAX_RESUME_ATTEMPTS = 40
MAX_RESUME_SECONDS = 900.0

DEFAULT_ALERTS: dict[str, Any] = {
    "enabled": False,
    "discord_webhook_url": "",
    "phone_webhook_url": "",
    "phone_topic": "",
    "min_interval_seconds": DEFAULT_MIN_INTERVAL_SECONDS,
    "events": sorted(ALERT_EVENTS),
    "daily_report_at": "09:00",
}


class FleetFeaturesMixin:
    """Statistics, schedule, account health, servers, comfort and alerts."""

    # Shared plumbing --------------------------------------------------------

    def _fleet_state(self) -> dict[str, Any]:
        state = getattr(self, "_fleet_cache", None)
        if state is None:
            state = {
                "open": {},            # pid -> open session row
                "crashed": set(),      # pids whose exit looked like a crash
                "activity": {},        # pid -> last observed event time
                "macro_seen": set(),   # run ids already written to the ledger
                "last_macro": {},      # account id -> last macro id started
                "resume": {},          # account id -> pending resume request
                "alert_sent": {},      # event name -> last send time
                "report_day": "",
            }
            self._fleet_cache = state
        return state

    def _load_json(self, key: str, default: Any) -> Any:
        try:
            stored = self.repository.get_setting(key, default)
        except Exception:  # noqa: BLE001 - a corrupt row must not break a tick
            self.logger.warning("Stored fleet data for %s could not be read.", key)
            return default
        return default if stored is None else stored

    def _save_json(self, key: str, value: Any) -> None:
        try:
            self.repository.set_setting(key, value)
        except Exception as exc:  # noqa: BLE001
            raise StorageError("That change could not be saved.") from exc

    @staticmethod
    def _epoch(value: Any) -> float | None:
        """Best-effort conversion of a stored timestamp to a POSIX float."""

        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value) if value > 0 else None
        text = str(value).strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None

    def _fleet_username(self, account_id: str) -> str:
        if not account_id:
            return ""
        try:
            return str(self.repository.get_account(account_id).username)
        except Exception:  # noqa: BLE001 - a deleted account still has history
            return ""

    def _safe_macro_runs(self) -> list[dict[str, Any]]:
        try:
            return [dict(run) for run in self.macro_engine.list_runs()]
        except Exception:  # noqa: BLE001
            return []

    def _instance_rows(self) -> list[dict[str, Any]]:
        """The shape the comfort engine expects, built from the live watcher."""

        activity = self._fleet_state()["activity"]
        macro_pids = {
            int(run.get("pid") or 0)
            for run in self._safe_macro_runs()
            if not run.get("finished_at")
        }
        rows: list[dict[str, Any]] = []
        for instance in self.monitor.current_instances():
            try:
                pid = int(getattr(instance, "pid", 0) or 0)
            except (TypeError, ValueError):
                continue
            if pid <= 0:
                continue
            account_id = str(getattr(instance, "account_id", "") or "")
            rows.append(
                {
                    "pid": pid,
                    "account_id": account_id,
                    "username": self._fleet_username(account_id),
                    "macro_running": pid in macro_pids,
                    "watched": False,
                    "last_activity_at": activity.get(pid),
                }
            )
        return rows

    # Ledgers ----------------------------------------------------------------

    def _update_fleet_ledgers(self, scan: Any = None) -> None:
        """Close finished sessions and archive finished macro runs.

        Called from the watcher tick.  It is the only writer of the history the
        statistics screen reads, so it stays cheap and never raises.
        """

        try:
            self._update_session_ledger(scan)
            self._update_macro_ledger()
        except Exception:  # noqa: BLE001 - history is never worth a crash
            self.logger.warning("Fleet history could not be updated on this tick.")

    def _update_session_ledger(self, scan: Any = None) -> None:
        state = self._fleet_state()
        now = time.time()
        for event in tuple(getattr(scan, "events", ()) or ()):
            pid = getattr(event, "pid", 0)
            try:
                pid = int(pid or 0)
            except (TypeError, ValueError):
                continue
            if pid <= 0:
                continue
            state["activity"][pid] = now
            if str(getattr(event, "kind", "")) in {"crashed", "terminated"}:
                state["crashed"].add(pid)

        live: set[int] = set()
        for instance in self.monitor.current_instances():
            try:
                pid = int(getattr(instance, "pid", 0) or 0)
            except (TypeError, ValueError):
                continue
            if pid <= 0:
                continue
            live.add(pid)
            if pid in state["open"]:
                continue
            account_id = str(getattr(instance, "account_id", "") or "")
            state["open"][pid] = {
                "account_id": account_id,
                "username": self._fleet_username(account_id),
                "started_at": self._epoch(getattr(instance, "started_at", None)) or now,
                "place_id": str(getattr(instance, "place_id", "") or ""),
                "macro_runs": 0,
                "macro_failures": 0,
            }
            state["activity"].setdefault(pid, now)

        finished = [pid for pid in state["open"] if pid not in live]
        if not finished:
            return
        ledger = list(self._load_json(KEY_LEDGER, []) or [])
        for pid in finished:
            row = state["open"].pop(pid, None)
            state["activity"].pop(pid, None)
            if not isinstance(row, dict):
                continue
            row["ended_at"] = now
            row["crashed"] = pid in state["crashed"]
            state["crashed"].discard(pid)
            ledger.append(row)
        self._save_json(KEY_LEDGER, ledger[-MAX_SESSIONS:])

    def _update_macro_ledger(self) -> None:
        state = self._fleet_state()
        runs = self._safe_macro_runs()
        fresh: list[dict[str, Any]] = []
        for run in runs:
            run_id = str(run.get("run_id") or "")
            account_id = str(run.get("account_id") or "")
            if account_id and run.get("macro_id"):
                state["last_macro"][account_id] = str(run["macro_id"])
            if not run_id or run.get("finished_at") is None or run_id in state["macro_seen"]:
                continue
            state["macro_seen"].add(run_id)
            fresh.append(
                {
                    "run_id": run_id,
                    "macro_id": str(run.get("macro_id") or ""),
                    "name": str(run.get("macro_name") or ""),
                    "account_id": account_id,
                    "state": str(run.get("state") or ""),
                    "error": run.get("error"),
                    "started_at": self._epoch(run.get("started_at")),
                    "finished_at": self._epoch(run.get("finished_at")),
                }
            )
        if not fresh:
            return
        ledger = list(self._load_json(KEY_MACRO_LEDGER, []) or [])
        ledger.extend(fresh)
        self._save_json(KEY_MACRO_LEDGER, ledger[-MAX_RUNS:])
        if len(state["macro_seen"]) > MAX_RUNS:
            state["macro_seen"] = set(list(state["macro_seen"])[-MAX_RUNS:])

    def _sessions(self) -> list[SessionRecord]:
        rows = list(self._load_json(KEY_LEDGER, []) or [])
        open_rows = [dict(row) for row in self._fleet_state()["open"].values()]
        records: list[SessionRecord] = []
        for row in (rows + open_rows)[-MAX_SESSIONS:]:
            if not isinstance(row, Mapping):
                continue
            started = self._epoch(row.get("started_at"))
            if not started:
                continue
            records.append(
                SessionRecord(
                    account_id=str(row.get("account_id") or "")[:128],
                    username=str(row.get("username") or "")[:64],
                    started_at=started,
                    ended_at=self._epoch(row.get("ended_at")),
                    crashed=bool(row.get("crashed", False)),
                    place_id=str(row.get("place_id") or "")[:32],
                    macro_runs=max(0, int(row.get("macro_runs") or 0)),
                    macro_failures=max(0, int(row.get("macro_failures") or 0)),
                )
            )
        return records

    def _macro_history(self) -> list[dict[str, Any]]:
        stored = [dict(row) for row in (self._load_json(KEY_MACRO_LEDGER, []) or []) if isinstance(row, Mapping)]
        seen = {str(row.get("run_id") or "") for row in stored}
        for run in self._safe_macro_runs():
            run_id = str(run.get("run_id") or "")
            if run_id in seen:
                continue
            stored.append(
                {
                    "run_id": run_id,
                    "macro_id": str(run.get("macro_id") or ""),
                    "name": str(run.get("macro_name") or ""),
                    "account_id": str(run.get("account_id") or ""),
                    "state": str(run.get("state") or ""),
                    "error": run.get("error"),
                    "started_at": self._epoch(run.get("started_at")),
                    "finished_at": self._epoch(run.get("finished_at")),
                }
            )
        return stored[-MAX_RUNS:]

    # Statistics -------------------------------------------------------------

    def get_statistics(self, window_days: Any = None) -> dict[str, Any]:
        """Dashboard, hourly heatmap, reliability and macro success rates."""

        days = DEFAULT_WINDOW_DAYS
        if window_days is not None:
            try:
                days = int(window_days)
            except (TypeError, ValueError) as exc:
                raise ValidationError("The statistics window must be a number of days.") from exc
            if not 1 <= days <= MAX_WINDOW_DAYS:
                raise ValidationError(f"The statistics window must be between 1 and {MAX_WINDOW_DAYS} days.")
        payload = build_statistics(
            sessions=self._sessions(),
            runs=self._macro_history(),
            now=time.time(),
            window_days=days,
        )
        payload["window_days"] = days
        return payload

    def compare_account_sessions(self, account_id: str) -> dict[str, Any]:
        """Compare an account's two most recent sessions."""

        identifier = str(account_id or "").strip()
        if not identifier:
            raise ValidationError("Select an account to compare.")
        rows = sorted(
            (row for row in self._sessions() if row.account_id == identifier),
            key=lambda row: row.started_at,
        )
        if len(rows) < 2:
            return {
                "available": False,
                "account_id": identifier,
                "reason": "This account needs two recorded sessions before they can be compared.",
            }
        result = compare_sessions(rows[-2], rows[-1], now=time.time())
        result["available"] = True
        result["account_id"] = identifier
        return result

    # Schedule ---------------------------------------------------------------

    def _stored_tasks(self) -> list[ScheduledTask]:
        try:
            return validated_tasks(self._load_json(KEY_TASKS, []) or [])
        except ValidationError:
            self.logger.warning("A stored scheduled task was invalid and was ignored.")
            return []

    def _write_tasks(self, tasks: list[ScheduledTask]) -> None:
        self._save_json(KEY_TASKS, [task.to_dict() for task in tasks])

    def list_scheduled_tasks(self) -> dict[str, Any]:
        tasks = self._stored_tasks()
        return {
            "tasks": describe_schedule(tasks, now=time.time()),
            "count": len(tasks),
        }

    def save_scheduled_task(self, task: Mapping[str, Any]) -> dict[str, Any]:
        payload = self._require_mapping(task, "Scheduled task")
        existing = self._stored_tasks()
        identifier = str(payload.get("id") or "").strip()
        validated = validated_task(payload, existing_id=identifier)
        replaced = False
        for index, current in enumerate(existing):
            if current.id == validated.id:
                validated.last_run_at = current.last_run_at
                existing[index] = validated
                replaced = True
                break
        if not replaced:
            existing.append(validated)
            existing = validated_tasks([item.to_dict() for item in existing])
        self._write_tasks(existing)
        self._activity("schedule", f"Scheduled task saved: {validated.name}")
        return validated.to_dict()

    def delete_scheduled_task(self, task_id: str) -> dict[str, Any]:
        identifier = str(task_id or "").strip()
        remaining = [task for task in self._stored_tasks() if task.id != identifier]
        if len(remaining) == len(self._stored_tasks()):
            raise NotFoundError("That scheduled task was not found.")
        self._write_tasks(remaining)
        return {"deleted": True, "id": identifier}

    def run_due_scheduled_tasks(self, *, silent: bool = False) -> dict[str, Any]:
        """Run whatever the clock says is due, once per slot."""

        now = time.time()
        tasks = self._stored_tasks()
        if not tasks:
            return {"ran": [], "checked_at": now}
        try:
            due = due_tasks(tasks, now=now)
        except ValidationError:
            return {"ran": [], "checked_at": now}
        ran: list[dict[str, Any]] = []
        for task in due:
            outcome = self._run_task(task)
            task.last_run_at = now
            ran.append({"id": task.id, "name": task.name, "action": task.action, **outcome})
            self._activity("schedule", f"Scheduled task ran: {task.name}", metadata=outcome)
            self._dispatch_alert(
                "schedule_ran",
                title=f"Scheduled task: {task.name}",
                body=str(outcome.get("detail") or ""),
                level="success" if outcome.get("ok") else "warning",
            )
        if ran:
            self._write_tasks(tasks)
            if not silent:
                self._notice("info", "Schedule", f"{len(ran)} scheduled task(s) ran.")
        return {"ran": ran, "checked_at": now}

    def _run_task(self, task: ScheduledTask) -> dict[str, Any]:
        try:
            if task.action == "launch_group":
                accounts = [
                    str(account.get("id"))
                    for account in self.list_accounts()
                    if str(account.get("group_id") or "") == task.group_id
                ]
                if not accounts:
                    return {"ok": False, "detail": "That group has no accounts."}
                self.start_wave_launch(accounts)
                return {"ok": True, "detail": f"{len(accounts)} account(s) queued."}
            if task.action == "launch_accounts":
                if not task.account_ids:
                    return {"ok": False, "detail": "No accounts are selected."}
                self.start_wave_launch(list(task.account_ids))
                return {"ok": True, "detail": f"{len(task.account_ids)} account(s) queued."}
            if task.action == "stop_macros":
                result = self.stop_all_macros()
                return {"ok": True, "detail": f"{len(result.get('stopped') or [])} macro run(s) stopped."}
            if task.action == "start_macro":
                return self._start_scheduled_macro(task)
            if task.action == "apply_resource_plan":
                apply_plan = getattr(self, "apply_resource_plan", None)
                if not callable(apply_plan):
                    return {"ok": False, "detail": "The resource planner is unavailable."}
                apply_plan()
                return {"ok": True, "detail": "The resource plan was applied."}
            if task.action == "close_instances":
                return self._close_scheduled_instances(task)
        except AppError as exc:
            return {"ok": False, "detail": str(exc)}
        except Exception:  # noqa: BLE001 - one bad task must not stop the rest
            self.logger.warning("A scheduled task failed", exc_info=True)
            return {"ok": False, "detail": "That task failed. Check Diagnostics."}
        return {"ok": False, "detail": "That task action is not supported."}

    def _start_scheduled_macro(self, task: ScheduledTask) -> dict[str, Any]:
        wanted = set(task.account_ids)
        for instance in self.monitor.current_instances():
            account_id = str(getattr(instance, "account_id", "") or "")
            if wanted and account_id not in wanted:
                continue
            self.start_macro(task.macro_id, int(getattr(instance, "pid", 0) or 0))
            return {"ok": True, "detail": f"Macro started on pid {getattr(instance, 'pid', 0)}."}
        return {"ok": False, "detail": "No verified Roblox client was available for that macro."}

    def _close_scheduled_instances(self, task: ScheduledTask) -> dict[str, Any]:
        """Close clients, and only ever because a person scheduled exactly that.

        Automatic rules never close a live client in this build.  A schedule is
        a written instruction from the operator, so it is honoured.
        """

        wanted = set(task.account_ids)
        closed = 0
        for instance in list(self.monitor.current_instances()):
            account_id = str(getattr(instance, "account_id", "") or "")
            if wanted and account_id not in wanted:
                continue
            try:
                self.close_instance(int(getattr(instance, "pid", 0) or 0), confirm=True)
                closed += 1
            except AppError:
                continue
        return {"ok": closed > 0, "detail": f"{closed} client(s) closed."}

    # Account health, tags and custom fields ---------------------------------

    def get_account_health(self, filters: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Health, tags and custom fields for every account, with filtering."""

        options = dict(filters or {})
        tags = normalize_tags(options.get("tags") or [])
        status = str(options.get("status") or "").strip().lower()
        query = str(options.get("query") or "").strip()
        running = {
            str(getattr(instance, "account_id", "") or "")
            for instance in self.monitor.current_instances()
        }
        now = time.time()
        rows: list[dict[str, Any]] = []
        counts: dict[str, int] = {}
        accounts = self.list_accounts()
        for account in accounts:
            health = evaluate_account_health(
                account,
                now=now,
                running=str(account.get("id") or "") in running,
            )
            counts[health["status"]] = counts.get(health["status"], 0) + 1
            merged = {**account, **health}
            if not matches_filters(merged, tags=tags, status=status, query=query):
                continue
            rows.append(
                {
                    "id": account.get("id"),
                    "username": account.get("username"),
                    "display_name": account.get("display_name"),
                    "group_id": account.get("group_id"),
                    "tags": normalize_tags((account.get("metadata") or {}).get("tags")),
                    "custom_fields": dict(account.get("custom_fields") or {}),
                    "priority": int(((account.get("metadata") or {}).get("priority") or 0)),
                    **health,
                }
            )
        return {
            "accounts": rows,
            "tags": collect_tags(accounts),
            "counts": counts,
            "total": len(accounts),
            "shown": len(rows),
            "needs_attention": sum(1 for row in rows if row.get("needs_attention")),
        }

    def update_account_tags(self, account_id: str, tags: Any) -> dict[str, Any]:
        account = self._get_account(account_id)
        metadata = dict(account.metadata or {})
        metadata["tags"] = normalize_tags(tags)
        return self.update_account(account.id, {"metadata": metadata})

    def update_account_fields(self, account_id: str, fields: Any) -> dict[str, Any]:
        account = self._get_account(account_id)
        return self.update_account(account.id, {"custom_fields": validated_custom_fields(fields)})

    def set_account_priority(self, account_id: str, priority: Any) -> dict[str, Any]:
        account = self._get_account(account_id)
        try:
            value = int(priority)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Priority must be a whole number.") from exc
        if not 0 <= value <= 10:
            raise ValidationError("Priority must be between 0 and 10.")
        metadata = dict(account.metadata or {})
        metadata["priority"] = value
        return self.update_account(account.id, {"metadata": metadata})

    # Servers ----------------------------------------------------------------

    def get_server_registry(self, place_id: Any = None) -> dict[str, Any]:
        history = coerce_history(self._load_json(KEY_SERVERS, []) or [])
        blacklist = normalize_blacklist(self._load_json(KEY_BLACKLIST, []) or [])
        wanted = normalize_place_id(place_id) if place_id else ""
        if wanted:
            history = [record for record in history if record.place_id == wanted]
        payload = inspect_history(history, blacklist=blacklist, now=time.time())
        payload["blacklist_entries"] = blacklist
        payload["place_id"] = wanted
        return payload

    def record_server_visit(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = self._require_mapping(payload, "Server visit")
        history = record_visit(
            self._load_json(KEY_SERVERS, []) or [],
            job_id=normalize_job_id(data.get("job_id")),
            place_id=normalize_place_id(data.get("place_id")),
            region=normalize_region(data.get("region")),
            players=int(data.get("players") or 0),
            max_players=int(data.get("max_players") or 0),
            now=time.time(),
            failed=bool(data.get("failed", False)),
        )
        self._save_json(KEY_SERVERS, [record.to_dict() for record in history])
        return {"recorded": True, "servers": len(history)}

    def update_server_blacklist(self, job_id: str, *, blacklisted: bool = True, note: str = "") -> dict[str, Any]:
        current = self._load_json(KEY_BLACKLIST, []) or []
        identifier = normalize_job_id(job_id)
        if blacklisted:
            updated = blacklist_add(current, job_id=identifier, note=str(note or ""), now=time.time())
        else:
            updated = blacklist_remove(current, job_id=identifier)
        self._save_json(KEY_BLACKLIST, updated)
        return {"job_id": identifier, "blacklisted": bool(blacklisted), "count": len(updated)}

    def pick_best_server(self, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        data = dict(payload or {})
        return pick_server(
            self._load_json(KEY_SERVERS, []) or [],
            place_id=normalize_place_id(data.get("place_id")),
            blacklist=self._load_json(KEY_BLACKLIST, []) or [],
            prefer_region=normalize_region(data.get("prefer_region")),
            avoid_job_ids=[normalize_job_id(item) for item in (data.get("avoid_job_ids") or []) if item],
            now=time.time(),
        )

    # Wave launching ---------------------------------------------------------

    def _fleet_launcher_settings(self) -> dict[str, Any]:
        return dict(self.get_settings()["categories"].get("launcher", {}) or {})

    def _fleet_machine_facts(self) -> dict[str, Any]:
        facts = getattr(self, "_system_facts", None)
        if not callable(facts):
            return {}
        try:
            sampled = facts()
        except Exception:  # noqa: BLE001 - a sampling failure never blocks a page
            return {}
        if isinstance(sampled, Mapping):
            return dict(sampled)
        return {
            "cpu_percent": getattr(sampled, "cpu_percent", None),
            "memory_percent": getattr(sampled, "memory_percent", None),
        }

    def _wave_ready_check(self) -> dict[str, Any]:
        """The gate the batch launcher polls between two waves."""

        comfort = dict(self.get_settings()["categories"].get("comfort", {}) or {})
        machine = self._fleet_machine_facts()
        running = len(list(self.monitor.current_instances()))
        pending = 0
        try:
            status = self.batch_launcher.status
            pending = max(0, int(status.get("total", 0) or 0) - int(status.get("launched", 0) or 0))
        except Exception:  # noqa: BLE001
            pending = 0
        return queue_gate(
            cpu_percent=machine.get("cpu_percent"),
            memory_percent=machine.get("memory_percent"),
            running=running,
            pending=pending,
            max_cpu_percent=int(comfort.get("queue_cpu_percent") or 80),
            max_memory_percent=int(comfort.get("queue_memory_percent") or 85),
            max_running=int(comfort.get("queue_max_instances") or 0),
        )

    def start_wave_launch(self, account_ids: Any, target: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Launch a list of accounts in waves, with a breather between each one."""

        if not isinstance(account_ids, list) or not account_ids:
            raise ValidationError("Select the accounts to launch.")
        settings = self._fleet_launcher_settings()
        queue = [str(item) for item in account_ids if str(item or "").strip()]
        if bool(settings.get("skip_running", True)):
            busy = {
                str(getattr(instance, "account_id", "") or "")
                for instance in self.monitor.current_instances()
            }
            filtered = [item for item in queue if item not in busy]
            queue = filtered or queue
        return self.batch_launcher.start_batch(
            queue,
            dict(target) if target else None,
            float(settings.get("delay_seconds") or 4.0),
            wave_size=int(settings.get("max_concurrent") or 3),
            wave_pause_seconds=float(settings.get("wave_pause_seconds") or 0.0),
            ready_check=self._wave_ready_check if bool(settings.get("wait_for_wave", True)) else None,
        )

    def get_wave_status(self) -> dict[str, Any]:
        status = dict(self.batch_launcher.status)
        status["gate"] = self._wave_ready_check()
        status["settings"] = self._fleet_launcher_settings()
        return status

    # Coordination -----------------------------------------------------------

    def _coordination_rows(self, account_ids: Any) -> list[dict[str, str]]:
        wanted = [str(item) for item in (account_ids or []) if str(item or "").strip()]
        if not wanted:
            raise ValidationError("Select the accounts to coordinate.")
        known = {str(account.get("id")): account for account in self.list_accounts()}
        rows: list[dict[str, str]] = []
        for account_id in wanted:
            account = known.get(account_id)
            if account is None:
                raise NotFoundError("One of the selected accounts no longer exists.")
            rows.append({"id": account_id, "username": str(account.get("username") or account_id)})
        return rows

    def plan_coordination(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Preview a spread, follower, synchronised or party launch."""

        data = self._require_mapping(payload, "Coordination request")
        mode = str(data.get("mode") or "spread").strip().lower()
        rows = self._coordination_rows(data.get("account_ids"))
        place_id = normalize_place_id(data.get("place_id")) if data.get("place_id") else ""
        job_id = normalize_job_id(data.get("job_id")) if data.get("job_id") else ""
        stagger = data.get("stagger_seconds")
        if mode == "spread":
            servers = list(data.get("servers") or [])
            if not servers:
                servers = [
                    record.job_id
                    for record in coerce_history(self._load_json(KEY_SERVERS, []) or [])
                    if not place_id or record.place_id == place_id
                ]
            plan = spread_plan(
                rows,
                servers=servers,
                max_per_server=int(data.get("max_per_server") or 1),
                place_id=place_id,
                stagger_seconds=1.5 if stagger is None else stagger,
            )
        elif mode == "followers":
            plan = follower_plan(
                main=rows[0],
                followers=rows[1:],
                job_id=job_id,
                place_id=place_id,
                stagger_seconds=1.5 if stagger is None else stagger,
            )
        elif mode == "sync":
            plan = sync_plan(
                rows,
                action=str(data.get("action") or "launch"),
                job_id=job_id,
                place_id=place_id,
                stagger_seconds=0.0 if stagger is None else stagger,
                now=time.time(),
                countdown_seconds=float(data.get("countdown_seconds") or 3.0),
            )
        elif mode == "party":
            plan = party_plan(
                rows,
                job_id=job_id,
                place_id=place_id,
                stagger_seconds=1.5 if stagger is None else stagger,
            )
        else:
            raise ValidationError("That coordination mode is not supported.")
        plan["mode"] = mode
        return plan

    def run_coordination(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Run a coordination plan through the wave launcher, in plan order."""

        plan = self.plan_coordination(payload)
        steps = [step for step in plan.get("steps", []) if step.get("account_id")]
        if not steps:
            raise ValidationError("That plan has nothing to launch.")
        data = dict(payload or {})
        target = dict(data["target"]) if isinstance(data.get("target"), Mapping) else None
        settings = self._fleet_launcher_settings()
        account_ids = [str(step["account_id"]) for step in steps]
        per_account_targets: dict[str, dict[str, Any] | None] = {}
        for step in steps:
            destination = dict(target or {})
            if step.get("place_id"):
                destination["place_id"] = str(step["place_id"])
            if step.get("job_id"):
                destination["job_id"] = str(step["job_id"])
            per_account_targets[str(step["account_id"])] = destination or None
        status = self.batch_launcher.start_batch(
            account_ids,
            target,
            float(settings.get("delay_seconds") or 4.0),
            wave_size=int(settings.get("max_concurrent") or 3),
            wave_pause_seconds=float(settings.get("wave_pause_seconds") or 0.0),
            ready_check=self._wave_ready_check if bool(settings.get("wait_for_wave", True)) else None,
            per_account_targets=per_account_targets,
        )
        self._activity(
            "coordination",
            f"{plan.get('mode', 'Coordinated')} launch queued for {len(steps)} account(s).",
            metadata={"mode": plan.get("mode"), "accounts": len(steps)},
        )
        return {"plan": plan, "batch": status}

    # Comfort ----------------------------------------------------------------

    def _comfort_settings(self) -> dict[str, Any]:
        return dict(self.get_settings()["categories"].get("comfort", {}) or {})

    def get_comfort_overview(self, focus_pid: Any = None) -> dict[str, Any]:
        """Focus, sleep, per-instance audio, safe shutdown and the launch gate."""

        settings = self._comfort_settings()
        instances = self._instance_rows()
        runs = [run for run in self._safe_macro_runs() if not run.get("finished_at")]
        volumes = dict(self._load_json(KEY_VOLUMES, {}) or {})
        pid: int | None = None
        if focus_pid not in (None, ""):
            try:
                pid = int(focus_pid)
            except (TypeError, ValueError) as exc:
                raise ValidationError("That process id is not a number.") from exc
        return {
            "focus": focus_plan(
                instances,
                focus_pid=pid,
                background_volume=int(settings.get("background_volume") or 0),
                focus_volume=int(settings.get("focus_volume") or 100),
                minimize_others=bool(settings.get("focus_minimizes_others", True)),
            ),
            "sleep": sleep_plan(
                instances,
                now=time.time(),
                idle_minutes=int(settings.get("sleep_after_minutes") or 15),
                include_macro_windows=False,
            ),
            "audio": audio_plan(
                instances,
                volumes=volumes,
                default_volume=int(settings.get("focus_volume") or 100),
                supported=False,
            ),
            "shutdown": shutdown_plan(instances, macro_runs=runs),
            "queue": self._wave_ready_check(),
            "instances": instances,
            "settings": settings,
        }

    def apply_comfort_action(self, action: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Apply what this build can really apply, and report the rest honestly."""

        data = dict(payload or {})
        name = str(action or "").strip().lower()
        if name in {"focus", "sleep"}:
            overview = self.get_comfort_overview(data.get("pid") if name == "focus" else None)
            plan = dict(overview[name])
            requested: list[tuple[int, str]] = []
            if name == "focus":
                conflicts = {int(pid) for pid in plan.get("macro_conflicts", [])}
                for target in plan.get("targets", []):
                    pid = int(target.get("pid") or 0)
                    if target.get("restore"):
                        requested.append((pid, "restore"))
                    elif target.get("minimize") and pid not in conflicts:
                        requested.append((pid, "minimize"))
            else:
                requested.extend(
                    (int(target.get("pid") or 0), "minimize")
                    for target in plan.get("sleeping", [])
                )
            results: list[dict[str, Any]] = []
            failures: list[dict[str, Any]] = []
            for pid, operation in requested:
                try:
                    snapshot = (
                        self.window_visibility.restore(pid)
                        if operation == "restore"
                        else self.window_visibility.minimize(pid)
                    )
                    results.append({"pid": pid, "operation": operation, **snapshot.to_dict()})
                except AppError as exc:
                    failures.append({"pid": pid, "operation": operation, "error": str(exc)})
            plan["requested"] = len(requested)
            plan["results"] = results
            plan["failures"] = failures
            plan["minimized"] = sum(1 for row in results if row["operation"] == "minimize")
            plan["applied"] = bool(results) and not failures
            return plan
        if name == "audio":
            volumes: dict[str, int] = {}
            for key, value in dict(data.get("volumes") or {}).items():
                try:
                    volumes[str(int(key))] = max(0, min(100, int(value)))
                except (TypeError, ValueError) as exc:
                    raise ValidationError("A volume must be a number between 0 and 100.") from exc
            self._save_json(KEY_VOLUMES, volumes)
            return audio_plan(self._instance_rows(), volumes=volumes, supported=False)
        if name == "shutdown":
            plan = shutdown_plan(
                self._instance_rows(),
                macro_runs=[run for run in self._safe_macro_runs() if not run.get("finished_at")],
            )
            if data.get("confirm") is not True:
                plan["applied"] = False
                return plan
            self.stop_all_macros()
            closed = 0
            for step in plan.get("steps", []):
                if step.get("action") != "close":
                    continue
                try:
                    self.close_instance(int(step.get("pid") or 0), confirm=True)
                    closed += 1
                except AppError:
                    continue
            plan["applied"] = True
            plan["closed"] = closed
            self._activity("comfort", f"Safe shutdown closed {closed} client(s).")
            return plan
        raise ValidationError("That comfort action is not supported.")

    # Alerts -----------------------------------------------------------------

    def _alert_config(self) -> dict[str, Any]:
        stored = self._load_json(KEY_ALERTS, {}) or {}
        return {**DEFAULT_ALERTS, **(dict(stored) if isinstance(stored, Mapping) else {})}

    def get_alert_settings(self) -> dict[str, Any]:
        merged = self._alert_config()
        events = sorted({str(item) for item in (merged.get("events") or []) if str(item) in ALERT_EVENTS})
        return {
            "enabled": bool(merged.get("enabled")),
            "events": events or sorted(ALERT_EVENTS),
            "known_events": sorted(ALERT_EVENTS),
            "min_interval_seconds": int(merged.get("min_interval_seconds") or 0),
            "daily_report_at": str(merged.get("daily_report_at") or ""),
            "phone_topic": str(merged.get("phone_topic") or ""),
            # A webhook address carries its own token, so it is write-only:
            # the UI is told whether one exists, never what it is.
            "discord_configured": bool(merged.get("discord_webhook_url")),
            "phone_configured": bool(merged.get("phone_webhook_url")),
        }

    def update_alert_settings(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = self._require_mapping(payload, "Alert settings")
        merged = self._alert_config()
        if "enabled" in data:
            merged["enabled"] = bool(data.get("enabled"))
        if "discord_webhook_url" in data:
            merged["discord_webhook_url"] = validated_webhook_url(data.get("discord_webhook_url"))
        if "phone_webhook_url" in data:
            merged["phone_webhook_url"] = validated_webhook_url(data.get("phone_webhook_url"))
        if "phone_topic" in data:
            merged["phone_topic"] = str(data.get("phone_topic") or "")[:60]
        if "min_interval_seconds" in data:
            try:
                merged["min_interval_seconds"] = max(0, int(data.get("min_interval_seconds") or 0))
            except (TypeError, ValueError) as exc:
                raise ValidationError("The minimum gap must be a number of seconds.") from exc
        if "events" in data:
            merged["events"] = sorted(
                {str(item) for item in (data.get("events") or []) if str(item) in ALERT_EVENTS}
            )
        if "daily_report_at" in data:
            value = str(data.get("daily_report_at") or "").strip()
            if value:
                parts = value.split(":")
                if len(parts) != 2 or not all(part.isdigit() for part in parts):
                    raise ValidationError("The daily report time must look like 09:00.")
                hour, minute = int(parts[0]), int(parts[1])
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValidationError("The daily report time must look like 09:00.")
                value = f"{hour:02d}:{minute:02d}"
            merged["daily_report_at"] = value
        self._save_json(KEY_ALERTS, merged)
        self._activity("alerts", "Alert settings updated.")
        return self.get_alert_settings()

    def _dispatch_alert(
        self,
        event: str,
        *,
        title: str = "",
        body: str = "",
        level: str = "info",
        fields: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send one alert when the configuration and the rate limit allow it."""

        config = self._alert_config()
        state = self._fleet_state()["alert_sent"]
        now = time.time()
        try:
            payload = build_event(
                event=str(event), title=title, body=body, level=level, fields=fields, now=now
            )
        except ValidationError as exc:
            return {"sent": False, "reason": str(exc)}
        results: list[dict[str, Any]] = []
        for channel, url_key in (("discord", "discord_webhook_url"), ("phone", "phone_webhook_url")):
            url = str(config.get(url_key) or "")
            verdict = should_send(
                enabled=bool(config.get("enabled")),
                url=url,
                event=str(event),
                last_sent_at=state.get(f"{channel}:{event}"),
                now=now,
                min_interval_seconds=int(config.get("min_interval_seconds") or 0),
                allowed_events=config.get("events"),
            )
            if not verdict.get("send"):
                results.append({"channel": channel, "sent": False, "reason": verdict.get("reason", "")})
                continue
            message = (
                discord_payload(payload)
                if channel == "discord"
                else push_payload(payload, topic=str(config.get("phone_topic") or ""))
            )
            try:
                outcome = post_json(url, message)
                state[f"{channel}:{event}"] = now
                results.append({"channel": channel, "sent": True, **outcome})
            except Exception as exc:  # noqa: BLE001 - the network is never a crash
                results.append({"channel": channel, "sent": False, "reason": redact(str(exc))})
        return {
            "sent": any(item.get("sent") for item in results),
            "channels": results,
            "event": payload,
        }

    def send_alert_test(self) -> dict[str, Any]:
        return self._dispatch_alert(
            "test",
            title="Astro test alert",
            body="If you can read this, the webhook works.",
            level="info",
        )

    def get_daily_report(self, send: bool = False) -> dict[str, Any]:
        """Build the daily summary, and push it only when asked."""

        events = []
        try:
            for item in self.repository.list_activity(limit=40):
                events.append({"summary": str(getattr(item, "summary", "")), "kind": str(getattr(item, "kind", ""))})
        except Exception:  # noqa: BLE001
            events = []
        report = daily_report(statistics=self.get_statistics(), events=events, now=time.time())
        if not send:
            return {"report": report, "sent": False}
        outcome = self._dispatch_alert(
            "daily_report",
            title=str(report.get("title") or "Astro daily report"),
            body=str(report.get("body") or ""),
            level=str(report.get("level") or "info"),
            fields=report.get("fields"),
        )
        return {"report": report, **outcome}

    # Macro studio -----------------------------------------------------------

    def _macro(self, macro_id: Any) -> dict[str, Any]:
        try:
            return self.repository.get_macro(str(macro_id))
        except Exception as exc:  # noqa: BLE001
            raise NotFoundError("Macro was not found.") from exc

    def _macro_actions(self, definition: Mapping[str, Any]) -> list[dict[str, Any]]:
        actions = definition.get("actions")
        return list(actions) if isinstance(actions, list) else []

    def _key_profiles(self) -> list[dict[str, Any]]:
        try:
            return validated_key_profiles(self._load_json(KEY_PROFILES, []) or [])
        except ValidationError:
            return []

    def _macro_versions(self) -> dict[str, Any]:
        stored = self._load_json(KEY_VERSIONS, {}) or {}
        return dict(stored) if isinstance(stored, Mapping) else {}

    def _account_variables(self, account_id: str) -> dict[str, str]:
        try:
            metadata = self._get_account(str(account_id)).metadata or {}
        except AppError:
            return {}
        try:
            return validated_variables((metadata.get("macro") or {}).get("variables") or {})
        except ValidationError:
            return {}

    def get_macro_studio(self, macro_id: Any = "", account_id: Any = "") -> dict[str, Any]:
        """Everything the macro studio panel needs for one macro."""

        identifier = str(macro_id or "").strip()
        account = str(account_id or "").strip()
        payload: dict[str, Any] = {
            "macro_id": identifier,
            "account_id": account,
            "profiles": self._key_profiles(),
            "variables": self._account_variables(account) if account else {},
            "versions": [],
            "profile_report": {},
            "steps": [],
        }
        if not identifier:
            return payload
        definition = self._macro(identifier)
        actions = self._macro_actions(definition)
        payload["name"] = definition.get("name")
        payload["versions"] = describe_versions(self._macro_versions().get(str(definition["id"])) or [])
        payload["profile_report"] = profile_macro(actions)
        payload["steps"] = flatten_steps(actions)
        return payload

    def save_key_profile(self, profile: Mapping[str, Any]) -> dict[str, Any]:
        validated = validated_key_profile(self._require_mapping(profile, "Key profile"))
        profiles = [item for item in self._key_profiles() if item["name"] != validated["name"]]
        profiles.append(validated)
        stored = validated_key_profiles(profiles)
        self._save_json(KEY_PROFILES, stored)
        return {"profiles": stored, "saved": validated["name"]}

    def delete_key_profile(self, name: str) -> dict[str, Any]:
        wanted = str(name or "").strip()
        profiles = [item for item in self._key_profiles() if item["name"] != wanted]
        self._save_json(KEY_PROFILES, profiles)
        return {"profiles": profiles, "deleted": wanted}

    def update_macro_variables(self, account_id: str, variables: Any) -> dict[str, Any]:
        account = self._get_account(account_id)
        validated = validated_variables(variables)
        metadata = dict(account.metadata or {})
        macro_meta = dict(metadata.get("macro") or {})
        macro_meta["variables"] = validated
        metadata["macro"] = macro_meta
        self.update_account(account.id, {"metadata": metadata})
        return {"account_id": account.id, "variables": validated}

    def debug_macro(self, macro_id: str, account_id: Any = "") -> dict[str, Any]:
        """Step-by-step listing with the key profile and variables applied."""

        definition = self._macro(macro_id)
        actions = self._macro_actions(definition)
        account = str(account_id or definition.get("account_id") or "").strip()
        variables = self._account_variables(account) if account else {}
        profile_name = str(definition.get("key_profile") or "").strip()
        profile = next((item for item in self._key_profiles() if item["name"] == profile_name), None)
        resolved = apply_profile_and_variables(actions, profile=profile, variables=variables)
        final_actions = resolved.get("actions") or actions
        return {
            "macro_id": definition.get("id"),
            "name": definition.get("name"),
            "account_id": account,
            "variables": variables,
            "profile": profile_name,
            "steps": flatten_steps(final_actions),
            "missing_variables": resolved.get("missing_variables") or [],
            "report": profile_macro(final_actions),
        }

    def snapshot_macro_version(self, macro_id: str, label: str = "") -> dict[str, Any]:
        definition = self._macro(macro_id)
        versions = self._macro_versions()
        history = push_version(
            versions.get(str(definition["id"])) or [],
            macro=definition,
            now=time.time(),
            label=str(label or ""),
        )
        versions[str(definition["id"])] = history
        self._save_json(KEY_VERSIONS, versions)
        return {"macro_id": definition["id"], "versions": describe_versions(history)}

    def rollback_macro(self, macro_id: str, version: Any) -> dict[str, Any]:
        definition = self._macro(macro_id)
        try:
            wanted = int(version)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Select the version to restore.") from exc
        history = self._macro_versions().get(str(definition["id"])) or []
        restored = rollback_version(history, version=wanted)
        # A snapshot only keeps the name, the actions and the DSL source, so the
        # current definition supplies everything else (mode, account, schedule).
        macro = dict(definition)
        macro["name"] = str(restored.get("name") or definition.get("name") or "")
        macro["actions"] = restored.get("actions") or []
        if restored.get("source"):
            macro["source"] = restored.get("source")
        macro["id"] = definition["id"]
        saved = self.save_macro(macro)
        self._activity("macro", f"Macro rolled back to version {wanted}: {saved.get('name')}")
        return {"macro": saved, "version": wanted}

    def start_group_macro(self, group_id: str, macro_id: str) -> dict[str, Any]:
        """Start one macro across a group's running clients.

        This build delivers input to a single Roblox window at a time, so the
        other clients are reported as queued rather than silently skipped.
        """

        group = self._get_group(group_id)
        definition = self._macro(macro_id)
        members = {
            str(account.get("id"))
            for account in self.list_accounts()
            if str(account.get("group_id") or "") == str(group.id)
        }
        started: list[dict[str, Any]] = []
        queued: list[dict[str, Any]] = []
        for instance in self.monitor.current_instances():
            account_id = str(getattr(instance, "account_id", "") or "")
            if account_id not in members:
                continue
            pid = int(getattr(instance, "pid", 0) or 0)
            if started:
                queued.append(
                    {"account_id": account_id, "pid": pid, "reason": "One macro window at a time in this build."}
                )
                continue
            try:
                run = self.start_macro(str(definition["id"]), pid)
                started.append({"account_id": account_id, "pid": pid, "run_id": run.get("run_id")})
            except AppError as exc:
                queued.append({"account_id": account_id, "pid": pid, "reason": str(exc)})
        if not started and not queued:
            raise ConflictError("No verified Roblox client is running for that group.")
        return {
            "group_id": str(group.id),
            "macro_id": str(definition["id"]),
            "started": started,
            "queued": queued,
        }

    # Rules ------------------------------------------------------------------

    def get_rules_overview(self) -> dict[str, Any]:
        """What the rule engine may do, and what it just did."""

        rules = dict(self.get_settings()["categories"].get("rules", {}) or {})
        priorities = []
        for account in self.list_accounts():
            metadata = account.get("metadata") or {}
            try:
                priority = int(metadata.get("priority") or 0)
            except (TypeError, ValueError):
                priority = 0
            priorities.append(
                {
                    "id": account.get("id"),
                    "username": account.get("username"),
                    "group_id": account.get("group_id"),
                    "priority": priority,
                }
            )
        priorities.sort(key=lambda row: (-row["priority"], str(row["username"]).lower()))
        return {
            "rules": rules,
            "groups": self.list_groups(),
            "decisions": self.get_rule_decisions(),
            "priorities": priorities[:200],
            "machine": self._fleet_machine_facts(),
            "resumes": self.get_rejoin_diagnostics(),
            "limits": {
                "never_closes_clients": True,
                "note": "Rules pause, relaunch and warn. Closing a live client always needs a person.",
            },
        }

    def update_rules(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = self._require_mapping(payload, "Rule settings")
        allowed = {
            "enabled",
            "macro_stuck_seconds",
            "max_runtime_hours",
            "cpu_pause_percent",
            "memory_pause_percent",
            "pause_priority_at_or_below",
            "restart_stuck_macros",
            "group_ids",
        }
        updates = {f"rules.{key}": value for key, value in data.items() if key in allowed}
        if not updates:
            raise ValidationError("No rule setting was provided.")
        self.update_settings(updates)
        return self.get_rules_overview()

    # Launch profiles --------------------------------------------------------

    def _launch_profile_rows(self) -> list[dict[str, Any]]:
        return normalize_profiles(self.repository.get_setting(KEY_LAUNCH_PROFILES) or [])

    def list_launch_profiles(self) -> dict[str, Any]:
        """Return every saved launch profile with a one-line summary."""

        profiles = self._launch_profile_rows()
        return {
            "profiles": [{**row, "summary": describe_profile(row)} for row in profiles],
            "count": len(profiles),
            "limit": MAX_LAUNCH_PROFILES,
            "groups": [
                {"id": str(group.get("id") or ""), "name": str(group.get("name") or "")}
                for group in self.list_groups()
            ],
        }

    def save_launch_profile(self, profile: Mapping[str, Any]) -> dict[str, Any]:
        """Create or replace one launch profile."""

        data = self._require_mapping(profile, "Launch profile")
        validated = validated_profile(data, existing_id=str(data.get("id") or ""))
        rows = upsert_profile(self._launch_profile_rows(), validated)
        self.repository.set_setting(KEY_LAUNCH_PROFILES, rows)
        self._activity("launcher", f"Launch profile saved: {validated['name']}")
        return self.list_launch_profiles()

    def delete_launch_profile(self, profile_id: Any) -> dict[str, Any]:
        identifier = str(profile_id or "").strip()
        current = self._launch_profile_rows()
        rows = [row for row in current if str(row.get("id")) != identifier]
        if len(rows) == len(current):
            raise NotFoundError("That launch profile no longer exists.")
        self.repository.set_setting(KEY_LAUNCH_PROFILES, rows)
        self._activity("launcher", "Launch profile deleted")
        return self.list_launch_profiles()

    def launch_with_profile(self, profile_id: Any, account_ids: Any = None) -> dict[str, Any]:
        """Launch accounts through a saved profile.

        This goes through the same wave launcher as any other multi-account
        launch, so the concurrency limit, the delay between launches and the
        pause between waves all still apply.  A profile is a destination, not a
        second launch path.
        """

        identifier = str(profile_id or "").strip()
        profile = next((row for row in self._launch_profile_rows() if str(row.get("id")) == identifier), None)
        if profile is None:
            raise NotFoundError("That launch profile no longer exists.")
        wanted = [str(item) for item in (account_ids or []) if str(item or "").strip()]
        if not wanted and profile.get("group_id"):
            wanted = [
                str(account.get("id"))
                for account in self.list_accounts()
                if str(account.get("group_id") or "") == str(profile.get("group_id"))
            ]
        if not wanted:
            raise ValidationError("Select the accounts to launch, or point this profile at a group.")
        fps = int(profile.get("fps") or 0)
        fps_applied = False
        if fps:
            try:
                fps_applied = bool(self.set_fps_cap(fps))
            except AppError:
                # A missing FPS unlocker must not stop the launch itself.
                fps_applied = False
        status = dict(self.start_wave_launch(wanted, profile_target(profile)))
        status["profile"] = {
            "id": str(profile.get("id")),
            "name": str(profile.get("name")),
            "summary": describe_profile(profile),
        }
        status["fps_applied"] = fps_applied
        status["note"] = (
            "The FPS cap is a global Roblox setting, so it now applies to every client, not only this profile."
            if fps_applied
            else ""
        )
        self._activity("launcher", f"Launch profile started: {profile.get('name')}")
        return status

    # Emergency stop ---------------------------------------------------------

    def emergency_stop(self, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Stop every macro and every queued launch in one gesture.

        Running clients are deliberately left alone: closing a live client stays
        a human decision, exactly like the rules engine.  Automatic rules are
        disarmed by default, otherwise a relaunch rule would quietly undo this
        stop a few seconds later.
        """

        data = dict(payload or {})
        disarm = bool(data.get("disarm_rules", True))
        macros = self.stop_all_macros()
        try:
            queue = dict(self.cancel_batch_launch())
        except AppError:
            queue = {"cancelled": False}
        state = self._fleet_state()
        pending_resumes = len(state["resume"])
        state["resume"].clear()
        rules_disarmed = False
        rules = self.get_settings()["categories"].get("rules", {})
        if disarm and bool(rules.get("enabled")):
            self.update_settings({"rules.enabled": False})
            rules_disarmed = True
        self._activity("macro", "Emergency stop: macros and queued launches halted")
        return {
            "macros_stopped": int(macros.get("count") or 0),
            "queue": queue,
            "resumes_cleared": pending_resumes,
            "rules_disarmed": rules_disarmed,
            "clients_closed": 0,
            "note": (
                "Running clients were left open. Re-arm automatic rules in the Rules tab when you are ready."
            ),
        }

    # Macro resume after a relaunch ------------------------------------------

    def _queue_macro_resume(self, account_id: Any, *, reason: str = "") -> None:
        """Remember that this account was running a macro before its relaunch."""

        identifier = str(account_id or "").strip()
        if not identifier:
            return
        state = self._fleet_state()
        macro_id = state["last_macro"].get(identifier)
        if not macro_id:
            return
        state["resume"][identifier] = {
            "macro_id": macro_id,
            "queued_at": time.time(),
            "attempts": 0,
            "reason": str(reason or "")[:120],
        }

    def _dispatch_macro_resumes(self) -> None:
        """Restart a queued macro once its account has a verified client again."""

        state = self._fleet_state()
        pending = state["resume"]
        if not pending:
            return
        try:
            enabled = bool(
                self.get_settings()["categories"].get("macros", {}).get("resume_after_relaunch", True)
            )
        except Exception:  # noqa: BLE001
            enabled = True
        if not enabled:
            pending.clear()
            return
        now = time.time()
        live = {
            str(getattr(instance, "account_id", "") or ""): instance
            for instance in self.monitor.current_instances()
        }
        for account_id, request in list(pending.items()):
            if now - float(request.get("queued_at") or now) > MAX_RESUME_SECONDS:
                pending.pop(account_id, None)
                self._activity(
                    "macro",
                    "Macro resume gave up: no verified client came back in time.",
                    account_id=account_id,
                )
                continue
            request["attempts"] = int(request.get("attempts") or 0) + 1
            if request["attempts"] > MAX_RESUME_ATTEMPTS:
                pending.pop(account_id, None)
                continue
            instance = live.get(account_id)
            if instance is None:
                continue
            try:
                run = self.start_macro(str(request["macro_id"]), int(getattr(instance, "pid", 0) or 0))
            except AppError as exc:
                # Busy or disabled: try again on a later tick, never lose it.
                self.logger.info("Macro resume deferred for %s: %s", account_id, exc)
                continue
            pending.pop(account_id, None)
            self._activity(
                "macro",
                "Macro resumed after a relaunch.",
                account_id=account_id,
                metadata={"macro_id": request["macro_id"], "run_id": run.get("run_id")},
            )
            self._dispatch_alert(
                "macro_resumed",
                title="Macro resumed",
                body="A relaunched client came back and its macro was restarted.",
                level="success",
            )

    def get_rejoin_diagnostics(self) -> dict[str, Any]:
        """What the watcher will do next for relaunches and macro resumes."""

        state = self._fleet_state()
        return {
            "pending_resumes": [
                {
                    "account_id": account_id,
                    "username": self._fleet_username(account_id),
                    "macro_id": request.get("macro_id"),
                    "attempts": request.get("attempts"),
                    "reason": request.get("reason"),
                }
                for account_id, request in state["resume"].items()
            ],
            "tracked_macros": len(state["last_macro"]),
            "open_sessions": len(state["open"]),
            "max_attempts": MAX_RESUME_ATTEMPTS,
            "max_wait_seconds": MAX_RESUME_SECONDS,
        }
MACRO_CONTROL_TIMEOUT_SECONDS = 90.0
MACRO_CONTROL_POLL_SECONDS = 1.5


class ServiceMacroController:
    """Gives macros the LAUNCH, TELEPORT and RESTART verbs.

    The macro engine knows how to press keys, not how to start Roblox, so the
    control blocks come back through the application and reuse the very same
    launch path as the buttons in the UI: same validation, same launch lock,
    same activity trail.  Every call returns the descriptor of the client the
    run must now follow, or ``None`` when no usable client appeared, so a macro
    never keeps typing into a window that is gone.
    """

    def __init__(self, service: Any) -> None:
        self._service = service

    # Helpers ----------------------------------------------------------------

    def _instance_for(self, account_id: str) -> Any | None:
        newest = None
        for instance in self._service.monitor.current_instances():
            if str(getattr(instance, "account_id", "") or "") != str(account_id):
                continue
            if newest is None or str(getattr(instance, "started_at", "") or "") > str(
                getattr(newest, "started_at", "") or ""
            ):
                newest = instance
        return newest

    @staticmethod
    def _descriptor(instance: Any) -> dict[str, Any] | None:
        pid = int(getattr(instance, "pid", 0) or 0)
        if pid <= 0:
            return None
        created_at: float | None = None
        started_at = getattr(instance, "started_at", None)
        if started_at:
            from datetime import datetime

            try:
                created_at = datetime.fromisoformat(
                    str(started_at).replace("Z", "+00:00")
                ).timestamp()
            except ValueError:
                created_at = None
        return {"pid": pid, "created_at": created_at}

    def _wait_for_client(self, account_id: str, *, ignore_pid: int | None = None) -> dict[str, Any] | None:
        """Wait for a verified client, rescanning instead of guessing."""

        deadline = time.time() + MACRO_CONTROL_TIMEOUT_SECONDS
        while time.time() < deadline:
            instance = self._instance_for(account_id)
            if instance is not None and int(getattr(instance, "pid", 0) or 0) != (ignore_pid or -1):
                return self._descriptor(instance)
            time.sleep(MACRO_CONTROL_POLL_SECONDS)
            try:
                self._service._scan_instances(allow_restarts=False)
            except Exception:  # noqa: BLE001 - a failed scan is retried, never fatal
                continue
        return None

    # Protocol ---------------------------------------------------------------

    def launch(self, account_id: str) -> dict[str, Any] | None:
        existing = self._instance_for(account_id)
        if existing is not None:
            # Already playing: the macro re-pins instead of opening a twin.
            return self._descriptor(existing)
        try:
            result = self._service.launch_account(str(account_id))
        except AppError:
            return None
        if not result.get("accepted"):
            return None
        return self._wait_for_client(str(account_id))

    def teleport(self, account_id: str, place_id: str, job_id: str) -> dict[str, Any] | None:
        target: dict[str, Any] = {"place_id": str(place_id or "")}
        if job_id:
            target["job_id"] = str(job_id)
        try:
            result = self._service.launch_account(str(account_id), target)
        except AppError:
            return None
        if not result.get("accepted"):
            return None
        # Roblox hands the join to the client that is already open, so the pid
        # usually stays the same; the run re-pins either way.
        return self._wait_for_client(str(account_id))

    def restart(self, account_id: str) -> dict[str, Any] | None:
        """Close this account's client, then start it again.

        This is the only place a macro closes a window, and only because a
        RESTART block is something a person wrote on purpose.  The automatic
        rules never do this.
        """

        current = self._instance_for(account_id)
        previous_pid = int(getattr(current, "pid", 0) or 0) if current is not None else None
        if current is not None:
            try:
                self._service.close_instance(previous_pid, confirm=True)
            except AppError:
                return None
            time.sleep(MACRO_CONTROL_POLL_SECONDS)
        try:
            result = self._service.launch_account(str(account_id))
        except AppError:
            return None
        if not result.get("accepted"):
            return None
        return self._wait_for_client(str(account_id), ignore_pid=previous_pid)

    def is_running(self, account_id: str) -> bool:
        return self._instance_for(account_id) is not None
