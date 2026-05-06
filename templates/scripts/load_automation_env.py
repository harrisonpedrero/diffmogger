#!/usr/bin/env python3
"""Load target-local dotenv files into the automation process environment.

This helper intentionally prints no loaded names or values. It is used by the
generated shell wrappers to re-exec themselves once with target-local env values
available to Codex, conveyor, role worktrees, and child processes.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys
from pathlib import Path
from typing import Iterable


SENTINEL = "CODEX_AUTOMATION_ENV_LOADED"
DEFAULT_ENV_PATTERNS = [
    ".env",
    ".env.development",
    ".env.local",
    ".env.development.local",
    "apps/*/.env",
    "apps/*/.env.development",
    "apps/*/.env.local",
    "apps/*/.env.development.local",
]
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def split_config_list(raw: str) -> list[str]:
    return [part.strip() for part in re.split(r"[:,]", raw) if part.strip()]


def candidate_env_files(target: Path, explicit: str = "") -> list[Path]:
    if explicit.strip():
        specs = split_config_list(explicit)
    else:
        specs = DEFAULT_ENV_PATTERNS

    seen: set[Path] = set()
    files: list[Path] = []
    for spec in specs:
        base = Path(spec).expanduser()
        pattern = base if base.is_absolute() else target / base
        pattern_text = str(pattern)
        if any(char in pattern_text for char in "*?["):
            matches = [Path(item) for item in sorted(glob.glob(pattern_text))]
        else:
            matches = [pattern]
        for match in matches:
            try:
                resolved = match.resolve()
            except OSError:
                resolved = match
            if resolved in seen or not match.exists() or not match.is_file() or match.is_symlink():
                continue
            seen.add(resolved)
            files.append(match)
    return files


def strip_inline_comment(value: str) -> str:
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
        if char == "#" and not in_single and not in_double:
            if index == 0 or value[index - 1].isspace():
                return value[:index].rstrip()
    return value.rstrip()


def parse_double_quoted(value: str) -> str:
    result: list[str] = []
    escaped = False
    for char in value:
        if escaped:
            result.append({"n": "\n", "r": "\r", "t": "\t"}.get(char, char))
            escaped = False
        elif char == "\\":
            escaped = True
        else:
            result.append(char)
    if escaped:
        result.append("\\")
    return "".join(result)


def parse_env_value(raw: str) -> str:
    value = strip_inline_comment(raw.strip())
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1]
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return parse_double_quoted(value[1:-1])
    return value


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return values
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if not ENV_NAME_RE.fullmatch(name):
            continue
        values[name] = parse_env_value(value)
    return values


def apply_env_files(env: dict[str, str], files: Iterable[Path]) -> dict[str, str]:
    protected = set(env)
    result = dict(env)
    for path in files:
        for name, value in parse_env_file(path).items():
            if name in protected:
                continue
            result[name] = value
    return result


def apply_denylist(env: dict[str, str], raw: str) -> dict[str, str]:
    result = dict(env)
    for name in split_config_list(raw):
        if ENV_NAME_RE.fullmatch(name):
            result.pop(name, None)
    return result


def build_environment(target: Path, base_env: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base_env if base_env is not None else os.environ)
    files = candidate_env_files(target, env.get("CODEX_AUTOMATION_ENV_FILES", ""))
    env = apply_env_files(env, files)
    env = apply_denylist(env, env.get("CODEX_AUTOMATION_ENV_DENYLIST", ""))
    env[SENTINEL] = "1"
    return env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load target dotenv files and exec a command without printing secrets.")
    parser.add_argument("--target", default=os.environ.get("TARGET", "."))
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print("load_automation_env.py requires a command after --", file=sys.stderr)
        return 2

    target = Path(args.target).expanduser().resolve()
    env = build_environment(target)
    try:
        os.execvpe(command[0], command, env)
    except OSError as exc:
        print(f"failed to exec requested command: {exc}", file=sys.stderr)
        return 126


if __name__ == "__main__":
    raise SystemExit(main())
