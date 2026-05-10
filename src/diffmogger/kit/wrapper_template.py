"""Canonical template for thin Python runtime entrypoint wrappers."""

from __future__ import annotations

import re


MODULE_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")

WRAPPER_TEMPLATE = '''#!/usr/bin/env python3
"""Compatibility wrapper for {module}."""

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
    from {module} import *  # noqa: F401,F403,E402


def _main() -> int:
    runpy.run_module("{module}", run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
'''


def render_wrapper(module: str) -> str:
    """Return the canonical wrapper for a package module entrypoint."""
    if not MODULE_NAME_RE.fullmatch(module):
        raise ValueError(f"invalid module name: {module!r}")
    return WRAPPER_TEMPLATE.format(module=module)
