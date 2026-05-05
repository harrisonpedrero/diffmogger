#!/usr/bin/env python3
"""Scaffold generic automation docs into a target project from an intake file."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
KIT_ROOT = SCRIPT_DIR.parent
TEMPLATE_ROOT = KIT_ROOT / "templates"
HUMAN_BRIDGE_FILES = {
    "docs/HUMAN_REQUESTS.md",
    "docs/HUMAN_INBOX.md",
    "docs/HUMAN_OUTBOX.md",
    "docs/HUMAN_RESPONSES_ARCHIVE.md",
    "docs/HUMAN_BRIDGE_SETUP.md",
}
AUTOMATION_SIGNAL_FILES = {
    "docs/AUTOMATION_SIGNALS.md",
}
VALID_HUMAN_BRIDGE_MODES = {"disabled", "file_only", "local_notifier", "discord_notifier"}
VALID_PROJECT_MODES = {"fresh_project", "existing_project"}
VALID_ENV_ACCESS_POLICIES = {"project_commands_only", "direct_env_files_allowed"}
MAX_WRITE_WORKER_COUNT = 10
DEFAULT_MAX_WRITE_WORKER_COUNT = 3
VALID_ROLE_PROFILES = {"single_lane", "planner_builder_hardener_integrator"}
VALID_SCHEDULE_STRATEGIES = {"single_lane_interval", "fixed_multi_role", "continuous_conveyor"}
VALID_AUTOMATION_RUN_MODES = {"continuous_improvement", "ticket_campaign"}
DEFAULT_MULTI_ROLE_CADENCE_MINUTES = 30
TICKET_RUN_FILES = {
    "docs/TICKET_RUN.md",
}
MULTI_ROLE_FILES = {
    ".agentic/roles/planner.md",
    ".agentic/roles/builder.md",
    ".agentic/roles/hardener.md",
    ".agentic/roles/integrator.md",
    "docs/MULTI_ROLE_PROGRESS.md",
    "scripts/run_role_automation.sh",
    "scripts/integrate_role_outputs.py",
    "scripts/list_deferred_patches.py",
}
MANAGED_EXISTING_PROJECT_FILES = {
    "AGENTS.md": "AGENTS",
    "docs/DEVELOPMENT.md": "DEVELOPMENT",
}

DIFFMOGGER_RUNTIME_EXCLUDE_PATTERNS = [
    "/scripts/__pycache__/",
    "/target/agent_runs/",
    "/target/automation_conveyor.lock",
    "/target/automation_conveyor_state.json",
    "/target/automation_logs/",
    "/target/automation_queue/",
    "/target/automation_signals.json",
    "/target/automation_venvs/",
    "/target/automation_worktrees/",
    "/target/codex_automation.lock",
    "/target/prisma-cache/",
    "/target/ticket_run_completion.json",
    "/target/ticket_run_reports/",
]


HEADING_TO_KEY = {
    "summary": "summary",
    "project mode": "project_mode",
    "project type": "project_mode",
    "target project mode": "project_mode",
    "product goal": "product_goal",
    "target user": "target_user",
    "desired first demo": "desired_first_demo",
    "tech preferences": "tech_preferences",
    "constraints": "hard_constraints",
    "hard constraints": "hard_constraints",
    "safety rules": "safety_constraints",
    "safety constraints": "safety_constraints",
    "automation must never do": "automation_must_never_do",
    "must never do": "automation_must_never_do",
    "external services": "external_services",
    "additional context": "additional_context_files",
    "additional context files": "additional_context_files",
    "context files": "additional_context_files",
    "verification": "verification_commands",
    "automation cadence": "desired_cadence",
    "desired cadence": "desired_cadence",
    "human bridge": "human_bridge_enabled",
    "human bridge mode": "human_bridge_mode",
    "human requested text responses": "human_requested_text_responses",
    "worker agents": "worker_agents_allowed",
    "codex cli workers": "codex_cli_workers_expected_on_broad_runs",
    "write worker agents": "write_worker_agents_allowed",
    "write-capable worker agents": "write_worker_agents_allowed",
    "bounded write workers": "write_worker_agents_allowed",
    "bounded write worker agents": "write_worker_agents_allowed",
    "max write workers": "max_write_worker_count",
    "maximum write workers": "max_write_worker_count",
    "max write worker count": "max_write_worker_count",
    "maximum write worker count": "max_write_worker_count",
    "write worker guidance": "write_worker_guidance",
    "write-worker guidance": "write_worker_guidance",
    "multi-role automations": "multi_role_automations_allowed",
    "multi role automations": "multi_role_automations_allowed",
    "multi-role automation": "multi_role_automations_allowed",
    "multi role automation": "multi_role_automations_allowed",
    "automation role profile": "automation_role_profile",
    "role profile": "automation_role_profile",
    "automation checkpoint commits": "automation_checkpoint_commits",
    "checkpoint commits": "automation_checkpoint_commits",
    "multi-role base cadence": "multi_role_base_cadence_minutes",
    "multi role base cadence": "multi_role_base_cadence_minutes",
    "multi-role cadence": "multi_role_base_cadence_minutes",
    "multi role cadence": "multi_role_base_cadence_minutes",
    "automation schedule strategy": "automation_schedule_strategy",
    "schedule strategy": "automation_schedule_strategy",
    "scheduling strategy": "automation_schedule_strategy",
    "multi-role allow remotes": "multi_role_allow_remotes",
    "multi role allow remotes": "multi_role_allow_remotes",
    "allow multi-role remotes": "multi_role_allow_remotes",
    "allow multi role remotes": "multi_role_allow_remotes",
    "automation signals": "automation_signals_enabled",
    "automation pulse": "automation_signals_enabled",
    "automation pulses": "automation_signals_enabled",
    "automation signal system": "automation_signals_enabled",
    "automation run mode": "automation_run_mode",
    "run mode": "automation_run_mode",
    "ticket run file": "ticket_run_file",
    "ticket file": "ticket_run_file",
    "ticket completion notify": "ticket_completion_notify",
    "ticket notification": "ticket_completion_notify",
    "environment access": "env_access_policy",
    "env access": "env_access_policy",
    "env access policy": "env_access_policy",
    "environment access policy": "env_access_policy",
    "meaningful deliverable": "meaningful_deliverable",
    "beyond mvp": "beyond_mvp",
    "beyond-mvp": "beyond_mvp",
    "long-run direction": "beyond_mvp",
    "long run direction": "beyond_mvp",
    "after initial scope": "beyond_mvp",
    "after first demo": "beyond_mvp",
    "future direction": "beyond_mvp",
    "assumptions": "assumptions",
}


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "new-project"


def normalize_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"yes", "true", "enabled", "allow", "allowed", "on"}:
        return True
    if text in {"no", "false", "disabled", "disallow", "off"}:
        return False
    if any(word in text for word in ["enabled", "allowed", "yes", "true"]):
        return True
    if any(word in text for word in ["disabled", "not allowed", "no", "false"]):
        return False
    return default


def normalize_lines(value: Any, fallback: str) -> str:
    if value is None:
        return fallback
    if isinstance(value, list):
        return "\n".join(f"- {item}" for item in value) or fallback
    text = str(value).strip()
    return text or fallback


def inline_text(value: Any, fallback: str) -> str:
    text = normalize_lines(value, fallback)
    cleaned: list[str] = []
    for line in text.splitlines():
        line = re.sub(r"^[-*]\s+", "", line.strip())
        if line:
            cleaned.append(line)
    return re.sub(r"\s+", " ", " ".join(cleaned)).strip()


def inline_phrase(value: Any, fallback: str) -> str:
    return inline_text(value, fallback).rstrip(".")


def table_cell(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("|", "/")).strip()


def normalize_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if value is None:
        return default
    match = re.search(r"-?\d+", str(value))
    if not match:
        return default
    return int(match.group(0))


def normalize_write_worker_count(value: Any, enabled: bool) -> int:
    if not enabled:
        return 0
    count = normalize_int(value, DEFAULT_MAX_WRITE_WORKER_COUNT)
    return max(1, min(MAX_WRITE_WORKER_COUNT, count))


def normalize_role_profile(value: Any, multi_role_enabled: bool) -> str:
    if not multi_role_enabled:
        return "single_lane"
    text = str(value or "planner_builder_hardener_integrator").strip().lower()
    text = text.replace("-", "_").replace(" ", "_")
    if text in VALID_ROLE_PROFILES:
        return text
    return "planner_builder_hardener_integrator"


def normalize_multi_role_cadence(value: Any) -> int:
    return max(30, normalize_int(value, DEFAULT_MULTI_ROLE_CADENCE_MINUTES))


def normalize_schedule_strategy(value: Any, multi_role_enabled: bool) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not text:
        return "fixed_multi_role" if multi_role_enabled else "single_lane_interval"
    if text in VALID_SCHEDULE_STRATEGIES:
        return text
    if any(term in text for term in ("conveyor", "continuous", "work_conserving", "workconserving")):
        return "continuous_conveyor"
    if any(term in text for term in ("fixed", "staggered", "calendar", "role")):
        return "fixed_multi_role"
    if any(term in text for term in ("single", "interval", "periodic", "cadence")):
        return "single_lane_interval"
    return "fixed_multi_role" if multi_role_enabled else "single_lane_interval"


def normalize_automation_run_mode(value: Any) -> str:
    text = str(value or "continuous_improvement").strip().lower()
    text = text.replace("-", "_").replace(" ", "_")
    return text if text in VALID_AUTOMATION_RUN_MODES else "continuous_improvement"


def ticket_run_values(data: dict[str, Any]) -> dict[str, str]:
    mode = normalize_automation_run_mode(data.get("automation_run_mode"))
    ticket_file = str(data.get("ticket_run_file") or "docs/TICKET_RUN.md").strip() or "docs/TICKET_RUN.md"
    notify = normalize_bool(data.get("ticket_completion_notify"), True)
    if mode == "ticket_campaign":
        section = f"""Automation run mode: `ticket_campaign`

Use `{ticket_file}` as the bounded ticket source of truth. Do not invent new backlog after listed tickets are done or blocked.

Before choosing ticket work in any normal campaign run, run:

```bash
python3 scripts/ticket_run.py . next --json
```

Use that dependency-aware selection as the only ticket scope for the run. Act on at most one selected ticket per run, preserving file order as the human's priority order when dependencies allow. A single-lane run may implement and verify that one ticket, but must not continue into another ticket after it is completed, blocked, or marked `candidate_done`.

If `next --json` reports placeholder tickets, missing dependencies, duplicate ticket IDs, dependency cycles, blocked dependencies, or no actionable ticket, record the structured blocker in `docs/CODEX_AUTOMATION_TASKS.md` instead of guessing or reordering the campaign by hand.

When every ticket is done, or when all remaining tickets are blocked, run:

```bash
python3 scripts/ticket_run.py . should-halt --finalize
```

Then stop launching new work. Diffmogger writes a local report, sends a native desktop notification when enabled, records fallback outbox state if notification delivery fails, and leaves remote push/PR creation to the human."""
        task_notes = f"""Ticket campaign mode: `ticket_campaign`

- Ticket source: `{ticket_file}`
- Bootstrap boundary: readiness-only; do not implement tickets during bootstrap.
- Normal campaign runs select one dependency-ready ticket with `python3 scripts/ticket_run.py . next --json`.
- Optional dependencies: use `depends_on` arrays in `{ticket_file}` when one ticket must wait for another.
- Halt when every ticket is done or all remaining tickets are blocked.
- Completion report is written under `target/ticket_run_reports/`.
- Completion notification uses the local desktop notification system when enabled.
- Remote push/PR creation is manual."""
        development = f"""Ticket campaign mode is enabled. Edit `{ticket_file}` with concrete local tickets before starting unattended automation. Use optional `depends_on` arrays when one ticket must wait for another ticket to be `done` with evidence.

```bash
python3 scripts/ticket_run.py . status --json
python3 scripts/ticket_run.py . next --json
python3 scripts/ticket_run.py . should-halt --finalize
```

Bootstrap is readiness-only in ticket-campaign mode: it should confirm setup, ticket shape, and verification commands, but it must not implement ticket acceptance criteria, mark tickets `candidate_done` or `done`, or finalize the campaign. Normal campaign runs should act on at most one `next --json` selection. The helper writes `target/ticket_run_completion.json` and a Markdown report when the run reaches a terminal state. When `ticket_completion_notify` or `notify_on_complete` is true on macOS, it sends a local desktop notification; if that fails, it records `LOCAL_NOTIFICATION_FAILED` in `docs/HUMAN_OUTBOX.md`."""
    else:
        section = """Automation run mode: `continuous_improvement`

Use the normal horizon/backlog loop. Ticket-campaign halting is inactive unless the project intake explicitly sets `automation_run_mode: ticket_campaign` and provides `docs/TICKET_RUN.md`. The helper `scripts/ticket_run.py` is available for future bounded ticket runs."""
        task_notes = """Ticket campaign mode: disabled.

- Use the normal continuous-improvement horizon loop."""
        development = """Ticket campaign mode is disabled by default. To run against bounded tickets later, set `automation_run_mode` to `ticket_campaign` in `.agentic/project_intake.json` and add `docs/TICKET_RUN.md`.

```bash
python3 scripts/ticket_run.py . status --json
python3 scripts/ticket_run.py . should-halt --finalize
```"""
    return {
        "AUTOMATION_RUN_MODE": mode,
        "TICKET_RUN_FILE": ticket_file,
        "TICKET_COMPLETION_NOTIFY": "true" if notify else "false",
        "TICKET_CAMPAIGN_SECTION": section.strip(),
        "TICKET_CAMPAIGN_TASK_NOTES": task_notes.strip(),
        "TICKET_CAMPAIGN_DEVELOPMENT_SECTION": development.strip(),
    }


def markdown_table(rows: list[tuple[str, str, str]]) -> str:
    lines = [
        "| Horizon | Goal | Advance when |",
        "| --- | --- | --- |",
    ]
    for horizon, goal, advance in rows:
        lines.append(f"| {table_cell(horizon)} | {table_cell(goal)} | {table_cell(advance)} |")
    return "\n".join(lines)


def progression_values(data: dict[str, Any], project_name: str) -> dict[str, str]:
    mode = normalize_automation_run_mode(data.get("automation_run_mode"))
    product_goal = inline_phrase(
        data.get("product_goal"),
        "Build a useful local-first product from the intake brief.",
    )
    target_user = inline_phrase(
        data.get("target_user"),
        "the primary user described in the intake brief",
    )
    first_demo = inline_phrase(
        data.get("desired_first_demo"),
        "a runnable local demo that proves the core workflow",
    )
    external_services = inline_phrase(data.get("external_services"), "optional integrations")
    deliverable = inline_phrase(
        data.get("meaningful_deliverable"),
        "a runnable, verified increment",
    )
    long_run = inline_phrase(
        data.get("beyond_mvp"),
        "continue improving core value, demo quality, integrations, and automation reliability",
    )
    ticket_file = str(data.get("ticket_run_file") or "docs/TICKET_RUN.md").strip() or "docs/TICKET_RUN.md"

    if mode == "ticket_campaign":
        rows = [
            (
                "T1 Ticket-run readiness",
                f"Confirm `{ticket_file}`, local setup, and verification are ready for `{project_name}`.",
                "The ticket source exists, setup expectations are clear, and at least one useful verification path is available or honestly blocked.",
            ),
            (
                "T2 Ticket implementation",
                "Use `scripts/ticket_run.py . next --json` to implement one dependency-ready ticket per run.",
                "The selected ticket has implementation notes, changed files, evidence, `candidate_done`, or a recorded blocker.",
            ),
            (
                "T3 Verification and hardening",
                "Verify candidate tickets, repair failures, and record acceptance evidence.",
                "Completed tickets have acceptance and verification evidence; blocked tickets explain the missing human or environment action.",
            ),
            (
                "T4 Completion report and stop",
                "Finalize when every ticket is done or all remaining tickets are blocked.",
                "`scripts/ticket_run.py . should-halt --finalize` writes the report and completion state, then automation stops launching new work.",
            ),
        ]
        guidance = f"""Progression is mode-aware for this target. Because `automation_run_mode` is `ticket_campaign`, use the bounded ticket-run phases below instead of a product roadmap. `{ticket_file}` is the source of truth for scope; do not invent new roadmap work after listed tickets are done or blocked. After T1 readiness, select ticket work with `python3 scripts/ticket_run.py . next --json` and act on at most one dependency-ready ticket per run.

{markdown_table(rows)}

At the end of every run, update `## Product Horizon State` with:

- current horizon or ticket-run phase
- horizon goal
- advancement criteria
- evidence gathered this run
- advancement decision: `stay`, `advance`, or `defer`
- next horizon candidate
- remaining work before advancement

If the phase criteria are met, update the current horizon to the next ticket-run phase and append a dated note to `## Horizon Transition Log` with the previous phase, new phase, evidence, and checks. When every ticket is done, or when all remaining tickets are blocked, finalize the ticket run and stop launching new work."""
        return {
            "PRODUCT_HORIZON_GUIDANCE": guidance.strip(),
            "CURRENT_HORIZON": "T1 Ticket-run readiness",
            "HORIZON_GOAL": f"Confirm `{ticket_file}`, local setup, and verification are ready for `{project_name}`.",
            "HORIZON_ADVANCEMENT_CRITERIA": "\n".join(
                [
                    f"  - `{ticket_file}` exists and contains the bounded ticket source of truth.",
                    "  - `python3 scripts/ticket_run.py . status --json` and `python3 scripts/ticket_run.py . next --json` can parse the ticket file, or an honest blocker is documented.",
                    "  - Local setup and verification expectations are documented.",
                    "  - The first ticket implementation run can start safely, or an environment blocker is documented.",
                ]
            ),
            "NEXT_HORIZON_CANDIDATE": "T2 Ticket implementation",
            "REMAINING_WORK_BEFORE_ADVANCEMENT": "\n".join(
                [
                    f"  - Populate or confirm `{ticket_file}`.",
                    "  - Run the readiness-only bootstrap prompt, verify local setup, and record ticket-readiness evidence.",
                    "  - Do not implement ticket acceptance criteria during bootstrap.",
                ]
            ),
            "INITIAL_KNOWN_ISSUES": "\n".join(
                [
                    "- Ticket source still needs to be populated or confirmed.",
                    "- Verification commands may need adjustment after bootstrap.",
                    "- Scheduled runs should use `scripts/run_codex_automation.sh`, which wraps local lock acquire/release before code mutation.",
                    "- Optional continuous conveyor scheduling should use `scripts/run_conveyor_automation.sh`, which records local scheduler state and delegates to the target-local wrappers.",
                ]
            ),
            "BEST_NEXT_MILESTONE": f"Complete T1 readiness-only ticket bootstrap for `{project_name}` and record whether one-ticket campaign runs can start.",
            "SUGGESTED_NEXT_SPRINT_TASK": f"Run `docs/INITIAL_BOOTSTRAP_PROMPT.md` in Codex, confirm `{ticket_file}`, run ticket status/next parsing, setup docs, checks, automation state, and ticket-readiness evidence without implementing tickets.",
            "BACKLOG_SECTION_HEADING": "Deferred / Follow-Up Tickets",
            "BACKLOG_SECTION_BODY": "\n".join(
                [
                    "- Keep follow-up work in `docs/TICKET_RUN.md` or a new local ticket file.",
                    "- Record blocked tickets with the exact missing human or environment action.",
                    "- Do not create open-ended roadmap work after the bounded ticket set is finalized.",
                ]
            ),
            "CONTINUE_RATIONALE": "Continue. The ticket campaign has a bounded local source of truth and no active blocker.",
            "AGENTS_PROGRESS_RULE": "Treat the ticket source as a bounded, dependency-aware execution queue; after readiness, act on at most one `scripts/ticket_run.py . next --json` selection per run.",
            "INITIAL_PROGRESS_EVIDENCE_LABEL": "ticket-readiness evidence",
            "BOOTSTRAP_SCOPE_BOUNDARY": "Ticket-campaign bootstrap is readiness-only: inspect the repo, confirm the ticket file parses, run `python3 scripts/ticket_run.py . status --json` and `python3 scripts/ticket_run.py . next --json` when possible, configure docs/checks, and update task state. If the ticket file is missing, placeholder-only, malformed, or ambiguous, record `ACTIVE_WITH_PENDING_USER_INPUT` or an honest blocker instead of solving tickets. Do not implement ticket acceptance criteria, mark tickets `candidate_done` or `done`, finalize the campaign, or continue into the first ticket.",
            "BOOTSTRAP_END_NOTE": "Use the ticket source as the first bounded readiness phase. Do not implement tickets during bootstrap, and do not create extra roadmap work after every ticket is done or blocked.",
        }

    rows = [
        (
            "H1 Runnable baseline",
            f"Create or confirm setup, local run path, and verification for `{project_name}`.",
            "Setup, a local run or demo command, and at least one useful verification path exist or an environment blocker is documented.",
        ),
        (
            "H2 Local-first demo",
            f"Make the desired first demo usable with local data: {first_demo}.",
            "A human can follow a documented local path through the core demo without live external services.",
        ),
        (
            "H3 Core workflow depth",
            f"Replace placeholders with meaningful behavior for: {product_goal}.",
            "The core workflow has representative data, real behavior, and targeted tests or smoke checks.",
        ),
        (
            "H4 Evidence and review surface",
            f"Add review, reporting, scoring, summaries, or comparison surfaces around: {deliverable}.",
            "The project can produce a useful decision-support or review artifact from local data.",
        ),
        (
            "H5 Safe optional integrations",
            f"Prepare optional integration paths without unsafe side effects: {external_services}.",
            "External adapters are mocked, gated, documented, and keep secrets outside the repo.",
        ),
        (
            "H6 Review-ready quality",
            f"Improve reliability, docs, and first-impression workflow for {target_user}.",
            "The review path is polished enough to inspect confidently and has no obvious broken first-impression workflow.",
        ),
        (
            "H7 Long-run direction",
            f"Implement high-value next capabilities from the long-run direction: {long_run}.",
            "At least one high-leverage extension is implemented, verified, and connected to the product narrative or backlog.",
        ),
        (
            "H8 Automation process improvement",
            "Improve the recurring automation workflow based on actual run evidence.",
            "The workflow has been reviewed, simplified, strengthened, or compacted based on real automation evidence.",
        ),
    ]
    guidance = f"""Product horizons are explicit state, not just inspiration. At the start of each run, read the `## Product Horizon State` section in `docs/CODEX_AUTOMATION_TASKS.md`. Choose work that advances the current horizon unless a regression, blocker, or human instruction requires a different focus.

These horizons were scaffolded from the project intake:

{markdown_table(rows)}

At the end of every run, update `## Product Horizon State` with:

- current horizon
- horizon goal
- advancement criteria
- evidence gathered this run
- advancement decision: `stay`, `advance`, or `defer`
- next horizon candidate
- remaining work before advancement

If the advancement criteria are met, update the current horizon to the next horizon and append a dated note to `## Horizon Transition Log` with the previous horizon, new horizon, evidence, and checks. Do not advance merely because a demo exists; advance when the criteria are satisfied enough that the next horizon is now the highest-leverage work. It is acceptable to advance with minor known issues if they are documented and do not undermine the next horizon. If a later regression undermines an earlier horizon, keep the current horizon but make the regression the next sprint-sized task.

Long-run direction: {long_run}"""
    return {
        "PRODUCT_HORIZON_GUIDANCE": guidance.strip(),
        "CURRENT_HORIZON": "H1 Runnable baseline",
        "HORIZON_GOAL": f"Create or confirm setup, local run path, and verification for `{project_name}`.",
        "HORIZON_ADVANCEMENT_CRITERIA": "\n".join(
            [
                "  - Setup path is documented.",
                "  - A local run or demo command exists.",
                "  - At least one useful verification command exists and has run, or an environment blocker is documented.",
            ]
        ),
        "NEXT_HORIZON_CANDIDATE": "H2 Local-first demo",
        "REMAINING_WORK_BEFORE_ADVANCEMENT": "  - Run the bootstrap prompt, create or inspect the baseline, and record verification results.",
        "INITIAL_KNOWN_ISSUES": "\n".join(
            [
                "- Product baseline still needs to be created or inspected.",
                "- Verification commands may need adjustment after bootstrap.",
                "- Scheduled runs should use `scripts/run_codex_automation.sh`, which wraps local lock acquire/release before code mutation.",
                "- Optional continuous conveyor scheduling should use `scripts/run_conveyor_automation.sh`, which records local scheduler state and delegates to the target-local wrappers.",
            ]
        ),
        "BEST_NEXT_MILESTONE": f"Complete H1 Runnable baseline for `{project_name}` and record whether the project is ready to advance to H2 Local-first demo.",
        "SUGGESTED_NEXT_SPRINT_TASK": "Run `docs/INITIAL_BOOTSTRAP_PROMPT.md` in Codex to scaffold the first demo, setup docs, checks, automation state, and H1 advancement evidence.",
        "BACKLOG_SECTION_HEADING": "Improvement Backlog",
        "BACKLOG_SECTION_BODY": "\n".join(
            [
                f"- Improve the first demo until {target_user} can understand it quickly.",
                "- Add an evaluation, reporting, or review layer once the baseline works.",
                f"- Prepare safe optional integration paths for: {external_services}.",
                f"- Use the long-run direction as future backlog seed: {long_run}.",
            ]
        ),
        "CONTINUE_RATIONALE": "Continue. The project has a clear mission and no active blocker.",
        "AGENTS_PROGRESS_RULE": "Treat the first working baseline as an early milestone, not the finish line.",
        "INITIAL_PROGRESS_EVIDENCE_LABEL": "H1 advancement evidence",
        "BOOTSTRAP_SCOPE_BOUNDARY": "During bootstrap, create or confirm the first runnable baseline and automation state for the current horizon.",
        "BOOTSTRAP_END_NOTE": "Do not stop merely because a basic demo exists. This is the first horizon, not the final product.",
    }


def normalize_mode(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    if text in VALID_HUMAN_BRIDGE_MODES:
        return text
    return None


def human_bridge_mode(data: dict[str, Any]) -> str:
    explicit = normalize_mode(data.get("human_bridge_mode"))
    if explicit:
        return explicit

    bridge_text = " ".join(
        str(data.get(key) or "")
        for key in ("human_bridge_enabled", "human_bridge_mode")
    ).lower()
    if any(term in bridge_text for term in ("disabled", "off", "no human", "none")):
        return "disabled"
    if "file" in bridge_text or "manual" in bridge_text:
        return "file_only"
    if "discord" in bridge_text:
        return "discord_notifier"
    if "notifier" in bridge_text or "local notification" in bridge_text:
        return "local_notifier"
    if normalize_bool(data.get("human_bridge_enabled"), False):
        return "file_only"
    return "disabled"


def project_mode(data: dict[str, Any]) -> str:
    raw = str(data.get("project_mode") or data.get("project_type") or "").strip().lower()
    text = raw.replace("-", "_").replace(" ", "_")
    if text in VALID_PROJECT_MODES:
        return text
    if any(term in text for term in ("existing", "integrat", "retrofit", "current_repo", "current")):
        return "existing_project"
    return "fresh_project"


def env_access_policy(data: dict[str, Any]) -> str:
    raw = str(data.get("env_access_policy") or data.get("environment_access_policy") or "").strip().lower()
    text = raw.replace("-", "_").replace(" ", "_")
    direct_aliases = {
        "direct_env_files_allowed",
        "allow_direct_env_files",
        "allow_env_files",
        "read_env_files_allowed",
        "direct",
        "allowed",
        "allow",
    }
    command_only_aliases = {
        "project_commands_only",
        "commands_only",
        "no_direct_env_files",
        "safe",
        "disabled",
        "off",
    }
    if text in direct_aliases:
        return "direct_env_files_allowed"
    if text in command_only_aliases or text in VALID_ENV_ACCESS_POLICIES:
        return text

    combined_parts: list[str] = []
    for key in ("hard_constraints", "safety_constraints", "automation_must_never_do", "external_services"):
        raw_value = data.get(key)
        values = raw_value if isinstance(raw_value, list) else [raw_value]
        combined_parts.extend(str(item) for item in values if item)
    combined = "\n".join(combined_parts).lower()
    if any(marker in combined for marker in ("may read .env", "can read .env", "allowed to read .env")):
        return "direct_env_files_allowed"
    return "project_commands_only"


def project_mode_label(mode: str) -> str:
    return "Existing project integration" if mode == "existing_project" else "Fresh project"


def project_mode_guidance(mode: str) -> str:
    if mode == "existing_project":
        return (
            "Integrate Diffmogger into the selected existing project. Preserve the existing "
            "architecture, package manager, tests, docs, and project-specific instructions unless "
            "the intake explicitly asks for a scoped change. Treat the desired first demo as an "
            "integrated increment inside the current codebase, not a greenfield rewrite."
        )
    return (
        "Create a new target project from the intake. Choose simple local-first defaults, create "
        "the initial repo structure, and document setup and verification as part of bootstrap."
    )


def env_access_values(data: dict[str, Any]) -> dict[str, str]:
    policy = env_access_policy(data)
    if policy == "direct_env_files_allowed":
        agents_rule = (
            "Local `.env*` files may be read when needed for approved local verification, "
            "disposable database work, or explicitly enabled live-provider tests. Never print, "
            "copy, summarize, store, or commit secret values."
        )
        guardrails = "\n".join(
            [
                "- Local `.env*` files may be read when needed for approved local verification, disposable database work, or explicitly enabled live-provider tests.",
                "- Never print, copy, summarize, store, or commit secret values.",
                "- Prefer project commands that load environment values naturally; inspect values only when the approved local workflow requires it.",
                "- Keep docs, examples, reports, and commits free of real credentials.",
            ]
        )
        worker_rule = (
            "Local `.env*` files may be read when needed for the assigned approved verification "
            "or integration task, but never print, copy, store, or commit secret values."
        )
        must_never_default = (
            "Never print, store, or commit secrets; local `.env*` files may be read only when "
            "the intake or human instructions approve live/local integration testing."
        )
    else:
        agents_rule = (
            "Do not open local `.env*` files. Project commands may load environment values "
            "normally; if a value is unavailable, use mocks/fixtures or ask for the specific "
            "missing variable name. Never print, copy, store, or commit secrets."
        )
        guardrails = "\n".join(
            [
                "- Do not open local `.env*` files.",
                "- Project commands may load environment values normally.",
                "- If a credential value is unavailable, use mocks/fixtures or ask for the specific missing variable name; do not ask for the secret value itself.",
                "- Never print, copy, summarize, store, or commit secret values.",
            ]
        )
        worker_rule = (
            "Do not open local `.env*` files. Project commands may load environment values "
            "normally; never print, copy, store, or commit secret values."
        )
        must_never_default = (
            "Never print, store, or commit secrets; project commands may load local env values "
            "normally, but do not open local `.env*` files unless env access is explicitly enabled."
        )
    return {
        "ENV_ACCESS_POLICY": policy,
        "ENV_ACCESS_AGENTS_RULE": agents_rule,
        "ENV_ACCESS_GUARDRAILS_POLICY": guardrails,
        "WORKER_ENV_ACCESS_RULE": worker_rule,
        "AUTOMATION_MUST_NEVER_DO_DEFAULT": must_never_default,
    }



def worker_values(data: dict[str, Any]) -> dict[str, str]:
    workers_allowed = normalize_bool(data.get("worker_agents_allowed"), True)
    codex_workers_expected = normalize_bool(
        data.get("codex_cli_workers_expected_on_broad_runs"),
        True,
    )
    write_workers_enabled = workers_allowed and normalize_bool(
        data.get("write_worker_agents_allowed"),
        False,
    )
    max_write_workers = normalize_write_worker_count(
        data.get("max_write_worker_count"),
        write_workers_enabled,
    )
    guidance = normalize_lines(
        data.get("write_worker_guidance"),
        (
            "Use the most parallelism the task can safely absorb. Write workers are "
            "optional acceleration for broad work with reviewable ownership boundaries; "
            "keep coordination lightweight and let the main agent integrate and verify."
        ),
    )

    if write_workers_enabled:
        orchestration = f"""Write-worker guidance:

{guidance}

Write workers are optional, never mandatory, and should be used as bounded acceleration. Default to the most useful parallelism the task can safely absorb: no workers for tiny or tightly coupled changes, a few workers for normal multi-surface work, and up to {max_write_workers} workers for broad implementation, audit, hardening, observability, docs, examples, validation, or competing prototype lanes.

The goal is to maximize validated useful diff per unit time while preserving local-first safety and reviewability. Prefer reviewable progress and repairable local breakage over over-planning a run into tiny changes.

At the beginning of every run, make an explicit strategy decision in addition to the Codex CLI availability decision:

```text
Worker strategy: READ_ONLY_REPORTS / WRITE_WORKERS / INTEGRATION_ONLY / NO_WORKERS
Write-worker count planned: <0-{max_write_workers}>
Parallelism budget: <0-{max_write_workers} workers>
Reason: <one sentence>
```

Use read-only workers by default for exploration, review, risk checks, product polish, and test-gap analysis.

Use write workers when the work can be split into useful bounded lanes and the main agent can integrate the results. Before spawning write workers, keep the plan lightweight but concrete:

- choose the milestone
- assign rough file/module ownership for each worker
- define only the shared contracts, interfaces, data shapes, or command boundaries that matter
- document a coordination protocol only when ownership overlaps
- choose expected checks

```text
Write-worker ownership plan:
- worker_<role_a>: owns <files/modules>; contract <interface/data shape>; must not touch <out of scope>
- worker_<role_b>: owns <files/modules>; contract <interface/data shape>; must not touch <out of scope>
Coordination protocol: <how shared interfaces, generated artifacts, or conflicts will be handled>
```

Example bounded write-worker helper:

```bash
bash scripts/spawn_worker_agent.sh \\
  --mode write \\
  --target . \\
  --run-id "$CODEX_RUN_ID" \\
  --role feature_a \\
  --ownership "src/feature-a/** and tests/feature-a/** only" \\
  --prompt "Implement the assigned slice using the agreed interface. List changed files and checks run."
```

Every write-worker assignment must tell the worker:

- You are not alone in the codebase.
- Modify only your assigned files/modules or scratch area.
- Do not revert unrelated edits or changes made by others.
- Adjust your implementation to documented contracts and other workers' outputs.
- Follow the generated environment-access policy. Never print, copy, store, or commit secret values.
- Do not spawn workers, use network, send messages, or run destructive cleanup.
- Stop after the bounded assignment and write `target/agent_runs/<run_id>/worker_<role>.md`.
- List changed files, checks run, integration notes, and risks.

After write workers finish, the main agent must:

- inspect each worker report and changed-file list
- review diffs rather than blindly accepting changes
- resolve conflicts and contract mismatches
- integrate the slices into one coherent change
- run relevant verification
- update `docs/CODEX_AUTOMATION_TASKS.md` with worker strategy, workers used, changed files, checks, accepted/rejected/deferred outputs, and final status"""
        guardrails = f"""- Write-capable workers are enabled but optional; use them as bounded acceleration when work can split into reviewable lanes.
- Spawn at most {max_write_workers} write workers in one run, and use the most parallelism the task can safely absorb.
- Define enough contracts/interfaces and file/module ownership for workers to avoid chaotic overlap, without turning planning into ceremony.
- Do not allow overlapping write ownership unless an explicit coordination protocol is documented first.
- Do not create unbounded recursive agent loops. Workers must not spawn workers.
- Do not blindly accept worker changes; the main agent must review, integrate, resolve conflicts, and verify.
- Do not use destructive cleanup, history rewrites, mass deletion, or broad formatting as a worker cleanup shortcut."""
        task_notes = f"""Write-capable worker agents allowed: true

- Max write worker count: {max_write_workers}
- Parallelism budget: choose 0-{max_write_workers} workers based on how much useful parallelism the task can absorb.
- Write workers are optional acceleration for broad work with reviewable ownership boundaries.
- Read-only workers remain the default for exploration and review.
- Integration-only runs with no workers are valid when faster or safer.
- The main agent must assign ownership, reject weak output, integrate strong output, verify, and update task state."""
        development = f"""Write-capable worker agents allowed: true

Max write worker count: {max_write_workers}

Write workers are optional acceleration. Use the most parallelism the task can safely absorb while keeping ownership reviewable and the main agent responsible for integration. The helper supports `--mode write`, but it does not replace code review or conflict resolution."""
        bootstrap = f"""Worker agents allowed: {str(workers_allowed).lower()}

Write-capable worker agents allowed: true

Max write worker count: {max_write_workers}

Recurring automation should use read-only worker reports for exploration and use bounded write workers as acceleration when work can split into useful parallel lanes. Keep planning lightweight, but make ownership, verification, and integration responsibilities clear."""
    else:
        orchestration = """Write workers are disabled for this project. Do not spawn nested workers that modify source files or docs. Use read-only worker reports when useful, and let the main agent implement, integrate, verify, and update task state directly.

Integration-only runs with no workers are valid."""
        guardrails = """- Write-capable workers are disabled unless the project intake is explicitly updated to enable them.
- Use read-only worker reports when workers are useful.
- Do not spawn nested workers that modify source files or docs."""
        task_notes = """Write-capable worker agents allowed: false

- Max write worker count: 0
- Read-only worker reports remain available when worker agents are allowed.
- The main agent performs implementation, integration, verification, and task-state updates."""
        development = """Write-capable worker agents allowed: false

Use read-only worker reports first. The main agent owns implementation and integration unless the project intake is explicitly updated to enable bounded write workers."""
        bootstrap = f"""Worker agents allowed: {str(workers_allowed).lower()}

Write-capable worker agents allowed: false

Generated automation should preserve read-only worker-report behavior and keep implementation responsibility with the main agent unless the intake is explicitly updated later."""

    return {
        "WORKER_AGENTS_ALLOWED": str(workers_allowed).lower(),
        "CODEX_CLI_WORKERS_EXPECTED_ON_BROAD_RUNS": str(codex_workers_expected).lower(),
        "WRITE_WORKER_AGENTS_ALLOWED": str(write_workers_enabled).lower(),
        "MAX_WRITE_WORKER_COUNT": str(max_write_workers),
        "WRITE_WORKER_GUIDANCE": guidance,
        "WRITE_WORKER_ORCHESTRATION": orchestration.strip(),
        "WRITE_WORKER_GUARDRAILS_POLICY": guardrails.strip(),
        "WRITE_WORKER_TASK_NOTES": task_notes.strip(),
        "WRITE_WORKER_DEVELOPMENT_SECTION": development.strip(),
        "WORKER_BOOTSTRAP_SECTION": bootstrap.strip(),
    }


def multi_role_values(data: dict[str, Any]) -> dict[str, str]:
    enabled = normalize_bool(data.get("multi_role_automations_allowed"), False)
    profile = normalize_role_profile(data.get("automation_role_profile"), enabled)
    checkpoint_commits = normalize_bool(data.get("automation_checkpoint_commits"), True)
    cadence_minutes = normalize_multi_role_cadence(data.get("multi_role_base_cadence_minutes"))
    schedule_strategy = normalize_schedule_strategy(data.get("automation_schedule_strategy"), enabled)
    allow_remotes = normalize_bool(data.get("multi_role_allow_remotes"), False)

    if enabled:
        automation_section = f"""Multi-role automations allowed: true

Role profile: `{profile}`

Automation schedule strategy: `{schedule_strategy}`

Planner cadence: hourly at minute `0`

Builder cadence: minutes `10` and `40`

Hardener cadence: minutes `20` and `50`

Integrator cadence: minutes `25` and `55`

The current single-lane automation remains valid for manual runs. Scheduled multi-role mode uses local role prompts under `.agentic/roles/`, isolated git worktrees under `target/automation_worktrees/`, queued patches under `target/automation_queue/`, and durable progress state in `docs/MULTI_ROLE_PROGRESS.md`.

Dashboard scheduling can use the fixed multi-role cadence or the continuous conveyor. The conveyor is one local launchd job that chooses the next runnable lane from current state, prioritizing queued integration first, fast-follow replanning after a planner patch is newly deferred or a planner deferral is resolved, due planning second, builder momentum by default, and one hardener pass after integrated builder work.

Multi-role mode is local-only. Roles must never push, fetch, pull, clone with remote tracking, configure remotes, set upstream tracking, or run any git command that touches a remote. Local commits, local branches, local tags, and local worktrees are allowed. Any remote-touching attempt is a `CRITICAL_STOP`.

Planner, builder, and hardener start from the latest main `HEAD` at run start. They may see partially integrated state from earlier patches in the same cycle; this is accepted. The integrator owns the main checkout, applies queued patches FIFO, verifies, creates local checkpoint commits, updates `docs/CODEX_AUTOMATION_TASKS.md`, updates `docs/MULTI_ROLE_PROGRESS.md`, and enforces retention."""
        guardrails = """- Multi-role automation is enabled but optional; the single-lane wrapper remains valid.
- Multi-role role runs require an initialized local git repo.
- Multi-role mode is local-only: never push, fetch, pull, clone with remote tracking, configure remotes, set upstream tracking, or run git commands that touch a remote.
- Role scripts must refuse to run when `git remote -v` is non-empty unless `MULTI_ROLE_ALLOW_REMOTES=1`.
- Integrator owns main-checkout mutation, local checkpoint commits, FIFO patch application, verification, task-state updates, and `docs/MULTI_ROLE_PROGRESS.md`.
- Planner, builder, and hardener must use isolated worktrees and queue patches instead of mutating the main checkout.
- Integrator must checkpoint dirty main changes as-is before applying queued patches; do not revert or discard human changes.
- Integrator must defer conflicting, stale, guardrail-violating, or verification-failing patches with machine-readable deferral reasons."""
        task_notes = f"""Multi-role automations allowed: true

- Role profile: `{profile}`
- Automation schedule strategy: `{schedule_strategy}`
- Planner runs hourly at minute `0`; builder, hardener, and integrator run on staggered half-hour offsets.
- Continuous conveyor mode is available through `scripts/run_conveyor_automation.sh`; it prioritizes queued integration first, fast-follow replanning after a planner patch is newly deferred or a planner deferral is resolved, due planning second, builder momentum by default, and one hardener pass after integrated builder work.
- Integrator maintains `docs/MULTI_ROLE_PROGRESS.md` and local checkpoint commits.
- Deferred patches remain visible through `scripts/list_deferred_patches.py`; use `python3 scripts/list_deferred_patches.py . --markdown` for grouped local triage or add `--decision-template` for a per-manifest cleanup worksheet.
- Local-only safety: no pushes, fetches, pulls, remote configuration, upstream tracking, or remote-touching git commands."""
        development = f"""Multi-role automations allowed: true

Role profile: `{profile}`

Automation schedule strategy: `{schedule_strategy}`

Use dashboard scheduling for staggered role jobs or the continuous conveyor. The conveyor keeps work moving by running the next useful lane as soon as the previous lane finishes:

```bash
bash scripts/run_conveyor_automation.sh --dry-run
bash scripts/run_conveyor_automation.sh --once
```

You can still run a role manually:

```bash
bash scripts/run_role_automation.sh --role planner
bash scripts/run_role_automation.sh --role builder
bash scripts/run_role_automation.sh --role hardener
bash scripts/run_role_automation.sh --role integrator
```

Review deferred backlog triage without mutating the repo:

```bash
python3 scripts/list_deferred_patches.py . --markdown
python3 scripts/list_deferred_patches.py . --decision-template
```

The Markdown view groups the backlog by reason and recommended local action. The decision template adds per-manifest fields for archive, replace-from-current-HEAD, repair-and-retry, retry-as-is, or keep-deferred choices during integrator cleanup.

The target must be an initialized git repo. Multi-role mode creates local worktrees, local queue artifacts, and local commits only. It never pushes."""
        bootstrap = f"""Multi-role automations allowed: true

Role profile: `{profile}`

Automation schedule strategy: `{schedule_strategy}`

After bootstrap, ensure this target is an initialized git repo before enabling scheduled multi-role automation. The recurring role prompts, conveyor, and helpers are generated locally; no remote git operations are allowed."""
    else:
        automation_section = """Multi-role automations allowed: false

This project uses the default single-lane automation wrapper unless the intake is explicitly updated to enable multi-role mode. The continuous conveyor wrapper is still available as an optional local scheduler; without multi-role files it falls back to the single-lane wrapper."""
        guardrails = "- Multi-role automations are disabled unless the project intake explicitly enables them."
        task_notes = """Multi-role automations allowed: false

- Use the default single-lane scheduled automation."""
        development = """Multi-role automations allowed: false

Use the default `scripts/run_codex_automation.sh` schedule unless the project intake is explicitly updated."""
        bootstrap = """Multi-role automations allowed: false

Use the default single-lane automation after bootstrap."""

    return {
        "MULTI_ROLE_AUTOMATIONS_ALLOWED": str(enabled).lower(),
        "AUTOMATION_ROLE_PROFILE": profile,
        "AUTOMATION_CHECKPOINT_COMMITS": str(checkpoint_commits).lower(),
        "MULTI_ROLE_BASE_CADENCE_MINUTES": str(cadence_minutes),
        "AUTOMATION_SCHEDULE_STRATEGY": schedule_strategy,
        "MULTI_ROLE_ALLOW_REMOTES": str(allow_remotes).lower(),
        "MULTI_ROLE_AUTOMATION_SECTION": automation_section.strip(),
        "MULTI_ROLE_GUARDRAILS_POLICY": guardrails.strip(),
        "MULTI_ROLE_TASK_NOTES": task_notes.strip(),
        "MULTI_ROLE_DEVELOPMENT_SECTION": development.strip(),
        "MULTI_ROLE_BOOTSTRAP_SECTION": bootstrap.strip(),
    }


def automation_signal_values(data: dict[str, Any]) -> dict[str, str]:
    enabled = normalize_bool(data.get("automation_signals_enabled"), False)
    if enabled:
        section = """Automation signals enabled: true

At run start, refresh recurring signal state with:

```bash
python3 scripts/update_automation_signals.py . --refresh --summary
```

Signals are local nudges defined in `docs/AUTOMATION_SIGNALS.md` and tracked at runtime in `target/automation_signals.json`. They do not override guardrails or task state. When a role acts on a signal, it should mark it complete with `scripts/update_automation_signals.py --complete` and record the decision in its normal summary."""
        development = """Automation signals enabled: true

Signal definitions live in `docs/AUTOMATION_SIGNALS.md`; runtime state lives in `target/automation_signals.json`.

```bash
python3 scripts/update_automation_signals.py . --refresh --summary
python3 scripts/update_automation_signals.py . --complete prompt-self-audit --role planner --note "Reviewed prompt scope."
```"""
        task_notes = """Automation signals enabled: true

- Signal definitions: `docs/AUTOMATION_SIGNALS.md`
- Runtime state: `target/automation_signals.json`
- Signals are recurring nudges only; they never override guardrails, active human requests, or the current sprint."""
        bootstrap = """Automation signals enabled: true

Use `docs/AUTOMATION_SIGNALS.md` for recurring local review nudges such as prompt self-audits, validation sweeps, deferred-patch triage, and human inbox triage."""
        file_reads = """docs/AUTOMATION_SIGNALS.md
target/automation_signals.json"""
    else:
        section = """Automation signals enabled: false

Use normal task-file and human-inbox state unless the project intake explicitly enables recurring automation signals."""
        development = """Automation signals enabled: false

The signal updater script is available for future opt-in, but no signal definitions are generated by default."""
        task_notes = """Automation signals enabled: false

- Use normal task-file state unless the intake explicitly enables signals."""
        bootstrap = """Automation signals enabled: false

Use normal task-file state unless the project intake explicitly enables recurring automation signals."""
        file_reads = ""

    return {
        "AUTOMATION_SIGNALS_ENABLED": str(enabled).lower(),
        "AUTOMATION_SIGNALS_SECTION": section.strip(),
        "AUTOMATION_SIGNALS_DEVELOPMENT_SECTION": development.strip(),
        "AUTOMATION_SIGNALS_TASK_NOTES": task_notes.strip(),
        "AUTOMATION_SIGNALS_BOOTSTRAP_SECTION": bootstrap.strip(),
        "AUTOMATION_SIGNAL_FILE_READS": file_reads,
    }


def parse_markdown_intake(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    data: dict[str, Any] = {}

    title = re.search(r"^#\s+Project Intake:\s*(.+)$", text, re.MULTILINE)
    if title:
        data["project_name"] = title.group(1).strip()

    matches = list(re.finditer(r"^##\s+(.+?)\s*$", text, re.MULTILINE))
    for index, match in enumerate(matches):
        heading = match.group(1).strip().lower()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        key = HEADING_TO_KEY.get(heading)
        if key:
            data[key] = text[start:end].strip()
    return data


def parse_intake(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json" or text.lstrip().startswith(("{", "[")):
        return json.loads(text)
    return parse_markdown_intake(path)


def bridge_values(mode: str, text_responses: bool) -> dict[str, str]:
    enabled = mode != "disabled"
    file_reads = ""
    if enabled:
        file_reads = """docs/HUMAN_REQUESTS.md
docs/HUMAN_INBOX.md
docs/HUMAN_OUTBOX.md
docs/HUMAN_RESPONSES_ARCHIVE.md"""

    if mode in {"local_notifier", "discord_notifier"}:
        channel_note = (
            "Discord notifier mode posts progress updates to the configured progress channel, "
            "direct human messages to the configured messaging channel, and captures only bot mentions/replies "
            "from the messaging channel into `docs/HUMAN_INBOX.md`. Local automation commits trigger brief "
            "`event_kind: \"progress\"` updates with the commit subject and work summary."
            if mode == "discord_notifier"
            else "Local notifier mode uses the same loopback API for native desktop notifications only; Discord is not required."
        )
        agents_read = """If human bridge files exist, also read:

```text
docs/HUMAN_REQUESTS.md
docs/HUMAN_INBOX.md
docs/HUMAN_OUTBOX.md
docs/HUMAN_RESPONSES_ARCHIVE.md
```"""
        agents_rules = """- Process human inbox messages, including freeform commands.
- If the human asks to be messaged or sent a status update, use the local notifier API when available instead of only writing Markdown.
- Process handled human inbox messages only after completing or intentionally deferring the requested action, then archive concise notes."""
        run_steps = """1. Classify and handle new human inbox messages, including freeform commands.
1. If a human message asks to be messaged, replied to, or sent a summary/status update, send a concise `event_kind: "message"` notification through the local notifier API.
1. Resolve any handled human replies from `docs/HUMAN_INBOX.md`.
1. Remove handled messages from `docs/HUMAN_INBOX.md` only after the requested action has actually been completed or intentionally deferred.
1. Archive concise notes to `docs/HUMAN_RESPONSES_ARCHIVE.md`."""
        protocol = f"""Human bridge enabled: true

Human bridge mode: `{mode}`

Use the human owner as an asynchronous resource for manual unlocks and high-leverage direction, not as an implementation worker.

This project may use a separate local notifier service if it is running:

```text
POST http://127.0.0.1:8765/api/notify
```

{channel_note} This target project must not inspect, clone, import, or modify the notifier service during normal automation runs. This project must not handle Discord credentials.

### Human Inbox Interpretation

At the beginning of every run, read `docs/HUMAN_INBOX.md`.

Human inbox entries can be structured replies such as `HR-001 DONE` or freeform instructions such as `send me a summary of what you've accomplished so far`. Interpret natural language intent; do not treat every freeform message as a request to create a local file.

If the human asks to be messaged, replied to, or sent a summary/status update, create a concise response and send it via `POST http://127.0.0.1:8765/api/notify` with `event_kind: "message"`. Human-unlock requests, blockers that need human input, and replies to user messages also use `event_kind: "message"` so they route to the messaging channel. Do not satisfy that request only by writing a local Markdown file. You may also update local docs, but the primary requested action is outbound notification.

If the human explicitly asks for a local document, report, Markdown file, artifact, or dashboard page, create the local artifact. Send a notifier message only if the human also asked for a direct message.

### Outbound Message Style

Notifier responses should be concise but useful: summarize the work done, checks run, current blocker, and next step. Avoid secrets, raw stack traces, and long reports.

Progress-only updates should use `event_kind: "progress"`. Direct human messages, blockers, human-unlock requests, and replies to user messages should use `event_kind: "message"`. In `discord_notifier` mode, `scripts/integrate_role_outputs.py` sends a brief progress-channel notification after each local automation commit it creates.

Payload shape for direct human-requested outbound responses:

```json
{{
  "request_id": "MSG-YYYY-MM-DD-001",
  "type": "human_requested_summary",
  "priority": "normal",
  "summary": "Progress summary requested by human",
  "event_kind": "message",
  "message_body": "{{PROJECT_NAME}} update: <concise summary body>",
  "agent_recommendation": "No action needed unless you want to review the generated artifacts.",
  "minimum_user_action": "None.",
  "reply_format": "Optional: reply with a follow-up request.",
  "unblocked_work_remaining": ["Continue current automation sprint"],
  "dedupe_key": "MSG-YYYY-MM-DD-001:v1",
  "expects_reply": false
}}
```

If the notifier is not reachable:

1. Do not claim a message was delivered.
2. Write the intended outbound message to `docs/HUMAN_OUTBOX.md` with status `NOTIFIER_UNREACHABLE`.
3. Keep or annotate the inbox entry as unresolved if a response is required.
4. Continue useful offline/product work.
5. Set status to `ACTIVE_WITH_PENDING_USER_INPUT` only if the unresolved item matters and useful work remains."""
        guardrails = """- Ask the human only for meaningful unlocks.
- For reversible choices, choose a safe default and document it.
- Use `ACTIVE_WITH_PENDING_USER_INPUT` when work can continue around a pending request.
- Use `POST http://127.0.0.1:8765/api/notify` when the local notifier is available; otherwise fall back to `docs/HUMAN_REQUESTS.md`.
- The notifier owns Discord credentials and local notification delivery. This repo must not import notifier code or print, copy, store, or commit notifier credential values.
- If the human asks to be messaged or sent a summary/status update, send a concise notifier response rather than only writing Markdown.
- If the notifier is unreachable, do not claim delivery. Record `NOTIFIER_UNREACHABLE` in `docs/HUMAN_OUTBOX.md` and continue useful work.
- Remove handled entries from `docs/HUMAN_INBOX.md` only after the requested action is complete or intentionally deferred, and archive concise notes in `docs/HUMAN_RESPONSES_ARCHIVE.md`."""
        task_notes = f"""Human bridge mode: `{mode}`

- The automation must read `docs/HUMAN_INBOX.md` at run start, interpret structured replies and freeform commands, remove handled entries only after completion or intentional deferral, and archive concise notes in `docs/HUMAN_RESPONSES_ARCHIVE.md`.
- If the local notifier is running, this project may call `POST http://127.0.0.1:8765/api/notify`.
- Direct human messages should use `event_kind: "message"`; progress updates should use `event_kind: "progress"`.
- In `discord_notifier` mode, each local automation commit created by the multi-role integrator sends a brief `event_kind: "progress"` update with the commit subject and work summary.
- If the notifier is unavailable, record the intended outbound message in `docs/HUMAN_OUTBOX.md` with status `NOTIFIER_UNREACHABLE` and continue useful work."""
        inbox = f"""# Human Inbox

Active inbox for replies from the human owner.

{('The Discord notifier writes captured bot mentions/replies from the messaging channel here. The human may also paste replies here manually.' if mode == 'discord_notifier' else 'The human may paste replies here manually. Local notifier mode does not require Discord inbound replies.')}

At the start of every automation run, Codex should:

1. read this file
2. handle any `status: unhandled` messages, including structured replies and freeform commands
3. update related requests in `docs/HUMAN_REQUESTS.md`
4. send a notifier response if the human asked to be messaged or sent a status update
5. remove handled messages from this file only after the requested action is complete or intentionally deferred
6. append concise records to `docs/HUMAN_RESPONSES_ARCHIVE.md`

Keep this file short. It is not a permanent log.

## Active Inbound Messages

None.

## Entry Template

```markdown
### INBOX-YYYY-MM-DD-001

- received_at: YYYY-MM-DDTHH:MM:SS
- channel: discord
- request_id: HR-YYYY-MM-DD-001
- status: unhandled

#### Body

HR-001 DONE. Key added locally.
```"""
        outbox = """# Human Outbox

Lightweight audit log of outbound human notifications sent or attempted through the local notifier service.

Use this file for:

- human-unlock requests sent through the notifier
- direct status/update responses sent because the human asked to be messaged
- failed notifier attempts with status `NOTIFIER_UNREACHABLE`, `DISCORD_SEND_FAILED`, or `LOCAL_NOTIFICATION_FAILED`

Do not write secrets, raw stack traces, or long reports here.

## Outbound Notifications

None yet.
"""
        setup = f"""# Human Bridge Setup

This project uses `{mode}` mode.

Run Diffmogger's bundled local notifier service separately:

```text
services/agentic-notifier/
```

Project automation calls:

```text
POST http://127.0.0.1:8765/api/notify
```

{channel_note}

The notifier owns credentials, dedupe state, optional JSONL queues, Discord inbound handling, and native desktop notification delivery. This repo must not print, copy, store, or commit notifier credential values.

## Inbox Handling Rules

- Treat `docs/HUMAN_INBOX.md` as an active queue, not a permanent log.
- Handle structured replies such as `HR-001 DONE` and freeform commands.
- Remove handled inbox entries only after the requested action is complete or intentionally deferred.
- Archive concise resolution notes in `docs/HUMAN_RESPONSES_ARCHIVE.md`.
- Record outbound messages and notifier failures in `docs/HUMAN_OUTBOX.md`.
"""
    elif mode == "file_only":
        agents_read = """If human bridge files exist, also read:

```text
docs/HUMAN_REQUESTS.md
docs/HUMAN_INBOX.md
docs/HUMAN_OUTBOX.md
docs/HUMAN_RESPONSES_ARCHIVE.md
```"""
        agents_rules = """- Process human inbox messages, including freeform commands.
- If the human asks for a summary, status update, explanation, or report, satisfy it locally in Markdown or app artifacts.
- Do not use Discord or notifier APIs unless the human explicitly changes bridge mode.
- Process handled human inbox messages only after completing or intentionally deferring the requested action, then archive concise notes."""
        run_steps = """1. Classify and handle new human inbox messages, including freeform commands.
1. Resolve any handled human replies from `docs/HUMAN_INBOX.md`.
1. Remove handled messages from `docs/HUMAN_INBOX.md` only after the requested action has actually been completed or intentionally deferred.
1. Archive concise notes to `docs/HUMAN_RESPONSES_ARCHIVE.md`."""
        protocol = """Human bridge enabled: true

Human bridge mode: `file_only`

Use file-only human intervention. Do not use Discord or notifier APIs for this project unless the human explicitly changes the bridge mode later.

The human owner will periodically inspect `docs/HUMAN_REQUESTS.md`, perform any manual action, and reply in `docs/HUMAN_INBOX.md`. If the human asks for a summary, status update, explanation, local report, or decision record, satisfy that request locally by updating the relevant Markdown file or app artifact."""
        guardrails = """- Ask the human only for meaningful unlocks.
- For reversible choices, choose a safe default and document it.
- Use `ACTIVE_WITH_PENDING_USER_INPUT` when work can continue around a pending request.
- Use file-only handoff files: write requests to `docs/HUMAN_REQUESTS.md`, read replies from `docs/HUMAN_INBOX.md`, and archive handled replies in `docs/HUMAN_RESPONSES_ARCHIVE.md`.
- Do not use Discord or notifier APIs unless the human explicitly changes the bridge mode.
- If the human asks for a summary or status update, answer locally in the requested Markdown/app artifact.
- Remove handled entries from `docs/HUMAN_INBOX.md` only after the requested action is complete or intentionally deferred."""
        task_notes = """Human bridge mode: `file_only`

- The automation must read `docs/HUMAN_INBOX.md` at run start, interpret structured replies and freeform commands, remove handled entries only after completion or intentional deferral, and archive concise notes in `docs/HUMAN_RESPONSES_ARCHIVE.md`.
- The human manually inspects `docs/HUMAN_REQUESTS.md` and replies in `docs/HUMAN_INBOX.md`.
- Do not use Discord or notifier APIs in this mode."""
        inbox = """# Human Inbox

Active inbox for replies from the human owner.

In file-only mode, the human manually pastes replies here after reading `docs/HUMAN_REQUESTS.md`. Do not use Discord or notifier APIs in file-only mode.

## Active Inbound Messages

None.
"""
        outbox = """# Human Outbox

File-only audit log of local outbound human-facing notes.

Use this file for concise records of local status summaries, request notices, or artifacts produced because the human asked for an update. Do not use it as a notifier delivery log in file-only mode.

## Outbound Records

None yet.
"""
        setup = """# Human Bridge Setup

This project uses file-only human intervention.

The automation writes active requests to `docs/HUMAN_REQUESTS.md`. The human manually replies in `docs/HUMAN_INBOX.md`. The next run consumes handled replies and archives concise notes.

No Discord, webhook, notifier API, or messaging credentials are used in this mode.
"""
    else:
        agents_read = "Human bridge files are not required unless the human later enables the bridge."
        agents_rules = "- Human bridge is disabled; do not create human request queues unless the human later enables the bridge."
        run_steps = "1. Skip human inbox processing because the human bridge is disabled for this project."
        protocol = """Human bridge enabled: false

Human bridge mode: `disabled`

Do not create human requests or wait for human replies during normal automation runs. If work becomes unsafe or impossible without the human, record the blocker in `docs/CODEX_AUTOMATION_TASKS.md` and use `BLOCKED_ON_USER` only when no useful work can continue."""
        guardrails = """- Human bridge is disabled.
- Do not create human request queues during normal runs.
- For reversible choices, choose a safe default and document it.
- Use `BLOCKED_ON_USER` only when no valuable work can continue without the human."""
        task_notes = "Human bridge mode: `disabled`. No human request queue is active."
        inbox = "# Human Inbox\n\nHuman bridge disabled for this project.\n"
        outbox = "# Human Outbox\n\nHuman bridge disabled for this project.\n"
        setup = "# Human Bridge Setup\n\nHuman bridge disabled for this project.\n"

    if mode in {"local_notifier", "discord_notifier"}:
        end_requirements = "- human requests created or resolved\n- human messages sent, including notifier delivery result\n"
        delivery_sentence = (
            "The project may call `POST http://127.0.0.1:8765/api/notify`; the notifier handles Discord/local notification delivery and credentials."
        )
        bootstrap_sentence = (
            "Use notifier mode. This repo may call `POST http://127.0.0.1:8765/api/notify` when the separate notifier service is running, but must not handle messaging credentials."
        )
    elif mode == "file_only":
        end_requirements = "- human inbox messages handled and local response artifacts created\n"
        delivery_sentence = "The human reads `docs/HUMAN_REQUESTS.md` and replies in `docs/HUMAN_INBOX.md`. The automation handles replies on later runs and archives them in `docs/HUMAN_RESPONSES_ARCHIVE.md`."
        bootstrap_sentence = "Use file-only mode. Create project-side human bridge files and do not use Discord or notifier APIs unless the human explicitly changes mode later."
    else:
        end_requirements = ""
        delivery_sentence = "No human bridge files are required for normal runs."
        bootstrap_sentence = "Human bridge disabled. Do not create human request queues unless the human later enables the bridge."

    development = f"""Human bridge enabled: {str(enabled).lower()}

Human bridge mode: `{mode}`

{delivery_sentence}
"""

    bootstrap = f"""Human bridge enabled: {str(enabled).lower()}

Human bridge mode: `{mode}`

{bootstrap_sentence}
"""

    return {
        "HUMAN_BRIDGE_ENABLED": str(enabled).lower(),
        "HUMAN_BRIDGE_MODE": mode,
        "HUMAN_FILE_READS": file_reads,
        "HUMAN_AGENTS_READ_BLOCK": agents_read,
        "HUMAN_AGENTS_RULES": agents_rules,
        "HUMAN_RUN_STEPS": run_steps,
        "HUMAN_PROTOCOL": protocol,
        "HUMAN_GUARDRAILS_POLICY": guardrails,
        "HUMAN_TASK_NOTES": task_notes,
        "HUMAN_INBOX_CONTENT": inbox,
        "HUMAN_OUTBOX_CONTENT": outbox,
        "HUMAN_BRIDGE_SETUP_CONTENT": setup,
        "HUMAN_END_REQUIREMENTS": end_requirements.rstrip(),
        "HUMAN_DEVELOPMENT_SECTION": development.strip(),
        "HUMAN_BOOTSTRAP_SECTION": bootstrap.strip(),
    }


def placeholders(data: dict[str, Any]) -> dict[str, str]:
    project_name = str(data.get("project_name") or data.get("summary") or "New Project").strip()
    mode = project_mode(data)
    bridge_mode = human_bridge_mode(data)
    text_responses = bridge_mode in {"local_notifier", "discord_notifier"} and normalize_bool(
        data.get("human_requested_text_responses"),
        True,
    )
    verification = normalize_lines(
        data.get("verification_commands"),
        "Add project-specific test, lint, build, or demo commands during bootstrap.",
    )
    env_values = env_access_values(data)
    values = {
        "PROJECT_NAME": project_name,
        "PROJECT_SLUG": slugify(project_name),
        "PROJECT_MODE": mode,
        "PROJECT_MODE_LABEL": project_mode_label(mode),
        "PROJECT_MODE_GUIDANCE": project_mode_guidance(mode),
        "PRODUCT_GOAL": normalize_lines(data.get("product_goal"), "Build a useful local-first product from the intake brief."),
        "TARGET_USER": normalize_lines(data.get("target_user"), "The primary user described in the intake brief."),
        "DESIRED_FIRST_DEMO": normalize_lines(data.get("desired_first_demo"), "A runnable local demo that proves the core workflow."),
        "TECH_PREFERENCES": normalize_lines(data.get("tech_preferences"), "Use the existing repo stack or choose a simple, well-supported default."),
        "HARD_CONSTRAINTS": normalize_lines(data.get("hard_constraints"), "Keep the first demo local-first and reviewable."),
        "SAFETY_CONSTRAINTS": normalize_lines(data.get("safety_constraints"), "No secrets, paid actions, public deploys, or real-world side effects without approval."),
        "AUTOMATION_MUST_NEVER_DO": normalize_lines(data.get("automation_must_never_do"), env_values["AUTOMATION_MUST_NEVER_DO_DEFAULT"]),
        "EXTERNAL_SERVICES": normalize_lines(data.get("external_services"), "None required for the first demo."),
        "ADDITIONAL_CONTEXT_FILES": normalize_lines(data.get("additional_context_files"), "No additional context files provided."),
        "VERIFICATION_COMMANDS": verification,
        "VERIFICATION_COMMANDS_INLINE": re.sub(r"\s+", " ", verification.replace("`", "")).strip(),
        "CADENCE": normalize_lines(data.get("desired_cadence"), "every 60 minutes"),
        "MEANINGFUL_DELIVERABLE": normalize_lines(data.get("meaningful_deliverable"), "A runnable, verified increment."),
        "BEYOND_MVP": normalize_lines(data.get("beyond_mvp"), "Continue improving core value, demo quality, integrations, and automation reliability."),
        "LONG_RUN_DIRECTION": normalize_lines(data.get("beyond_mvp"), "Continue improving core value, demo quality, integrations, and automation reliability."),
        "ASSUMPTIONS": normalize_lines(data.get("assumptions"), "Assumptions should be documented during bootstrap."),
        "CREATED_AT": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    values.update(progression_values(data, project_name))
    values.update(worker_values(data))
    values.update(env_values)
    values.update(multi_role_values(data))
    values.update(automation_signal_values(data))
    values.update(ticket_run_values(data))
    values.update(bridge_values(bridge_mode, text_responses))
    return values


def render_template(text: str, values: dict[str, str]) -> str:
    # Some mode-specific blocks contain ordinary placeholders such as
    # {{PROJECT_NAME}}. A short fixed-point pass keeps the template language
    # simple without requiring conditionals.
    for _ in range(3):
        before = text
        for key, value in values.items():
            text = text.replace("{{" + key + "}}", value)
        if text == before:
            break
    return text


def diffmogger_local_exclude_patterns(values: dict[str, str]) -> list[str]:
    patterns: set[str] = set(DIFFMOGGER_RUNTIME_EXCLUDE_PATTERNS)
    for template_path in sorted(TEMPLATE_ROOT.rglob("*")):
        if template_path.is_dir():
            continue
        if "__pycache__" in template_path.parts or template_path.suffix == ".pyc":
            continue
        rel = template_path.relative_to(TEMPLATE_ROOT).as_posix()
        if values.get("HUMAN_BRIDGE_MODE") == "disabled" and rel in HUMAN_BRIDGE_FILES:
            continue
        if values.get("AUTOMATION_SIGNALS_ENABLED") != "true" and rel in AUTOMATION_SIGNAL_FILES:
            continue
        if values.get("AUTOMATION_RUN_MODE") != "ticket_campaign" and rel in TICKET_RUN_FILES:
            continue
        if values.get("MULTI_ROLE_AUTOMATIONS_ALLOWED") != "true" and rel in MULTI_ROLE_FILES:
            continue
        if rel.startswith(".agentic/"):
            patterns.add("/.agentic/")
        else:
            patterns.add(f"/{rel}")
    patterns.add("/.pnpm-store/")
    return sorted(patterns)


def git_path(target: Path, path: str) -> Path | None:
    result = subprocess.run(
        ["git", "rev-parse", "--git-path", path],
        cwd=target,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    raw = result.stdout.strip()
    if not raw:
        return None
    resolved = Path(raw)
    if not resolved.is_absolute():
        resolved = target / resolved
    return resolved


def install_diffmogger_local_excludes(target: Path, values: dict[str, str]) -> list[str]:
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=target,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or result.stdout.strip() != "true":
        return []
    exclude = git_path(target, "info/exclude")
    if exclude is None:
        return []
    patterns = diffmogger_local_exclude_patterns(values)
    try:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    except OSError:
        return []
    lines = existing.splitlines()
    changed = False
    if "# Diffmogger local automation scaffold/runtime" not in lines:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("# Diffmogger local automation scaffold/runtime")
        changed = True
    for pattern in patterns:
        if pattern not in lines:
            lines.append(pattern)
            changed = True
    if changed:
        try:
            exclude.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        except OSError:
            return []
    return patterns


def managed_section_bounds(kind: str) -> tuple[str, str]:
    return (f"<!-- DIFFMOGGER:START {kind} -->", f"<!-- DIFFMOGGER:END {kind} -->")


def demote_markdown_headings(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
    demoted: list[str] = []
    for line in lines:
        if line.startswith("#"):
            hashes = len(line) - len(line.lstrip("#"))
            if hashes > 0 and len(line) > hashes and line[hashes] == " ":
                line = "#" + line
        demoted.append(line)
    return "\n".join(demoted).strip()


def render_managed_section(kind: str, rendered: str) -> str:
    start, end = managed_section_bounds(kind)
    body = demote_markdown_headings(rendered)
    return (
        f"{start}\n"
        "## Diffmogger Automation\n\n"
        "This block is managed by Diffmogger. Keep project-owned instructions outside this block.\n\n"
        f"{body}\n"
        f"{end}\n"
    )


def upsert_managed_section(existing: str, section: str, kind: str) -> str:
    start, end = managed_section_bounds(kind)
    pattern = re.compile(
        rf"{re.escape(start)}.*?{re.escape(end)}\s*",
        re.DOTALL,
    )
    if pattern.search(existing):
        return pattern.sub(section, existing).rstrip() + "\n"
    separator = "\n\n" if existing.rstrip() else ""
    return existing.rstrip() + separator + section


def scaffold(target: Path, values: dict[str, str], force: bool) -> list[Path]:
    written: list[Path] = []
    mode = values.get("PROJECT_MODE", "fresh_project")
    for template_path in sorted(TEMPLATE_ROOT.rglob("*")):
        if template_path.is_dir():
            continue
        if "__pycache__" in template_path.parts or template_path.suffix == ".pyc":
            continue
        rel = template_path.relative_to(TEMPLATE_ROOT)
        if values.get("HUMAN_BRIDGE_MODE") == "disabled" and rel.as_posix() in HUMAN_BRIDGE_FILES:
            continue
        if values.get("AUTOMATION_SIGNALS_ENABLED") != "true" and rel.as_posix() in AUTOMATION_SIGNAL_FILES:
            continue
        if values.get("AUTOMATION_RUN_MODE") != "ticket_campaign" and rel.as_posix() in TICKET_RUN_FILES:
            continue
        if values.get("MULTI_ROLE_AUTOMATIONS_ALLOWED") != "true" and rel.as_posix() in MULTI_ROLE_FILES:
            continue
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        rendered = render_template(template_path.read_text(encoding="utf-8"), values)
        managed_kind = MANAGED_EXISTING_PROJECT_FILES.get(rel.as_posix())
        if mode == "existing_project" and managed_kind and dest.exists():
            existing = dest.read_text(encoding="utf-8", errors="replace")
            section = render_managed_section(managed_kind, rendered)
            dest.write_text(upsert_managed_section(existing, section, managed_kind), encoding="utf-8")
            written.append(dest)
            continue
        if dest.exists() and not force:
            continue
        dest.write_text(rendered, encoding="utf-8")
        if rel.parts and rel.parts[0] == "scripts" and dest.suffix in {".sh", ".py"}:
            dest.chmod(0o755)
        written.append(dest)
    install_diffmogger_local_excludes(target, values)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intake", required=True, help="Markdown or JSON project intake file")
    parser.add_argument("--target", required=True, help="Target project directory")
    parser.add_argument("--force", action="store_true", help="Overwrite existing files")
    args = parser.parse_args()

    intake_path = Path(args.intake).resolve()
    target = Path(args.target).resolve()
    data = parse_intake(intake_path)
    values = placeholders(data)
    written = scaffold(target, values, args.force)

    print(f"Scaffolded {len(written)} files into {target}")
    for path in written:
        print(path.relative_to(target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
