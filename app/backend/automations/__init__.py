"""Local, bounded desktop automations."""

from .direct_input import (
    PyDirectInputRobloxBackend,
    PyDirectInputUnavailable,
    pydirectinput_available,
)
from .macros import (
    MacroEngine,
    MacroParseError,
    MacroRunNotFound,
    Win32RobloxInputBackend,
    legacy_win32_backend_available,
    parse_macro_dsl,
    validate_macro_actions,
)

__all__ = [
    "MacroEngine",
    "MacroParseError",
    "MacroRunNotFound",
    "PyDirectInputRobloxBackend",
    "PyDirectInputUnavailable",
    # Deprecated prototype, kept importable but disabled unless opted into.
    "Win32RobloxInputBackend",
    "legacy_win32_backend_available",
    "parse_macro_dsl",
    "pydirectinput_available",
    "validate_macro_actions",
]
