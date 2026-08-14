"""Local, bounded desktop automations."""

from .macros import MacroEngine, MacroParseError, Win32RobloxInputBackend, parse_macro_dsl, validate_macro_actions

__all__ = [
    "MacroEngine",
    "MacroParseError",
    "Win32RobloxInputBackend",
    "parse_macro_dsl",
    "validate_macro_actions",
]
