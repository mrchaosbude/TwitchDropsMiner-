"""Helpers that make the legacy miner modules importable in headless mode."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType
from typing import Tuple


def ensure_legacy_constants(repo_root: Path) -> None:
    """Import the legacy :mod:`constants` module, applying hotfixes if required."""

    if "constants" in sys.modules:
        return

    try:
        importlib.import_module("constants")
    except SyntaxError as exc:
        module = _load_patched_constants(repo_root, exc)
        sys.modules["constants"] = module


def _load_patched_constants(repo_root: Path, error: SyntaxError) -> ModuleType:
    """Load ``constants.py`` after repairing known syntax issues.

    Currently we only patch an issue observed in some distributions where the
    ``DropCampaignDetails`` GraphQL operation is accidentally split across
    multiple lines, leaving an unterminated string literal.
    """

    constants_path = repo_root / "constants.py"
    source = constants_path.read_text(encoding="utf-8")
    patched_source, changed = _repair_drop_campaign_details(source)
    if not changed:
        raise error

    module = ModuleType("constants")
    module.__file__ = str(constants_path)
    code = compile(patched_source, str(constants_path), "exec")
    exec(code, module.__dict__)
    return module


def _repair_drop_campaign_details(source: str) -> Tuple[str, bool]:
    lines = source.splitlines(keepends=True)
    changed = False
    idx = 0
    while idx < len(lines) - 1:
        line = lines[idx]
        if "\"DropCampai" in line and "DropCampaignDetails" not in line:
            next_line = lines[idx + 1]
            if next_line.strip().startswith("gnDetails"):
                indent = line[: len(line) - len(line.lstrip())]
                newline = line[len(line.rstrip("\r\n")) :]
                lines[idx] = f'{indent}"DropCampaignDetails",{newline}'
                lines.pop(idx + 1)
                changed = True
                continue
        idx += 1
    return "".join(lines), changed
