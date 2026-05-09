#!/usr/bin/env python3
"""Check that a target project has the required agentic automation files."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from diffmogger.runtime.paths import (
    MANIFEST_REL,
    existing_or_target_path,
    load_manifest,
    manifest_list,
    sidecar_enabled,
    sidecarize_text,
    target_rel,
)


BASE_REQUIRED = [
    "AGENTS.md",
    ".agentic/automation_prompt.md",
    ".agentic/verification_commands.txt",
    ".agentic/smoke_commands.txt",
    "scripts/acquire_codex_lock.sh",
    "scripts/release_codex_lock.sh",
    "scripts/run_codex_automation.sh",
    "scripts/run_process_watchdog.py",
    "scripts/run_conveyor_automation.py",
    "scripts/run_conveyor_automation.sh",
    "scripts/run_observatory.py",
    "scripts/build_replay.py",
    "scripts/diffmogger_browser.py",
    "scripts/load_automation_env.py",
    "scripts/ticket_run.py",
    "scripts/repair_environment.py",
    "scripts/spawn_worker_agent.sh",
    "scripts/summarize_worker_outputs.py",
    "scripts/compact_agent_state.py",
    "docs/INITIAL_BOOTSTRAP_PROMPT.md",
    "docs/DEVELOPMENT.md",
    "docs/PROJECT_CONTEXT.md",
    "docs/CODEX_AUTOMATION_TASKS.md",
    "docs/CODEX_AUTOMATION_GUARDRAILS.md",
    "docs/AUTONOMY_EXPERIMENT_LOG.md",
    "docs/DAILY_AUTOMATION_REVIEW.md",
]

TICKET_CAMPAIGN_REQUIRED = [
    "docs/TICKET_RUN.md",
]

HUMAN_REQUIRED = [
    "docs/HUMAN_REQUESTS.md",
    "docs/HUMAN_INBOX.md",
    "docs/HUMAN_OUTBOX.md",
    "docs/HUMAN_RESPONSES_ARCHIVE.md",
    "docs/HUMAN_BRIDGE_SETUP.md",
]

MULTI_ROLE_REQUIRED = [
    ".agentic/roles/planner.md",
    ".agentic/roles/builder.md",
    ".agentic/roles/hardener.md",
    ".agentic/roles/integrator.md",
    "docs/MULTI_ROLE_PROGRESS.md",
    "scripts/run_role_automation.sh",
    "scripts/integrate_role_outputs.py",
    "scripts/list_deferred_patches.py",
]

MCP_REQUIRED = [
    ".codex/config.toml",
    "docs/MCP_INTEGRATIONS.md",
]

PLAYWRIGHT_MCP_REQUIRED = [
    "scripts/run_playwright_mcp.sh",
    "docs/backlog/README.md",
]

RUNTIME_LIBRARY_REQUIRED = [
    ".diffmogger/lib/diffmogger/__init__.py",
    ".diffmogger/lib/diffmogger/conveyor/__init__.py",
    ".diffmogger/lib/diffmogger/conveyor/active_role.py",
    ".diffmogger/lib/diffmogger/conveyor/baseline.py",
    ".diffmogger/lib/diffmogger/conveyor/cli.py",
    ".diffmogger/lib/diffmogger/conveyor/decisions.py",
    ".diffmogger/lib/diffmogger/conveyor/locks.py",
    ".diffmogger/lib/diffmogger/conveyor/progress.py",
    ".diffmogger/lib/diffmogger/conveyor/queue_state.py",
    ".diffmogger/lib/diffmogger/conveyor/runner.py",
    ".diffmogger/lib/diffmogger/conveyor/state.py",
    ".diffmogger/lib/diffmogger/conveyor/tickets.py",
    ".diffmogger/lib/diffmogger/integrator/__init__.py",
    ".diffmogger/lib/diffmogger/integrator/baseline.py",
    ".diffmogger/lib/diffmogger/integrator/cleanup.py",
    ".diffmogger/lib/diffmogger/integrator/cli.py",
    ".diffmogger/lib/diffmogger/integrator/commits.py",
    ".diffmogger/lib/diffmogger/integrator/common.py",
    ".diffmogger/lib/diffmogger/integrator/git_safety.py",
    ".diffmogger/lib/diffmogger/integrator/locks.py",
    ".diffmogger/lib/diffmogger/integrator/notifier.py",
    ".diffmogger/lib/diffmogger/integrator/patching.py",
    ".diffmogger/lib/diffmogger/integrator/progress.py",
    ".diffmogger/lib/diffmogger/integrator/queue.py",
    ".diffmogger/lib/diffmogger/integrator/runtime_state.py",
    ".diffmogger/lib/diffmogger/integrator/verification.py",
    ".diffmogger/lib/diffmogger/observatory/__init__.py",
    ".diffmogger/lib/diffmogger/observatory/cli.py",
    ".diffmogger/lib/diffmogger/observatory/common.py",
    ".diffmogger/lib/diffmogger/observatory/git_state.py",
    ".diffmogger/lib/diffmogger/observatory/html_render.py",
    ".diffmogger/lib/diffmogger/observatory/markdown_render.py",
    ".diffmogger/lib/diffmogger/observatory/queue_state.py",
    ".diffmogger/lib/diffmogger/observatory/scoring.py",
    ".diffmogger/lib/diffmogger/observatory/self_review.py",
    ".diffmogger/lib/diffmogger/observatory/server.py",
    ".diffmogger/lib/diffmogger/observatory/signals.py",
    ".diffmogger/lib/diffmogger/observatory/snapshots.py",
    ".diffmogger/lib/diffmogger/runtime/__init__.py",
    ".diffmogger/lib/diffmogger/runtime/paths.py",
    ".diffmogger/lib/diffmogger/runtime/build_replay.py",
    ".diffmogger/lib/diffmogger/runtime/compact_agent_state.py",
    ".diffmogger/lib/diffmogger/runtime/diffmogger_browser.py",
    ".diffmogger/lib/diffmogger/runtime/integrate_role_outputs.py",
    ".diffmogger/lib/diffmogger/runtime/list_deferred_patches.py",
    ".diffmogger/lib/diffmogger/runtime/load_automation_env.py",
    ".diffmogger/lib/diffmogger/runtime/repair_environment.py",
    ".diffmogger/lib/diffmogger/runtime/run_conveyor_automation.py",
    ".diffmogger/lib/diffmogger/runtime/run_observatory.py",
    ".diffmogger/lib/diffmogger/runtime/run_process_watchdog.py",
    ".diffmogger/lib/diffmogger/runtime/summarize_worker_outputs.py",
    ".diffmogger/lib/diffmogger/runtime/ticket_run.py",
]

RUNTIME_MARKER_SOURCES = {
    "scripts/build_replay.py": ".diffmogger/lib/diffmogger/runtime/build_replay.py",
    "scripts/compact_agent_state.py": ".diffmogger/lib/diffmogger/runtime/compact_agent_state.py",
    "scripts/diffmogger_browser.py": ".diffmogger/lib/diffmogger/runtime/diffmogger_browser.py",
    "scripts/integrate_role_outputs.py": ".diffmogger/lib/diffmogger/runtime/integrate_role_outputs.py",
    "scripts/list_deferred_patches.py": ".diffmogger/lib/diffmogger/runtime/list_deferred_patches.py",
    "scripts/load_automation_env.py": ".diffmogger/lib/diffmogger/runtime/load_automation_env.py",
    "scripts/repair_environment.py": ".diffmogger/lib/diffmogger/runtime/repair_environment.py",
    "scripts/run_conveyor_automation.py": ".diffmogger/lib/diffmogger/runtime/run_conveyor_automation.py",
    "scripts/run_observatory.py": ".diffmogger/lib/diffmogger/runtime/run_observatory.py",
    "scripts/run_process_watchdog.py": ".diffmogger/lib/diffmogger/runtime/run_process_watchdog.py",
    "scripts/summarize_worker_outputs.py": ".diffmogger/lib/diffmogger/runtime/summarize_worker_outputs.py",
    "scripts/ticket_run.py": ".diffmogger/lib/diffmogger/runtime/ticket_run.py",
}

TASK_REQUIRED_STRINGS = [
    "AUTOMATION_STATUS:",
    "## Current Project State",
    "## Automation Must Never Do",
    "## Product Horizon State",
    "## Horizon Transition Log",
    "## Completed Last Run",
    "## Checks From Last Run",
    "## Worker-Agent Activity",
    "Parallelism budget:",
    "## Known Issues",
    "## Pending Human Requests",
    "## Human Messages Sent",
    "## Best Next Milestone",
    "## Suggested Next Sprint-Sized Task",
    "## Continue/Block/Critical-Stop Rationale",
]

TASK_BACKLOG_HEADINGS = [
    "## Improvement Backlog",
    "## Deferred / Follow-Up Tickets",
    "## Ambitious Ideas Backlog",
]

DEVELOPMENT_REQUIRED_STRINGS = [
    "First Review Checklist",
    "bash scripts/validate_starter_kit.sh",
    "python3 .diffmogger/scripts/diffmogger_browser.py doctor --launch",
    "python3 .diffmogger/scripts/ticket_run.py . status --json",
    "Run Safety Check",
    "python3 .diffmogger/scripts/run_observatory.py --target . --review-dir /tmp/Diffmogger-review",
    "Diffmogger-observatory.html",
    "Diffmogger-self-review.md",
    "Automation Environment Loading",
    "CODEX_AUTOMATION_ENV_FILES",
    "CODEX_AUTOMATION_ENV_DENYLIST",
]

AUTOMATION_REQUIRED_STRINGS = [
    "CODEX_LOCK_ALREADY_ACQUIRED=true",
    ".diffmogger/scripts/run_codex_automation.sh",
    ".diffmogger/scripts/acquire_codex_lock.sh",
    ".diffmogger/scripts/release_codex_lock.sh",
    ".diffmogger/scripts/spawn_worker_agent.sh",
    ".diffmogger/scripts/summarize_worker_outputs.py",
    "Codex CLI worker decision: USE / SKIP / UNAVAILABLE",
    "command -v codex",
    "--dangerously-bypass-approvals-and-sandbox",
    "ACTIVE_WITH_PENDING_USER_INPUT",
    "BLOCKED_ON_USER",
    "ticket_campaign",
    ".diffmogger/scripts/ticket_run.py",
]

RUNNER_REQUIRED_STRINGS = [
    "CODEX_LOCK_ALREADY_ACQUIRED",
    "CODEX_LOCK_CONTEXT",
    "CODEX_NESTED_CLI_HOME",
    "load_automation_env.py",
    "CODEX_AUTOMATION_ENV_LOADED",
    "diffmogger_browser.py",
    "DIFFMOGGER_BROWSER_PATH",
    "PLAYWRIGHT_MCP_EXECUTABLE_PATH",
    "PLAYWRIGHT_MCP_OUTPUT_DIR",
    "mcp_servers.context7.command",
    "mcp_servers.context7.env_vars",
    "mcp_servers.playwright.command",
    "mcp_servers.playwright.disabled_tools",
    "--add-dir",
    "$HOME/.codex",
    "codex exec --full-auto",
    "--skip-git-repo-check",
    "repair_environment.py",
    "ticket_run.py",
    "child_pid",
    "forward_signal",
    "run_process_watchdog.py",
]

RUNNER_FORBIDDEN_STRINGS = [
    "Diffmogger Self Improvement scheduled sprint",
]

CONVEYOR_REQUIRED_STRINGS = [
    "automation_conveyor.lock",
    "automation_conveyor_state.json",
    "queued role patch",
    "run_role_automation.sh",
    "run_codex_automation.sh",
    "MULTI_ROLE_ALLOW_REMOTES",
    "active_role_run",
    "CODEX_ROLE_TIMEOUT_SECONDS",
    "role_timeout_streaks",
    "decision_queue",
    "planner deferred patch resolved",
    "ticket campaign complete",
    "ticket campaign blocked",
]

OBSERVATORY_REQUIRED_STRINGS = [
    "Diffmogger Observatory",
    "automation_conveyor_state.json",
    "automation_runner.json",
    "automation_queue",
    "ThreadingHTTPServer",
    "--open",
    "--review-output",
    "--review-dir",
    "Self Review",
    "Scorecard",
    "Action Plan",
    "Integration Safety",
    "First Review Readiness",
    "Action Plan",
]

WORKER_HELPER_REQUIRED_STRINGS = [
    "--disable plugins",
    "--ephemeral",
    "--dangerously-bypass-approvals-and-sandbox",
    "-C \"$target_abs\"",
]

BROWSER_HELPER_REQUIRED_STRINGS = [
    "chrome-headless-shell@stable",
    "@puppeteer/browsers",
    "DIFFMOGGER_BROWSER_PATH",
    "CHROME_PATH",
    "DIFFMOGGER_BROWSER_CACHE",
    "DevTools listening on",
]

TICKET_HELPER_REQUIRED_STRINGS = [
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
]

TICKET_RUN_REQUIRED_STRINGS = [
    "json ticket-run",
    "depends_on",
    "next --json",
    "halt_when_complete",
    "notify_on_complete",
    "candidate_done",
    "target/ticket_run_reports",
]

WRITE_WORKER_AUTOMATION_REQUIRED_STRINGS = [
    "Worker strategy: READ_ONLY_REPORTS / WRITE_WORKERS / INTEGRATION_ONLY / NO_WORKERS",
    "Parallelism budget:",
    "Write-capable worker agents allowed: true",
    "Max write worker count:",
    "--mode write",
    "not alone in the codebase",
    "blindly accepting changes",
]

WRITE_WORKER_HELPER_REQUIRED_STRINGS = [
    "--mode",
    "--ownership",
    "You are not alone in the codebase.",
    "files changed",
    "checks run",
]

FILE_ONLY_AUTOMATION_REQUIRED_STRINGS = [
    "Human bridge mode: `file_only`",
    "docs/HUMAN_INBOX.md",
    "Remove handled",
    "docs/HUMAN_RESPONSES_ARCHIVE.md",
    "docs/HUMAN_REQUESTS.md",
    "Do not use Discord or notifier APIs",
]

LOCAL_NOTIFIER_AUTOMATION_REQUIRED_STRINGS = [
    "Human bridge mode: `local_notifier`",
    "POST http://127.0.0.1:8765/api/notify",
    "docs/HUMAN_INBOX.md",
    "Remove handled",
    "docs/HUMAN_RESPONSES_ARCHIVE.md",
    "docs/HUMAN_OUTBOX.md",
    "NOTIFIER_UNREACHABLE",
    "message_body",
    "event_kind",
    "desktop notifications",
]

DISCORD_NOTIFIER_AUTOMATION_REQUIRED_STRINGS = [
    "Human bridge mode: `discord_notifier`",
    "POST http://127.0.0.1:8765/api/notify",
    "event_kind",
    "progress",
    "message",
    "Local automation commits trigger",
    "docs/HUMAN_INBOX.md",
    "docs/HUMAN_OUTBOX.md",
    "NOTIFIER_UNREACHABLE",
]

MULTI_ROLE_AUTOMATION_REQUIRED_STRINGS = [
    "Multi-role automations allowed: true",
    "Role profile: `planner_builder_hardener_integrator`",
    "Continuous conveyor",
    "target/automation_worktrees",
    "target/automation_queue",
    "docs/MULTI_ROLE_PROGRESS.md",
    "CRITICAL_STOP",
]

MULTI_ROLE_GUARDRAIL_REQUIRED_STRINGS = [
    "Multi-role automation is enabled",
    "MULTI_ROLE_ALLOW_REMOTES=1",
    "checkpoint dirty main changes as-is",
    "machine-readable deferral reasons",
]

MULTI_ROLE_PROGRESS_REQUIRED_STRINGS = [
    "## Project State At Last Integration",
    "## Cumulative Metrics",
    "## Recent Activity Log",
    "## Historical Summary",
    "## Deferred-Patch Backlog",
    "## Architectural Decisions",
    "## Role Health",
    "fast-follow replanning",
]

ROLE_PROMPT_REQUIRED_STRINGS = [
    "NEVER push to a remote",
    "NEVER configure a remote",
    "NEVER set up upstream tracking",
    "CRITICAL_STOP",
    "docs/MULTI_ROLE_PROGRESS.md",
]

QUEUE_ROLE_PROMPT_REQUIRED_STRINGS = [
    "Commit subject:",
    "Do not use generic subjects",
]

RUN_ROLE_REQUIRED_STRINGS = [
    "--role",
    "MULTI_ROLE_ALLOW_REMOTES",
    "diffmogger_browser.py",
    "DIFFMOGGER_BROWSER_PATH",
    "PLAYWRIGHT_MCP_EXECUTABLE_PATH",
    "PLAYWRIGHT_MCP_OUTPUT_DIR",
    "mcp_servers.context7.command",
    "mcp_servers.context7.env_vars",
    "mcp_servers.playwright.command",
    "mcp_servers.playwright.disabled_tools",
    "git remote -v",
    "git worktree add",
    "git ls-files --others --exclude-standard -z",
    "git add -N",
    "CRITICAL_STOP",
    "repair_environment.py",
    "manifest.json",
    "automation_worktrees",
    "automation_queue",
    "Runtime Summary Contract",
    "Commit subject:",
    "run_process_watchdog.py",
]

WATCHDOG_REQUIRED_STRINGS = [
    "CODEX_ROLE_TIMEOUT_SECONDS",
    "CODEX_ROLE_TERMINATION_GRACE_SECONDS",
    "DEFAULT_TIMEOUT_SECONDS = 5400",
    "TIMEOUT_EXIT_CODE = 124",
    "start_new_session=True",
    "os.killpg",
    "timed_out",
    "idle_timed_out",
]

INTEGRATOR_REQUIRED_STRINGS = [
    "git apply",
    "--check",
    "deferral_reason",
    "staleness",
    "MULTI_ROLE_ALLOW_REMOTES",
    "git push",
    "hooks",
    "semantic_commit_message",
    "parse_commit_intent",
    "semantic_changed_files",
    "notify_commit_progress",
    "automation_commit_progress",
    "chore(integrator): checkpoint preexisting local changes",
    "repair_environment.py",
    "worktree",
    "prune",
]

DEFERRED_HELPER_REQUIRED_STRINGS = [
    "deferral_reason",
    "status",
    "deferred",
    "--pretty",
    "--markdown",
    "--decision-template",
]

MCP_CONFIG_REQUIRED_STRINGS = [
    "Diffmogger optional MCP configuration",
    "mcp_servers.context7",
    "mcp_servers.playwright",
    "env_vars = [\"CONTEXT7_API_KEY\"]",
    "enabled = false",
    "required = false",
    "profiles.diffmogger-planner",
    "profiles.diffmogger-builder",
    "profiles.diffmogger-hardener",
    "disabled_tools = [\"browser_run_code_unsafe\", \"browser_file_upload\"]",
]

MCP_DOC_REQUIRED_STRINGS = [
    "Optional MCP servers enabled",
    "Context7",
    "Playwright MCP",
    "CONTEXT7_API_KEY",
    "auth errors",
    "Diffmogger never runs `codex mcp add`, `codex mcp login`, or mutates user/global Codex config",
]

PLAYWRIGHT_MCP_HELPER_REQUIRED_STRINGS = [
    "@playwright/mcp@latest",
    "--headless",
    "--isolated",
    "--codegen",
    "--output-dir",
    "PLAYWRIGHT_MCP_EXECUTABLE_PATH",
    "docs/backlog/ui_artifacts",
]


def check_file(path: Path) -> str | None:
    if not path.exists():
        return "missing"
    if not path.is_file():
        return "not a file"
    if not path.read_text(encoding="utf-8").strip():
        return "empty"
    return None




def has_marker(text: str, marker: str) -> bool:
    return marker in text or sidecarize_text(marker) in text or marker.replace("scripts/", ".diffmogger/scripts/") in text

def rel_label(root: Path, legacy_rel: str) -> str:
    return target_rel(root, legacy_rel) if sidecar_enabled(root) else legacy_rel


def rel_path(root: Path, legacy_rel: str) -> Path:
    return existing_or_target_path(root, legacy_rel)


def marker_source_path(root: Path, legacy_rel: str) -> Path:
    runtime_rel = RUNTIME_MARKER_SOURCES.get(legacy_rel)
    if sidecar_enabled(root) and runtime_rel:
        runtime_path = root / runtime_rel
        if runtime_path.exists():
            return runtime_path
    return rel_path(root, legacy_rel)


def project_intake(root: Path) -> dict[str, object]:
    path = rel_path(root, ".agentic/project_intake.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def optional_mcp_servers(root: Path) -> list[str]:
    raw = project_intake(root).get("optional_mcp_servers")
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else re.split(r"[\n,]+", str(raw))
    enabled: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = re.sub(r"^[-*]\s+", "", str(item).strip().lower()).replace("-", "_").replace(" ", "_")
        names: list[str] = []
        if "context7" in normalized:
            names.append("context7")
        if "playwright" in normalized:
            names.append("playwright")
        for name in names:
            if name not in seen:
                seen.add(name)
                enabled.append(name)
    return enabled


def inferred_human_bridge_mode(root: Path) -> str:
    intake_mode = str(project_intake(root).get("human_bridge_mode") or "").strip()
    if intake_mode:
        return intake_mode
    for rel in [".agentic/automation_prompt.md", "docs/CODEX_AUTOMATION_TASKS.md"]:
        try:
            text = rel_path(root, rel).read_text(encoding="utf-8")
        except OSError:
            continue
        for mode in ["disabled", "file_only", "local_notifier", "discord_notifier"]:
            if f"Human bridge mode: `{mode}`" in text:
                return mode
    return "file_only"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", default=".", help="Target project directory")
    parser.add_argument(
        "--no-human-bridge",
        action="store_true",
        help="Do not require HUMAN_* bridge files",
    )
    parser.add_argument(
        "--human-bridge-mode",
        choices=["file_only", "local_notifier", "discord_notifier", "disabled"],
        default=None,
        help="Validate mode-specific human bridge markers.",
    )
    parser.add_argument(
        "--write-workers-enabled",
        action="store_true",
        help="Validate write-worker markers for targets whose intake explicitly enabled bounded write workers.",
    )
    parser.add_argument(
        "--multi-role-enabled",
        action="store_true",
        help="Validate optional multi-role automation files and markers.",
    )
    parser.add_argument(
        "--ticket-campaign-enabled",
        action="store_true",
        help="Validate optional ticket-campaign source file and markers.",
    )
    parser.add_argument(
        "--optional-mcp-enabled",
        action="store_true",
        help="Validate optional MCP config, docs, role scoping, and Playwright artifact markers.",
    )
    args = parser.parse_args()

    root = Path(args.target).resolve()
    mode = args.human_bridge_mode or ("disabled" if args.no_human_bridge else inferred_human_bridge_mode(root))
    mcp_servers = optional_mcp_servers(root) if args.optional_mcp_enabled else []
    required = list(BASE_REQUIRED)
    if sidecar_enabled(root):
        required.extend(
            [
                MANIFEST_REL,
                "scripts/diffmogger_paths.py",
                "scripts/integrate_role_outputs.py",
                "scripts/list_deferred_patches.py",
                *RUNTIME_LIBRARY_REQUIRED,
            ]
        )
    if mode != "disabled":
        required.extend(HUMAN_REQUIRED)
    if args.multi_role_enabled:
        required.extend(MULTI_ROLE_REQUIRED)
    if args.ticket_campaign_enabled:
        required.extend(TICKET_CAMPAIGN_REQUIRED)
    if args.optional_mcp_enabled:
        required.extend(MCP_REQUIRED)
    if "playwright" in mcp_servers:
        required.extend(PLAYWRIGHT_MCP_REQUIRED)

    problems: list[str] = []
    if sidecar_enabled(root):
        manifest = load_manifest(root)
        if manifest.get("schema_version") != 1:
            problems.append(f"{MANIFEST_REL}: schema_version must be 1")
        if manifest.get("layout") != "sidecar_v1":
            problems.append(f"{MANIFEST_REL}: layout must be sidecar_v1")
        for key in [
            "owned_paths",
            "runtime_paths",
            "worktree_seed_paths",
            "patch_exclude_paths",
            "human_state_paths",
        ]:
            if not isinstance(manifest.get(key), list):
                problems.append(f"{MANIFEST_REL}: {key} must be a list")
        aliases = manifest.get("path_aliases") if isinstance(manifest.get("path_aliases"), dict) else {}
        script_aliases_sidecar = str(aliases.get("scripts") or "").strip().lstrip("./").rstrip("/") == ".diffmogger/scripts"
        owned = set(manifest_list(manifest, "owned_paths"))
        required_owned_paths = [
            ".diffmogger/agentic/automation_prompt.md",
            ".diffmogger/agentic/verification_commands.txt",
            ".diffmogger/state/CODEX_AUTOMATION_TASKS.md",
            ".diffmogger/lib/diffmogger/runtime/paths.py",
            ".diffmogger/lib/diffmogger/runtime/run_observatory.py",
            ".diffmogger/runtime/automation_queue",
            ".diffmogger/runtime/automation_worktrees",
        ]
        if script_aliases_sidecar:
            required_owned_paths.append(".diffmogger/scripts/diffmogger_paths.py")
        for required_owned in required_owned_paths:
            if required_owned not in owned:
                problems.append(f"{MANIFEST_REL}: owned_paths missing {required_owned!r}")
        for rel in manifest_list(manifest, "patch_exclude_paths"):
            if not rel.startswith((".diffmogger/", "scripts/", "AGENTS.md")):
                problems.append(f"{MANIFEST_REL}: patch_exclude_paths contains unexpected project-facing path {rel!r}")

    for rel in required:
        problem = check_file(rel_path(root, rel))
        if problem:
            problems.append(f"{rel_label(root, rel)}: {problem}")

    task_rel = "docs/CODEX_AUTOMATION_TASKS.md"
    task_label = rel_label(root, task_rel)
    task_path = rel_path(root, task_rel)
    if task_path.exists() and task_path.is_file():
        task_text = task_path.read_text(encoding="utf-8")
        for marker in TASK_REQUIRED_STRINGS:
            if not has_marker(task_text, marker):
                problems.append(f"{task_label}: missing marker {marker!r}")
        if args.optional_mcp_enabled:
            for marker in ["## Optional MCP Integrations", "## UI Artifact Backlog", "docs/backlog/ui_artifacts/<run_id>/"]:
                if not has_marker(task_text, marker):
                    problems.append(f"{task_label}: missing marker {marker!r}")
        if not any(marker in task_text for marker in TASK_BACKLOG_HEADINGS):
            problems.append(
                f"{task_label}: missing a recognized backlog heading"
            )

    development_rel = "docs/DEVELOPMENT.md"
    development_label = rel_label(root, development_rel)
    development_path = rel_path(root, development_rel)
    if development_path.exists() and development_path.is_file():
        development_text = development_path.read_text(encoding="utf-8")
        for marker in DEVELOPMENT_REQUIRED_STRINGS:
            if not has_marker(development_text, marker):
                problems.append(f"{development_label}: missing marker {marker!r}")
        if args.optional_mcp_enabled:
            for marker in ["## Optional MCP Integrations", ".codex/config.toml", "docs/backlog/ui_artifacts/<run_id>/<issue-slug>.png"]:
                if not has_marker(development_text, marker):
                    problems.append(f"{development_label}: missing marker {marker!r}")

    automation_rel = ".agentic/automation_prompt.md"
    automation_label = rel_label(root, automation_rel)
    automation_path = rel_path(root, automation_rel)
    if automation_path.exists() and automation_path.is_file():
        automation_text = automation_path.read_text(encoding="utf-8")
        mode_markers: list[str] = []
        if mode == "file_only":
            mode_markers = FILE_ONLY_AUTOMATION_REQUIRED_STRINGS
        elif mode == "local_notifier":
            mode_markers = LOCAL_NOTIFIER_AUTOMATION_REQUIRED_STRINGS
        elif mode == "discord_notifier":
            mode_markers = DISCORD_NOTIFIER_AUTOMATION_REQUIRED_STRINGS
        write_worker_markers = WRITE_WORKER_AUTOMATION_REQUIRED_STRINGS if args.write_workers_enabled else []
        multi_role_markers = MULTI_ROLE_AUTOMATION_REQUIRED_STRINGS if args.multi_role_enabled else []
        ticket_markers = ["Automation run mode: `ticket_campaign`", "docs/TICKET_RUN.md"] if args.ticket_campaign_enabled else []
        for marker in AUTOMATION_REQUIRED_STRINGS + mode_markers + write_worker_markers + multi_role_markers + ticket_markers:
            if not has_marker(automation_text, marker):
                problems.append(f"{automation_label}: missing marker {marker!r}")
        if args.optional_mcp_enabled:
            for marker in ["## Optional MCP Integrations", "expired auth", "docs/backlog/ui_artifacts/<run_id>/<issue-slug>.png"]:
                if not has_marker(automation_text, marker):
                    problems.append(f"{automation_label}: missing marker {marker!r}")

    if args.ticket_campaign_enabled:
        ticket_rel = "docs/TICKET_RUN.md"
        ticket_label = rel_label(root, ticket_rel)
        ticket_run_path = rel_path(root, ticket_rel)
        if ticket_run_path.exists() and ticket_run_path.is_file():
            ticket_text = ticket_run_path.read_text(encoding="utf-8")
            for marker in TICKET_RUN_REQUIRED_STRINGS:
                if not has_marker(ticket_text, marker):
                    problems.append(f"{ticket_label}: missing marker {marker!r}")

    if args.multi_role_enabled:
        guardrails_rel = "docs/CODEX_AUTOMATION_GUARDRAILS.md"
        guardrails_label = rel_label(root, guardrails_rel)
        guardrails_path = rel_path(root, guardrails_rel)
        if guardrails_path.exists() and guardrails_path.is_file():
            guardrails_text = guardrails_path.read_text(encoding="utf-8")
            for marker in MULTI_ROLE_GUARDRAIL_REQUIRED_STRINGS:
                if not has_marker(guardrails_text, marker):
                    problems.append(f"{guardrails_label}: missing marker {marker!r}")

        progress_rel = "docs/MULTI_ROLE_PROGRESS.md"
        progress_label = rel_label(root, progress_rel)
        progress_path = rel_path(root, progress_rel)
        if progress_path.exists() and progress_path.is_file():
            progress_text = progress_path.read_text(encoding="utf-8")
            for marker in MULTI_ROLE_PROGRESS_REQUIRED_STRINGS:
                if not has_marker(progress_text, marker):
                    problems.append(f"{progress_label}: missing marker {marker!r}")

        for role in ["planner", "builder", "hardener", "integrator"]:
            role_rel = f".agentic/roles/{role}.md"
            role_label = rel_label(root, role_rel)
            role_path = rel_path(root, role_rel)
            if role_path.exists() and role_path.is_file():
                role_text = role_path.read_text(encoding="utf-8")
                role_markers = ROLE_PROMPT_REQUIRED_STRINGS
                if role != "integrator":
                    role_markers = role_markers + QUEUE_ROLE_PROMPT_REQUIRED_STRINGS
                if args.optional_mcp_enabled and "context7" in mcp_servers and role in {"planner", "builder"}:
                    role_markers = role_markers + ["Context7", "auth errors", "do not halt"]
                if args.optional_mcp_enabled and "playwright" in mcp_servers and role in {"hardener", "integrator"}:
                    role_markers = role_markers + ["browser_take_screenshot", "docs/backlog/ui_artifacts"]
                for marker in role_markers:
                    if not has_marker(role_text, marker):
                        problems.append(f"{role_label}: missing marker {marker!r}")

    if args.optional_mcp_enabled:
        config_rel = ".codex/config.toml"
        config_label = rel_label(root, config_rel)
        config_path = rel_path(root, config_rel)
        if config_path.exists() and config_path.is_file():
            config_text = config_path.read_text(encoding="utf-8")
            config_markers = [
                "Diffmogger optional MCP configuration",
                "enabled = false",
                "required = false",
            ]
            if "context7" in mcp_servers:
                config_markers.extend(
                    [
                        "mcp_servers.context7",
                        "env_vars = [\"CONTEXT7_API_KEY\"]",
                        "profiles.diffmogger-planner",
                        "profiles.diffmogger-builder",
                    ]
                )
            if "playwright" in mcp_servers:
                config_markers.extend(
                    [
                        "mcp_servers.playwright",
                        "profiles.diffmogger-hardener",
                        "profiles.diffmogger-integrator",
                        "disabled_tools = [\"browser_run_code_unsafe\", \"browser_file_upload\"]",
                    ]
                )
            for marker in config_markers:
                if not has_marker(config_text, marker):
                    problems.append(f"{config_label}: missing marker {marker!r}")

        mcp_doc_rel = "docs/MCP_INTEGRATIONS.md"
        mcp_doc_label = rel_label(root, mcp_doc_rel)
        mcp_doc_path = rel_path(root, mcp_doc_rel)
        if mcp_doc_path.exists() and mcp_doc_path.is_file():
            mcp_doc_text = mcp_doc_path.read_text(encoding="utf-8")
            for marker in MCP_DOC_REQUIRED_STRINGS:
                if not has_marker(mcp_doc_text, marker):
                    problems.append(f"{mcp_doc_label}: missing marker {marker!r}")

        if "playwright" in mcp_servers:
            playwright_helper_rel = "scripts/run_playwright_mcp.sh"
            playwright_helper_label = rel_label(root, playwright_helper_rel)
            playwright_helper_path = rel_path(root, playwright_helper_rel)
            if playwright_helper_path.exists() and playwright_helper_path.is_file():
                playwright_helper_text = playwright_helper_path.read_text(encoding="utf-8")
                for marker in PLAYWRIGHT_MCP_HELPER_REQUIRED_STRINGS:
                    if not has_marker(playwright_helper_text, marker):
                        problems.append(f"{playwright_helper_label}: missing marker {marker!r}")

    runner_rel = "scripts/run_codex_automation.sh"
    runner_label = rel_label(root, runner_rel)
    runner_path = rel_path(root, runner_rel)
    if runner_path.exists() and runner_path.is_file():
        runner_text = runner_path.read_text(encoding="utf-8")
        for marker in RUNNER_REQUIRED_STRINGS:
            if not has_marker(runner_text, marker):
                problems.append(f"{runner_label}: missing marker {marker!r}")
        for marker in RUNNER_FORBIDDEN_STRINGS:
            if marker in runner_text:
                problems.append(f"{runner_label}: forbidden self-run marker {marker!r}")

    watchdog_rel = "scripts/run_process_watchdog.py"
    watchdog_label = rel_label(root, watchdog_rel)
    watchdog_path = marker_source_path(root, watchdog_rel)
    if watchdog_path.exists() and watchdog_path.is_file():
        watchdog_text = watchdog_path.read_text(encoding="utf-8")
        for marker in WATCHDOG_REQUIRED_STRINGS:
            if not has_marker(watchdog_text, marker):
                problems.append(f"{watchdog_label}: missing marker {marker!r}")

    conveyor_rel = "scripts/run_conveyor_automation.py"
    conveyor_label = rel_label(root, conveyor_rel)
    conveyor_path = marker_source_path(root, conveyor_rel)
    if conveyor_path.exists() and conveyor_path.is_file():
        conveyor_text = conveyor_path.read_text(encoding="utf-8")
        conveyor_package = root / ".diffmogger" / "lib" / "diffmogger" / "conveyor"
        if conveyor_package.exists():
            for package_file in sorted(conveyor_package.glob("*.py")):
                conveyor_text += "\n" + package_file.read_text(encoding="utf-8")
        for marker in CONVEYOR_REQUIRED_STRINGS:
            if not has_marker(conveyor_text, marker):
                problems.append(f"{conveyor_label}: missing marker {marker!r}")

    observatory_rel = "scripts/run_observatory.py"
    observatory_label = rel_label(root, observatory_rel)
    observatory_path = marker_source_path(root, observatory_rel)
    if observatory_path.exists() and observatory_path.is_file():
        observatory_text = observatory_path.read_text(encoding="utf-8")
        observatory_package = root / ".diffmogger" / "lib" / "diffmogger" / "observatory"
        if observatory_package.exists():
            for package_file in sorted(observatory_package.glob("*.py")):
                observatory_text += "\n" + package_file.read_text(encoding="utf-8")
        for marker in OBSERVATORY_REQUIRED_STRINGS:
            if not has_marker(observatory_text, marker):
                problems.append(f"{observatory_label}: missing marker {marker!r}")

    worker_helper_rel = "scripts/spawn_worker_agent.sh"
    worker_helper_label = rel_label(root, worker_helper_rel)
    worker_helper_path = rel_path(root, worker_helper_rel)
    if worker_helper_path.exists() and worker_helper_path.is_file():
        worker_helper_text = worker_helper_path.read_text(encoding="utf-8")
        write_worker_helper_markers = WRITE_WORKER_HELPER_REQUIRED_STRINGS if args.write_workers_enabled else []
        for marker in WORKER_HELPER_REQUIRED_STRINGS + write_worker_helper_markers:
            if not has_marker(worker_helper_text, marker):
                problems.append(f"{worker_helper_label}: missing marker {marker!r}")

    browser_helper_rel = "scripts/diffmogger_browser.py"
    browser_helper_label = rel_label(root, browser_helper_rel)
    browser_helper_path = marker_source_path(root, browser_helper_rel)
    if browser_helper_path.exists() and browser_helper_path.is_file():
        browser_helper_text = browser_helper_path.read_text(encoding="utf-8")
        for marker in BROWSER_HELPER_REQUIRED_STRINGS:
            if not has_marker(browser_helper_text, marker):
                problems.append(f"{browser_helper_label}: missing marker {marker!r}")

    ticket_helper_rel = "scripts/ticket_run.py"
    ticket_helper_label = rel_label(root, ticket_helper_rel)
    ticket_helper_path = marker_source_path(root, ticket_helper_rel)
    if ticket_helper_path.exists() and ticket_helper_path.is_file():
        ticket_helper_text = ticket_helper_path.read_text(encoding="utf-8")
        for marker in TICKET_HELPER_REQUIRED_STRINGS:
            if not has_marker(ticket_helper_text, marker):
                problems.append(f"{ticket_helper_label}: missing marker {marker!r}")

    if args.multi_role_enabled:
        run_role_rel = "scripts/run_role_automation.sh"
        run_role_label = rel_label(root, run_role_rel)
        run_role_path = rel_path(root, run_role_rel)
        if run_role_path.exists() and run_role_path.is_file():
            run_role_text = run_role_path.read_text(encoding="utf-8")
            for marker in RUN_ROLE_REQUIRED_STRINGS:
                if not has_marker(run_role_text, marker):
                    problems.append(f"{run_role_label}: missing marker {marker!r}")

        integrator_rel = "scripts/integrate_role_outputs.py"
        integrator_label = rel_label(root, integrator_rel)
        integrator_path = marker_source_path(root, integrator_rel)
        if integrator_path.exists() and integrator_path.is_file():
            integrator_text = integrator_path.read_text(encoding="utf-8")
            integrator_package = root / ".diffmogger" / "lib" / "diffmogger" / "integrator"
            if integrator_package.exists():
                for package_file in sorted(integrator_package.glob("*.py")):
                    integrator_text += "\n" + package_file.read_text(encoding="utf-8")
            for marker in INTEGRATOR_REQUIRED_STRINGS:
                if not has_marker(integrator_text, marker):
                    problems.append(f"{integrator_label}: missing marker {marker!r}")

        deferred_helper_rel = "scripts/list_deferred_patches.py"
        deferred_helper_label = rel_label(root, deferred_helper_rel)
        deferred_helper_path = marker_source_path(root, deferred_helper_rel)
        if deferred_helper_path.exists() and deferred_helper_path.is_file():
            deferred_helper_text = deferred_helper_path.read_text(encoding="utf-8")
            for marker in DEFERRED_HELPER_REQUIRED_STRINGS:
                if not has_marker(deferred_helper_text, marker):
                    problems.append(f"{deferred_helper_label}: missing marker {marker!r}")

    if problems:
        print("Required automation file check failed:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        return 1

    print(f"OK: required automation files exist under {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
