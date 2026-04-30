#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

required_files=(
  "README.md"
  "LICENSE"
  "CONTRIBUTING.md"
  "DEVELOPMENT.md"
  "AGENTS.md"
  ".gitignore"
  ".github/workflows/validate.yml"
  "docs/CONCEPTS.md"
  "docs/OPERATING_MODEL.md"
  "docs/CODEX_SETUP.md"
  "docs/HUMAN_BRIDGE.md"
  "docs/WORKER_AGENTS.md"
  "docs/SCHEDULES.md"
  "docs/TROUBLESHOOTING.md"
  "docs/EXAMPLES.md"
  "docs/DECISION_RECORDS.md"
  "docs/PRE_RELEASE_CHECKLIST.md"
  "prompts/PROJECT_INTAKE_PROMPT.md"
  "prompts/GENERATE_PROJECT_AUTOMATION_PROMPTS.md"
  "prompts/BOOTSTRAP_NEW_PROJECT.md"
  "prompts/REVIEW_EXISTING_PROJECT.md"
  "prompts/IMPROVE_RUNNING_AUTOMATION.md"
  "prompts/DAILY_REVIEW_PROMPT.md"
  "prompts/HUMAN_BRIDGE_SETUP_PROMPT.md"
  "prompts/WORKER_AGENT_PROMPTS.md"
  "templates/AGENTS.md"
  "templates/.agentic/automation_prompt.md"
  "templates/docs/INITIAL_BOOTSTRAP_PROMPT.md"
  "templates/docs/CODEX_AUTOMATION_TASKS.md"
  "templates/docs/CODEX_AUTOMATION_GUARDRAILS.md"
  "templates/docs/AUTONOMY_EXPERIMENT_LOG.md"
  "templates/docs/DAILY_AUTOMATION_REVIEW.md"
  "templates/docs/HUMAN_REQUESTS.md"
  "templates/docs/HUMAN_INBOX.md"
  "templates/docs/HUMAN_OUTBOX.md"
  "templates/docs/HUMAN_RESPONSES_ARCHIVE.md"
  "templates/docs/HUMAN_BRIDGE_SETUP.md"
  "templates/docs/DEVELOPMENT.md"
  "examples/generic-web-app/project_intake.md"
  "examples/generic-web-app/expected_generated_files.md"
  "examples/trendlab-signal-intelligence/project_intake.md"
  "examples/trendlab-signal-intelligence/expected_generated_files.md"
  "schemas/project_intake.schema.json"
  "schemas/human_request.schema.json"
  "schemas/human_response.schema.json"
  "schemas/automation_task_file.schema.json"
  "scripts/check_required_files.py"
  "scripts/scaffold_project_docs.py"
  "scripts/acquire_codex_lock.sh"
  "scripts/release_codex_lock.sh"
  "scripts/spawn_worker_agent.sh"
  "scripts/summarize_worker_outputs.py"
  "scripts/compact_agent_state.py"
  "services/agentic-notifier/README.md"
  "services/agentic-notifier/.env.example"
  "services/agentic-notifier/requirements.txt"
  "services/agentic-notifier/pyproject.toml"
  "services/agentic-notifier/runtime/.gitkeep"
  "services/agentic-notifier/agentic_notifier/__init__.py"
  "services/agentic-notifier/agentic_notifier/config.py"
  "services/agentic-notifier/agentic_notifier/models.py"
  "services/agentic-notifier/agentic_notifier/formatter.py"
  "services/agentic-notifier/agentic_notifier/parser.py"
  "services/agentic-notifier/agentic_notifier/dedupe.py"
  "services/agentic-notifier/agentic_notifier/target_files.py"
  "services/agentic-notifier/agentic_notifier/twilio_client.py"
  "services/agentic-notifier/agentic_notifier/api_app.py"
  "services/agentic-notifier/agentic_notifier/webhook_app.py"
  "services/agentic-notifier/agentic_notifier/run_service.py"
  "services/agentic-notifier/scripts/send_test_notification.py"
  "services/agentic-notifier/scripts/dry_run_inbound.py"
  "services/agentic-notifier/tests/test_formatter.py"
  "services/agentic-notifier/tests/test_parser.py"
  "services/agentic-notifier/tests/test_dedupe.py"
  "services/agentic-notifier/tests/test_target_files.py"
  "services/agentic-notifier/tests/test_api_notify.py"
  "services/agentic-notifier/tests/test_webhook_inbound.py"
  "services/agentic-notifier/tests/test_twilio_client.py"
  "services/agentic-notifier/tests/test_schema_alignment.py"
)

for file in "${required_files[@]}"; do
  if [[ ! -s "$file" ]]; then
    echo "Missing or empty required file: $file" >&2
    exit 1
  fi
done

python3 - <<'PY'
from pathlib import Path
import json
import sys

for path in sorted(Path("schemas").glob("*.json")):
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Invalid JSON schema {path}: {exc}", file=sys.stderr)
        raise SystemExit(1)

stale_terms = [
    "Signal" + "Forge",
    "signal" + "forge",
    "agentic-kit-" + "lab",
    "/User" + "s/",
    "parent lab work" + "space",
]
stale_hits = []
for path in sorted(Path(".").rglob("*")):
    if not path.is_file():
        continue
    if ".git" in path.parts or ".venv" in path.parts or "__pycache__" in path.parts:
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue
    for term in stale_terms:
        if term in text:
            stale_hits.append((path, term))

if stale_hits:
    for path, term in stale_hits:
        print(f"Stale workspace/product reference in {path}: {term}", file=sys.stderr)
    raise SystemExit(1)

required_phrase = "Treat each run as a substantial engineering sprint."
for path in [
    Path("templates/.agentic/automation_prompt.md"),
    Path("prompts/GENERATE_PROJECT_AUTOMATION_PROMPTS.md"),
]:
    if required_phrase not in path.read_text(encoding="utf-8"):
        print(f"Missing key sprint phrase in {path}", file=sys.stderr)
        raise SystemExit(1)

automation_sections = [
    "## File Reads",
    "## Mission",
    "## Core Operating Principle",
    "## Run Structure",
    "## Sprint Sizing",
    "## Autonomy",
    "## Product Horizons",
    "## Worker-Agent Orchestration",
    "## Human-Intervention Protocol",
    "## Lock-File Behavior",
    "## Verification",
    "## End-Of-Run Requirements",
    "## Self-Improvement Loop",
    "## Status Model",
]
automation = Path("templates/.agentic/automation_prompt.md").read_text(encoding="utf-8")
missing = [section for section in automation_sections if section not in automation]
if missing:
    print(f"Automation prompt template missing sections: {missing}", file=sys.stderr)
    raise SystemExit(1)

task_markers = [
    "AUTOMATION_STATUS: ACTIVE",
    "## Current Project State",
    "## Completed Last Run",
    "## Checks From Last Run",
    "## Worker-Agent Activity",
    "## Known Issues",
    "## Pending Human Requests",
    "## Human Messages Sent",
    "## Best Next Milestone",
    "## Suggested Next Sprint-Sized Task",
    "## Ambitious Ideas Backlog",
    "## Continue/Block/Critical-Stop Rationale",
]
task = Path("templates/docs/CODEX_AUTOMATION_TASKS.md").read_text(encoding="utf-8")
missing = [marker for marker in task_markers if marker not in task]
if missing:
    print(f"Task template missing markers: {missing}", file=sys.stderr)
    raise SystemExit(1)

guardrail_markers = [
    "## Scope Boundaries",
    "## Secrets Policy",
    "## External Side Effects Policy",
    "## Quality Policy",
    "## Worker-Agent Policy",
    "## Lock-File Policy",
    "## Human-Intervention Policy",
    "## Status Policy",
    "## Context-Bloat Policy",
]
guardrails = Path("templates/docs/CODEX_AUTOMATION_GUARDRAILS.md").read_text(encoding="utf-8")
missing = [marker for marker in guardrail_markers if marker not in guardrails]
if missing:
    print(f"Guardrails template missing markers: {missing}", file=sys.stderr)
    raise SystemExit(1)

human_setup = Path("templates/docs/HUMAN_BRIDGE_SETUP.md").read_text(encoding="utf-8")
for marker in ["Style A: Local-File-Only Mode", "Style B: Local Diffmogger Notifier Mode", "POST http://127.0.0.1:8765/api/notify"]:
    if marker not in human_setup:
        print(f"Human bridge setup missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

for path in [
    Path("templates/docs/HUMAN_INBOX.md"),
    Path("templates/docs/HUMAN_OUTBOX.md"),
    Path("templates/docs/HUMAN_REQUESTS.md"),
    Path("templates/docs/HUMAN_RESPONSES_ARCHIVE.md"),
]:
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        print(f"Missing required human bridge template: {path}", file=sys.stderr)
        raise SystemExit(1)

for marker in [
    "POST http://127.0.0.1:8765/api/notify",
    "docs/HUMAN_INBOX.md",
    "remove handled",
    "docs/HUMAN_RESPONSES_ARCHIVE.md",
    "docs/HUMAN_OUTBOX.md",
    "NOTIFIER_UNREACHABLE",
    "scripts/acquire_codex_lock.sh",
    "scripts/release_codex_lock.sh",
    "scripts/spawn_worker_agent.sh",
    "scripts/summarize_worker_outputs.py",
    "Codex CLI worker decision: USE / SKIP / UNAVAILABLE",
    "command -v codex",
    "message_body",
    "send me",
    "text me",
]:
    if marker not in automation:
        print(f"Automation prompt missing notifier/inbox marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

notifier_readme = Path("services/agentic-notifier/README.md").read_text(encoding="utf-8")
for marker in [
    "POST http://127.0.0.1:8765/api/notify",
    "POST http://127.0.0.1:8787/twilio/inbound",
    "DRY_RUN=true",
    "ngrok http 8787",
    "message_body",
    "expects_reply",
    "TWILIO_MESSAGING_SERVICE_SID",
    "A2P 10DLC",
    "30034",
    "PROVIDER_SEND_FAILED",
]:
    if marker not in notifier_readme:
        print(f"Notifier README missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

readme = Path("README.md").read_text(encoding="utf-8")
for marker in [
    "# Diffmogger",
    "A Markdown-first operating system for recurring AI coding agents.",
    "## Who This Is For",
    "## Core Idea",
    "## How This Is Different",
    "## What Is Novel Here",
    "## What Diffmogger Creates",
    "## Quickstart",
    "## Validation",
    "## Worker Agents",
    "## Human Bridge",
    "## Notifier Setup",
    "## Lock Files And State Compaction",
    "## Safety Defaults",
    "## What It Is Not",
    "## Known Limitations",
    "## Roadmap",
    "## Example Validation",
    "## Schemas And Runtime",
    "## License",
    "Markdown-first state",
    "Decoupled human bridge",
    "Marker-enforced contracts",
    "Explicit failure modes",
    "MIT License",
    "https://github.com/harrisonpedrero/diffmogger.git",
    "TWILIO_MESSAGING_SERVICE_SID",
    "A2P 10DLC",
    "scripts/acquire_codex_lock.sh",
    "scripts/spawn_worker_agent.sh",
    "scripts/compact_agent_state.py",
]:
    if marker not in readme:
        print(f"README missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

license_text = Path("LICENSE").read_text(encoding="utf-8")
for marker in ["MIT License", "Copyright (c) 2026", "THE SOFTWARE IS PROVIDED"]:
    if marker not in license_text:
        print(f"LICENSE missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

workflow = Path(".github/workflows/validate.yml").read_text(encoding="utf-8")
for marker in [
    "pull_request:",
    "push:",
    "actions/setup-python",
    "bash scripts/validate_starter_kit.sh",
    "AGENTIC_NOTIFIER_SKIP_DOTENV",
    "python -m pip install -r services/agentic-notifier/requirements.txt",
    "working-directory: services/agentic-notifier",
    "python -m pytest",
]:
    if marker not in workflow:
        print(f"GitHub Actions validation workflow missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)
PY

lock_smoke_dir="$(mktemp -d)"
CODEX_LOCK_PATH="$lock_smoke_dir/target/codex_automation.lock" \
CODEX_RUN_ID="validation-smoke" \
bash scripts/acquire_codex_lock.sh "validation smoke" >/tmp/Diffmogger-lock-acquire.log

if CODEX_LOCK_PATH="$lock_smoke_dir/target/codex_automation.lock" \
  CODEX_RUN_ID="validation-other" \
  bash scripts/acquire_codex_lock.sh "validation overlap" >/tmp/Diffmogger-lock-overlap.log 2>&1; then
    echo "Lock smoke failed: overlapping acquire unexpectedly succeeded" >&2
    rm -rf "$lock_smoke_dir"
    exit 1
fi

CODEX_LOCK_PATH="$lock_smoke_dir/target/codex_automation.lock" \
CODEX_RUN_ID="validation-smoke" \
bash scripts/release_codex_lock.sh >/tmp/Diffmogger-lock-release.log
rm -rf "$lock_smoke_dir"

tmp_dir="$(mktemp -d)"
python3 scripts/scaffold_project_docs.py --intake examples/generic-web-app/project_intake.md --target "$tmp_dir" >/tmp/Diffmogger-scaffold.log
python3 scripts/check_required_files.py "$tmp_dir" >/tmp/Diffmogger-check.log
rm -rf "$tmp_dir"

notifier_python="python3"
if [[ -x "services/agentic-notifier/.venv/bin/python" ]]; then
    notifier_python="services/agentic-notifier/.venv/bin/python"
fi

"$notifier_python" - <<'PY'
import importlib.util
import os
import subprocess
import sys

required = ["fastapi", "twilio", "pytest", "httpx", "uvicorn"]
missing = [name for name in required if importlib.util.find_spec(name) is None]
if missing:
    print(
        "Skipping notifier unit tests; missing dependencies: "
        + ", ".join(missing)
        + ". Run: cd services/agentic-notifier && python -m pip install -r requirements.txt && python -m pytest"
    )
else:
    env = os.environ.copy()
    env["PYTHONPATH"] = "services/agentic-notifier"
    subprocess.run(
        [sys.executable, "-m", "pytest", "services/agentic-notifier/tests"],
        env=env,
        check=True,
    )
PY

echo "OK: starter kit validation passed"
