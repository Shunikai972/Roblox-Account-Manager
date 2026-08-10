"""Build the Astro Account Manager desktop application as a Windows executable.

Examples
--------
Inspect the exact PyInstaller invocation without writing build output::

    python scripts\build_windows.py --dry-run

Create the default single-file executable::

    python -m pip install ".[dev]"
    python scripts\build_windows.py

The script deliberately only writes under ``build/`` and ``dist/`` in this
project.  It packages the static frontend alongside ``main.py`` so the frozen
application keeps the same local-only pywebview architecture as development.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import re
import sys
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENTRY_POINT = PROJECT_ROOT / "main.py"
FRONTEND_DIR = PROJECT_ROOT / "app" / "frontend"
DEFAULT_ICON = FRONTEND_DIR / "assets" / "asteria.ico"
DEFAULT_NAME = "AstroAccountManager"
MINIMUM_PYTHON = (3, 12)


class BuildConfigurationError(RuntimeError):
    """A requested build configuration is unsafe or incomplete."""


@dataclass(frozen=True)
class BuildLayout:
    """Resolved output locations, restricted to this checkout."""

    dist_dir: Path
    work_dir: Path
    spec_dir: Path


def _within_project(path: Path, *, allowed_root: Path, label: str) -> Path:
    """Resolve *path* and keep PyInstaller output under its expected root."""

    resolved = path.resolve()
    root = allowed_root.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise BuildConfigurationError(
            f"{label} must stay under {root}; received {resolved}."
        ) from error
    return resolved


def _project_path(value: str) -> Path:
    """Interpret relative CLI paths from the project root, not the caller CWD."""

    candidate = Path(value)
    return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate


def _safe_name(value: str) -> str:
    """Allow a simple executable name only; never let it become a path."""

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", value):
        raise argparse.ArgumentTypeError(
            "--name must contain only letters, digits, '.', '_' or '-' and start with a letter or digit"
        )
    return value


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Package Astro Account Manager for Windows with PyInstaller."
    )
    parser.add_argument(
        "--name",
        default=DEFAULT_NAME,
        type=_safe_name,
        help=f"Executable base name (default: {DEFAULT_NAME}).",
    )
    parser.add_argument(
        "--dist-dir",
        default="dist",
        help="Output directory relative to the project root (default: dist).",
    )
    parser.add_argument(
        "--work-dir",
        default="build/pyinstaller",
        help="PyInstaller work directory relative to the project root.",
    )
    parser.add_argument(
        "--spec-dir",
        default="build/spec",
        help="PyInstaller spec-file directory relative to the project root.",
    )
    parser.add_argument(
        "--icon",
        default=str(DEFAULT_ICON.relative_to(PROJECT_ROOT)),
        help="Optional .ico file, relative to the project root or absolute.",
    )
    parser.add_argument(
        "--onedir",
        action="store_true",
        help="Build a folder instead of the default single executable.",
    )
    parser.add_argument(
        "--console",
        action="store_true",
        help="Keep a console window for diagnostic builds.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable PyInstaller bootloader debug diagnostics.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the validated build plan without importing PyInstaller or writing files.",
    )
    parser.add_argument(
        "--allow-non-windows",
        action="store_true",
        help="Only for CI diagnosis; this cannot create a supported Windows release on another OS.",
    )
    return parser.parse_args(argv)


def _validate_environment(args: argparse.Namespace) -> BuildLayout:
    """Check immutable inputs before PyInstaller is allowed to create output."""

    if sys.version_info < MINIMUM_PYTHON:
        current = ".".join(map(str, sys.version_info[:3]))
        minimum = ".".join(map(str, MINIMUM_PYTHON))
        raise BuildConfigurationError(
            f"Python {minimum}+ is required by this project; found Python {current}."
        )
    if os.name != "nt" and not (args.allow_non_windows or args.dry_run):
        raise BuildConfigurationError(
            "A Windows release must be built on Windows. "
            "Use --dry-run for inspection, or --allow-non-windows only for CI diagnostics."
        )
    if not ENTRY_POINT.is_file():
        raise BuildConfigurationError(f"Missing entry point: {ENTRY_POINT}")
    if not (FRONTEND_DIR / "index.html").is_file():
        raise BuildConfigurationError(
            f"Missing frontend asset: {FRONTEND_DIR / 'index.html'}"
        )

    if args.icon:
        icon = _project_path(args.icon).resolve()
        if not icon.is_file():
            raise BuildConfigurationError(f"The requested icon does not exist: {icon}")
        if icon.suffix.lower() != ".ico":
            raise BuildConfigurationError("Windows packaging expects an .ico file for --icon.")

    return BuildLayout(
        dist_dir=_within_project(
            _project_path(args.dist_dir),
            allowed_root=PROJECT_ROOT / "dist",
            label="Distribution output",
        ),
        work_dir=_within_project(
            _project_path(args.work_dir),
            allowed_root=PROJECT_ROOT / "build",
            label="PyInstaller work output",
        ),
        spec_dir=_within_project(
            _project_path(args.spec_dir),
            allowed_root=PROJECT_ROOT / "build",
            label="PyInstaller spec output",
        ),
    )


def _pyinstaller_arguments(args: argparse.Namespace, layout: BuildLayout) -> list[str]:
    """Return a reproducible PyInstaller argument list.

    ``os.pathsep`` is ``;`` on Windows, which is the separator PyInstaller
    expects for ``--add-data`` on the supported target platform.
    """

    frontend_mapping = f"{FRONTEND_DIR}{os.pathsep}app/frontend"
    command = [
        "--noconfirm",
        "--clean",
        "--name",
        args.name,
        "--distpath",
        str(layout.dist_dir),
        "--workpath",
        str(layout.work_dir),
        "--specpath",
        str(layout.spec_dir),
        "--add-data",
        frontend_mapping,
        # pywebview chooses a GUI backend dynamically. Collect its package so
        # the Edge/WebView2 backend remains available in a frozen executable.
        "--collect-all",
        "webview",
        "--collect-all",
        "websockets",
        "--collect-submodules",
        "app",
        "--onedir" if args.onedir else "--onefile",
        "--console" if args.console else "--windowed",
    ]
    if args.icon:
        command.extend(["--icon", str(_project_path(args.icon).resolve())])
    if args.debug:
        command.extend(["--debug", "all"])
    command.append(str(ENTRY_POINT))
    return command


def _artifact_path(args: argparse.Namespace, layout: BuildLayout) -> Path:
    # This script targets Windows even when a non-Windows CI worker performs a
    # dry run. A real non-Windows build is intentionally rejected by default.
    filename = f"{args.name}.exe"
    return layout.dist_dir / args.name / filename if args.onedir else layout.dist_dir / filename


def _display_command(arguments: Sequence[str]) -> str:
    """Render an informative command line without attempting shell execution."""

    return "python -m PyInstaller " + " ".join(
        f'"{part}"' if any(character.isspace() for character in part) else part
        for part in arguments
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Validate and execute the local Windows packaging workflow."""

    args = parse_args(argv)
    try:
        layout = _validate_environment(args)
    except BuildConfigurationError as error:
        print(f"Build configuration error: {error}", file=sys.stderr)
        return 2

    arguments = _pyinstaller_arguments(args, layout)
    artifact = _artifact_path(args, layout)
    print("Astro Account Manager Windows build plan")
    print(f"  project:  {PROJECT_ROOT}")
    print(f"  frontend: {FRONTEND_DIR}")
    print(f"  artifact: {artifact}")
    print(f"  command:  {_display_command(arguments)}")

    if args.dry_run:
        print("Dry run complete: no PyInstaller import and no files were written.")
        return 0

    try:
        from PyInstaller.__main__ import run as pyinstaller_run
    except ImportError:
        print(
            "PyInstaller is not installed. Run: python -m pip install \".[dev]\"",
            file=sys.stderr,
        )
        return 3

    try:
        result = pyinstaller_run(arguments)
    except SystemExit as error:
        exit_code = error.code if isinstance(error.code, int) else 1
        if exit_code:
            print(f"PyInstaller stopped with exit code {exit_code}.", file=sys.stderr)
        return exit_code
    except Exception as error:  # PyInstaller may surface build-tool exceptions directly.
        print(f"PyInstaller failed: {error}", file=sys.stderr)
        return 1

    if result not in (None, 0):
        print(f"PyInstaller reported a non-zero result: {result}", file=sys.stderr)
        return int(result) if isinstance(result, int) else 1
    if not artifact.is_file():
        print(
            "PyInstaller completed but the expected artifact was not found: "
            f"{artifact}",
            file=sys.stderr,
        )
        return 1

    print(f"Build completed successfully: {artifact}")
    print("Run the release checklist before distributing this executable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
