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
  "docs/DASHBOARD.md"
  "docs/FRESH_PROJECT_SETUP.md"
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
  "templates/.agentic/roles/planner.md"
  "templates/.agentic/roles/builder.md"
  "templates/.agentic/roles/hardener.md"
  "templates/.agentic/roles/integrator.md"
  "templates/docs/INITIAL_BOOTSTRAP_PROMPT.md"
  "templates/docs/PROJECT_CONTEXT.md"
  "templates/docs/CODEX_AUTOMATION_TASKS.md"
  "templates/docs/CODEX_AUTOMATION_GUARDRAILS.md"
  "templates/docs/MULTI_ROLE_PROGRESS.md"
  "templates/docs/AUTOMATION_SIGNALS.md"
  "templates/docs/AUTONOMY_EXPERIMENT_LOG.md"
  "templates/docs/DAILY_AUTOMATION_REVIEW.md"
  "templates/docs/HUMAN_REQUESTS.md"
  "templates/docs/HUMAN_INBOX.md"
  "templates/docs/HUMAN_OUTBOX.md"
  "templates/docs/HUMAN_RESPONSES_ARCHIVE.md"
  "templates/docs/HUMAN_BRIDGE_SETUP.md"
  "templates/docs/DEVELOPMENT.md"
  "templates/scripts/acquire_codex_lock.sh"
  "templates/scripts/release_codex_lock.sh"
  "templates/scripts/run_codex_automation.sh"
  "templates/scripts/run_conveyor_automation.py"
  "templates/scripts/run_conveyor_automation.sh"
  "templates/scripts/update_automation_signals.py"
  "templates/scripts/run_role_automation.sh"
  "templates/scripts/integrate_role_outputs.py"
  "templates/scripts/list_deferred_patches.py"
  "templates/scripts/spawn_worker_agent.sh"
  "templates/scripts/summarize_worker_outputs.py"
  "templates/scripts/compact_agent_state.py"
  "examples/generic-web-app/project_intake.md"
  "examples/generic-web-app/expected_generated_files.md"
  "examples/trendlab-signal-intelligence/project_intake.md"
  "examples/trendlab-signal-intelligence/expected_generated_files.md"
  "schemas/project_intake.schema.json"
  "schemas/automation_signals.schema.json"
  "schemas/human_request.schema.json"
  "schemas/human_response.schema.json"
  "schemas/automation_task_file.schema.json"
  "scripts/check_required_files.py"
  "scripts/scaffold_project_docs.py"
  "scripts/run_dashboard.py"
  "scripts/acquire_codex_lock.sh"
  "scripts/release_codex_lock.sh"
  "scripts/run_conveyor_automation.py"
  "scripts/run_conveyor_automation.sh"
  "scripts/update_automation_signals.py"
  "scripts/run_role_automation.sh"
  "scripts/integrate_role_outputs.py"
  "scripts/list_deferred_patches.py"
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
  "services/agentic-dashboard/README.md"
  "services/agentic-dashboard/agentic_dashboard/__init__.py"
  "services/agentic-dashboard/agentic_dashboard/app.py"
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
import subprocess
import sys

for path in sorted(Path("schemas").glob("*.json")):
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Invalid JSON schema {path}: {exc}", file=sys.stderr)
        raise SystemExit(1)

project_schema = Path("schemas/project_intake.schema.json").read_text(encoding="utf-8")
for marker in [
    "write_worker_agents_allowed",
    "max_write_worker_count",
    "write_worker_guidance",
    "\"maximum\": 10",
    "multi_role_automations_allowed",
    "automation_role_profile",
    "planner_builder_hardener_integrator",
    "automation_checkpoint_commits",
    "multi_role_base_cadence_minutes",
    "automation_schedule_strategy",
    "continuous_conveyor",
    "multi_role_allow_remotes",
    "automation_signals_enabled",
]:
    if marker not in project_schema:
        print(f"Project intake schema missing write-worker marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

stale_terms = [
    "Signal" + "Forge",
    "signal" + "forge",
    "agentic-kit-" + "lab",
    "/User" + "s/",
    "parent lab work" + "space",
]


def skip_stale_reference_scan(path: Path) -> bool:
    runtime_parts = {
        ".git",
        ".pytest_cache",
        ".venv",
        "__pycache__",
        "target",
    }
    if any(part in runtime_parts for part in path.parts):
        return True
    if path == Path(".agentic/dashboard_state.json"):
        return True
    if path.name == ".env" or path.name.startswith(".env."):
        return True
    return False


stale_hits = []
for path in sorted(Path(".").rglob("*")):
    if not path.is_file():
        continue
    if skip_stale_reference_scan(path):
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
    "## Multi-Role Automation",
    "## Automation Signals",
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
    "## Automation Must Never Do",
    "## Product Horizon State",
    "## Horizon Transition Log",
    "## Completed Last Run",
    "## Checks From Last Run",
    "## Worker-Agent Activity",
    "Worker strategy:",
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

context_template = Path("templates/docs/PROJECT_CONTEXT.md").read_text(encoding="utf-8")
for marker in ["# Project Context", "{{ADDITIONAL_CONTEXT_FILES}}", "Do not place secrets"]:
    if marker not in context_template:
        print(f"Project context template missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

guardrail_markers = [
    "## Scope Boundaries",
    "## Automation Must Never Do",
    "## Secrets Policy",
    "## External Side Effects Policy",
    "## Quality Policy",
    "## Worker-Agent Policy",
    "{{WRITE_WORKER_GUARDRAILS_POLICY}}",
    "## Multi-Role Automation Policy",
    "{{MULTI_ROLE_GUARDRAILS_POLICY}}",
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
if "{{HUMAN_BRIDGE_SETUP_CONTENT}}" not in human_setup:
    print("Human bridge setup template missing mode-aware placeholder", file=sys.stderr)
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
    "CODEX_LOCK_ALREADY_ACQUIRED=true",
    "scripts/run_codex_automation.sh",
    "scripts/acquire_codex_lock.sh",
    "scripts/release_codex_lock.sh",
    "scripts/spawn_worker_agent.sh",
    "scripts/summarize_worker_outputs.py",
    "Codex CLI worker decision: USE / SKIP / UNAVAILABLE",
    "Worker strategy: READ_ONLY_REPORTS / WRITE_WORKERS / INTEGRATION_ONLY / NO_WORKERS",
    "Write-capable worker agents allowed:",
    "Max write worker count:",
    "command -v codex",
    "--dangerously-bypass-approvals-and-sandbox",
    "{{HUMAN_PROTOCOL}}",
    "{{WRITE_WORKER_ORCHESTRATION}}",
    "{{MULTI_ROLE_AUTOMATION_SECTION}}",
    "advancement decision: `stay`, `advance`, or `defer`",
    "## Product Horizon State",
    "## Horizon Transition Log",
]:
    if marker not in automation:
        print(f"Automation prompt missing required marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

runner = Path("templates/scripts/run_codex_automation.sh").read_text(encoding="utf-8")
for marker in [
    "CODEX_NESTED_CLI_HOME",
    "$HOME/.codex",
    "--add-dir",
    "codex exec --full-auto",
    "--skip-git-repo-check",
    "update_automation_signals.py",
    "child_pid",
    "forward_signal",
]:
    if marker not in runner:
        print(f"Scheduled runner template missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

conveyor = Path("templates/scripts/run_conveyor_automation.py").read_text(encoding="utf-8")
for marker in [
    "automation_conveyor.lock",
    "automation_conveyor_state.json",
    "queued role patch",
    "run_role_automation.sh",
    "run_codex_automation.sh",
    "MULTI_ROLE_ALLOW_REMOTES",
]:
    if marker not in conveyor:
        print(f"Conveyor runner template missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

signals = Path("templates/scripts/update_automation_signals.py").read_text(encoding="utf-8")
for marker in [
    "docs/AUTOMATION_SIGNALS.md",
    "target/automation_signals.json",
    "--complete",
    "--merge-state",
]:
    if marker not in signals:
        print(f"Automation signals helper template missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

worker_helper = Path("templates/scripts/spawn_worker_agent.sh").read_text(encoding="utf-8")
for marker in [
    "--disable plugins",
    "--ephemeral",
    "--dangerously-bypass-approvals-and-sandbox",
    "--mode",
    "--ownership",
    "-C \"$target_abs\"",
]:
    if marker not in worker_helper:
        print(f"Worker helper template missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

for role in ["planner", "builder", "hardener", "integrator"]:
    role_prompt = Path(f"templates/.agentic/roles/{role}.md").read_text(encoding="utf-8")
    for marker in [
        "NEVER push to a remote",
        "NEVER configure a remote",
        "NEVER set up upstream tracking",
        "CRITICAL_STOP",
        "docs/MULTI_ROLE_PROGRESS.md",
    ]:
        if marker not in role_prompt:
            print(f"Role prompt template {role} missing marker: {marker}", file=sys.stderr)
            raise SystemExit(1)

run_role = Path("templates/scripts/run_role_automation.sh").read_text(encoding="utf-8")
for marker in [
    "--role",
    "planner|builder|hardener|integrator",
    "MULTI_ROLE_ALLOW_REMOTES",
    "git remote -v",
    "git worktree add",
    "git ls-files --others --exclude-standard -z",
    "git add -N",
    "CRITICAL_STOP",
    "update_automation_signals.py",
    "automation_queue",
    "automation_worktrees",
    "manifest.json",
]:
    if marker not in run_role:
        print(f"Role runner template missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

integrator = Path("templates/scripts/integrate_role_outputs.py").read_text(encoding="utf-8")
for marker in [
    "git apply --check",
    "deferral_reason",
    "staleness",
    "verification_failure",
    "MULTI_ROLE_ALLOW_REMOTES",
    "checkpoint pre-existing local changes",
    "git push",
    "worktree",
    "prune",
]:
    if marker not in integrator:
        print(f"Integrator template missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

progress = Path("templates/docs/MULTI_ROLE_PROGRESS.md").read_text(encoding="utf-8")
for marker in [
    "## Project State At Last Integration",
    "## Cumulative Metrics",
    "## Recent Activity Log",
    "## Historical Summary",
    "## Deferred-Patch Backlog",
    "## Architectural Decisions",
    "## Role Health",
]:
    if marker not in progress:
        print(f"Multi-role progress template missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

for path in [
    Path("scripts/run_conveyor_automation.py"),
    Path("templates/scripts/run_conveyor_automation.py"),
    Path("scripts/run_dashboard.py"),
    Path("services/agentic-dashboard/agentic_dashboard/app.py"),
]:
    result = subprocess.run([sys.executable, "-m", "py_compile", str(path)])
    if result.returncode != 0:
        print(f"Dashboard Python compile failed: {path}", file=sys.stderr)
        raise SystemExit(1)

dashboard_app = Path("services/agentic-dashboard/agentic_dashboard/app.py").read_text(encoding="utf-8")
for marker in [
    "DASHBOARD_STATE_FILE",
    "Open Diffmogger Project",
    "write_worker_agents_allowed",
    "max_write_worker_count",
    "multi_role_automations_allowed",
    "automation_schedule_strategy",
    "continuous_conveyor",
    "multi_role_allow_remotes",
    "automation_signals_enabled",
    "planner_builder_hardener_integrator",
    "write_role_launchd_plist",
    "write_conveyor_launchd_plist",
    "run_conveyor_automation.sh",
    "DEFAULT_AUTOMATION_PATH",
    "StartCalendarInterval",
    "run_role_automation.sh",
    "start_new_session=True",
    "MAX_DASHBOARD_LOG_LINES",
    "os.killpg",
]:
    if marker not in dashboard_app:
        print(f"Dashboard app missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

dashboard_readme = Path("services/agentic-dashboard/README.md").read_text(encoding="utf-8")
for marker in [
    "python3 scripts/run_dashboard.py",
    "Scaffold & Bootstrap",
    ".agentic/dashboard_state.json",
    "Open Diffmogger Project",
    "docs/context/",
    "docs/PROJECT_CONTEXT.md",
    "Codex CLI installed and signed in",
]:
    if marker not in dashboard_readme:
        print(f"Dashboard README missing marker: {marker}", file=sys.stderr)
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
    "## Dashboard",
    "## Validation",
    "docs/FRESH_PROJECT_SETUP.md",
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
    "write_worker_agents_allowed",
    "scripts/compact_agent_state.py",
    "scripts/run_dashboard.py",
    "services/agentic-dashboard",
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

python3 scripts/run_dashboard.py --smoke-check >/tmp/Diffmogger-dashboard-smoke.log

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
python3 scripts/check_required_files.py --human-bridge-mode file_only "$tmp_dir" >/tmp/Diffmogger-check.log
if grep -R "POST http://127.0.0.1:8765/api/notify\\|NOTIFIER_UNREACHABLE\\|message_body" "$tmp_dir/.agentic" "$tmp_dir/docs" >/tmp/Diffmogger-file-only-grep.log 2>&1; then
    echo "File-only scaffold unexpectedly contains notifier-only markers" >&2
    cat /tmp/Diffmogger-file-only-grep.log >&2
    rm -rf "$tmp_dir"
    exit 1
fi
rm -rf "$tmp_dir"

tmp_dir="$(mktemp -d)"
tmp_intake="$(mktemp /tmp/Diffmogger-write-workers.XXXXXX)"
cat >"$tmp_intake" <<'JSON'
{
  "project_name": "Write Worker Smoke",
  "product_goal": "Build a write-worker scaffold smoke target.",
  "target_user": "Automation tester.",
  "desired_first_demo": "Generated docs only.",
  "human_bridge_enabled": false,
  "human_bridge_mode": "disabled",
  "worker_agents_allowed": true,
  "write_worker_agents_allowed": true,
  "max_write_worker_count": 25,
  "write_worker_guidance": "Use write workers only for planned disjoint modules.",
  "verification_commands": ["npm test"]
}
JSON
python3 scripts/scaffold_project_docs.py --intake "$tmp_intake" --target "$tmp_dir" >/tmp/Diffmogger-scaffold-write-workers.log
python3 scripts/check_required_files.py --human-bridge-mode disabled --write-workers-enabled "$tmp_dir" >/tmp/Diffmogger-check-write-workers.log
for marker in \
    "Write-capable worker agents allowed: true" \
    "Max write worker count: 10" \
    "Worker strategy: READ_ONLY_REPORTS / WRITE_WORKERS / INTEGRATION_ONLY / NO_WORKERS" \
    "--mode write" \
    "not alone in the codebase" \
    "blindly accepting changes"; do
    if ! grep -R -- "$marker" "$tmp_dir/.agentic" "$tmp_dir/docs" "$tmp_dir/scripts/spawn_worker_agent.sh" >/tmp/Diffmogger-write-worker-grep.log 2>&1; then
        echo "Write-worker scaffold missing marker: $marker" >&2
        rm -rf "$tmp_dir" "$tmp_intake"
        exit 1
    fi
done
rm -rf "$tmp_dir" "$tmp_intake"

tmp_dir="$(mktemp -d)"
tmp_intake="$(mktemp /tmp/Diffmogger-multi-role.XXXXXX)"
cat >"$tmp_intake" <<'JSON'
{
  "project_name": "Multi Role Smoke",
  "product_goal": "Build a multi-role scaffold smoke target.",
  "target_user": "Automation tester.",
  "desired_first_demo": "Generated docs only.",
  "human_bridge_enabled": false,
  "human_bridge_mode": "disabled",
  "multi_role_automations_allowed": true,
  "automation_role_profile": "planner_builder_hardener_integrator",
  "automation_checkpoint_commits": true,
  "multi_role_base_cadence_minutes": 30,
  "automation_signals_enabled": true,
  "verification_commands": ["test -f accepted.txt"]
}
JSON
python3 scripts/scaffold_project_docs.py --intake "$tmp_intake" --target "$tmp_dir" >/tmp/Diffmogger-scaffold-multi-role.log
python3 scripts/check_required_files.py --human-bridge-mode disabled --multi-role-enabled --automation-signals-enabled "$tmp_dir" >/tmp/Diffmogger-check-multi-role.log
python3 "$tmp_dir/scripts/update_automation_signals.py" "$tmp_dir" --refresh --role planner --summary >/tmp/Diffmogger-signals-refresh.log
if ! grep "AUTOMATION_SIGNALS active=" /tmp/Diffmogger-signals-refresh.log >/tmp/Diffmogger-signals-active.log; then
    echo "Automation signals refresh did not print active signal summary" >&2
    cat /tmp/Diffmogger-signals-refresh.log >&2
    rm -rf "$tmp_dir" "$tmp_intake"
    exit 1
fi
python3 "$tmp_dir/scripts/update_automation_signals.py" "$tmp_dir" --complete prompt-self-audit --role planner --note "validation smoke" >/tmp/Diffmogger-signals-complete.log
if ! grep '"last_completed_by": "planner"' "$tmp_dir/target/automation_signals.json" >/tmp/Diffmogger-signals-completed-by.log; then
    echo "Automation signals completion smoke failed" >&2
    cat "$tmp_dir/target/automation_signals.json" >&2
    rm -rf "$tmp_dir" "$tmp_intake"
    exit 1
fi
if find "$tmp_dir/docs" -maxdepth 1 -name 'HUMAN*' | grep . >/tmp/Diffmogger-multi-role-human-files.log; then
    echo "Disabled human bridge multi-role scaffold unexpectedly generated human bridge files" >&2
    cat /tmp/Diffmogger-multi-role-human-files.log >&2
    rm -rf "$tmp_dir" "$tmp_intake"
    exit 1
fi
(
  cd "$tmp_dir"
  git init >/tmp/Diffmogger-multi-role-git-init.log
  git config user.name "Diffmogger Validation"
  git config user.email "diffmogger-validation@example.invalid"
  git add .
  git commit -m "initial smoke target" >/tmp/Diffmogger-multi-role-initial-commit.log
  printf 'tracked base\n' > tracked_role_export.txt
  git add tracked_role_export.txt
  git commit -m "add role export smoke base" >/tmp/Diffmogger-role-export-base-commit.log
)
role_export_base="$(git -C "$tmp_dir" rev-parse HEAD)"
role_export_untracked="$(mktemp /tmp/Diffmogger-role-export-untracked.XXXXXX)"
(
  cd "$tmp_dir"
  printf 'tracked changed\n' > tracked_role_export.txt
  mkdir -p generated
  printf 'new generated file\n' > generated/role_export_new.txt
  git ls-files --others --exclude-standard -z > "$role_export_untracked"
  if [[ -s "$role_export_untracked" ]]; then
    xargs -0 git add -N -- < "$role_export_untracked"
  fi
  git diff --binary "$role_export_base" > role_export.patch
  git diff --name-only "$role_export_base" > role_export.changed
  git reset -q -- tracked_role_export.txt generated/role_export_new.txt >/dev/null
  git checkout -- tracked_role_export.txt
  rm -rf generated
)
rm -f "$role_export_untracked"
if ! grep -q "diff --git a/generated/role_export_new.txt b/generated/role_export_new.txt" "$tmp_dir/role_export.patch"; then
    echo "Role patch export smoke omitted untracked new file from patch" >&2
    rm -rf "$tmp_dir" "$tmp_intake" "$role_export_untracked"
    exit 1
fi
if ! grep -q "new file mode" "$tmp_dir/role_export.patch"; then
    echo "Role patch export smoke did not render new file mode" >&2
    rm -rf "$tmp_dir" "$tmp_intake" "$role_export_untracked"
    exit 1
fi
if ! grep -Fx "generated/role_export_new.txt" "$tmp_dir/role_export.changed" >/tmp/Diffmogger-role-export-new-file.log; then
    echo "Role patch export smoke omitted untracked new file from changed-files list" >&2
    rm -rf "$tmp_dir" "$tmp_intake" "$role_export_untracked"
    exit 1
fi
if ! grep -Fx "tracked_role_export.txt" "$tmp_dir/role_export.changed" >/tmp/Diffmogger-role-export-tracked-file.log; then
    echo "Role patch export smoke omitted tracked file from changed-files list" >&2
    rm -rf "$tmp_dir" "$tmp_intake" "$role_export_untracked"
    exit 1
fi
rm -f "$tmp_dir/role_export.patch" "$tmp_dir/role_export.changed"
(
  cd "$tmp_dir"
  printf 'accepted\n' > accepted.txt
  git add -N accepted.txt
  git diff --binary HEAD > target_patch.diff
  git reset -- accepted.txt >/dev/null
  rm accepted.txt
)
mkdir -p "$tmp_dir/target/automation_queue/builder/run-001"
mv "$tmp_dir/target_patch.diff" "$tmp_dir/target/automation_queue/builder/run-001/changes.patch"
base_commit="$(git -C "$tmp_dir" rev-parse HEAD)"
cat >"$tmp_dir/target/automation_queue/builder/run-001/manifest.json" <<JSON
{
  "role": "builder",
  "run_id": "run-001",
  "base_commit": "$base_commit",
  "head_before_integration": null,
  "status": "queued",
  "deferral_reason": null,
  "deferral_detail": "",
  "patch_path": "target/automation_queue/builder/run-001/changes.patch",
  "changed_files": ["accepted.txt"],
  "checks_run": [],
  "summary": "Create accepted smoke file.",
  "created_at": "2026-05-02T00:00:00+00:00",
  "integrated_at": null,
  "checkpoint_commit": null,
  "accepted_commit": null
}
JSON
python3 scripts/integrate_role_outputs.py "$tmp_dir" --run-id validation-integrator >/tmp/Diffmogger-integrator-smoke.log
if ! git -C "$tmp_dir" log --oneline --all | grep "codex/integrator: accept builder patch run-001" >/tmp/Diffmogger-integrator-log.log; then
    echo "Integrator smoke did not create accepted patch commit" >&2
    cat /tmp/Diffmogger-integrator-smoke.log >&2
    rm -rf "$tmp_dir" "$tmp_intake"
    exit 1
fi
stale_base="$(git -C "$tmp_dir" rev-parse HEAD)"
(
  cd "$tmp_dir"
  printf 'stale patch version\n' > stale.txt
  git add -N stale.txt
  git diff --binary HEAD > stale_patch.diff
  git reset -- stale.txt >/dev/null
  rm stale.txt
  printf 'main version\n' > stale.txt
  git add stale.txt
  git commit -m "advance main for stale patch smoke" >/tmp/Diffmogger-stale-main-commit.log
)
mkdir -p "$tmp_dir/target/automation_queue/builder/run-stale"
mv "$tmp_dir/stale_patch.diff" "$tmp_dir/target/automation_queue/builder/run-stale/changes.patch"
cat >"$tmp_dir/target/automation_queue/builder/run-stale/manifest.json" <<JSON
{
  "role": "builder",
  "run_id": "run-stale",
  "base_commit": "$stale_base",
  "head_before_integration": null,
  "status": "queued",
  "deferral_reason": null,
  "deferral_detail": "",
  "patch_path": "target/automation_queue/builder/run-stale/changes.patch",
  "changed_files": ["stale.txt"],
  "checks_run": [],
  "summary": "Stale patch smoke.",
  "created_at": "2026-05-02T00:01:00+00:00",
  "integrated_at": null,
  "checkpoint_commit": null,
  "accepted_commit": null
}
JSON
python3 scripts/integrate_role_outputs.py "$tmp_dir" --run-id validation-stale >/tmp/Diffmogger-stale-integrator.log
if ! grep '"deferral_reason": "staleness"' "$tmp_dir/target/automation_queue/builder/run-stale/manifest.json" >/tmp/Diffmogger-stale-reason.log; then
    echo "Integrator stale patch smoke did not classify staleness" >&2
    cat "$tmp_dir/target/automation_queue/builder/run-stale/manifest.json" >&2
    rm -rf "$tmp_dir" "$tmp_intake"
    exit 1
fi
python3 scripts/list_deferred_patches.py "$tmp_dir" --pretty >/tmp/Diffmogger-deferred-list.log
CODEX_LOCK_PATH="$tmp_dir/target/codex_automation.lock" \
CODEX_RUN_ID="held-lock" \
bash "$tmp_dir/scripts/acquire_codex_lock.sh" "validation held lock" >/tmp/Diffmogger-integrator-held-lock-acquire.log
if python3 scripts/integrate_role_outputs.py "$tmp_dir" --run-id blocked-by-lock >/tmp/Diffmogger-integrator-lock-refusal.log 2>&1; then
    echo "Integrator lock guard failed: run unexpectedly succeeded while lock was held" >&2
    rm -rf "$tmp_dir" "$tmp_intake"
    exit 1
fi
CODEX_LOCK_PATH="$tmp_dir/target/codex_automation.lock" \
CODEX_RUN_ID="held-lock" \
bash "$tmp_dir/scripts/release_codex_lock.sh" >/tmp/Diffmogger-integrator-held-lock-release.log
real_git="$(command -v git)"
fake_git_dir="$(mktemp -d)"
cat >"$fake_git_dir/git" <<SH
#!/usr/bin/env bash
if [[ "\${1:-}" == "remote" && "\${2:-}" == "-v" ]]; then
  printf 'origin\thttps://example.invalid/repo.git (fetch)\n'
  printf 'origin\thttps://example.invalid/repo.git (push)\n'
  exit 0
fi
exec "$real_git" "\$@"
SH
chmod +x "$fake_git_dir/git"
if PATH="$fake_git_dir:$PATH" python3 scripts/integrate_role_outputs.py "$tmp_dir" --dry-run >/tmp/Diffmogger-remote-guard.log 2>&1; then
    echo "Integrator remote guard failed: run unexpectedly succeeded with remote configured" >&2
    rm -rf "$tmp_dir" "$tmp_intake" "$fake_git_dir"
    exit 1
fi
PATH="$fake_git_dir:$PATH" MULTI_ROLE_ALLOW_REMOTES=1 python3 scripts/integrate_role_outputs.py "$tmp_dir" --dry-run >/tmp/Diffmogger-remote-opt-in.log
cat >"$tmp_dir/.git/hooks/pre-commit" <<'SH'
#!/usr/bin/env sh
git push
SH
chmod +x "$tmp_dir/.git/hooks/pre-commit"
if PATH="$fake_git_dir:$PATH" MULTI_ROLE_ALLOW_REMOTES=1 python3 scripts/integrate_role_outputs.py "$tmp_dir" --dry-run >/tmp/Diffmogger-hook-guard.log 2>&1; then
    echo "Integrator hook guard failed: run unexpectedly succeeded with a push hook" >&2
    rm -rf "$tmp_dir" "$tmp_intake" "$fake_git_dir"
    exit 1
fi
rm -rf "$tmp_dir" "$tmp_intake" "$fake_git_dir"

tmp_dir="$(mktemp -d)"
tmp_intake="$(mktemp /tmp/Diffmogger-local-notifier.XXXXXX)"
cat >"$tmp_intake" <<'JSON'
{
  "project_name": "Notifier Smoke",
  "product_goal": "Build a notifier-mode scaffold smoke target.",
  "target_user": "Automation tester.",
  "desired_first_demo": "Generated docs only.",
  "human_bridge_enabled": true,
  "human_bridge_mode": "local_notifier",
  "verification_commands": ["npm test"]
}
JSON
python3 scripts/scaffold_project_docs.py --intake "$tmp_intake" --target "$tmp_dir" >/tmp/Diffmogger-scaffold-notifier.log
python3 scripts/check_required_files.py --human-bridge-mode local_notifier "$tmp_dir" >/tmp/Diffmogger-check-notifier.log
rm -rf "$tmp_dir" "$tmp_intake"

tmp_dir="$(mktemp -d)"
tmp_intake="$(mktemp /tmp/Diffmogger-disabled.XXXXXX)"
cat >"$tmp_intake" <<'JSON'
{
  "project_name": "Disabled Bridge Smoke",
  "product_goal": "Build a disabled-bridge scaffold smoke target.",
  "target_user": "Automation tester.",
  "desired_first_demo": "Generated docs only.",
  "human_bridge_enabled": false,
  "human_bridge_mode": "disabled",
  "verification_commands": ["npm test"]
}
JSON
python3 scripts/scaffold_project_docs.py --intake "$tmp_intake" --target "$tmp_dir" >/tmp/Diffmogger-scaffold-disabled.log
python3 scripts/check_required_files.py --human-bridge-mode disabled "$tmp_dir" >/tmp/Diffmogger-check-disabled.log
if find "$tmp_dir/docs" -maxdepth 1 -name 'HUMAN*' | grep . >/tmp/Diffmogger-disabled-human-files.log; then
    echo "Disabled human bridge scaffold unexpectedly generated human bridge files" >&2
    cat /tmp/Diffmogger-disabled-human-files.log >&2
    rm -rf "$tmp_dir" "$tmp_intake"
    exit 1
fi
rm -rf "$tmp_dir" "$tmp_intake"

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
