#!/usr/bin/env python3
"""Launch the standalone Diffmogger dashboard."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import MutableMapping


KIT_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_ROOT = KIT_ROOT / "services" / "agentic-dashboard"
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _strip_inline_comment(value: str) -> str:
    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_double:
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if char == "#" and not in_single and not in_double and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
    return value.rstrip()


def _parse_double_quoted(value: str) -> str:
    result: list[str] = []
    escaped = False
    escapes = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", '"': '"', "$": "$", "`": "`"}
    for char in value:
        if escaped:
            result.append(escapes.get(char, char))
            escaped = False
        elif char == "\\":
            escaped = True
        else:
            result.append(char)
    if escaped:
        result.append("\\")
    return "".join(result)


def _parse_dotenv_value(raw: str) -> str:
    value = _strip_inline_comment(raw.strip())
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1]
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return _parse_double_quoted(value[1:-1])
    return value


def _parse_dotenv_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return values
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export") and len(line) > len("export") and line[len("export")].isspace():
            line = line[len("export") :].lstrip()
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if not ENV_NAME_RE.fullmatch(name):
            continue
        values[name] = _parse_dotenv_value(value)
    return values


def load_dotenv_file(path: Path, env: MutableMapping[str, str] | None = None) -> int:
    if not path.exists() or not path.is_file():
        return 0
    target_env = os.environ if env is None else env
    protected = set(target_env)
    loaded = 0
    for name, value in _parse_dotenv_file(path).items():
        if name in protected:
            continue
        target_env[name] = value
        loaded += 1
    return loaded


def load_repo_dotenv(repo_root: Path = KIT_ROOT, env: MutableMapping[str, str] | None = None) -> int:
    return load_dotenv_file(repo_root / ".env", env)


def main() -> int:
    load_repo_dotenv(KIT_ROOT)
    dashboard_root = str(DASHBOARD_ROOT)
    if dashboard_root not in sys.path:
        sys.path.insert(0, dashboard_root)
    from agentic_dashboard.app import main as dashboard_main  # noqa: PLC0415

    return dashboard_main()


if __name__ == "__main__":
    raise SystemExit(main())
