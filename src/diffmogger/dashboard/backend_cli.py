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
from diffmogger.dashboard.commands import run_control as _run_control
from diffmogger.dashboard.commands.brief import *  # noqa: F401,F403
from diffmogger.dashboard.commands.context import *  # noqa: F401,F403
from diffmogger.dashboard.commands.diagnostics import *  # noqa: F401,F403
from diffmogger.dashboard.commands.project import *  # noqa: F401,F403
from diffmogger.dashboard.commands.run_control import *  # noqa: F401,F403
from diffmogger.dashboard.commands.state import *  # noqa: F401,F403
from diffmogger.dashboard.commands.tickets import *  # noqa: F401,F403
from diffmogger.dashboard.commands.workers import *  # noqa: F401,F403

_RUN_CONTROL_SYNC_NAMES = [
    "load_dashboard_module",
]
_RUN_CONTROL_ORIGINALS = {
    name: getattr(_run_control, name)
    for name in _RUN_CONTROL_SYNC_NAMES
}


def _sync_target_overrides() -> None:
    _target.KIT_ROOT = globals()["KIT_ROOT"]


def _sync_run_control_overrides() -> None:
    _sync_target_overrides()
    for name in _RUN_CONTROL_SYNC_NAMES:
        if name in globals():
            setattr(_run_control, name, globals()[name])


def _restore_run_control_overrides() -> None:
    for name, value in _RUN_CONTROL_ORIGINALS.items():
        setattr(_run_control, name, value)


def load_repo_dotenv_for_backend() -> int:
    _sync_target_overrides()
    return _target.load_repo_dotenv_for_backend()


def automation_status_snapshot(*args, **kwargs):
    try:
        _sync_run_control_overrides()
        return _run_control.automation_status_snapshot(*args, **kwargs)
    finally:
        _restore_run_control_overrides()


def command_automation_start(*args, **kwargs):
    try:
        _sync_run_control_overrides()
        return _run_control.command_automation_start(*args, **kwargs)
    finally:
        _restore_run_control_overrides()


def command_automation_stop(*args, **kwargs):
    try:
        _sync_run_control_overrides()
        return _run_control.command_automation_stop(*args, **kwargs)
    finally:
        _restore_run_control_overrides()


def command_blocker_recheck_baseline(*args, **kwargs):
    try:
        _sync_run_control_overrides()
        return _run_control.command_blocker_recheck_baseline(*args, **kwargs)
    finally:
        _restore_run_control_overrides()


if __name__ == "__main__":
    raise SystemExit(main())
