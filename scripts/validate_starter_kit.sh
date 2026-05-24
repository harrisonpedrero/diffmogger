#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -n "${DIFFMOGGER_PYTHON:-}" ]]; then
  python_bin="$DIFFMOGGER_PYTHON"
elif [[ -x ".venv/bin/python" ]]; then
  python_bin=".venv/bin/python"
else
  python_bin="python3"
fi

export PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}"

"$python_bin" scripts/validate_starter_kit_manifest.py validation/starter_kit_manifest.json

"$python_bin" - <<'PY'
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


for path in sorted(Path("schemas").glob("*.json")):
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"Invalid JSON schema {path}: {exc}")

required_imports = [
    "alembic",
    "apprise",
    "pydantic",
    "temporalio",
    "tree_sitter",
    "tree_sitter_python",
    "tree_sitter_javascript",
]
missing = []
for name in required_imports:
    try:
        __import__(name)
    except ImportError:
        missing.append(name)
if missing:
    fail(
        "Missing Diffmogger dependencies: "
        + ", ".join(missing)
        + ". Run `python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt -r services/agentic-notifier/requirements.txt`."
    )

for stale_path in [
    "src/diffmogger/conveyor",
    "src/diffmogger/runtime/run_process_watchdog.py",
    "src/diffmogger/runtime/run_conveyor_automation.py",
    "services/agentic-notifier/agentic_notifier/discord_bot.py",
    "services/agentic-notifier/agentic_notifier/local_notifications.py",
    "templates/scripts/run_conveyor_automation.sh",
]:
    if Path(stale_path).exists():
        fail(f"Legacy plumbing still present: {stale_path}")

for required in [
    "src/diffmogger/orchestration/workflows.py",
    "src/diffmogger/orchestration/activities.py",
    "src/diffmogger/orchestration/scheduler_policy.py",
    "src/diffmogger/state/migrations/versions/0001_control_plane.py",
    "src/diffmogger/state/migrations/versions/0002_adopt_legacy_control_plane_names.py",
    "src/diffmogger/state/migrations/versions/0003_restore_dashboard_projection_schema.py",
    "src/diffmogger/state/migrations/versions/0004_coexist_legacy_and_typed_tables.py",
    "src/diffmogger/state/migrations/versions/0005_parallel_execution_read_models.py",
    "src/diffmogger/runtime/code_facts.py",
    "src/diffmogger/supervision.py",
    "src/diffmogger/notifications.py",
    "templates/scripts/run_temporal_worker.sh",
]:
    if not Path(required).exists():
        fail(f"New architecture file missing: {required}")

public_scan_paths = [
    Path("README.md"),
    Path("DEVELOPMENT.md"),
    Path("docs"),
    Path("prompts"),
    Path("templates"),
    Path("services/agentic-notifier/README.md"),
]
for root in public_scan_paths:
    paths = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
    for path in paths:
        if "__pycache__" in path.parts or path.suffix in {".png", ".icns", ".ico"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for marker in [
            "Discord",
            "discord_notifier",
            "run_conveyor_automation",
            "run_process_watchdog",
            "automation_conveyor_state",
        ]:
            if marker in text:
                fail(f"Stale architecture marker `{marker}` remains in {path}")

compile_paths = [
    *Path("src/diffmogger").rglob("*.py"),
    *Path("scripts").rglob("*.py"),
    *Path("services/agentic-notifier/agentic_notifier").rglob("*.py"),
]
for path in sorted(set(compile_paths)):
    if "__pycache__" in path.parts:
        continue
    result = subprocess.run([sys.executable, "-m", "py_compile", str(path)])
    if result.returncode != 0:
        fail(f"Python compile failed: {path}")
PY

"$python_bin" -m pytest tests/test_new_architecture.py
(
  cd services/agentic-notifier
  PYTHONPATH=. "../../$python_bin" -m pytest tests
)

tmp_dir="$(mktemp -d)"
"$python_bin" -m diffmogger.orchestration.cli policy-cycle --target "$tmp_dir" --run-id validation-policy >/tmp/Diffmogger-policy-cycle.json
"$python_bin" -m diffmogger.orchestration.cli temporal-cycle --target "$tmp_dir" --run-id validation-temporal --download-dest-dir /tmp/diffmogger-temporal-bin >/tmp/Diffmogger-temporal-cycle.json
rm -rf "$tmp_dir"

tmp_dir="$(mktemp -d)"
"$python_bin" scripts/scaffold_project_docs.py --intake examples/generic-web-app/project_intake.md --target "$tmp_dir" --force >/tmp/Diffmogger-scaffold.log
"$python_bin" scripts/check_required_files.py "$tmp_dir" >/tmp/Diffmogger-check.log
if [[ ! -x "$tmp_dir/.diffmogger/scripts/run_temporal_worker.sh" ]]; then
  echo "Scaffold did not install run_temporal_worker.sh" >&2
  rm -rf "$tmp_dir"
  exit 1
fi
rm -rf "$tmp_dir"

echo "OK: starter kit validation passed"
