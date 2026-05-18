#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
kit_root="$(pwd)"

python3 scripts/validate_starter_kit_manifest.py validation/starter_kit_manifest.json

python3 - <<'PY'
from pathlib import Path
import json
import os
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
    "multi_role_allow_remotes",
    "campaign_mode",
    "bounded",
    "ongoing",
    "ticket_run_file",
    "ticket_completion_notify",
    "discord_notifier",
    "local_notifications_enabled",
    "optional_mcp_servers",
    "\"default\": [\"context7\", \"playwright\"]",
    "context7",
    "playwright",
]:
    if marker not in project_schema:
        print(f"Project intake schema missing write-worker marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

for removed_marker in [
    "desired_cadence",
    "multi_role_base_cadence_minutes",
    "automation_schedule_strategy",
    "automation_signals_enabled",
]:
    if removed_marker in project_schema:
        print(f"Project intake schema still contains retired schedule/signal marker: {removed_marker}", file=sys.stderr)
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
        "node_modules",
        "dist",
        "dist-ssr",
        "gen",
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
for root, dirnames, filenames in os.walk("."):
    root_path = Path(root)
    dirnames[:] = sorted(
        dirname
        for dirname in dirnames
        if not skip_stale_reference_scan(root_path / dirname)
    )
    for filename in sorted(filenames):
        path = root_path / filename
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
    "## Automation Role Profile",
    "## Optional MCP Integrations",
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
    "## Optional MCP Integrations",
    "## UI Artifact Backlog",
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
    "Optional MCP servers must never be required for progress",
    "docs/backlog/ui_artifacts/<run_id>/",
    "MCP decision: context7 used|skipped",
    "npm run browser-smoke",
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

for marker in [
    "CODEX_LOCK_ALREADY_ACQUIRED=true",
    ".diffmogger/scripts/acquire_codex_lock.sh",
    ".diffmogger/scripts/release_codex_lock.sh",
    ".diffmogger/scripts/spawn_worker_agent.sh",
    ".diffmogger/scripts/summarize_worker_outputs.py",
    "target/canonical_state_brief.md",
    "Codex CLI worker decision: USE / SKIP / UNAVAILABLE",
    "MCP decision: context7 used|skipped",
    "Worker strategy: READ_ONLY_REPORTS / WRITE_WORKERS / INTEGRATION_ONLY / NO_WORKERS",
    "Parallelism budget:",
    "Write-capable worker agents allowed:",
    "Max write worker count:",
    "command -v codex",
    "--dangerously-bypass-approvals-and-sandbox",
    "{{HUMAN_PROTOCOL}}",
    "{{WRITE_WORKER_ORCHESTRATION}}",
    "{{MULTI_ROLE_AUTOMATION_SECTION}}",
    "{{MCP_SETUP_SECTION}}",
    "expired auth",
    "docs/backlog/ui_artifacts/<run_id>/<issue-slug>.png",
    "npm run browser-smoke",
    "{{TICKET_CAMPAIGN_SECTION}}",
    "{{PRODUCT_HORIZON_GUIDANCE}}",
    "## Product Horizon State",
    "## Horizon Transition Log",
]:
    if marker not in automation:
        print(f"Automation prompt missing required marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

runner = Path("templates/scripts/run_role_automation.sh").read_text(encoding="utf-8")
for marker in [
    "diffmogger_browser.py",
    "DIFFMOGGER_BROWSER_PATH",
    "PLAYWRIGHT_MCP_EXECUTABLE_PATH",
    "PLAYWRIGHT_MCP_OUTPUT_DIR",
    "mcp_servers.context7.command",
    "mcp_servers.context7.env_vars",
    "mcp_servers.playwright.command",
    "mcp_servers.playwright.disabled_tools",
    "mcp_telemetry_path",
    "mcp_requested_servers",
    "mcp_mounted_servers",
    "playwright_validation_status",
    "--add-dir",
    "codex exec --full-auto",
    "--skip-git-repo-check",
    "repair_environment.py",
    "state_brief.py",
    "canonical_state_brief.md",
    "ticket_run.py",
    "run_process_watchdog.py",
]:
    if marker not in runner:
        print(f"Automation runner template missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

watchdog = Path("src/diffmogger/runtime/run_process_watchdog.py").read_text(encoding="utf-8")
for marker in [
    "CODEX_ROLE_TIMEOUT_SECONDS",
    "CODEX_ROLE_IDLE_TIMEOUT_SECONDS",
    "CODEX_ROLE_TERMINATION_GRACE_SECONDS",
    "DEFAULT_TIMEOUT_SECONDS = 5400",
    "DEFAULT_IDLE_TIMEOUT_SECONDS = 600",
    "TIMEOUT_EXIT_CODE = 124",
    "start_new_session=True",
    "os.killpg",
    "timed_out",
    "idle_timed_out",
    "progress_path_changed",
]:
    if marker not in watchdog:
        print(f"Watchdog helper template missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)
if "Diffmogger Self Improvement scheduled sprint" in runner:
    print("Scheduled runner template contains self-run lock context", file=sys.stderr)
    raise SystemExit(1)

mcp_config = Path("templates/.codex/config.toml").read_text(encoding="utf-8")
for marker in [
    "Diffmogger optional MCP configuration",
    "{{MCP_CODEX_CONFIG}}",
    "temporary per-role `codex exec -c` overrides",
]:
    if marker not in mcp_config:
        print(f"MCP config template missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

mcp_docs = Path("templates/docs/MCP_INTEGRATIONS.md").read_text(encoding="utf-8")
for marker in [
    "# Optional MCP Integrations",
    "{{MCP_SETUP_SECTION}}",
    "Role wrappers apply temporary `codex exec -c` MCP overrides",
    "CONTEXT7_API_KEY",
    "browser_take_screenshot",
    "MCP decision: context7 used|skipped",
    "do not depend on a worktree `.codex/config.toml`",
]:
    if marker not in mcp_docs:
        print(f"MCP docs template missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

playwright_mcp_helper = Path("templates/scripts/run_playwright_mcp.sh").read_text(encoding="utf-8")
for marker in [
    "@playwright/mcp@latest",
    "--headless",
    "--isolated",
    "--codegen",
    "--output-dir",
    "PLAYWRIGHT_MCP_EXECUTABLE_PATH",
    "docs/backlog/ui_artifacts",
]:
    if marker not in playwright_mcp_helper:
        print(f"Playwright MCP helper template missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

browser_helper = Path("src/diffmogger/runtime/diffmogger_browser.py").read_text(encoding="utf-8")
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

env_loader = Path("src/diffmogger/runtime/load_automation_env.py").read_text(encoding="utf-8")
for marker in [
    "CODEX_AUTOMATION_ENV_LOADED",
    "CODEX_AUTOMATION_ENV_FILES",
    "CODEX_AUTOMATION_ENV_DENYLIST",
    "apps/*/.env.local",
    "os.execvpe",
]:
    if marker not in env_loader:
        print(f"Automation env loader template missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

ticket_helper = Path("src/diffmogger/runtime/ticket_run.py").read_text(encoding="utf-8")
for marker in [
    "json ticket-run",
    "next",
    "depends_on",
    "placeholder_tickets",
    "dependency_cycles",
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

conveyor_files = [
    Path("src/diffmogger/runtime/run_conveyor_automation.py"),
    Path("src/diffmogger/runtime/state_store.py"),
    *sorted(Path("src/diffmogger/conveyor").glob("*.py")),
]
conveyor = "\n".join(path.read_text(encoding="utf-8") for path in conveyor_files)
for marker in [
    "automation_conveyor.lock",
    "orchestration.sqlite3",
    "automation_activity",
    "conveyor_work_items",
    "conveyor_stage_contracts",
    "conveyor_stage_attempts",
    "execution_dag_nodes",
    "execution_dag_edges",
    "execution_dag",
    "capability_manifests",
    "validation_receipts",
    "automation_control",
    "automation.control",
    "escalations",
    "task_edges",
    "repo.capability_manifest",
    "refresh_index",
    "DIFFMOGGER_SELECTED_PATCH_IDS",
    "patch_id",
    "queued role patch",
    "run_role_automation.sh",
	    "MULTI_ROLE_ALLOW_REMOTES",
	    "active_role_run",
    "decision_queue",
    "accepted_by_role",
    "deferred_delta_by_role",
    "planner deferred patch resolved",
    "bounded campaign complete",
    "bounded campaign blocked",
    "builder-first policy",
]:
    if marker not in conveyor:
        print(f"Automation runner template missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

observatory_files = [
    Path("src/diffmogger/runtime/run_observatory.py"),
    *sorted(Path("src/diffmogger/observatory").glob("*.py")),
]
observatory = "\n".join(path.read_text(encoding="utf-8") for path in observatory_files)
for marker in [
    "Diffmogger Observatory",
    "state_snapshot",
    "runner_projection_path_for_target",
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
    "Runtime Health",
	    "Recent Outcomes",
	]:
	    if marker not in observatory:
	        print(f"Observatory template missing marker: {marker}", file=sys.stderr)
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
        "target/canonical_state_brief.md",
        "docs/MULTI_ROLE_PROGRESS.md",
        "MCP decision: context7 used|skipped",
    ]
    if role != "integrator":
        markers.extend(["Commit subject:", "Do not use generic subjects"])
    if role in {"planner", "builder"}:
        markers.extend(["Context7", "auth errors", "do not halt"])
    if role in {"hardener", "integrator"}:
        markers.extend(["browser_take_screenshot", "docs/backlog/ui_artifacts"])
    for marker in markers:
        if marker not in role_prompt:
            print(f"Role prompt template {role} missing marker: {marker}", file=sys.stderr)
            raise SystemExit(1)

run_role = Path("templates/scripts/run_role_automation.sh").read_text(encoding="utf-8")
for marker in [
    "--role",
    "planner|builder|hardener|integrator",
    "MULTI_ROLE_ALLOW_REMOTES",
    "PLAYWRIGHT_MCP_EXECUTABLE_PATH",
    "PLAYWRIGHT_MCP_OUTPUT_DIR",
    "load_automation_env.py",
    "CODEX_AUTOMATION_ENV_LOADED",
    "mcp_servers.context7.command",
    "mcp_servers.context7.env_vars",
    "mcp_servers.playwright.command",
    "mcp_servers.playwright.disabled_tools",
    "mcp_telemetry_path",
    "mcp_requested_servers",
    "mcp_mounted_servers",
    "playwright_validation_status",
    "git remote -v",
    "git worktree add",
    "git ls-files --others --exclude-standard -z",
    "git add -N",
    "CRITICAL_STOP",
    "repair_environment.py",
    "automation_queue",
    "automation_worktrees",
    "validation_jobs",
    "manifest.json",
    "runtime_state_actions.json",
    "runtime_state_changed_files",
    "hardener_deferred_context.md",
    "runtime_state_status",
    "runtime_state_paths.txt",
    "allowed_runtime_path",
    ".agentic/automation_prompt.md",
    ".agentic/roles/builder.md",
    ".codex/config.toml",
    "scripts/run_playwright_mcp.sh",
    "Runtime Summary Contract",
    "Commit subject:",
    "state_brief.py",
    "canonical_state_brief.md",
]:
    if marker not in run_role:
        print(f"Role runner template missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

integrator_files = [
    Path("src/diffmogger/runtime/integrate_role_outputs.py"),
    *sorted(Path("src/diffmogger/integrator").glob("*.py")),
]
integrator = "\n".join(path.read_text(encoding="utf-8") for path in integrator_files)
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
    "validation_jobs",
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
    "## UI Artifact Backlog",
    "## Architectural Decisions",
    "## Role Health",
    "fast-follow replanning",
]:
    if marker not in progress:
        print(f"Multi-role progress template missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

compile_paths = [
    *Path("src/diffmogger").rglob("*.py"),
    *Path("scripts").rglob("*.py"),
]
for path in sorted(set(compile_paths)):
    result = subprocess.run([sys.executable, "-m", "py_compile", str(path)])
    if result.returncode != 0:
        print(f"Dashboard Python compile failed: {path}", file=sys.stderr)
        raise SystemExit(1)

dashboard_shared = Path("src/diffmogger/dashboard/shared/__init__.py").read_text(encoding="utf-8")
for marker in [
    "DASHBOARD_STATE_FILE",
    "load_repo_dotenv",
    "DIFFMOGGER_KIT_ROOT",
    "check_prerequisites",
    "format_prerequisites",
    "write_worker_count_from_text",
    "env_access_policy_from_value",
    "optional_mcp_servers_from_value",
    "optional_mcp_servers_from_sources",
    "DEFAULT_OPTIONAL_MCP_SERVERS",
    "codex_mcp_detail",
    "CONTEXT7_API_KEY",
    "PLAYWRIGHT_MCP_EXECUTABLE_PATH",
    "planner_builder_hardener_integrator",
    "OBSERVATORY_SCRIPT",
    "INTEGRATION_SAFETY_SCRIPT",
    "Run Safety Check",
    "dashboard_worker_strategy",
    "read_only_worker_command",
    "write_worker_command",
    "integration_only_command",
    "check_integration_safety.py",
    "run_observatory.py",
    "spawn_worker_agent.sh",
    "DEFAULT_AUTOMATION_PATH",
    "DIFFMOGGER_BROWSER_PATH",
    "DIFFMOGGER_BROWSER_CACHE",
    "automation_environment",
    "run_role_automation.sh",
]:
    if marker not in dashboard_shared:
        print(f"Dashboard shared helper missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

backend_cli_files = [
    Path("src/diffmogger/dashboard/backend_cli.py"),
    Path("src/diffmogger/dashboard/cli.py"),
    Path("src/diffmogger/dashboard/errors.py"),
    Path("src/diffmogger/dashboard/jsonio.py"),
    Path("src/diffmogger/dashboard/target.py"),
    *sorted(Path("src/diffmogger/dashboard/commands").glob("*.py")),
]
backend_cli = "\n".join(path.read_text(encoding="utf-8") for path in backend_cli_files)
for marker in [
    "project.load_snapshot",
    "project.list_recent",
    "brief.load",
    "brief.save_draft",
    "brief.scaffold_preview",
    "brief.scaffold",
    "context.import",
    "inbox.load",
    "inbox.send_note",
    "inbox.reply_request",
    "run.load",
    "run.load_log",
    "run.once",
    "automation.start",
    "automation.stop",
    "run_conveyor_automation.sh",
    "runner_projection_path_for_target",
    "automation_logs",
    "start_new_session=True",
    "safety.run_check",
    "worker.run_read_only",
    "worker.run_write",
    "worker.run_integrator",
    "observatory.snapshot",
    "observatory.generate_html",
    "observatory.load_html",
    "review.load",
    "review.export_bundle",
    "review.mark_reviewed",
    "state.snapshot",
    "state.validate",
    "diagnostics.environment",
    "diagnostics.run_checks",
    "advanced.list_files",
    "advanced.load_file",
    "advanced.save_file",
    "advanced.validate_file",
    "advanced.export_debug_bundle",
    "schema_version",
    "BackendArgumentParser",
    "resolve_target",
]:
    if marker not in backend_cli:
        print(f"Dashboard backend CLI missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

native_package = Path("services/agentic-dashboard/native/package.json").read_text(encoding="utf-8")
for marker in [
    "diffmogger-native-dashboard",
    "@tauri-apps/api",
    "lucide-react",
    "\"build\": \"tsc && vite build\"",
    "\"test\": \"vitest run\"",
    "\"tauri\": \"tauri\"",
]:
    if marker not in native_package:
        print(f"Native dashboard package missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

native_tauri = Path("services/agentic-dashboard/native/src-tauri/tauri.conf.json").read_text(encoding="utf-8")
for marker in [
    "Diffmogger",
    "com.diffmogger.dashboard",
    "\"decorations\": false",
    "\"targets\": [\"app\"]",
]:
    if marker not in native_tauri:
        print(f"Native Tauri config missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

native_cargo = Path("services/agentic-dashboard/native/src-tauri/Cargo.toml").read_text(encoding="utf-8")
for marker in [
    "diffmogger-native-dashboard",
    "tauri = { version = \"2\"",
    "rfd =",
    "serde_json",
]:
    if marker not in native_cargo:
        print(f"Native Cargo manifest missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

native_lib = Path("services/agentic-dashboard/native/src-tauri/src/lib.rs").read_text(encoding="utf-8")
for marker in [
    "scripts/dashboard_backend_cli.py",
    "RECENT_CONFIG_FILE",
    "validate_target_path",
    "READ_ONLY_BACKEND_COMMANDS",
    "MUTATING_BACKEND_COMMANDS",
    "DEFAULT_AUTOMATION_PATH",
    "path_with_native_toolchain",
    "backend_python_executable",
    "prepare_backend_process",
    "DIFFMOGGER_NATIVE_APP_PATH",
    "DIFFMOGGER_BACKEND_PATH",
    "rfd::FileDialog",
    "select_context_files",
    "select_settings_directory",
    "get_advanced_settings",
    "update_advanced_settings",
    "run_backend_command_streamed",
    "backend-log",
    "brief.scaffold",
    "brief.scaffold_preview",
    "context.import",
    "inbox.load",
    "inbox.send_note",
    "inbox.reply_request",
    "automation.start",
    "automation.stop",
    "safety.run_check",
    "worker.run_read_only",
    "worker.run_write",
    "worker.run_integrator",
    "project.load_snapshot",
    "diagnostics.environment",
    "observatory.snapshot",
    "observatory.load_html",
    "review.load",
    "review.mark_reviewed",
    "state.snapshot",
    "state.validate",
    "advanced.save_file",
    "advanced.validate_file",
    "advanced.export_debug_bundle",
    "open_observatory_file",
    "open_review_artifact",
    "open_managed_file",
    "reveal_managed_file",
    "reveal_project",
    "open_project_in_editor",
    "ALLOWED_EDITOR_COMMANDS",
    "validate_review_artifact_path",
    "validate_observatory_html_path",
    "app_config_dir",
    "run_backend_command",
]:
    if marker not in native_lib:
        print(f"Native Rust command layer missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

native_api = Path("services/agentic-dashboard/native/src/api/backend.ts").read_text(encoding="utf-8")
for marker in [
    "BackendEnvelope",
    "InboxSnapshot",
    "ReviewSnapshot",
    "ProjectSnapshot",
    "listRecentProjects",
    "selectProjectFolder",
    "selectContextFiles",
    "loadProjectSnapshot",
    "runBackendCommand",
    "runBackendCommandStreamed",
    "listenBackendLogs",
    "openObservatoryFile",
    "openReviewArtifact",
    "openManagedFile",
    "revealManagedFile",
    "revealProject",
    "openProjectInEditor",
    "AdvancedSettings",
    "AdvancedDebugBundleResult",
    "CanonicalStateSnapshot",
    "ObservatorySnapshot",
    "ownership",
]:
    if marker not in native_api:
        print(f"Native frontend API missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

native_app = Path("services/agentic-dashboard/native/src/App.tsx").read_text(encoding="utf-8")
for marker in [
    "Home",
    "Brief",
    "Run",
    "Observatory",
    "Inbox",
    "Review",
    "Advanced",
    "Backend Error",
    "Choose project",
    "Command",
    "HomePage",
    "BriefWizard",
    "InboxPage",
    "ObservatoryPage",
    "ReviewPage",
    "RunPage",
    "AdvancedPage",
    "CommandPalette",
    "Cmd/Ctrl+K",
    "executePaletteCommand",
    "buildCommandPaletteModel",
    "Next action",
]:
    if marker not in native_app:
        print(f"Native React shell missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

native_command_palette = Path("services/agentic-dashboard/native/src/CommandPalette.tsx").read_text(encoding="utf-8")
for marker in [
    "Command palette",
    "Search commands",
    "disabledReason",
    "No matching commands",
    "ArrowDown",
    "ArrowUp",
    "Enter",
    "Escape",
]:
    if marker not in native_command_palette:
        print(f"Native CommandPalette missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

native_command_palette_model = Path("services/agentic-dashboard/native/src/commandPaletteModel.ts").read_text(encoding="utf-8")
for marker in [
    "Open project",
    "New project",
    "Reveal project in Finder",
    "Open project in editor",
    "Open setup",
    "Import context files",
    "Scaffold",
    "Run",
    "Start automation.",
    "Stop automation.",
    "Run safety check",
    "Open activity",
    "Export review",
    "Send note to next run",
    "Open task state",
    "Open diagnostics",
    "Export debug",
    "filterPaletteCommands",
]:
    if marker not in native_command_palette_model:
        print(f"Native command palette model missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

native_command_palette_tests = Path("services/agentic-dashboard/native/src/commandPaletteModel.test.ts").read_text(encoding="utf-8")
for marker in [
    "includes the required command surface",
    "explains disabled target-scoped commands",
    "uses run-control reasons",
    "searches command title",
]:
    if marker not in native_command_palette_tests:
        print(f"Native command palette tests missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

native_brief = Path("services/agentic-dashboard/native/src/BriefWizard.tsx").read_text(encoding="utf-8")
for marker in [
    "Setup",
    "Project",
    "Goal",
    "Stack",
    "Run mode",
    "Guardrails",
    "Context files",
    "Review",
    "brief.save_draft",
    "brief.scaffold_preview",
    "context.import",
    "brief.scaffold",
    "Scaffold",
    "Add context files",
    "Context7 MCP",
    "Playwright MCP",
    "Checkpoint commits",
    "FIRST_REVIEW_NEEDED",
    "progress-log",
    "Open Debug",
]:
    if marker not in native_brief:
        print(f"Native Brief wizard missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

native_home_model = Path("services/agentic-dashboard/native/src/homeModel.ts").read_text(encoding="utf-8")
for marker in [
    "buildHomeModel",
    "Unknown",
    "Open setup",
    "Open Run",
    "Open Inbox",
    "Review",
    "Start automation from Run.",
    "Gates needing attention",
]:
    if marker not in native_home_model:
        print(f"Native Home model missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

native_home_tests = Path("services/agentic-dashboard/native/src/homeModel.test.ts").read_text(encoding="utf-8")
for marker in [
    "maps no target",
    "maps unconfigured targets",
    "maps scaffolded targets with no runs",
    "maps running targets",
    "maps blocked human input",
    "maps environment blockers",
]:
    if marker not in native_home_tests:
        print(f"Native Home tests missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

native_run_model = Path("services/agentic-dashboard/native/src/runModel.ts").read_text(encoding="utf-8")
for marker in [
    "buildRunModel",
    "Complete setup before running.",
    "Run",
    "Start",
    "Stop",
    "Run safety check",
    "automation.start",
    "automation.stop",
    "safety.run_check",
    "worker.run_read_only",
    "worker.run_write",
    "worker.run_integrator",
    "READ_ONLY_REPORTS",
    "Run read-only worker",
    "Environment blocker",
]:
    if marker not in native_run_model:
        print(f"Native Run model missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

native_run_page = Path("services/agentic-dashboard/native/src/RunPage.tsx").read_text(encoding="utf-8")
for marker in [
    "Readiness",
    "Controls",
    "Automation",
    "Current status",
    "Log",
    "Helper Strategy",
    "Blockers",
    "worker.run_write",
    "Copy",
    "Open Log File",
]:
    if marker not in native_run_page:
        print(f"Native Run page missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

native_run_tests = Path("services/agentic-dashboard/native/src/runModel.test.ts").read_text(encoding="utf-8")
for marker in [
    "disables run controls when no target is selected",
    "maps unscaffolded targets to the Brief gate",
    "enables Start for ready scaffolded targets",
    "disables start controls while automation is active",
    "enables Stop only when automation is running",
    "translates read-only worker strategy strings",
]:
    if marker not in native_run_tests:
        print(f"Native Run tests missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

native_inbox = Path("services/agentic-dashboard/native/src/InboxPage.tsx").read_text(encoding="utf-8")
for marker in [
    "Requests",
    "Notes to next run",
    "Archive",
    "bridge-mode-pill",
    "inbox.load",
    "inbox.send_note",
    "inbox.reply_request",
    "Send reply",
    "Send to next run",
    "Queued and recent notes",
    "Search archive",
]:
    if marker not in native_inbox:
        print(f"Native Inbox page missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

native_review = Path("services/agentic-dashboard/native/src/ReviewPage.tsx").read_text(encoding="utf-8")
native_review_model = Path("services/agentic-dashboard/native/src/reviewModel.ts").read_text(encoding="utf-8")
for marker in [
    "review-trust-summary",
    "Latest Run Review",
    "Run in progress",
    "Review marker",
    "Next action",
    "Changed files",
    "Commits",
    "Verification",
    "Safety check",
    "Skipped checks",
    "Markdown preview",
    "Review export",
    "review.load",
    "review.export_bundle",
    "review.mark_reviewed",
    "openReviewArtifact",
    "Open Markdown",
    "Reveal folder",
    "Open Inbox",
    "Mark latest snapshot reviewed",
]:
    if marker not in native_review and marker not in native_review_model:
        print(f"Native Review page missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

native_advanced = Path("services/agentic-dashboard/native/src/AdvancedPage.tsx").read_text(encoding="utf-8")
for marker in [
    "Files",
    "Diagnostics",
    "Settings",
    "Debug export",
    "Core state",
    "Human bridge",
    "Review",
    "Context",
    "Roles / scheduler",
    "advanced.list_files",
    "advanced.load_file",
    "advanced.save_file",
    "advanced.validate_file",
    "advanced.export_debug_bundle",
    "Open externally",
    "Reveal in Finder",
    "Run checks",
    "Codex",
    "Tools",
    "Target write access",
    "Notifier",
    "Backend versions",
    "Review export directory",
    "Preferred editor command",
    "Inbox mode",
    "Appearance",
    "Density",
    ".env and .env.* contents are omitted",
]:
    if marker not in native_advanced:
        print(f"Native Advanced page missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

native_observatory_page = Path("services/agentic-dashboard/native/src/ObservatoryPage.tsx").read_text(encoding="utf-8")
for marker in [
    "Activity",
    "observatory.snapshot",
    "review.export_bundle",
    "targetSubdir",
    "Export review",
    "Summary",
    "Events",
    "Queue",
    "Metrics",
    "MissionStrip",
    "AutomationActivityGraphPanel",
    "Recent role results",
    "LandedWorkSection",
    "RecentOutcomesSection",
    "Runtime",
    "RoleCard",
    "CommitCard",
]:
    if marker not in native_observatory_page:
        print(f"Native Observatory page missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

native_observatory_model = Path("services/agentic-dashboard/native/src/observatoryModel.ts").read_text(encoding="utf-8")
for marker in [
    "buildObservatoryViewModel",
    "Critical stop is active",
    "Input needed",
    "Activity",
    "Summary",
    "Events",
    "activeRole",
    "Queue",
    "Metrics",
]:
    if marker not in native_observatory_model:
        print(f"Native Observatory model missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

native_observatory_tests = Path("services/agentic-dashboard/native/src/observatoryModel.test.ts").read_text(encoding="utf-8")
for marker in [
    "covers the empty state",
    "covers an active builder",
    "covers a queued patch",
    "covers blocked user input",
    "covers critical stop",
]:
    if marker not in native_observatory_tests:
        print(f"Native Observatory tests missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

native_observatory_page_tests = Path("services/agentic-dashboard/native/src/ObservatoryPage.test.tsx").read_text(encoding="utf-8")
for marker in [
    "renders the empty state",
    "renders an active builder",
    "renders a queued patch",
    "renders blocked user input",
    "renders a critical stop",
    "renderToStaticMarkup",
]:
    if marker not in native_observatory_page_tests:
        print(f"Native Observatory component tests missing marker: {marker}", file=sys.stderr)
        raise SystemExit(1)

dashboard_readme = Path("services/agentic-dashboard/README.md").read_text(encoding="utf-8")
for marker in [
    "services/agentic-dashboard/native",
    "scripts/dashboard_backend_cli.py",
    "Scaffold",
    ".diffmogger/agentic/dashboard_state.json",
    "Open Diffmogger Project",
    ".diffmogger/context/",
    ".diffmogger/state/PROJECT_CONTEXT.md",
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
        "python3 .diffmogger/scripts/run_observatory.py --target . --review-dir /tmp/Diffmogger-review",
        "Diffmogger-observatory.html",
        "Diffmogger-self-review.md",
    ],
    Path("docs/DASHBOARD.md"): [
        "First Review Checklist",
        "Open Diffmogger Project",
        "Export Review Bundle",
        "Run Safety Check",
        "python3 .diffmogger/scripts/run_observatory.py --target . --review-dir /tmp/Diffmogger-review",
        "Diffmogger-observatory.html",
        "Diffmogger-self-review.md",
    ],
    Path("docs/FRESH_PROJECT_SETUP.md"): [
        "First Review Checklist",
        "bash scripts/validate_starter_kit.sh",
        "Export Review Bundle",
        "Run Safety Check",
        "python3 .diffmogger/scripts/run_observatory.py --target . --review-dir /tmp/Diffmogger-review",
        "Diffmogger-observatory.html",
        "Diffmogger-self-review.md",
    ],
    Path("templates/docs/DEVELOPMENT.md"): [
        "First Review Checklist",
        "bash scripts/validate_starter_kit.sh",
        "python3 .diffmogger/scripts/diffmogger_browser.py doctor --launch",
        "Export Review Bundle",
        "Run Safety Check",
        "python3 .diffmogger/scripts/run_observatory.py --target . --review-dir /tmp/Diffmogger-review",
        "Diffmogger-observatory.html",
        "Diffmogger-self-review.md",
    ],
    Path("services/agentic-dashboard/README.md"): [
        "First Review Checklist",
        "bash scripts/validate_starter_kit.sh",
        "Export Review Bundle",
        "Run Safety Check",
        "python3 .diffmogger/scripts/run_observatory.py --target . --review-dir /tmp/Diffmogger-review",
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
    "Diffmogger is a local orchestration engine for Codex, backed by a directed execution graph.",
    "## Execution Model",
    "## Quickstart",
    "## Source Layout",
    "src/diffmogger/kit/",
    "src/diffmogger/runtime/",
    "src/diffmogger/integrator/",
    "src/diffmogger/observatory/",
    "src/diffmogger/dashboard/",
    ".diffmogger/runtime/orchestration.sqlite3",
    "## Generated Targets",
    ".diffmogger/lib/diffmogger/",
    "## Dashboard",
    "## Validation",
    "validation/starter_kit_manifest.json",
    "docs/FRESH_PROJECT_SETUP.md",
    "## Safety Defaults",
    "## Docs",
    "## License",
    "MIT License",
    "https://github.com/harrisonpedrero/diffmogger.git",
    "services/agentic-dashboard/native",
    "scripts/scaffold_project_docs.py",
    "scripts/check_required_files.py",
    "Run Safety Check",
    "Export Review Bundle",
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

python3 -m unittest tests.runtime.test_state_store tests.runtime.test_codebase_graph tests.runtime.test_worker_agents tests.runtime.test_run_observatory tests.dashboard.test_dashboard_backend_cli tests.dashboard.test_dashboard_env_loading tests.kit.test_native_rebuild_guardrails tests.kit.test_starter_kit_manifest tests.runtime.test_run_conveyor_automation tests.runtime.test_run_role_automation tests.runtime.test_run_process_watchdog tests.runtime.test_load_automation_env tests.runtime.test_repair_environment tests.runtime.test_integrate_role_outputs tests.runtime.test_list_deferred_patches tests.runtime.test_ticket_run tests.runtime.test_readiness_eval tests.runtime.test_preflight tests.kit.test_check_integration_safety tests.kit.test_check_required_files tests.runtime.test_summarize_worker_outputs

python3 scripts/evaluate_symbol_scheduler_readiness.py --first-24h >/tmp/Diffmogger-readiness-eval.log

python3 scripts/check_integration_safety.py >/tmp/Diffmogger-integration-safety.log

python3 - <<'PY' >/tmp/Diffmogger-dashboard-smoke.log
import sys
from pathlib import Path
sys.path.insert(0, str(Path("src").resolve()))
from diffmogger.dashboard import shared
raise SystemExit(shared.smoke_check())
PY

lock_smoke_dir="$(mktemp -d)"
CODEX_LOCK_PATH="$lock_smoke_dir/target/codex_automation.lock" \
CODEX_RUN_ID="validation-smoke" \
bash scripts/target/acquire_codex_lock.sh "validation smoke" >/tmp/Diffmogger-lock-acquire.log

if CODEX_LOCK_PATH="$lock_smoke_dir/target/codex_automation.lock" \
  CODEX_RUN_ID="validation-other" \
  bash scripts/target/acquire_codex_lock.sh "validation overlap" >/tmp/Diffmogger-lock-overlap.log 2>&1; then
    echo "Lock smoke failed: overlapping acquire unexpectedly succeeded" >&2
    rm -rf "$lock_smoke_dir"
    exit 1
fi

CODEX_LOCK_PATH="$lock_smoke_dir/target/codex_automation.lock" \
CODEX_RUN_ID="validation-smoke" \
bash scripts/target/release_codex_lock.sh >/tmp/Diffmogger-lock-release.log
rm -rf "$lock_smoke_dir"

tmp_dir="$(mktemp -d)"
python3 scripts/scaffold_project_docs.py --intake examples/generic-web-app/project_intake.md --target "$tmp_dir" >/tmp/Diffmogger-scaffold.log
python3 scripts/check_required_files.py --human-bridge-mode file_only --multi-role-enabled --optional-mcp-enabled "$tmp_dir" >/tmp/Diffmogger-check.log
if grep -R "POST http://127.0.0.1:8765/api/notify\\|NOTIFIER_UNREACHABLE\\|message_body\\|discord_notifier\\|DISCORD_" "$tmp_dir/.diffmogger/agentic" "$tmp_dir/.diffmogger/state" >/tmp/Diffmogger-file-only-grep.log 2>&1; then
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
if [ -f "$tmp_dir/.diffmogger/state/TICKET_RUN.md" ]; then
    echo "Default scaffold unexpectedly generated ticket campaign source" >&2
    rm -rf "$tmp_dir"
    exit 1
fi
python3 - "$tmp_dir" <<'PY'
import json
import sys
from pathlib import Path

target = Path(sys.argv[1])
manifest = json.loads((target / ".diffmogger/manifest.json").read_text(encoding="utf-8"))
aliases = manifest.get("path_aliases") if isinstance(manifest.get("path_aliases"), dict) else {}
legacy = {
    "docs/HUMAN_INBOX.md",
    "docs/HUMAN_OUTBOX.md",
    "docs/HUMAN_REQUESTS.md",
    "docs/HUMAN_RESPONSES_ARCHIVE.md",
    "docs/TICKET_RUN.md",
}
present = sorted(legacy & set(aliases))
if present:
    print(f"Default scaffold manifest still aliases removed Markdown queues: {present}", file=sys.stderr)
    raise SystemExit(1)
PY
for expected_mcp_path in \
    ".diffmogger/agentic/codex_config.toml" \
    ".diffmogger/state/MCP_INTEGRATIONS.md" \
    ".diffmogger/state/backlog/README.md" \
    ".diffmogger/scripts/run_playwright_mcp.sh"; do
    if [ ! -e "$tmp_dir/$expected_mcp_path" ]; then
        echo "Default scaffold missing enabled MCP file: $expected_mcp_path" >&2
        rm -rf "$tmp_dir"
        exit 1
    fi
done
python3 - "$tmp_dir" <<'PY'
import json
import sys
from pathlib import Path

target = Path(sys.argv[1])
intake = json.loads((target / ".diffmogger/agentic/project_intake.json").read_text(encoding="utf-8"))
manifest = json.loads((target / ".diffmogger/manifest.json").read_text(encoding="utf-8"))
expected = ["context7", "playwright"]
if intake.get("optional_mcp_servers") != expected:
    print(f"Default scaffold did not write all supported MCPs to intake: {intake.get('optional_mcp_servers')}", file=sys.stderr)
    raise SystemExit(1)
if manifest.get("optional_mcp_servers") != expected:
    print(f"Default scaffold did not write resolved MCPs to manifest: {manifest.get('optional_mcp_servers')}", file=sys.stderr)
    raise SystemExit(1)
PY
for marker in \
    "H2 Local-first demo" \
    "weekly board" \
    "Long-run direction" \
    "recurring review capsules" \
    "MCP decision: context7 used|skipped" \
    "npm run browser-smoke" \
    "## Improvement Backlog"; do
    if ! grep -R -- "$marker" "$tmp_dir/.diffmogger/agentic" "$tmp_dir/.diffmogger/state/CODEX_AUTOMATION_TASKS.md" >/tmp/Diffmogger-mode-horizon-grep.log 2>&1; then
        echo "Continuous-improvement scaffold missing mode-aware horizon marker: $marker" >&2
        cat /tmp/Diffmogger-mode-horizon-grep.log >&2
        rm -rf "$tmp_dir"
        exit 1
    fi
done
rm -rf "$tmp_dir"

tmp_dir="$(mktemp -d)"
tmp_intake="$(mktemp /tmp/Diffmogger-mcp-opt-out.XXXXXX)"
cat >"$tmp_intake" <<'JSON'
{
  "project_name": "MCP Opt Out Smoke",
  "product_goal": "Validate explicit MCP opt-out.",
  "target_user": "Automation tester.",
  "desired_first_demo": "Generated docs only.",
  "human_bridge_enabled": false,
  "human_bridge_mode": "disabled",
  "automation_role_profile": "planner_builder_hardener_integrator",
  "optional_mcp_servers": [],
  "verification_commands": ["npm test"]
}
JSON
python3 scripts/scaffold_project_docs.py --intake "$tmp_intake" --target "$tmp_dir" >/tmp/Diffmogger-scaffold-mcp-opt-out.log
python3 scripts/check_required_files.py --human-bridge-mode disabled --multi-role-enabled "$tmp_dir" >/tmp/Diffmogger-check-mcp-opt-out.log
for unexpected_mcp_path in \
    ".diffmogger/agentic/codex_config.toml" \
    ".diffmogger/state/MCP_INTEGRATIONS.md" \
    ".diffmogger/state/backlog/README.md" \
    ".diffmogger/scripts/run_playwright_mcp.sh"; do
    if [ -e "$tmp_dir/$unexpected_mcp_path" ]; then
        echo "Explicit optional_mcp_servers opt-out unexpectedly generated MCP file: $unexpected_mcp_path" >&2
        rm -rf "$tmp_dir" "$tmp_intake"
        exit 1
    fi
done
rm -rf "$tmp_dir" "$tmp_intake"

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
  "automation_role_profile": "planner_builder_hardener_integrator",
  "campaign_mode": "bounded",
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
for ignored_path in ".diffmogger/agentic/automation_prompt.md" ".diffmogger/state/CODEX_AUTOMATION_TASKS.md" ".diffmogger/scripts/run_role_automation.sh" ".diffmogger/runtime/agent_runs/run-1/summary.md" ".diffmogger/runtime/prisma-cache/node/cache-file" "target/validation_jobs/validation-job-test.log"; do
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
  "campaign_mode": "bounded",
  "ticket_completion_notify": true,
  "verification_commands": ["npm test"]
}
JSON
python3 scripts/scaffold_project_docs.py --intake "$tmp_intake" --target "$tmp_dir" >/tmp/Diffmogger-scaffold-ticket-campaign.log
python3 scripts/check_required_files.py --human-bridge-mode local_notifier --ticket-campaign-enabled "$tmp_dir" >/tmp/Diffmogger-check-ticket-campaign.log
if grep -Fx "npm test" "$tmp_dir/.diffmogger/agentic/verification_commands.txt" >/tmp/Diffmogger-ticket-campaign-verification-future.log 2>&1; then
    echo "Ticket-campaign scaffold put a future project command in the clean-HEAD baseline gate" >&2
    cat "$tmp_dir/.diffmogger/agentic/verification_commands.txt" >&2
    rm -rf "$tmp_dir" "$tmp_intake"
    exit 1
fi
for command in \
    "python3 .diffmogger/scripts/ticket_run.py . status --json" \
    "python3 .diffmogger/scripts/ticket_run.py . next --json" \
    "python3 -m py_compile .diffmogger/scripts/run_process_watchdog.py .diffmogger/scripts/ticket_run.py .diffmogger/scripts/compact_agent_state.py .diffmogger/scripts/run_observatory.py .diffmogger/scripts/repair_environment.py"; do
    if ! grep -Fx "$command" "$tmp_dir/.diffmogger/agentic/verification_commands.txt" >/tmp/Diffmogger-ticket-campaign-verification-grep.log 2>&1; then
            echo "Ticket-campaign scaffold missing baseline verification command: $command" >&2
        cat "$tmp_dir/.diffmogger/agentic/verification_commands.txt" >&2
        rm -rf "$tmp_dir" "$tmp_intake"
        exit 1
    fi
done
(
  cd "$tmp_dir"
  while IFS= read -r command; do
    command="${command#- }"
    case "$command" in
      ""|\#*) continue ;;
    esac
    /bin/bash -lc "$command"
  done < .diffmogger/agentic/verification_commands.txt
) >/tmp/Diffmogger-ticket-campaign-baseline.log 2>&1 || {
    echo "Ticket-campaign baseline verification commands did not pass" >&2
    cat /tmp/Diffmogger-ticket-campaign-baseline.log >&2
    rm -rf "$tmp_dir" "$tmp_intake"
    exit 1
}
if ! grep -R "Campaign mode: \`bounded\`\\|SQLite ticket queue\\|.diffmogger/scripts/ticket_run.py" "$tmp_dir/.diffmogger/agentic" "$tmp_dir/.diffmogger/state" "$tmp_dir/.diffmogger/scripts" >/tmp/Diffmogger-ticket-campaign-grep.log 2>&1; then
    echo "Ticket-campaign scaffold missing mode markers" >&2
    rm -rf "$tmp_dir" "$tmp_intake"
    exit 1
fi
for marker in \
    "T1 Ticket-run readiness" \
    "T4 Completion report and stop" \
    "Scaffold seeds and validates the ticket queue" \
    "python3 .diffmogger/scripts/ticket_run.py . next --json" \
    "let execution DAG dependencies, confidence, and ownership scopes determine" \
    "depends_on" \
    "## Deferred / Follow-Up Tickets"; do
    if ! grep -R -- "$marker" "$tmp_dir/.diffmogger/agentic" "$tmp_dir/.diffmogger/state/CODEX_AUTOMATION_TASKS.md" >/tmp/Diffmogger-ticket-horizon-grep.log 2>&1; then
        echo "Ticket-campaign scaffold missing ticket progression marker: $marker" >&2
        cat /tmp/Diffmogger-ticket-horizon-grep.log >&2
        rm -rf "$tmp_dir" "$tmp_intake"
        exit 1
    fi
done
if grep -R -E "MVP|Beyond MVP|Ambitious extensions" "$tmp_dir/.diffmogger/agentic/automation_prompt.md" "$tmp_dir/.diffmogger/state/CODEX_AUTOMATION_TASKS.md" >/tmp/Diffmogger-ticket-roadmap-language.log 2>&1; then
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
if ! grep -R "discord_notifier\\|event_kind\\|progress\\|message\\|POST http://127.0.0.1:8765/api/notify" "$tmp_dir/.diffmogger/agentic" "$tmp_dir/.diffmogger/state" >/tmp/Diffmogger-discord-notifier-grep.log 2>&1; then
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
  "max_write_worker_count": 25,
  "write_worker_guidance": "Use write workers only for planned disjoint modules.",
  "verification_commands": ["npm test"]
}
JSON
python3 scripts/scaffold_project_docs.py --intake "$tmp_intake" --target "$tmp_dir" >/tmp/Diffmogger-scaffold-write-workers.log
python3 scripts/check_required_files.py --human-bridge-mode disabled "$tmp_dir" >/tmp/Diffmogger-check-write-workers.log
for marker in \
    "Write-capable worker agents allowed: true" \
    "Max write worker count: 10" \
    "Worker strategy: READ_ONLY_REPORTS / WRITE_WORKERS / INTEGRATION_ONLY / NO_WORKERS" \
    "Parallelism budget:" \
    "--mode write" \
    "not alone in the codebase" \
    "blindly accepting changes"; do
    if ! grep -R -- "$marker" "$tmp_dir/.diffmogger/agentic" "$tmp_dir/.diffmogger/state" "$tmp_dir/.diffmogger/scripts/spawn_worker_agent.sh" >/tmp/Diffmogger-write-worker-grep.log 2>&1; then
        echo "Write-worker scaffold missing marker: $marker" >&2
        rm -rf "$tmp_dir" "$tmp_intake"
        exit 1
    fi
done
rm -rf "$tmp_dir" "$tmp_intake"

tmp_dir="$(mktemp -d)"
tmp_intake="$(mktemp /tmp/Diffmogger-optional-mcp.XXXXXX)"
cat >"$tmp_intake" <<'JSON'
{
  "project_name": "Optional MCP Smoke",
  "product_goal": "Build an optional MCP scaffold smoke target.",
  "target_user": "Automation tester.",
  "desired_first_demo": "Generated docs only.",
  "human_bridge_enabled": false,
  "human_bridge_mode": "disabled",
  "automation_role_profile": "planner_builder_hardener_integrator",
  "optional_mcp_servers": ["context7", "playwright"],
  "verification_commands": ["npm test"]
}
JSON
python3 scripts/scaffold_project_docs.py --intake "$tmp_intake" --target "$tmp_dir" >/tmp/Diffmogger-scaffold-optional-mcp.log
python3 scripts/check_required_files.py --human-bridge-mode disabled --multi-role-enabled --optional-mcp-enabled "$tmp_dir" >/tmp/Diffmogger-check-optional-mcp.log
for marker in \
    "[mcp_servers.context7]" \
    "@upstash/context7-mcp" \
    'env_vars = ["CONTEXT7_API_KEY"]' \
    "[mcp_servers.playwright]" \
    'disabled_tools = ["browser_run_code_unsafe", "browser_file_upload"]' \
    "[profiles.diffmogger-planner.mcp_servers.context7]" \
    "[profiles.diffmogger-hardener.mcp_servers.playwright]"; do
    if ! grep -F -- "$marker" "$tmp_dir/.diffmogger/agentic/codex_config.toml" >/tmp/Diffmogger-optional-mcp-config-grep.log 2>&1; then
        echo "Optional MCP config missing marker: $marker" >&2
        rm -rf "$tmp_dir" "$tmp_intake"
        exit 1
    fi
done
for marker in \
    'mcp_servers.context7.command="npx"' \
    'mcp_servers.context7.env_vars=["CONTEXT7_API_KEY"]' \
    'mcp_servers.playwright.command="bash"' \
    'mcp_servers.playwright.disabled_tools=["browser_run_code_unsafe","browser_file_upload"]' \
    "PLAYWRIGHT_MCP_OUTPUT_DIR" \
    "mcp_telemetry_path" \
    "mcp_requested_servers" \
    "mcp_mounted_servers" \
    "playwright_validation_status"; do
    if ! grep -F -- "$marker" "$tmp_dir/.diffmogger/scripts/run_role_automation.sh" >/tmp/Diffmogger-optional-mcp-runner-grep.log 2>&1; then
        echo "Optional MCP runner missing marker: $marker" >&2
        rm -rf "$tmp_dir" "$tmp_intake"
        exit 1
    fi
done
for marker in \
    "auth errors" \
    "browser_take_screenshot" \
    "docs/backlog/ui_artifacts/<run_id>/<issue-slug>.png" \
    "MCP decision: context7 used|skipped" \
    "npm run browser-smoke"; do
    if ! grep -R -- "$marker" "$tmp_dir/.diffmogger/agentic" "$tmp_dir/.diffmogger/state" >/tmp/Diffmogger-optional-mcp-prompt-grep.log 2>&1; then
        echo "Optional MCP prompt/docs missing marker: $marker" >&2
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
  "automation_role_profile": "planner_builder_hardener_integrator",
  "automation_checkpoint_commits": true,
  "verification_commands": ["test -f accepted.txt"]
}
JSON
python3 scripts/scaffold_project_docs.py --intake "$tmp_intake" --target "$tmp_dir" >/tmp/Diffmogger-scaffold-multi-role.log
python3 scripts/check_required_files.py --human-bridge-mode disabled --multi-role-enabled "$tmp_dir" >/tmp/Diffmogger-check-multi-role.log
if test -e "$tmp_dir/.diffmogger/scripts/update_automation_signals.py" || test -e "$tmp_dir/.diffmogger/state/AUTOMATION_SIGNALS.md"; then
    echo "Multi-role scaffold generated retired automation signal files" >&2
    find "$tmp_dir/.diffmogger" -name '*AUTOMATION_SIGNALS*' -o -name 'update_automation_signals.py' >&2
    rm -rf "$tmp_dir" "$tmp_intake"
    exit 1
fi
if find "$tmp_dir/.diffmogger/state" -maxdepth 1 -name 'HUMAN*' | grep . >/tmp/Diffmogger-multi-role-human-files.log; then
    echo "Disabled human bridge multi-role scaffold unexpectedly generated human bridge files" >&2
    cat /tmp/Diffmogger-multi-role-human-files.log >&2
    rm -rf "$tmp_dir" "$tmp_intake"
    exit 1
fi
(
  cd "$tmp_dir"
  git config user.name "Diffmogger Validation"
  git config user.email "diffmogger-validation@example.invalid"
  git rev-parse --verify HEAD >/tmp/Diffmogger-multi-role-initial-commit.log
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
queue_root="$tmp_dir/.diffmogger/runtime/automation_queue"
lock_path="$tmp_dir/.diffmogger/runtime/codex_automation.lock"
mkdir -p "$queue_root/builder/run-001"
mv "$tmp_dir/target_patch.diff" "$queue_root/builder/run-001/changes.patch"
base_commit="$(git -C "$tmp_dir" rev-parse HEAD)"
cat >"$queue_root/builder/run-001/manifest.json" <<JSON
{
  "role": "builder",
  "run_id": "run-001",
  "base_commit": "$base_commit",
  "head_before_integration": null,
  "status": "queued",
  "deferral_reason": null,
  "deferral_detail": "",
  "patch_path": ".diffmogger/runtime/automation_queue/builder/run-001/changes.patch",
  "changed_files": ["accepted.txt"],
  "checks_run": [],
  "summary": "Commit type: chore\\nCommit scope: smoke\\nCommit subject: create accepted smoke file\\n\\n## Summary\\n- Create accepted smoke file.",
  "created_at": "2026-05-02T00:00:00+00:00",
  "integrated_at": null,
  "checkpoint_commit": null,
  "accepted_commit": null
}
JSON
python3 scripts/runtime/integrate_role_outputs.py "$tmp_dir" --run-id validation-integrator >/tmp/Diffmogger-integrator-smoke.log
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
mkdir -p "$queue_root/builder/run-stale"
mv "$tmp_dir/stale_patch.diff" "$queue_root/builder/run-stale/changes.patch"
cat >"$queue_root/builder/run-stale/manifest.json" <<JSON
{
  "role": "builder",
  "run_id": "run-stale",
  "base_commit": "$stale_base",
  "head_before_integration": null,
  "status": "queued",
  "deferral_reason": null,
  "deferral_detail": "",
  "patch_path": ".diffmogger/runtime/automation_queue/builder/run-stale/changes.patch",
  "changed_files": ["stale.txt"],
  "checks_run": [],
  "summary": "Stale patch smoke.",
  "created_at": "2026-05-02T00:01:00+00:00",
  "integrated_at": null,
  "checkpoint_commit": null,
  "accepted_commit": null
}
JSON
python3 scripts/runtime/integrate_role_outputs.py "$tmp_dir" --run-id validation-stale >/tmp/Diffmogger-stale-integrator.log
if ! grep '"deferral_reason": "conflict"' "$queue_root/builder/run-stale/manifest.json" >/tmp/Diffmogger-stale-reason.log; then
    echo "Integrator stale patch smoke did not classify true add/add conflict" >&2
    cat "$queue_root/builder/run-stale/manifest.json" >&2
    rm -rf "$tmp_dir" "$tmp_intake"
    exit 1
fi
if ! grep '"integration_resolution": "true_conflict"' "$queue_root/builder/run-stale/manifest.json" >/tmp/Diffmogger-stale-resolution.log; then
    echo "Integrator stale patch smoke did not record true_conflict resolution" >&2
    cat "$queue_root/builder/run-stale/manifest.json" >&2
    rm -rf "$tmp_dir" "$tmp_intake"
    exit 1
fi
python3 scripts/runtime/list_deferred_patches.py "$tmp_dir" --pretty >/tmp/Diffmogger-deferred-list.log
python3 scripts/runtime/list_deferred_patches.py "$tmp_dir" --markdown >/tmp/Diffmogger-deferred-list.md
python3 scripts/runtime/list_deferred_patches.py "$tmp_dir" --decision-template >/tmp/Diffmogger-deferred-decision-template.md
if ! grep 'recommended_next_action: Start with `conflict`' /tmp/Diffmogger-deferred-list.md >/tmp/Diffmogger-deferred-markdown.log; then
    echo "Deferred patch Markdown triage smoke did not recommend conflict first" >&2
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
CODEX_LOCK_PATH="$lock_path" \
CODEX_RUN_ID="held-lock" \
bash "$tmp_dir/.diffmogger/scripts/acquire_codex_lock.sh" "validation held lock" >/tmp/Diffmogger-integrator-held-lock-acquire.log
if python3 scripts/runtime/integrate_role_outputs.py "$tmp_dir" --run-id blocked-by-lock >/tmp/Diffmogger-integrator-lock-refusal.log 2>&1; then
    echo "Integrator lock guard failed: run unexpectedly succeeded while lock was held" >&2
    rm -rf "$tmp_dir" "$tmp_intake"
    exit 1
fi
CODEX_LOCK_PATH="$lock_path" \
CODEX_RUN_ID="held-lock" \
bash "$tmp_dir/.diffmogger/scripts/release_codex_lock.sh" >/tmp/Diffmogger-integrator-held-lock-release.log
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
if env -u MULTI_ROLE_ALLOW_REMOTES PATH="$fake_git_dir:$PATH" python3 scripts/runtime/integrate_role_outputs.py "$tmp_dir" --dry-run >/tmp/Diffmogger-remote-guard.log 2>&1; then
    echo "Integrator remote guard failed: run unexpectedly succeeded with remote configured" >&2
    rm -rf "$tmp_dir" "$tmp_intake" "$fake_git_dir"
    exit 1
fi
PATH="$fake_git_dir:$PATH" MULTI_ROLE_ALLOW_REMOTES=1 python3 scripts/runtime/integrate_role_outputs.py "$tmp_dir" --dry-run >/tmp/Diffmogger-remote-opt-in.log
cat >"$tmp_dir/.git/hooks/pre-commit" <<'SH'
#!/usr/bin/env sh
git push
SH
chmod +x "$tmp_dir/.git/hooks/pre-commit"
if PATH="$fake_git_dir:$PATH" MULTI_ROLE_ALLOW_REMOTES=1 python3 scripts/runtime/integrate_role_outputs.py "$tmp_dir" --dry-run >/tmp/Diffmogger-hook-guard.log 2>&1; then
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
spec = importlib.util.spec_from_file_location("integrate_role_outputs", Path("scripts/runtime/integrate_role_outputs.py"))
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
spec = importlib.util.spec_from_file_location("repair_environment", Path("scripts/runtime/repair_environment.py"))
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
spec = importlib.util.spec_from_file_location("integrate_role_outputs", Path("scripts/runtime/integrate_role_outputs.py"))
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
spec = importlib.util.spec_from_file_location("run_conveyor_automation", Path("scripts/runtime/run_conveyor_automation.py"))
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)
from contextlib import closing
from diffmogger.runtime.state_store import (
    connect,
    database_path_for_target,
    execution_dag_read_model,
    latest_scheduler_decision_conn,
    stable_json,
    upsert_execution_dag_node,
)

(target / "src").mkdir(parents=True)
(target / "src/app.py").write_text("VALUE = 1\n", encoding="utf-8")
with closing(connect(database_path_for_target(target))) as conn:
    with conn:
        upsert_execution_dag_node(
            conn,
            node_id="dag-node:validation-smoke:build",
            task_id="T1",
            action_type="building",
            status="ready",
            owner_role="builder",
            confidence=0.9,
            metadata={
                "source": "validation.dag_scheduler_smoke",
                "summary": "Update src/app.py",
                "paths": ["src/app.py"],
            },
        )

role, reason, stop = module.choose_next(target, {"last_completed_role": "integrator"}, 2)
with closing(connect(database_path_for_target(target))) as conn:
    decision = latest_scheduler_decision_conn(conn)
candidate = decision["selected_candidate"]
if role != "builder" or candidate.get("action_kind") != "launch_write_group" or stop:
    print(("dag-write-launch", role, reason, stop, candidate), file=sys.stderr)
    raise SystemExit(1)
if decision.get("scheduler_fallback_used") or decision.get("legacy_result"):
    print(("legacy-fallback-used", decision), file=sys.stderr)
    raise SystemExit(1)

(target / "target/automation_queue/planner/run-queued").mkdir(parents=True)
(target / "target/automation_queue/planner/run-queued/manifest.json").write_text(
    '{"role":"planner","run_id":"run-queued","status":"queued"}\n',
    encoding="utf-8",
)
role, reason, stop = module.choose_next(target, {"last_completed_role": "hardener"}, 2)
with closing(connect(database_path_for_target(target))) as conn:
    decision = latest_scheduler_decision_conn(conn)
if role != "builder" or decision["selected_candidate"].get("action_kind") != "launch_write_group" or stop:
    print(("legacy-queue-preempted-dag", role, reason, stop, decision["selected_candidate"]), file=sys.stderr)
    raise SystemExit(1)

with closing(connect(database_path_for_target(target))) as conn:
    with conn:
        upsert_execution_dag_node(
            conn,
            node_id="dag-node:validation-smoke:build",
            task_id="T1",
            action_type="building",
            status="done",
            owner_role="builder",
            confidence=0.9,
            metadata={
                "source": "validation.dag_scheduler_smoke",
                "summary": "Update src/app.py",
                "paths": ["src/app.py"],
            },
        )

state = {
    "schema_version": 1,
    "cycles": 3,
    "last_completed_role": "builder",
    "integrator_no_progress": {
        "active": True,
        "streak": 2,
        "threshold": 2,
        "reason": "legacy no-progress smoke",
    },
}
role, reason, stop = module.choose_next(target, state, 2)
queue = module.conveyor_decision_queue(target, state, role, reason, 2)
with closing(connect(database_path_for_target(target))) as conn:
    decision = latest_scheduler_decision_conn(conn)
    model = execution_dag_read_model(conn)
if role is not None or "no DAG-ready scheduler action" not in reason or stop:
    print(("idle-without-dag-work", role, reason, stop), file=sys.stderr)
    raise SystemExit(1)
if decision["selected_candidate"].get("action_kind") != "idle" or queue[0].get("action_kind") != "idle":
    print(("idle-candidate-missing", decision["selected_candidate"], queue), file=sys.stderr)
    raise SystemExit(1)
if not any(item.get("action_type") == "building" and item.get("status") == "done" for item in model["terminal_nodes"]):
    print(("done-dag-node-missing", model), file=sys.stderr)
    raise SystemExit(1)

with closing(connect(database_path_for_target(target))) as conn:
    with conn:
        conn.execute(
            """
            INSERT INTO validation_jobs(
                job_id, execution_group_id, plan_id, gate_id, command, cwd,
                status, started_at, finished_at, exit_code, log_artifact_id,
                resource_profile, payload_json
            )
            VALUES('validation-job:smoke', 'execution-group:validation-smoke', 'validation-plan:smoke',
                   'T1', 'python -m pytest', '', 'failed', '2026-05-15T00:00:00+00:00',
                   '2026-05-15T00:00:01+00:00', 1, 'log:validation-job:smoke', 'cpu', ?)
            """,
            (stable_json({"required": True}),),
        )
role, reason, stop = module.choose_next(target, state, 2)
with closing(connect(database_path_for_target(target))) as conn:
    decision = latest_scheduler_decision_conn(conn)
if role != "builder" or decision["selected_candidate"].get("action_kind") != "create_repair_nodes" or stop:
    print(("validation-repair-action-missing", role, reason, stop, decision["selected_candidate"]), file=sys.stderr)
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
(target / "target/automation_queue/planner/run-stale").mkdir(parents=True)
(target / "target/automation_queue/planner/run-stale/manifest.json").write_text(
    json.dumps(
        {
            "role": "planner",
            "run_id": "run-stale",
            "status": "deferred",
            "summary": "Patch base no longer matches HEAD.",
            "deferral_reason": "staleness",
            "deferral_detail": "Patch base no longer matches HEAD.",
            "changed_files": ["docs/CODEX_AUTOMATION_TASKS.md"],
            "created_at": "2026-05-03T00:00:30+00:00",
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
python3 scripts/runtime/run_observatory.py --target "$tmp_dir" --once --output "$tmp_dir/target/observatory/index.html" >/tmp/Diffmogger-observatory-render.log
for marker in "Diffmogger Observatory" "Activity Lanes" "First Review / Runtime State" "run-observe" "builder" "Runtime Health" "First review" "Scorecard" "Action Plan" "Integration safety" "Run integrator triage" "Accepted patches" "Deferred triage" "Start with \`staleness\`" "Next-Run Worker Strategy" "INTEGRATION_ONLY" "NO-PROGRESS CIRCUIT" "staleness:no_detail" "Recent Outcomes" "run-skipped" "skipped"; do
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
  bash "$kit_root/scripts/target/run_role_automation.sh" --target "$tmp_dir" --role builder >/tmp/Diffmogger-role-context.log
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
  bash "$kit_root/scripts/target/run_role_automation.sh" --target "$tmp_dir" --role builder >/tmp/Diffmogger-role-skipped.log
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
if find "$tmp_dir/.diffmogger/state" -maxdepth 1 -name 'HUMAN*' | grep . >/tmp/Diffmogger-disabled-human-files.log; then
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
