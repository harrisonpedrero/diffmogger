from __future__ import annotations

import contextlib
import signal
import tempfile

from ..errors import *
from ..jsonio import *
from ..target import *

from .context import merge_context_files
from .diagnostics import run_subprocess
from .run_control import run_subprocess_streamed
from ..ticket_generation import (
    build_ticket_generation_snapshot,
    normalize_ticket_complexity,
    project_snapshot_prompt_block,
    ticket_coverage_guidance,
    ticket_generation_quality_gate,
    ticket_quality_warnings,
    ticket_sizing_policy_prompt,
    ticket_scope_groups_from_intake,
)
from diffmogger.runtime import ticket_run
from diffmogger.runtime.state_store import (
    connect,
    automation_control_state,
    database_path_for_target,
    open_blockers,
    upsert_blocker,
    write_automation_control_state,
)

DEFAULT_INTAKE_CODEX_TIMEOUT_SECONDS = 180
DEFAULT_TICKET_CODEX_TIMEOUT_SECONDS = 420
DEFAULT_TICKET_REFINEMENT_CODEX_TIMEOUT_SECONDS = 420
LOW_CORTISOL_FALLBACK_MAX_TICKETS = 120
BOOTSTRAP_PENDING_STATUSES = {"", "unknown", "pending", "not_bootstrapped", "not bootstrapped", "blocked"}
BOOTSTRAP_PRODUCT_COMMIT_MESSAGE = "chore(bootstrap): checkpoint runnable baseline"
BOOTSTRAP_SUCCESSFUL_CHECKPOINT_STATUSES = {"committed", "already_checkpointed", "already_tracked"}
STALE_BOOTSTRAP_CHECKPOINT_BLOCKER_TERMS = (
    ".git/index.lock",
    "initial local commit",
    "git metadata",
    "write access to .git",
)
BOOTSTRAP_PRODUCT_EXCLUDED_PREFIXES = (
    ".diffmogger/",
    ".agentic/",
    ".codex/",
    ".git/",
    "target/",
    "__pycache__/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    "node_modules/",
)
BOOTSTRAP_PRODUCT_EXCLUDED_NAMES = {
    "AGENTS.md",
    ".DS_Store",
}
BOOTSTRAP_PRODUCT_EXCLUDED_SUFFIXES = (
    ".pyc",
    ".pyo",
    ".sqlite",
    ".sqlite3",
    ".db",
    ".log",
    ".lock",
)
BOOTSTRAP_SCAFFOLD_INTERNALS = {
    "docs/CODEX_AUTOMATION_TASKS.md",
    "docs/INITIAL_BOOTSTRAP_PROMPT.md",
    "docs/MULTI_ROLE_PROGRESS.md",
    "docs/HUMAN_BRIDGE_SETUP.md",
    "docs/HUMAN_INBOX.md",
    "docs/HUMAN_OUTBOX.md",
    "docs/HUMAN_REQUESTS.md",
    "docs/HUMAN_RESPONSES_ARCHIVE.md",
    "docs/TICKET_RUN.md",
    "scripts/acquire_codex_lock.sh",
    "scripts/compact_agent_state.py",
    "scripts/integrate_role_outputs.py",
    "scripts/list_deferred_patches.py",
    "scripts/load_automation_env.py",
    "scripts/release_codex_lock.sh",
    "scripts/repair_environment.py",
    "scripts/run_conveyor_automation.py",
    "scripts/run_conveyor_automation.sh",
    "scripts/run_observatory.py",
    "scripts/run_process_watchdog.py",
    "scripts/run_role_automation.sh",
    "scripts/spawn_worker_agent.sh",
    "scripts/state_brief.py",
    "scripts/summarize_worker_outputs.py",
    "scripts/ticket_run.py",
}

LOW_CORTISOL_DEFAULT_INTAKE: dict[str, Any] = {
    "project_name": "New Project",
    "project_mode": "fresh_project",
    "product_goal": "Build a useful local-first project from the user's short build description.",
    "target_user": "The people described in the build request.",
    "desired_first_demo": "A runnable milestone that proves the core workflow.",
    "tech_preferences": ["Use the existing target stack when one is detected.", "Prefer a simple, well-supported local-first stack."],
    "hard_constraints": ["Keep the implementation local, reviewable, and easy to validate."],
    "safety_constraints": ["Do not store secrets in generated docs or code.", "Do not push, deploy, purchase, or modify production data without direct human instruction."],
    "automation_must_never_do": ["Never push to remotes without direct human instruction.", "Never modify credentials, production data, or paid services."],
    "external_services": ["None required for local execution."],
    "env_access_policy": "project_commands_only",
    "verification_commands": ["Run the project test suite.", "Run lint/typecheck/build commands when present."],
    "human_bridge_enabled": True,
    "human_bridge_mode": "file_only",
    "human_requested_text_responses": True,
    "local_notifications_enabled": True,
    "worker_agents_allowed": True,
    "codex_cli_workers_expected_on_broad_runs": True,
    "write_worker_agents_allowed": True,
    "max_write_worker_count": 3,
    "write_worker_guidance": "Use write workers as optional bounded acceleration when work splits into reviewable ownership scopes.",
    "parallel_execution_mode": "aggressive",
    "symbol_graph_languages": ["python", "typescript", "javascript"],
    "parallel_write_min_confidence": 0.75,
    "parallel_write_direct_confidence": 0.75,
    "max_parallel_write_workers": 3,
    "max_parallel_scope_workers": 2,
    "multi_role_automations_allowed": True,
    "automation_role_profile": "planner_builder_hardener_integrator",
    "automation_checkpoint_commits": True,
    "multi_role_allow_remotes": False,
    "optional_mcp_servers": [],
    "campaign_mode": "bounded",
    "ticket_run_file": "",
    "ticket_run_seed_tickets": [],
    "ticket_completion_notify": True,
    "meaningful_deliverable": "A runnable, verified increment toward the described project.",
    "beyond_mvp": "Continue through the remaining dashboard ticket queue in small, reviewable increments.",
    "assumptions": ["Generated from a short low-cortisol build description; ask through the dashboard when a decision is ambiguous."],
    "ticket_generation_complexity": "small",
    "ticket_generation_decomposition_brief": "Decompose the requested project scope into dependency-safe, reviewable ticket groups.",
    "ticket_generation_scope_groups": [],
    "ticket_generation_quality_warnings": [],
    "ticket_generation_refinement_needed": False,
    "ticket_generation_refinement_passed": True,
    "ticket_generation_scope_surface_floor": 0,
    "additional_context_files": [],
    "overwrite_existing_scaffold_files": False,
}


def _extract_json_payload(text: str, *, label: str) -> Any:
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", stripped)
    if fenced:
        try:
            return json.loads(fenced.group(1).strip())
        except json.JSONDecodeError:
            pass
    match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", stripped)
    if not match:
        raise BackendError(
            f"Codex did not return JSON {label}.",
            error_type="intake_generation_parse_failed",
            details={"stdout_excerpt": stripped[-1600:]},
        )
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise BackendError(
            f"Codex returned malformed JSON {label}.",
            error_type="intake_generation_parse_failed",
            details={"exception": str(exc), "stdout_excerpt": stripped[-1600:]},
        ) from exc


def _string_list(value: Any, fallback: list[str]) -> list[str]:
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        return items or list(fallback)
    if isinstance(value, str):
        items = [re.sub(r"^[-*]\s*", "", line.strip()) for line in value.splitlines()]
        items = [item for item in items if item]
        return items or list(fallback)
    return list(fallback)


def _string_value(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text or fallback


def _bool_value(value: Any, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return fallback
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return fallback


def _int_value(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed >= 0 else fallback


def _float_value(value: Any, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return parsed


def _compact_ticket_text(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+(?:and|plus|with)\s+", " / ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" .:-")
    return text[:120] or fallback


def _target_default_project_mode(target: Path) -> str:
    try:
        visible = [
            path
            for path in target.iterdir()
            if path.name not in {".git", ".diffmogger"} and not path.name.startswith(".DS_Store")
        ]
    except OSError:
        return "fresh_project"
    return "existing_project" if visible else "fresh_project"


def _normalize_low_cortisol_intake(
    target: Path,
    generated: Any,
    description: str,
    *,
    require_tickets: bool = True,
) -> dict[str, Any]:
    if not isinstance(generated, dict):
        raise BackendError(
            "Codex intake generation must return a JSON object.",
            error_type="intake_generation_parse_failed",
            details={"returned_type": type(generated).__name__},
        )

    payload = json.loads(json.dumps(LOW_CORTISOL_DEFAULT_INTAKE))
    payload.update(generated)

    text_fields = [
        "project_name",
        "product_goal",
        "target_user",
        "desired_first_demo",
        "env_access_policy",
        "write_worker_guidance",
        "automation_role_profile",
        "meaningful_deliverable",
        "beyond_mvp",
        "ticket_generation_complexity",
        "ticket_generation_decomposition_brief",
    ]
    for key in text_fields:
        payload[key] = _string_value(payload.get(key), str(LOW_CORTISOL_DEFAULT_INTAKE[key]))

    if payload["project_name"] == LOW_CORTISOL_DEFAULT_INTAKE["project_name"]:
        payload["project_name"] = target.name or "New Project"
    if payload["product_goal"] == LOW_CORTISOL_DEFAULT_INTAKE["product_goal"]:
        payload["product_goal"] = description.strip()

    project_mode = str(payload.get("project_mode") or "").strip()
    payload["project_mode"] = project_mode if project_mode in {"fresh_project", "existing_project"} else _target_default_project_mode(target)
    payload["env_access_policy"] = (
        payload["env_access_policy"]
        if payload["env_access_policy"] in {"project_commands_only", "direct_env_files_allowed"}
        else "project_commands_only"
    )

    for key in [
        "tech_preferences",
        "hard_constraints",
        "safety_constraints",
        "automation_must_never_do",
        "external_services",
        "verification_commands",
        "assumptions",
        "additional_context_files",
    ]:
        payload[key] = _string_list(payload.get(key), list(LOW_CORTISOL_DEFAULT_INTAKE[key]))

    payload["automation_role_profile"] = "planner_builder_hardener_integrator"
    payload["multi_role_automations_allowed"] = True

    payload["human_bridge_enabled"] = True
    payload["human_bridge_mode"] = "file_only"
    payload["human_requested_text_responses"] = _bool_value(payload.get("human_requested_text_responses"), True)
    payload["local_notifications_enabled"] = _bool_value(payload.get("local_notifications_enabled"), True)
    payload["worker_agents_allowed"] = _bool_value(payload.get("worker_agents_allowed"), True)
    payload["codex_cli_workers_expected_on_broad_runs"] = _bool_value(payload.get("codex_cli_workers_expected_on_broad_runs"), True)
    payload["write_worker_agents_allowed"] = True
    payload["max_write_worker_count"] = max(1, min(10, _int_value(payload.get("max_write_worker_count"), 3)))
    payload["parallel_execution_mode"] = (
        "conservative" if str(payload.get("parallel_execution_mode") or "").strip().lower() == "conservative" else "aggressive"
    )
    languages = payload.get("symbol_graph_languages")
    if not isinstance(languages, list):
        languages = ["python", "typescript", "javascript"]
    payload["symbol_graph_languages"] = [
        item
        for item in [str(language).strip().lower() for language in languages]
        if item in {"python", "typescript", "javascript"}
    ] or ["python", "typescript", "javascript"]
    payload["parallel_write_min_confidence"] = max(0.0, min(1.0, _float_value(payload.get("parallel_write_min_confidence"), 0.75)))
    payload["parallel_write_direct_confidence"] = max(
        0.0,
        min(1.0, _float_value(payload.get("parallel_write_direct_confidence"), 0.75)),
    )
    payload["max_parallel_write_workers"] = max(1, min(10, _int_value(payload.get("max_parallel_write_workers"), 3)))
    payload["max_parallel_scope_workers"] = max(1, min(10, _int_value(payload.get("max_parallel_scope_workers"), 2)))
    payload["automation_checkpoint_commits"] = _bool_value(payload.get("automation_checkpoint_commits"), True)
    payload["multi_role_allow_remotes"] = False
    payload["optional_mcp_servers"] = []
    payload["campaign_mode"] = "bounded"
    payload["ticket_run_file"] = ""
    payload["ticket_completion_notify"] = _bool_value(payload.get("ticket_completion_notify"), True)
    payload["overwrite_existing_scaffold_files"] = False
    payload["ticket_generation_complexity"] = normalize_ticket_complexity(payload.get("ticket_generation_complexity"))
    payload["ticket_generation_scope_groups"] = ticket_scope_groups_from_intake(payload)
    payload["ticket_generation_quality_warnings"] = [
        item for item in payload.get("ticket_generation_quality_warnings", []) if isinstance(item, dict)
    ] if isinstance(payload.get("ticket_generation_quality_warnings"), list) else []
    payload["ticket_generation_refinement_needed"] = _bool_value(payload.get("ticket_generation_refinement_needed"), False)
    payload["ticket_generation_refinement_passed"] = _bool_value(payload.get("ticket_generation_refinement_passed"), True)
    payload["ticket_generation_scope_surface_floor"] = _int_value(payload.get("ticket_generation_scope_surface_floor"), 0)

    seed_source = payload.get("ticket_run_seed_tickets")
    if not isinstance(seed_source, list):
        seed_source = payload.get("tickets")
    if not isinstance(seed_source, list):
        seed_source = []
    tickets = ticket_run.normalized_tickets([item for item in seed_source if isinstance(item, dict)])
    if not require_tickets:
        payload["ticket_run_seed_tickets"] = []
        return payload
    if not tickets:
        raise BackendError(
            "Codex did not return any ticket_run_seed_tickets.",
            error_type="intake_generation_no_tickets",
            details={"project_name": payload["project_name"]},
        )
    payload["ticket_run_seed_tickets"] = tickets

    return payload


def _low_cortisol_timeout_warning(
    *,
    warning_type: str,
    stage_label: str,
    timeout_seconds: Any,
) -> dict[str, Any]:
    seconds = _int_value(timeout_seconds, 0)
    if seconds:
        detail = (
            f"Codex {stage_label} timed out after {seconds} seconds; "
            "Diffmogger generated a conservative deterministic fallback."
        )
    else:
        detail = f"Codex {stage_label} timed out; Diffmogger generated a conservative deterministic fallback."
    return {
        "ticket_id": "",
        "type": warning_type,
        "detail": detail,
    }


def _fallback_scope_groups(description: str) -> list[dict[str, Any]]:
    goal = description.strip() or "the requested local project"
    return [
        {
            "name": "Project foundation",
            "description": goal[:500],
            "surfaces": ["project scaffold", "local development checks"],
        },
        {
            "name": "Core user workflow",
            "description": "Implement the primary local workflow described by the request.",
            "surfaces": ["primary workflow", "state persistence"],
        },
        {
            "name": "Reviewability",
            "description": "Keep the generated project easy to validate and hand off.",
            "surfaces": ["validation", "documentation"],
        },
    ]


def _fallback_low_cortisol_intake(target: Path, description: str) -> dict[str, Any]:
    generated = json.loads(json.dumps(LOW_CORTISOL_DEFAULT_INTAKE))
    generated.update(
        {
            "project_name": target.name or LOW_CORTISOL_DEFAULT_INTAKE["project_name"],
            "project_mode": _target_default_project_mode(target),
            "product_goal": description.strip() or LOW_CORTISOL_DEFAULT_INTAKE["product_goal"],
            "target_user": "The people described in the build request.",
            "desired_first_demo": "A runnable local milestone that proves the core requested workflow.",
            "ticket_generation_complexity": "small",
            "ticket_generation_decomposition_brief": (
                "Create a conservative local project foundation, core workflow, persistence, validation, and docs queue."
            ),
            "ticket_generation_scope_groups": _fallback_scope_groups(description),
        }
    )
    return _normalize_low_cortisol_intake(target, generated, description, require_tickets=False)


def _fallback_low_cortisol_tickets(
    intake: dict[str, Any],
    description: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups = ticket_scope_groups_from_intake(intake) or _fallback_scope_groups(description)
    verification = ["Run available project checks."]
    tickets: list[dict[str, Any]] = []
    truncated = False
    for group in groups:
        group_name = _compact_ticket_text(group.get("name"), "project scope")
        surfaces = _string_list(group.get("surfaces"), [group_name])
        for surface in surfaces:
            if len(tickets) >= LOW_CORTISOL_FALLBACK_MAX_TICKETS:
                truncated = True
                break
            surface_name = _compact_ticket_text(surface, group_name)
            ticket_id = f"TICKET-{len(tickets) + 1:03d}"
            tickets.append(
                {
                    "id": ticket_id,
                    "summary": f"Deliver {surface_name} for {group_name}",
                    "status": "pending",
                    "depends_on": [],
                    "acceptance_criteria": [
                        f"{surface_name} has a focused implementation for {group_name}.",
                        "Scope stays within this ticket's named deliverable.",
                    ],
                    "verification_commands": verification,
                    "evidence": [],
                    "related_commits": [],
                    "blocker": "",
                }
            )
        if truncated:
            break
    warnings: list[dict[str, Any]] = []
    if truncated:
        warnings.append(
            {
                "ticket_id": "",
                "type": "fallback_ticket_limit_reached",
                "detail": (
                    f"Fallback ticket generation stopped at {LOW_CORTISOL_FALLBACK_MAX_TICKETS} tickets; "
                    "split or add remaining scope from the dashboard if needed."
                ),
            }
        )
    return ticket_run.normalized_tickets(tickets), warnings


def _low_cortisol_intake_prompt(target: Path, description: str) -> str:
    snapshot = build_ticket_generation_snapshot(target, include_intake=True)
    current_intake = load_intake(target)
    current_draft = load_dashboard_state(target).get("brief_draft_intake") or {}
    intake_fields = [key for key in LOW_CORTISOL_DEFAULT_INTAKE.keys() if key != "ticket_run_seed_tickets"]
    return "\n".join(
        [
            "Generate a normalized Diffmogger project intake from a short build request.",
            "Return JSON only: one object with Diffmogger intake fields.",
            "Do not return final seed tickets in this pass; set ticket_run_seed_tickets to an empty array if you include the field.",
            "",
            "Hard requirements:",
            "- Set campaign_mode to bounded.",
            "- Leave ticket_run_file empty; ticket scope is stored in the dashboard-backed SQLite ticket queue.",
            "- Classify ticket_generation_complexity as one of tiny, small, medium, or large.",
            "- Add ticket_generation_decomposition_brief with a concise full-scope decomposition plan, not ticket objects.",
            "- Add ticket_generation_scope_groups as a compact array of scope groups. Each group should have name, description, and surfaces.",
            "- Decompose the full requested project scope, not just an initial demo path.",
            "- Set automation_role_profile to planner_builder_hardener_integrator. Diffmogger uses a typed execution DAG scheduler.",
            "- Set parallel_execution_mode to aggressive, symbol_graph_languages to python/typescript/javascript, parallel_write_min_confidence and parallel_write_direct_confidence to 0.75, max_parallel_write_workers to 3, and max_parallel_scope_workers to 2 unless the request clearly needs stricter local limits.",
            "- Set optional_mcp_servers to an empty array. Context7 and Playwright MCPs are disabled by default.",
            "- Set human_bridge_enabled true and human_bridge_mode to file_only.",
            "- Keep the intake reusable and target-project agnostic. Do not include secrets.",
            "- Keep assumptions concise and explicit.",
            "",
            ticket_sizing_policy_prompt(),
            "",
            "Fields to return:",
            json.dumps(intake_fields, indent=2),
            "",
            "Bounded target project snapshot JSON:",
            project_snapshot_prompt_block(snapshot),
            "",
            "Current intake JSON, if any:",
            json.dumps(current_intake, indent=2, sort_keys=True, default=json_default),
            "",
            "Current dashboard draft JSON, if any:",
            json.dumps(current_draft, indent=2, sort_keys=True, default=json_default),
            "",
            "Build request:",
            description.strip(),
        ]
    )


def _low_cortisol_ticket_prompt(target: Path, description: str, intake: dict[str, Any]) -> str:
    complexity = normalize_ticket_complexity(intake.get("ticket_generation_complexity"))
    snapshot = build_ticket_generation_snapshot(target, include_intake=True)
    scope_groups = ticket_scope_groups_from_intake(intake)
    return "\n".join(
        [
            "Generate the complete Diffmogger ticket_run_seed_tickets queue for the normalized intake.",
            "Return JSON only: one object with ticket_run_seed_tickets and optional quality_notes.",
            "Do not include prose outside JSON. Do not modify files.",
            "",
            ticket_sizing_policy_prompt(complexity),
            "",
            "Ticket requirements:",
            f"- {ticket_coverage_guidance(complexity)}",
            "- Generate a whole execution queue for the full requested scope, not a capped demo plan.",
            "- Use the decomposition brief and scope groups as coverage requirements.",
            "- If the requested scope has many real surfaces, return many tickets rather than broad tickets.",
            "- Use pending status for every ticket.",
            "- Ticket ids must be TICKET-001, TICKET-002, and so on.",
            "- Each ticket must include id, summary, status, depends_on, acceptance_criteria, verification_commands, evidence, related_commits, and blocker.",
            "- Dependencies must point only to earlier seed ticket ids when a real dependency exists.",
            "- Each summary and acceptance list must identify the component, surface, workflow, or artifact being changed.",
            "- Keep every ticket generic and target-project agnostic; do not include secrets.",
            "",
            "Normalized intake JSON:",
            json.dumps(intake, indent=2, sort_keys=True, default=json_default),
            "",
            "Ticket generation scope groups JSON:",
            json.dumps(scope_groups, indent=2, sort_keys=True, default=json_default),
            "",
            "Bounded target project snapshot JSON:",
            project_snapshot_prompt_block(snapshot),
            "",
            "Original build request:",
            description.strip(),
        ]
    )


def _low_cortisol_refinement_prompt(
    target: Path,
    description: str,
    intake: dict[str, Any],
    seed_tickets: list[dict[str, Any]],
    quality_gate: dict[str, Any],
) -> str:
    complexity = normalize_ticket_complexity(intake.get("ticket_generation_complexity"))
    snapshot = build_ticket_generation_snapshot(target, include_intake=True)
    scope_groups = ticket_scope_groups_from_intake(intake)
    return "\n".join(
        [
            "Refine a Diffmogger seed ticket queue that appears under-decomposed.",
            "Return JSON only: one object with a complete replacement ticket_run_seed_tickets array and optional quality_notes.",
            "Do not include prose outside JSON. Do not modify files.",
            "",
            ticket_sizing_policy_prompt(complexity),
            "",
            "Refinement requirements:",
            "- Preserve useful tickets when they are already appropriately granular.",
            "- Split broad tickets into one reviewable local patch with one primary deliverable.",
            "- Add missing tickets for uncovered decomposition groups and surfaces.",
            "- Generate as many tickets as the full described scope needs; do not impose a fixed maximum.",
            "- Keep dependencies pointing only to earlier ticket ids when a real dependency exists.",
            "- Keep every ticket generic and target-project agnostic; do not include secrets.",
            "",
            "Normalized intake JSON:",
            json.dumps(intake, indent=2, sort_keys=True, default=json_default),
            "",
            "Ticket generation scope groups JSON:",
            json.dumps(scope_groups, indent=2, sort_keys=True, default=json_default),
            "",
            "Quality gate JSON:",
            json.dumps(quality_gate, indent=2, sort_keys=True, default=json_default),
            "",
            "Current generated ticket_run_seed_tickets JSON:",
            json.dumps(seed_tickets, indent=2, sort_keys=True, default=json_default),
            "",
            "Bounded target project snapshot JSON:",
            project_snapshot_prompt_block(snapshot),
            "",
            "Original build request:",
            description.strip(),
        ]
    )


def _extract_seed_tickets_payload(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        seed_source = raw
    elif isinstance(raw, dict):
        seed_source = raw.get("ticket_run_seed_tickets")
        if not isinstance(seed_source, list):
            seed_source = raw.get("tickets")
    else:
        seed_source = []
    if not isinstance(seed_source, list):
        seed_source = []
    return [item for item in seed_source if isinstance(item, dict)]


def _codex_timeout_seconds(env_names: tuple[str, ...], default: int) -> int:
    for env_name in env_names:
        raw = os.environ.get(env_name, "").strip()
        if not raw:
            continue
        try:
            parsed = int(raw)
        except ValueError:
            continue
        return max(15, parsed)
    return default


def _intake_codex_timeout_seconds() -> int:
    return _codex_timeout_seconds(
        (
            "DIFFMOGGER_INTAKE_CODEX_TIMEOUT_SECONDS",
            "DIFFMOGGER_CODEX_GENERATION_TIMEOUT_SECONDS",
        ),
        DEFAULT_INTAKE_CODEX_TIMEOUT_SECONDS,
    )


def _ticket_codex_timeout_seconds() -> int:
    return _codex_timeout_seconds(
        (
            "DIFFMOGGER_TICKET_CODEX_TIMEOUT_SECONDS",
            "DIFFMOGGER_CODEX_GENERATION_TIMEOUT_SECONDS",
            "DIFFMOGGER_INTAKE_CODEX_TIMEOUT_SECONDS",
        ),
        DEFAULT_TICKET_CODEX_TIMEOUT_SECONDS,
    )


def _ticket_refinement_codex_timeout_seconds() -> int:
    return _codex_timeout_seconds(
        (
            "DIFFMOGGER_TICKET_REFINEMENT_CODEX_TIMEOUT_SECONDS",
            "DIFFMOGGER_TICKET_CODEX_TIMEOUT_SECONDS",
            "DIFFMOGGER_CODEX_GENERATION_TIMEOUT_SECONDS",
            "DIFFMOGGER_INTAKE_CODEX_TIMEOUT_SECONDS",
        ),
        DEFAULT_TICKET_REFINEMENT_CODEX_TIMEOUT_SECONDS,
    )


def _terminate_process_group(proc: subprocess.Popen[str]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        proc.terminate()
    try:
        proc.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except OSError:
        proc.kill()
    proc.wait()


def _run_codex_intake_generation(
    prompt: str,
    *,
    cwd: Path,
    timeout_seconds: int,
    stage_label: str = "intake generation",
    timeout_error_type: str = "intake_generation_timeout",
) -> subprocess.CompletedProcess[str]:
    command = [
        "codex",
        "exec",
        "--full-auto",
        "--skip-git-repo-check",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--disable",
        "plugins",
        prompt,
    ]
    proc = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        _terminate_process_group(proc)
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        raise BackendError(
            f"Codex {stage_label} timed out.",
            error_type=timeout_error_type,
            details={
                "timeout_seconds": timeout_seconds,
                "stdout": str(stdout)[-2000:],
                "stderr": str(stderr)[-2000:],
                "stage": stage_label,
            },
        ) from exc
    return subprocess.CompletedProcess(command, proc.returncode, stdout=stdout, stderr=stderr)


def command_brief_generate_intake(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    description = str(getattr(args, "body", "") or "").strip()
    if not description:
        raise BackendError(
            "A build description is required.",
            exit_code=2,
            error_type="missing_build_description",
            details={"target": str(target)},
        )
    generation_warnings: list[dict[str, Any]] = []
    intake_prompt = _low_cortisol_intake_prompt(target, description)
    stream_event(args, "intake-generate", "Generating intake.")
    try:
        with tempfile.TemporaryDirectory(prefix="diffmogger-intake-") as tmp:
            intake_result = _run_codex_intake_generation(
                intake_prompt,
                cwd=Path(tmp),
                timeout_seconds=_intake_codex_timeout_seconds(),
                stage_label="intake generation",
                timeout_error_type="intake_generation_timeout",
            )
    except BackendError as exc:
        if exc.error_type != "intake_generation_timeout":
            raise
        stream_event(args, "intake-fallback", "Intake generation timed out; using deterministic fallback.", level="warning")
        generation_warnings.append(
            _low_cortisol_timeout_warning(
                warning_type="codex_intake_generation_timeout_fallback",
                stage_label="intake generation",
                timeout_seconds=exc.details.get("timeout_seconds"),
            )
        )
        intake = _fallback_low_cortisol_intake(target, description)
    else:
        if intake_result.returncode != 0:
            raise BackendError(
                "Codex intake generation failed.",
                error_type="intake_generation_failed",
                details={"exit_code": intake_result.returncode, "stdout": intake_result.stdout[-2000:], "stderr": intake_result.stderr[-2000:]},
            )
        raw_intake = _extract_json_payload(intake_result.stdout, label="intake")
        intake = _normalize_low_cortisol_intake(target, raw_intake, description, require_tickets=False)

    ticket_prompt = _low_cortisol_ticket_prompt(target, description, intake)
    stream_event(args, "ticket-generate", "Generating tickets.")
    scope_groups = ticket_scope_groups_from_intake(intake)
    fallback_ticket_warnings: list[dict[str, Any]] = []
    try:
        with tempfile.TemporaryDirectory(prefix="diffmogger-tickets-") as tmp:
            ticket_result = _run_codex_intake_generation(
                ticket_prompt,
                cwd=Path(tmp),
                timeout_seconds=_ticket_codex_timeout_seconds(),
                stage_label="ticket generation",
                timeout_error_type="ticket_generation_timeout",
            )
    except BackendError as exc:
        if exc.error_type != "ticket_generation_timeout":
            raise
        stream_event(args, "ticket-fallback", "Ticket generation timed out; using deterministic fallback queue.", level="warning")
        seed_tickets, fallback_ticket_warnings = _fallback_low_cortisol_tickets(intake, description)
        fallback_ticket_warnings.insert(
            0,
            _low_cortisol_timeout_warning(
                warning_type="codex_ticket_generation_timeout_fallback",
                stage_label="ticket generation",
                timeout_seconds=exc.details.get("timeout_seconds"),
            ),
        )
        quality_gate = ticket_generation_quality_gate(seed_tickets, scope_groups=scope_groups)
        refinement_needed = False
    else:
        if ticket_result.returncode != 0:
            raise BackendError(
                "Codex ticket generation failed.",
                error_type="ticket_generation_failed",
                details={"exit_code": ticket_result.returncode, "stdout": ticket_result.stdout[-2000:], "stderr": ticket_result.stderr[-2000:]},
            )
        raw_tickets = _extract_json_payload(ticket_result.stdout, label="ticket seed")
        seed_tickets = ticket_run.normalized_tickets(_extract_seed_tickets_payload(raw_tickets))
        if not seed_tickets:
            raise BackendError(
                "Codex did not return any ticket_run_seed_tickets.",
                error_type="intake_generation_no_tickets",
                details={"project_name": intake["project_name"]},
            )
        quality_gate = ticket_generation_quality_gate(seed_tickets, scope_groups=scope_groups)
        refinement_needed = not bool(quality_gate.get("passed"))
        if refinement_needed:
            ticket_prompt = _low_cortisol_refinement_prompt(target, description, intake, seed_tickets, quality_gate)
            stream_event(args, "ticket-refine", "Refining under-decomposed tickets.")
            try:
                with tempfile.TemporaryDirectory(prefix="diffmogger-ticket-refine-") as tmp:
                    ticket_result = _run_codex_intake_generation(
                        ticket_prompt,
                        cwd=Path(tmp),
                        timeout_seconds=_ticket_refinement_codex_timeout_seconds(),
                        stage_label="ticket refinement",
                        timeout_error_type="ticket_refinement_timeout",
                    )
            except BackendError as exc:
                if exc.error_type != "ticket_refinement_timeout":
                    raise
                stream_event(args, "ticket-fallback", "Ticket refinement timed out; using deterministic fallback queue.", level="warning")
                seed_tickets, fallback_ticket_warnings = _fallback_low_cortisol_tickets(intake, description)
                fallback_ticket_warnings.insert(
                    0,
                    _low_cortisol_timeout_warning(
                        warning_type="codex_ticket_refinement_timeout_fallback",
                        stage_label="ticket refinement",
                        timeout_seconds=exc.details.get("timeout_seconds"),
                    ),
                )
                quality_gate = ticket_generation_quality_gate(seed_tickets, scope_groups=scope_groups)
            else:
                if ticket_result.returncode != 0:
                    raise BackendError(
                        "Codex ticket refinement failed.",
                        error_type="ticket_refinement_failed",
                        details={"exit_code": ticket_result.returncode, "stdout": ticket_result.stdout[-2000:], "stderr": ticket_result.stderr[-2000:]},
                    )
                raw_tickets = _extract_json_payload(ticket_result.stdout, label="ticket refinement")
                refined_tickets = ticket_run.normalized_tickets(_extract_seed_tickets_payload(raw_tickets))
                if refined_tickets:
                    seed_tickets = refined_tickets
                    quality_gate = ticket_generation_quality_gate(seed_tickets, scope_groups=scope_groups)
    intake["ticket_run_seed_tickets"] = seed_tickets
    intake["ticket_generation_scope_groups"] = scope_groups
    quality_warnings = list(quality_gate.get("warnings") or ticket_quality_warnings(seed_tickets, scope_groups=scope_groups))
    intake["ticket_generation_quality_warnings"] = [*generation_warnings, *fallback_ticket_warnings, *quality_warnings]
    intake["ticket_generation_refinement_needed"] = refinement_needed
    intake["ticket_generation_refinement_passed"] = bool(quality_gate.get("passed"))
    intake["ticket_generation_scope_surface_floor"] = int(quality_gate.get("scope_surface_floor") or 0)
    state_path = write_dashboard_state_from_intake(target, intake, last_action="low_cortisol_intake_generated")
    write_dashboard_action_state(target, last_action="low_cortisol_intake_generated")
    return {
        "target": target_metadata(target),
        "dashboard_state_path": str(state_path),
        "intake": intake,
        "ticket_count": len(intake["ticket_run_seed_tickets"]),
        "ticket_generation_complexity": intake["ticket_generation_complexity"],
        "ticket_generation_quality_warnings": intake["ticket_generation_quality_warnings"],
        "ticket_generation_scope_groups": intake["ticket_generation_scope_groups"],
        "ticket_generation_refinement_needed": intake["ticket_generation_refinement_needed"],
        "ticket_generation_refinement_passed": intake["ticket_generation_refinement_passed"],
        "ticket_generation_scope_surface_floor": intake["ticket_generation_scope_surface_floor"],
        "automation_role_profile": intake["automation_role_profile"],
        "ticket_run_file": intake["ticket_run_file"],
    }

def command_brief_load(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    intake = load_intake(target)
    dashboard_state = load_dashboard_state(target)
    draft_intake = dashboard_state.get("brief_draft_intake")
    if not isinstance(draft_intake, dict):
        draft_intake = intake
    project_name = (
        draft_intake.get("project_name")
        or intake.get("project_name")
        or dashboard_state.get("project_name")
        or target.name
        or str(target)
    )
    return {
        "target": target_metadata(target),
        "exists": bool(intake),
        "project_name": project_name,
        "project_mode": draft_intake.get("project_mode") or intake.get("project_mode") or dashboard_state.get("project_mode") or "unknown",
        "intake": intake,
        "draft_intake": draft_intake,
        "dashboard_state": dashboard_state,
        "context_files": list(intake.get("additional_context_files") or []),
        "detected": detect_target_context(target),
    }

def command_brief_save_draft(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    intake = parse_json_arg(args.intake_json, label="intake-json")
    if not isinstance(intake, dict):
        raise BackendError(
            "intake-json must decode to an object.",
            exit_code=2,
            error_type="invalid_json",
            details={"label": "intake-json"},
        )
    state_path = write_dashboard_state_from_intake(target, intake, last_action="brief_draft_saved")
    return {
        "target": target_metadata(target),
        "dashboard_state_path": str(state_path),
        "intake": intake,
        "detected": detect_target_context(target),
    }

def run_required_file_check_for_intake(target: Path, intake: dict[str, Any]) -> dict[str, Any]:
    command = [
        sys.executable,
        str(CHECK_REQUIRED_SCRIPT),
        "--human-bridge-mode",
        str(intake.get("human_bridge_mode") or "file_only"),
    ]
    command.append("--write-workers-enabled")
    command.append("--multi-role-enabled")
    campaign = str(intake.get("campaign_mode") or intake.get("automation_run_mode") or "").strip().lower()
    campaign = campaign.replace("-", "_").replace(" ", "_")
    if campaign in {"bounded", "ticket_campaign"}:
        command.append("--ticket-campaign-enabled")
    if intake.get("optional_mcp_servers"):
        command.append("--optional-mcp-enabled")
    command.append(str(target))
    result = run_subprocess(command)
    result["status"] = "pass" if result["exit_code"] == 0 else "fail"
    return result

def bootstrap_status_pending(control: dict[str, Any]) -> bool:
    status = str(control.get("bootstrap_status") or "").strip().lower()
    return status in BOOTSTRAP_PENDING_STATUSES

def initial_bootstrap_completed(target: Path, control: dict[str, Any] | None = None) -> bool:
    dashboard_state = load_dashboard_state(target)
    dashboard_status = str(dashboard_state.get("initial_bootstrap_status") or "").strip().lower()
    if dashboard_status == "pass" or str(dashboard_state.get("initial_bootstrap_completed_at") or "").strip():
        return True
    control = control or automation_control_state(target)
    return not bootstrap_status_pending(control)

def bootstrap_lock_path(target: Path) -> Path:
    return target_path(target.expanduser().resolve(), "target/automation_logs/initial_bootstrap.lock")

@contextlib.contextmanager
def acquire_initial_bootstrap_lock(target: Path):
    path = bootstrap_lock_path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise BackendError(
            "Initial bootstrap is already running for this target.",
            error_type="bootstrap_already_running",
            details={"lock_path": str(path)},
        ) from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            )
        yield path
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass

def checkpoint_completed_successfully(checkpoint: Mapping[str, Any] | None) -> bool:
    return str((checkpoint or {}).get("status") or "").strip().lower() in BOOTSTRAP_SUCCESSFUL_CHECKPOINT_STATUSES

def bootstrap_checkpoint_reference(checkpoint: Mapping[str, Any] | None) -> str:
    commit = str((checkpoint or {}).get("commit") or "").strip()
    return commit[:12] if commit else "the recorded bootstrap checkpoint"

def has_stale_bootstrap_checkpoint_blocker_text(control: Mapping[str, Any]) -> bool:
    pieces = [
        str(control.get("current_assessment") or ""),
        str(control.get("best_next_milestone") or ""),
        str(control.get("suggested_next_task") or ""),
        str(control.get("known_issue") or ""),
    ]
    issues = control.get("known_issues") if isinstance(control.get("known_issues"), list) else []
    pieces.extend(str(item) for item in issues)
    text = "\n".join(pieces).lower()
    return any(term in text for term in STALE_BOOTSTRAP_CHECKPOINT_BLOCKER_TERMS)

def should_clear_stale_bootstrap_blocker(
    target: Path,
    control: Mapping[str, Any],
    checkpoint: Mapping[str, Any] | None,
) -> bool:
    if not checkpoint_completed_successfully(checkpoint):
        return False
    if str(control.get("status") or "").strip().upper() != "BLOCKED_ON_ENVIRONMENT":
        return False
    if not has_stale_bootstrap_checkpoint_blocker_text(control):
        return False
    with connect(database_path_for_target(target)) as conn:
        return not open_blockers(conn)

def ensure_bootstrap_control_completed(target: Path, checkpoint: Mapping[str, Any] | None = None) -> dict[str, Any]:
    control = automation_control_state(target)
    clear_stale_blocker = should_clear_stale_bootstrap_blocker(target, control, checkpoint)
    if not bootstrap_status_pending(control) and not clear_stale_blocker:
        return control
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    current_assessment = str(control.get("current_assessment") or "").strip()
    if not current_assessment or "not bootstrapped" in current_assessment.lower():
        current_assessment = "Initial bootstrap completed from the dashboard."
    updates: dict[str, Any] = {
        "last_updated": now,
        "current_assessment": current_assessment,
        "bootstrap_status": "bootstrapped",
    }
    if clear_stale_blocker:
        checkpoint_ref = bootstrap_checkpoint_reference(checkpoint)
        updates.update(
            {
                "status": "ACTIVE",
                "current_assessment": (
                    f"Initial bootstrap completed and product baseline checkpoint `{checkpoint_ref}` is recorded; "
                    "continue with the next typed ticket or DAG action."
                ),
                "best_next_milestone": "Continue the next dependency-ready typed ticket or DAG action from the successful bootstrap baseline.",
                "suggested_next_task": "Use the queued ticket/DAG scheduler state to continue product work from the verified bootstrap baseline.",
                "known_issue": "",
                "known_issues": [],
            }
        )
    return write_automation_control_state(
        target,
        updates,
        actor_role="dashboard",
        event_type="automation.initial_bootstrap_completed",
    )

def run_git(target: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=target,
        env=env,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )

def git_head(target: Path) -> str:
    result = run_git(target, "rev-parse", "--verify", "HEAD")
    return result.stdout.strip() if result.returncode == 0 else ""

def parse_git_status_paths(output: str) -> list[str]:
    paths: list[str] = []
    records = [item for item in output.split("\0") if item]
    index = 0
    while index < len(records):
        record = records[index]
        if len(record) < 4:
            index += 1
            continue
        status = record[:2]
        path = record[3:]
        if status.startswith(("R", "C")) and index + 1 < len(records):
            path = records[index + 1]
            index += 1
        paths.append(path)
        index += 1
    return paths

def bootstrap_product_path_allowed(rel_path: str) -> bool:
    rel_path = rel_path.strip().lstrip("/")
    if not rel_path:
        return False
    if rel_path in BOOTSTRAP_PRODUCT_EXCLUDED_NAMES or rel_path in BOOTSTRAP_SCAFFOLD_INTERNALS:
        return False
    if rel_path.startswith(BOOTSTRAP_PRODUCT_EXCLUDED_PREFIXES):
        return False
    name = Path(rel_path).name
    if name.startswith(".env") or name in {"id_rsa", "id_ed25519"}:
        return False
    if rel_path.endswith(BOOTSTRAP_PRODUCT_EXCLUDED_SUFFIXES):
        return False
    parts = set(Path(rel_path).parts)
    if parts.intersection({"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules"}):
        return False
    return True

def bootstrap_product_status_paths(target: Path) -> list[str]:
    result = run_git(target, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "git status failed").strip())
    return sorted({path for path in parse_git_status_paths(result.stdout) if bootstrap_product_path_allowed(path)})

def tracked_product_paths(target: Path) -> list[str]:
    result = run_git(target, "ls-files", "-z")
    if result.returncode != 0:
        return []
    return sorted({path for path in result.stdout.split("\0") if bootstrap_product_path_allowed(path)})

def bootstrap_git_commit_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("GIT_AUTHOR_NAME", "Diffmogger Bootstrap")
    env.setdefault("GIT_AUTHOR_EMAIL", "diffmogger-bootstrap@example.invalid")
    env.setdefault("GIT_COMMITTER_NAME", "Diffmogger Bootstrap")
    env.setdefault("GIT_COMMITTER_EMAIL", "diffmogger-bootstrap@example.invalid")
    return env

def record_bootstrap_checkpoint_blocker(target: Path, *, reason: str, detail: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    blocker_payload = {
        "schema_version": 1,
        "reason": reason,
        "detail": detail,
        "next_action": "Inspect bootstrap output, create a safe local product checkpoint, then rerun or clear the bootstrap gate.",
    }
    with connect(database_path_for_target(target)) as conn:
        with conn:
            upsert_blocker(
                conn,
                blocker_id="blocker:initial_bootstrap_checkpoint",
                task_id="task:initial_bootstrap",
                kind="initial_bootstrap_checkpoint",
                status="open",
                summary=detail,
                resume_token=reason,
                created_at=now,
                updated_at=now,
                payload=blocker_payload,
            )
    control = write_automation_control_state(
        target,
        {
            "status": "BLOCKED_ON_ENVIRONMENT",
            "bootstrap_status": "blocked",
            "current_assessment": detail,
            "known_issue": detail,
            "known_issues": [detail],
            "last_updated": now,
        },
        actor_role="dashboard",
        event_type="automation.initial_bootstrap_checkpoint_blocked",
    )
    return {"status": "blocked", "reason": reason, "detail": detail, "automation_control": control}

def checkpoint_initial_bootstrap_baseline(target: Path, *, head_before: str) -> dict[str, Any]:
    target = target.expanduser().resolve()
    head_after = git_head(target)
    changed_product_paths = bootstrap_product_status_paths(target)
    if changed_product_paths:
        add = run_git(target, "add", "-A", "--", *changed_product_paths)
        if add.returncode != 0:
            detail = (add.stderr or add.stdout or "git add failed").strip()
            return record_bootstrap_checkpoint_blocker(target, reason="git_add_failed", detail=detail)
        diff = run_git(target, "diff", "--cached", "--quiet", "--exit-code")
        if diff.returncode not in {0, 1}:
            detail = (diff.stderr or diff.stdout or "git diff failed").strip()
            return record_bootstrap_checkpoint_blocker(target, reason="git_diff_failed", detail=detail)
        if diff.returncode == 1:
            commit = run_git(
                target,
                "commit",
                "--no-verify",
                "-m",
                BOOTSTRAP_PRODUCT_COMMIT_MESSAGE,
                env=bootstrap_git_commit_env(),
            )
            if commit.returncode != 0:
                detail = (commit.stderr or commit.stdout or "git commit failed").strip()
                return record_bootstrap_checkpoint_blocker(target, reason="git_commit_failed", detail=detail)
            return {
                "status": "committed",
                "commit": git_head(target),
                "message": BOOTSTRAP_PRODUCT_COMMIT_MESSAGE,
                "paths": changed_product_paths,
            }

    tracked_products = tracked_product_paths(target)
    if tracked_products and head_after and head_after != head_before:
        return {"status": "already_checkpointed", "commit": head_after, "paths": tracked_products}
    if tracked_products and head_after:
        return {"status": "already_tracked", "commit": head_after, "paths": tracked_products}
    return record_bootstrap_checkpoint_blocker(
        target,
        reason="no_product_checkpoint",
        detail="Initial bootstrap finished, but no safe product baseline files were available to checkpoint.",
    )

def run_initial_bootstrap(
    args: argparse.Namespace,
    target: Path,
    *,
    log: Callable[[str, str], None] | None = None,
) -> dict[str, Any]:
    def note(stage: str, message: str) -> None:
        if log is not None:
            log(stage, message)
        else:
            stream_event(args, stage, message)

    intake = load_intake(target)
    if not intake:
        raise BackendError(
            "Setup must be scaffolded before initial bootstrap can run.",
            error_type="bootstrap_not_scaffolded",
            details={"target": str(target)},
        )
    prompt_path = preferred_target_path(target, "docs/INITIAL_BOOTSTRAP_PROMPT.md")
    if not prompt_path.exists():
        raise BackendError(
            "Could not read the initial bootstrap prompt.",
            error_type="bootstrap_prompt_missing",
            details={"path": str(prompt_path)},
        )
    control = automation_control_state(target)
    if initial_bootstrap_completed(target, control):
        raise BackendError(
            "Initial bootstrap has already completed for this target.",
            error_type="bootstrap_already_completed",
            details={
                "bootstrap_status": str(control.get("bootstrap_status") or ""),
                "dashboard_state": {
                    "initial_bootstrap_status": str(load_dashboard_state(target).get("initial_bootstrap_status") or ""),
                    "initial_bootstrap_completed_at": str(load_dashboard_state(target).get("initial_bootstrap_completed_at") or ""),
                },
            },
        )

    prerequisites = prereq_snapshot(target, intake)
    required_failures = list(prerequisites.get("required_failures") or [])
    if required_failures:
        raise BackendError(
            "Required prerequisites are missing before initial bootstrap.",
            error_type="prerequisites_failed",
            details={"required_failures": required_failures, "prerequisites": prerequisites},
        )
    required_files = run_required_file_check_for_intake(target, intake)
    if required_files.get("exit_code") != 0:
        raise BackendError(
            "Required-file validation failed before initial bootstrap.",
            error_type="required_files_failed",
            details=required_files,
        )

    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_dashboard_action_state(
        target,
        last_action="initial_bootstrap_started",
        updates={
            "initial_bootstrap_status": "running",
            "last_initial_bootstrap_started_at": started_at,
        },
    )
    note("bootstrap", "Starting Codex initial bootstrap run.")
    prompt = prompt_path.read_text(encoding="utf-8")
    dashboard_app = load_dashboard_module()
    try:
        dashboard_app.load_scaffold_module().ensure_initial_git_commit(target)
    except Exception as exc:
        raise BackendError(
            "Git bootstrap failed before initial Codex bootstrap.",
            error_type="git_bootstrap_failed",
            details={"target": str(target), "exception": str(exc)},
        ) from exc
    env = {**os.environ, **dashboard_app.automation_environment(target)}
    head_before = git_head(target)
    result = run_subprocess_streamed(
        args,
        ["codex", "exec", "--full-auto", "--skip-git-repo-check", prompt],
        cwd=target,
        stage="bootstrap",
        env=env,
    )
    finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    exit_code = int(result.get("exit_code") if result.get("exit_code") is not None else 1)
    status = "pass" if exit_code == 0 else "fail"
    if status != "pass":
        write_dashboard_action_state(
            target,
            last_action="initial_bootstrap_failed",
            updates={
                "initial_bootstrap_status": status,
                "last_initial_bootstrap_started_at": started_at,
                "last_initial_bootstrap_finished_at": finished_at,
                "last_initial_bootstrap_exit_code": result.get("exit_code"),
            },
        )
        raise BackendError(
            "Codex bootstrap failed.",
            error_type="codex_bootstrap_failed",
            details={**result, "started_at": started_at, "finished_at": finished_at},
        )

    checkpoint = checkpoint_initial_bootstrap_baseline(target, head_before=head_before)
    if checkpoint.get("status") == "blocked":
        write_dashboard_action_state(
            target,
            last_action="initial_bootstrap_checkpoint_blocked",
            updates={
                "initial_bootstrap_status": "blocked",
                "last_initial_bootstrap_started_at": started_at,
                "last_initial_bootstrap_finished_at": finished_at,
                "last_initial_bootstrap_exit_code": result.get("exit_code"),
                "initial_bootstrap_checkpoint": checkpoint,
            },
        )
        raise BackendError(
            "Initial bootstrap completed but no safe product checkpoint could be created.",
            error_type="bootstrap_checkpoint_failed",
            details={**checkpoint, "started_at": started_at, "finished_at": finished_at},
        )

    control = ensure_bootstrap_control_completed(target, checkpoint=checkpoint)
    state_path = write_dashboard_action_state(
        target,
        last_action="initial_bootstrap_completed",
        updates={
            "initial_bootstrap_status": status,
            "initial_bootstrap_completed_at": finished_at,
            "last_initial_bootstrap_started_at": started_at,
            "last_initial_bootstrap_finished_at": finished_at,
            "last_initial_bootstrap_exit_code": result.get("exit_code"),
            "initial_bootstrap_checkpoint": checkpoint,
        },
    )
    note("bootstrap", "Initial bootstrap completed.")
    return {
        "target": target_metadata(target),
        "dashboard_state_path": str(state_path),
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "result": result,
        "checkpoint": checkpoint,
        "required_files": required_files,
        "prerequisites": prerequisites,
        "automation_control": control,
    }

def scaffold_template_included(scaffold_module: Any, rel_path: str, values: dict[str, str]) -> bool:
    if hasattr(scaffold_module, "template_included"):
        return bool(scaffold_module.template_included(rel_path, values))
    if values.get("MCP_ENABLED") != "true" and rel_path in scaffold_module.MCP_FILES:
        return False
    if values.get("PLAYWRIGHT_MCP_ENABLED") != "true" and rel_path in scaffold_module.PLAYWRIGHT_MCP_FILES:
        return False
    return True

def scaffold_file_preview(target: Path, intake: dict[str, Any], *, force: bool) -> list[dict[str, Any]]:
    scaffold_module = load_dashboard_module().load_scaffold_module()
    scaffold_intake = project_intake_payload(intake)
    values = scaffold_module.placeholders(scaffold_intake)
    mode = values.get("PROJECT_MODE", "fresh_project")
    records: list[dict[str, Any]] = []
    for template_path in sorted(scaffold_module.TEMPLATE_ROOT.rglob("*")):
        if template_path.is_dir():
            continue
        if template_path.name == ".DS_Store":
            continue
        if "__pycache__" in template_path.parts or template_path.suffix == ".pyc":
            continue
        rel = template_path.relative_to(scaffold_module.TEMPLATE_ROOT)
        rel_path = rel.as_posix()
        if rel_path.startswith("scripts/") and template_path.suffix == ".py":
            continue
        if not scaffold_template_included(scaffold_module, rel_path, values):
            continue

        dest_rel = (
            scaffold_module.template_destination_rel(rel_path)
            if hasattr(scaffold_module, "template_destination_rel")
            else rel_path
        )
        dest = target / dest_rel
        exists = dest.exists()
        managed_kind = scaffold_module.MANAGED_EXISTING_PROJECT_FILES.get(rel_path)
        managed = False
        action = "create"
        detail = "Will create this target-local generated file."

        if mode == "existing_project" and managed_kind and exists:
            action = "managed_section_update"
            managed = True
            detail = f"Will update only the Diffmogger-managed {managed_kind} section and preserve surrounding content."
        elif mode == "existing_project" and managed_kind:
            managed = True
            detail = f"Will create this file with a Diffmogger-managed {managed_kind} section."
        elif exists and force:
            action = "overwrite"
            detail = "Will overwrite this scaffold-managed file because force is enabled."
        elif exists:
            if not dest_rel.startswith(".diffmogger/"):
                action = "conflict_requires_user_choice"
                detail = "A project-facing path already exists; Diffmogger will not silently overwrite or skip it."
            else:
                action = "skip_existing"
                detail = "Will not overwrite the existing sidecar file with force disabled."

        records.append(
            {
                "rel_path": dest_rel,
                "template_rel_path": rel_path,
                "path": str(dest),
                "exists": exists,
                "action": action,
                "managed_section": managed,
                "detail": detail,
            }
        )

    manifest = target / ".diffmogger" / "manifest.json"
    records.append(
        {
            "rel_path": ".diffmogger/manifest.json",
            "path": str(manifest),
            "exists": manifest.exists(),
            "action": "create" if not manifest.exists() else ("overwrite" if force else "skip_existing"),
            "managed_section": True,
            "detail": "Will write the sidecar ownership manifest used by runners, validation, and local excludes.",
        }
    )

    if (target / ".git").exists():
        exclude = target / ".git" / "info" / "exclude"
        records.append(
            {
                "rel_path": ".git/info/exclude",
                "path": str(exclude),
                "exists": exclude.exists(),
                "action": "update_local_exclude",
                "managed_section": True,
                "detail": "Will merge Diffmogger runtime ignore entries into the local git exclude file.",
            }
        )
    return records

def preview_summary(files: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for record in files:
        action = str(record.get("action") or "unknown")
        summary[action] = summary.get(action, 0) + 1
    return summary

def prereq_snapshot(target: Path, intake: dict[str, Any]) -> dict[str, Any]:
    dashboard_app = load_dashboard_module()
    bridge_mode = str(intake.get("human_bridge_mode") or "file_only")
    optional_mcp = dashboard_app.optional_mcp_servers_from_value(intake.get("optional_mcp_servers"))
    items = dashboard_app.check_prerequisites(target, bridge_mode, optional_mcp)
    rows = [
        {
            "name": item.name,
            "ok": item.ok,
            "required": item.required,
            "detail": item.detail,
        }
        for item in items
    ]
    required_failures = [item for item in rows if item["required"] and not item["ok"]]
    advisory_warnings = [item for item in rows if not item["required"] and not item["ok"]]
    return {
        "status": "pass" if not required_failures else "fail",
        "items": rows,
        "required_failures": required_failures,
        "advisory_warnings": advisory_warnings,
    }

def git_warnings_from_detected(detected: dict[str, Any]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    if detected.get("is_git_repo") and int(detected.get("git_dirty_count") or 0) > 0:
        warnings.append(
            {
                "type": "dirty_git",
                "level": "warning",
                "message": f"Git has {detected.get('git_dirty_count')} changed file(s). Review the working tree before scaffolding into an existing repo.",
            }
        )
    return warnings

def build_scaffold_preview(target: Path, intake: dict[str, Any], *, force: bool) -> dict[str, Any]:
    files = scaffold_file_preview(target, intake, force=force)
    detected = detect_target_context(target)
    prerequisites = prereq_snapshot(target, intake)
    warnings = git_warnings_from_detected(detected)
    warnings.extend(
        {
            "type": "missing_prerequisite",
            "level": "warning",
            "message": f"{item['name']}: {item['detail']}",
        }
        for item in prerequisites["required_failures"]
    )
    warnings.extend(
        {
            "type": "advisory_prerequisite",
            "level": "info",
            "message": f"{item['name']}: {item['detail']}",
        }
        for item in prerequisites["advisory_warnings"]
    )
    return {
        "target": target_metadata(target),
        "project_mode": str(intake.get("project_mode") or "fresh_project"),
        "force": force,
        "files": files,
        "summary": preview_summary(files),
        "warnings": warnings,
        "prerequisites": prerequisites,
        "detected": detected,
    }

def command_brief_scaffold_preview(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    intake = parse_json_arg(args.intake_json, label="intake-json")
    if not isinstance(intake, dict):
        raise BackendError(
            "intake-json must decode to an object.",
            exit_code=2,
            error_type="invalid_json",
            details={"label": "intake-json"},
        )
    return build_scaffold_preview(target, intake, force=bool(args.force))

def command_brief_run_bootstrap(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    if target == KIT_ROOT:
        raise BackendError(
            "Refusing to bootstrap the Diffmogger source checkout.",
            exit_code=2,
            error_type="invalid_target",
            details={"target": str(target)},
        )
    with acquire_initial_bootstrap_lock(target):
        return run_initial_bootstrap(args, target)

def native_next_state_from_target(target: Path) -> dict[str, Any]:
    try:
        snapshot = build_observatory_snapshot(target)
    except BackendError as exc:
        return {
            "state": "READY_TO_RUN",
            "reason": f"Scaffold completed, but Observatory snapshot could not be built yet: {exc.message}",
            "first_review_status": "unknown",
            "task_status": "unknown",
        }
    first_review = snapshot.get("first_review") if isinstance(snapshot.get("first_review"), dict) else {}
    task = snapshot.get("task") if isinstance(snapshot.get("task"), dict) else {}
    first_review_status = str(first_review.get("status") or "unknown")
    if first_review_status != "ready":
        return {
            "state": "FIRST_REVIEW_NEEDED",
            "reason": first_review.get("summary") or "Scaffold completed; complete first-review readiness before leaving automation unattended.",
            "first_review_status": first_review_status,
            "task_status": task.get("status") or "unknown",
        }
    return {
        "state": "READY_TO_RUN",
        "reason": first_review.get("summary") or "Scaffold completed and first-review readiness is recorded.",
        "first_review_status": first_review_status,
        "task_status": task.get("status") or "unknown",
    }

def command_brief_scaffold_bootstrap(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    intake = parse_json_arg(args.intake_json, label="intake-json")
    if not isinstance(intake, dict):
        raise BackendError(
            "intake-json must decode to an object.",
            exit_code=2,
            error_type="invalid_json",
            details={"label": "intake-json"},
        )
    if target == KIT_ROOT:
        raise BackendError(
            "Refusing to scaffold into the Diffmogger source checkout.",
            exit_code=2,
            error_type="invalid_target",
            details={"target": str(target)},
        )

    log_lines: list[dict[str, Any]] = []

    def log(stage: str, message: str, *, level: str = "info", data: dict[str, Any] | None = None) -> None:
        record = {
            "stage": stage,
            "level": level,
            "message": message,
            "data": data or {},
        }
        log_lines.append(record)
        stream_event(args, stage, message, level=level, data=data)

    log("preflight", "Building scaffold preview and prerequisite summary.")
    preflight = build_scaffold_preview(target, intake, force=bool(args.force))
    required_failures = list((preflight.get("prerequisites") or {}).get("required_failures") or [])
    if required_failures and bool(args.run_codex):
        log(
            "preflight",
            "Required prerequisites are missing; Codex bootstrap cannot start.",
            level="error",
            data={"required_failures": required_failures},
        )
        raise BackendError(
            "Required prerequisites are missing before Codex bootstrap.",
            error_type="prerequisites_failed",
            details={"required_failures": required_failures, "preflight": preflight, "log": log_lines[-12:]},
        )
    if required_failures:
        log(
            "preflight",
            "Required prerequisites are missing for full bootstrap; scaffold will continue without running Codex.",
            level="warning",
            data={"required_failures": required_failures},
        )

    log("state", "Writing target-local dashboard state.")
    state_path = write_dashboard_state_from_intake(target, intake, last_action="scaffold_bootstrap_started")
    intake_path = preferred_target_path(target, ".agentic/project_intake.json")
    intake_path.parent.mkdir(parents=True, exist_ok=True)
    scaffold_intake = project_intake_payload(intake)
    write_json_file(intake_path, scaffold_intake)
    log("state", f"Wrote {intake_path.relative_to(target)}.")

    scaffold_module = load_dashboard_module().load_scaffold_module()
    try:
        log("scaffold", "Rendering scaffold templates.")
        values = scaffold_module.placeholders(scaffold_intake)
        written = scaffold_module.scaffold(target, values, bool(args.force))
        log("scaffold", f"Scaffold wrote or updated {len(written)} file(s).")
        for path in written[:24]:
            log("scaffold", f"wrote {path.relative_to(target)}", data={"rel_path": str(path.relative_to(target))})
        if len(written) > 24:
            log("scaffold", f"... {len(written) - 24} more file(s).")
    except Exception as exc:
        log("scaffold", f"Scaffold generation failed: {exc}", level="error")
        raise BackendError(
            "Scaffold generation failed.",
            error_type="scaffold_failed",
            details={"target": str(target), "exception": str(exc), "log": log_lines[-20:]},
        ) from exc

    log("validation", "Running generated required-file validation.")
    required_files = run_required_file_check_for_intake(target, scaffold_intake)
    if required_files.get("stdout"):
        log("validation", str(required_files.get("stdout"))[:800], data={"exit_code": required_files.get("exit_code")})
    if required_files.get("stderr"):
        log("validation", str(required_files.get("stderr"))[:800], level="warning", data={"exit_code": required_files.get("exit_code")})
    if required_files["exit_code"] != 0:
        log("validation", "Required-file validation failed after scaffolding.", level="error")
        raise BackendError(
            "Required-file validation failed after scaffolding.",
            error_type="required_files_failed",
            details={**required_files, "log": log_lines[-20:]},
        )

    codex_result: dict[str, Any] = {
        "status": "skipped",
        "reason": "Codex bootstrap was not requested by this backend command.",
    }
    if bool(args.run_codex):
        with acquire_initial_bootstrap_lock(target):
            codex_result = run_initial_bootstrap(args, target, log=log)
    else:
        log("bootstrap", "Skipped Codex initial bootstrap; use the Setup bootstrap control before starting ongoing automation.")

    git_bootstrap: dict[str, Any] = {}
    try:
        log("git", "Ensuring target git repo and initial commit.")
        git_bootstrap = scaffold_module.ensure_initial_git_commit(target, values)
        if git_bootstrap.get("committed"):
            log(
                "git",
                f"Created initial commit {str(git_bootstrap.get('commit') or '')[:12]}.",
                data=git_bootstrap,
            )
        elif git_bootstrap.get("initialized"):
            log(
                "git",
                "Initialized git repo; existing HEAD is already available.",
                data=git_bootstrap,
            )
        else:
            log("git", "Target already has an initial git commit.", data=git_bootstrap)
    except Exception as exc:
        log("git", f"Git bootstrap failed: {exc}", level="error")
        raise BackendError(
            "Git bootstrap failed after scaffolding.",
            error_type="git_bootstrap_failed",
            details={"target": str(target), "exception": str(exc), "log": log_lines[-20:]},
        ) from exc

    write_dashboard_state_from_intake(
        target,
        intake,
        last_action="scaffold_bootstrap_completed" if bool(args.run_codex) else "scaffold_completed",
    )
    next_state = native_next_state_from_target(target)
    log("done", f"Scaffold pipeline completed: {next_state['state']}.", data=next_state)
    return {
        "target": target_metadata(target),
        "dashboard_state_path": str(state_path),
        "project_intake_path": str(intake_path),
        "written_files": [str(path.relative_to(target)) for path in written],
        "written_count": len(written),
        "required_files": required_files,
        "codex": codex_result,
        "git": git_bootstrap,
        "preflight": preflight,
        "native_next_state": next_state,
        "log": log_lines,
        "log_excerpt": log_lines[-20:],
    }
