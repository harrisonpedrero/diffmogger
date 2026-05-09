#!/usr/bin/env python3
"""Compatibility wrapper for diffmogger.runtime.diffmogger_browser."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
for _candidate in (
    _HERE.parents[1] / "src",
    _HERE.parents[2] / "src" if len(_HERE.parents) > 2 else None,
    _HERE.parents[1] / "lib",
):
    if _candidate is not None and _candidate.exists():
        _candidate_text = str(_candidate)
        if _candidate_text not in sys.path:
            sys.path.insert(0, _candidate_text)

if __name__ != "__main__":
    from diffmogger.runtime.diffmogger_browser import *  # noqa: F401,F403,E402


def _main() -> int:
    runpy.run_module("diffmogger.runtime.diffmogger_browser", run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
