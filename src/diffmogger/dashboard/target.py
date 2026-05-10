from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from diffmogger.dashboard import shared as dashboard_shared
from diffmogger.runtime.paths import existing_or_target_path, preferred_target_path, sidecar_rel, target_path

from .errors import BackendError
from .jsonio import *

def find_kit_root() -> Path:
    override = os.environ.get("DIFFMOGGER_KIT_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    for parent in Path(__file__).resolve().parents:
        if (parent / "templates").is_dir() and (parent / "scripts").is_dir():
            return parent
    return Path(__file__).resolve().parents[3]

KIT_ROOT = find_kit_root()

OBSERVATORY_SCRIPT = KIT_ROOT / "scripts" / "runtime" / "run_observatory.py"

CHECK_REQUIRED_SCRIPT = KIT_ROOT / "scripts" / "check_required_files.py"

CHECK_INTEGRATION_SAFETY_SCRIPT = KIT_ROOT / "scripts" / "check_integration_safety.py"

DEFAULT_REVIEW_HTML = "Diffmogger-observatory.html"

DEFAULT_REVIEW_MARKDOWN = "Diffmogger-self-review.md"

def target_script_path(target: Path, legacy_rel: str) -> Path:
    return existing_or_target_path(target.expanduser().resolve(), legacy_rel)

def load_dashboard_module() -> Any:
    return dashboard_shared

def load_repo_dotenv_for_backend() -> int:
    return int(dashboard_shared.load_repo_dotenv(KIT_ROOT) or 0)

def load_observatory_module() -> Any:
    dashboard_app = load_dashboard_module()
    try:
        return dashboard_app.load_observatory_module()
    except Exception as exc:
        raise BackendError(
            "Could not import the existing Observatory helper.",
            error_type="observatory_import_failed",
            details={"path": str(OBSERVATORY_SCRIPT), "exception": str(exc)},
        ) from exc

def resolve_target(raw: str) -> Path:
    if not raw or not str(raw).strip():
        raise BackendError("A target path is required.", exit_code=2, error_type="invalid_target")
    target = Path(raw).expanduser()
    try:
        resolved = target.resolve()
    except OSError as exc:
        raise BackendError(
            "Could not resolve target path.",
            exit_code=2,
            error_type="invalid_target",
            details={"target": str(raw), "exception": str(exc)},
        ) from exc
    if not resolved.exists():
        raise BackendError(
            "Target path does not exist.",
            exit_code=2,
            error_type="invalid_target",
            details={"target": str(resolved)},
        )
    if not resolved.is_dir():
        raise BackendError(
            "Target path must be a directory.",
            exit_code=2,
            error_type="invalid_target",
            details={"target": str(resolved)},
        )
    return resolved

def resolve_review_dir(raw: str) -> Path:
    if not raw or not str(raw).strip():
        raise BackendError("A review directory is required.", exit_code=2, error_type="invalid_review_dir")
    path = Path(raw).expanduser()
    try:
        resolved = path.resolve()
    except OSError as exc:
        raise BackendError(
            "Could not resolve review directory.",
            exit_code=2,
            error_type="invalid_review_dir",
            details={"review_dir": str(raw), "exception": str(exc)},
        ) from exc
    if resolved.exists() and not resolved.is_dir():
        raise BackendError(
            "Review path exists but is not a directory.",
            exit_code=2,
            error_type="invalid_review_dir",
            details={"review_dir": str(resolved)},
        )
    try:
        resolved.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BackendError(
            "Could not create review directory.",
            exit_code=2,
            error_type="invalid_review_dir",
            details={"review_dir": str(resolved), "exception": str(exc)},
        ) from exc
    return resolved

def target_metadata(target: Path) -> dict[str, Any]:
    intake_path = existing_or_target_path(target, ".agentic/project_intake.json")
    dashboard_path = existing_or_target_path(target, ".agentic/dashboard_state.json")
    task_path = existing_or_target_path(target, "docs/CODEX_AUTOMATION_TASKS.md")
    return {
        "path": str(target),
        "name": target.name or str(target),
        "exists": target.exists(),
        "is_dir": target.is_dir(),
        "is_diffmogger_project": intake_path.exists() or task_path.exists(),
        "project_intake_path": str(intake_path),
        "project_intake_exists": intake_path.exists(),
        "dashboard_state_path": str(dashboard_path),
        "dashboard_state_exists": dashboard_path.exists(),
        "automation_task_path": str(task_path),
        "automation_task_exists": task_path.exists(),
    }

def load_intake(target: Path) -> dict[str, Any]:
    return read_json_file(existing_or_target_path(target, ".agentic/project_intake.json"))

def load_dashboard_state(target: Path) -> dict[str, Any]:
    return read_json_file(existing_or_target_path(target, ".agentic/dashboard_state.json"))

def write_dashboard_action_state(
    target: Path,
    *,
    last_action: str,
    updates: dict[str, Any] | None = None,
) -> Path:
    if target == KIT_ROOT:
        raise BackendError(
            "Refusing to write target dashboard state into the Diffmogger source checkout.",
            exit_code=2,
            error_type="invalid_target",
            details={"target": str(target)},
        )
    state = load_dashboard_state(target)
    state.update(updates or {})
    state["schema_version"] = int(state.get("schema_version") or 1)
    state["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    state["last_action"] = last_action
    state_path = preferred_target_path(target, ".agentic/dashboard_state.json")
    write_json_file(state_path, state)
    return state_path

def normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [line.strip().removeprefix("-").strip() for line in value.splitlines() if line.strip()]
    return []

def dashboard_state_from_intake(
    target: Path,
    intake: dict[str, Any],
    *,
    last_action: str,
) -> dict[str, Any]:
    dashboard_app = load_dashboard_module()
    existing = load_dashboard_state(target)
    optional_mcp = dashboard_app.optional_mcp_servers_from_value(intake.get("optional_mcp_servers"))
    write_workers_enabled = bool(intake.get("write_worker_agents_allowed")) and bool(intake.get("worker_agents_allowed", True))
    raw_role_profile = str(intake.get("automation_role_profile") or "").strip()
    requested_multi_role = bool(intake.get("multi_role_automations_allowed", True))
    if raw_role_profile == "single_lane" or not requested_multi_role:
        automation_role_profile = "single_lane"
        multi_role_enabled = False
    else:
        automation_role_profile = "planner_builder_hardener_integrator"
        multi_role_enabled = True
    state = {
        **existing,
        "schema_version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_name": str(intake.get("project_name") or target.name or "New Project"),
        "project_mode": str(intake.get("project_mode") or "fresh_project"),
        "human_bridge_enabled": bool(intake.get("human_bridge_enabled", True)),
        "human_bridge_mode": str(intake.get("human_bridge_mode") or "file_only"),
        "human_requested_text_responses": bool(intake.get("human_requested_text_responses", True)),
        "local_notifications_enabled": bool(intake.get("local_notifications_enabled", True)),
        "env_access_policy": str(intake.get("env_access_policy") or "project_commands_only"),
        "worker_agents_allowed": bool(intake.get("worker_agents_allowed", True)),
        "codex_cli_workers_expected_on_broad_runs": bool(intake.get("codex_cli_workers_expected_on_broad_runs", True)),
        "optional_mcp_servers": optional_mcp,
        "write_worker_agents_allowed": write_workers_enabled,
        "max_write_worker_count": dashboard_app.write_worker_count_from_text(
            intake.get("max_write_worker_count"),
            enabled=write_workers_enabled,
        ),
        "multi_role_automations_allowed": multi_role_enabled,
        "automation_role_profile": automation_role_profile,
        "automation_checkpoint_commits": bool(intake.get("automation_checkpoint_commits", True)),
        "multi_role_allow_remotes": bool(intake.get("multi_role_allow_remotes", False)),
        "automation_run_mode": str(intake.get("automation_run_mode") or "continuous_improvement"),
        "ticket_run_file": str(intake.get("ticket_run_file") or sidecar_rel("docs/TICKET_RUN.md")),
        "ticket_completion_notify": bool(intake.get("ticket_completion_notify", True)),
        "overwrite_existing_scaffold_files": bool(intake.get("overwrite_existing_scaffold_files", False)),
        "brief_draft_intake": intake,
        "last_action": last_action,
    }
    return state

def project_intake_payload(intake: dict[str, Any]) -> dict[str, Any]:
    payload = dict(intake)
    payload.pop("overwrite_existing_scaffold_files", None)
    return payload

def write_dashboard_state_from_intake(target: Path, intake: dict[str, Any], *, last_action: str) -> Path:
    if target == KIT_ROOT:
        raise BackendError(
            "Refusing to write target dashboard state into the Diffmogger source checkout.",
            exit_code=2,
            error_type="invalid_target",
            details={"target": str(target)},
        )
    state_path = preferred_target_path(target, ".agentic/dashboard_state.json")
    write_json_file(state_path, dashboard_state_from_intake(target, intake, last_action=last_action))
    return state_path

def detect_target_context(target: Path) -> dict[str, Any]:
    def exists(*parts: str) -> bool:
        return (target.joinpath(*parts)).exists()

    def read_package_scripts() -> dict[str, str]:
        package = read_json_file(target / "package.json")
        scripts = package.get("scripts") if isinstance(package.get("scripts"), dict) else {}
        return {str(key): str(value) for key, value in scripts.items()}

    def git_output(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=str(target),
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
        )

    package_manager = "unknown"
    if exists("pnpm-lock.yaml"):
        package_manager = "pnpm"
    elif exists("yarn.lock"):
        package_manager = "yarn"
    elif exists("package-lock.json"):
        package_manager = "npm"
    elif exists("bun.lockb") or exists("bun.lock"):
        package_manager = "bun"
    elif exists("uv.lock"):
        package_manager = "uv"
    elif exists("poetry.lock"):
        package_manager = "poetry"
    elif exists("package.json"):
        package_manager = "npm"
    elif exists("pyproject.toml"):
        package_manager = "python"

    scripts = read_package_scripts()
    suggested_commands: list[str] = []
    if scripts:
        runner = {"pnpm": "pnpm", "yarn": "yarn", "bun": "bun"}.get(package_manager, "npm run")
        for name in ["test", "lint", "typecheck", "build", "dev"]:
            if name in scripts:
                suggested_commands.append(f"{runner} {name}" if runner != "yarn" else f"yarn {name}")
    if exists("pyproject.toml"):
        if not suggested_commands:
            suggested_commands.extend(["python -m pytest", "python -m unittest"])
    if exists("Cargo.toml"):
        suggested_commands.extend(["cargo test", "cargo check"])

    try:
        branch = git_output(["branch", "--show-current"])
        status = git_output(["status", "--short"])
        remotes = git_output(["remote", "-v"])
        is_git_repo = branch.returncode == 0 or status.returncode == 0
        dirty_count = len([line for line in status.stdout.splitlines() if line.strip()]) if status.returncode == 0 else 0
    except OSError:
        is_git_repo = False
        dirty_count = 0
        branch = subprocess.CompletedProcess([], 1, "", "")
        remotes = subprocess.CompletedProcess([], 1, "", "")

    return {
        "is_git_repo": is_git_repo,
        "git_branch": branch.stdout.strip() if branch.returncode == 0 else "unknown",
        "git_dirty_count": dirty_count,
        "has_remotes": bool(remotes.stdout.strip()) if remotes.returncode == 0 else False,
        "package_manager": package_manager,
        "package_scripts": scripts,
        "suggested_verification_commands": suggested_commands,
        "detected_files": {
            "package_json": exists("package.json"),
            "pyproject_toml": exists("pyproject.toml"),
            "cargo_toml": exists("Cargo.toml"),
            "go_mod": exists("go.mod"),
            "makefile": exists("Makefile") or exists("makefile"),
        },
    }

def optional_mcp_from_state(target: Path, dashboard_app: Any) -> list[str]:
    dashboard_state = load_dashboard_state(target)
    if "optional_mcp_servers" in dashboard_state:
        return dashboard_app.optional_mcp_servers_from_value(dashboard_state.get("optional_mcp_servers"))
    intake = load_intake(target)
    return dashboard_app.optional_mcp_servers_from_value(intake.get("optional_mcp_servers"))

def human_bridge_mode_from_state(target: Path) -> str:
    for data in (load_intake(target), load_dashboard_state(target)):
        mode = str(data.get("human_bridge_mode") or "").strip()
        enabled = bool(data.get("human_bridge_enabled", mode != "disabled"))
        if enabled and mode in {"file_only", "local_notifier", "discord_notifier"}:
            return mode
        if mode == "disabled":
            return "disabled"
    return "file_only"

def build_observatory_snapshot(target: Path) -> dict[str, Any]:
    module = load_observatory_module()
    try:
        return module.build_snapshot(target)
    except Exception as exc:
        raise BackendError(
            "Could not build Observatory snapshot for target.",
            error_type="snapshot_failed",
            details={"target": str(target), "exception": str(exc)},
        ) from exc

def file_category(rel_path: str, group: str, label: str) -> str:
    path = rel_path.replace("\\", "/")
    lower = f"{label} {path}".lower()
    if group == "human" or "human_" in lower:
        return "Human bridge"
    if any(term in lower for term in ("review", "observatory", "safety", "daily review", "experiment log")):
        return "Review"
    if "context" in lower:
        return "Context"
    if any(term in lower for term in ("multi-role", "multi_role", "conveyor", "automation_queue", "signals", "role")):
        return "Multi-role / conveyor"
    return "Core state"

def validation_kind_for_file(rel_path: str) -> str:
    if rel_path.endswith(".json"):
        return "json"
    if rel_path in {"docs/CODEX_AUTOMATION_TASKS.md", sidecar_rel("docs/CODEX_AUTOMATION_TASKS.md")}:
        return "required_files"
    if rel_path in {"docs/TICKET_RUN.md", sidecar_rel("docs/TICKET_RUN.md")}:
        return "ticket_run"
    if rel_path in {"target/integration_safety_check.json", sidecar_rel("target/integration_safety_check.json")}:
        return "integration_safety_record"
    return ""

def file_registry(dashboard_app: Any) -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}

    def add(prefix: str, label: str, rel_path: str, *, editable: bool = True) -> None:
        key_base = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "file"
        key = f"{prefix}.{key_base}"
        registry[key] = {
            "key": key,
            "label": label,
            "rel_path": rel_path,
            "group": prefix,
            "category": file_category(rel_path, prefix, label),
            "editable": editable,
            "validation": validation_kind_for_file(rel_path),
        }

    for label, rel_path in dashboard_app.DOC_CHOICES.items():
        add("monitor", label, rel_path)
    for label, rel_path in dashboard_app.HUMAN_DOC_CHOICES.items():
        add("human", label, rel_path)
    registry["state.project_intake"] = {
        "key": "state.project_intake",
        "label": "Project Intake JSON",
        "rel_path": sidecar_rel(".agentic/project_intake.json"),
        "group": "state",
        "category": "Core state",
        "editable": True,
        "validation": "json",
    }
    registry["state.dashboard"] = {
        "key": "state.dashboard",
        "label": "Dashboard State JSON",
        "rel_path": sidecar_rel(".agentic/dashboard_state.json"),
        "group": "state",
        "category": "Core state",
        "editable": True,
        "validation": "json",
    }
    registry["state.integration_safety"] = {
        "key": "state.integration_safety",
        "label": "Integration Safety Record",
        "rel_path": sidecar_rel("target/integration_safety_check.json"),
        "group": "state",
        "category": "Review",
        "editable": False,
        "validation": "json",
    }
    registry["review.self_review"] = {
        "key": "review.self_review",
        "label": "Self-Review Markdown",
        "rel_path": sidecar_rel(f"target/first-review/{DEFAULT_REVIEW_MARKDOWN}"),
        "group": "review",
        "category": "Review",
        "editable": True,
        "validation": "",
    }
    registry["review.observatory_html"] = {
        "key": "review.observatory_html",
        "label": "Observatory HTML Export",
        "rel_path": sidecar_rel(f"target/first-review/{DEFAULT_REVIEW_HTML}"),
        "group": "review",
        "category": "Review",
        "editable": False,
        "validation": "",
    }
    registry["state.conveyor"] = {
        "key": "state.conveyor",
        "label": "Conveyor State JSON",
        "rel_path": sidecar_rel("target/automation_conveyor_state.json"),
        "group": "state",
        "category": "Multi-role / conveyor",
        "editable": True,
        "validation": "json",
    }
    registry["state.action_plan_history"] = {
        "key": "state.action_plan_history",
        "label": "Action Plan History JSON",
        "rel_path": sidecar_rel("target/action_plan_history.json"),
        "group": "state",
        "category": "Review",
        "editable": True,
        "validation": "json",
    }
    return registry

def describe_registered_file(target: Path, record: dict[str, Any]) -> dict[str, Any]:
    path = (target / record["rel_path"]).resolve()
    if target not in path.parents and path != target:
        raise BackendError(
            "Registered file resolved outside the target.",
            exit_code=2,
            error_type="invalid_file_key",
            details={"file_key": record["key"], "path": str(path)},
        )
    exists = path.exists() and path.is_file()
    size = path.stat().st_size if exists else None
    return {
        **record,
        "path": str(path),
        "exists": exists,
        "size_bytes": size,
        "modified_at": mtime_iso(path) if exists else None,
    }
