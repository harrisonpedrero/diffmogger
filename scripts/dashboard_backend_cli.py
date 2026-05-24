#!/usr/bin/env python3
"""Compatibility wrapper for diffmogger.dashboard.backend_cli."""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_ROOT = _HERE.parents[1]


def _maybe_reexec_source_venv() -> None:
    if os.environ.get("DIFFMOGGER_BACKEND_REEXECED") or os.environ.get("DIFFMOGGER_BACKEND_NO_VENV_REEXEC"):
        return
    candidate = _ROOT / ".venv" / "bin" / "python"
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        return
    try:
        current = Path(sys.executable).resolve()
        target = candidate.resolve()
    except OSError:
        return
    if current == target:
        return
    env = os.environ.copy()
    env["DIFFMOGGER_BACKEND_REEXECED"] = "1"
    os.execve(str(target), [str(target), *sys.argv], env)


_maybe_reexec_source_venv()

for _candidate in (
    _ROOT / "src",
    _HERE.parents[2] / "src" if len(_HERE.parents) > 2 else None,
    _ROOT / "lib",
):
    if _candidate is not None and _candidate.exists():
        _candidate_text = str(_candidate)
        if _candidate_text not in sys.path:
            sys.path.insert(0, _candidate_text)

if __name__ != "__main__":
    from diffmogger.dashboard.backend_cli import *  # noqa: F401,F403,E402


def _main() -> int:
    runpy.run_module("diffmogger.dashboard.backend_cli", run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
