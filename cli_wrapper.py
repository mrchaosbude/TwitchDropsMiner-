"""Command line wrapper for Twitch Drops Miner.

This module exposes a minimal command line interface that forwards commands
onto the original GUI application without requiring any modifications to the
upstream project files.  The intention is to keep the wrapper stable even when
updates are pulled into the repository.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence

ROOT_DIR = Path(__file__).resolve().parent
MAIN_SCRIPT = ROOT_DIR / "main.py"


def _ensure_main_script() -> Path:
    """Return the path to ``main.py`` and raise a helpful error if missing."""
    if not MAIN_SCRIPT.exists():
        raise FileNotFoundError(
            "main.py could not be found next to the wrapper. "
            "Ensure you are running the wrapper from the project root."
        )
    return MAIN_SCRIPT


def run_main_script(arguments: Sequence[str]) -> int:
    """Execute the original ``main.py`` script with ``arguments``.

    The call is executed using the current Python interpreter so that the
    runtime environment matches the one used for the wrapper itself.  The
    return code from the subprocess is propagated back to the caller.
    """

    script_path = _ensure_main_script()
    command = [sys.executable, str(script_path), *arguments]
    try:
        completed = subprocess.run(command, check=False, env=os.environ.copy())
    except OSError as exc:  # pragma: no cover - depends on platform specifics
        raise RuntimeError(f"Failed to launch {script_path}: {exc}") from exc
    return completed.returncode


def print_version() -> None:
    """Print the version string defined by the upstream project."""

    from version import __version__  # Imported lazily to avoid side effects.

    print(__version__)


def show_main_path(relative: bool) -> None:
    """Display the path to ``main.py`` for debugging purposes."""

    script_path = _ensure_main_script()
    if relative:
        script_path = script_path.relative_to(ROOT_DIR)
    print(script_path)


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments for the wrapper."""

    parser = argparse.ArgumentParser(
        description=(
            "Command line helper for Twitch Drops Miner. Use the 'run' command "
            "to start the original application and pass any additional "
            "arguments after a '--' separator."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run",
        help="Launch the original Twitch Drops Miner application.",
    )
    run_parser.add_argument(
        "main_args",
        nargs=argparse.REMAINDER,
        help=(
            "Arguments forwarded to main.py. Use '--' before the options to "
            "prevent the wrapper from parsing them."
        ),
    )

    subparsers.add_parser(
        "version",
        help="Print the Twitch Drops Miner version as reported by the project.",
    )

    path_parser = subparsers.add_parser(
        "path",
        help="Show the filesystem location of the wrapped main.py script.",
    )
    path_parser.add_argument(
        "--relative",
        action="store_true",
        help="Show the path relative to the project root.",
    )

    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the command line interface."""

    args = parse_arguments(argv)

    if args.command == "run":
        forwarded = list(args.main_args)
        if forwarded and forwarded[0] == "--":
            forwarded = forwarded[1:]
        return run_main_script(forwarded)
    if args.command == "version":
        print_version()
        return 0
    if args.command == "path":
        show_main_path(args.relative)
        return 0

    raise RuntimeError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
