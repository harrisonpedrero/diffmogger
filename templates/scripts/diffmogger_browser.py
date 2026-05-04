#!/usr/bin/env python3
"""Manage Diffmogger's local browser runtime.

The helper keeps browser-dependent automation away from ambient system Chrome
when a managed headless browser is available. It intentionally uses only the
standard library; installation is explicit and delegated to `npx`.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ENV_BROWSER_KEYS = ("DIFFMOGGER_BROWSER_PATH", "CHROME_PATH")
DEFAULT_BROWSER_PACKAGE = "chrome-headless-shell@stable"
INSTALL_PACKAGE = "@puppeteer/browsers"
DEVTOOLS_MARKER = "DevTools listening on "
SYSTEM_CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    "google-chrome",
    "chromium",
    "chromium-browser",
    "chrome",
]
MANAGED_BROWSER_NAMES = {
    "chrome-headless-shell",
    "chrome",
    "Google Chrome for Testing",
    "Chromium",
}


@dataclass(frozen=True)
class Candidate:
    source: str
    requested: str
    path: str | None
    exists: bool
    executable: bool


def default_cache_dir() -> Path:
    configured = os.environ.get("DIFFMOGGER_BROWSER_CACHE", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".cache" / "diffmogger" / "browsers"


def resolve_path(value: str) -> str | None:
    if not value:
        return None
    expanded = Path(value).expanduser()
    if expanded.is_absolute() or os.sep in value or (os.altsep and os.altsep in value):
        return str(expanded) if expanded.exists() else None
    resolved = shutil.which(value)
    return resolved


def executable(path: str | None) -> bool:
    return bool(path and Path(path).is_file() and os.access(path, os.X_OK))


def candidate_for(source: str, requested: str) -> Candidate:
    path = resolve_path(requested)
    exists = bool(path and Path(path).exists())
    return Candidate(source=source, requested=requested, path=path, exists=exists, executable=executable(path))


def managed_candidates(cache_dir: Path) -> list[Candidate]:
    if not cache_dir.exists():
        return []
    found: list[Candidate] = []
    for path in cache_dir.rglob("*"):
        if not path.is_file() or path.name not in MANAGED_BROWSER_NAMES:
            continue
        if "Crashpad" in path.parts:
            continue
        found.append(
            Candidate(
                source="managed",
                requested=str(path),
                path=str(path),
                exists=True,
                executable=os.access(path, os.X_OK),
            )
        )
    found.sort(key=lambda item: (Path(item.path or item.requested).stat().st_mtime if item.path else 0), reverse=True)
    return found


def collect_candidates(*, include_system: bool, prefer_system: bool) -> list[Candidate]:
    cache_dir = default_cache_dir()
    env_items = [
        candidate_for(key, os.environ.get(key, "").strip())
        for key in ENV_BROWSER_KEYS
        if os.environ.get(key, "").strip()
    ]
    managed_items = managed_candidates(cache_dir)
    system_items = [candidate_for("system", item) for item in SYSTEM_CHROME_CANDIDATES] if include_system else []
    if prefer_system:
        return env_items + system_items + managed_items
    return env_items + managed_items + system_items


def resolve_browser(*, include_system: bool, prefer_system: bool) -> tuple[Candidate | None, list[Candidate]]:
    candidates = collect_candidates(include_system=include_system, prefer_system=prefer_system)
    for candidate in candidates:
        if candidate.executable:
            return candidate, candidates
    return None, candidates


def base_launch_args(profile_dir: Path, extra_args: list[str]) -> list[str]:
    return [
        "--headless=new",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--no-first-run",
        "--no-default-browser-check",
        "--enable-logging=stderr",
        "--remote-debugging-port=0",
        f"--user-data-dir={profile_dir}",
        *extra_args,
        "about:blank",
    ]


def pump(stream: Any, lines: list[str]) -> None:
    try:
        for line in iter(stream.readline, ""):
            if not line:
                break
            lines.append(line)
    finally:
        try:
            stream.close()
        except Exception:
            pass


def launch_doctor(browser_path: str, timeout_seconds: float, extra_args: list[str]) -> dict[str, Any]:
    profile_dir = Path(tempfile.mkdtemp(prefix="diffmogger-browser-profile-"))
    args = [browser_path, *base_launch_args(profile_dir, extra_args)]
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    started_at = time.time()
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    threads = [
        threading.Thread(target=pump, args=(process.stdout, stdout_lines), daemon=True),
        threading.Thread(target=pump, args=(process.stderr, stderr_lines), daemon=True),
    ]
    for thread in threads:
        thread.start()

    status = "failed_timeout"
    browser_ws_url = ""
    exit_code: int | None = None
    signal: str | None = None
    try:
        while time.time() - started_at < timeout_seconds:
            combined = "".join(stdout_lines + stderr_lines)
            marker_index = combined.find(DEVTOOLS_MARKER)
            if marker_index != -1:
                browser_ws_url = combined[marker_index + len(DEVTOOLS_MARKER) :].split()[0]
                status = "ok"
                break
            exit_code = process.poll()
            if exit_code is not None:
                status = "failed_early_exit"
                if exit_code < 0:
                    signal = f"SIG{-exit_code}"
                break
            time.sleep(0.1)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        shutil.rmtree(profile_dir, ignore_errors=True)

    return {
        "status": status,
        "browserPath": browser_path,
        "browserWsUrl": browser_ws_url or None,
        "exitCode": exit_code,
        "signal": signal,
        "elapsedSeconds": round(time.time() - started_at, 3),
        "launchArgs": args[1:],
        "chromeStdout": "".join(stdout_lines),
        "chromeStderr": "".join(stderr_lines),
    }


def result_payload(candidate: Candidate | None, candidates: list[Candidate], *, include_launch: bool = False) -> dict[str, Any]:
    return {
        "ok": bool(candidate and candidate.executable),
        "cacheDir": str(default_cache_dir()),
        "browserPath": candidate.path if candidate else None,
        "source": candidate.source if candidate else None,
        "candidates": [candidate.__dict__ for candidate in candidates],
        "launch": None if not include_launch else {},
    }


def print_human(payload: dict[str, Any]) -> None:
    if payload.get("ok"):
        print(f"browser: {payload.get('browserPath')} ({payload.get('source')})")
    else:
        print("browser: unavailable")
    launch = payload.get("launch")
    if launch:
        print(f"launch: {launch.get('status')}")
        if launch.get("browserWsUrl"):
            print(f"devtools: {launch.get('browserWsUrl')}")
        if launch.get("signal"):
            print(f"signal: {launch.get('signal')}")
    print(f"cache: {payload.get('cacheDir')}")


def command_resolve(args: argparse.Namespace) -> int:
    candidate, candidates = resolve_browser(include_system=not args.managed_only, prefer_system=args.prefer_system)
    payload = result_payload(candidate, candidates)
    if args.json:
        print(json.dumps(payload, indent=2))
    elif candidate:
        print(candidate.path)
    else:
        print("No compatible browser found.", file=sys.stderr)
    return 0 if candidate else 1


def command_env(args: argparse.Namespace) -> int:
    candidate, _ = resolve_browser(include_system=args.allow_system, prefer_system=False)
    if not candidate or not candidate.path:
        return 1
    values = {
        "DIFFMOGGER_BROWSER_PATH": candidate.path,
        "CHROME_PATH": candidate.path,
        "DIFFMOGGER_BROWSER_CACHE": str(default_cache_dir()),
    }
    for key, value in values.items():
        print(f"export {key}={shlex.quote(value)}")
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    candidate, candidates = resolve_browser(include_system=not args.managed_only, prefer_system=args.prefer_system)
    payload = result_payload(candidate, candidates, include_launch=args.launch)
    if candidate and args.launch:
        extra_args = shlex.split(os.environ.get("CHROME_EXTRA_ARGS", ""))
        extra_args.extend(args.extra_arg or [])
        payload["launch"] = launch_doctor(candidate.path or "", args.timeout, extra_args)
        payload["ok"] = payload["launch"].get("status") == "ok"
    if args.diagnostics:
        diagnostics_path = Path(args.diagnostics)
        diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
        diagnostics_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print_human(payload)
    return 0 if payload.get("ok") else 1


def command_install(args: argparse.Namespace) -> int:
    npx = shutil.which("npx")
    if not npx:
        print("npx is required to install the managed browser runtime.", file=sys.stderr)
        return 1
    cache_dir = Path(args.path).expanduser() if args.path else default_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    command = [
        npx,
        "--yes",
        INSTALL_PACKAGE,
        "install",
        args.browser,
        "--path",
        str(cache_dir),
    ]
    if args.print_command:
        print(shlex.join(command))
        return 0
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        return result.returncode
    candidate, candidates = resolve_browser(include_system=False, prefer_system=False)
    payload = result_payload(candidate, candidates)
    if args.json:
        print(json.dumps(payload, indent=2))
    elif candidate:
        print(f"Installed managed browser: {candidate.path}")
        print("To export it in the current shell:")
        print(f"export DIFFMOGGER_BROWSER_PATH={shlex.quote(candidate.path or '')}")
        print(f"export CHROME_PATH={shlex.quote(candidate.path or '')}")
    else:
        print("Install finished, but no managed browser executable was found.", file=sys.stderr)
    return 0 if candidate else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    resolve = subparsers.add_parser("resolve", help="Print the selected browser path.")
    resolve.add_argument("--json", action="store_true")
    resolve.add_argument("--managed-only", action="store_true")
    resolve.add_argument("--prefer-system", action="store_true")
    resolve.set_defaults(func=command_resolve)

    env = subparsers.add_parser("env", help="Print shell exports for the selected managed/env browser.")
    env.add_argument("--allow-system", action="store_true", help="Allow system Chrome fallback in exported env.")
    env.set_defaults(func=command_env)

    doctor = subparsers.add_parser("doctor", help="Check browser resolution and optional DevTools launch.")
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("--launch", action="store_true", help="Launch the browser and wait for DevTools.")
    doctor.add_argument("--managed-only", action="store_true")
    doctor.add_argument("--prefer-system", action="store_true")
    doctor.add_argument("--timeout", type=float, default=10.0)
    doctor.add_argument("--extra-arg", action="append")
    doctor.add_argument("--diagnostics")
    doctor.set_defaults(func=command_doctor)

    install = subparsers.add_parser("install", help="Install a managed browser through npx @puppeteer/browsers.")
    install.add_argument("--browser", default=DEFAULT_BROWSER_PACKAGE)
    install.add_argument("--path")
    install.add_argument("--json", action="store_true")
    install.add_argument("--print-command", action="store_true")
    install.set_defaults(func=command_install)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
