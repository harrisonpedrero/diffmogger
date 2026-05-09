#!/usr/bin/env python3
"""Compatibility entrypoint for the Diffmogger role-output integrator."""

from __future__ import annotations

import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from diffmogger.integrator.cli import main
from diffmogger.integrator import *  # noqa: F401,F403
from diffmogger.integrator import commits as _commits
from diffmogger.integrator import git_safety as _git_safety
from diffmogger.integrator import notifier as _notifier


def _sync_compat_overrides() -> None:
    _git_safety.lock_open_process_details = globals()["lock_open_process_details"]
    _notifier.post_notifier = globals()["post_notifier"]


def git(*args, **kwargs):
    _sync_compat_overrides()
    return _git_safety.git(*args, **kwargs)


def notify_commit_progress(*args, **kwargs):
    _sync_compat_overrides()
    return _notifier.notify_commit_progress(*args, **kwargs)


def checkpoint_dirty_main(*args, **kwargs):
    _sync_compat_overrides()
    return _commits.checkpoint_dirty_main(*args, **kwargs)


def commit_current_patch(*args, **kwargs):
    _sync_compat_overrides()
    return _commits.commit_current_patch(*args, **kwargs)


def commit_automation_state(*args, **kwargs):
    _sync_compat_overrides()
    return _commits.commit_automation_state(*args, **kwargs)


if __name__ == "__main__":
    raise SystemExit(main())
