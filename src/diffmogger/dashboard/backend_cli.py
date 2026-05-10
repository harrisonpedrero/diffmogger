#!/usr/bin/env python3
"""Compatibility entrypoint for the Diffmogger native dashboard backend."""

from __future__ import annotations

import sys
from pathlib import Path

from diffmogger.dashboard.cli import main
from diffmogger.dashboard.cli import *  # noqa: F401,F403
from diffmogger.dashboard.errors import *  # noqa: F401,F403
from diffmogger.dashboard.jsonio import *  # noqa: F401,F403
from diffmogger.dashboard.target import *  # noqa: F401,F403
from diffmogger.dashboard import target as _target
from diffmogger.dashboard.commands import run_schedule as _run_schedule
from diffmogger.dashboard.commands.advanced import *  # noqa: F401,F403
from diffmogger.dashboard.commands.brief import *  # noqa: F401,F403
from diffmogger.dashboard.commands.context import *  # noqa: F401,F403
from diffmogger.dashboard.commands.diagnostics import *  # noqa: F401,F403
from diffmogger.dashboard.commands.inbox import *  # noqa: F401,F403
from diffmogger.dashboard.commands.observatory import *  # noqa: F401,F403
from diffmogger.dashboard.commands.project import *  # noqa: F401,F403
from diffmogger.dashboard.commands.review import *  # noqa: F401,F403
from diffmogger.dashboard.commands.run_schedule import *  # noqa: F401,F403
from diffmogger.dashboard.commands.tickets import *  # noqa: F401,F403
from diffmogger.dashboard.commands.workers import *  # noqa: F401,F403

_RUN_SCHEDULE_SYNC_NAMES = [
    "load_dashboard_module",
    "automation_status_snapshot",
    "automation_ready",
    "automation_prerequisites",
    "running_runner_state",
    "process_is_alive",
    "subprocess",
    "os",
    "time",
]
_RUN_SCHEDULE_ORIGINALS = {
    name: getattr(_run_schedule, name)
    for name in _RUN_SCHEDULE_SYNC_NAMES
}


def _sync_target_overrides() -> None:
    _target.KIT_ROOT = globals()["KIT_ROOT"]


def _sync_schedule_overrides() -> None:
    _sync_target_overrides()
    for name in _RUN_SCHEDULE_SYNC_NAMES:
        if name in globals():
            value = globals()[name]
            if (
                name == "automation_status_snapshot"
                and getattr(value, "__module__", "") == __name__
                and getattr(value, "__name__", "") == "automation_status_snapshot"
            ):
                value = _RUN_SCHEDULE_ORIGINALS[name]
            setattr(_run_schedule, name, value)


def _restore_schedule_overrides() -> None:
    for name, value in _RUN_SCHEDULE_ORIGINALS.items():
        setattr(_run_schedule, name, value)


def load_repo_dotenv_for_backend() -> int:
    _sync_target_overrides()
    return _target.load_repo_dotenv_for_backend()


def automation_status_snapshot(*args, **kwargs):
    try:
        _sync_schedule_overrides()
        return _run_schedule.automation_status_snapshot(*args, **kwargs)
    finally:
        _restore_schedule_overrides()


def command_automation_start(*args, **kwargs):
    try:
        _sync_schedule_overrides()
        return _run_schedule.command_automation_start(*args, **kwargs)
    finally:
        _restore_schedule_overrides()


def command_automation_stop(*args, **kwargs):
    try:
        _sync_schedule_overrides()
        return _run_schedule.command_automation_stop(*args, **kwargs)
    finally:
        _restore_schedule_overrides()


if __name__ == "__main__":
    raise SystemExit(main())
