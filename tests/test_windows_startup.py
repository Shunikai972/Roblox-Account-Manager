from __future__ import annotations

from pathlib import Path

import pytest

from app.backend.core.errors import ValidationError
from app.backend.core.windows_startup import (
    ASTRO_RUN_VALUE_NAME,
    StartupRegistrationError,
    WindowsStartupManager,
)


class _RunStore:
    def __init__(self, values: dict[str, object] | None = None) -> None:
        self.values = dict(values or {})
        self.reads: list[str] = []
        self.writes: list[tuple[str, str]] = []
        self.deletes: list[str] = []

    def get_value(self, name: str) -> object | None:
        self.reads.append(name)
        return self.values.get(name)

    def set_value(self, name: str, value: str) -> None:
        self.writes.append((name, value))
        self.values[name] = value

    def delete_value(self, name: str) -> bool:
        self.deletes.append(name)
        return self.values.pop(name, None) is not None


def _executable(tmp_path: Path, name: str = "AstroAccountManager.exe") -> Path:
    executable = tmp_path / name
    executable.write_bytes(b"MZ")
    return executable


def test_inspect_is_non_mutating_and_enable_writes_only_the_astro_run_value(tmp_path: Path) -> None:
    executable = _executable(tmp_path)
    store = _RunStore({"Other Application": '"C:\\Other.exe"'})
    manager = WindowsStartupManager(executable, store=store, platform_name=lambda: "Windows")

    before = manager.inspect()

    assert before.supported is True
    assert before.accessible is True
    assert before.registered is False
    assert before.enabled is False
    assert store.writes == []

    enabled = manager.enable()

    expected = f'"{executable.resolve()}"'
    assert enabled.enabled is True
    assert enabled.needs_repair is False
    assert store.writes == [(ASTRO_RUN_VALUE_NAME, expected)]
    assert store.values["Other Application"] == '"C:\\Other.exe"'
    assert "Other Application" not in store.deletes


def test_existing_moved_or_malformed_astro_value_is_reported_then_repaired_only_on_enable(tmp_path: Path) -> None:
    executable = _executable(tmp_path)
    store = _RunStore({ASTRO_RUN_VALUE_NAME: '"C:\\Old Location\\Astro.exe"'})
    manager = WindowsStartupManager(executable, store=store, platform_name=lambda: "Windows")

    inspected = manager.inspect()

    assert inspected.registered is True
    assert inspected.enabled is False
    assert inspected.needs_repair is True
    assert store.writes == []

    repaired = manager.enable()
    assert repaired.enabled is True
    assert store.values[ASTRO_RUN_VALUE_NAME] == f'"{executable.resolve()}"'

    store.values[ASTRO_RUN_VALUE_NAME] = 123
    malformed = manager.inspect()
    assert malformed.registered is True
    assert malformed.enabled is False
    assert malformed.needs_repair is True


def test_disable_removes_only_astro_registration_and_is_idempotent(tmp_path: Path) -> None:
    executable = _executable(tmp_path)
    store = _RunStore(
        {
            ASTRO_RUN_VALUE_NAME: f'"{executable.resolve()}"',
            "Other Application": '"C:\\Other.exe"',
        }
    )
    manager = WindowsStartupManager(executable, store=store, platform_name=lambda: "Windows")

    disabled = manager.disable()

    assert disabled.registered is False
    assert disabled.enabled is False
    assert store.deletes == [ASTRO_RUN_VALUE_NAME]
    assert store.values == {"Other Application": '"C:\\Other.exe"'}
    assert manager.disable().enabled is False
    assert store.deletes == [ASTRO_RUN_VALUE_NAME, ASTRO_RUN_VALUE_NAME]


def test_startup_manager_is_read_only_unavailable_off_windows(tmp_path: Path) -> None:
    executable = _executable(tmp_path)
    store = _RunStore()
    manager = WindowsStartupManager(executable, store=store, platform_name=lambda: "Linux")

    status = manager.inspect()

    assert status.supported is False
    assert status.accessible is False
    assert status.reason
    with pytest.raises(StartupRegistrationError, match="available on Windows only"):
        manager.enable()
    with pytest.raises(StartupRegistrationError, match="available on Windows only"):
        manager.disable()
    assert store.writes == []
    assert store.deletes == []


@pytest.mark.parametrize("filename", ("relative.exe", "AstroAccountManager.py"))
def test_startup_manager_requires_a_real_absolute_executable(tmp_path: Path, filename: str) -> None:
    if filename.endswith(".py"):
        candidate = _executable(tmp_path, filename)
    else:
        candidate = Path(filename)

    with pytest.raises(ValidationError):
        WindowsStartupManager(candidate, store=_RunStore(), platform_name=lambda: "Windows")


def test_registry_access_error_is_sanitized_for_inspection_and_actions(tmp_path: Path) -> None:
    executable = _executable(tmp_path)

    class _FailingStore(_RunStore):
        def get_value(self, name: str) -> object | None:
            raise StartupRegistrationError("C:\\private\\registry detail")

        def set_value(self, name: str, value: str) -> None:
            raise StartupRegistrationError("C:\\private\\registry detail")

    manager = WindowsStartupManager(executable, store=_FailingStore(), platform_name=lambda: "Windows")

    inspected = manager.inspect()
    assert inspected.accessible is False
    assert "private" not in (inspected.reason or "")
    with pytest.raises(StartupRegistrationError, match="could not be enabled") as captured:
        manager.enable()
    assert "private" not in str(captured.value)
