#!/usr/bin/env python3
"""Check that a target project has the required agentic automation files."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


BASE_REQUIRED = [
    "AGENTS.md",
    ".agentic/automation_prompt.md",
    ".agentic/verification_commands.txt",
    ".agentic/smoke_commands.txt",
    "scripts/acquire_codex_lock.sh",
    "scripts/release_codex_lock.sh",
    "scripts/run_codex_automation.sh",
    "scripts/run_conveyor_automation.py",
    "scripts/run_conveyor_automation.sh",
    "scripts/run_observatory.py",
    "scripts/build_replay.py",
    "scripts/diffmogger_browser.py",
    "scripts/ticket_run.py",
    "scripts/repair_environment.py",
    "scripts/update_automation_signals.py",
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

AUTOMATION_SIGNALS_REQUIRED = [
    "docs/AUTOMATION_SIGNALS.md",
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
    "python3 scripts/diffmogger_browser.py doctor --launch",
    "python3 scripts/ticket_run.py . status --json",
    "Run Safety Check",
    "python3 scripts/run_observatory.py --target . --review-dir /tmp/Diffmogger-review",
    "Diffmogger-observatory.html",
    "Diffmogger-self-review.md",
]

AUTOMATION_REQUIRED_STRINGS = [
    "CODEX_LOCK_ALREADY_ACQUIRED=true",
    "scripts/run_codex_automation.sh",
    "scripts/acquire_codex_lock.sh",
    "scripts/release_codex_lock.sh",
    "scripts/spawn_worker_agent.sh",
    "scripts/summarize_worker_outputs.py",
    "Codex CLI worker decision: USE / SKIP / UNAVAILABLE",
    "command -v codex",
    "--dangerously-bypass-approvals-and-sandbox",
    "ACTIVE_WITH_PENDING_USER_INPUT",
    "BLOCKED_ON_USER",
    "ticket_campaign",
    "scripts/ticket_run.py",
]

RUNNER_REQUIRED_STRINGS = [
    "CODEX_LOCK_ALREADY_ACQUIRED",
    "CODEX_LOCK_CONTEXT",
    "CODEX_NESTED_CLI_HOME",
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
    "update_automation_signals.py",
    "repair_environment.py",
    "ticket_run.py",
    "child_pid",
    "forward_signal",
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
    "decision_queue",
    "planner deferred patch resolved",
    "ticket campaign complete",
    "ticket campaign blocked",
]

OBSERVATORY_REQUIRED_STRINGS = [
    "Diffmogger Observatory",
    "automation_conveyor_state.json",
    "automation_signals.json",
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
    "Active Signals",
]

SIGNAL_HELPER_REQUIRED_STRINGS = [
    "docs/AUTOMATION_SIGNALS.md",
    "target/automation_signals.json",
    "--complete",
    "--merge-state",
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
    "Planner cadence: hourly at minute `0`",
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
    "update_automation_signals.py",
    "repair_environment.py",
    "manifest.json",
    "automation_worktrees",
    "automation_queue",
    "Runtime Summary Contract",
    "Commit subject:",
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


def project_intake(root: Path) -> dict[str, object]:
    path = root / ".agentic" / "project_intake.json"
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
            text = (root / rel).read_text(encoding="utf-8")
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
        "--automation-signals-enabled",
        action="store_true",
        help="Validate optional automation signal definitions and markers.",
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
    if mode != "disabled":
        required.extend(HUMAN_REQUIRED)
    if args.multi_role_enabled:
        required.extend(MULTI_ROLE_REQUIRED)
    if args.automation_signals_enabled:
        required.extend(AUTOMATION_SIGNALS_REQUIRED)
    if args.ticket_campaign_enabled:
        required.extend(TICKET_CAMPAIGN_REQUIRED)
    if args.optional_mcp_enabled:
        required.extend(MCP_REQUIRED)
    if "playwright" in mcp_servers:
        required.extend(PLAYWRIGHT_MCP_REQUIRED)

    problems: list[str] = []
    for rel in required:
        problem = check_file(root / rel)
        if problem:
            problems.append(f"{rel}: {problem}")

    task_path = root / "docs/CODEX_AUTOMATION_TASKS.md"
    if task_path.exists() and task_path.is_file():
        task_text = task_path.read_text(encoding="utf-8")
        for marker in TASK_REQUIRED_STRINGS:
            if marker not in task_text:
                problems.append(f"docs/CODEX_AUTOMATION_TASKS.md: missing marker {marker!r}")
        if args.optional_mcp_enabled:
            for marker in ["## Optional MCP Integrations", "## UI Artifact Backlog", "docs/backlog/ui_artifacts/<run_id>/"]:
                if marker not in task_text:
                    problems.append(f"docs/CODEX_AUTOMATION_TASKS.md: missing marker {marker!r}")
        if not any(marker in task_text for marker in TASK_BACKLOG_HEADINGS):
            problems.append(
                "docs/CODEX_AUTOMATION_TASKS.md: missing a recognized backlog heading"
            )

    development_path = root / "docs/DEVELOPMENT.md"
    if development_path.exists() and development_path.is_file():
        development_text = development_path.read_text(encoding="utf-8")
        for marker in DEVELOPMENT_REQUIRED_STRINGS:
            if marker not in development_text:
                problems.append(f"docs/DEVELOPMENT.md: missing marker {marker!r}")
        if args.optional_mcp_enabled:
            for marker in ["## Optional MCP Integrations", ".codex/config.toml", "docs/backlog/ui_artifacts/<run_id>/<issue-slug>.png"]:
                if marker not in development_text:
                    problems.append(f"docs/DEVELOPMENT.md: missing marker {marker!r}")

    automation_path = root / ".agentic/automation_prompt.md"
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
        signal_markers = ["Automation signals enabled: true", "target/automation_signals.json"] if args.automation_signals_enabled else []
        ticket_markers = ["Automation run mode: `ticket_campaign`", "docs/TICKET_RUN.md"] if args.ticket_campaign_enabled else []
        for marker in AUTOMATION_REQUIRED_STRINGS + mode_markers + write_worker_markers + multi_role_markers + signal_markers + ticket_markers:
            if marker not in automation_text:
                problems.append(f".agentic/automation_prompt.md: missing marker {marker!r}")
        if args.optional_mcp_enabled:
            for marker in ["## Optional MCP Integrations", "expired auth", "docs/backlog/ui_artifacts/<run_id>/<issue-slug>.png"]:
                if marker not in automation_text:
                    problems.append(f".agentic/automation_prompt.md: missing marker {marker!r}")

    if args.ticket_campaign_enabled:
        ticket_run_path = root / "docs/TICKET_RUN.md"
        if ticket_run_path.exists() and ticket_run_path.is_file():
            ticket_text = ticket_run_path.read_text(encoding="utf-8")
            for marker in TICKET_RUN_REQUIRED_STRINGS:
                if marker not in ticket_text:
                    problems.append(f"docs/TICKET_RUN.md: missing marker {marker!r}")

    if args.multi_role_enabled:
        guardrails_path = root / "docs/CODEX_AUTOMATION_GUARDRAILS.md"
        if guardrails_path.exists() and guardrails_path.is_file():
            guardrails_text = guardrails_path.read_text(encoding="utf-8")
            for marker in MULTI_ROLE_GUARDRAIL_REQUIRED_STRINGS:
                if marker not in guardrails_text:
                    problems.append(f"docs/CODEX_AUTOMATION_GUARDRAILS.md: missing marker {marker!r}")

        progress_path = root / "docs/MULTI_ROLE_PROGRESS.md"
        if progress_path.exists() and progress_path.is_file():
            progress_text = progress_path.read_text(encoding="utf-8")
            for marker in MULTI_ROLE_PROGRESS_REQUIRED_STRINGS:
                if marker not in progress_text:
                    problems.append(f"docs/MULTI_ROLE_PROGRESS.md: missing marker {marker!r}")

        for role in ["planner", "builder", "hardener", "integrator"]:
            role_path = root / ".agentic" / "roles" / f"{role}.md"
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
                    if marker not in role_text:
                        problems.append(f".agentic/roles/{role}.md: missing marker {marker!r}")

    if args.optional_mcp_enabled:
        config_path = root / ".codex" / "config.toml"
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
                if marker not in config_text:
                    problems.append(f".codex/config.toml: missing marker {marker!r}")

        mcp_doc_path = root / "docs" / "MCP_INTEGRATIONS.md"
        if mcp_doc_path.exists() and mcp_doc_path.is_file():
            mcp_doc_text = mcp_doc_path.read_text(encoding="utf-8")
            for marker in MCP_DOC_REQUIRED_STRINGS:
                if marker not in mcp_doc_text:
                    problems.append(f"docs/MCP_INTEGRATIONS.md: missing marker {marker!r}")

        if "playwright" in mcp_servers:
            playwright_helper_path = root / "scripts" / "run_playwright_mcp.sh"
            if playwright_helper_path.exists() and playwright_helper_path.is_file():
                playwright_helper_text = playwright_helper_path.read_text(encoding="utf-8")
                for marker in PLAYWRIGHT_MCP_HELPER_REQUIRED_STRINGS:
                    if marker not in playwright_helper_text:
                        problems.append(f"scripts/run_playwright_mcp.sh: missing marker {marker!r}")

    runner_path = root / "scripts/run_codex_automation.sh"
    if runner_path.exists() and runner_path.is_file():
        runner_text = runner_path.read_text(encoding="utf-8")
        for marker in RUNNER_REQUIRED_STRINGS:
            if marker not in runner_text:
                problems.append(f"scripts/run_codex_automation.sh: missing marker {marker!r}")
        for marker in RUNNER_FORBIDDEN_STRINGS:
            if marker in runner_text:
                problems.append(f"scripts/run_codex_automation.sh: forbidden self-run marker {marker!r}")

    conveyor_path = root / "scripts/run_conveyor_automation.py"
    if conveyor_path.exists() and conveyor_path.is_file():
        conveyor_text = conveyor_path.read_text(encoding="utf-8")
        for marker in CONVEYOR_REQUIRED_STRINGS:
            if marker not in conveyor_text:
                problems.append(f"scripts/run_conveyor_automation.py: missing marker {marker!r}")

    observatory_path = root / "scripts/run_observatory.py"
    if observatory_path.exists() and observatory_path.is_file():
        observatory_text = observatory_path.read_text(encoding="utf-8")
        for marker in OBSERVATORY_REQUIRED_STRINGS:
            if marker not in observatory_text:
                problems.append(f"scripts/run_observatory.py: missing marker {marker!r}")

    signal_helper_path = root / "scripts/update_automation_signals.py"
    if signal_helper_path.exists() and signal_helper_path.is_file():
        signal_helper_text = signal_helper_path.read_text(encoding="utf-8")
        for marker in SIGNAL_HELPER_REQUIRED_STRINGS:
            if marker not in signal_helper_text:
                problems.append(f"scripts/update_automation_signals.py: missing marker {marker!r}")

    worker_helper_path = root / "scripts/spawn_worker_agent.sh"
    if worker_helper_path.exists() and worker_helper_path.is_file():
        worker_helper_text = worker_helper_path.read_text(encoding="utf-8")
        write_worker_helper_markers = WRITE_WORKER_HELPER_REQUIRED_STRINGS if args.write_workers_enabled else []
        for marker in WORKER_HELPER_REQUIRED_STRINGS + write_worker_helper_markers:
            if marker not in worker_helper_text:
                problems.append(f"scripts/spawn_worker_agent.sh: missing marker {marker!r}")

    browser_helper_path = root / "scripts/diffmogger_browser.py"
    if browser_helper_path.exists() and browser_helper_path.is_file():
        browser_helper_text = browser_helper_path.read_text(encoding="utf-8")
        for marker in BROWSER_HELPER_REQUIRED_STRINGS:
            if marker not in browser_helper_text:
                problems.append(f"scripts/diffmogger_browser.py: missing marker {marker!r}")

    ticket_helper_path = root / "scripts/ticket_run.py"
    if ticket_helper_path.exists() and ticket_helper_path.is_file():
        ticket_helper_text = ticket_helper_path.read_text(encoding="utf-8")
        for marker in TICKET_HELPER_REQUIRED_STRINGS:
            if marker not in ticket_helper_text:
                problems.append(f"scripts/ticket_run.py: missing marker {marker!r}")

    if args.multi_role_enabled:
        run_role_path = root / "scripts/run_role_automation.sh"
        if run_role_path.exists() and run_role_path.is_file():
            run_role_text = run_role_path.read_text(encoding="utf-8")
            for marker in RUN_ROLE_REQUIRED_STRINGS:
                if marker not in run_role_text:
                    problems.append(f"scripts/run_role_automation.sh: missing marker {marker!r}")

        integrator_path = root / "scripts/integrate_role_outputs.py"
        if integrator_path.exists() and integrator_path.is_file():
            integrator_text = integrator_path.read_text(encoding="utf-8")
            for marker in INTEGRATOR_REQUIRED_STRINGS:
                if marker not in integrator_text:
                    problems.append(f"scripts/integrate_role_outputs.py: missing marker {marker!r}")

        deferred_helper_path = root / "scripts/list_deferred_patches.py"
        if deferred_helper_path.exists() and deferred_helper_path.is_file():
            deferred_helper_text = deferred_helper_path.read_text(encoding="utf-8")
            for marker in DEFERRED_HELPER_REQUIRED_STRINGS:
                if marker not in deferred_helper_text:
                    problems.append(f"scripts/list_deferred_patches.py: missing marker {marker!r}")

    if problems:
        print("Required automation file check failed:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        return 1

    print(f"OK: required automation files exist under {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
