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
  "templates/scripts/run_observatory.py"
  "templates/scripts/build_replay.py"
  "templates/scripts/diffmogger_browser.py"
  "templates/scripts/ticket_run.py"
  "templates/scripts/repair_environment.py"
  "templates/scripts/update_automation_signals.py"
  "templates/scripts/run_role_automation.sh"
  "templates/scripts/integrate_role_outputs.py"
  "templates/scripts/list_deferred_patches.py"
  "templates/scripts/spawn_worker_agent.sh"
  "templates/scripts/summarize_worker_outputs.py"
  "templates/scripts/compact_agent_state.py"
  "tests/test_run_observatory.py"
  "tests/test_run_conveyor_automation.py"
  "tests/test_repair_environment.py"
  "tests/test_integrate_role_outputs.py"
  "tests/test_list_deferred_patches.py"
  "tests/test_ticket_run.py"
  "tests/test_check_integration_safety.py"
  "tests/test_check_required_files.py"
  "tests/test_summarize_worker_outputs.py"
  "examples/generic-web-app/project_intake.md"
  "examples/generic-web-app/expected_generated_files.md"
  "examples/trendlab-signal-intelligence/project_intake.md"
  "examples/trendlab-signal-intelligence/expected_generated_files.md"
  "examples/ticket-campaign/project_intake.md"
  "examples/ticket-campaign/expected_generated_files.md"
  "schemas/project_intake.schema.json"
  "schemas/automation_signals.schema.json"
  "schemas/human_request.schema.json"
  "schemas/human_response.schema.json"
  "schemas/automation_task_file.schema.json"
  "scripts/check_required_files.py"
  "scripts/check_integration_safety.py"
  "scripts/scaffold_project_docs.py"
  "scripts/run_dashboard.py"
  "scripts/acquire_codex_lock.sh"
  "scripts/release_codex_lock.sh"
  "scripts/run_conveyor_automation.py"
  "scripts/run_conveyor_automation.sh"
  "scripts/run_observatory.py"
  "scripts/build_replay.py"
  "scripts/diffmogger_browser.py"
  "scripts/ticket_run.py"
  "scripts/repair_environment.py"
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
  "services/agentic-notifier/agentic_notifier/dedupe.py"
  "services/agentic-notifier/agentic_notifier/target_files.py"
  "services/agentic-notifier/agentic_notifier/discord_bot.py"
  "services/agentic-notifier/agentic_notifier/local_notifications.py"
  "services/agentic-notifier/agentic_notifier/api_app.py"
  "services/agentic-notifier/agentic_notifier/run_service.py"
  "services/agentic-notifier/scripts/send_test_notification.py"
  "services/agentic-notifier/scripts/dry_run_inbound.py"
  "services/agentic-notifier/tests/test_formatter.py"
  "services/agentic-notifier/tests/test_dedupe.py"
  "services/agentic-notifier/tests/test_target_files.py"
  "services/agentic-notifier/tests/test_api_notify.py"
  "services/agentic-notifier/tests/test_discord_bot.py"
  "services/agentic-notifier/tests/test_local_notifications.py"
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
    "automation_run_mode",
    "ticket_campaign",
    "ticket_run_file",
    "ticket_completion_notify",
    "discord_notifier",
    "local_notifications_enabled",
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


def git_ignored(path: Path) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--", path.as_posix()],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


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
    if path.parts and path.parts[0] == ".agentic":
        return True
    if git_ignored(path):
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
    "Parallelism budget:",
    "## Known Issues",
    "## Pending Human Requests",
    "## Human Messages Sent",
    "## Best Next Milestone",
    "## Suggested Next Sprint-Sized Task",
    "{{BACKLOG_SECTION_HEADING}}",
    "{{BACKLOG_SECTION_BODY}}",
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
    "parallelism budget",
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
    "Parallelism budget:",
    "Write-capable worker agents allowed:",
    "Max write worker count:",
    "command -v codex",
    "--dangerously-bypass-approvals-and-sandbox",
    "{{HUMAN_PROTOCOL}}",
    "{{WRITE_WORKER_ORCHESTRATION}}",
    "{{MULTI_ROLE_AUTOMATION_SECTION}}",
    "{{TICKET_CAMPAIGN_SECTION}}",
    "{{PRODUCT_HORIZON_GUIDANCE}}",
    "## Product Horizon State",
    "## Horizon Transition Log",
]:
    if marker not in automation:
        print(f"Automation prompt missing required marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

runner = Path("templates/scripts/run_codex_automation.sh").read_text(encoding="utf-8")
for marker in [
    "CODEX_NESTED_CLI_HOME",
    "CODEX_LOCK_CONTEXT",
    "$HOME/.codex",
    "diffmogger_browser.py",
    "DIFFMOGGER_BROWSER_PATH",
    "--add-dir",
    "codex exec --full-auto",
    "--skip-git-repo-check",
    "update_automation_signals.py",
    "repair_environment.py",
    "ticket_run.py",
    "child_pid",
    "forward_signal",
]:
    if marker not in runner:
        print(f"Scheduled runner template missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)
if "Diffmogger Self Improvement scheduled sprint" in runner:
    print("Scheduled runner template contains self-run lock context", file=sys.stderr)
    raise SystemExit(1)

browser_helper = Path("templates/scripts/diffmogger_browser.py").read_text(encoding="utf-8")
for marker in [
    "chrome-headless-shell@stable",
    "@puppeteer/browsers",
    "DIFFMOGGER_BROWSER_PATH",
    "CHROME_PATH",
    "DIFFMOGGER_BROWSER_CACHE",
    "DevTools listening on",
]:
    if marker not in browser_helper:
        print(f"Browser helper template missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

ticket_helper = Path("templates/scripts/ticket_run.py").read_text(encoding="utf-8")
for marker in [
    "json ticket-run",
    "should-halt",
    "target/ticket_run_completion.json",
    "target/ticket_run_reports",
    "api/notify",
    "event_kind",
    "local_notify",
    "NOTIFIER_UNREACHABLE",
]:
    if marker not in ticket_helper:
        print(f"Ticket run helper template missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

conveyor = Path("templates/scripts/run_conveyor_automation.py").read_text(encoding="utf-8")
for marker in [
    "automation_conveyor.lock",
    "automation_conveyor_state.json",
    "queued role patch",
    "run_role_automation.sh",
    "run_codex_automation.sh",
	    "MULTI_ROLE_ALLOW_REMOTES",
	    "active_role_run",
    "decision_queue",
    "accepted_by_role",
    "deferred_delta_by_role",
    "planner deferred patch resolved",
    "ticket campaign complete",
    "ticket campaign blocked",
    "builder-first policy",
]:
    if marker not in conveyor:
        print(f"Conveyor runner template missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

observatory = Path("templates/scripts/run_observatory.py").read_text(encoding="utf-8")
for marker in [
    "Diffmogger Observatory",
    "automation_conveyor_state.json",
	    "automation_signals.json",
	    "automation_queue",
	    "ThreadingHTTPServer",
	    "--open",
	    "--review-output",
	    "--review-dir",
	    "Self Review",
	    "First Review Readiness",
	    "Scorecard",
	    "Action Plan",
	    "Integration Safety",
	    "Deferred Patch Triage",
	    "Next-Run Worker Strategy",
	    "worker_strategy_snapshot",
	    "no_progress_circuit",
	    "Active Signals",
	    "Conveyor Health",
	    "Recent Outcomes",
	]:
	    if marker not in observatory:
	        print(f"Observatory template missing marker: {marker}", file=sys.stderr)
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
    markers = [
        "NEVER push to a remote",
        "NEVER configure a remote",
        "NEVER set up upstream tracking",
        "CRITICAL_STOP",
        "docs/MULTI_ROLE_PROGRESS.md",
    ]
    if role != "integrator":
        markers.extend(["Commit subject:", "Do not use generic subjects"])
    for marker in markers:
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
    "repair_environment.py",
    "automation_queue",
    "automation_worktrees",
    "manifest.json",
    "runtime_state_actions.json",
    "runtime_state_changed_files",
    "runtime_state_status",
    "runtime_state_paths.txt",
    "allowed_runtime_path",
    ".agentic/automation_prompt.md",
    ".agentic/roles/builder.md",
    "Runtime Summary Contract",
    "Commit subject:",
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
    "semantic_commit_message",
    "chore(integrator): checkpoint preexisting local changes",
    "repair_environment.py",
    "git push",
    "worktree",
    "prune",
    "RUNTIME_STATE_WHITELIST",
    "apply_runtime_state_actions",
    "runtime_state_results",
    "RUNTIME_STATE_ALLOWED_PREFIXES",
    "RUNTIME_STATE_DENY_PARTS",
    ".agentic/automation_prompt.md",
    ".agentic/roles/builder.md",
    "parse_commit_intent",
    "semantic_changed_files",
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
    "fast-follow replanning",
]:
    if marker not in progress:
        print(f"Multi-role progress template missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

for path in [
    Path("scripts/run_conveyor_automation.py"),
    Path("templates/scripts/run_conveyor_automation.py"),
    Path("scripts/run_observatory.py"),
    Path("templates/scripts/run_observatory.py"),
    Path("scripts/diffmogger_browser.py"),
    Path("templates/scripts/diffmogger_browser.py"),
    Path("scripts/ticket_run.py"),
    Path("templates/scripts/ticket_run.py"),
    Path("scripts/repair_environment.py"),
    Path("templates/scripts/repair_environment.py"),
    Path("scripts/integrate_role_outputs.py"),
    Path("templates/scripts/integrate_role_outputs.py"),
    Path("scripts/summarize_worker_outputs.py"),
    Path("templates/scripts/summarize_worker_outputs.py"),
    Path("scripts/run_dashboard.py"),
    Path("scripts/check_integration_safety.py"),
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
    "OBSERVATORY_SCRIPT",
    "INTEGRATION_SAFETY_SCRIPT",
    "Launch Observatory",
    "Export Review Bundle",
    "Run Safety Check",
    "Worker Strategy Controls",
    "Run Read-Only Worker",
    "Run Write Worker",
    "Run Integrator",
    "dashboard_worker_strategy",
    "read_only_worker_command",
    "write_worker_command",
    "integration_only_command",
    "check_integration_safety.py",
    "run_observatory.py",
    "spawn_worker_agent.sh",
    "run_conveyor_automation.sh",
    "DEFAULT_AUTOMATION_PATH",
    "DIFFMOGGER_BROWSER_PATH",
    "DIFFMOGGER_BROWSER_CACHE",
    "automation_environment",
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
    "Export Review Bundle",
    "Run Safety Check",
    "Worker Strategy Controls",
]:
    if marker not in dashboard_readme:
        print(f"Dashboard README missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

first_review_markers = {
    Path("README.md"): [
        "First Review Checklist",
        "bash scripts/validate_starter_kit.sh",
        "Export Review Bundle",
        "Run Safety Check",
        "python3 scripts/run_observatory.py --target . --review-dir /tmp/Diffmogger-review",
        "Diffmogger-observatory.html",
        "Diffmogger-self-review.md",
    ],
    Path("docs/DASHBOARD.md"): [
        "First Review Checklist",
        "Open Diffmogger Project",
        "Export Review Bundle",
        "Run Safety Check",
        "python3 scripts/run_observatory.py --target . --review-dir /tmp/Diffmogger-review",
        "Diffmogger-observatory.html",
        "Diffmogger-self-review.md",
    ],
    Path("docs/FRESH_PROJECT_SETUP.md"): [
        "First Review Checklist",
        "bash scripts/validate_starter_kit.sh",
        "Export Review Bundle",
        "Run Safety Check",
        "python3 scripts/run_observatory.py --target . --review-dir /tmp/Diffmogger-review",
        "Diffmogger-observatory.html",
        "Diffmogger-self-review.md",
    ],
    Path("templates/docs/DEVELOPMENT.md"): [
        "First Review Checklist",
        "bash scripts/validate_starter_kit.sh",
        "python3 scripts/diffmogger_browser.py doctor --launch",
        "Export Review Bundle",
        "Run Safety Check",
        "python3 scripts/run_observatory.py --target . --review-dir /tmp/Diffmogger-review",
        "Diffmogger-observatory.html",
        "Diffmogger-self-review.md",
    ],
    Path("services/agentic-dashboard/README.md"): [
        "First Review Checklist",
        "bash scripts/validate_starter_kit.sh",
        "Export Review Bundle",
        "Run Safety Check",
        "python3 scripts/run_observatory.py --target . --review-dir /tmp/Diffmogger-review",
        "Diffmogger-observatory.html",
        "Diffmogger-self-review.md",
    ],
}
for path, markers in first_review_markers.items():
    text = path.read_text(encoding="utf-8")
    missing = [marker for marker in markers if marker not in text]
    if missing:
        print(f"{path} missing first-review markers: {missing}", file=sys.stderr)
        raise SystemExit(1)

notifier_readme = Path("services/agentic-notifier/README.md").read_text(encoding="utf-8")
for marker in [
    "POST http://127.0.0.1:8765/api/notify",
    "DISCORD_BOT_TOKEN",
    "DISCORD_PROGRESS_CHANNEL_ID",
    "DISCORD_MESSAGING_CHANNEL_ID",
    "LOCAL_NOTIFICATIONS_ENABLED",
    "Message Content Intent",
    "View Channels",
    "Send Messages",
    "Read Message History",
    "DRY_RUN=true",
    "event_kind",
    "message_body",
    "expects_reply",
    "DISCORD_SEND_FAILED",
    "LOCAL_NOTIFICATION_FAILED",
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
    "DISCORD_BOT_TOKEN",
    "LOCAL_NOTIFICATIONS_ENABLED",
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

python3 -m unittest tests/test_run_observatory.py tests/test_run_conveyor_automation.py tests/test_repair_environment.py tests/test_integrate_role_outputs.py tests/test_list_deferred_patches.py tests/test_ticket_run.py tests/test_check_integration_safety.py tests/test_check_required_files.py tests/test_summarize_worker_outputs.py

python3 scripts/check_integration_safety.py >/tmp/Diffmogger-integration-safety.log

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
if grep -R "POST http://127.0.0.1:8765/api/notify\\|NOTIFIER_UNREACHABLE\\|message_body\\|discord_notifier\\|DISCORD_" "$tmp_dir/.agentic" "$tmp_dir/docs" >/tmp/Diffmogger-file-only-grep.log 2>&1; then
    echo "File-only scaffold unexpectedly contains notifier-only markers" >&2
    cat /tmp/Diffmogger-file-only-grep.log >&2
    rm -rf "$tmp_dir"
    exit 1
fi
if grep -R "Diffmogger Self Improvement scheduled sprint" "$tmp_dir" >/tmp/Diffmogger-self-run-leak.log 2>&1; then
    echo "Scaffold unexpectedly contains self-run lock context" >&2
    cat /tmp/Diffmogger-self-run-leak.log >&2
    rm -rf "$tmp_dir"
    exit 1
fi
if ! grep "CODEX_LOCK_CONTEXT" "$tmp_dir/scripts/run_codex_automation.sh" >/tmp/Diffmogger-lock-context-marker.log 2>&1; then
    echo "Scaffolded runner missing target-local lock context override marker" >&2
    cat "$tmp_dir/scripts/run_codex_automation.sh" >&2
    rm -rf "$tmp_dir"
    exit 1
fi
if [ -f "$tmp_dir/docs/TICKET_RUN.md" ]; then
    echo "Default scaffold unexpectedly generated ticket campaign source" >&2
    rm -rf "$tmp_dir"
    exit 1
fi
for marker in \
    "H2 Local-first demo" \
    "weekly board" \
    "Long-run direction" \
    "recurring review capsules" \
    "## Improvement Backlog"; do
    if ! grep -R -- "$marker" "$tmp_dir/.agentic" "$tmp_dir/docs/CODEX_AUTOMATION_TASKS.md" >/tmp/Diffmogger-mode-horizon-grep.log 2>&1; then
        echo "Continuous-improvement scaffold missing mode-aware horizon marker: $marker" >&2
        cat /tmp/Diffmogger-mode-horizon-grep.log >&2
        rm -rf "$tmp_dir"
        exit 1
    fi
done
rm -rf "$tmp_dir"

tmp_dir="$(mktemp -d)"
tmp_intake="$(mktemp /tmp/Diffmogger-local-excludes.XXXXXX)"
cat >"$tmp_intake" <<'JSON'
{
  "project_name": "Existing Local Excludes Smoke",
  "project_mode": "existing_project",
  "product_goal": "Integrate automation without polluting product git status.",
  "target_user": "Automation tester.",
  "desired_first_demo": "Generated local automation state is ignored.",
  "human_bridge_enabled": true,
  "human_bridge_mode": "file_only",
  "multi_role_automations_allowed": true,
  "automation_role_profile": "planner_builder_hardener_integrator",
  "automation_run_mode": "ticket_campaign",
  "verification_commands": ["npm test"]
}
JSON
(
  cd "$tmp_dir"
  git init >/tmp/Diffmogger-local-excludes-git-init.log
  git config user.name "Diffmogger Validation"
  git config user.email "diffmogger-validation@example.invalid"
  mkdir -p docs scripts
  printf '# Product Doc\n' > docs/product.md
  printf '#!/usr/bin/env bash\n' > scripts/product.sh
  git add docs/product.md scripts/product.sh
  git commit -m "product base" >/tmp/Diffmogger-local-excludes-commit.log
)
python3 scripts/scaffold_project_docs.py --intake "$tmp_intake" --target "$tmp_dir" >/tmp/Diffmogger-local-excludes-scaffold.log
for ignored_path in ".agentic/automation_prompt.md" "docs/CODEX_AUTOMATION_TASKS.md" "docs/TICKET_RUN.md" "scripts/run_role_automation.sh" "target/agent_runs/run-1/summary.md" "target/prisma-cache/node/cache-file"; do
    if ! git -C "$tmp_dir" check-ignore -q -- "$ignored_path"; then
        echo "Existing-project scaffold failed to locally ignore Diffmogger path: $ignored_path" >&2
        cat "$tmp_dir/.git/info/exclude" >&2
        rm -rf "$tmp_dir" "$tmp_intake"
        exit 1
    fi
done
for product_path in "docs/product.md" "scripts/product.sh"; do
    if git -C "$tmp_dir" check-ignore -q -- "$product_path"; then
        echo "Existing-project scaffold unexpectedly ignored product path: $product_path" >&2
        cat "$tmp_dir/.git/info/exclude" >&2
        rm -rf "$tmp_dir" "$tmp_intake"
        exit 1
    fi
done
rm -rf "$tmp_dir" "$tmp_intake"

tmp_dir="$(mktemp -d)"
tmp_intake="$(mktemp /tmp/Diffmogger-ticket-campaign.XXXXXX)"
cat >"$tmp_intake" <<'JSON'
{
  "project_name": "Ticket Campaign Smoke",
  "product_goal": "Run bounded local tickets on a fork.",
  "target_user": "Automation tester.",
  "desired_first_demo": "A completed local ticket campaign report.",
  "human_bridge_enabled": true,
  "human_bridge_mode": "local_notifier",
  "automation_run_mode": "ticket_campaign",
  "ticket_completion_notify": true,
  "verification_commands": ["npm test"]
}
JSON
python3 scripts/scaffold_project_docs.py --intake "$tmp_intake" --target "$tmp_dir" >/tmp/Diffmogger-scaffold-ticket-campaign.log
python3 scripts/check_required_files.py --human-bridge-mode local_notifier --ticket-campaign-enabled "$tmp_dir" >/tmp/Diffmogger-check-ticket-campaign.log
if ! grep -R "Automation run mode: \`ticket_campaign\`\\|docs/TICKET_RUN.md\\|scripts/ticket_run.py" "$tmp_dir/.agentic" "$tmp_dir/docs" "$tmp_dir/scripts" >/tmp/Diffmogger-ticket-campaign-grep.log 2>&1; then
    echo "Ticket-campaign scaffold missing mode markers" >&2
    rm -rf "$tmp_dir" "$tmp_intake"
    exit 1
fi
for marker in \
    "T1 Ticket-run readiness" \
    "T4 Completion report and stop" \
    "## Deferred / Follow-Up Tickets"; do
    if ! grep -R -- "$marker" "$tmp_dir/.agentic" "$tmp_dir/docs/CODEX_AUTOMATION_TASKS.md" >/tmp/Diffmogger-ticket-horizon-grep.log 2>&1; then
        echo "Ticket-campaign scaffold missing ticket progression marker: $marker" >&2
        cat /tmp/Diffmogger-ticket-horizon-grep.log >&2
        rm -rf "$tmp_dir" "$tmp_intake"
        exit 1
    fi
done
if grep -R -E "MVP|Beyond MVP|Ambitious extensions" "$tmp_dir/.agentic/automation_prompt.md" "$tmp_dir/docs/CODEX_AUTOMATION_TASKS.md" >/tmp/Diffmogger-ticket-roadmap-language.log 2>&1; then
    echo "Ticket-campaign prompt/task unexpectedly contains product-roadmap language" >&2
    cat /tmp/Diffmogger-ticket-roadmap-language.log >&2
    rm -rf "$tmp_dir" "$tmp_intake"
    exit 1
fi
rm -rf "$tmp_dir" "$tmp_intake"

tmp_dir="$(mktemp -d)"
tmp_intake="$(mktemp /tmp/Diffmogger-discord-notifier.XXXXXX)"
cat >"$tmp_intake" <<'JSON'
{
  "project_name": "Discord Notifier Smoke",
  "product_goal": "Build a Discord notifier scaffold smoke target.",
  "target_user": "Automation tester.",
  "desired_first_demo": "Generated docs only.",
  "human_bridge_enabled": true,
  "human_bridge_mode": "discord_notifier",
  "local_notifications_enabled": true,
  "verification_commands": ["npm test"]
}
JSON
python3 scripts/scaffold_project_docs.py --intake "$tmp_intake" --target "$tmp_dir" >/tmp/Diffmogger-scaffold-discord-notifier.log
python3 scripts/check_required_files.py --human-bridge-mode discord_notifier "$tmp_dir" >/tmp/Diffmogger-check-discord-notifier.log
if ! grep -R "discord_notifier\\|event_kind\\|progress\\|message\\|POST http://127.0.0.1:8765/api/notify" "$tmp_dir/.agentic" "$tmp_dir/docs" >/tmp/Diffmogger-discord-notifier-grep.log 2>&1; then
    echo "Discord-notifier scaffold missing notifier routing markers" >&2
    cat /tmp/Diffmogger-discord-notifier-grep.log >&2
    rm -rf "$tmp_dir" "$tmp_intake"
    exit 1
fi
rm -rf "$tmp_dir" "$tmp_intake"

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
    "Parallelism budget:" \
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
  "summary": "Commit type: chore\\nCommit scope: smoke\\nCommit subject: create accepted smoke file\\n\\n## Summary\\n- Create accepted smoke file.",
  "created_at": "2026-05-02T00:00:00+00:00",
  "integrated_at": null,
  "checkpoint_commit": null,
  "accepted_commit": null
}
JSON
python3 scripts/integrate_role_outputs.py "$tmp_dir" --run-id validation-integrator >/tmp/Diffmogger-integrator-smoke.log
if ! git -C "$tmp_dir" log --oneline --all | grep "chore(smoke): create accepted smoke file" >/tmp/Diffmogger-integrator-log.log; then
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
python3 scripts/list_deferred_patches.py "$tmp_dir" --markdown >/tmp/Diffmogger-deferred-list.md
python3 scripts/list_deferred_patches.py "$tmp_dir" --decision-template >/tmp/Diffmogger-deferred-decision-template.md
if ! grep 'recommended_next_action: Start with `staleness`' /tmp/Diffmogger-deferred-list.md >/tmp/Diffmogger-deferred-markdown.log; then
    echo "Deferred patch Markdown triage smoke did not recommend staleness first" >&2
    cat /tmp/Diffmogger-deferred-list.md >&2
    rm -rf "$tmp_dir" "$tmp_intake"
    exit 1
fi
if ! grep 'recommended_decision: replace_from_current_head' /tmp/Diffmogger-deferred-decision-template.md >/tmp/Diffmogger-deferred-decision-template.log; then
    echo "Deferred patch decision-template smoke did not recommend replacement from current HEAD" >&2
    cat /tmp/Diffmogger-deferred-decision-template.md >&2
    rm -rf "$tmp_dir" "$tmp_intake"
    exit 1
fi
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
if env -u MULTI_ROLE_ALLOW_REMOTES PATH="$fake_git_dir:$PATH" python3 scripts/integrate_role_outputs.py "$tmp_dir" --dry-run >/tmp/Diffmogger-remote-guard.log 2>&1; then
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
(
  cd "$tmp_dir"
  git init >/tmp/Diffmogger-pytest-repair-git-init.log
  git config user.name "Diffmogger Validation"
  git config user.email "diffmogger-validation@example.invalid"
  mkdir -p .agentic services/agentic-notifier/.venv/bin
  printf './missing_pytest_python -m pytest\n' > .agentic/verification_commands.txt
  cat > missing_pytest_python <<'SH'
#!/usr/bin/env sh
echo "No module named pytest" >&2
exit 1
SH
  chmod +x missing_pytest_python
  cat > services/agentic-notifier/.venv/bin/python <<'SH'
#!/usr/bin/env sh
if [ "$1" = "-c" ]; then
  exit 0
fi
if [ "$1" = "-m" ] && [ "$2" = "pytest" ] && [ "$3" = "services/agentic-notifier" ]; then
  exit 0
fi
echo "unexpected fake venv invocation: $*" >&2
exit 2
SH
  chmod +x services/agentic-notifier/.venv/bin/python
  git add .
  git commit -m "pytest repair smoke base" >/tmp/Diffmogger-pytest-repair-commit.log
)
python3 - "$tmp_dir" <<'PY'
import importlib.util
import sys
from pathlib import Path

target = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("integrate_role_outputs", Path("scripts/integrate_role_outputs.py"))
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)
result = module.run_verification(target)
if not result.ok:
    print(result.detail, file=sys.stderr)
    raise SystemExit(1)
checks = "\n".join(result.checks_run)
if "environment repair:" not in checks or "services/agentic-notifier/.venv/bin/python" not in checks:
    print(f"Missing pytest repair evidence in checks_run: {checks}", file=sys.stderr)
    raise SystemExit(1)
PY
rm -rf "$tmp_dir"

tmp_dir="$(mktemp -d)"
fake_npm_dir="$(mktemp -d)"
cat >"$fake_npm_dir/npm" <<'SH'
#!/usr/bin/env bash
if [ "$1" = "ci" ]; then
  mkdir -p node_modules/.bin
  cat > node_modules/.bin/vite <<'EOF'
#!/usr/bin/env sh
echo fake-vite-ok
exit 0
EOF
  chmod +x node_modules/.bin/vite
  exit 0
fi
echo "unexpected npm invocation: $*" >&2
exit 2
SH
chmod +x "$fake_npm_dir/npm"
(
  cd "$tmp_dir"
  git init >/tmp/Diffmogger-node-repair-git-init.log
  git config user.name "Diffmogger Validation"
  git config user.email "diffmogger-validation@example.invalid"
  printf '{"scripts":{"test":"vite --version"},"dependencies":{"vite":"0.0.0"}}\n' > package.json
  printf '{"lockfileVersion":3,"packages":{}}\n' > package-lock.json
  mkdir -p .git/info
  printf '/node_modules/\n' >> .git/info/exclude
  git add package.json package-lock.json
  git commit -m "node repair smoke base" >/tmp/Diffmogger-node-repair-commit.log
)
PATH="$fake_npm_dir:$PATH" python3 - "$tmp_dir" <<'PY'
import importlib.util
import os
import sys
from pathlib import Path

target = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("repair_environment", Path("scripts/repair_environment.py"))
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)
outcome = module.run_command_with_repair(target, "vite --version")
if not outcome.ok or not outcome.repair_performed:
    print(outcome.detail(), file=sys.stderr)
    raise SystemExit(1)
if "node_modules/.bin" not in "\n".join(outcome.path_prepend):
    print(outcome.to_json(), file=sys.stderr)
    raise SystemExit(1)
PY
rm -rf "$tmp_dir" "$fake_npm_dir"

tmp_dir="$(mktemp -d)"
python3 - "$tmp_dir" <<'PY'
import importlib.util
import json
import sys
from pathlib import Path

target = Path(sys.argv[1])
(target / "docs").mkdir(parents=True)
(target / "target/automation_queue/builder/run-bad").mkdir(parents=True)
(target / "docs/MULTI_ROLE_PROGRESS.md").write_text(
    "# Multi-Role Progress\n\n## Recent Activity Log\n\n- No multi-role integrator runs yet.\n",
    encoding="utf-8",
)
manifest = {
    "role": "builder",
    "run_id": "run-bad",
    "status": "deferred",
    "deferral_reason": "verification_failure",
    "deferral_detail": "failed at /User" + "s/example/agentic-kit-" + "lab/project with huge output\n" + ("x" * 5000),
    "changed_files": [],
}
(target / "target/automation_queue/builder/run-bad/manifest.json").write_text(
    json.dumps(manifest),
    encoding="utf-8",
)
spec = importlib.util.spec_from_file_location("integrate_role_outputs", Path("scripts/integrate_role_outputs.py"))
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)
module.update_progress(
    target,
    run_id="sanitize-smoke",
    verification_status="failed at /User" + "s/example/agentic-kit-" + "lab/project",
    committed=[],
    deferred_count=1,
    checkpoint_commit=None,
    cleanup_summary=[],
    dry_run=False,
)
progress = (target / "docs/MULTI_ROLE_PROGRESS.md").read_text(encoding="utf-8")
if ("/User" + "s/") in progress or ("agentic-kit-" + "lab") in progress:
    print(progress, file=sys.stderr)
    raise SystemExit(1)
if len(progress) > 5000:
    print("Progress sanitation smoke produced oversized progress output", file=sys.stderr)
    raise SystemExit(1)
PY
rm -rf "$tmp_dir"

tmp_dir="$(mktemp -d)"
python3 - "$tmp_dir" <<'PY'
import importlib.util
import sys
from pathlib import Path

target = Path(sys.argv[1])
(target / "docs").mkdir(parents=True)
(target / ".agentic/roles").mkdir(parents=True)
(target / "scripts").mkdir(parents=True)
(target / "docs/CODEX_AUTOMATION_TASKS.md").write_text("AUTOMATION_STATUS: ACTIVE\n", encoding="utf-8")
(target / "docs/MULTI_ROLE_PROGRESS.md").write_text(
    "# Multi-Role Progress\n\n## Recent Activity Log\n\n- No multi-role integrator runs yet.\n\n## Role Health\n\n- integrator: no runs yet\n",
    encoding="utf-8",
)
(target / "scripts/run_role_automation.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
for role in ["planner", "builder", "hardener", "integrator"]:
    (target / ".agentic/roles" / f"{role}.md").write_text(role, encoding="utf-8")
spec = importlib.util.spec_from_file_location("run_conveyor_automation", Path("scripts/run_conveyor_automation.py"))
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)

def conveyor_state(
    last_role="integrator",
    accepted_by_role=None,
    deferred_delta_by_role=None,
    include_metadata=True,
):
    entry = {"role": "integrator", "exit_code": 0, "progress_success": True}
    if include_metadata:
        entry["metadata"] = {
            "accepted_by_role": accepted_by_role or {"planner": 0, "builder": 0, "hardener": 0},
            "deferred_delta_by_role": deferred_delta_by_role or {"planner": 0, "builder": 0, "hardener": 0},
        }
    return {
        "schema_version": 1,
        "cycles": 1,
        "role_counts": {},
        "history": [entry],
        "last_success_by_role": {"planner": module.utc_now()},
        "last_completed_role": last_role,
    }

role, reason, stop = module.choose_next(
    target,
    conveyor_state(accepted_by_role={"planner": 1, "builder": 0, "hardener": 0}),
    3600,
    2,
)
if role != "builder" or "builder-first" not in reason or stop:
    print(("planner-integrated", role, reason, stop), file=sys.stderr)
    raise SystemExit(1)
role, reason, stop = module.choose_next(
    target,
    conveyor_state(accepted_by_role={"planner": 0, "builder": 0, "hardener": 1}),
    3600,
    2,
)
if role != "builder" or "builder-first" not in reason or stop:
    print(("hardener-integrated", role, reason, stop), file=sys.stderr)
    raise SystemExit(1)
role, reason, stop = module.choose_next(
    target,
    conveyor_state(accepted_by_role={"planner": 0, "builder": 1, "hardener": 0}),
    3600,
    2,
)
if role != "hardener" or "builder patch integrated" not in reason or stop:
    print(("builder-integrated", role, reason, stop), file=sys.stderr)
    raise SystemExit(1)
role, reason, stop = module.choose_next(target, conveyor_state(include_metadata=False), 3600, 2)
if role != "builder" or "builder-first" not in reason or stop:
    print(("missing-metadata", role, reason, stop), file=sys.stderr)
    raise SystemExit(1)

role, reason, stop = module.choose_next(
    target,
    conveyor_state(
        accepted_by_role={"planner": 0, "builder": 0, "hardener": 0},
        deferred_delta_by_role={"planner": 1, "builder": 0, "hardener": 0},
    ),
    3600,
    2,
)
if role != "planner" or "fast-follow replanning" not in reason or stop:
    print(("planner-deferral-fast-follow", role, reason, stop), file=sys.stderr)
    raise SystemExit(1)
role, reason, stop = module.choose_next(
    target,
    conveyor_state(
        accepted_by_role={"planner": 0, "builder": 0, "hardener": 0},
        deferred_delta_by_role={"planner": -1, "builder": 0, "hardener": 0},
    ),
    3600,
    2,
)
if role != "planner" or "resolved" not in reason or "fast-follow replanning" not in reason or stop:
    print(("planner-deferral-resolved-fast-follow", role, reason, stop), file=sys.stderr)
    raise SystemExit(1)

(target / "target/automation_queue/hardener/run-skipped").mkdir(parents=True)
(target / "target/automation_queue/hardener/run-skipped/manifest.json").write_text(
    '{"role":"hardener","run_id":"run-skipped","status":"skipped"}\n',
    encoding="utf-8",
)
role, reason, stop = module.choose_next(target, conveyor_state(include_metadata=False), 3600, 2)
if role == "integrator" or stop:
    print(("skipped-counted-as-queued", role, reason, stop), file=sys.stderr)
    raise SystemExit(1)
(target / "target/automation_queue/planner/run-queued").mkdir(parents=True)
queued_manifest = target / "target/automation_queue/planner/run-queued/manifest.json"
queued_manifest.write_text(
    '{"role":"planner","run_id":"run-queued","status":"queued"}\n',
    encoding="utf-8",
)
role, reason, stop = module.choose_next(target, conveyor_state(include_metadata=False), 3600, 2)
if role != "integrator" or stop:
    print(("queued-did-not-preempt", role, reason, stop), file=sys.stderr)
    raise SystemExit(1)
queued_manifest.unlink()

state = {"schema_version": 1, "cycles": 0, "role_counts": {}, "history": []}
before = {"queued": 1, "deferred": 0, "applied": 0, "failed": 0, "deferred_signature": "none"}
after = {
    "queued": 0,
    "deferred": 1,
    "applied": 0,
    "failed": 0,
    "deferred_signature": "verification_environment_failure:missing_pytest",
}
module.update_integrator_no_progress(
    state,
    before=before,
    after=after,
    exit_code=0,
    threshold=2,
    finished_at=module.utc_now(),
)
before = after
after = {
    "queued": 0,
    "deferred": 1,
    "applied": 0,
    "failed": 0,
    "deferred_signature": "verification_environment_failure:missing_pytest",
}
metadata = module.update_integrator_no_progress(
    state,
    before=before,
    after=after,
    exit_code=0,
    threshold=2,
    finished_at=module.utc_now(),
)
if not metadata.get("just_tripped") or not module.no_progress_active(state, 2):
    print(state, file=sys.stderr)
    raise SystemExit(1)
module.write_no_progress_progress_note(target, state["integrator_no_progress"])
role, reason, stop = module.choose_next(target, state, 3600, 2)
if role != "planner" or stop:
    print((role, reason, stop), file=sys.stderr)
    raise SystemExit(1)
state["integrator_no_progress"]["planner_requested_at"] = module.utc_now()
role, reason, stop = module.choose_next(target, state, 3600, 2)
if role is not None or "circuit breaker active" not in reason:
    print((role, reason, stop), file=sys.stderr)
    raise SystemExit(1)
progress = (target / "docs/MULTI_ROLE_PROGRESS.md").read_text(encoding="utf-8")
if "conveyor-no-progress" not in progress:
    print(progress, file=sys.stderr)
    raise SystemExit(1)
resolved_metadata = module.update_integrator_no_progress(
    state,
    before={
        "queued": 0,
        "deferred": 1,
        "applied": 0,
        "failed": 0,
        "deferred_signature": "staleness:no_detail",
        "deferred_by_role": {"planner": 1, "builder": 0, "hardener": 0},
    },
    after={
        "queued": 0,
        "deferred": 0,
        "applied": 0,
        "failed": 0,
        "deferred_signature": "none",
        "deferred_by_role": {"planner": 0, "builder": 0, "hardener": 0},
    },
    exit_code=0,
    threshold=2,
    finished_at=module.utc_now(),
)
if module.no_progress_active(state, 2) or not resolved_metadata.get("progress_success"):
    print(("deferral-resolution-did-not-clear-no-progress", state, resolved_metadata), file=sys.stderr)
    raise SystemExit(1)
PY
rm -rf "$tmp_dir"

tmp_dir="$(mktemp -d)"
python3 - "$tmp_dir" <<'PY'
import json
import os
import sys
from pathlib import Path

target = Path(sys.argv[1])
(target / "docs").mkdir(parents=True)
(target / "target/automation_queue/builder/run-observe").mkdir(parents=True)
(target / "target/automation_logs").mkdir(parents=True)
(target / "docs/CODEX_AUTOMATION_TASKS.md").write_text(
    "\n".join(
        [
            "AUTOMATION_STATUS: ACTIVE",
            "Last updated: validation smoke",
            "",
            "## Product Horizon State",
            "",
            "- Current horizon: local demo",
            "- Advancement decision: stay",
            "",
            "## Best Next Milestone",
            "",
            "- Ship the demo observatory.",
            "",
            "## Suggested Next Sprint-Sized Task",
            "",
            "- Tighten the conveyor timeline.",
            "",
            "## Known Issues",
            "",
            "- No known issues.",
        ]
    )
    + "\n",
    encoding="utf-8",
)
(target / "docs/MULTI_ROLE_PROGRESS.md").write_text(
    "\n".join(
        [
            "# Multi-Role Progress",
            "",
            "## Cumulative Metrics",
            "",
            "- Total integrator runs: 2",
            "- Accepted patches by role:",
            "  - planner: 1",
            "  - builder: 2",
            "  - hardener: 1",
            "- Deferred patches by role:",
            "  - planner: 1",
            "  - builder: 0",
            "  - hardener: 0",
            "- Current deferred queue depth: 1",
            "",
            "## Recent Activity Log",
            "",
            "- builder queued an observatory smoke patch.",
            "",
            "## Deferred-Patch Backlog",
            "",
            "- planner `run-stale`: staleness; Patch base no longer matches HEAD.",
        ]
    )
    + "\n",
    encoding="utf-8",
)
(target / "target/automation_logs/conveyor.stdout.log").write_text(
    "CONVEYOR_DECISION role=builder reason=validation smoke\n",
    encoding="utf-8",
)
(target / "target/automation_conveyor_state.json").write_text(
    json.dumps(
        {
            "schema_version": 1,
            "cycles": 2,
            "updated_at": "2026-05-03T00:00:00+00:00",
            "active_role_run": {
                "role": "builder",
                "run_id": "observe-smoke",
                "reason": "validation smoke",
                "pid": os.getpid(),
                "started_at": "2026-05-03T00:00:00+00:00",
                "status": "running",
            },
            "decision_queue": [
                {"role": "builder", "state": "next", "reason": "builder lane is next"},
                {"role": "integrator", "state": "ready", "reason": "queued patch needs integration"},
            ],
            "integrator_no_progress": {
                "active": True,
                "streak": 2,
                "threshold": 2,
                "reason": "integrator accepted 0 patches; deferred queue stayed blocked for staleness:no_detail",
                "planner_requested_at": None,
            },
	            "history": [
	                {
	                    "role": "hardener",
	                    "reason": "builder lane completed without queued work",
	                    "exit_code": 0,
	                    "finished_at": "2026-05-03T00:00:00+00:00",
	                    "progress_success": True,
	                },
	                {
	                    "role": "integrator",
	                    "reason": "queued patch needs integration",
	                    "exit_code": 0,
	                    "finished_at": "2026-05-03T00:01:00+00:00",
	                    "progress_success": True,
	                    "metadata": {"accepted_by_role": {"planner": 0, "builder": 0, "hardener": 1}},
	                },
	                {
	                    "role": "hardener",
	                    "reason": "hardener churn smoke",
	                    "exit_code": 0,
	                    "finished_at": "2026-05-03T00:02:00+00:00",
	                    "progress_success": True,
	                },
	                {
	                    "role": "integrator",
	                    "reason": "queued patch needs integration",
	                    "exit_code": 0,
	                    "finished_at": "2026-05-03T00:03:00+00:00",
	                    "progress_success": True,
	                    "metadata": {"accepted_by_role": {"planner": 0, "builder": 0, "hardener": 1}},
	                },
	            ],
	        },
	        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
(target / "target/automation_signals.json").write_text(
    json.dumps(
        {
            "schema_version": 1,
            "updated_at": "2026-05-03T00:00:00+00:00",
            "signals": [
                {
                    "id": "prompt-self-audit",
                    "owner_role": "planner",
                    "priority": "high",
                    "cadence": "weekly",
                    "instructions": "Review whether the recurring automation prompt still matches current project needs.",
                    "active": True,
                    "last_activated_at": "2026-05-03T00:00:00+00:00",
                    "last_completed_at": None,
                    "last_completed_by": None,
                    "last_completion_note": None,
                    "next_due_at": "2026-05-03T00:00:00+00:00",
                }
            ],
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
(target / "target/automation_queue/builder/run-observe/manifest.json").write_text(
    json.dumps(
        {
            "role": "builder",
            "run_id": "run-observe",
            "status": "queued",
            "summary": "Render a local observatory page.",
            "changed_files": ["scripts/run_observatory.py"],
            "created_at": "2026-05-03T00:00:00+00:00",
        }
    ),
    encoding="utf-8",
)
(target / "target/automation_queue/hardener/run-skipped").mkdir(parents=True)
(target / "target/automation_queue/hardener/run-skipped/manifest.json").write_text(
    json.dumps(
        {
            "role": "hardener",
            "run_id": "run-skipped",
            "status": "skipped",
            "summary": "No hardening changes were needed.",
            "changed_files": [],
            "created_at": "2026-05-03T00:04:00+00:00",
        }
    ),
    encoding="utf-8",
)
PY
python3 scripts/run_observatory.py --target "$tmp_dir" --once --output "$tmp_dir/target/observatory/index.html" >/tmp/Diffmogger-observatory-render.log
for marker in "Diffmogger Observatory" "Conveyor Belt" "Active Signals" "prompt-self-audit" "run-observe" "builder" "Conveyor Health" "First review" "Scorecard" "Action Plan" "Integration safety" "Run integrator triage" "Accepted patches" "Deferred triage" "Start with \`staleness\`" "Next-Run Worker Strategy" "INTEGRATION_ONLY" "NO-PROGRESS CIRCUIT" "staleness:no_detail" "Recent Outcomes" "run-skipped" "skipped" "hardener/integrator churn"; do
    if ! grep -q "$marker" "$tmp_dir/target/observatory/index.html"; then
        echo "Observatory render smoke missing marker: $marker" >&2
        rm -rf "$tmp_dir"
        exit 1
    fi
done
if grep -q "$tmp_dir" "$tmp_dir/target/observatory/index.html"; then
    echo "Observatory render leaked an absolute target path" >&2
    rm -rf "$tmp_dir"
    exit 1
fi
rm -rf "$tmp_dir"

tmp_dir="$(mktemp -d)"
fake_codex_dir="$(mktemp -d)"
cat >"$fake_codex_dir/codex" <<'SH'
#!/usr/bin/env bash
worktree=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "-C" ]; then
    worktree="$2"
    shift 2
    continue
  fi
  shift
done
if [ -z "$worktree" ]; then
  echo "missing -C worktree" >&2
  exit 2
fi
test -f "$worktree/.agentic/roles/builder.md" || exit 3
test -f "$worktree/docs/CODEX_AUTOMATION_TASKS.md" || exit 4
test -f "$worktree/docs/MULTI_ROLE_PROGRESS.md" || exit 5
printf 'role context smoke\n' > "$worktree/feature.txt"
exit 0
SH
chmod +x "$fake_codex_dir/codex"
(
  cd "$tmp_dir"
  git init >/tmp/Diffmogger-role-context-git-init.log
  git config user.name "Diffmogger Validation"
  git config user.email "diffmogger-validation@example.invalid"
  printf '# Role Context Smoke\n' > README.md
  git add README.md
  git commit -m "role context smoke base" >/tmp/Diffmogger-role-context-commit.log
  mkdir -p .agentic/roles docs
  printf 'builder prompt\n' > .agentic/roles/builder.md
  printf 'planner prompt\n' > .agentic/roles/planner.md
  printf 'hardener prompt\n' > .agentic/roles/hardener.md
  printf 'integrator prompt\n' > .agentic/roles/integrator.md
  printf 'AUTOMATION_STATUS: ACTIVE\n' > docs/CODEX_AUTOMATION_TASKS.md
  printf '# Multi-Role Progress\n' > docs/MULTI_ROLE_PROGRESS.md
  mkdir -p .git/info
  {
    printf '/.agentic/\n'
    printf '/docs/CODEX_AUTOMATION_TASKS.md\n'
    printf '/docs/MULTI_ROLE_PROGRESS.md\n'
  } >> .git/info/exclude
)
CODEX_AUTOMATION_PATH="$fake_codex_dir:$PATH" CODEX_RUN_ID="validation-context" \
  bash scripts/run_role_automation.sh --target "$tmp_dir" --role builder >/tmp/Diffmogger-role-context.log
patch_path="$tmp_dir/target/automation_queue/builder/validation-context/changes.patch"
changed_path="$tmp_dir/target/automation_queue/builder/validation-context/changed_files.txt"
if ! grep -q "feature.txt" "$patch_path"; then
    echo "Role context smoke did not export fake feature change" >&2
    cat /tmp/Diffmogger-role-context.log >&2
    rm -rf "$tmp_dir" "$fake_codex_dir"
    exit 1
fi
if grep -E "\\.agentic|CODEX_AUTOMATION_TASKS|MULTI_ROLE_PROGRESS" "$patch_path" "$changed_path" >/tmp/Diffmogger-role-context-pollution.log; then
    echo "Role context smoke leaked seeded context into queued patch" >&2
    cat /tmp/Diffmogger-role-context-pollution.log >&2
    rm -rf "$tmp_dir" "$fake_codex_dir"
    exit 1
fi
rm -rf "$tmp_dir" "$fake_codex_dir"

tmp_dir="$(mktemp -d)"
fake_codex_dir="$(mktemp -d)"
cat >"$fake_codex_dir/codex" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod +x "$fake_codex_dir/codex"
(
  cd "$tmp_dir"
  git init >/tmp/Diffmogger-role-skipped-git-init.log
  git config user.name "Diffmogger Validation"
  git config user.email "diffmogger-validation@example.invalid"
  printf '# Role Skipped Smoke\n' > README.md
  git add README.md
  git commit -m "role skipped smoke base" >/tmp/Diffmogger-role-skipped-commit.log
  mkdir -p .agentic/roles docs
  printf 'builder prompt\n' > .agentic/roles/builder.md
)
CODEX_AUTOMATION_PATH="$fake_codex_dir:$PATH" CODEX_RUN_ID="validation-skipped" \
  bash scripts/run_role_automation.sh --target "$tmp_dir" --role builder >/tmp/Diffmogger-role-skipped.log
if ! grep '"status": "skipped"' "$tmp_dir/target/automation_queue/builder/validation-skipped/manifest.json" >/tmp/Diffmogger-role-skipped-status.log; then
    echo "Role no-op smoke did not mark empty patch as skipped" >&2
    cat /tmp/Diffmogger-role-skipped.log >&2
    rm -rf "$tmp_dir" "$fake_codex_dir"
    exit 1
fi
rm -rf "$tmp_dir" "$fake_codex_dir"

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

required = ["fastapi", "discord", "pytest", "httpx", "uvicorn"]
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
