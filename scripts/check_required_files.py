#!/usr/bin/env python3
"""Check that a target project has the required agentic automation files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


BASE_REQUIRED = [
    "AGENTS.md",
    ".agentic/automation_prompt.md",
    "scripts/acquire_codex_lock.sh",
    "scripts/release_codex_lock.sh",
    "scripts/run_codex_automation.sh",
    "scripts/run_conveyor_automation.py",
    "scripts/run_conveyor_automation.sh",
    "scripts/run_observatory.py",
    "scripts/repair_environment.py",
    "scripts/update_automation_signals.py",
    "scripts/spawn_worker_agent.sh",
    "scripts/summarize_worker_outputs.py",
    "scripts/compact_agent_state.py",
    "docs/INITIAL_BOOTSTRAP_PROMPT.md",
    "docs/PROJECT_CONTEXT.md",
    "docs/CODEX_AUTOMATION_TASKS.md",
    "docs/CODEX_AUTOMATION_GUARDRAILS.md",
    "docs/AUTONOMY_EXPERIMENT_LOG.md",
    "docs/DAILY_AUTOMATION_REVIEW.md",
]

AUTOMATION_SIGNALS_REQUIRED = [
    "docs/AUTOMATION_SIGNALS.md",
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
    "## Ambitious Ideas Backlog",
    "## Continue/Block/Critical-Stop Rationale",
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
]

RUNNER_REQUIRED_STRINGS = [
    "CODEX_LOCK_ALREADY_ACQUIRED",
    "CODEX_NESTED_CLI_HOME",
    "--add-dir",
    "$HOME/.codex",
    "codex exec --full-auto",
    "--skip-git-repo-check",
    "update_automation_signals.py",
    "repair_environment.py",
    "child_pid",
    "forward_signal",
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
]

OBSERVATORY_REQUIRED_STRINGS = [
    "Diffmogger Observatory",
    "automation_conveyor_state.json",
    "automation_signals.json",
    "automation_queue",
    "ThreadingHTTPServer",
    "--open",
    "--review-output",
    "Self Review",
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
    "Do not attempt to send a text message",
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
    "send me",
    "text me",
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
]

ROLE_PROMPT_REQUIRED_STRINGS = [
    "NEVER push to a remote",
    "NEVER configure a remote",
    "NEVER set up upstream tracking",
    "CRITICAL_STOP",
    "docs/MULTI_ROLE_PROGRESS.md",
]

RUN_ROLE_REQUIRED_STRINGS = [
    "--role",
    "MULTI_ROLE_ALLOW_REMOTES",
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
]

INTEGRATOR_REQUIRED_STRINGS = [
    "git apply",
    "--check",
    "deferral_reason",
    "staleness",
    "MULTI_ROLE_ALLOW_REMOTES",
    "git push",
    "hooks",
    "checkpoint pre-existing local changes",
    "repair_environment.py",
    "worktree",
    "prune",
]

DEFERRED_HELPER_REQUIRED_STRINGS = [
    "deferral_reason",
    "status",
    "deferred",
    "--pretty",
]


def check_file(path: Path) -> str | None:
    if not path.exists():
        return "missing"
    if not path.is_file():
        return "not a file"
    if not path.read_text(encoding="utf-8").strip():
        return "empty"
    return None


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
        choices=["file_only", "local_notifier", "disabled"],
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
    args = parser.parse_args()

    root = Path(args.target).resolve()
    mode = args.human_bridge_mode or ("disabled" if args.no_human_bridge else "file_only")
    required = list(BASE_REQUIRED)
    if mode != "disabled":
        required.extend(HUMAN_REQUIRED)
    if args.multi_role_enabled:
        required.extend(MULTI_ROLE_REQUIRED)
    if args.automation_signals_enabled:
        required.extend(AUTOMATION_SIGNALS_REQUIRED)

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

    automation_path = root / ".agentic/automation_prompt.md"
    if automation_path.exists() and automation_path.is_file():
        automation_text = automation_path.read_text(encoding="utf-8")
        mode_markers: list[str] = []
        if mode == "file_only":
            mode_markers = FILE_ONLY_AUTOMATION_REQUIRED_STRINGS
        elif mode == "local_notifier":
            mode_markers = LOCAL_NOTIFIER_AUTOMATION_REQUIRED_STRINGS
        write_worker_markers = WRITE_WORKER_AUTOMATION_REQUIRED_STRINGS if args.write_workers_enabled else []
        multi_role_markers = MULTI_ROLE_AUTOMATION_REQUIRED_STRINGS if args.multi_role_enabled else []
        signal_markers = ["Automation signals enabled: true", "target/automation_signals.json"] if args.automation_signals_enabled else []
        for marker in AUTOMATION_REQUIRED_STRINGS + mode_markers + write_worker_markers + multi_role_markers + signal_markers:
            if marker not in automation_text:
                problems.append(f".agentic/automation_prompt.md: missing marker {marker!r}")

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
                for marker in ROLE_PROMPT_REQUIRED_STRINGS:
                    if marker not in role_text:
                        problems.append(f".agentic/roles/{role}.md: missing marker {marker!r}")

    runner_path = root / "scripts/run_codex_automation.sh"
    if runner_path.exists() and runner_path.is_file():
        runner_text = runner_path.read_text(encoding="utf-8")
        for marker in RUNNER_REQUIRED_STRINGS:
            if marker not in runner_text:
                problems.append(f"scripts/run_codex_automation.sh: missing marker {marker!r}")

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
