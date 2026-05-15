"""Canonical typed SQLite state for Diffmogger orchestration.

The runtime keeps SQLite as the authoritative control-plane store. JSON files
under ``.diffmogger/runtime`` are generated projections for compatibility and
human/debug tooling; they are never the source of truth once this module has
initialized a target.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from diffmogger.runtime.blocker_review import adjudicate_baseline_blocker
from diffmogger.runtime import codebase_graph
from diffmogger.runtime.paths import existing_or_target_path, target_path, target_rel


STATE_SCHEMA_VERSION = 6
STATE_APPLICATION_ID = 0x444D4752  # DMGR
CANONICAL_DB_RELATIVE = "target/orchestration.sqlite3"
CONVEYOR_PROJECTION_RELATIVE = "target/automation_conveyor_state.json"
CONVEYOR_STREAM_ID = "stream:conveyor"
CONVEYOR_TASK_ID = "task:conveyor"
CONVEYOR_WORK_ITEM_ID = "workitem:default"
CONVEYOR_PROJECTION_NAME = "conveyor.state"
CONVEYOR_MACHINE_PROJECTION_NAME = "conveyor.machine"
BLOCKER_REVIEW_PROJECTION_NAME = "blocker.review"
CAPABILITY_PROJECTION_NAME = "repo.capability_manifest"
CAPABILITY_MANIFEST_ID = "capability:repo"
CODEBASE_GRAPH_NAMESPACE = "codebase"
CODEBASE_GRAPH_SCAN_LIMIT = 5000
TASK_GRAPH_NAMESPACE = "task"
TASK_GRAPH_NODE_KINDS = (
    "ticket",
    "work_item",
    "run",
    "blocker",
    "approval",
    "validation_plan",
    "recovery_playbook",
    "worker_assignment",
)
TASK_GRAPH_EDGE_KINDS = (
    "depends_on",
    "blocks",
    "supersedes",
    "duplicates",
    "validates",
    "repairs",
    "spawned_by",
)
TASK_DONE_STATUSES = {"done", "resolved", "closed", "complete", "completed", "superseded"}
TASK_PENDING_STATUSES = {"pending", "open", "active", "in_progress", "running", "waiting", "blocked"}
TASK_BLOCKED_STATUSES = {"blocked", "blocked_on_user", "blocked_on_environment"}
IMPACT_GRAPH_NAMESPACE = "impact"
IMPACT_GRAPH_EDGE_KINDS = (
    "likely_touches",
    "touched_by",
    "read_by",
    "owns_lease_for",
    "conflicts_with",
    "requires_validation",
    "requires_human_approval",
    "relevant_context_for",
)
IMPACT_CONTEXT_PACK_LIMIT = 12
IMPACT_CONTEXT_SECRET_BASENAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    ".npmrc",
    ".pypirc",
}
RESOURCE_LEASE_SCOPE_KINDS = {"file", "directory", "module", "command", "repo"}
RESOURCE_LEASE_STATUSES = {"active", "released", "expired", "superseded"}
AUTOMATION_CONTROL_ID = "automation-control:default"
AUTOMATION_CONTROL_STREAM_ID = "stream:automation-control"
AUTOMATION_CONTROL_TASK_ID = "task:automation-control"
AUTOMATION_CONTROL_PROJECTION_NAME = "automation.control"
CONVEYOR_MACHINE_VERSION = 1
STAGE_CONTRACT_VERSION = 1
RUNNER_PROJECTION_RELATIVE = "target/automation_runner.json"
RUNNER_STREAM_ID = "stream:automation-runner"
RUNNER_TASK_ID = "task:automation-runner"
RUNNER_PROJECTION_NAME = "automation.runner"
CANONICAL_STATE_BRIEF_RELATIVE = "target/canonical_state_brief.md"
CANONICAL_STATE_BRIEF_PROJECTION_NAME = "canonical.state_brief"
HUMAN_STREAM_ID = "stream:human-messages"
HUMAN_TASK_ID = "task:human-messages"
HUMAN_PROJECTION_NAME = "human.messages"
TICKET_STREAM_ID = "stream:ticket-run"
TICKET_TASK_ID = "task:ticket-run"
TICKET_RUN_PROJECTION_NAME = "ticket.run"
DEFAULT_EVENT_LIMIT = 20
BRIEF_ITEM_LIMIT = 8
BRIEF_TEXT_LIMIT = 240

STATUS_MODEL = (
    "ACTIVE",
    "ACTIVE_WITH_PENDING_USER_INPUT",
    "BLOCKED_ON_USER",
    "BLOCKED_ON_ENVIRONMENT",
    "CRITICAL_STOP",
)

ORCHESTRATION_TABLES = (
    "meta",
    "streams",
    "events",
    "checkpoints",
    "tasks",
    "runs",
    "worktrees",
    "validations",
    "assumptions",
    "decisions",
    "blockers",
    "artifacts",
    "next_actions",
    "projections",
    "human_messages",
    "ticket_runs",
    "ticket_items",
    "automation_control",
    "conveyor_work_items",
    "conveyor_stage_contracts",
    "conveyor_stage_attempts",
    "capability_manifests",
    "graph_snapshots",
    "graph_nodes",
    "graph_edges",
    "graph_node_facts",
    "graph_edge_facts",
    "resource_leases",
    "scheduler_candidates",
    "validation_receipts",
    "escalations",
    "task_edges",
    "schema_migrations",
    "compatibility_migrations",
)

CONVEYOR_STAGES = (
    "intake",
    "discovery",
    "decomposition",
    "planning",
    "implementation",
    "review",
    "validation",
    "integration",
    "handoff",
    "continuation",
)

STAGE_TO_OWNER_ROLE = {
    "intake": "planner",
    "discovery": "planner",
    "decomposition": "planner",
    "planning": "planner",
    "implementation": "builder",
    "review": "hardener",
    "validation": "hardener",
    "integration": "integrator",
    "handoff": "planner",
    "continuation": "conveyor",
}

ROLE_TO_CONVEYOR_STAGE = {
    "planner": ("planning", "planner"),
    "builder": ("implementation", "builder"),
    "single_lane": ("implementation", "single_lane"),
    "hardener": ("validation", "hardener"),
    "integrator": ("integration", "integrator"),
}

CAPABILITY_SCAN_IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".diffmogger",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "dist-ssr",
    "build",
    "target",
    "coverage",
    ".next",
    ".turbo",
    "vendor",
}

LOCKFILE_NAMES = {
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lock",
    "bun.lockb",
    "Cargo.lock",
    "poetry.lock",
    "uv.lock",
    "requirements.txt",
    "go.sum",
    "Gemfile.lock",
    "composer.lock",
}

GRAPH_FILE_NODE_KINDS = {"file", "test_file", "config_file", "doc_file", "lockfile"}
CODEBASE_GRAPH_PARTIAL_REINDEX_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}

CONFIG_FILE_NAMES = {
    ".babelrc",
    ".env.example",
    ".eslintrc",
    ".eslintrc.cjs",
    ".eslintrc.js",
    ".eslintrc.json",
    ".gitignore",
    ".prettierrc",
    ".prettierrc.json",
    ".python-version",
    ".ruby-version",
    ".tool-versions",
    "Cargo.toml",
    "Dockerfile",
    "Gemfile",
    "Makefile",
    "Pipfile",
    "bunfig.toml",
    "compose.yaml",
    "docker-compose.yml",
    "go.mod",
    "jest.config.js",
    "jest.config.ts",
    "mypy.ini",
    "package.json",
    "playwright.config.js",
    "playwright.config.ts",
    "pyproject.toml",
    "pytest.ini",
    "ruff.toml",
    "setup.cfg",
    "setup.py",
    "tox.ini",
    "tsconfig.json",
    "vite.config.js",
    "vite.config.ts",
}

LANGUAGE_BY_EXTENSION = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".rs": "Rust",
    ".go": "Go",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".c": "C",
    ".h": "C/C++",
    ".cc": "C++",
    ".cpp": "C++",
    ".hpp": "C++",
    ".swift": "Swift",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".sql": "SQL",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "CSS",
    ".md": "Markdown",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".json": "JSON",
    ".toml": "TOML",
}

HUMAN_REQUEST_ACTIVE_STATUSES = {"active", "awaiting_user", "awaiting_human", "pending", "open", "unresolved"}
HUMAN_ARCHIVE_STATUSES = {"resolved", "handled", "consumed", "archived", "done", "closed", "skipped"}
HUMAN_NOTE_ACTIVE_STATUSES = {"unhandled", "queued", "failed", "pending", "open"}
TICKET_ITEM_STATUSES = {"pending", "in_progress", "candidate_done", "done", "blocked"}
TICKET_CAMPAIGN_HORIZONS = (
    "T1 Ticket-run readiness",
    "T2 Ticket implementation",
    "T3 Verification and hardening",
    "T4 Completion report and stop",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def pretty_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, default=str) + "\n"


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_json_file(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json_projection(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(pretty_json(payload), encoding="utf-8")
    tmp.replace(path)


def default_conveyor_state() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "state_machine_version": CONVEYOR_MACHINE_VERSION,
        "status": "ACTIVE",
        "cycles": 0,
        "role_counts": {},
        "history": [],
    }


def normalize_conveyor_state(state: Mapping[str, Any] | None) -> dict[str, Any]:
    normalized = dict(state or {})
    normalized.setdefault("schema_version", 2)
    normalized.setdefault("state_machine_version", CONVEYOR_MACHINE_VERSION)
    normalized.setdefault("status", "ACTIVE")
    normalized.setdefault("cycles", 0)
    normalized.setdefault("role_counts", {})
    normalized.setdefault("history", [])
    if not isinstance(normalized.get("role_counts"), dict):
        normalized["role_counts"] = {}
    if not isinstance(normalized.get("history"), list):
        normalized["history"] = []
    return normalized


def normalize_runner_state(state: Mapping[str, Any] | None) -> dict[str, Any]:
    normalized = dict(state or {})
    if not normalized:
        return {}
    normalized.setdefault("schema_version", 1)
    return normalized


def database_path_for_target(target: Path) -> Path:
    return target_path(target.expanduser().resolve(), CANONICAL_DB_RELATIVE)


def conveyor_projection_path_for_target(target: Path) -> Path:
    return target_path(target.expanduser().resolve(), CONVEYOR_PROJECTION_RELATIVE)


def runner_projection_path_for_target(target: Path) -> Path:
    return target_path(target.expanduser().resolve(), RUNNER_PROJECTION_RELATIVE)


def canonical_state_brief_path_for_target(target: Path) -> Path:
    return target_path(target.expanduser().resolve(), CANONICAL_STATE_BRIEF_RELATIVE)


def database_path_for_projection(projection_path: Path) -> Path:
    path = projection_path.expanduser()
    if path.name in {Path(CONVEYOR_PROJECTION_RELATIVE).name, Path(RUNNER_PROJECTION_RELATIVE).name}:
        return path.with_name("orchestration.sqlite3")
    return path.with_suffix(".sqlite3")


@dataclass(frozen=True)
class StateEvent:
    stream_id: str
    event_type: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    actor_role: str = "runtime"
    actor_id: str = ""
    phase: str = ""
    status: str = ""
    task_id: str = ""
    run_id: str = ""
    causation_id: int | None = None
    correlation_id: str = ""
    occurred_at: str = ""


def default_stage_contracts() -> dict[str, dict[str, Any]]:
    """Reusable stage contracts for the project-agnostic conveyor state machine."""

    contracts: dict[str, dict[str, Any]] = {
        "intake": {
            "entry_criteria": ["external request, generated intake, ticket queue, or existing task state is present"],
            "required_artifacts": ["canonical work item", "requested outcome", "acceptance criteria or honest unknown"],
            "allowed_tools": ["dashboard", "typed_state_api", "read_repo_metadata"],
            "exit_criteria": ["work item has repository identity, base revision, constraints, and risk tier"],
            "retry_policy": {"max_attempts": 2, "backoff_seconds": 60, "on_exhausted": "handoff"},
            "escalation_policy": {"trigger": "ambiguous or unsafe requested outcome", "target": "user"},
            "parallelism": {"mode": "serial", "may_spawn_children": False},
        },
        "discovery": {
            "entry_criteria": ["work item exists", "target repository path is known"],
            "required_artifacts": ["capability manifest", "repo instruction list", "build/test command candidates"],
            "allowed_tools": ["read_repo", "git_status", "capability_scan", "read_only_workers"],
            "exit_criteria": ["capability manifest is current for repository files and lockfiles"],
            "retry_policy": {"max_attempts": 3, "backoff_seconds": 120, "on_exhausted": "handoff"},
            "escalation_policy": {"trigger": "no runnable verification path can be inferred", "target": "planner"},
            "parallelism": {"mode": "read_only_fanout", "may_spawn_children": True},
        },
        "decomposition": {
            "entry_criteria": ["capability manifest exists", "requested outcome is bounded"],
            "required_artifacts": ["subtask or lane plan", "dependency notes", "predicted write scopes"],
            "allowed_tools": ["planner", "read_repo", "typed_state_api"],
            "exit_criteria": ["next implementation, validation, or integration lane is explicit"],
            "retry_policy": {"max_attempts": 3, "backoff_seconds": 120, "on_exhausted": "handoff"},
            "escalation_policy": {"trigger": "dependencies or scope cannot be made safe", "target": "user"},
            "parallelism": {"mode": "serial_planning", "may_spawn_children": False},
        },
        "planning": {
            "entry_criteria": ["discovery evidence is available", "no higher-priority blocker owns the next move"],
            "required_artifacts": ["plan artifact", "validation plan", "risk notes"],
            "allowed_tools": ["planner", "read_repo", "context_packs", "typed_state_api"],
            "exit_criteria": ["implementation or review lane has an owner and a reason"],
            "retry_policy": {"max_attempts": 3, "backoff_seconds": 120, "on_exhausted": "handoff"},
            "escalation_policy": {"trigger": "plan conflict or repeated no-progress", "target": "user_or_planner"},
            "parallelism": {"mode": "mostly_serial", "may_spawn_children": True},
        },
        "implementation": {
            "entry_criteria": ["plan or bounded ticket is selected", "write scope is allowed"],
            "required_artifacts": ["patch artifact or implementation notes", "changed-file metadata", "local evidence"],
            "allowed_tools": ["builder", "single_lane", "isolated_worktree", "bounded_write_workers"],
            "exit_criteria": ["candidate patch is queued, committed, blocked, or explicitly handed off"],
            "retry_policy": {"max_attempts": 3, "backoff_seconds": 300, "on_exhausted": "validation_or_handoff"},
            "escalation_policy": {"trigger": "unsafe mutation, unknown dependency, or repeated patch churn", "target": "planner"},
            "parallelism": {"mode": "write_scope_leases", "may_spawn_children": True},
        },
        "review": {
            "entry_criteria": ["candidate change or queued patch exists"],
            "required_artifacts": ["review record", "policy findings", "missing-test notes"],
            "allowed_tools": ["hardener", "read_repo", "diff_review", "read_only_workers"],
            "exit_criteria": ["change is accepted for validation, sent for repair, or blocked with evidence"],
            "retry_policy": {"max_attempts": 2, "backoff_seconds": 180, "on_exhausted": "planning"},
            "escalation_policy": {"trigger": "policy finding requires human judgment", "target": "user"},
            "parallelism": {"mode": "review_fanout_then_serial_decision", "may_spawn_children": True},
        },
        "validation": {
            "entry_criteria": ["candidate change, baseline preflight, or ticket candidate needs proof"],
            "required_artifacts": ["validation receipts", "command logs", "environment lease"],
            "allowed_tools": ["hardener", "integrator", "test_runner", "browser_validation", "ci_probe"],
            "exit_criteria": ["required receipts pass, fail with blocker, or expire as stale"],
            "retry_policy": {"max_attempts": 3, "backoff_seconds": 300, "on_exhausted": "repair_or_handoff"},
            "escalation_policy": {"trigger": "environment cannot be reproduced", "target": "environment"},
            "parallelism": {"mode": "validation_fanout", "may_spawn_children": True},
        },
        "integration": {
            "entry_criteria": ["validated candidate or queued role patch exists"],
            "required_artifacts": ["integration result", "checkpoint commit or deferral record", "post-integration validation"],
            "allowed_tools": ["integrator", "git_worktree", "patch_queue", "validation_runner"],
            "exit_criteria": ["change is integrated with evidence, deferred with machine-readable reason, or stopped"],
            "retry_policy": {"max_attempts": 2, "backoff_seconds": 300, "on_exhausted": "planning"},
            "escalation_policy": {"trigger": "merge conflict, protected path, or remote/policy boundary", "target": "user_or_planner"},
            "parallelism": {"mode": "serialized_integrator", "may_spawn_children": False},
        },
        "handoff": {
            "entry_criteria": ["human input, environment action, or policy decision is required"],
            "required_artifacts": ["escalation record", "minimum context", "resume token"],
            "allowed_tools": ["dashboard", "human_message_state", "notifier_when_enabled"],
            "exit_criteria": ["reply is recorded, blocker is closed, or continuation is suspended"],
            "retry_policy": {"max_attempts": 1, "backoff_seconds": 0, "on_exhausted": "suspend"},
            "escalation_policy": {"trigger": "unanswered blocking decision", "target": "user"},
            "parallelism": {"mode": "interrupt_wait", "may_spawn_children": False},
        },
        "continuation": {
            "entry_criteria": ["run is complete, blocked, idle, or ready to roll forward"],
            "required_artifacts": ["continuation decision", "next action queue", "state brief"],
            "allowed_tools": ["conveyor", "typed_state_api", "dashboard"],
            "exit_criteria": ["completed, suspended, forked, or next bounded run is selected"],
            "retry_policy": {"max_attempts": 1, "backoff_seconds": 0, "on_exhausted": "suspend"},
            "escalation_policy": {"trigger": "no ready work above policy threshold", "target": "dashboard"},
            "parallelism": {"mode": "serial_decision", "may_spawn_children": False},
        },
    }
    for stage, contract in contracts.items():
        contract["stage"] = stage
        contract["schema_version"] = STAGE_CONTRACT_VERSION
    return contracts


def target_from_projection_path(projection_path: Path) -> Path:
    path = projection_path.expanduser().resolve()
    parts = list(path.parts)
    if ".diffmogger" in parts:
        index = parts.index(".diffmogger")
        return Path(*parts[:index]) if index > 0 else path.parent
    if path.parent.name == "target":
        return path.parent.parent
    return path.parent


def git_value(target: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=target,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def read_optional_text(path: Path, *, limit: int = 200_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def file_digest(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    return hashlib.sha256(data).hexdigest()


def _gitignore_directory_patterns(target: Path) -> set[str]:
    patterns: set[str] = set()
    for raw in read_optional_text(target / ".gitignore", limit=80_000).splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        if any(token in line for token in ("*", "?", "[")):
            continue
        directory_pattern = line.endswith("/")
        pattern = line.strip("/").lstrip("/")
        if not pattern:
            continue
        if directory_pattern or "/" in pattern or "." not in Path(pattern).name:
            patterns.add(pattern)
    return patterns


def _ignored_repo_directory(rel: Path, ignored_patterns: set[str]) -> bool:
    name = rel.name
    if name in CAPABILITY_SCAN_IGNORED_DIRS or name.startswith(".cache"):
        return True
    rel_text = rel.as_posix().strip("/")
    for pattern in ignored_patterns:
        if "/" in pattern:
            if rel_text == pattern or rel_text.startswith(pattern.rstrip("/") + "/"):
                return True
        elif name == pattern:
            return True
    return False


def scan_repo_paths(target: Path, *, limit: int = CODEBASE_GRAPH_SCAN_LIMIT) -> tuple[list[Path], list[Path], bool]:
    directories: list[Path] = []
    files: list[Path] = []
    ignored_patterns = _gitignore_directory_patterns(target)
    truncated = False
    for root, dirnames, filenames in os.walk(target):
        root_path = Path(root)
        try:
            root_rel = root_path.relative_to(target)
        except ValueError:
            continue
        kept_dirnames: list[str] = []
        for name in sorted(dirnames):
            rel = (root_rel / name) if root_rel != Path(".") else Path(name)
            if _ignored_repo_directory(rel, ignored_patterns):
                continue
            kept_dirnames.append(name)
            directories.append(root_path / name)
        dirnames[:] = kept_dirnames
        for filename in sorted(filenames):
            path = root_path / filename
            try:
                rel = path.relative_to(target)
            except ValueError:
                continue
            if any(part in CAPABILITY_SCAN_IGNORED_DIRS for part in rel.parts):
                continue
            files.append(path)
            if len(files) >= limit:
                truncated = True
                return directories, files, truncated
    return directories, files, truncated


def scan_repo_files(target: Path, *, limit: int = 5000) -> list[Path]:
    _, files, _ = scan_repo_paths(target, limit=limit)
    return files


def _json_file(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _line_commands(path: Path) -> list[str]:
    commands: list[str] = []
    for raw in read_optional_text(path, limit=40_000).splitlines():
        line = re.sub(r"^[-*]\s+", "", raw.strip())
        if line and not line.startswith("#"):
            commands.append(line)
    return commands


def discover_repo_capabilities(target: Path) -> dict[str, Any]:
    """Infer reusable repository capabilities without product-specific assumptions."""

    target = target.expanduser().resolve()
    files = scan_repo_files(target)
    rel_files = [path.relative_to(target).as_posix() for path in files]
    language_counts: dict[str, int] = {}
    for path in files:
        language = LANGUAGE_BY_EXTENSION.get(path.suffix.lower())
        if language:
            language_counts[language] = language_counts.get(language, 0) + 1

    markers = {rel: target / rel for rel in rel_files}
    lockfiles = [
        {"path": rel, "sha256": file_digest(path)}
        for rel, path in sorted(markers.items())
        if Path(rel).name in LOCKFILE_NAMES
    ]

    ci_files = [
        rel
        for rel in rel_files
        if rel.startswith(".github/workflows/") and Path(rel).suffix.lower() in {".yml", ".yaml"}
        or rel in {".gitlab-ci.yml", "azure-pipelines.yml", "Jenkinsfile"}
    ]
    instruction_files = [
        rel
        for rel in rel_files
        if Path(rel).name in {"AGENTS.md", "README.md", "CONTRIBUTING.md", "DEVELOPMENT.md", "CLAUDE.md"}
    ][:20]

    commands: list[dict[str, str]] = []
    verification_path = existing_or_target_path(target, ".agentic/verification_commands.txt")
    smoke_path = existing_or_target_path(target, ".agentic/smoke_commands.txt")
    for command in _line_commands(verification_path):
        commands.append({"kind": "verification", "command": command, "source": target_rel(target, ".agentic/verification_commands.txt")})
    for command in _line_commands(smoke_path):
        commands.append({"kind": "smoke", "command": command, "source": target_rel(target, ".agentic/smoke_commands.txt")})

    package_json = _json_file(target / "package.json")
    scripts = package_json.get("scripts") if isinstance(package_json.get("scripts"), dict) else {}
    for name in ("test", "lint", "typecheck", "build", "check"):
        if name in scripts:
            commands.append({"kind": name, "command": f"npm run {name}", "source": "package.json"})
    if (target / "pyproject.toml").exists() or (target / "pytest.ini").exists() or (target / "setup.cfg").exists():
        commands.append({"kind": "test", "command": "python3 -m pytest", "source": "python project metadata"})
    if (target / "Cargo.toml").exists():
        commands.append({"kind": "test", "command": "cargo test", "source": "Cargo.toml"})
        commands.append({"kind": "lint", "command": "cargo clippy --all-targets --all-features", "source": "Cargo.toml"})
    if (target / "go.mod").exists():
        commands.append({"kind": "test", "command": "go test ./...", "source": "go.mod"})
    if (target / "Makefile").exists():
        commands.append({"kind": "make", "command": "make test", "source": "Makefile"})

    analyzers: list[str] = []
    joined_ci = "\n".join(read_optional_text(target / rel, limit=20_000) for rel in ci_files).lower()
    if "codeql" in joined_ci:
        analyzers.append("codeql")
    if "eslint" in stable_json(package_json).lower():
        analyzers.append("eslint")
    if any((target / name).exists() for name in ("pyproject.toml", "ruff.toml", ".ruff.toml")):
        analyzers.append("ruff")
    if (target / "mypy.ini").exists() or "mypy" in read_optional_text(target / "pyproject.toml").lower():
        analyzers.append("mypy")
    if (target / "Cargo.toml").exists():
        analyzers.append("cargo-clippy")
    if (target / "go.mod").exists():
        analyzers.append("go-vet")

    head = git_value(target, "rev-parse", "--verify", "HEAD")
    branch = git_value(target, "branch", "--show-current")
    status_porcelain = git_value(target, "status", "--porcelain=v1", "--untracked-files=no")
    payload = {
        "schema_version": 1,
        "manifest_id": CAPABILITY_MANIFEST_ID,
        "generated_at": utc_now(),
        "repo": {
            "root": str(target),
            "name": target.name,
            "vcs": "git" if (target / ".git").exists() or git_value(target, "rev-parse", "--is-inside-work-tree") == "true" else "unknown",
            "branch": branch,
            "head_commit": head,
            "dirty_tracked_files": len([line for line in status_porcelain.splitlines() if line.strip()]),
        },
        "languages": {
            "counts": dict(sorted(language_counts.items(), key=lambda item: (-item[1], item[0]))),
            "primary": max(language_counts, key=language_counts.get) if language_counts else "unknown",
        },
        "files": {
            "scanned_count": len(files),
            "truncated": len(files) >= 5000,
            "instructions": instruction_files,
            "ci": ci_files[:40],
            "lockfiles": lockfiles,
        },
        "commands": commands,
        "analyzers": sorted(set(analyzers)),
        "policy": {
            "canonical_state": "sqlite",
            "agents_propose_transitions": True,
            "integration_serialized": True,
            "markdown_is_projection": True,
        },
    }
    payload["digest"] = sha256_text(stable_json({key: value for key, value in payload.items() if key != "generated_at"}))
    return payload


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(f"PRAGMA application_id = {STATE_APPLICATION_ID}")
    ensure_schema(conn)
    return conn


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def sqlite_user_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("PRAGMA user_version").fetchone()
    except sqlite3.Error:
        return 0
    if row is None:
        return 0
    try:
        return int(row[0] or 0)
    except (TypeError, ValueError):
        return 0


def create_schema_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            checksum TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'applied',
            details_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )


def create_codebase_graph_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS graph_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            graph_namespace TEXT NOT NULL,
            repo_root TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            head_commit TEXT NOT NULL DEFAULT '',
            dirty_tracked_file_count INTEGER NOT NULL DEFAULT 0,
            dirty_tracked_files_digest TEXT NOT NULL DEFAULT '',
            indexed_file_count INTEGER NOT NULL DEFAULT 0,
            directory_node_count INTEGER NOT NULL DEFAULT 0,
            command_node_count INTEGER NOT NULL DEFAULT 0,
            test_node_count INTEGER NOT NULL DEFAULT 0,
            stale_node_count INTEGER NOT NULL DEFAULT 0,
            digest TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_graph_snapshots_namespace
            ON graph_snapshots(graph_namespace, generated_at);

        CREATE TABLE IF NOT EXISTS graph_nodes (
            snapshot_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            graph_namespace TEXT NOT NULL,
            kind TEXT NOT NULL,
            path TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL DEFAULT '',
            digest TEXT NOT NULL DEFAULT '',
            is_stale INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY(snapshot_id, node_id),
            FOREIGN KEY(snapshot_id) REFERENCES graph_snapshots(snapshot_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_graph_nodes_kind
            ON graph_nodes(graph_namespace, kind, path);

        CREATE TABLE IF NOT EXISTS graph_edges (
            snapshot_id TEXT NOT NULL,
            edge_id TEXT NOT NULL,
            graph_namespace TEXT NOT NULL,
            kind TEXT NOT NULL,
            from_node_id TEXT NOT NULL,
            to_node_id TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY(snapshot_id, edge_id),
            FOREIGN KEY(snapshot_id) REFERENCES graph_snapshots(snapshot_id) ON DELETE CASCADE,
            FOREIGN KEY(snapshot_id, from_node_id) REFERENCES graph_nodes(snapshot_id, node_id) ON DELETE CASCADE,
            FOREIGN KEY(snapshot_id, to_node_id) REFERENCES graph_nodes(snapshot_id, node_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_graph_edges_kind
            ON graph_edges(graph_namespace, kind);
        CREATE INDEX IF NOT EXISTS idx_graph_edges_from
            ON graph_edges(snapshot_id, from_node_id);
        CREATE INDEX IF NOT EXISTS idx_graph_edges_to
            ON graph_edges(snapshot_id, to_node_id);

        CREATE TABLE IF NOT EXISTS graph_node_facts (
            snapshot_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            graph_namespace TEXT NOT NULL,
            fact_key TEXT NOT NULL,
            fact_value TEXT NOT NULL DEFAULT '',
            value_type TEXT NOT NULL DEFAULT 'text',
            source TEXT NOT NULL DEFAULT 'indexer',
            confidence REAL NOT NULL DEFAULT 1.0,
            PRIMARY KEY(snapshot_id, node_id, fact_key),
            FOREIGN KEY(snapshot_id, node_id) REFERENCES graph_nodes(snapshot_id, node_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS graph_edge_facts (
            snapshot_id TEXT NOT NULL,
            edge_id TEXT NOT NULL,
            graph_namespace TEXT NOT NULL,
            fact_key TEXT NOT NULL,
            fact_value TEXT NOT NULL DEFAULT '',
            value_type TEXT NOT NULL DEFAULT 'text',
            source TEXT NOT NULL DEFAULT 'indexer',
            confidence REAL NOT NULL DEFAULT 1.0,
            PRIMARY KEY(snapshot_id, edge_id, fact_key),
            FOREIGN KEY(snapshot_id, edge_id) REFERENCES graph_edges(snapshot_id, edge_id) ON DELETE CASCADE
        );
        """
    )


def create_resource_leases_table(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS resource_leases (
            lease_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL DEFAULT '',
            owner_role TEXT NOT NULL DEFAULT '',
            run_id TEXT NOT NULL DEFAULT '',
            scope_kind TEXT NOT NULL,
            scope_node_id TEXT NOT NULL,
            status TEXT NOT NULL,
            acquired_at TEXT NOT NULL,
            expires_at TEXT NOT NULL DEFAULT '',
            released_at TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_resource_leases_status
            ON resource_leases(status, expires_at);
        CREATE INDEX IF NOT EXISTS idx_resource_leases_scope
            ON resource_leases(scope_kind, scope_node_id, status);
        CREATE INDEX IF NOT EXISTS idx_resource_leases_task
            ON resource_leases(task_id, status);
        """
    )


def create_scheduler_candidates_table(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS scheduler_candidates (
            candidate_id TEXT PRIMARY KEY,
            decision_id TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT '',
            task_id TEXT NOT NULL DEFAULT '',
            action_kind TEXT NOT NULL DEFAULT '',
            score REAL NOT NULL DEFAULT 0,
            state TEXT NOT NULL DEFAULT 'ready',
            skipped_reason TEXT NOT NULL DEFAULT '',
            stop INTEGER NOT NULL DEFAULT 0,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_scheduler_candidates_decision
            ON scheduler_candidates(decision_id, state, score);
        CREATE INDEX IF NOT EXISTS idx_scheduler_candidates_generated
            ON scheduler_candidates(generated_at);
        """
    )


def migrate_schema_to_4(conn: sqlite3.Connection) -> None:
    """Introduce an explicit schema migration ledger.

    Earlier schema versions already created the current typed runtime tables
    idempotently from ``ensure_schema``. Version 4 makes that evolution
    auditable with a durable migration registry.
    """

    create_schema_migrations_table(conn)


def migrate_schema_to_5(conn: sqlite3.Connection) -> None:
    """Add durable codebase graph snapshots, nodes, edges, and facts."""

    create_codebase_graph_tables(conn)


def migrate_schema_to_6(conn: sqlite3.Connection) -> None:
    """Add typed resource leases and scheduler candidates."""

    create_resource_leases_table(conn)
    create_scheduler_candidates_table(conn)


SCHEMA_MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    4: migrate_schema_to_4,
    5: migrate_schema_to_5,
    6: migrate_schema_to_6,
}


def apply_schema_migrations(conn: sqlite3.Connection, *, starting_version: int) -> None:
    if starting_version > STATE_SCHEMA_VERSION:
        raise RuntimeError(
            f"SQLite state schema version {starting_version} is newer than supported version {STATE_SCHEMA_VERSION}."
        )
    for version in sorted(version for version in SCHEMA_MIGRATIONS if starting_version < version <= STATE_SCHEMA_VERSION):
        migration = SCHEMA_MIGRATIONS[version]
        checksum = sha256_text(f"{version}:{migration.__name__}:{migration.__doc__ or ''}")
        details = stable_json({"from_version": starting_version, "to_version": version})
        conn.commit()
        conn.execute("BEGIN")
        try:
            migration(conn)
            conn.execute(
                """
                INSERT INTO schema_migrations(version, name, applied_at, checksum, status, details_json)
                VALUES(?, ?, ?, ?, 'applied', ?)
                ON CONFLICT(version) DO UPDATE SET
                    name=excluded.name,
                    applied_at=excluded.applied_at,
                    checksum=excluded.checksum,
                    status=excluded.status,
                    details_json=excluded.details_json
                """,
                (version, migration.__name__, utc_now(), checksum, details),
            )
            conn.execute(f"PRAGMA user_version = {version}")
        except Exception:
            conn.rollback()
            raise
        else:
            conn.commit()
        starting_version = version

def ensure_schema(conn: sqlite3.Connection) -> None:
    starting_version = sqlite_user_version(conn)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS streams (
            stream_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            current_sequence INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            stream_id TEXT NOT NULL REFERENCES streams(stream_id) ON DELETE CASCADE,
            sequence INTEGER NOT NULL,
            occurred_at TEXT NOT NULL,
            event_type TEXT NOT NULL,
            actor_role TEXT NOT NULL,
            actor_id TEXT NOT NULL DEFAULT '',
            phase TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT '',
            task_id TEXT NOT NULL DEFAULT '',
            run_id TEXT NOT NULL DEFAULT '',
            causation_id INTEGER,
            correlation_id TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            prev_hash TEXT NOT NULL DEFAULT '',
            event_hash TEXT NOT NULL,
            UNIQUE(stream_id, sequence)
        );
        CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type, occurred_at);
        CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id, occurred_at);
        CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, occurred_at);

        CREATE TABLE IF NOT EXISTS checkpoints (
            checkpoint_id TEXT PRIMARY KEY,
            stream_id TEXT NOT NULL REFERENCES streams(stream_id) ON DELETE CASCADE,
            sequence INTEGER NOT NULL,
            kind TEXT NOT NULL,
            created_at TEXT NOT NULL,
            state_json TEXT NOT NULL,
            state_sha256 TEXT NOT NULL,
            event_id INTEGER REFERENCES events(event_id)
        );
        CREATE INDEX IF NOT EXISTS idx_checkpoints_stream ON checkpoints(stream_id, sequence);

        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            parent_task_id TEXT,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            phase TEXT NOT NULL,
            owner_role TEXT NOT NULL DEFAULT '',
            risk_tier TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            stream_id TEXT NOT NULL,
            status TEXT NOT NULL,
            phase TEXT NOT NULL,
            owner_role TEXT NOT NULL DEFAULT '',
            started_at TEXT NOT NULL DEFAULT '',
            finished_at TEXT NOT NULL DEFAULT '',
            base_commit TEXT NOT NULL DEFAULT '',
            head_commit TEXT NOT NULL DEFAULT '',
            worktree_id TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_runs_task ON runs(task_id, status);

        CREATE TABLE IF NOT EXISTS worktrees (
            worktree_id TEXT PRIMARY KEY,
            repo_root TEXT NOT NULL,
            path TEXT NOT NULL,
            branch TEXT NOT NULL DEFAULT '',
            base_commit TEXT NOT NULL DEFAULT '',
            head_commit TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS validations (
            validation_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            run_id TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL,
            command TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            started_at TEXT NOT NULL DEFAULT '',
            finished_at TEXT NOT NULL DEFAULT '',
            environment_digest TEXT NOT NULL DEFAULT '',
            log_artifact_id TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_validations_task ON validations(task_id, status);

        CREATE TABLE IF NOT EXISTS assumptions (
            assumption_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            status TEXT NOT NULL,
            scope TEXT NOT NULL DEFAULT '',
            text TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0,
            evidence_event_id INTEGER,
            introduced_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            invalidation_rule TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS decisions (
            decision_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            status TEXT NOT NULL,
            summary TEXT NOT NULL,
            owner_role TEXT NOT NULL DEFAULT '',
            decided_at TEXT NOT NULL,
            superseded_by TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS blockers (
            blocker_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            summary TEXT NOT NULL,
            resume_token TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_blockers_status ON blockers(status, kind);

        CREATE TABLE IF NOT EXISTS artifacts (
            artifact_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL DEFAULT '',
            run_id TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL,
            path TEXT NOT NULL,
            digest TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS next_actions (
            action_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            owner_role TEXT NOT NULL,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            priority INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            source_projection TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_next_actions_status ON next_actions(status, owner_role, priority);

        CREATE TABLE IF NOT EXISTS projections (
            name TEXT PRIMARY KEY,
            updated_at TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            event_id INTEGER REFERENCES events(event_id)
        );

        CREATE TABLE IF NOT EXISTS human_messages (
            message_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            intent TEXT NOT NULL DEFAULT '',
            request_id TEXT NOT NULL DEFAULT '',
            source_inbox_id TEXT NOT NULL DEFAULT '',
            channel TEXT NOT NULL DEFAULT '',
            sender TEXT NOT NULL DEFAULT '',
            recipient TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_human_messages_kind_status ON human_messages(kind, status, updated_at);
        CREATE INDEX IF NOT EXISTS idx_human_messages_request ON human_messages(request_id, updated_at);

        CREATE TABLE IF NOT EXISTS ticket_runs (
            run_id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'active',
            halt_when_complete INTEGER NOT NULL DEFAULT 1,
            notify_on_complete INTEGER NOT NULL DEFAULT 1,
            ticket_file TEXT NOT NULL DEFAULT '',
            report_path TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS ticket_items (
            ticket_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            position INTEGER NOT NULL,
            summary TEXT NOT NULL,
            status TEXT NOT NULL,
            blocker TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_ticket_items_run_status ON ticket_items(run_id, status, position);

        CREATE TABLE IF NOT EXISTS automation_control (
            control_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            last_updated TEXT NOT NULL DEFAULT '',
            current_horizon TEXT NOT NULL DEFAULT '',
            horizon_decision TEXT NOT NULL DEFAULT '',
            current_assessment TEXT NOT NULL DEFAULT '',
            best_next_milestone TEXT NOT NULL DEFAULT '',
            suggested_next_task TEXT NOT NULL DEFAULT '',
            bootstrap_status TEXT NOT NULL DEFAULT '',
            worker_agents_allowed INTEGER NOT NULL DEFAULT 1,
            write_workers_allowed INTEGER NOT NULL DEFAULT 0,
            max_write_worker_count INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS conveyor_work_items (
            work_item_id TEXT PRIMARY KEY,
            parent_work_item_id TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            current_stage TEXT NOT NULL,
            stage_status TEXT NOT NULL,
            owner_role TEXT NOT NULL DEFAULT '',
            dependency_state TEXT NOT NULL DEFAULT 'unblocked',
            workspace_id TEXT NOT NULL DEFAULT '',
            repo_root TEXT NOT NULL DEFAULT '',
            base_commit TEXT NOT NULL DEFAULT '',
            head_commit TEXT NOT NULL DEFAULT '',
            capability_manifest_id TEXT NOT NULL DEFAULT '',
            capability_manifest_version INTEGER NOT NULL DEFAULT 0,
            validation_status TEXT NOT NULL DEFAULT 'not_recorded',
            risk_tier TEXT NOT NULL DEFAULT 'medium',
            handoff_target TEXT NOT NULL DEFAULT '',
            continuation_token TEXT NOT NULL DEFAULT '',
            ledger_event_id INTEGER REFERENCES events(event_id),
            entered_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_conveyor_work_items_stage ON conveyor_work_items(current_stage, status, updated_at);

        CREATE TABLE IF NOT EXISTS conveyor_stage_contracts (
            stage TEXT PRIMARY KEY,
            schema_version INTEGER NOT NULL,
            entry_criteria_json TEXT NOT NULL,
            required_artifacts_json TEXT NOT NULL,
            allowed_tools_json TEXT NOT NULL,
            exit_criteria_json TEXT NOT NULL,
            retry_policy_json TEXT NOT NULL,
            escalation_policy_json TEXT NOT NULL,
            parallelism_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS conveyor_stage_attempts (
            attempt_id TEXT PRIMARY KEY,
            work_item_id TEXT NOT NULL,
            stage TEXT NOT NULL,
            status TEXT NOT NULL,
            owner_role TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '',
            run_id TEXT NOT NULL DEFAULT '',
            started_at TEXT NOT NULL DEFAULT '',
            finished_at TEXT NOT NULL DEFAULT '',
            event_id INTEGER REFERENCES events(event_id),
            payload_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_conveyor_stage_attempts_work ON conveyor_stage_attempts(work_item_id, stage, started_at);

        CREATE TABLE IF NOT EXISTS capability_manifests (
            manifest_id TEXT PRIMARY KEY,
            repo_root TEXT NOT NULL,
            version INTEGER NOT NULL,
            digest TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            languages_json TEXT NOT NULL DEFAULT '{}',
            commands_json TEXT NOT NULL DEFAULT '[]',
            ci_json TEXT NOT NULL DEFAULT '[]',
            lockfiles_json TEXT NOT NULL DEFAULT '[]',
            analyzers_json TEXT NOT NULL DEFAULT '[]',
            payload_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_capability_manifests_repo ON capability_manifests(repo_root, generated_at);

        CREATE TABLE IF NOT EXISTS validation_receipts (
            receipt_id TEXT PRIMARY KEY,
            work_item_id TEXT NOT NULL,
            run_id TEXT NOT NULL DEFAULT '',
            stage TEXT NOT NULL,
            kind TEXT NOT NULL,
            command TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            lease_json TEXT NOT NULL DEFAULT '{}',
            started_at TEXT NOT NULL DEFAULT '',
            finished_at TEXT NOT NULL DEFAULT '',
            log_artifact_id TEXT NOT NULL DEFAULT '',
            event_id INTEGER REFERENCES events(event_id),
            payload_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_validation_receipts_work ON validation_receipts(work_item_id, status, finished_at);

        CREATE TABLE IF NOT EXISTS escalations (
            escalation_id TEXT PRIMARY KEY,
            work_item_id TEXT NOT NULL,
            status TEXT NOT NULL,
            kind TEXT NOT NULL,
            question TEXT NOT NULL,
            options_json TEXT NOT NULL DEFAULT '[]',
            resume_token TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            event_id INTEGER REFERENCES events(event_id),
            payload_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_escalations_status ON escalations(status, kind, updated_at);

        CREATE TABLE IF NOT EXISTS task_edges (
            parent_task_id TEXT NOT NULL,
            child_task_id TEXT NOT NULL,
            relation TEXT NOT NULL DEFAULT 'depends_on',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY(parent_task_id, child_task_id, relation)
        );

        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            checksum TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'applied',
            details_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS compatibility_migrations (
            source_path TEXT PRIMARY KEY,
            source_sha256 TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            event_id INTEGER REFERENCES events(event_id)
        );
        """
    )
    create_codebase_graph_tables(conn)
    create_resource_leases_table(conn)
    create_scheduler_candidates_table(conn)
    conn.commit()
    apply_schema_migrations(conn, starting_version=starting_version)
    current_version = sqlite_user_version(conn)
    if current_version != STATE_SCHEMA_VERSION:
        raise RuntimeError(
            f"SQLite state schema migration stopped at version {current_version}; expected {STATE_SCHEMA_VERSION}."
        )
    now = utc_now()
    conn.execute(
        "INSERT INTO meta(key, value, updated_at) VALUES(?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        ("schema_version", str(STATE_SCHEMA_VERSION), now),
    )
    conn.execute(
        "INSERT INTO meta(key, value, updated_at) VALUES(?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        ("state_authority", "sqlite", now),
    )
    seed_stage_contracts(conn)
    conn.commit()


def seed_stage_contracts(conn: sqlite3.Connection) -> None:
    now = utc_now()
    with conn:
        for stage, contract in default_stage_contracts().items():
            conn.execute(
                """
                INSERT INTO conveyor_stage_contracts(
                    stage, schema_version, entry_criteria_json, required_artifacts_json,
                    allowed_tools_json, exit_criteria_json, retry_policy_json,
                    escalation_policy_json, parallelism_json, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(stage) DO UPDATE SET
                    schema_version=excluded.schema_version,
                    entry_criteria_json=excluded.entry_criteria_json,
                    required_artifacts_json=excluded.required_artifacts_json,
                    allowed_tools_json=excluded.allowed_tools_json,
                    exit_criteria_json=excluded.exit_criteria_json,
                    retry_policy_json=excluded.retry_policy_json,
                    escalation_policy_json=excluded.escalation_policy_json,
                    parallelism_json=excluded.parallelism_json,
                    updated_at=excluded.updated_at
                """,
                (
                    stage,
                    STAGE_CONTRACT_VERSION,
                    stable_json(contract["entry_criteria"]),
                    stable_json(contract["required_artifacts"]),
                    stable_json(contract["allowed_tools"]),
                    stable_json(contract["exit_criteria"]),
                    stable_json(contract["retry_policy"]),
                    stable_json(contract["escalation_policy"]),
                    stable_json(contract["parallelism"]),
                    now,
                ),
            )


def append_event(conn: sqlite3.Connection, event: StateEvent) -> int:
    occurred_at = event.occurred_at or utc_now()
    payload_json = stable_json(dict(event.payload))
    payload_sha = sha256_text(payload_json)
    with conn:
        row = conn.execute(
            "SELECT current_sequence FROM streams WHERE stream_id = ?",
            (event.stream_id,),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO streams(stream_id, kind, subject_id, status, current_sequence, created_at, updated_at, payload_json) "
                "VALUES(?, ?, ?, ?, 0, ?, ?, ?)",
                (
                    event.stream_id,
                    "conveyor"
                    if event.stream_id == CONVEYOR_STREAM_ID
                    else (
                        "runner"
                        if event.stream_id == RUNNER_STREAM_ID
                        else (
                            "human"
                            if event.stream_id == HUMAN_STREAM_ID
                            else ("ticket_run" if event.stream_id == TICKET_STREAM_ID else "task")
                        )
                    ),
                    event.task_id or event.stream_id,
                    event.status or "ACTIVE",
                    occurred_at,
                    occurred_at,
                    "{}",
                ),
            )
            sequence = 1
            prev_hash = ""
        else:
            sequence = int(row["current_sequence"]) + 1
            last = conn.execute(
                "SELECT event_hash FROM events WHERE stream_id = ? ORDER BY sequence DESC LIMIT 1",
                (event.stream_id,),
            ).fetchone()
            prev_hash = str(last["event_hash"]) if last else ""
        material = stable_json(
            {
                "stream_id": event.stream_id,
                "sequence": sequence,
                "occurred_at": occurred_at,
                "event_type": event.event_type,
                "actor_role": event.actor_role,
                "actor_id": event.actor_id,
                "phase": event.phase,
                "status": event.status,
                "task_id": event.task_id,
                "run_id": event.run_id,
                "causation_id": event.causation_id,
                "correlation_id": event.correlation_id,
                "payload_sha256": payload_sha,
                "prev_hash": prev_hash,
            }
        )
        event_hash = sha256_text(material)
        cursor = conn.execute(
            """
            INSERT INTO events(
                stream_id, sequence, occurred_at, event_type, actor_role, actor_id,
                phase, status, task_id, run_id, causation_id, correlation_id,
                payload_json, payload_sha256, prev_hash, event_hash
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.stream_id,
                sequence,
                occurred_at,
                event.event_type,
                event.actor_role,
                event.actor_id,
                event.phase,
                event.status,
                event.task_id,
                event.run_id,
                event.causation_id,
                event.correlation_id,
                payload_json,
                payload_sha,
                prev_hash,
                event_hash,
            ),
        )
        conn.execute(
            "UPDATE streams SET current_sequence = ?, status = ?, updated_at = ? WHERE stream_id = ?",
            (sequence, event.status or "ACTIVE", occurred_at, event.stream_id),
        )
        return int(cursor.lastrowid)


def replace_projection(
    conn: sqlite3.Connection,
    *,
    name: str,
    payload: Mapping[str, Any],
    event_id: int | None,
) -> None:
    payload_json = stable_json(dict(payload))
    now = utc_now()
    with conn:
        conn.execute(
            "INSERT INTO projections(name, updated_at, payload_json, payload_sha256, event_id) "
            "VALUES(?, ?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET "
            "updated_at=excluded.updated_at, payload_json=excluded.payload_json, "
            "payload_sha256=excluded.payload_sha256, event_id=excluded.event_id",
            (name, now, payload_json, sha256_text(payload_json), event_id),
        )


def load_projection(conn: sqlite3.Connection, name: str) -> dict[str, Any]:
    row = conn.execute("SELECT payload_json FROM projections WHERE name = ?", (name,)).fetchone()
    if row is None:
        return {}
    try:
        data = json.loads(str(row["payload_json"]))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def checkpoint_stream(
    conn: sqlite3.Connection,
    *,
    stream_id: str,
    kind: str,
    state: Mapping[str, Any],
    event_id: int | None,
) -> str:
    row = conn.execute(
        "SELECT current_sequence FROM streams WHERE stream_id = ?",
        (stream_id,),
    ).fetchone()
    sequence = int(row["current_sequence"]) if row else 0
    state_json = stable_json(dict(state))
    checkpoint_id = f"ckpt:{stream_id}:{sequence}"
    with conn:
        conn.execute(
            "INSERT INTO checkpoints(checkpoint_id, stream_id, sequence, kind, created_at, state_json, state_sha256, event_id) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(checkpoint_id) DO UPDATE SET "
            "created_at=excluded.created_at, state_json=excluded.state_json, "
            "state_sha256=excluded.state_sha256, event_id=excluded.event_id",
            (
                checkpoint_id,
                stream_id,
                sequence,
                kind,
                utc_now(),
                state_json,
                sha256_text(state_json),
                event_id,
            ),
        )
    return checkpoint_id


def _json_cell(value: Any, fallback: Any) -> Any:
    try:
        parsed = json.loads(str(value or ""))
    except json.JSONDecodeError:
        return fallback
    return parsed


def stage_contract_payload(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    return {
        "stage": str(row["stage"]),
        "schema_version": int(row["schema_version"]),
        "entry_criteria": _json_cell(row["entry_criteria_json"], []),
        "required_artifacts": _json_cell(row["required_artifacts_json"], []),
        "allowed_tools": _json_cell(row["allowed_tools_json"], []),
        "exit_criteria": _json_cell(row["exit_criteria_json"], []),
        "retry_policy": _json_cell(row["retry_policy_json"], {}),
        "escalation_policy": _json_cell(row["escalation_policy_json"], {}),
        "parallelism": _json_cell(row["parallelism_json"], {}),
        "updated_at": str(row["updated_at"]),
    }


def capability_manifest_payload(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    payload = _json_cell(row["payload_json"], {})
    return payload if isinstance(payload, dict) else {}


def refresh_capability_manifest_conn(
    conn: sqlite3.Connection,
    target: Path,
    *,
    actor_role: str = "runtime",
    append_event_first: bool = False,
) -> dict[str, Any]:
    target = target.expanduser().resolve()
    manifest = discover_repo_capabilities(target)
    current = conn.execute(
        "SELECT digest, version, payload_json FROM capability_manifests WHERE manifest_id = ?",
        (CAPABILITY_MANIFEST_ID,),
    ).fetchone()
    current_digest = str(current["digest"]) if current else ""
    current_version = int(current["version"]) if current else 0
    if current_digest == manifest["digest"]:
        payload = capability_manifest_payload(current)
        return payload if payload else manifest

    version = current_version + 1
    manifest["version"] = version
    event_id = None
    if append_event_first:
        event_id = append_event(
            conn,
            StateEvent(
                stream_id=CONVEYOR_STREAM_ID,
                event_type="capabilities.manifest_discovered",
                actor_role=actor_role,
                phase="discovery",
                status="ACTIVE",
                task_id=CONVEYOR_TASK_ID,
                payload={
                    "manifest_id": CAPABILITY_MANIFEST_ID,
                    "version": version,
                    "digest": manifest["digest"],
                    "primary_language": manifest.get("languages", {}).get("primary"),
                    "command_count": len(manifest.get("commands", [])),
                },
            ),
        )
    with conn:
        conn.execute(
            """
            INSERT INTO capability_manifests(
                manifest_id, repo_root, version, digest, generated_at,
                languages_json, commands_json, ci_json, lockfiles_json, analyzers_json, payload_json
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(manifest_id) DO UPDATE SET
                repo_root=excluded.repo_root,
                version=excluded.version,
                digest=excluded.digest,
                generated_at=excluded.generated_at,
                languages_json=excluded.languages_json,
                commands_json=excluded.commands_json,
                ci_json=excluded.ci_json,
                lockfiles_json=excluded.lockfiles_json,
                analyzers_json=excluded.analyzers_json,
                payload_json=excluded.payload_json
            """,
            (
                CAPABILITY_MANIFEST_ID,
                str(target),
                version,
                str(manifest["digest"]),
                str(manifest["generated_at"]),
                stable_json(manifest.get("languages") or {}),
                stable_json(manifest.get("commands") or []),
                stable_json((manifest.get("files") or {}).get("ci") or []),
                stable_json((manifest.get("files") or {}).get("lockfiles") or []),
                stable_json(manifest.get("analyzers") or []),
                stable_json(manifest),
            ),
        )
        replace_projection(conn, name=CAPABILITY_PROJECTION_NAME, payload=manifest, event_id=event_id)
    return manifest


def latest_capability_manifest(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        "SELECT payload_json FROM capability_manifests WHERE manifest_id = ?",
        (CAPABILITY_MANIFEST_ID,),
    ).fetchone()
    if row is None:
        return {}
    payload = _json_cell(row["payload_json"], {})
    return payload if isinstance(payload, dict) else {}


def build_codebase_graph(target: Path, capability: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return codebase_graph.build_codebase_graph(target, capability=capability)


def _latest_codebase_graph_snapshot_row(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT *
        FROM graph_snapshots
        WHERE graph_namespace = ?
        ORDER BY generated_at DESC, rowid DESC
        LIMIT 1
        """,
        (CODEBASE_GRAPH_NAMESPACE,),
    ).fetchone()


def _insert_codebase_graph_conn(conn: sqlite3.Connection, graph: Mapping[str, Any]) -> None:
    snapshot_id = str(graph["snapshot_id"])
    with conn:
        conn.execute("DELETE FROM graph_snapshots WHERE snapshot_id = ?", (snapshot_id,))
        conn.execute(
            """
            INSERT INTO graph_snapshots(
                snapshot_id, graph_namespace, repo_root, generated_at, head_commit,
                dirty_tracked_file_count, dirty_tracked_files_digest, indexed_file_count,
                directory_node_count, command_node_count, test_node_count, stale_node_count,
                digest, payload_json
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                CODEBASE_GRAPH_NAMESPACE,
                str(graph.get("repo_root") or ""),
                str(graph.get("generated_at") or utc_now()),
                str(graph.get("head_commit") or ""),
                int(graph.get("dirty_tracked_file_count") or 0),
                str(graph.get("dirty_tracked_files_digest") or ""),
                int(graph.get("indexed_file_count") or 0),
                int(graph.get("directory_node_count") or 0),
                int(graph.get("command_node_count") or 0),
                int(graph.get("test_node_count") or 0),
                int(graph.get("stale_node_count") or 0),
                str(graph.get("digest") or ""),
                stable_json(graph.get("payload") if isinstance(graph.get("payload"), Mapping) else {}),
            ),
        )
        for node in graph.get("nodes") or []:
            if not isinstance(node, Mapping):
                continue
            conn.execute(
                """
                INSERT INTO graph_nodes(
                    snapshot_id, node_id, graph_namespace, kind, path, name, digest, is_stale, metadata_json
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    str(node.get("node_id") or ""),
                    CODEBASE_GRAPH_NAMESPACE,
                    str(node.get("kind") or ""),
                    str(node.get("path") or ""),
                    str(node.get("name") or ""),
                    str(node.get("digest") or ""),
                    int(node.get("is_stale") or 0),
                    stable_json(node.get("metadata") if isinstance(node.get("metadata"), Mapping) else {}),
                ),
            )
            for fact in node.get("facts") or []:
                if not isinstance(fact, Mapping):
                    continue
                conn.execute(
                    """
                    INSERT INTO graph_node_facts(
                        snapshot_id, node_id, graph_namespace, fact_key, fact_value, value_type, source, confidence
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_id,
                        str(node.get("node_id") or ""),
                        CODEBASE_GRAPH_NAMESPACE,
                        str(fact.get("fact_key") or ""),
                        str(fact.get("fact_value") or ""),
                        str(fact.get("value_type") or "text"),
                        str(fact.get("source") or "indexer"),
                        float(fact.get("confidence") if fact.get("confidence") is not None else 1.0),
                    ),
                )
        for edge in graph.get("edges") or []:
            if not isinstance(edge, Mapping):
                continue
            conn.execute(
                """
                INSERT INTO graph_edges(
                    snapshot_id, edge_id, graph_namespace, kind, from_node_id, to_node_id, metadata_json
                )
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    str(edge.get("edge_id") or ""),
                    CODEBASE_GRAPH_NAMESPACE,
                    str(edge.get("kind") or ""),
                    str(edge.get("from_node_id") or ""),
                    str(edge.get("to_node_id") or ""),
                    stable_json(edge.get("metadata") if isinstance(edge.get("metadata"), Mapping) else {}),
                ),
            )
            for fact in edge.get("facts") or []:
                if not isinstance(fact, Mapping):
                    continue
                conn.execute(
                    """
                    INSERT INTO graph_edge_facts(
                        snapshot_id, edge_id, graph_namespace, fact_key, fact_value, value_type, source, confidence
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_id,
                        str(edge.get("edge_id") or ""),
                        CODEBASE_GRAPH_NAMESPACE,
                        str(fact.get("fact_key") or ""),
                        str(fact.get("fact_value") or ""),
                        str(fact.get("value_type") or "text"),
                        str(fact.get("source") or "indexer"),
                        float(fact.get("confidence") if fact.get("confidence") is not None else 1.0),
                    ),
                )


def _codebase_graph_payload_inventory_fields(inventory: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "graph_inventory_digest": str(inventory.get("graph_inventory_digest") or ""),
        "indexed_path_count": int(inventory.get("indexed_path_count") or 0),
        "indexed_paths_truncated": bool(inventory.get("indexed_paths_truncated")),
        "indexed_path_sample": list(inventory.get("indexed_path_sample") or [])[:24],
    }


def _merge_codebase_graph_snapshot_payload_conn(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    updates: Mapping[str, Any],
) -> None:
    payload = _json_cell(row["payload_json"], {})
    if not isinstance(payload, dict):
        payload = {}
    merged = {**payload, **dict(updates)}
    if stable_json(merged) == stable_json(payload):
        return
    with conn:
        conn.execute(
            "UPDATE graph_snapshots SET payload_json = ? WHERE snapshot_id = ?",
            (stable_json(merged), str(row["snapshot_id"])),
        )


def refresh_codebase_graph_conn(
    conn: sqlite3.Connection,
    target: Path,
    *,
    capability: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    graph = build_codebase_graph(target, capability=capability)
    latest = _latest_codebase_graph_snapshot_row(conn)
    if latest is not None and str(latest["digest"]) == str(graph["digest"]):
        payload = graph.get("payload") if isinstance(graph.get("payload"), Mapping) else {}
        _merge_codebase_graph_snapshot_payload_conn(conn, latest, payload)
        refresh_codebase_graph_staleness_conn(conn, target, snapshot_id=str(latest["snapshot_id"]))
        return codebase_graph_summary(conn)
    _insert_codebase_graph_conn(conn, graph)
    return codebase_graph_summary(conn)


def refresh_codebase_graph(target: Path) -> dict[str, Any]:
    target = target.expanduser().resolve()
    with closing(connect(database_path_for_target(target))) as conn:
        capability = refresh_capability_manifest_conn(conn, target)
        return refresh_codebase_graph_conn(conn, target, capability=capability)


def refresh_codebase_graph_staleness_conn(
    conn: sqlite3.Connection,
    target: Path,
    *,
    snapshot_id: str | None = None,
) -> int:
    row = _latest_codebase_graph_snapshot_row(conn) if snapshot_id is None else conn.execute(
        "SELECT * FROM graph_snapshots WHERE snapshot_id = ? AND graph_namespace = ?",
        (snapshot_id, CODEBASE_GRAPH_NAMESPACE),
    ).fetchone()
    if row is None:
        return 0
    resolved_snapshot_id = str(row["snapshot_id"])
    file_rows = conn.execute(
        """
        SELECT node_id, path, digest, is_stale
        FROM graph_nodes
        WHERE snapshot_id = ?
          AND graph_namespace = ?
          AND kind IN ('file', 'test_file', 'config_file', 'doc_file', 'lockfile')
          AND path <> ''
        """,
        (resolved_snapshot_id, CODEBASE_GRAPH_NAMESPACE),
    ).fetchall()
    stale_count = 0
    changed = False
    with conn:
        for node in file_rows:
            path = target / str(node["path"])
            current_digest = file_digest(path)
            is_stale = 1 if not current_digest or current_digest != str(node["digest"] or "") else 0
            stale_count += is_stale
            if is_stale != int(node["is_stale"] or 0):
                changed = True
                conn.execute(
                    "UPDATE graph_nodes SET is_stale = ? WHERE snapshot_id = ? AND node_id = ?",
                    (is_stale, resolved_snapshot_id, str(node["node_id"])),
                )
        if changed or stale_count != int(row["stale_node_count"] or 0):
            conn.execute(
                "UPDATE graph_snapshots SET stale_node_count = ? WHERE snapshot_id = ?",
                (stale_count, resolved_snapshot_id),
            )
    return stale_count


def _graph_counts(conn: sqlite3.Connection, snapshot_id: str, column: str, table: str) -> dict[str, int]:
    rows = conn.execute(
        f"SELECT {column} AS kind, COUNT(*) AS count FROM {table} WHERE snapshot_id = ? GROUP BY {column} ORDER BY {column}",
        (snapshot_id,),
    ).fetchall()
    return {str(row["kind"]): int(row["count"]) for row in rows}


def codebase_graph_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    row = _latest_codebase_graph_snapshot_row(conn)
    if row is None:
        return {
            "schema_version": 1,
            "graph_namespace": CODEBASE_GRAPH_NAMESPACE,
            "exists": False,
            "latest_snapshot_id": "",
            "latest_graph_snapshot": {},
            "stale_node_count": 0,
            "indexed_file_count": 0,
            "command_node_count": 0,
            "test_node_count": 0,
            "graph_refresh_mode": "",
            "graph_refresh_reason": "",
            "graph_inventory_digest": "",
            "graph_inventory_changed": False,
            "graph_inventory_added_count": 0,
            "graph_inventory_deleted_count": 0,
            "graph_inventory_structural_count": 0,
            "indexed_path_count": 0,
            "indexed_paths_truncated": False,
            "indexed_path_sample": [],
            "node_counts": {},
            "edge_counts": {},
        }
    snapshot_id = str(row["snapshot_id"])
    payload = _json_cell(row["payload_json"], {})
    if not isinstance(payload, dict):
        payload = {}
    stale_row = conn.execute(
        "SELECT COUNT(*) AS count FROM graph_nodes WHERE snapshot_id = ? AND is_stale = 1",
        (snapshot_id,),
    ).fetchone()
    stale_count = int(stale_row["count"] if stale_row else 0)
    if stale_count != int(row["stale_node_count"] or 0):
        with conn:
            conn.execute(
                "UPDATE graph_snapshots SET stale_node_count = ? WHERE snapshot_id = ?",
                (stale_count, snapshot_id),
            )
    node_counts = _graph_counts(conn, snapshot_id, "kind", "graph_nodes")
    edge_counts = _graph_counts(conn, snapshot_id, "kind", "graph_edges")
    latest = {
        "snapshot_id": snapshot_id,
        "graph_namespace": str(row["graph_namespace"]),
        "generated_at": str(row["generated_at"]),
        "head_commit": str(row["head_commit"] or ""),
        "dirty_tracked_file_count": int(row["dirty_tracked_file_count"] or 0),
        "dirty_tracked_files_digest": str(row["dirty_tracked_files_digest"] or ""),
        "indexed_file_count": int(row["indexed_file_count"] or 0),
        "directory_node_count": int(row["directory_node_count"] or 0),
        "command_node_count": int(row["command_node_count"] or 0),
        "test_node_count": int(row["test_node_count"] or 0),
        "stale_node_count": stale_count,
        "digest": str(row["digest"] or ""),
        "graph_inventory_digest": str(payload.get("graph_inventory_digest") or ""),
        "indexed_path_count": int(payload.get("indexed_path_count") or 0),
        "indexed_paths_truncated": bool(payload.get("indexed_paths_truncated")),
    }
    return {
        "schema_version": 1,
        "graph_namespace": CODEBASE_GRAPH_NAMESPACE,
        "exists": True,
        "latest_snapshot_id": snapshot_id,
        "latest_graph_snapshot": latest,
        "stale_node_count": stale_count,
        "indexed_file_count": int(row["indexed_file_count"] or 0),
        "command_node_count": int(row["command_node_count"] or 0),
        "test_node_count": int(row["test_node_count"] or 0),
        "graph_refresh_mode": str(payload.get("graph_refresh_mode") or ""),
        "graph_refresh_reason": str(payload.get("graph_refresh_reason") or ""),
        "graph_inventory_digest": str(payload.get("graph_inventory_digest") or ""),
        "graph_inventory_changed": bool(payload.get("graph_inventory_changed")),
        "graph_inventory_added_count": int(payload.get("graph_inventory_added_count") or 0),
        "graph_inventory_deleted_count": int(payload.get("graph_inventory_deleted_count") or 0),
        "graph_inventory_structural_count": int(payload.get("graph_inventory_structural_count") or 0),
        "indexed_path_count": int(payload.get("indexed_path_count") or 0),
        "indexed_paths_truncated": bool(payload.get("indexed_paths_truncated")),
        "indexed_path_sample": list(payload.get("indexed_path_sample") or [])[:24],
        "node_counts": node_counts,
        "edge_counts": edge_counts,
    }


def _upsert_graph_node_conn(conn: sqlite3.Connection, snapshot_id: str, node: Mapping[str, Any]) -> None:
    node_id = str(node.get("node_id") or "")
    if not node_id:
        return
    conn.execute(
        """
        INSERT INTO graph_nodes(
            snapshot_id, node_id, graph_namespace, kind, path, name, digest, is_stale, metadata_json
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(snapshot_id, node_id) DO UPDATE SET
            graph_namespace=excluded.graph_namespace,
            kind=excluded.kind,
            path=excluded.path,
            name=excluded.name,
            digest=excluded.digest,
            is_stale=excluded.is_stale,
            metadata_json=excluded.metadata_json
        """,
        (
            snapshot_id,
            node_id,
            CODEBASE_GRAPH_NAMESPACE,
            str(node.get("kind") or ""),
            str(node.get("path") or ""),
            str(node.get("name") or ""),
            str(node.get("digest") or ""),
            int(node.get("is_stale") or 0),
            stable_json(node.get("metadata") if isinstance(node.get("metadata"), Mapping) else {}),
        ),
    )
    conn.execute("DELETE FROM graph_node_facts WHERE snapshot_id = ? AND node_id = ?", (snapshot_id, node_id))
    for fact in node.get("facts") or []:
        if not isinstance(fact, Mapping):
            continue
        conn.execute(
            """
            INSERT INTO graph_node_facts(
                snapshot_id, node_id, graph_namespace, fact_key, fact_value, value_type, source, confidence
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                node_id,
                CODEBASE_GRAPH_NAMESPACE,
                str(fact.get("fact_key") or ""),
                str(fact.get("fact_value") or ""),
                str(fact.get("value_type") or "text"),
                str(fact.get("source") or "indexer"),
                float(fact.get("confidence") if fact.get("confidence") is not None else 1.0),
            ),
        )


def _upsert_graph_edge_conn(conn: sqlite3.Connection, snapshot_id: str, edge: Mapping[str, Any]) -> None:
    edge_id = str(edge.get("edge_id") or "")
    if not edge_id:
        return
    conn.execute(
        """
        INSERT INTO graph_edges(
            snapshot_id, edge_id, graph_namespace, kind, from_node_id, to_node_id, metadata_json
        )
        VALUES(?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(snapshot_id, edge_id) DO UPDATE SET
            graph_namespace=excluded.graph_namespace,
            kind=excluded.kind,
            from_node_id=excluded.from_node_id,
            to_node_id=excluded.to_node_id,
            metadata_json=excluded.metadata_json
        """,
        (
            snapshot_id,
            edge_id,
            CODEBASE_GRAPH_NAMESPACE,
            str(edge.get("kind") or ""),
            str(edge.get("from_node_id") or ""),
            str(edge.get("to_node_id") or ""),
            stable_json(edge.get("metadata") if isinstance(edge.get("metadata"), Mapping) else {}),
        ),
    )
    conn.execute("DELETE FROM graph_edge_facts WHERE snapshot_id = ? AND edge_id = ?", (snapshot_id, edge_id))
    for fact in edge.get("facts") or []:
        if not isinstance(fact, Mapping):
            continue
        conn.execute(
            """
            INSERT INTO graph_edge_facts(
                snapshot_id, edge_id, graph_namespace, fact_key, fact_value, value_type, source, confidence
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                edge_id,
                CODEBASE_GRAPH_NAMESPACE,
                str(fact.get("fact_key") or ""),
                str(fact.get("fact_value") or ""),
                str(fact.get("value_type") or "text"),
                str(fact.get("source") or "indexer"),
                float(fact.get("confidence") if fact.get("confidence") is not None else 1.0),
            ),
        )


def _file_node_map_for_snapshot(conn: sqlite3.Connection, snapshot_id: str) -> dict[str, str]:
    rows = conn.execute(
        """
        SELECT path, node_id
        FROM graph_nodes
        WHERE snapshot_id = ?
          AND graph_namespace = ?
          AND kind IN ('file', 'test_file', 'config_file', 'doc_file', 'lockfile')
          AND path <> ''
        """,
        (snapshot_id, CODEBASE_GRAPH_NAMESPACE),
    ).fetchall()
    return {str(row["path"]): str(row["node_id"]) for row in rows}


def refresh_codebase_graph_changed_file_conn(
    conn: sqlite3.Connection,
    target: Path,
    rel_path: str | Path,
    *,
    capability: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    row = _latest_codebase_graph_snapshot_row(conn)
    if row is None:
        return refresh_codebase_graph_conn(conn, target, capability=capability)
    snapshot_id = str(row["snapshot_id"])
    rel = normalize_path_for_brief(Path(str(rel_path).replace("\\", "/")).as_posix())
    node_row = conn.execute(
        """
        SELECT node_id
        FROM graph_nodes
        WHERE snapshot_id = ?
          AND graph_namespace = ?
          AND path = ?
          AND kind IN ('file', 'test_file', 'config_file', 'doc_file', 'lockfile')
        """,
        (snapshot_id, CODEBASE_GRAPH_NAMESPACE, rel),
    ).fetchone()
    if node_row is None:
        return refresh_codebase_graph_conn(conn, target, capability=capability)

    file_node_by_rel = _file_node_map_for_snapshot(conn, snapshot_id)
    file_node = codebase_graph.file_node_for_path(target, rel)
    if str(file_node.get("node_id") or "") != str(node_row["node_id"]):
        return refresh_codebase_graph_conn(conn, target, capability=capability)
    fragment = codebase_graph.dependency_fragment_for_file(
        target,
        rel,
        file_node_by_rel,
        source_file_node_id=str(node_row["node_id"]),
    )

    edge_rows = conn.execute(
        """
        SELECT edge_id, metadata_json
        FROM graph_edges
        WHERE snapshot_id = ?
          AND graph_namespace = ?
          AND kind IN ('imports', 'references', 'defines_module', 'resolved_to')
        """,
        (snapshot_id, CODEBASE_GRAPH_NAMESPACE),
    ).fetchall()
    delete_edge_ids: list[str] = []
    for edge_row in edge_rows:
        metadata = _json_cell(edge_row["metadata_json"], {})
        if isinstance(metadata, dict) and str(metadata.get("source_path") or "") == rel:
            delete_edge_ids.append(str(edge_row["edge_id"]))

    with conn:
        _upsert_graph_node_conn(conn, snapshot_id, file_node)
        if delete_edge_ids:
            conn.executemany(
                "DELETE FROM graph_edge_facts WHERE snapshot_id = ? AND edge_id = ?",
                [(snapshot_id, edge_id) for edge_id in delete_edge_ids],
            )
            conn.executemany(
                "DELETE FROM graph_edges WHERE snapshot_id = ? AND edge_id = ?",
                [(snapshot_id, edge_id) for edge_id in delete_edge_ids],
            )
        for node in fragment["nodes"]:
            _upsert_graph_node_conn(conn, snapshot_id, node)
        for edge in fragment["edges"]:
            _upsert_graph_edge_conn(conn, snapshot_id, edge)
        stale_count = refresh_codebase_graph_staleness_conn(conn, target, snapshot_id=snapshot_id)
        payload = _json_cell(row["payload_json"], {})
        if not isinstance(payload, dict):
            payload = {}
        payload["partial_reindex"] = {
            "path": rel,
            "updated_at": utc_now(),
            "edge_count": len(fragment["edges"]),
            "deleted_edge_count": len(delete_edge_ids),
        }
        inventory = codebase_graph.build_graph_inventory(target, limit=CODEBASE_GRAPH_SCAN_LIMIT)
        payload.update(_codebase_graph_payload_inventory_fields(inventory))
        payload["command_signature_digest"] = codebase_graph.codebase_command_signature_digest(
            target,
            capability=capability,
        )
        payload["node_counts"] = _graph_counts(conn, snapshot_id, "kind", "graph_nodes")
        payload["edge_counts"] = _graph_counts(conn, snapshot_id, "kind", "graph_edges")
        head_commit, dirty_count, dirty_digest = _current_codebase_graph_git_inputs(target)
        partial_digest = sha256_text(
            stable_json(
                {
                    "snapshot_id": snapshot_id,
                    "previous_digest": str(row["digest"] or ""),
                    "path": rel,
                    "file_digest": str(file_node.get("digest") or ""),
                    "edge_ids": sorted(str(edge.get("edge_id") or "") for edge in fragment["edges"]),
                }
            )
        )
        conn.execute(
            """
            UPDATE graph_snapshots
            SET stale_node_count = ?,
                digest = ?,
                generated_at = ?,
                head_commit = ?,
                dirty_tracked_file_count = ?,
                dirty_tracked_files_digest = ?,
                payload_json = ?
            WHERE snapshot_id = ?
            """,
            (stale_count, partial_digest, utc_now(), head_commit, dirty_count, dirty_digest, stable_json(payload), snapshot_id),
        )
    return codebase_graph_summary(conn)


def refresh_codebase_graph_changed_file(target: Path, rel_path: str | Path) -> dict[str, Any]:
    target = target.expanduser().resolve()
    with closing(connect(database_path_for_target(target))) as conn:
        capability = refresh_capability_manifest_conn(conn, target)
        return refresh_codebase_graph_changed_file_conn(conn, target, rel_path, capability=capability)


@dataclass
class CodebaseGraphRefreshDecision:
    mode: str
    reason: str
    inventory: dict[str, Any] = field(default_factory=dict)
    inventory_changed: bool = False
    added_count: int = 0
    deleted_count: int = 0
    structural_count: int = 0
    changed_paths: list[str] = field(default_factory=list)
    partial_paths: list[str] = field(default_factory=list)


def _current_codebase_graph_git_inputs(target: Path) -> tuple[str, int, str]:
    head_commit = codebase_graph.git_value(target, "rev-parse", "--verify", "HEAD")
    status_porcelain = codebase_graph.git_value(target, "status", "--porcelain=v1", "--untracked-files=no")
    dirty_lines = sorted(line for line in status_porcelain.splitlines() if line.strip())
    dirty_digest = sha256_text("\n".join(dirty_lines)) if dirty_lines else ""
    return head_commit, len(dirty_lines), dirty_digest


def _inventory_record_key(record: Mapping[str, Any]) -> tuple[str, str]:
    return (str(record.get("path_kind") or ""), str(record.get("path") or ""))


def _snapshot_codebase_inventory_records_conn(conn: sqlite3.Connection, snapshot_id: str) -> list[dict[str, str]]:
    rows = conn.execute(
        """
        SELECT kind, path
        FROM graph_nodes
        WHERE snapshot_id = ?
          AND graph_namespace = ?
          AND (
              kind = 'directory'
              OR kind IN ('file', 'test_file', 'config_file', 'doc_file', 'lockfile')
          )
          AND path <> ''
        ORDER BY kind, path
        """,
        (snapshot_id, CODEBASE_GRAPH_NAMESPACE),
    ).fetchall()
    records: list[dict[str, str]] = []
    for row in rows:
        path = str(row["path"] or "")
        kind = str(row["kind"] or "")
        rel = Path(path)
        if kind == "directory":
            records.append(
                {
                    "path": path,
                    "path_kind": "directory",
                    "kind": "directory",
                    "extension": "",
                    "parent": rel.parent.as_posix() if path != "." and rel.parent.as_posix() != "." else "",
                }
            )
        else:
            records.append(
                {
                    "path": path,
                    "path_kind": "file",
                    "kind": kind,
                    "extension": rel.suffix.lower(),
                    "parent": rel.parent.as_posix() if rel.parent.as_posix() != "." else ".",
                }
            )
    return sorted(records, key=lambda item: (item["path_kind"], item["path"], item["kind"]))


def _codebase_graph_inventory_diff(
    current_inventory: Mapping[str, Any],
    snapshot_records: list[dict[str, str]],
    *,
    stored_digest: str = "",
) -> dict[str, Any]:
    current_records = [
        dict(item)
        for item in current_inventory.get("records", [])
        if isinstance(item, Mapping)
    ]
    current_by_key = {_inventory_record_key(item): item for item in current_records}
    snapshot_by_key = {_inventory_record_key(item): item for item in snapshot_records}
    current_keys = set(current_by_key)
    snapshot_keys = set(snapshot_by_key)
    added = sorted(current_keys - snapshot_keys)
    deleted = sorted(snapshot_keys - current_keys)
    changed = sorted(
        key
        for key in current_keys & snapshot_keys
        if stable_json(current_by_key[key]) != stable_json(snapshot_by_key[key])
    )
    current_digest = str(current_inventory.get("graph_inventory_digest") or "")
    snapshot_digest = stored_digest or codebase_graph.graph_inventory_digest(snapshot_records)
    structural_count = len(added) + len(deleted) + len(changed)
    return {
        "graph_inventory_digest": current_digest,
        "snapshot_inventory_digest": snapshot_digest,
        "inventory_changed": current_digest != snapshot_digest or structural_count > 0,
        "added_count": len(added),
        "deleted_count": len(deleted),
        "structural_count": structural_count,
        "added": added,
        "deleted": deleted,
        "changed": changed,
    }


def _codebase_graph_file_changes_conn(conn: sqlite3.Connection, target: Path, snapshot_id: str) -> list[dict[str, str]]:
    rows = conn.execute(
        """
        SELECT path, kind, digest
        FROM graph_nodes
        WHERE snapshot_id = ?
          AND graph_namespace = ?
          AND kind IN ('file', 'test_file', 'config_file', 'doc_file', 'lockfile')
          AND path <> ''
        ORDER BY path
        """,
        (snapshot_id, CODEBASE_GRAPH_NAMESPACE),
    ).fetchall()
    changes: list[dict[str, str]] = []
    for row in rows:
        rel = str(row["path"] or "")
        current_digest = file_digest(target / rel)
        if current_digest and current_digest != str(row["digest"] or ""):
            changes.append(
                {
                    "path": rel,
                    "kind": str(row["kind"] or ""),
                    "extension": Path(rel).suffix.lower(),
                    "current_digest": current_digest,
                    "snapshot_digest": str(row["digest"] or ""),
                }
            )
    return changes


def _codebase_graph_change_requires_full_refresh(change: Mapping[str, Any]) -> bool:
    path = Path(str(change.get("path") or ""))
    kind = str(change.get("kind") or "")
    return kind in {"config_file", "lockfile"} or path.name in {"package.json", ".gitignore"}


def _codebase_graph_change_can_partial_reindex(change: Mapping[str, Any]) -> bool:
    if _codebase_graph_change_requires_full_refresh(change):
        return False
    return str(change.get("extension") or "").lower() in CODEBASE_GRAPH_PARTIAL_REINDEX_EXTENSIONS


def _snapshot_codebase_command_signature_conn(conn: sqlite3.Connection, snapshot_id: str) -> list[dict[str, str]]:
    rows = conn.execute(
        """
        SELECT name, metadata_json
        FROM graph_nodes
        WHERE snapshot_id = ?
          AND graph_namespace = ?
          AND kind = 'command'
        """,
        (snapshot_id, CODEBASE_GRAPH_NAMESPACE),
    ).fetchall()
    signature: list[dict[str, str]] = []
    for row in rows:
        metadata = _json_cell(row["metadata_json"], {})
        if not isinstance(metadata, dict):
            metadata = {}
        signature.append(
            {
                "command": str(row["name"] or ""),
                "kind": str(metadata.get("command_kind") or ""),
                "source": str(metadata.get("source") or ""),
                "origin": str(metadata.get("origin") or ""),
                "script": str(metadata.get("script") or ""),
                "script_digest": str(metadata.get("script_digest") or ""),
            }
        )
    return sorted(signature, key=lambda item: (item["source"], item["command"], item["kind"], item["origin"]))


def _codebase_graph_refresh_decision_conn(
    conn: sqlite3.Connection,
    target: Path,
    *,
    capability: Mapping[str, Any] | None = None,
    latest: sqlite3.Row | None = None,
) -> CodebaseGraphRefreshDecision:
    latest = latest if latest is not None else _latest_codebase_graph_snapshot_row(conn)
    inventory = codebase_graph.build_graph_inventory(target, limit=CODEBASE_GRAPH_SCAN_LIMIT)
    if latest is None:
        return CodebaseGraphRefreshDecision(
            mode="full",
            reason="codebase graph snapshot is missing",
            inventory=dict(inventory),
            inventory_changed=True,
            added_count=int(inventory.get("indexed_path_count") or 0),
            structural_count=int(inventory.get("indexed_path_count") or 0),
        )

    snapshot_id = str(latest["snapshot_id"])
    payload = _json_cell(latest["payload_json"], {})
    if not isinstance(payload, dict):
        payload = {}
    snapshot_records = _snapshot_codebase_inventory_records_conn(conn, snapshot_id)
    diff = _codebase_graph_inventory_diff(
        inventory,
        snapshot_records,
        stored_digest=str(payload.get("graph_inventory_digest") or ""),
    )
    if int(diff["structural_count"]):
        if int(diff["added_count"]) and int(diff["deleted_count"]):
            reason = "indexable paths were added and deleted"
        elif int(diff["added_count"]):
            reason = "new indexable paths were added"
        elif int(diff["deleted_count"]):
            reason = "indexed paths were deleted"
        else:
            reason = "indexed path metadata changed"
        return CodebaseGraphRefreshDecision(
            mode="full",
            reason=reason,
            inventory=dict(inventory),
            inventory_changed=bool(diff["inventory_changed"]),
            added_count=int(diff["added_count"]),
            deleted_count=int(diff["deleted_count"]),
            structural_count=int(diff["structural_count"]),
        )

    current_command_digest = codebase_graph.codebase_command_signature_digest(target, capability=capability)
    snapshot_command_digest = str(payload.get("command_signature_digest") or "")
    if not snapshot_command_digest:
        snapshot_command_digest = sha256_text(stable_json(_snapshot_codebase_command_signature_conn(conn, snapshot_id)))
    if current_command_digest != snapshot_command_digest:
        return CodebaseGraphRefreshDecision(
            mode="full",
            reason="capability command inputs changed",
            inventory=dict(inventory),
            inventory_changed=bool(diff["inventory_changed"]),
            added_count=int(diff["added_count"]),
            deleted_count=int(diff["deleted_count"]),
            structural_count=int(diff["structural_count"]),
        )

    head_commit, dirty_count, dirty_digest = _current_codebase_graph_git_inputs(target)
    if str(latest["head_commit"] or "") != head_commit:
        return CodebaseGraphRefreshDecision(
            mode="full",
            reason="repository HEAD changed",
            inventory=dict(inventory),
            inventory_changed=bool(diff["inventory_changed"]),
        )

    file_changes = _codebase_graph_file_changes_conn(conn, target, snapshot_id)
    changed_paths = [str(item["path"]) for item in file_changes]
    if any(_codebase_graph_change_requires_full_refresh(item) for item in file_changes):
        return CodebaseGraphRefreshDecision(
            mode="full",
            reason="package, config, lockfile, or ignore file changed",
            inventory=dict(inventory),
            inventory_changed=bool(diff["inventory_changed"]),
            changed_paths=changed_paths,
        )
    if file_changes and all(_codebase_graph_change_can_partial_reindex(item) for item in file_changes):
        return CodebaseGraphRefreshDecision(
            mode="partial",
            reason="known source files changed",
            inventory=dict(inventory),
            inventory_changed=bool(diff["inventory_changed"]),
            changed_paths=changed_paths,
            partial_paths=changed_paths,
        )

    if int(latest["dirty_tracked_file_count"] or 0) != dirty_count or str(latest["dirty_tracked_files_digest"] or "") != dirty_digest:
        return CodebaseGraphRefreshDecision(
            mode="full",
            reason="dirty tracked file state changed",
            inventory=dict(inventory),
            inventory_changed=bool(diff["inventory_changed"]),
            changed_paths=changed_paths,
        )

    return CodebaseGraphRefreshDecision(
        mode="staleness",
        reason="no structural graph refresh needed",
        inventory=dict(inventory),
        inventory_changed=bool(diff["inventory_changed"]),
        added_count=int(diff["added_count"]),
        deleted_count=int(diff["deleted_count"]),
        structural_count=int(diff["structural_count"]),
        changed_paths=changed_paths,
    )


def _codebase_graph_refresh_metadata(decision: CodebaseGraphRefreshDecision) -> dict[str, Any]:
    return {
        "graph_refresh_mode": decision.mode,
        "graph_refresh_reason": decision.reason,
        "graph_inventory_digest": str(decision.inventory.get("graph_inventory_digest") or ""),
        "graph_inventory_changed": bool(decision.inventory_changed),
        "graph_inventory_added_count": int(decision.added_count),
        "graph_inventory_deleted_count": int(decision.deleted_count),
        "graph_inventory_structural_count": int(decision.structural_count),
        "indexed_path_count": int(decision.inventory.get("indexed_path_count") or 0),
        "indexed_paths_truncated": bool(decision.inventory.get("indexed_paths_truncated")),
        "indexed_path_sample": list(decision.inventory.get("indexed_path_sample") or [])[:24],
    }


def _with_codebase_graph_refresh_metadata(
    summary: Mapping[str, Any],
    decision: CodebaseGraphRefreshDecision,
) -> dict[str, Any]:
    enriched = dict(summary)
    metadata = _codebase_graph_refresh_metadata(decision)
    enriched.update(metadata)
    latest = enriched.get("latest_graph_snapshot") if isinstance(enriched.get("latest_graph_snapshot"), dict) else {}
    if latest:
        latest = dict(latest)
        latest.update(
            {
                "graph_inventory_digest": metadata["graph_inventory_digest"],
                "indexed_path_count": metadata["indexed_path_count"],
                "indexed_paths_truncated": metadata["indexed_paths_truncated"],
            }
        )
        enriched["latest_graph_snapshot"] = latest
    return enriched


def ensure_codebase_graph_conn(
    conn: sqlite3.Connection,
    target: Path,
    *,
    capability: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    latest = _latest_codebase_graph_snapshot_row(conn)
    effective_capability = capability if capability is not None else latest_capability_manifest(conn)
    if not effective_capability:
        effective_capability = refresh_capability_manifest_conn(conn, target)
    decision = _codebase_graph_refresh_decision_conn(conn, target, capability=effective_capability, latest=latest)
    if latest is None:
        return _with_codebase_graph_refresh_metadata(
            refresh_codebase_graph_conn(conn, target, capability=effective_capability),
            decision,
        )
    if decision.mode == "full":
        return _with_codebase_graph_refresh_metadata(
            refresh_codebase_graph_conn(conn, target, capability=effective_capability),
            decision,
        )
    if decision.mode == "partial":
        summary: dict[str, Any] = {}
        for rel_path in decision.partial_paths:
            summary = refresh_codebase_graph_changed_file_conn(
                conn,
                target,
                rel_path,
                capability=effective_capability,
            )
        return _with_codebase_graph_refresh_metadata(summary or codebase_graph_summary(conn), decision)
    inventory_payload = _codebase_graph_payload_inventory_fields(decision.inventory)
    inventory_payload["command_signature_digest"] = codebase_graph.codebase_command_signature_digest(
        target,
        capability=effective_capability,
    )
    _merge_codebase_graph_snapshot_payload_conn(conn, latest, inventory_payload)
    refresh_codebase_graph_staleness_conn(conn, target, snapshot_id=str(latest["snapshot_id"]))
    return _with_codebase_graph_refresh_metadata(codebase_graph_summary(conn), decision)


def _task_graph_node_id(kind: str, key: str) -> str:
    return f"graph-node:{TASK_GRAPH_NAMESPACE}:{kind}:{sha256_text(str(key))[:24]}"


def _task_graph_edge_id(kind: str, from_node_id: str, to_node_id: str, key: str = "") -> str:
    digest = sha256_text(stable_json({"kind": kind, "from": from_node_id, "to": to_node_id, "key": key}))
    return f"graph-edge:{TASK_GRAPH_NAMESPACE}:{kind}:{digest[:24]}"


def _task_graph_fact(
    key: str,
    value: Any,
    *,
    value_type: str = "text",
    source: str = "task_graph_mirror",
    confidence: float = 1.0,
) -> dict[str, Any]:
    return {
        "fact_key": key,
        "fact_value": stable_json(value) if isinstance(value, (dict, list, tuple)) else str(value),
        "value_type": value_type,
        "source": source,
        "confidence": confidence,
    }


def _task_text_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        for key in ("id", "ticket_id", "work_item_id", "node_id"):
            text = str(value.get(key) or "").strip()
            if text:
                return [text]
        return []
    if isinstance(value, (list, tuple, set)):
        items: list[str] = []
        for item in value:
            items.extend(_task_text_values(item))
        return items
    text = str(value).strip()
    if not text:
        return []
    if "," in text:
        return [part.strip() for part in text.split(",") if part.strip()]
    return [text]


def _task_status_done(status: Any) -> bool:
    return str(status or "").strip().lower() in TASK_DONE_STATUSES


def _task_status_pending(status: Any) -> bool:
    normalized = str(status or "").strip().lower()
    return not normalized or normalized in TASK_PENDING_STATUSES or normalized in TASK_BLOCKED_STATUSES


def _task_graph_node(
    kind: str,
    key: str,
    *,
    name: str = "",
    path: str = "",
    status: str = "",
    metadata: Mapping[str, Any] | None = None,
    facts: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    node_metadata = dict(metadata or {})
    if status:
        node_metadata["status"] = status
    return {
        "node_id": _task_graph_node_id(kind, key),
        "kind": kind,
        "path": path,
        "name": name or key,
        "digest": sha256_text(stable_json({"kind": kind, "key": key, "metadata": node_metadata})),
        "is_stale": 0,
        "metadata": node_metadata,
        "facts": list(facts or []),
    }


def _task_graph_edge(
    kind: str,
    from_node_id: str,
    to_node_id: str,
    *,
    key: str = "",
    metadata: Mapping[str, Any] | None = None,
    facts: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    edge_metadata = dict(metadata or {})
    return {
        "edge_id": _task_graph_edge_id(kind, from_node_id, to_node_id, key),
        "kind": kind,
        "from_node_id": from_node_id,
        "to_node_id": to_node_id,
        "metadata": edge_metadata,
        "facts": list(facts or []),
    }


def _add_task_graph_node(nodes: dict[str, dict[str, Any]], node: Mapping[str, Any]) -> dict[str, Any]:
    node_id = str(node.get("node_id") or "")
    if not node_id:
        return {}
    existing = nodes.get(node_id)
    if existing is None:
        nodes[node_id] = dict(node)
        return nodes[node_id]
    metadata = dict(existing.get("metadata") if isinstance(existing.get("metadata"), Mapping) else {})
    incoming_metadata = node.get("metadata") if isinstance(node.get("metadata"), Mapping) else {}
    metadata.update(incoming_metadata)
    existing["metadata"] = metadata
    existing["digest"] = sha256_text(stable_json({"node_id": node_id, "metadata": metadata}))
    return existing


def _add_task_graph_edge(edges: dict[str, dict[str, Any]], edge: Mapping[str, Any]) -> None:
    edge_id = str(edge.get("edge_id") or "")
    if edge_id:
        edges[edge_id] = dict(edge)


def _ticket_payload_from_row(row: sqlite3.Row) -> dict[str, Any]:
    payload = _json_cell(row["payload_json"], {})
    ticket = dict(payload) if isinstance(payload, dict) else {}
    ticket.update(
        {
            "id": str(row["ticket_id"]),
            "summary": str(row["summary"] or ""),
            "status": str(row["status"] or "pending"),
            "blocker": str(row["blocker"] or ""),
            "position": int(row["position"] or 0),
            "run_id": str(row["run_id"] or ""),
        }
    )
    return ticket


def _task_graph_ticket_nodes(
    conn: sqlite3.Connection,
    nodes: dict[str, dict[str, Any]],
    edges: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    run = conn.execute("SELECT * FROM ticket_runs ORDER BY updated_at DESC LIMIT 1").fetchone()
    if run is None:
        return {}
    run_id = str(run["run_id"] or "ticket-run")
    run_node = _task_graph_node(
        "run",
        f"ticket-run:{run_id}",
        name=run_id,
        status=str(run["status"] or ""),
        metadata={
            "run_id": run_id,
            "source": "ticket_runs",
            "halt_when_complete": bool(run["halt_when_complete"]),
            "notify_on_complete": bool(run["notify_on_complete"]),
            "ticket_file": str(run["ticket_file"] or ""),
            "report_path": str(run["report_path"] or ""),
            "updated_at": str(run["updated_at"] or ""),
        },
        facts=[
            _task_graph_fact("source", "ticket_runs"),
            _task_graph_fact("status", str(run["status"] or "")),
        ],
    )
    run_node = _add_task_graph_node(nodes, run_node)

    rows = conn.execute(
        "SELECT * FROM ticket_items WHERE run_id = ? ORDER BY position ASC, ticket_id ASC",
        (run_id,),
    ).fetchall()
    ticket_nodes: dict[str, dict[str, Any]] = {}
    ticket_payloads: dict[str, dict[str, Any]] = {}
    for row in rows:
        ticket = _ticket_payload_from_row(row)
        ticket_id = str(ticket.get("id") or "").strip()
        if not ticket_id:
            continue
        status = str(ticket.get("status") or "pending").strip().lower()
        summary = _brief_text(ticket.get("summary"), limit=180)
        node = _task_graph_node(
            "ticket",
            ticket_id,
            name=ticket_id,
            status=status,
            metadata={
                "ticket_id": ticket_id,
                "run_id": run_id,
                "position": int(ticket.get("position") or 0),
                "summary": summary,
                "status": status,
                "blocker": _brief_text(ticket.get("blocker"), limit=180),
                "source": "ticket_items",
            },
            facts=[
                _task_graph_fact("source", "ticket_items"),
                _task_graph_fact("ticket_id", ticket_id),
                _task_graph_fact("status", status),
            ],
        )
        node = _add_task_graph_node(nodes, node)
        ticket_nodes[ticket_id] = node
        ticket_payloads[ticket_id] = ticket
        if run_node:
            _add_task_graph_edge(
                edges,
                _task_graph_edge(
                    "spawned_by",
                    str(node["node_id"]),
                    str(run_node["node_id"]),
                    key=f"ticket-run:{run_id}:{ticket_id}",
                    metadata={"source": "ticket_items", "ticket_id": ticket_id, "run_id": run_id},
                    facts=[_task_graph_fact("source", "ticket_items")],
                ),
            )

    for ticket_id, ticket in ticket_payloads.items():
        source_node = ticket_nodes[ticket_id]
        for dependency in _task_text_values(ticket.get("depends_on")):
            target_node = ticket_nodes.get(dependency)
            if target_node is None:
                target_node = _task_graph_node(
                    "ticket",
                    f"unresolved:{dependency}",
                    name=dependency,
                    status="unknown",
                    metadata={
                        "ticket_id": dependency,
                        "status": "unknown",
                        "source": "unresolved_dependency",
                    },
                    facts=[
                        _task_graph_fact("source", "unresolved_dependency", confidence=0.5),
                        _task_graph_fact("ticket_id", dependency, confidence=0.5),
                    ],
                )
                target_node = _add_task_graph_node(nodes, target_node)
                ticket_nodes[dependency] = target_node
            _add_task_graph_edge(
                edges,
                _task_graph_edge(
                    "depends_on",
                    str(source_node["node_id"]),
                    str(target_node["node_id"]),
                    key=f"{ticket_id}:{dependency}",
                    metadata={
                        "source": "ticket_items.depends_on",
                        "ticket_id": ticket_id,
                        "dependency": dependency,
                    },
                    facts=[
                        _task_graph_fact("source", "ticket_items.depends_on"),
                        _task_graph_fact("dependency", dependency),
                    ],
                ),
            )

        for relation_kind, payload_key in (("supersedes", "supersedes"), ("duplicates", "duplicates")):
            for related in _task_text_values(ticket.get(payload_key)):
                related_node = ticket_nodes.get(related)
                if related_node is None:
                    continue
                _add_task_graph_edge(
                    edges,
                    _task_graph_edge(
                        relation_kind,
                        str(source_node["node_id"]),
                        str(related_node["node_id"]),
                        key=f"{ticket_id}:{payload_key}:{related}",
                        metadata={"source": f"ticket_items.{payload_key}", "ticket_id": ticket_id, "target": related},
                        facts=[_task_graph_fact("source", f"ticket_items.{payload_key}")],
                    ),
                )

        blocker_text = str(ticket.get("blocker") or "").strip()
        if blocker_text:
            blocker_key = f"ticket:{ticket_id}:blocker:{sha256_text(blocker_text)[:12]}"
            blocker_node = _task_graph_node(
                "blocker",
                blocker_key,
                name=f"{ticket_id} blocker",
                status="pending" if str(ticket.get("status") or "").lower() == "blocked" else "open",
                metadata={
                    "ticket_id": ticket_id,
                    "summary": _brief_text(blocker_text, limit=180),
                    "source": "ticket_items.blocker",
                },
                facts=[
                    _task_graph_fact("source", "ticket_items.blocker"),
                    _task_graph_fact("ticket_id", ticket_id),
                ],
            )
            blocker_node = _add_task_graph_node(nodes, blocker_node)
            _add_task_graph_edge(
                edges,
                _task_graph_edge(
                    "blocks",
                    str(blocker_node["node_id"]),
                    str(source_node["node_id"]),
                    key=f"ticket-blocker:{ticket_id}",
                    metadata={"source": "ticket_items.blocker", "ticket_id": ticket_id},
                    facts=[_task_graph_fact("source", "ticket_items.blocker")],
                ),
            )
    return ticket_nodes


def _task_graph_conveyor_nodes(
    conn: sqlite3.Connection,
    nodes: dict[str, dict[str, Any]],
    edges: dict[str, dict[str, Any]],
    ticket_nodes: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    work_row = conn.execute(
        "SELECT * FROM conveyor_work_items WHERE work_item_id = ?",
        (CONVEYOR_WORK_ITEM_ID,),
    ).fetchone()
    work_node: dict[str, Any] = {}
    if work_row is not None:
        work_node = _task_graph_node(
            "work_item",
            str(work_row["work_item_id"]),
            name=str(work_row["title"] or work_row["work_item_id"]),
            status=str(work_row["status"] or ""),
            metadata={
                "work_item_id": str(work_row["work_item_id"]),
                "title": str(work_row["title"] or ""),
                "status": str(work_row["status"] or ""),
                "current_stage": str(work_row["current_stage"] or ""),
                "stage_status": str(work_row["stage_status"] or ""),
                "owner_role": str(work_row["owner_role"] or ""),
                "dependency_state": str(work_row["dependency_state"] or ""),
                "validation_status": str(work_row["validation_status"] or ""),
                "risk_tier": str(work_row["risk_tier"] or ""),
                "source": "conveyor_work_items",
            },
            facts=[
                _task_graph_fact("source", "conveyor_work_items"),
                _task_graph_fact("status", str(work_row["status"] or "")),
            ],
        )
        work_node = _add_task_graph_node(nodes, work_node)
        validation_plan_node = _task_graph_node(
            "validation_plan",
            f"work-item:{work_row['work_item_id']}:validation-plan",
            name=f"{work_row['work_item_id']} validation plan",
            status=str(work_row["validation_status"] or "not_recorded"),
            metadata={
                "work_item_id": str(work_row["work_item_id"]),
                "status": str(work_row["validation_status"] or "not_recorded"),
                "source": "conveyor_work_items.validation_status",
            },
            facts=[_task_graph_fact("source", "conveyor_work_items.validation_status")],
        )
        validation_plan_node = _add_task_graph_node(nodes, validation_plan_node)
        _add_task_graph_edge(
            edges,
            _task_graph_edge(
                "validates",
                str(validation_plan_node["node_id"]),
                str(work_node["node_id"]),
                key=f"validation-plan:{work_row['work_item_id']}",
                metadata={"source": "conveyor_work_items.validation_status"},
                facts=[_task_graph_fact("source", "conveyor_work_items.validation_status")],
            ),
        )

    for row in conn.execute(
        """
        SELECT *
        FROM runs
        ORDER BY COALESCE(NULLIF(finished_at, ''), started_at) DESC, run_id ASC
        LIMIT 50
        """
    ).fetchall():
        run_node = _task_graph_node(
            "run",
            f"run:{row['run_id']}",
            name=str(row["run_id"]),
            status=str(row["status"] or ""),
            metadata={
                "run_id": str(row["run_id"]),
                "task_id": str(row["task_id"] or ""),
                "stream_id": str(row["stream_id"] or ""),
                "phase": str(row["phase"] or ""),
                "owner_role": str(row["owner_role"] or ""),
                "status": str(row["status"] or ""),
                "source": "runs",
            },
            facts=[
                _task_graph_fact("source", "runs"),
                _task_graph_fact("status", str(row["status"] or "")),
            ],
        )
        run_node = _add_task_graph_node(nodes, run_node)
        if work_node and str(row["task_id"] or "") == CONVEYOR_TASK_ID:
            _add_task_graph_edge(
                edges,
                _task_graph_edge(
                    "spawned_by",
                    str(run_node["node_id"]),
                    str(work_node["node_id"]),
                    key=f"run:{row['run_id']}:work-item",
                    metadata={"source": "runs", "task_id": str(row["task_id"] or "")},
                    facts=[_task_graph_fact("source", "runs")],
                ),
            )
        owner_role = str(row["owner_role"] or "").strip()
        if owner_role:
            assignment_node = _task_graph_node(
                "worker_assignment",
                f"{row['run_id']}:{owner_role}",
                name=owner_role,
                status=str(row["status"] or ""),
                metadata={
                    "run_id": str(row["run_id"]),
                    "owner_role": owner_role,
                    "status": str(row["status"] or ""),
                    "source": "runs.owner_role",
                },
                facts=[_task_graph_fact("source", "runs.owner_role")],
            )
            assignment_node = _add_task_graph_node(nodes, assignment_node)
            _add_task_graph_edge(
                edges,
                _task_graph_edge(
                    "spawned_by",
                    str(assignment_node["node_id"]),
                    str(run_node["node_id"]),
                    key=f"assignment:{row['run_id']}:{owner_role}",
                    metadata={"source": "runs.owner_role"},
                    facts=[_task_graph_fact("source", "runs.owner_role")],
                ),
            )

    ticket_by_id = {
        str((node.get("metadata") or {}).get("ticket_id") or ""): node
        for node in ticket_nodes.values()
        if isinstance(node.get("metadata"), Mapping)
    }
    for row in conn.execute(
        "SELECT * FROM blockers ORDER BY updated_at DESC, blocker_id ASC LIMIT 50"
    ).fetchall():
        status = str(row["status"] or "")
        blocker_node = _task_graph_node(
            "blocker",
            str(row["blocker_id"]),
            name=str(row["kind"] or row["blocker_id"]),
            status=status,
            metadata={
                "blocker_id": str(row["blocker_id"]),
                "task_id": str(row["task_id"] or ""),
                "kind": str(row["kind"] or ""),
                "status": status,
                "summary": _brief_text(row["summary"], limit=180),
                "source": "blockers",
            },
            facts=[
                _task_graph_fact("source", "blockers"),
                _task_graph_fact("status", status),
            ],
        )
        blocker_node = _add_task_graph_node(nodes, blocker_node)
        task_id = str(row["task_id"] or "")
        target_node = ticket_by_id.get(task_id)
        if target_node is None and work_node and task_id in {CONVEYOR_TASK_ID, CONVEYOR_WORK_ITEM_ID, ""}:
            target_node = work_node
        if target_node:
            _add_task_graph_edge(
                edges,
                _task_graph_edge(
                    "blocks",
                    str(blocker_node["node_id"]),
                    str(target_node["node_id"]),
                    key=f"blocker:{row['blocker_id']}:{target_node['node_id']}",
                    metadata={"source": "blockers", "task_id": task_id},
                    facts=[_task_graph_fact("source", "blockers")],
                ),
            )
        if not _task_status_done(status):
            playbook_node = _task_graph_node(
                "recovery_playbook",
                f"blocker:{row['blocker_id']}:recovery",
                name=f"{row['blocker_id']} recovery",
                status="planned",
                metadata={
                    "blocker_id": str(row["blocker_id"]),
                    "status": "planned",
                    "source": "blockers",
                },
                facts=[_task_graph_fact("source", "blockers")],
            )
            playbook_node = _add_task_graph_node(nodes, playbook_node)
            _add_task_graph_edge(
                edges,
                _task_graph_edge(
                    "repairs",
                    str(playbook_node["node_id"]),
                    str(blocker_node["node_id"]),
                    key=f"recovery:{row['blocker_id']}",
                    metadata={"source": "blockers"},
                    facts=[_task_graph_fact("source", "blockers")],
                ),
            )

    for row in conn.execute(
        "SELECT * FROM escalations ORDER BY updated_at DESC, escalation_id ASC LIMIT 50"
    ).fetchall():
        approval_node = _task_graph_node(
            "approval",
            str(row["escalation_id"]),
            name=str(row["kind"] or row["escalation_id"]),
            status=str(row["status"] or ""),
            metadata={
                "approval_id": str(row["escalation_id"]),
                "work_item_id": str(row["work_item_id"] or ""),
                "kind": str(row["kind"] or ""),
                "status": str(row["status"] or ""),
                "summary": _brief_text(row["question"], limit=180),
                "source": "escalations",
            },
            facts=[
                _task_graph_fact("source", "escalations"),
                _task_graph_fact("status", str(row["status"] or "")),
            ],
        )
        approval_node = _add_task_graph_node(nodes, approval_node)
        if work_node and str(row["work_item_id"] or "") == str((work_node.get("metadata") or {}).get("work_item_id") or ""):
            _add_task_graph_edge(
                edges,
                _task_graph_edge(
                    "blocks",
                    str(approval_node["node_id"]),
                    str(work_node["node_id"]),
                    key=f"approval:{row['escalation_id']}",
                    metadata={"source": "escalations", "work_item_id": str(row["work_item_id"] or "")},
                    facts=[_task_graph_fact("source", "escalations")],
                ),
            )
    return work_node


def build_task_graph_conn(conn: sqlite3.Connection, target: Path) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    ticket_nodes = _task_graph_ticket_nodes(conn, nodes, edges)
    _task_graph_conveyor_nodes(conn, nodes, edges, ticket_nodes)
    node_list = sorted(nodes.values(), key=lambda item: (str(item.get("kind") or ""), str(item.get("name") or "")))
    edge_list = sorted(edges.values(), key=lambda item: (str(item.get("kind") or ""), str(item.get("edge_id") or "")))
    node_counts: dict[str, int] = {}
    for node in node_list:
        kind = str(node.get("kind") or "")
        node_counts[kind] = node_counts.get(kind, 0) + 1
    edge_counts: dict[str, int] = {}
    for edge in edge_list:
        kind = str(edge.get("kind") or "")
        edge_counts[kind] = edge_counts.get(kind, 0) + 1
    digest = sha256_text(
        stable_json(
            {
                "namespace": TASK_GRAPH_NAMESPACE,
                "nodes": [
                    {
                        "node_id": node.get("node_id"),
                        "kind": node.get("kind"),
                        "name": node.get("name"),
                        "metadata": node.get("metadata") if isinstance(node.get("metadata"), Mapping) else {},
                    }
                    for node in node_list
                ],
                "edges": [
                    {
                        "edge_id": edge.get("edge_id"),
                        "kind": edge.get("kind"),
                        "from_node_id": edge.get("from_node_id"),
                        "to_node_id": edge.get("to_node_id"),
                        "metadata": edge.get("metadata") if isinstance(edge.get("metadata"), Mapping) else {},
                    }
                    for edge in edge_list
                ],
            }
        )
    )
    return {
        "schema_version": 1,
        "snapshot_id": f"graph-snapshot:{TASK_GRAPH_NAMESPACE}:{digest[:24]}",
        "graph_namespace": TASK_GRAPH_NAMESPACE,
        "repo_root": str(target),
        "generated_at": utc_now(),
        "digest": digest,
        "nodes": node_list,
        "edges": edge_list,
        "payload": {
            "schema_version": 1,
            "graph_namespace": TASK_GRAPH_NAMESPACE,
            "node_kinds": list(TASK_GRAPH_NODE_KINDS),
            "edge_kinds": list(TASK_GRAPH_EDGE_KINDS),
            "node_counts": node_counts,
            "edge_counts": edge_counts,
        },
    }


def _latest_task_graph_snapshot_row(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT *
        FROM graph_snapshots
        WHERE graph_namespace = ?
        ORDER BY generated_at DESC, rowid DESC
        LIMIT 1
        """,
        (TASK_GRAPH_NAMESPACE,),
    ).fetchone()


def _insert_task_graph_conn(conn: sqlite3.Connection, graph: Mapping[str, Any]) -> None:
    snapshot_id = str(graph["snapshot_id"])
    with conn:
        conn.execute("DELETE FROM graph_snapshots WHERE snapshot_id = ?", (snapshot_id,))
        conn.execute(
            """
            INSERT INTO graph_snapshots(
                snapshot_id, graph_namespace, repo_root, generated_at, head_commit,
                dirty_tracked_file_count, dirty_tracked_files_digest, indexed_file_count,
                directory_node_count, command_node_count, test_node_count, stale_node_count,
                digest, payload_json
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                TASK_GRAPH_NAMESPACE,
                str(graph.get("repo_root") or ""),
                str(graph.get("generated_at") or utc_now()),
                "",
                0,
                "",
                0,
                0,
                0,
                0,
                0,
                str(graph.get("digest") or ""),
                stable_json(graph.get("payload") if isinstance(graph.get("payload"), Mapping) else {}),
            ),
        )
        for node in graph.get("nodes") or []:
            if not isinstance(node, Mapping):
                continue
            node_id = str(node.get("node_id") or "")
            conn.execute(
                """
                INSERT INTO graph_nodes(
                    snapshot_id, node_id, graph_namespace, kind, path, name, digest, is_stale, metadata_json
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    node_id,
                    TASK_GRAPH_NAMESPACE,
                    str(node.get("kind") or ""),
                    str(node.get("path") or ""),
                    str(node.get("name") or ""),
                    str(node.get("digest") or ""),
                    int(node.get("is_stale") or 0),
                    stable_json(node.get("metadata") if isinstance(node.get("metadata"), Mapping) else {}),
                ),
            )
            for fact in node.get("facts") or []:
                if not isinstance(fact, Mapping):
                    continue
                conn.execute(
                    """
                    INSERT INTO graph_node_facts(
                        snapshot_id, node_id, graph_namespace, fact_key, fact_value, value_type, source, confidence
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_id,
                        node_id,
                        TASK_GRAPH_NAMESPACE,
                        str(fact.get("fact_key") or ""),
                        str(fact.get("fact_value") or ""),
                        str(fact.get("value_type") or "text"),
                        str(fact.get("source") or "task_graph_mirror"),
                        float(fact.get("confidence") if fact.get("confidence") is not None else 1.0),
                    ),
                )
        for edge in graph.get("edges") or []:
            if not isinstance(edge, Mapping):
                continue
            edge_id = str(edge.get("edge_id") or "")
            conn.execute(
                """
                INSERT INTO graph_edges(
                    snapshot_id, edge_id, graph_namespace, kind, from_node_id, to_node_id, metadata_json
                )
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    edge_id,
                    TASK_GRAPH_NAMESPACE,
                    str(edge.get("kind") or ""),
                    str(edge.get("from_node_id") or ""),
                    str(edge.get("to_node_id") or ""),
                    stable_json(edge.get("metadata") if isinstance(edge.get("metadata"), Mapping) else {}),
                ),
            )
            for fact in edge.get("facts") or []:
                if not isinstance(fact, Mapping):
                    continue
                conn.execute(
                    """
                    INSERT INTO graph_edge_facts(
                        snapshot_id, edge_id, graph_namespace, fact_key, fact_value, value_type, source, confidence
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_id,
                        edge_id,
                        TASK_GRAPH_NAMESPACE,
                        str(fact.get("fact_key") or ""),
                        str(fact.get("fact_value") or ""),
                        str(fact.get("value_type") or "text"),
                        str(fact.get("source") or "task_graph_mirror"),
                        float(fact.get("confidence") if fact.get("confidence") is not None else 1.0),
                    ),
                )


def refresh_task_graph_conn(conn: sqlite3.Connection, target: Path) -> dict[str, Any]:
    graph = build_task_graph_conn(conn, target)
    latest = _latest_task_graph_snapshot_row(conn)
    if latest is not None and str(latest["digest"]) == str(graph["digest"]):
        return task_graph_summary(conn)
    _insert_task_graph_conn(conn, graph)
    return task_graph_summary(conn)


def _task_graph_node_public_id(node: Mapping[str, Any]) -> str:
    metadata = node.get("metadata") if isinstance(node.get("metadata"), Mapping) else {}
    for key in ("ticket_id", "work_item_id", "run_id", "blocker_id", "approval_id"):
        text = str(metadata.get(key) or "").strip()
        if text:
            return text
    return str(node.get("name") or node.get("node_id") or "")


def _task_graph_node_brief(node: Mapping[str, Any]) -> dict[str, Any]:
    metadata = node.get("metadata") if isinstance(node.get("metadata"), Mapping) else {}
    return {
        "node_id": str(node.get("node_id") or ""),
        "kind": str(node.get("kind") or ""),
        "id": _task_graph_node_public_id(node),
        "name": str(node.get("name") or ""),
        "status": str(metadata.get("status") or ""),
        "summary": _brief_text(metadata.get("summary") or metadata.get("title") or "", limit=140),
    }


def _task_graph_dependency_cycles(nodes: Mapping[str, Mapping[str, Any]], depends_on: Mapping[str, list[str]]) -> list[dict[str, Any]]:
    visiting: list[str] = []
    visited: set[str] = set()
    cycle_keys: set[tuple[str, ...]] = set()
    cycles: list[dict[str, Any]] = []

    def canonical(ids: list[str]) -> tuple[str, ...]:
        if not ids:
            return ()
        rotations = [tuple(ids[index:] + ids[:index]) for index in range(len(ids))]
        return min(rotations)

    def visit(node_id: str) -> None:
        if node_id in visiting:
            index = visiting.index(node_id)
            ids = visiting[index:]
            key = canonical(ids)
            if key and key not in cycle_keys:
                cycle_keys.add(key)
                cycle_ids = list(key)
                cycles.append(
                    {
                        "node_ids": cycle_ids,
                        "labels": [_task_graph_node_public_id(nodes.get(item, {"node_id": item})) for item in cycle_ids],
                        "length": len(cycle_ids),
                    }
                )
            return
        if node_id in visited:
            return
        visiting.append(node_id)
        for dependency_id in depends_on.get(node_id, []):
            visit(dependency_id)
        visiting.pop()
        visited.add(node_id)

    for node_id in sorted(depends_on):
        visit(node_id)
    return cycles[:20]


def task_graph_read_model(conn: sqlite3.Connection, *, snapshot_id: str | None = None) -> dict[str, Any]:
    row = _latest_task_graph_snapshot_row(conn) if snapshot_id is None else conn.execute(
        "SELECT * FROM graph_snapshots WHERE snapshot_id = ? AND graph_namespace = ?",
        (snapshot_id, TASK_GRAPH_NAMESPACE),
    ).fetchone()
    if row is None:
        return {"ready_task_nodes": [], "blocked_task_nodes": [], "dependency_cycles": []}
    resolved_snapshot_id = str(row["snapshot_id"])
    node_rows = conn.execute(
        """
        SELECT node_id, kind, path, name, metadata_json
        FROM graph_nodes
        WHERE snapshot_id = ? AND graph_namespace = ?
        """,
        (resolved_snapshot_id, TASK_GRAPH_NAMESPACE),
    ).fetchall()
    edge_rows = conn.execute(
        """
        SELECT kind, from_node_id, to_node_id, metadata_json
        FROM graph_edges
        WHERE snapshot_id = ? AND graph_namespace = ?
        """,
        (resolved_snapshot_id, TASK_GRAPH_NAMESPACE),
    ).fetchall()
    nodes: dict[str, dict[str, Any]] = {}
    for node_row in node_rows:
        metadata = _json_cell(node_row["metadata_json"], {})
        nodes[str(node_row["node_id"])] = {
            "node_id": str(node_row["node_id"]),
            "kind": str(node_row["kind"] or ""),
            "path": str(node_row["path"] or ""),
            "name": str(node_row["name"] or ""),
            "metadata": metadata if isinstance(metadata, dict) else {},
        }
    depends_on: dict[str, list[str]] = {}
    blocks_target: dict[str, list[str]] = {}
    for edge_row in edge_rows:
        kind = str(edge_row["kind"] or "")
        from_node_id = str(edge_row["from_node_id"] or "")
        to_node_id = str(edge_row["to_node_id"] or "")
        if kind == "depends_on":
            depends_on.setdefault(from_node_id, []).append(to_node_id)
        elif kind == "blocks":
            blocks_target.setdefault(to_node_id, []).append(from_node_id)

    ready: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for node_id in sorted(nodes):
        node = nodes[node_id]
        kind = str(node.get("kind") or "")
        if kind not in {"ticket", "work_item"}:
            continue
        metadata = node.get("metadata") if isinstance(node.get("metadata"), Mapping) else {}
        status = str(metadata.get("status") or "").strip().lower()
        if _task_status_done(status):
            continue
        blocked_reasons: list[dict[str, Any]] = []
        if status in TASK_BLOCKED_STATUSES:
            blocked_reasons.append({"kind": "status", "status": status})
        for dependency_id in depends_on.get(node_id, []):
            dependency = nodes.get(dependency_id, {"node_id": dependency_id, "kind": "unknown", "metadata": {}})
            dependency_metadata = dependency.get("metadata") if isinstance(dependency.get("metadata"), Mapping) else {}
            dependency_status = str(dependency_metadata.get("status") or "").strip().lower()
            if not _task_status_done(dependency_status):
                blocked_reasons.append(
                    {
                        "kind": "dependency",
                        "status": dependency_status or "unknown",
                        "dependency": _task_graph_node_brief(dependency),
                    }
                )
        for blocker_id in blocks_target.get(node_id, []):
            blocker = nodes.get(blocker_id, {"node_id": blocker_id, "kind": "blocker", "metadata": {}})
            blocker_metadata = blocker.get("metadata") if isinstance(blocker.get("metadata"), Mapping) else {}
            blocker_status = str(blocker_metadata.get("status") or "").strip().lower()
            if _task_status_pending(blocker_status) and not _task_status_done(blocker_status):
                blocked_reasons.append(
                    {
                        "kind": str(blocker.get("kind") or "blocker"),
                        "status": blocker_status or "pending",
                        "blocker": _task_graph_node_brief(blocker),
                    }
                )
        brief = _task_graph_node_brief(node)
        if blocked_reasons:
            brief["blocked_reasons"] = blocked_reasons[:5]
            blocked.append(brief)
        else:
            brief["ready_reason"] = "dependencies_resolved"
            ready.append(brief)

    cycles = _task_graph_dependency_cycles(nodes, depends_on)
    return {
        "ready_task_nodes": ready[:20],
        "blocked_task_nodes": blocked[:20],
        "dependency_cycles": cycles,
    }


def task_graph_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    row = _latest_task_graph_snapshot_row(conn)
    if row is None:
        return {
            "schema_version": 1,
            "graph_namespace": TASK_GRAPH_NAMESPACE,
            "exists": False,
            "latest_snapshot_id": "",
            "latest_graph_snapshot": {},
            "node_counts": {},
            "edge_counts": {},
            "ready_task_count": 0,
            "blocked_task_count": 0,
            "dependency_cycle_count": 0,
        }
    snapshot_id = str(row["snapshot_id"])
    node_counts = _graph_counts(conn, snapshot_id, "kind", "graph_nodes")
    edge_counts = _graph_counts(conn, snapshot_id, "kind", "graph_edges")
    read_model = task_graph_read_model(conn, snapshot_id=snapshot_id)
    latest = {
        "snapshot_id": snapshot_id,
        "graph_namespace": str(row["graph_namespace"]),
        "generated_at": str(row["generated_at"] or ""),
        "digest": str(row["digest"] or ""),
        "node_count": sum(node_counts.values()),
        "edge_count": sum(edge_counts.values()),
        "ticket_node_count": int(node_counts.get("ticket", 0)),
        "work_item_node_count": int(node_counts.get("work_item", 0)),
        "ready_task_count": len(read_model["ready_task_nodes"]),
        "blocked_task_count": len(read_model["blocked_task_nodes"]),
        "dependency_cycle_count": len(read_model["dependency_cycles"]),
    }
    return {
        "schema_version": 1,
        "graph_namespace": TASK_GRAPH_NAMESPACE,
        "exists": True,
        "latest_snapshot_id": snapshot_id,
        "latest_graph_snapshot": latest,
        "node_counts": node_counts,
        "edge_counts": edge_counts,
        "ready_task_count": len(read_model["ready_task_nodes"]),
        "blocked_task_count": len(read_model["blocked_task_nodes"]),
        "dependency_cycle_count": len(read_model["dependency_cycles"]),
    }


def _impact_graph_node_id(kind: str, key: str) -> str:
    return f"graph-node:{IMPACT_GRAPH_NAMESPACE}:{kind}:{sha256_text(str(key))[:24]}"


def _impact_graph_edge_id(kind: str, from_node_id: str, to_node_id: str, key: str = "") -> str:
    digest = sha256_text(stable_json({"kind": kind, "from": from_node_id, "to": to_node_id, "key": key}))
    return f"graph-edge:{IMPACT_GRAPH_NAMESPACE}:{kind}:{digest[:24]}"


def _impact_graph_fact(
    key: str,
    value: Any,
    *,
    value_type: str = "text",
    source: str = "impact_inference",
    confidence: float = 1.0,
) -> dict[str, Any]:
    return {
        "fact_key": key,
        "fact_value": stable_json(value) if isinstance(value, (dict, list, tuple)) else str(value),
        "value_type": value_type,
        "source": source,
        "confidence": confidence,
    }


def _impact_graph_edge(
    kind: str,
    from_node_id: str,
    to_node_id: str,
    *,
    confidence: float,
    reason: str,
    source: str,
    key: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_confidence = max(0.0, min(1.0, float(confidence)))
    edge_metadata = dict(metadata or {})
    edge_metadata.update(
        {
            "confidence": round(normalized_confidence, 4),
            "reason": _brief_text(reason, limit=180),
            "source": source,
        }
    )
    return {
        "edge_id": _impact_graph_edge_id(kind, from_node_id, to_node_id, key),
        "kind": kind,
        "from_node_id": from_node_id,
        "to_node_id": to_node_id,
        "metadata": edge_metadata,
        "facts": [
            _impact_graph_fact("source", source, source=source, confidence=normalized_confidence),
            _impact_graph_fact("confidence", f"{normalized_confidence:.4f}", value_type="number", source=source, confidence=normalized_confidence),
            _impact_graph_fact("reason", edge_metadata["reason"], source=source, confidence=normalized_confidence),
        ],
    }


def _impact_copy_graph_node(row: sqlite3.Row, *, source_namespace: str, source_snapshot_id: str) -> dict[str, Any]:
    metadata = _json_cell(row["metadata_json"], {})
    node_metadata = dict(metadata) if isinstance(metadata, dict) else {}
    node_metadata.update(
        {
            "source_graph_namespace": source_namespace,
            "source_snapshot_id": source_snapshot_id,
        }
    )
    return {
        "node_id": str(row["node_id"]),
        "kind": str(row["kind"] or ""),
        "path": str(row["path"] or ""),
        "name": str(row["name"] or ""),
        "digest": str(row["digest"] or ""),
        "is_stale": int(row["is_stale"] or 0),
        "metadata": node_metadata,
        "facts": [
            _impact_graph_fact("source_graph_namespace", source_namespace),
            _impact_graph_fact("source_snapshot_id", source_snapshot_id),
        ],
    }


def _impact_add_node(nodes: dict[str, dict[str, Any]], node: Mapping[str, Any]) -> dict[str, Any]:
    node_id = str(node.get("node_id") or "")
    if not node_id:
        return {}
    existing = nodes.get(node_id)
    if existing is None:
        nodes[node_id] = dict(node)
        return nodes[node_id]
    existing_stale = int(existing.get("is_stale") or 0)
    incoming_stale = int(node.get("is_stale") or 0)
    existing["is_stale"] = 1 if existing_stale or incoming_stale else 0
    metadata = dict(existing.get("metadata") if isinstance(existing.get("metadata"), Mapping) else {})
    incoming_metadata = node.get("metadata") if isinstance(node.get("metadata"), Mapping) else {}
    metadata.update(incoming_metadata)
    existing["metadata"] = metadata
    return existing


def _impact_add_edge(edges: dict[str, dict[str, Any]], edge: Mapping[str, Any]) -> None:
    edge_id = str(edge.get("edge_id") or "")
    if not edge_id:
        return
    current = edges.get(edge_id)
    if current is None:
        edges[edge_id] = dict(edge)
        return
    current_metadata = current.get("metadata") if isinstance(current.get("metadata"), Mapping) else {}
    next_metadata = edge.get("metadata") if isinstance(edge.get("metadata"), Mapping) else {}
    if float(next_metadata.get("confidence") or 0) > float(current_metadata.get("confidence") or 0):
        edges[edge_id] = dict(edge)


def _impact_terms(value: Any) -> set[str]:
    text = str(value or "").lower()
    stopwords = {
        "add",
        "and",
        "are",
        "bug",
        "build",
        "change",
        "code",
        "file",
        "fix",
        "for",
        "from",
        "into",
        "new",
        "node",
        "repo",
        "task",
        "test",
        "the",
        "this",
        "ticket",
        "update",
        "with",
        "work",
    }
    terms = {item for item in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", text) if item not in stopwords}
    expanded: set[str] = set()
    for term in terms:
        expanded.add(term.replace("-", "_"))
        expanded.add(term.replace("_", "-"))
        expanded.add(term)
    return expanded


def _impact_path_mentions(value: Any) -> set[str]:
    text = str(value or "")
    mentions: set[str] = set()
    pattern = r"(?<![A-Za-z0-9_./-])([A-Za-z0-9_.@/-]+(?:/[A-Za-z0-9_.@-]+)+|[A-Za-z0-9_.@/-]+\.[A-Za-z0-9]{1,12})(?![A-Za-z0-9_./-])"
    for raw in re.findall(pattern, text):
        candidate = normalize_path_for_brief(raw.strip("`'\"()[]{}:,;"))
        if candidate and not candidate.startswith("http"):
            mentions.add(candidate)
    return mentions


def _impact_node_text(node: Mapping[str, Any]) -> str:
    metadata = node.get("metadata") if isinstance(node.get("metadata"), Mapping) else {}
    parts = [
        node.get("name"),
        metadata.get("summary"),
        metadata.get("title"),
        metadata.get("ticket_id"),
        metadata.get("work_item_id"),
        metadata.get("blocker"),
    ]
    return " ".join(str(part or "") for part in parts)


def _impact_code_segments(node: Mapping[str, Any]) -> set[str]:
    path = str(node.get("path") or "")
    name = str(node.get("name") or "")
    text = f"{path} {name}".lower()
    segments = {item for item in re.split(r"[^a-z0-9]+", text) if len(item) >= 3}
    for part in Path(path).parts:
        stem = Path(part).stem.lower()
        if len(stem) >= 3:
            segments.add(stem)
    return segments


def _impact_code_category(kind: str) -> str:
    if kind == "test_file":
        return "tests"
    if kind in {"config_file", "lockfile"}:
        return "configs"
    if kind == "doc_file":
        return "docs"
    if kind == "command":
        return "commands"
    if kind == "artifact":
        return "artifacts"
    return "files"


def _impact_context_path_allowed(path_value: Any) -> bool:
    path = str(path_value or "").strip()
    if not path:
        return True
    name = Path(path).name.lower()
    if name in IMPACT_CONTEXT_SECRET_BASENAMES:
        return False
    if name.startswith(".env.") and name != ".env.example":
        return False
    suffixes = {".pem", ".key", ".p12", ".pfx"}
    if Path(path).suffix.lower() in suffixes:
        return False
    lowered = path.lower()
    secret_tokens = ("/secrets/", "/credentials/", "id_rsa", "private_key")
    return not any(token in lowered for token in secret_tokens)


def _impact_candidate(
    nodes: dict[str, dict[str, Any]],
    edges: dict[str, dict[str, Any]],
    task_node: Mapping[str, Any],
    target_node: Mapping[str, Any],
    *,
    edge_kind: str = "likely_touches",
    confidence: float,
    reason: str,
    source: str,
) -> None:
    task = _impact_add_node(nodes, task_node)
    target = _impact_add_node(nodes, target_node)
    if not task or not target:
        return
    confidence = max(0.0, min(1.0, confidence))
    task_public_id = _task_graph_node_public_id(task)
    metadata = {
        "task_id": task_public_id,
        "target_kind": str(target.get("kind") or ""),
        "target_path": str(target.get("path") or ""),
        "target_name": str(target.get("name") or ""),
    }
    _impact_add_edge(
        edges,
        _impact_graph_edge(
            edge_kind,
            str(task["node_id"]),
            str(target["node_id"]),
            confidence=confidence,
            reason=reason,
            source=source,
            key=f"{edge_kind}:{task['node_id']}:{target['node_id']}",
            metadata=metadata,
        ),
    )
    if edge_kind == "likely_touches":
        reverse_metadata = dict(metadata)
        reverse_metadata["task_id"] = task_public_id
        for reverse_kind in ("touched_by", "relevant_context_for"):
            _impact_add_edge(
                edges,
                _impact_graph_edge(
                    reverse_kind,
                    str(target["node_id"]),
                    str(task["node_id"]),
                    confidence=confidence,
                    reason=reason,
                    source=source,
                    key=f"{reverse_kind}:{target['node_id']}:{task['node_id']}",
                    metadata=reverse_metadata,
                ),
            )


def _impact_score_path_mentions(task_text: str, code_node: Mapping[str, Any]) -> tuple[float, str]:
    path = normalize_path_for_brief(str(code_node.get("path") or ""))
    if not path:
        return 0.0, ""
    for mention in sorted(_impact_path_mentions(task_text), key=len, reverse=True):
        if path == mention or path.endswith("/" + mention) or mention.endswith("/" + path):
            return 0.98, f"path mention `{mention}`"
    return 0.0, ""


def _impact_score_keywords(task_terms: set[str], code_node: Mapping[str, Any]) -> tuple[float, str]:
    if not task_terms:
        return 0.0, ""
    segments = _impact_code_segments(code_node)
    matches: list[str] = []
    for term in task_terms:
        if term in segments:
            matches.append(term)
            continue
        if len(term) >= 4 and any(term in segment or segment in term for segment in segments if len(segment) >= 4):
            matches.append(term)
    if not matches:
        return 0.0, ""
    kind = str(code_node.get("kind") or "")
    base = 0.36 + min(0.32, 0.12 * len(set(matches)))
    if kind in {"file", "test_file"}:
        base += 0.08
    elif kind in {"config_file", "doc_file", "lockfile"}:
        base += 0.02
    return min(0.86, base), "keyword match: " + ", ".join(sorted(set(matches))[:4])


def _impact_score_command(task_text: str, task_terms: set[str], code_node: Mapping[str, Any], *, has_test_candidate: bool) -> tuple[float, str]:
    if str(code_node.get("kind") or "") != "command":
        return 0.0, ""
    metadata = code_node.get("metadata") if isinstance(code_node.get("metadata"), Mapping) else {}
    command_text = f"{code_node.get('name') or ''} {metadata.get('command') or ''}".lower()
    command_terms = _impact_terms(command_text)
    matches = sorted(term for term in task_terms if term in command_terms)
    validation_words = {"verify", "validation", "smoke", "test", "lint", "build", "check"}
    if matches:
        return 0.72, "command keyword match: " + ", ".join(matches[:4])
    if has_test_candidate and any(word in command_text for word in ("test", "pytest", "vitest", "jest", "node --test")):
        return 0.6, "validation command for impacted tests"
    if any(word in task_text.lower() for word in validation_words) and any(word in command_text for word in validation_words):
        return 0.58, "validation command relevance"
    return 0.0, ""


def _latest_impact_graph_snapshot_row(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT *
        FROM graph_snapshots
        WHERE graph_namespace = ?
        ORDER BY generated_at DESC, rowid DESC
        LIMIT 1
        """,
        (IMPACT_GRAPH_NAMESPACE,),
    ).fetchone()


def build_impact_graph_conn(conn: sqlite3.Connection, target: Path) -> dict[str, Any]:
    codebase_row = _latest_codebase_graph_snapshot_row(conn)
    task_row = _latest_task_graph_snapshot_row(conn)
    if codebase_row is None or task_row is None:
        digest = sha256_text(stable_json({"namespace": IMPACT_GRAPH_NAMESPACE, "codebase": bool(codebase_row), "task": bool(task_row)}))
        return {
            "schema_version": 1,
            "snapshot_id": f"graph-snapshot:{IMPACT_GRAPH_NAMESPACE}:{digest[:24]}",
            "graph_namespace": IMPACT_GRAPH_NAMESPACE,
            "repo_root": str(target),
            "generated_at": utc_now(),
            "digest": digest,
            "nodes": [],
            "edges": [],
            "payload": {
                "schema_version": 1,
                "graph_namespace": IMPACT_GRAPH_NAMESPACE,
                "edge_kinds": list(IMPACT_GRAPH_EDGE_KINDS),
                "node_counts": {},
                "edge_counts": {},
            },
        }

    codebase_snapshot_id = str(codebase_row["snapshot_id"])
    task_snapshot_id = str(task_row["snapshot_id"])
    code_rows = conn.execute(
        """
        SELECT node_id, kind, path, name, digest, is_stale, metadata_json
        FROM graph_nodes
        WHERE snapshot_id = ? AND graph_namespace = ?
          AND kind IN ('file', 'test_file', 'config_file', 'doc_file', 'lockfile', 'command')
        """,
        (codebase_snapshot_id, CODEBASE_GRAPH_NAMESPACE),
    ).fetchall()
    task_rows = conn.execute(
        """
        SELECT node_id, kind, path, name, digest, is_stale, metadata_json
        FROM graph_nodes
        WHERE snapshot_id = ? AND graph_namespace = ?
          AND kind IN ('ticket', 'work_item', 'blocker', 'approval')
        """,
        (task_snapshot_id, TASK_GRAPH_NAMESPACE),
    ).fetchall()
    code_nodes = [
        _impact_copy_graph_node(row, source_namespace=CODEBASE_GRAPH_NAMESPACE, source_snapshot_id=codebase_snapshot_id)
        for row in code_rows
        if _impact_context_path_allowed(row["path"])
    ]
    task_nodes = [
        _impact_copy_graph_node(row, source_namespace=TASK_GRAPH_NAMESPACE, source_snapshot_id=task_snapshot_id)
        for row in task_rows
    ]
    code_by_id = {str(node["node_id"]): node for node in code_nodes}
    test_edges: dict[str, list[str]] = {}
    for row in conn.execute(
        """
        SELECT from_node_id, to_node_id
        FROM graph_edges
        WHERE snapshot_id = ? AND graph_namespace = ? AND kind = 'likely_tests'
        """,
        (codebase_snapshot_id, CODEBASE_GRAPH_NAMESPACE),
    ).fetchall():
        test_id = str(row["from_node_id"])
        source_id = str(row["to_node_id"])
        if test_id in code_by_id and source_id in code_by_id:
            test_edges.setdefault(source_id, []).append(test_id)

    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    primary_candidate_ids_by_task: dict[str, list[tuple[str, float, str]]] = {}
    for task_node in task_nodes:
        task_kind = str(task_node.get("kind") or "")
        if task_kind not in {"ticket", "work_item"}:
            continue
        task_text = _impact_node_text(task_node)
        task_terms = _impact_terms(task_text)
        primary_candidates: list[tuple[str, float, str]] = []
        for code_node in code_nodes:
            kind = str(code_node.get("kind") or "")
            if kind == "command":
                continue
            path_confidence, path_reason = _impact_score_path_mentions(task_text, code_node)
            keyword_confidence, keyword_reason = _impact_score_keywords(task_terms, code_node)
            confidence = path_confidence
            reason = path_reason
            source = "path_mention" if path_confidence else "keyword_path_match"
            if keyword_confidence > confidence:
                confidence = keyword_confidence
                reason = keyword_reason
            if confidence <= 0:
                continue
            _impact_candidate(
                nodes,
                edges,
                task_node,
                code_node,
                confidence=confidence,
                reason=reason,
                source=source,
            )
            primary_candidates.append((str(code_node["node_id"]), confidence, reason))
        primary_candidate_ids_by_task[str(task_node["node_id"])] = primary_candidates

    for task_node in task_nodes:
        task_id = str(task_node.get("node_id") or "")
        primary_candidates = primary_candidate_ids_by_task.get(task_id, [])
        has_test_candidate = any(str(code_by_id.get(node_id, {}).get("kind") or "") == "test_file" for node_id, _confidence, _reason in primary_candidates)
        for source_node_id, confidence, _reason in primary_candidates:
            for test_node_id in test_edges.get(source_node_id, []):
                test_node = code_by_id[test_node_id]
                _impact_candidate(
                    nodes,
                    edges,
                    task_node,
                    test_node,
                    confidence=max(0.2, confidence - 0.1),
                    reason=f"test proximity for `{code_by_id[source_node_id].get('path') or code_by_id[source_node_id].get('name')}`",
                    source="test_proximity",
                )
                has_test_candidate = True
        task_text = _impact_node_text(task_node)
        task_terms = _impact_terms(task_text)
        for code_node in code_nodes:
            command_confidence, command_reason = _impact_score_command(task_text, task_terms, code_node, has_test_candidate=has_test_candidate)
            if command_confidence <= 0:
                continue
            _impact_candidate(
                nodes,
                edges,
                task_node,
                code_node,
                edge_kind="requires_validation",
                confidence=command_confidence,
                reason=command_reason,
                source="command_relevance",
            )

    artifact_rows = conn.execute(
        "SELECT artifact_id, task_id, run_id, kind, path, digest, created_at, payload_json FROM artifacts ORDER BY created_at DESC LIMIT 50"
    ).fetchall()
    for row in artifact_rows:
        path = str(row["path"] or "")
        if not _impact_context_path_allowed(path):
            continue
        artifact_node = {
            "node_id": _impact_graph_node_id("artifact", str(row["artifact_id"])),
            "kind": "artifact",
            "path": normalize_path_for_brief(path),
            "name": str(row["artifact_id"]),
            "digest": str(row["digest"] or ""),
            "is_stale": 0,
            "metadata": {
                "artifact_id": str(row["artifact_id"]),
                "task_id": str(row["task_id"] or ""),
                "run_id": str(row["run_id"] or ""),
                "kind": str(row["kind"] or ""),
                "created_at": str(row["created_at"] or ""),
                "source_graph_namespace": IMPACT_GRAPH_NAMESPACE,
            },
            "facts": [_impact_graph_fact("source", "artifacts")],
        }
        artifact_terms = _impact_terms(path)
        for task_node in task_nodes:
            task_terms = _impact_terms(_impact_node_text(task_node))
            if artifact_terms and task_terms.intersection(artifact_terms):
                _impact_candidate(
                    nodes,
                    edges,
                    task_node,
                    artifact_node,
                    confidence=0.44,
                    reason="previous artifact path matches task keywords",
                    source="artifact_relevance",
                )

    touched_by_target: dict[str, list[str]] = {}
    active_task_ids = {
        str(node.get("node_id") or "")
        for node in task_nodes
        if str((node.get("metadata") if isinstance(node.get("metadata"), Mapping) else {}).get("status") or "").lower()
        not in TASK_DONE_STATUSES
    }
    for edge in list(edges.values()):
        if str(edge.get("kind") or "") != "likely_touches":
            continue
        from_id = str(edge.get("from_node_id") or "")
        to_id = str(edge.get("to_node_id") or "")
        if from_id in active_task_ids:
            touched_by_target.setdefault(to_id, []).append(from_id)
    task_by_id = {str(node.get("node_id") or ""): node for node in task_nodes}
    for target_id, task_ids in touched_by_target.items():
        unique_task_ids = sorted(set(task_ids))
        if len(unique_task_ids) < 2:
            continue
        target_node = code_by_id.get(target_id) or nodes.get(target_id)
        if not target_node:
            continue
        for index, first_id in enumerate(unique_task_ids):
            for second_id in unique_task_ids[index + 1 :]:
                if first_id not in task_by_id or second_id not in task_by_id:
                    continue
                reason = f"both tasks may touch `{target_node.get('path') or target_node.get('name')}`"
                _impact_candidate(
                    nodes,
                    edges,
                    task_by_id[first_id],
                    task_by_id[second_id],
                    edge_kind="conflicts_with",
                    confidence=0.5,
                    reason=reason,
                    source="shared_likely_touch",
                )
                _impact_candidate(
                    nodes,
                    edges,
                    task_by_id[second_id],
                    task_by_id[first_id],
                    edge_kind="conflicts_with",
                    confidence=0.5,
                    reason=reason,
                    source="shared_likely_touch",
                )

    node_list = sorted(nodes.values(), key=lambda item: (str(item.get("kind") or ""), str(item.get("path") or ""), str(item.get("name") or "")))
    edge_list = sorted(edges.values(), key=lambda item: (str(item.get("kind") or ""), str(item.get("edge_id") or "")))
    node_counts: dict[str, int] = {}
    for node in node_list:
        kind = str(node.get("kind") or "")
        node_counts[kind] = node_counts.get(kind, 0) + 1
    edge_counts: dict[str, int] = {}
    for edge in edge_list:
        kind = str(edge.get("kind") or "")
        edge_counts[kind] = edge_counts.get(kind, 0) + 1
    digest = sha256_text(
        stable_json(
            {
                "namespace": IMPACT_GRAPH_NAMESPACE,
                "codebase_snapshot": codebase_snapshot_id,
                "task_snapshot": task_snapshot_id,
                "nodes": [
                    {
                        "node_id": node.get("node_id"),
                        "kind": node.get("kind"),
                        "path": node.get("path"),
                        "name": node.get("name"),
                        "is_stale": int(node.get("is_stale") or 0),
                        "metadata": node.get("metadata") if isinstance(node.get("metadata"), Mapping) else {},
                    }
                    for node in node_list
                ],
                "edges": [
                    {
                        "edge_id": edge.get("edge_id"),
                        "kind": edge.get("kind"),
                        "from_node_id": edge.get("from_node_id"),
                        "to_node_id": edge.get("to_node_id"),
                        "metadata": edge.get("metadata") if isinstance(edge.get("metadata"), Mapping) else {},
                    }
                    for edge in edge_list
                ],
            }
        )
    )
    return {
        "schema_version": 1,
        "snapshot_id": f"graph-snapshot:{IMPACT_GRAPH_NAMESPACE}:{digest[:24]}",
        "graph_namespace": IMPACT_GRAPH_NAMESPACE,
        "repo_root": str(target),
        "generated_at": utc_now(),
        "digest": digest,
        "nodes": node_list,
        "edges": edge_list,
        "payload": {
            "schema_version": 1,
            "graph_namespace": IMPACT_GRAPH_NAMESPACE,
            "edge_kinds": list(IMPACT_GRAPH_EDGE_KINDS),
            "codebase_snapshot_id": codebase_snapshot_id,
            "task_snapshot_id": task_snapshot_id,
            "node_counts": node_counts,
            "edge_counts": edge_counts,
        },
    }


def _insert_impact_graph_conn(conn: sqlite3.Connection, graph: Mapping[str, Any]) -> None:
    snapshot_id = str(graph["snapshot_id"])
    with conn:
        conn.execute("DELETE FROM graph_snapshots WHERE snapshot_id = ?", (snapshot_id,))
        conn.execute(
            """
            INSERT INTO graph_snapshots(
                snapshot_id, graph_namespace, repo_root, generated_at, head_commit,
                dirty_tracked_file_count, dirty_tracked_files_digest, indexed_file_count,
                directory_node_count, command_node_count, test_node_count, stale_node_count,
                digest, payload_json
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                IMPACT_GRAPH_NAMESPACE,
                str(graph.get("repo_root") or ""),
                str(graph.get("generated_at") or utc_now()),
                "",
                0,
                "",
                0,
                0,
                0,
                0,
                sum(1 for node in graph.get("nodes") or [] if isinstance(node, Mapping) and int(node.get("is_stale") or 0)),
                str(graph.get("digest") or ""),
                stable_json(graph.get("payload") if isinstance(graph.get("payload"), Mapping) else {}),
            ),
        )
        for node in graph.get("nodes") or []:
            if not isinstance(node, Mapping):
                continue
            node_id = str(node.get("node_id") or "")
            conn.execute(
                """
                INSERT INTO graph_nodes(
                    snapshot_id, node_id, graph_namespace, kind, path, name, digest, is_stale, metadata_json
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    node_id,
                    IMPACT_GRAPH_NAMESPACE,
                    str(node.get("kind") or ""),
                    str(node.get("path") or ""),
                    str(node.get("name") or ""),
                    str(node.get("digest") or ""),
                    int(node.get("is_stale") or 0),
                    stable_json(node.get("metadata") if isinstance(node.get("metadata"), Mapping) else {}),
                ),
            )
            for fact in node.get("facts") or []:
                if not isinstance(fact, Mapping):
                    continue
                conn.execute(
                    """
                    INSERT INTO graph_node_facts(
                        snapshot_id, node_id, graph_namespace, fact_key, fact_value, value_type, source, confidence
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_id,
                        node_id,
                        IMPACT_GRAPH_NAMESPACE,
                        str(fact.get("fact_key") or ""),
                        str(fact.get("fact_value") or ""),
                        str(fact.get("value_type") or "text"),
                        str(fact.get("source") or "impact_inference"),
                        float(fact.get("confidence") if fact.get("confidence") is not None else 1.0),
                    ),
                )
        for edge in graph.get("edges") or []:
            if not isinstance(edge, Mapping):
                continue
            edge_id = str(edge.get("edge_id") or "")
            conn.execute(
                """
                INSERT INTO graph_edges(
                    snapshot_id, edge_id, graph_namespace, kind, from_node_id, to_node_id, metadata_json
                )
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    edge_id,
                    IMPACT_GRAPH_NAMESPACE,
                    str(edge.get("kind") or ""),
                    str(edge.get("from_node_id") or ""),
                    str(edge.get("to_node_id") or ""),
                    stable_json(edge.get("metadata") if isinstance(edge.get("metadata"), Mapping) else {}),
                ),
            )
            for fact in edge.get("facts") or []:
                if not isinstance(fact, Mapping):
                    continue
                conn.execute(
                    """
                    INSERT INTO graph_edge_facts(
                        snapshot_id, edge_id, graph_namespace, fact_key, fact_value, value_type, source, confidence
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_id,
                        edge_id,
                        IMPACT_GRAPH_NAMESPACE,
                        str(fact.get("fact_key") or ""),
                        str(fact.get("fact_value") or ""),
                        str(fact.get("value_type") or "text"),
                        str(fact.get("source") or "impact_inference"),
                        float(fact.get("confidence") if fact.get("confidence") is not None else 1.0),
                    ),
                )


def refresh_impact_graph_conn(conn: sqlite3.Connection, target: Path) -> dict[str, Any]:
    graph = build_impact_graph_conn(conn, target)
    latest = _latest_impact_graph_snapshot_row(conn)
    if latest is not None and str(latest["digest"]) == str(graph["digest"]):
        return impact_graph_summary(conn)
    _insert_impact_graph_conn(conn, graph)
    return impact_graph_summary(conn)


def impact_graph_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    row = _latest_impact_graph_snapshot_row(conn)
    if row is None:
        return {
            "schema_version": 1,
            "graph_namespace": IMPACT_GRAPH_NAMESPACE,
            "exists": False,
            "latest_snapshot_id": "",
            "latest_graph_snapshot": {},
            "node_counts": {},
            "edge_counts": {},
            "stale_node_count": 0,
        }
    snapshot_id = str(row["snapshot_id"])
    node_counts = _graph_counts(conn, snapshot_id, "kind", "graph_nodes")
    edge_counts = _graph_counts(conn, snapshot_id, "kind", "graph_edges")
    latest = {
        "snapshot_id": snapshot_id,
        "graph_namespace": str(row["graph_namespace"]),
        "generated_at": str(row["generated_at"] or ""),
        "digest": str(row["digest"] or ""),
        "node_count": sum(node_counts.values()),
        "edge_count": sum(edge_counts.values()),
        "stale_node_count": int(row["stale_node_count"] or 0),
    }
    return {
        "schema_version": 1,
        "graph_namespace": IMPACT_GRAPH_NAMESPACE,
        "exists": True,
        "latest_snapshot_id": snapshot_id,
        "latest_graph_snapshot": latest,
        "node_counts": node_counts,
        "edge_counts": edge_counts,
        "stale_node_count": int(row["stale_node_count"] or 0),
    }


def _context_pack_item_from_node(node: Mapping[str, Any], edge_metadata: Mapping[str, Any]) -> dict[str, Any]:
    kind = str(node.get("kind") or "")
    path = str(node.get("path") or "")
    return {
        "node_id": str(node.get("node_id") or ""),
        "kind": kind,
        "category": _impact_code_category(kind),
        "path": path,
        "name": str(node.get("name") or ""),
        "confidence": round(float(edge_metadata.get("confidence") or 0), 4),
        "reason": _brief_text(edge_metadata.get("reason") or "", limit=180),
        "is_stale": bool(int(node.get("is_stale") or 0)),
        "raw_contents_included": False,
    }


def _context_pack_selected_task(
    nodes: Mapping[str, Mapping[str, Any]],
    *,
    ticket_id: str = "",
    work_item_id: str = "",
    task_node_id: str = "",
) -> dict[str, Any]:
    if task_node_id and task_node_id in nodes:
        return dict(nodes[task_node_id])
    candidates = [node for node in nodes.values() if str(node.get("kind") or "") in {"ticket", "work_item"}]
    if ticket_id:
        for node in candidates:
            metadata = node.get("metadata") if isinstance(node.get("metadata"), Mapping) else {}
            if str(metadata.get("ticket_id") or "") == ticket_id:
                return dict(node)
    if work_item_id:
        for node in candidates:
            metadata = node.get("metadata") if isinstance(node.get("metadata"), Mapping) else {}
            if str(metadata.get("work_item_id") or "") == work_item_id:
                return dict(node)
    not_done = [
        node
        for node in candidates
        if not _task_status_done((node.get("metadata") if isinstance(node.get("metadata"), Mapping) else {}).get("status"))
    ]
    ordered = sorted(
        not_done or candidates,
        key=lambda node: (
            0 if str(node.get("kind") or "") == "ticket" else 1,
            int((node.get("metadata") if isinstance(node.get("metadata"), Mapping) else {}).get("position") or 9999),
            str(node.get("name") or ""),
        ),
    )
    return dict(ordered[0]) if ordered else {}


def _context_pack_policy_note(items: list[dict[str, Any]], skipped_secret_count: int) -> list[str]:
    notes = ["raw source contents are omitted by default"]
    if skipped_secret_count:
        notes.append(f"{skipped_secret_count} secret-like path(s) were excluded")
    if any(item.get("is_stale") for item in items):
        notes.append("one or more graph nodes are stale; refresh or inspect changed files before relying on the pack")
    return notes


def _load_impact_snapshot_nodes_edges(conn: sqlite3.Connection, snapshot_id: str) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    node_rows = conn.execute(
        """
        SELECT node_id, kind, path, name, digest, is_stale, metadata_json
        FROM graph_nodes
        WHERE snapshot_id = ? AND graph_namespace = ?
        """,
        (snapshot_id, IMPACT_GRAPH_NAMESPACE),
    ).fetchall()
    nodes: dict[str, dict[str, Any]] = {}
    for row in node_rows:
        metadata = _json_cell(row["metadata_json"], {})
        nodes[str(row["node_id"])] = {
            "node_id": str(row["node_id"]),
            "kind": str(row["kind"] or ""),
            "path": str(row["path"] or ""),
            "name": str(row["name"] or ""),
            "digest": str(row["digest"] or ""),
            "is_stale": int(row["is_stale"] or 0),
            "metadata": metadata if isinstance(metadata, dict) else {},
        }
    edge_rows = conn.execute(
        """
        SELECT edge_id, kind, from_node_id, to_node_id, metadata_json
        FROM graph_edges
        WHERE snapshot_id = ? AND graph_namespace = ?
        """,
        (snapshot_id, IMPACT_GRAPH_NAMESPACE),
    ).fetchall()
    edges = []
    for row in edge_rows:
        metadata = _json_cell(row["metadata_json"], {})
        edges.append(
            {
                "edge_id": str(row["edge_id"]),
                "kind": str(row["kind"] or ""),
                "from_node_id": str(row["from_node_id"] or ""),
                "to_node_id": str(row["to_node_id"] or ""),
                "metadata": metadata if isinstance(metadata, dict) else {},
            }
        )
    return nodes, edges


def _record_context_pack_read_receipts_conn(
    conn: sqlite3.Connection,
    *,
    snapshot_id: str,
    task_node_id: str,
    items: list[dict[str, Any]],
    actor_role: str = "",
    run_id: str = "",
    reason: str = "",
) -> int:
    if not task_node_id:
        return 0
    now = utc_now()
    records: list[dict[str, Any]] = []
    for item in items:
        if item.get("category") not in {"files", "tests", "configs", "docs"}:
            continue
        node_id = str(item.get("node_id") or "")
        if not node_id:
            continue
        edge = _impact_graph_edge(
            "read_by",
            node_id,
            task_node_id,
            confidence=float(item.get("confidence") or 0),
            reason=reason or str(item.get("reason") or "context pack included node"),
            source="context_pack_read_receipt",
            key=f"read:{node_id}:{task_node_id}:{actor_role}:{run_id}:{now}",
            metadata={
                "actor_role": actor_role,
                "run_id": run_id,
                "read_at": now,
                "context_pack_reason": str(item.get("reason") or ""),
            },
        )
        records.append(edge)
    with conn:
        for edge in records:
            edge_id = str(edge.get("edge_id") or "")
            conn.execute(
                """
                INSERT OR IGNORE INTO graph_edges(
                    snapshot_id, edge_id, graph_namespace, kind, from_node_id, to_node_id, metadata_json
                )
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    edge_id,
                    IMPACT_GRAPH_NAMESPACE,
                    "read_by",
                    str(edge.get("from_node_id") or ""),
                    str(edge.get("to_node_id") or ""),
                    stable_json(edge.get("metadata") if isinstance(edge.get("metadata"), Mapping) else {}),
                ),
            )
            for fact in edge.get("facts") or []:
                if not isinstance(fact, Mapping):
                    continue
                conn.execute(
                    """
                    INSERT OR IGNORE INTO graph_edge_facts(
                        snapshot_id, edge_id, graph_namespace, fact_key, fact_value, value_type, source, confidence
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_id,
                        edge_id,
                        IMPACT_GRAPH_NAMESPACE,
                        str(fact.get("fact_key") or ""),
                        str(fact.get("fact_value") or ""),
                        str(fact.get("value_type") or "text"),
                        str(fact.get("source") or "context_pack_read_receipt"),
                        float(fact.get("confidence") if fact.get("confidence") is not None else 1.0),
                    ),
                )
    return len(records)


def build_context_pack_conn(
    conn: sqlite3.Connection,
    target: Path,
    *,
    ticket_id: str = "",
    work_item_id: str = "",
    task_node_id: str = "",
    query: str = "",
    max_items: int = IMPACT_CONTEXT_PACK_LIMIT,
    actor_role: str = "",
    run_id: str = "",
    reason: str = "",
    record_read_receipt: bool = False,
) -> dict[str, Any]:
    impact_row = _latest_impact_graph_snapshot_row(conn)
    if impact_row is None:
        refresh_impact_graph_conn(conn, target)
        impact_row = _latest_impact_graph_snapshot_row(conn)
    if impact_row is None:
        return {
            "schema_version": 1,
            "graph_namespace": IMPACT_GRAPH_NAMESPACE,
            "items": [],
            "files": [],
            "tests": [],
            "configs": [],
            "docs": [],
            "commands": [],
            "artifacts": [],
            "stale_context_warning": "",
            "policy_notes": ["raw source contents are omitted by default"],
        }
    snapshot_id = str(impact_row["snapshot_id"])
    nodes, edges = _load_impact_snapshot_nodes_edges(conn, snapshot_id)
    selected_task = _context_pack_selected_task(
        nodes,
        ticket_id=str(ticket_id or "").strip(),
        work_item_id=str(work_item_id or "").strip(),
        task_node_id=str(task_node_id or "").strip(),
    )
    selected_task_id = str(selected_task.get("node_id") or "")
    item_by_node: dict[str, dict[str, Any]] = {}
    skipped_secret_count = 0
    if query and not selected_task_id:
        terms = _impact_terms(query)
        mentions = _impact_path_mentions(query)
        for node in nodes.values():
            if str(node.get("kind") or "") not in {"file", "test_file", "config_file", "doc_file", "lockfile", "command", "artifact"}:
                continue
            path = str(node.get("path") or "")
            if not _impact_context_path_allowed(path):
                skipped_secret_count += 1
                continue
            confidence = 0.0
            reason = ""
            if path and any(path == mention or path.endswith("/" + mention) for mention in mentions):
                confidence = 0.96
                reason = "freeform path mention"
            else:
                keyword_confidence, keyword_reason = _impact_score_keywords(terms, node)
                confidence = keyword_confidence
                reason = keyword_reason
            if confidence > 0:
                item_by_node[str(node["node_id"])] = _context_pack_item_from_node(node, {"confidence": confidence, "reason": reason})
    else:
        for edge in edges:
            kind = str(edge.get("kind") or "")
            metadata = edge.get("metadata") if isinstance(edge.get("metadata"), Mapping) else {}
            if kind in {"likely_touches", "requires_validation", "requires_human_approval"}:
                if selected_task_id and str(edge.get("from_node_id") or "") != selected_task_id:
                    continue
                target_id = str(edge.get("to_node_id") or "")
            elif kind == "relevant_context_for":
                if selected_task_id and str(edge.get("to_node_id") or "") != selected_task_id:
                    continue
                target_id = str(edge.get("from_node_id") or "")
            else:
                continue
            node = nodes.get(target_id)
            if not node:
                continue
            path = str(node.get("path") or "")
            if not _impact_context_path_allowed(path):
                skipped_secret_count += 1
                continue
            item = _context_pack_item_from_node(node, metadata)
            if kind == "requires_validation":
                item["category"] = "commands"
            current = item_by_node.get(target_id)
            if current is None or float(item.get("confidence") or 0) > float(current.get("confidence") or 0):
                item_by_node[target_id] = item

    category_priority = {"files": 0, "tests": 1, "configs": 2, "commands": 3, "docs": 4, "artifacts": 5}
    items = sorted(
        item_by_node.values(),
        key=lambda item: (
            -float(item.get("confidence") or 0),
            category_priority.get(str(item.get("category") or ""), 99),
            str(item.get("path") or item.get("name") or ""),
        ),
    )[: max(1, int(max_items or IMPACT_CONTEXT_PACK_LIMIT))]
    read_receipt_count = 0
    if record_read_receipt and selected_task_id:
        read_receipt_count = _record_context_pack_read_receipts_conn(
            conn,
            snapshot_id=snapshot_id,
            task_node_id=selected_task_id,
            items=items,
            actor_role=actor_role,
            run_id=run_id,
            reason=reason,
        )
    by_category: dict[str, list[dict[str, Any]]] = {
        "files": [],
        "tests": [],
        "configs": [],
        "docs": [],
        "commands": [],
        "artifacts": [],
    }
    for item in items:
        category = str(item.get("category") or "files")
        if category in by_category:
            by_category[category].append(item)
    stale_items = [item for item in items if item.get("is_stale")]
    selected_task_brief = _task_graph_node_brief(selected_task) if selected_task else {}
    return {
        "schema_version": 1,
        "graph_namespace": IMPACT_GRAPH_NAMESPACE,
        "impact_snapshot_id": snapshot_id,
        "selected_task": selected_task_brief,
        "query": _brief_text(query, limit=180),
        "bounded": True,
        "max_items": max_items,
        "item_count": len(items),
        "items": items,
        **by_category,
        "stale_context_warning": "Relevant context includes stale file graph nodes." if stale_items else "",
        "policy_notes": _context_pack_policy_note(items, skipped_secret_count),
        "read_receipts_recorded": read_receipt_count,
    }


def impact_graph_read_model(conn: sqlite3.Connection, target: Path) -> dict[str, Any]:
    impact_summary = impact_graph_summary(conn)
    context_pack = build_context_pack_conn(conn, target, max_items=IMPACT_CONTEXT_PACK_LIMIT)
    row = _latest_impact_graph_snapshot_row(conn)
    if row is None:
        return {
            "impact_graph_summary": impact_summary,
            "active_task_code_impacts": [],
            "context_pack_preview": context_pack,
            "top_impacted_nodes": [],
            "stale_context_warning": "",
        }
    snapshot_id = str(row["snapshot_id"])
    nodes, edges = _load_impact_snapshot_nodes_edges(conn, snapshot_id)
    impacted: dict[str, dict[str, Any]] = {}
    active_impacts: list[dict[str, Any]] = []
    for edge in edges:
        kind = str(edge.get("kind") or "")
        if kind not in {"likely_touches", "requires_validation"}:
            continue
        source = nodes.get(str(edge.get("from_node_id") or ""))
        target_node = nodes.get(str(edge.get("to_node_id") or ""))
        if not source or not target_node:
            continue
        metadata = edge.get("metadata") if isinstance(edge.get("metadata"), Mapping) else {}
        item = _context_pack_item_from_node(target_node, metadata)
        task_brief = _task_graph_node_brief(source)
        impact = {
            "task": task_brief,
            "edge_kind": kind,
            "node": item,
            "confidence": item["confidence"],
            "reason": item["reason"],
        }
        active_impacts.append(impact)
        target_id = str(target_node.get("node_id") or "")
        current = impacted.get(target_id)
        if current is None:
            impacted[target_id] = {
                **item,
                "impact_count": 1,
                "max_confidence": item["confidence"],
            }
        else:
            current["impact_count"] = int(current.get("impact_count") or 0) + 1
            current["max_confidence"] = max(float(current.get("max_confidence") or 0), item["confidence"])
    active_impacts = sorted(
        active_impacts,
        key=lambda item: (-float(item.get("confidence") or 0), str(((item.get("node") or {}).get("path") or ""))),
    )[:20]
    top_impacted = sorted(
        impacted.values(),
        key=lambda item: (-int(item.get("impact_count") or 0), -float(item.get("max_confidence") or 0), str(item.get("path") or "")),
    )[:20]
    stale_warning = context_pack.get("stale_context_warning") or (
        "Impact graph includes stale codebase nodes." if any(item.get("is_stale") for item in top_impacted) else ""
    )
    return {
        "impact_graph_summary": impact_summary,
        "active_task_code_impacts": active_impacts,
        "context_pack_preview": context_pack,
        "top_impacted_nodes": top_impacted,
        "stale_context_warning": stale_warning,
    }


def _parse_state_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _lease_id(
    *,
    task_id: str,
    owner_role: str,
    run_id: str,
    scope_kind: str,
    scope_node_id: str,
    acquired_at: str,
) -> str:
    digest = sha256_text(
        stable_json(
            {
                "task_id": task_id,
                "owner_role": owner_role,
                "run_id": run_id,
                "scope_kind": scope_kind,
                "scope_node_id": scope_node_id,
                "acquired_at": acquired_at,
            }
        )
    )
    return f"resource-lease:{digest[:24]}"


def _latest_graph_node_row(
    conn: sqlite3.Connection,
    node_id: str,
    *,
    namespaces: tuple[str, ...] = (IMPACT_GRAPH_NAMESPACE, CODEBASE_GRAPH_NAMESPACE, TASK_GRAPH_NAMESPACE),
) -> sqlite3.Row | None:
    for namespace in namespaces:
        row = conn.execute(
            """
            SELECT node.*
            FROM graph_nodes node
            JOIN graph_snapshots snapshot
              ON snapshot.snapshot_id = node.snapshot_id
            WHERE node.node_id = ?
              AND node.graph_namespace = ?
            ORDER BY snapshot.generated_at DESC, snapshot.rowid DESC
            LIMIT 1
            """,
            (node_id, namespace),
        ).fetchone()
        if row is not None:
            return row
    return None


def _lease_scope_descriptor_conn(conn: sqlite3.Connection, scope_kind: str, scope_node_id: str) -> dict[str, Any]:
    scope_kind = str(scope_kind or "").strip().lower()
    scope_node_id = str(scope_node_id or "").strip()
    if scope_kind == "repo":
        row = conn.execute(
            """
            SELECT node.*
            FROM graph_nodes node
            JOIN graph_snapshots snapshot
              ON snapshot.snapshot_id = node.snapshot_id
            WHERE node.graph_namespace = ?
              AND node.kind = 'repo'
            ORDER BY snapshot.generated_at DESC, snapshot.rowid DESC
            LIMIT 1
            """,
            (CODEBASE_GRAPH_NAMESPACE,),
        ).fetchone()
        if row is not None:
            return {
                "scope_kind": "repo",
                "scope_node_id": str(row["node_id"]),
                "kind": str(row["kind"] or "repo"),
                "path": ".",
                "name": str(row["name"] or "repo"),
                "metadata": _json_cell(row["metadata_json"], {}),
            }
        return {"scope_kind": "repo", "scope_node_id": scope_node_id, "kind": "repo", "path": ".", "name": "repo", "metadata": {}}
    row = _latest_graph_node_row(conn, scope_node_id)
    if row is None:
        return {
            "scope_kind": scope_kind,
            "scope_node_id": scope_node_id,
            "kind": scope_kind,
            "path": "",
            "name": scope_node_id,
            "metadata": {},
        }
    metadata = _json_cell(row["metadata_json"], {})
    return {
        "scope_kind": scope_kind,
        "scope_node_id": scope_node_id,
        "kind": str(row["kind"] or scope_kind),
        "path": normalize_path_for_brief(str(row["path"] or "")),
        "name": str(row["name"] or ""),
        "metadata": metadata if isinstance(metadata, dict) else {},
    }


def _lease_scope_from_row(conn: sqlite3.Connection, row: Mapping[str, Any]) -> dict[str, Any]:
    return _lease_scope_descriptor_conn(conn, str(row.get("scope_kind") or ""), str(row.get("scope_node_id") or ""))


def _path_under(path: str, directory: str) -> bool:
    path = normalize_path_for_brief(path)
    directory = normalize_path_for_brief(directory)
    if directory in {"", "."}:
        return bool(path)
    return path == directory or path.startswith(directory.rstrip("/") + "/")


def _lease_scopes_overlap(first: Mapping[str, Any], second: Mapping[str, Any]) -> tuple[bool, str]:
    first_kind = str(first.get("scope_kind") or "").lower()
    second_kind = str(second.get("scope_kind") or "").lower()
    first_node = str(first.get("scope_node_id") or "")
    second_node = str(second.get("scope_node_id") or "")
    first_path = normalize_path_for_brief(str(first.get("path") or ""))
    second_path = normalize_path_for_brief(str(second.get("path") or ""))
    if first_kind == "repo" or second_kind == "repo":
        return True, "repo lease overlaps all scopes"
    if first_node and first_node == second_node:
        return True, "same graph node"
    if first_kind == "module" and second_kind == "module" and first_node == second_node:
        return True, "same module node"
    if first_kind == "command" or second_kind == "command":
        return (first_kind == second_kind and first_node == second_node), "same command node"
    if first_kind == "file" and second_kind == "file" and first_path and first_path == second_path:
        return True, "same file path"
    if first_kind == "directory" and second_kind == "directory" and first_path and second_path:
        if _path_under(first_path, second_path) or _path_under(second_path, first_path):
            return True, "overlapping directories"
    if first_kind == "directory" and second_kind == "file" and second_path and _path_under(second_path, first_path):
        return True, "file under leased directory"
    if first_kind == "file" and second_kind == "directory" and first_path and _path_under(first_path, second_path):
        return True, "directory contains leased file"
    return False, ""


def _lease_row_to_dict(conn: sqlite3.Connection, row: sqlite3.Row | Mapping[str, Any]) -> dict[str, Any]:
    item = dict(row)
    payload = _json_cell(item.pop("payload_json", "{}"), {})
    item["payload"] = payload if isinstance(payload, dict) else {}
    item["scope"] = _lease_scope_from_row(conn, item)
    return item


def expire_stale_leases_conn(conn: sqlite3.Connection, *, now: str | None = None) -> int:
    now_text = now or utc_now()
    now_dt = _parse_state_datetime(now_text)
    rows = conn.execute(
        "SELECT lease_id, expires_at FROM resource_leases WHERE status = 'active' AND expires_at <> ''"
    ).fetchall()
    expired_ids: list[str] = []
    for row in rows:
        expires_dt = _parse_state_datetime(row["expires_at"])
        if expires_dt is not None and now_dt is not None and expires_dt <= now_dt:
            expired_ids.append(str(row["lease_id"]))
    if expired_ids:
        with conn:
            conn.executemany(
                "UPDATE resource_leases SET status = 'expired', released_at = ? WHERE lease_id = ? AND status = 'active'",
                [(now_text, lease_id) for lease_id in expired_ids],
            )
    return len(expired_ids)


def expire_stale_leases(target: Path, *, now: str | None = None) -> int:
    target = target.expanduser().resolve()
    with closing(connect(database_path_for_target(target))) as conn:
        return expire_stale_leases_conn(conn, now=now)


def active_resource_leases_conn(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT *
        FROM resource_leases
        WHERE status = 'active'
        ORDER BY acquired_at ASC, lease_id ASC
        """
    ).fetchall()
    return [_lease_row_to_dict(conn, row) for row in rows]


def list_conflicting_leases_conn(
    conn: sqlite3.Connection,
    *,
    scope_kind: str,
    scope_node_id: str,
    task_id: str = "",
    owner_role: str = "",
    run_id: str = "",
) -> list[dict[str, Any]]:
    candidate = _lease_scope_descriptor_conn(conn, scope_kind, scope_node_id)
    candidate.update(
        {
            "scope_kind": str(scope_kind or "").strip().lower(),
            "scope_node_id": str(scope_node_id or "").strip(),
            "task_id": str(task_id or ""),
            "owner_role": str(owner_role or ""),
            "run_id": str(run_id or ""),
        }
    )
    conflicts: list[dict[str, Any]] = []
    for lease in active_resource_leases_conn(conn):
        if task_id and str(lease.get("task_id") or "") == str(task_id):
            continue
        overlaps, reason = _lease_scopes_overlap(candidate, lease.get("scope") if isinstance(lease.get("scope"), Mapping) else {})
        if overlaps:
            conflicts.append(
                {
                    "lease": lease,
                    "candidate": {
                        "task_id": str(task_id or ""),
                        "owner_role": str(owner_role or ""),
                        "run_id": str(run_id or ""),
                        "scope_kind": candidate["scope_kind"],
                        "scope_node_id": candidate["scope_node_id"],
                        "scope": {key: candidate.get(key) for key in ("kind", "path", "name")},
                    },
                    "reason": reason,
                }
            )
    return conflicts


def list_conflicting_leases(
    target: Path,
    *,
    scope_kind: str,
    scope_node_id: str,
    task_id: str = "",
    owner_role: str = "",
    run_id: str = "",
) -> list[dict[str, Any]]:
    target = target.expanduser().resolve()
    with closing(connect(database_path_for_target(target))) as conn:
        expire_stale_leases_conn(conn)
        return list_conflicting_leases_conn(
            conn,
            scope_kind=scope_kind,
            scope_node_id=scope_node_id,
            task_id=task_id,
            owner_role=owner_role,
            run_id=run_id,
        )


def acquire_resource_lease_conn(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    owner_role: str,
    run_id: str = "",
    scope_kind: str,
    scope_node_id: str,
    expires_at: str = "",
    payload: Mapping[str, Any] | None = None,
    allow_conflicts: bool = False,
) -> dict[str, Any]:
    scope_kind = str(scope_kind or "").strip().lower()
    if scope_kind not in RESOURCE_LEASE_SCOPE_KINDS:
        raise ValueError(f"unsupported resource lease scope_kind: {scope_kind}")
    task_id = str(task_id or "").strip()
    scope_node_id = str(scope_node_id or "").strip()
    if not scope_node_id:
        raise ValueError("resource lease scope_node_id is required")
    expire_stale_leases_conn(conn)
    conflicts = list_conflicting_leases_conn(
        conn,
        scope_kind=scope_kind,
        scope_node_id=scope_node_id,
        task_id=task_id,
        owner_role=owner_role,
        run_id=run_id,
    )
    if conflicts and not allow_conflicts:
        return {"acquired": False, "lease": {}, "conflicts": conflicts}
    acquired_at = utc_now()
    lease_id = _lease_id(
        task_id=task_id,
        owner_role=str(owner_role or ""),
        run_id=str(run_id or ""),
        scope_kind=scope_kind,
        scope_node_id=scope_node_id,
        acquired_at=acquired_at,
    )
    with conn:
        conn.execute(
            """
            INSERT INTO resource_leases(
                lease_id, task_id, owner_role, run_id, scope_kind, scope_node_id,
                status, acquired_at, expires_at, released_at, payload_json
            )
            VALUES(?, ?, ?, ?, ?, ?, 'active', ?, ?, '', ?)
            """,
            (
                lease_id,
                task_id,
                str(owner_role or ""),
                str(run_id or ""),
                scope_kind,
                scope_node_id,
                acquired_at,
                str(expires_at or ""),
                stable_json(payload if isinstance(payload, Mapping) else {}),
            ),
        )
    row = conn.execute("SELECT * FROM resource_leases WHERE lease_id = ?", (lease_id,)).fetchone()
    lease = _lease_row_to_dict(conn, row) if row is not None else {}
    return {"acquired": True, "lease": lease, "conflicts": conflicts}


def acquire_resource_lease(
    target: Path,
    *,
    task_id: str,
    owner_role: str,
    run_id: str = "",
    scope_kind: str,
    scope_node_id: str,
    expires_at: str = "",
    payload: Mapping[str, Any] | None = None,
    allow_conflicts: bool = False,
) -> dict[str, Any]:
    target = target.expanduser().resolve()
    with closing(connect(database_path_for_target(target))) as conn:
        return acquire_resource_lease_conn(
            conn,
            task_id=task_id,
            owner_role=owner_role,
            run_id=run_id,
            scope_kind=scope_kind,
            scope_node_id=scope_node_id,
            expires_at=expires_at,
            payload=payload,
            allow_conflicts=allow_conflicts,
        )


def release_resource_lease_conn(
    conn: sqlite3.Connection,
    *,
    lease_id: str,
    released_at: str | None = None,
    status: str = "released",
) -> dict[str, Any]:
    status = str(status or "released").strip().lower()
    if status not in {"released", "superseded", "expired"}:
        raise ValueError(f"unsupported release status: {status}")
    released_at = released_at or utc_now()
    with conn:
        conn.execute(
            "UPDATE resource_leases SET status = ?, released_at = ? WHERE lease_id = ? AND status = 'active'",
            (status, released_at, str(lease_id or "")),
        )
    row = conn.execute("SELECT * FROM resource_leases WHERE lease_id = ?", (str(lease_id or ""),)).fetchone()
    return {"released": bool(row and str(row["status"]) == status), "lease": _lease_row_to_dict(conn, row) if row else {}}


def release_resource_lease(target: Path, lease_id: str, *, released_at: str | None = None) -> dict[str, Any]:
    target = target.expanduser().resolve()
    with closing(connect(database_path_for_target(target))) as conn:
        return release_resource_lease_conn(conn, lease_id=lease_id, released_at=released_at)


def current_conflicting_resource_leases_conn(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    leases = active_resource_leases_conn(conn)
    conflicts: list[dict[str, Any]] = []
    for index, first in enumerate(leases):
        first_scope = first.get("scope") if isinstance(first.get("scope"), Mapping) else {}
        for second in leases[index + 1 :]:
            if str(first.get("task_id") or "") and str(first.get("task_id") or "") == str(second.get("task_id") or ""):
                continue
            second_scope = second.get("scope") if isinstance(second.get("scope"), Mapping) else {}
            overlaps, reason = _lease_scopes_overlap(first_scope, second_scope)
            if overlaps:
                conflicts.append({"lease": first, "conflicting_lease": second, "reason": reason})
    return conflicts


def _directory_node_for_path_conn(conn: sqlite3.Connection, directory_path: str) -> dict[str, Any]:
    row = _latest_codebase_graph_snapshot_row(conn)
    if row is None:
        return {}
    graph_snapshot_id = str(row["snapshot_id"])
    normalized = normalize_path_for_brief(directory_path) or "."
    node = conn.execute(
        """
        SELECT node_id, kind, path, name, metadata_json
        FROM graph_nodes
        WHERE snapshot_id = ?
          AND graph_namespace = ?
          AND kind = 'directory'
          AND path = ?
        """,
        (graph_snapshot_id, CODEBASE_GRAPH_NAMESPACE, normalized),
    ).fetchone()
    if node is None:
        return {}
    metadata = _json_cell(node["metadata_json"], {})
    return {
        "node_id": str(node["node_id"]),
        "kind": str(node["kind"] or "directory"),
        "path": str(node["path"] or ""),
        "name": str(node["name"] or ""),
        "metadata": metadata if isinstance(metadata, dict) else {},
    }


def _repo_node_id_conn(conn: sqlite3.Connection) -> str:
    row = _latest_codebase_graph_snapshot_row(conn)
    if row is None:
        return ""
    node = conn.execute(
        """
        SELECT node_id
        FROM graph_nodes
        WHERE snapshot_id = ?
          AND graph_namespace = ?
          AND kind = 'repo'
        LIMIT 1
        """,
        (str(row["snapshot_id"]), CODEBASE_GRAPH_NAMESPACE),
    ).fetchone()
    return str(node["node_id"]) if node else ""


def lease_suggestions_for_next_action_conn(
    conn: sqlite3.Connection,
    target: Path,
    *,
    ticket_id: str = "",
    work_item_id: str = "",
    task_node_id: str = "",
    query: str = "",
    max_suggestions: int = 8,
) -> list[dict[str, Any]]:
    context_pack = build_context_pack_conn(
        conn,
        target,
        ticket_id=ticket_id,
        work_item_id=work_item_id,
        task_node_id=task_node_id,
        query=query,
        max_items=IMPACT_CONTEXT_PACK_LIMIT,
    )
    selected_task = context_pack.get("selected_task") if isinstance(context_pack.get("selected_task"), dict) else {}
    task_id = str(selected_task.get("node_id") or selected_task.get("id") or "")
    items = context_pack.get("items") if isinstance(context_pack.get("items"), list) else []
    file_like = [
        item
        for item in items
        if isinstance(item, dict)
        and str(item.get("category") or "") in {"files", "tests", "configs", "docs"}
        and str(item.get("node_id") or "")
        and str(item.get("path") or "")
    ]
    suggestions: list[dict[str, Any]] = []
    by_directory: dict[str, list[dict[str, Any]]] = {}
    for item in file_like:
        parent = Path(str(item.get("path") or "")).parent.as_posix()
        by_directory.setdefault(parent if parent != "." else ".", []).append(item)
    for directory, group in sorted(by_directory.items(), key=lambda pair: (-len(pair[1]), pair[0])):
        if len(group) < 3:
            continue
        directory_node = _directory_node_for_path_conn(conn, directory)
        if not directory_node:
            continue
        confidence = max(float(item.get("confidence") or 0) for item in group)
        suggestion = {
            "scope_kind": "directory",
            "scope_node_id": directory_node["node_id"],
            "path": directory_node.get("path") or directory,
            "task_id": task_id,
            "recommended": True,
            "caution": False,
            "confidence": round(confidence, 4),
            "reason": f"{len(group)} relevant context files under `{directory}`",
        }
        suggestion["conflicts"] = list_conflicting_leases_conn(
            conn,
            scope_kind="directory",
            scope_node_id=str(suggestion["scope_node_id"]),
            task_id=task_id,
        )
        suggestions.append(suggestion)

    covered_dirs = {
        str(suggestion.get("path") or "")
        for suggestion in suggestions
        if suggestion.get("scope_kind") == "directory" and suggestion.get("recommended")
    }
    for item in file_like:
        path = str(item.get("path") or "")
        if any(_path_under(path, directory) for directory in covered_dirs):
            continue
        suggestion = {
            "scope_kind": "file",
            "scope_node_id": str(item.get("node_id") or ""),
            "path": path,
            "task_id": task_id,
            "recommended": True,
            "caution": False,
            "confidence": round(float(item.get("confidence") or 0), 4),
            "reason": _brief_text(item.get("reason") or "likely touched by next task", limit=180),
        }
        suggestion["conflicts"] = list_conflicting_leases_conn(
            conn,
            scope_kind="file",
            scope_node_id=str(suggestion["scope_node_id"]),
            task_id=task_id,
        )
        suggestions.append(suggestion)

    for item in items:
        if not isinstance(item, dict) or str(item.get("category") or "") != "commands":
            continue
        suggestion = {
            "scope_kind": "command",
            "scope_node_id": str(item.get("node_id") or ""),
            "path": str(item.get("path") or ""),
            "name": str(item.get("name") or ""),
            "task_id": task_id,
            "recommended": True,
            "caution": False,
            "confidence": round(float(item.get("confidence") or 0), 4),
            "reason": _brief_text(item.get("reason") or "validation command relevant to next task", limit=180),
        }
        suggestion["conflicts"] = list_conflicting_leases_conn(
            conn,
            scope_kind="command",
            scope_node_id=str(suggestion["scope_node_id"]),
            task_id=task_id,
        )
        suggestions.append(suggestion)

    if not suggestions:
        repo_node_id = _repo_node_id_conn(conn)
        suggestions.append(
            {
                "scope_kind": "repo",
                "scope_node_id": repo_node_id,
                "task_id": task_id,
                "recommended": False,
                "caution": True,
                "confidence": 0.0,
                "reason": "No confident impact surface found; review manually before considering a broad repo lease.",
                "conflicts": [],
            }
        )
    suggestions = sorted(
        suggestions,
        key=lambda item: (
            0 if item.get("recommended") else 1,
            0 if item.get("scope_kind") == "directory" else 1,
            -float(item.get("confidence") or 0),
            str(item.get("path") or item.get("name") or ""),
        ),
    )
    return suggestions[: max(1, int(max_suggestions or 8))]


def _scheduler_candidate_id(decision_id: str, index: int, candidate: Mapping[str, Any]) -> str:
    digest = sha256_text(
        stable_json(
            {
                "decision_id": decision_id,
                "index": index,
                "source": candidate.get("source"),
                "role": candidate.get("role"),
                "task_id": candidate.get("task_id"),
                "public_task_id": candidate.get("public_task_id"),
                "action_kind": candidate.get("action_kind"),
                "state": candidate.get("state"),
                "skipped_reason": candidate.get("skipped_reason"),
            }
        )
    )
    return f"scheduler-candidate:{digest[:24]}"


def _scheduler_candidate_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    payload = _json_cell(row["payload_json"], {})
    item = dict(payload) if isinstance(payload, dict) else {}
    item.update(
        {
            "candidate_id": str(row["candidate_id"]),
            "decision_id": str(row["decision_id"]),
            "generated_at": str(row["generated_at"]),
            "role": str(row["role"] or item.get("role") or ""),
            "task_id": str(row["task_id"] or item.get("task_id") or ""),
            "action_kind": str(row["action_kind"] or item.get("action_kind") or ""),
            "score": float(row["score"] or 0),
            "state": str(row["state"] or item.get("state") or ""),
            "skipped_reason": str(row["skipped_reason"] or item.get("skipped_reason") or ""),
            "stop": bool(row["stop"]),
        }
    )
    return item


def write_scheduler_decision_conn(
    conn: sqlite3.Connection,
    *,
    candidates: list[Mapping[str, Any]],
    selected_candidate: Mapping[str, Any] | None = None,
    fallback_used: bool = False,
    graph_signals_used: Mapping[str, Any] | None = None,
    lease_conflicts_considered: list[Mapping[str, Any]] | None = None,
    legacy_result: Mapping[str, Any] | None = None,
    decision_id: str = "",
    generated_at: str = "",
) -> dict[str, Any]:
    generated_at = generated_at or utc_now()
    decision_id = decision_id or f"scheduler-decision:{sha256_text(generated_at + stable_json(candidates))[:24]}"
    selected_task_id = str((selected_candidate or {}).get("task_id") or "")
    graph_signals = dict(graph_signals_used or {})
    lease_conflicts = [dict(item) for item in (lease_conflicts_considered or []) if isinstance(item, Mapping)]
    legacy_payload = dict(legacy_result or {})
    rows: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        item = dict(candidate)
        state = str(item.get("state") or "")
        if not state:
            state = "selected" if selected_task_id and str(item.get("task_id") or "") == selected_task_id else "ready"
        item["state"] = state
        item["selected"] = state == "selected"
        item.setdefault("scheduler_fallback_used", fallback_used)
        item.setdefault("fallback_used", fallback_used)
        item.setdefault("decision_id", decision_id)
        item.setdefault("generated_at", generated_at)
        item.setdefault("graph_signals_used", graph_signals)
        item.setdefault("lease_conflicts_considered", lease_conflicts)
        item.setdefault("legacy_result", legacy_payload)
        item["candidate_id"] = str(item.get("candidate_id") or _scheduler_candidate_id(decision_id, index, item))
        rows.append(item)
    with conn:
        for item in rows:
            conn.execute(
                """
                INSERT INTO scheduler_candidates(
                    candidate_id, decision_id, generated_at, role, task_id, action_kind,
                    score, state, skipped_reason, stop, payload_json
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(candidate_id) DO UPDATE SET
                    decision_id=excluded.decision_id,
                    generated_at=excluded.generated_at,
                    role=excluded.role,
                    task_id=excluded.task_id,
                    action_kind=excluded.action_kind,
                    score=excluded.score,
                    state=excluded.state,
                    skipped_reason=excluded.skipped_reason,
                    stop=excluded.stop,
                    payload_json=excluded.payload_json
                """,
                (
                    str(item["candidate_id"]),
                    decision_id,
                    generated_at,
                    str(item.get("role") or ""),
                    str(item.get("task_id") or ""),
                    str(item.get("action_kind") or ""),
                    float(item.get("score") or 0),
                    str(item.get("state") or "ready"),
                    str(item.get("skipped_reason") or ""),
                    1 if bool(item.get("stop")) else 0,
                    stable_json(item),
                ),
            )
    return latest_scheduler_decision_conn(conn, decision_id=decision_id)


def latest_scheduler_decision_conn(conn: sqlite3.Connection, *, decision_id: str = "") -> dict[str, Any]:
    if not decision_id:
        row = conn.execute(
            """
            SELECT decision_id
            FROM scheduler_candidates
            ORDER BY generated_at DESC, rowid DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return {
                "decision_id": "",
                "generated_at": "",
                "scheduling_candidates": [],
                "selected_candidate": {},
                "selected_scheduler_candidate": {},
                "skipped_candidates": [],
                "skipped_scheduler_candidates": [],
                "scheduler_fallback_used": False,
                "fallback_used": False,
                "graph_signals_used": {},
                "lease_conflicts_considered": [],
                "legacy_result": {},
            }
        decision_id = str(row["decision_id"])
    rows = conn.execute(
        """
        SELECT *
        FROM scheduler_candidates
        WHERE decision_id = ?
        ORDER BY
            CASE state WHEN 'selected' THEN 0 WHEN 'ready' THEN 1 WHEN 'skipped' THEN 2 ELSE 3 END,
            score DESC,
            candidate_id ASC
        """,
        (decision_id,),
    ).fetchall()
    candidates = [_scheduler_candidate_row_to_dict(row) for row in rows]
    selected = next((item for item in candidates if str(item.get("state") or "") == "selected"), {})
    skipped = [item for item in candidates if str(item.get("state") or "") == "skipped"]
    fallback_used = any(bool(item.get("scheduler_fallback_used")) for item in candidates)
    generated_at = str(candidates[0].get("generated_at") or "") if candidates else ""
    graph_signals = next(
        (item.get("graph_signals_used") for item in candidates if isinstance(item.get("graph_signals_used"), dict)),
        {},
    )
    lease_conflicts = next(
        (
            item.get("lease_conflicts_considered")
            for item in candidates
            if isinstance(item.get("lease_conflicts_considered"), list)
        ),
        [],
    )
    legacy_payload = next(
        (item.get("legacy_result") for item in candidates if isinstance(item.get("legacy_result"), dict)),
        {},
    )
    return {
        "decision_id": decision_id,
        "generated_at": generated_at,
        "scheduling_candidates": candidates,
        "selected_candidate": selected,
        "selected_scheduler_candidate": selected,
        "skipped_candidates": skipped,
        "skipped_scheduler_candidates": skipped,
        "scheduler_fallback_used": fallback_used,
        "fallback_used": fallback_used,
        "graph_signals_used": graph_signals if isinstance(graph_signals, dict) else {},
        "lease_conflicts_considered": lease_conflicts if isinstance(lease_conflicts, list) else [],
        "legacy_result": legacy_payload if isinstance(legacy_payload, dict) else {},
    }


def scheduler_candidates_read_model(conn: sqlite3.Connection) -> dict[str, Any]:
    return latest_scheduler_decision_conn(conn)


def infer_conveyor_stage(state: Mapping[str, Any]) -> tuple[str, str, str]:
    active = state.get("active_role_run") if isinstance(state.get("active_role_run"), dict) else {}
    decision = state.get("last_decision") if isinstance(state.get("last_decision"), dict) else {}
    active_role = str(active.get("role") or "").strip()
    decision_role = str(decision.get("role") or "").strip()
    role = active_role or decision_role
    reason = str(active.get("reason") or decision.get("reason") or "").strip().lower()
    status = str(state.get("status") or "ACTIVE").strip().upper()
    stage_status = "running" if active else "ready"

    if status == "CRITICAL_STOP":
        return "handoff", "blocked", "conveyor"
    if status in {"BLOCKED_ON_USER", "ACTIVE_WITH_PENDING_USER_INPUT"}:
        return "handoff", "waiting", "planner"
    if active_role in ROLE_TO_CONVEYOR_STAGE:
        stage, owner_role = ROLE_TO_CONVEYOR_STAGE[active_role]
        return stage, stage_status, owner_role
    if decision_role in ROLE_TO_CONVEYOR_STAGE:
        stage, owner_role = ROLE_TO_CONVEYOR_STAGE[decision_role]
        return stage, stage_status, owner_role
    if "human" in reason or "user" in reason:
        return "handoff", "waiting", "planner"
    if "complete" in reason or "should-halt" in reason or "stop" in reason:
        return "continuation", "closed", "conveyor"
    if "baseline" in reason or "verification" in reason or "candidate" in reason:
        return "validation", stage_status, role or "hardener"
    if "queued role patch" in reason or "integration" in reason:
        return "integration", stage_status, "integrator"
    if reason:
        return "continuation", "idle", "conveyor"
    return "intake", "ready", "planner"


def validation_status_from_rows(conn: sqlite3.Connection, work_item_id: str) -> str:
    rows = conn.execute(
        "SELECT status, COUNT(*) AS count FROM validation_receipts WHERE work_item_id = ? GROUP BY status",
        (work_item_id,),
    ).fetchall()
    counts = {str(row["status"]).lower(): int(row["count"]) for row in rows}
    if counts.get("fail") or counts.get("failed"):
        return "failed"
    if counts.get("blocked") or counts.get("blocked_environment"):
        return "blocked"
    if counts.get("warn") or counts.get("warning"):
        return "warning"
    if counts.get("running") or counts.get("pending"):
        return "pending"
    if counts.get("pass") or counts.get("passed"):
        return "passed"
    legacy = validation_summary(conn).get("counts", {})
    if isinstance(legacy, dict):
        if any(int(value or 0) for key, value in legacy.items() if str(key).lower() in {"fail", "failed"}):
            return "failed"
        if any(int(value or 0) for key, value in legacy.items() if str(key).lower() in {"pass", "passed", "ok"}):
            return "passed"
    return "not_recorded"


def validation_receipt_status(source_status: Any, *, source_kind: str = "") -> str:
    status = str(source_status or "").strip().lower()
    if source_kind == "baseline_verification":
        if status == "passing":
            return "pass"
        if status == "blocked_environment":
            return "blocked"
        if status in {"missing_config", "repairable_local_service", "failing_source", "unknown"}:
            return "fail"
    if status in {"passing", "passed", "pass", "ok", "success", "clean"}:
        return "pass"
    if status in {"failing", "failed", "fail", "error", "critical", "critical_stop"}:
        return "fail"
    if status in {"blocked", "blocked_environment", "environment"}:
        return "blocked"
    if status in {"warn", "warning"}:
        return "warn"
    if status in {"running", "pending", "not_run"}:
        return "pending"
    return status or "unknown"


def baseline_validation_receipt_status(baseline: Mapping[str, Any]) -> str:
    status = validation_receipt_status(baseline.get("status"), source_kind="baseline_verification")
    review = adjudicate_baseline_blocker(baseline)
    if status in {"blocked", "fail"} and not review.get("is_blocker"):
        return "warn"
    return status


def upsert_validation_receipt(
    conn: sqlite3.Connection,
    *,
    receipt_id: str,
    work_item_id: str,
    stage: str,
    kind: str,
    run_id: str = "",
    command: str = "",
    status: str = "unknown",
    started_at: str = "",
    finished_at: str = "",
    log_artifact_id: str = "",
    event_id: int | None = None,
    payload: Mapping[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO validation_receipts(
            receipt_id, work_item_id, run_id, stage, kind, command, status,
            lease_json, started_at, finished_at, log_artifact_id, event_id, payload_json
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, '{}', ?, ?, ?, ?, ?)
        ON CONFLICT(receipt_id) DO UPDATE SET
            work_item_id=excluded.work_item_id,
            run_id=excluded.run_id,
            stage=excluded.stage,
            kind=excluded.kind,
            command=excluded.command,
            status=excluded.status,
            started_at=excluded.started_at,
            finished_at=excluded.finished_at,
            log_artifact_id=excluded.log_artifact_id,
            event_id=excluded.event_id,
            payload_json=excluded.payload_json
        """,
        (
            receipt_id,
            work_item_id,
            run_id,
            stage,
            kind,
            command,
            status,
            started_at,
            finished_at,
            log_artifact_id,
            event_id,
            stable_json(dict(payload or {})),
        ),
    )


def upsert_blocker(
    conn: sqlite3.Connection,
    *,
    blocker_id: str,
    task_id: str,
    kind: str,
    status: str,
    summary: str,
    resume_token: str = "",
    created_at: str = "",
    updated_at: str = "",
    payload: Mapping[str, Any] | None = None,
) -> None:
    now = utc_now()
    conn.execute(
        """
        INSERT INTO blockers(blocker_id, task_id, kind, status, summary, resume_token, created_at, updated_at, payload_json)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(blocker_id) DO UPDATE SET
            task_id=excluded.task_id,
            kind=excluded.kind,
            status=excluded.status,
            summary=excluded.summary,
            resume_token=excluded.resume_token,
            updated_at=excluded.updated_at,
            payload_json=excluded.payload_json
        """,
        (
            blocker_id,
            task_id,
            kind,
            status,
            summary,
            resume_token,
            created_at or now,
            updated_at or now,
            stable_json(dict(payload or {})),
        ),
    )


def materialize_blocker_reviews(conn: sqlite3.Connection, target: Path) -> None:
    """Record adjudicated blockers with audit payloads instead of only raw labels."""

    baseline = read_json_file(existing_or_target_path(target, "target/baseline_verification.json"))
    conn.execute(
        "DELETE FROM next_actions WHERE source_projection = ?",
        (BLOCKER_REVIEW_PROJECTION_NAME,),
    )
    if not baseline:
        return
    review = adjudicate_baseline_blocker(baseline)
    status = str(review.get("blocker_status") or ("open" if review.get("is_blocker") else "superseded"))
    verdict = str(review.get("verdict") or "needs_human")
    if verdict == "not_applicable":
        conn.execute(
            """
            UPDATE blockers
            SET status = 'resolved', updated_at = ?
            WHERE kind = 'baseline_verification' AND status NOT IN ('closed', 'resolved', 'superseded')
            """,
            (utc_now(),),
        )
        return
    upsert_blocker(
        conn,
        blocker_id=str(review.get("blocker_id") or "blocker:baseline_verification:baseline"),
        task_id=CONVEYOR_TASK_ID,
        kind="baseline_verification",
        status=status,
        summary=str(review.get("summary") or baseline.get("root_cause") or "Baseline blocker needs review."),
        resume_token=str(baseline.get("failure_signature") or ""),
        created_at=str(baseline.get("first_seen_at") or ""),
        updated_at=str(baseline.get("last_seen_at") or ""),
        payload={
            "source": "baseline_verification",
            "baseline": baseline,
            "blocker_review": review,
        },
    )
    if verdict == "needs_human":
        now = utc_now()
        conn.execute(
            """
            INSERT INTO next_actions(action_id, task_id, owner_role, kind, status, reason, priority, created_at, updated_at, source_projection, payload_json)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"next:blocker-review:{str(review.get('blocker_id') or 'baseline')[:120]}",
                CONVEYOR_TASK_ID,
                "planner",
                "blocker_adjudication",
                "planned",
                str(review.get("recommended_action") or "Adjudicate whether the blocker is real before stopping automation."),
                -10,
                now,
                now,
                BLOCKER_REVIEW_PROJECTION_NAME,
                stable_json({"blocker_review": review}),
            ),
        )


def materialize_validation_receipts(conn: sqlite3.Connection, target: Path) -> None:
    """Project validation evidence into typed receipts without making files authoritative."""

    now = utc_now()
    with conn:
        rows = conn.execute(
            """
            SELECT validation_id, task_id, run_id, kind, command, status,
                   started_at, finished_at, log_artifact_id, payload_json
            FROM validations
            ORDER BY COALESCE(NULLIF(finished_at, ''), started_at) DESC
            LIMIT 100
            """
        ).fetchall()
        for row in rows:
            payload = _json_cell(row["payload_json"], {})
            upsert_validation_receipt(
                conn,
                receipt_id=f"receipt:validation:{row['validation_id']}",
                work_item_id=CONVEYOR_WORK_ITEM_ID,
                stage="validation",
                kind=str(row["kind"] or "validation"),
                run_id=str(row["run_id"] or ""),
                command=str(row["command"] or ""),
                status=validation_receipt_status(row["status"]),
                started_at=str(row["started_at"] or ""),
                finished_at=str(row["finished_at"] or ""),
                log_artifact_id=str(row["log_artifact_id"] or ""),
                payload={
                    "source": "validations",
                    "validation_id": str(row["validation_id"]),
                    "task_id": str(row["task_id"] or ""),
                    "run_id": str(row["run_id"] or ""),
                    "payload": payload if isinstance(payload, dict) else {},
                },
            )

        baseline = read_json_file(existing_or_target_path(target, "target/baseline_verification.json"))
        if baseline:
            checks = baseline.get("checks_run") if isinstance(baseline.get("checks_run"), list) else []
            upsert_validation_receipt(
                conn,
                receipt_id="receipt:baseline_verification",
                work_item_id=CONVEYOR_WORK_ITEM_ID,
                stage="validation",
                kind="baseline_verification",
                command="; ".join(str(item) for item in checks[:4]),
                status=baseline_validation_receipt_status(baseline),
                started_at=str(baseline.get("first_seen_at") or ""),
                finished_at=str(baseline.get("last_seen_at") or now),
                log_artifact_id="target/baseline_verification.json",
                payload={
                    "source": "baseline_verification",
                    "record": baseline,
                    "blocker_review": adjudicate_baseline_blocker(baseline),
                },
            )

        safety = read_json_file(existing_or_target_path(target, "target/integration_safety_check.json"))
        if safety:
            upsert_validation_receipt(
                conn,
                receipt_id="receipt:integration_safety",
                work_item_id=CONVEYOR_WORK_ITEM_ID,
                stage="validation",
                kind="integration_safety",
                command=str(safety.get("command") or "python3 scripts/check_integration_safety.py"),
                status=validation_receipt_status(safety.get("status")),
                started_at=str(safety.get("checked_at") or ""),
                finished_at=str(safety.get("checked_at") or now),
                log_artifact_id="target/integration_safety_check.json",
                payload={"source": "integration_safety_check", "record": safety},
            )


def upsert_conveyor_stage_attempt(
    conn: sqlite3.Connection,
    *,
    work_item_id: str,
    stage: str,
    stage_status: str,
    owner_role: str,
    reason: str,
    run_id: str,
    event_id: int | None,
    payload: Mapping[str, Any],
) -> None:
    if event_id is None:
        return
    attempt_id = f"attempt:{work_item_id}:{event_id}"
    now = utc_now()
    started_at = str(payload.get("started_at") or payload.get("decided_at") or now)
    finished_at = str(payload.get("finished_at") or "") if stage_status in {"finished", "closed", "blocked"} else ""
    with conn:
        conn.execute(
            """
            INSERT INTO conveyor_stage_attempts(
                attempt_id, work_item_id, stage, status, owner_role, reason,
                run_id, started_at, finished_at, event_id, payload_json
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(attempt_id) DO UPDATE SET
                status=excluded.status,
                owner_role=excluded.owner_role,
                reason=excluded.reason,
                run_id=excluded.run_id,
                finished_at=excluded.finished_at,
                payload_json=excluded.payload_json
            """,
            (
                attempt_id,
                work_item_id,
                stage,
                stage_status,
                owner_role,
                reason,
                run_id,
                started_at,
                finished_at,
                event_id,
                stable_json(dict(payload)),
            ),
        )


def apply_conveyor_machine_read_models(
    conn: sqlite3.Connection,
    target: Path,
    state: Mapping[str, Any],
    *,
    event_id: int | None,
    event_type: str = "",
) -> dict[str, Any]:
    target = target.expanduser().resolve()
    capability = latest_capability_manifest(conn) or refresh_capability_manifest_conn(conn, target)
    materialize_validation_receipts(conn, target)
    materialize_blocker_reviews(conn, target)
    stage, stage_status, owner_role = infer_conveyor_stage(state)
    now = utc_now()
    active = state.get("active_role_run") if isinstance(state.get("active_role_run"), dict) else {}
    last_decision = state.get("last_decision") if isinstance(state.get("last_decision"), dict) else {}
    reason = str(active.get("reason") or last_decision.get("reason") or "")
    last_active = state.get("last_active_role_run") if isinstance(state.get("last_active_role_run"), dict) else {}
    run_id = str(active.get("run_id") or last_active.get("run_id") or "")
    head = str((capability.get("repo") if isinstance(capability.get("repo"), dict) else {}).get("head_commit") or "")
    status = str(state.get("status") or "ACTIVE")
    if stage_status == "waiting" and status == "ACTIVE":
        status = "ACTIVE_WITH_PENDING_USER_INPUT"
    validation_status = validation_status_from_rows(conn, CONVEYOR_WORK_ITEM_ID)
    row = conn.execute(
        "SELECT current_stage, entered_at, created_at FROM conveyor_work_items WHERE work_item_id = ?",
        (CONVEYOR_WORK_ITEM_ID,),
    ).fetchone()
    entered_at = now if row is None or str(row["current_stage"]) != stage else str(row["entered_at"])
    created_at = now if row is None else str(row["created_at"])
    continuation_token = f"{CONVEYOR_WORK_ITEM_ID}:{stage}:{event_id or 0}"
    payload = {
        "event_type": event_type,
        "legacy_projection_keys": sorted(str(key) for key in state.keys()),
        "reason": reason,
        "decision": last_decision if isinstance(last_decision, dict) else {},
        "active_role_run": active if isinstance(active, dict) else {},
        "capability_digest": capability.get("digest"),
    }
    with conn:
        conn.execute(
            """
            INSERT INTO conveyor_work_items(
                work_item_id, parent_work_item_id, title, status, current_stage, stage_status,
                owner_role, dependency_state, workspace_id, repo_root, base_commit, head_commit,
                capability_manifest_id, capability_manifest_version, validation_status, risk_tier,
                handoff_target, continuation_token, ledger_event_id, entered_at, created_at, updated_at, payload_json
            )
            VALUES(?, '', ?, ?, ?, ?, ?, 'unblocked', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(work_item_id) DO UPDATE SET
                status=excluded.status,
                current_stage=excluded.current_stage,
                stage_status=excluded.stage_status,
                owner_role=excluded.owner_role,
                dependency_state=excluded.dependency_state,
                workspace_id=excluded.workspace_id,
                repo_root=excluded.repo_root,
                base_commit=excluded.base_commit,
                head_commit=excluded.head_commit,
                capability_manifest_id=excluded.capability_manifest_id,
                capability_manifest_version=excluded.capability_manifest_version,
                validation_status=excluded.validation_status,
                risk_tier=excluded.risk_tier,
                handoff_target=excluded.handoff_target,
                continuation_token=excluded.continuation_token,
                ledger_event_id=excluded.ledger_event_id,
                entered_at=excluded.entered_at,
                updated_at=excluded.updated_at,
                payload_json=excluded.payload_json
            """,
            (
                CONVEYOR_WORK_ITEM_ID,
                "Default conveyor work item",
                status,
                stage,
                stage_status,
                owner_role,
                str(active.get("worktree_id") or active.get("role") or ""),
                str(target),
                head,
                head,
                CAPABILITY_MANIFEST_ID,
                int(capability.get("version") or 0),
                validation_status,
                "medium",
                "user" if stage == "handoff" else "",
                continuation_token,
                event_id,
                entered_at,
                created_at,
                now,
                stable_json(payload),
            ),
        )
    upsert_conveyor_stage_attempt(
        conn,
        work_item_id=CONVEYOR_WORK_ITEM_ID,
        stage=stage,
        stage_status=stage_status,
        owner_role=owner_role,
        reason=reason,
        run_id=run_id,
        event_id=event_id,
        payload=payload,
    )
    return conveyor_machine_payload(conn, target)


def conveyor_machine_payload(conn: sqlite3.Connection, target: Path) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM conveyor_work_items WHERE work_item_id = ?",
        (CONVEYOR_WORK_ITEM_ID,),
    ).fetchone()
    if row is None:
        return {}
    stage = str(row["current_stage"])
    contract = stage_contract_payload(
        conn.execute("SELECT * FROM conveyor_stage_contracts WHERE stage = ?", (stage,)).fetchone()
    )
    contract_rows = conn.execute(
        "SELECT * FROM conveyor_stage_contracts ORDER BY rowid ASC"
    ).fetchall()
    attempts = conn.execute(
        """
        SELECT attempt_id, stage, status, owner_role, reason, run_id, started_at, finished_at, event_id
        FROM conveyor_stage_attempts
        WHERE work_item_id = ?
        ORDER BY COALESCE(NULLIF(started_at, ''), attempt_id) DESC
        LIMIT 12
        """,
        (CONVEYOR_WORK_ITEM_ID,),
    ).fetchall()
    receipts = conn.execute(
        """
        SELECT receipt_id, stage, kind, command, status, started_at, finished_at, log_artifact_id
        FROM validation_receipts
        WHERE work_item_id = ?
        ORDER BY COALESCE(NULLIF(finished_at, ''), started_at) DESC
        LIMIT 12
        """,
        (CONVEYOR_WORK_ITEM_ID,),
    ).fetchall()
    capability = latest_capability_manifest(conn)
    payload_json = _json_cell(row["payload_json"], {})
    work_item = {
        "id": str(row["work_item_id"]),
        "title": str(row["title"]),
        "status": str(row["status"]),
        "current_stage": stage,
        "stage_status": str(row["stage_status"]),
        "owner_role": str(row["owner_role"]),
        "dependency_state": str(row["dependency_state"]),
        "workspace_id": str(row["workspace_id"]),
        "repo_root": str(row["repo_root"]),
        "base_commit": str(row["base_commit"]),
        "head_commit": str(row["head_commit"]),
        "capability_manifest_id": str(row["capability_manifest_id"]),
        "capability_manifest_version": int(row["capability_manifest_version"]),
        "validation_status": str(row["validation_status"]),
        "risk_tier": str(row["risk_tier"]),
        "handoff_target": str(row["handoff_target"]),
        "continuation_token": str(row["continuation_token"]),
        "ledger_event_id": int(row["ledger_event_id"]) if row["ledger_event_id"] is not None else None,
        "entered_at": str(row["entered_at"]),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
        "payload": payload_json if isinstance(payload_json, dict) else {},
    }
    return {
        "schema_version": 1,
        "machine_version": CONVEYOR_MACHINE_VERSION,
        "authority": "sqlite",
        "work_item": work_item,
        "current_stage": stage,
        "stage_status": work_item["stage_status"],
        "owner_role": work_item["owner_role"],
        "stage_contract": contract,
        "stage_contracts": [stage_contract_payload(item) for item in contract_rows],
        "capability_manifest": capability,
        "stage_attempts": [dict(item) for item in attempts],
        "validation_receipts": [dict(item) for item in receipts],
        "policy": {
            "workflow_owns_truth": True,
            "agents_propose_transitions": True,
            "sqlite_is_canonical": True,
            "markdown_and_json_are_projections": True,
            "integration_is_serialized": True,
            "target": str(target),
        },
    }


def apply_conveyor_read_models(conn: sqlite3.Connection, state: Mapping[str, Any], *, event_id: int | None) -> None:
    now = utc_now()
    active = state.get("active_role_run") if isinstance(state.get("active_role_run"), dict) else {}
    last_decision = state.get("last_decision") if isinstance(state.get("last_decision"), dict) else {}
    machine = state.get("state_machine") if isinstance(state.get("state_machine"), dict) else {}
    work_item = machine.get("work_item") if isinstance(machine.get("work_item"), dict) else {}
    phase = str(work_item.get("current_stage") or machine.get("current_stage") or last_decision.get("role") or active.get("role") or "idle")
    with conn:
        conn.execute(
            """
            INSERT INTO tasks(task_id, parent_task_id, title, status, phase, owner_role, risk_tier, created_at, updated_at, payload_json)
            VALUES(?, '', ?, ?, ?, ?, '', ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                status=excluded.status,
                phase=excluded.phase,
                owner_role=excluded.owner_role,
                updated_at=excluded.updated_at,
                payload_json=excluded.payload_json
            """,
            (
                CONVEYOR_TASK_ID,
                "Automation conveyor",
                "ACTIVE",
                phase,
                str(active.get("role") or ""),
                now,
                now,
                stable_json({"projection": CONVEYOR_PROJECTION_NAME, "last_event_id": event_id}),
            ),
        )
        for run_key in ("active_role_run", "last_active_role_run"):
            run = state.get(run_key)
            if not isinstance(run, dict) or not run.get("run_id"):
                continue
            run_id = str(run.get("run_id"))
            status = str(run.get("status") or ("running" if run_key == "active_role_run" else "finished"))
            conn.execute(
                """
                INSERT INTO runs(run_id, task_id, stream_id, status, phase, owner_role, started_at, finished_at, payload_json)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status=excluded.status,
                    phase=excluded.phase,
                    owner_role=excluded.owner_role,
                    started_at=excluded.started_at,
                    finished_at=excluded.finished_at,
                    payload_json=excluded.payload_json
                """,
                (
                    run_id,
                    CONVEYOR_TASK_ID,
                    CONVEYOR_STREAM_ID,
                    status,
                    str(run.get("role") or ""),
                    str(run.get("role") or ""),
                    str(run.get("started_at") or ""),
                    str(run.get("finished_at") or ""),
                    stable_json(run),
                ),
            )
        conn.execute(
            "DELETE FROM next_actions WHERE source_projection = ?",
            (CONVEYOR_PROJECTION_NAME,),
        )
        decision_queue = state.get("decision_queue") if isinstance(state.get("decision_queue"), list) else []
        for index, item in enumerate(decision_queue[:12]):
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "idle")
            state_name = str(item.get("state") or "planned")
            reason = str(item.get("reason") or "")
            action_id = f"next:conveyor:{index}:{sha256_text(role + state_name + reason)[:12]}"
            conn.execute(
                """
                INSERT INTO next_actions(action_id, task_id, owner_role, kind, status, reason, priority, created_at, updated_at, source_projection, payload_json)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action_id,
                    CONVEYOR_TASK_ID,
                    role,
                    "conveyor_lane",
                    state_name,
                    reason,
                    index,
                    now,
                    now,
                    CONVEYOR_PROJECTION_NAME,
                    stable_json(item),
                ),
            )


def annotate_projection_state(
    state: dict[str, Any],
    db_path: Path,
    event_id: int | None,
    *,
    machine: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    annotated = normalize_conveyor_state(state)
    annotated["canonical_state"] = {
        "authority": "sqlite",
        "database_path": str(db_path),
        "projection": CONVEYOR_PROJECTION_NAME,
        "projected_at": utc_now(),
        "event_id": event_id,
        "note": "This JSON file is a generated projection. Do not edit it as authoritative state.",
    }
    if machine:
        annotated["state_machine"] = dict(machine)
    return annotated


def write_conveyor_state(
    projection_path: Path,
    state: Mapping[str, Any],
    *,
    event_type: str = "conveyor.state_projection_updated",
    actor_role: str = "conveyor",
    phase: str = "",
    status: str = "ACTIVE",
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    base_state = normalize_conveyor_state(state)
    base_state["updated_at"] = utc_now()
    db_path = database_path_for_projection(projection_path)
    target = target_from_projection_path(projection_path)
    active_run = base_state.get("active_role_run") if isinstance(base_state.get("active_role_run"), dict) else {}
    with closing(connect(db_path)) as conn:
        ensure_automation_control_conn(conn, target, import_legacy_if_empty=True)
        refresh_capability_manifest_conn(conn, target, actor_role=actor_role, append_event_first=True)
        event_payload = {
            "projection": CONVEYOR_PROJECTION_NAME,
            "state": base_state,
        }
        if payload:
            event_payload["metadata"] = dict(payload)
        event_id = append_event(
            conn,
            StateEvent(
                stream_id=CONVEYOR_STREAM_ID,
                event_type=event_type,
                actor_role=actor_role,
                phase=phase,
                status=status,
                task_id=CONVEYOR_TASK_ID,
                run_id=str(active_run.get("run_id") or ""),
                payload=event_payload,
            ),
        )
        machine = apply_conveyor_machine_read_models(
            conn,
            target,
            base_state,
            event_id=event_id,
            event_type=event_type,
        )
        annotated = annotate_projection_state(base_state, db_path, event_id, machine=machine)
        replace_projection(conn, name=CONVEYOR_PROJECTION_NAME, payload=annotated, event_id=event_id)
        apply_conveyor_read_models(conn, annotated, event_id=event_id)
        replace_projection(conn, name=CONVEYOR_MACHINE_PROJECTION_NAME, payload=machine, event_id=event_id)
        checkpoint_stream(
            conn,
            stream_id=CONVEYOR_STREAM_ID,
            kind="conveyor_projection",
            state=annotated,
            event_id=event_id,
        )
    write_json_projection(projection_path, annotated)
    return annotated


def import_legacy_conveyor_json(projection_path: Path, db_path: Path) -> dict[str, Any]:
    legacy = normalize_conveyor_state(read_json_file(projection_path))
    source_hash = sha256_text(stable_json(legacy))
    target = target_from_projection_path(projection_path)
    with closing(connect(db_path)) as conn:
        ensure_automation_control_conn(conn, target, import_legacy_if_empty=True)
        existing = conn.execute(
            "SELECT event_id FROM compatibility_migrations WHERE source_path = ? AND source_sha256 = ?",
            (str(projection_path), source_hash),
        ).fetchone()
        if existing is not None:
            projected = load_projection(conn, CONVEYOR_PROJECTION_NAME)
            if projected:
                return normalize_conveyor_state(projected)
        refresh_capability_manifest_conn(conn, target, actor_role="migration", append_event_first=True)
        event_id = append_event(
            conn,
            StateEvent(
                stream_id=CONVEYOR_STREAM_ID,
                event_type="compatibility.legacy_conveyor_json_imported",
                actor_role="migration",
                phase="migration",
                status="ACTIVE",
                task_id=CONVEYOR_TASK_ID,
                payload={"source_path": str(projection_path), "source_sha256": source_hash, "state": legacy},
            ),
        )
        machine = apply_conveyor_machine_read_models(
            conn,
            target,
            legacy,
            event_id=event_id,
            event_type="compatibility.legacy_conveyor_json_imported",
        )
        annotated = annotate_projection_state(legacy, db_path, event_id, machine=machine)
        replace_projection(conn, name=CONVEYOR_PROJECTION_NAME, payload=annotated, event_id=event_id)
        apply_conveyor_read_models(conn, annotated, event_id=event_id)
        replace_projection(conn, name=CONVEYOR_MACHINE_PROJECTION_NAME, payload=machine, event_id=event_id)
        checkpoint_stream(
            conn,
            stream_id=CONVEYOR_STREAM_ID,
            kind="legacy_import",
            state=annotated,
            event_id=event_id,
        )
        with conn:
            conn.execute(
                "INSERT INTO compatibility_migrations(source_path, source_sha256, imported_at, event_id) "
                "VALUES(?, ?, ?, ?) "
                "ON CONFLICT(source_path) DO UPDATE SET source_sha256=excluded.source_sha256, "
                "imported_at=excluded.imported_at, event_id=excluded.event_id",
                (str(projection_path), source_hash, utc_now(), event_id),
            )
    write_json_projection(projection_path, annotated)
    return annotated


def initialize_conveyor_state(projection_path: Path, db_path: Path) -> dict[str, Any]:
    state = default_conveyor_state()
    return write_conveyor_state(
        projection_path,
        state,
        event_type="conveyor.state_initialized",
        actor_role="runtime",
        phase="initialization",
        payload={"reason": "canonical SQLite store initialized"},
    )


def load_conveyor_state(projection_path: Path) -> dict[str, Any]:
    db_path = database_path_for_projection(projection_path)
    if db_path.exists():
        with closing(connect(db_path)) as conn:
            projected = load_projection(conn, CONVEYOR_PROJECTION_NAME)
            if projected:
                normalized = normalize_conveyor_state(projected)
                if isinstance(normalized.get("state_machine"), dict):
                    return normalized
                target = target_from_projection_path(projection_path)
                refresh_capability_manifest_conn(conn, target, actor_role="runtime", append_event_first=True)
                machine = apply_conveyor_machine_read_models(
                    conn,
                    target,
                    normalized,
                    event_id=None,
                    event_type="conveyor.state_machine_backfilled",
                )
                annotated = annotate_projection_state(normalized, db_path, None, machine=machine)
                replace_projection(conn, name=CONVEYOR_PROJECTION_NAME, payload=annotated, event_id=None)
                replace_projection(conn, name=CONVEYOR_MACHINE_PROJECTION_NAME, payload=machine, event_id=None)
                write_json_projection(projection_path, annotated)
                return normalize_conveyor_state(annotated)
    if projection_path.exists():
        return import_legacy_conveyor_json(projection_path, db_path)
    return initialize_conveyor_state(projection_path, db_path)


def annotate_runner_state(state: Mapping[str, Any], db_path: Path, event_id: int | None) -> dict[str, Any]:
    annotated = normalize_runner_state(state)
    if not annotated:
        return {}
    annotated["canonical_state"] = {
        "authority": "sqlite",
        "database_path": str(db_path),
        "projection": RUNNER_PROJECTION_NAME,
        "projected_at": utc_now(),
        "event_id": event_id,
        "note": "This JSON file is a generated projection. Do not edit it as authoritative state.",
    }
    return annotated


def write_runner_state(
    projection_path: Path,
    state: Mapping[str, Any],
    *,
    event_type: str = "runner.state_projection_updated",
    actor_role: str = "dashboard",
    phase: str = "run_control",
    status: str = "",
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    base_state = normalize_runner_state(state)
    if not base_state:
        base_state = {"schema_version": 1, "state": "stopped"}
    base_state["updated_at"] = utc_now()
    db_path = database_path_for_projection(projection_path)
    with closing(connect(db_path)) as conn:
        event_payload = {
            "projection": RUNNER_PROJECTION_NAME,
            "state": base_state,
        }
        if payload:
            event_payload["metadata"] = dict(payload)
        event_id = append_event(
            conn,
            StateEvent(
                stream_id=RUNNER_STREAM_ID,
                event_type=event_type,
                actor_role=actor_role,
                phase=phase,
                status=status or str(base_state.get("state") or ""),
                task_id=RUNNER_TASK_ID,
                run_id=str(base_state.get("run_id") or ""),
                payload=event_payload,
            ),
        )
        annotated = annotate_runner_state(base_state, db_path, event_id)
        replace_projection(conn, name=RUNNER_PROJECTION_NAME, payload=annotated, event_id=event_id)
        checkpoint_stream(
            conn,
            stream_id=RUNNER_STREAM_ID,
            kind="runner_projection",
            state=annotated,
            event_id=event_id,
        )
    write_json_projection(projection_path, annotated)
    return annotated


def import_legacy_runner_json(projection_path: Path, db_path: Path) -> dict[str, Any]:
    legacy = normalize_runner_state(read_json_file(projection_path))
    if not legacy:
        return {}
    source_hash = sha256_text(stable_json(legacy))
    with closing(connect(db_path)) as conn:
        existing = conn.execute(
            "SELECT event_id FROM compatibility_migrations WHERE source_path = ? AND source_sha256 = ?",
            (str(projection_path), source_hash),
        ).fetchone()
        if existing is not None:
            projected = load_projection(conn, RUNNER_PROJECTION_NAME)
            if projected:
                return normalize_runner_state(projected)
        event_id = append_event(
            conn,
            StateEvent(
                stream_id=RUNNER_STREAM_ID,
                event_type="compatibility.legacy_runner_json_imported",
                actor_role="migration",
                phase="migration",
                status=str(legacy.get("state") or ""),
                task_id=RUNNER_TASK_ID,
                payload={"source_path": str(projection_path), "source_sha256": source_hash, "state": legacy},
            ),
        )
        annotated = annotate_runner_state(legacy, db_path, event_id)
        replace_projection(conn, name=RUNNER_PROJECTION_NAME, payload=annotated, event_id=event_id)
        checkpoint_stream(
            conn,
            stream_id=RUNNER_STREAM_ID,
            kind="legacy_import",
            state=annotated,
            event_id=event_id,
        )
        with conn:
            conn.execute(
                "INSERT INTO compatibility_migrations(source_path, source_sha256, imported_at, event_id) "
                "VALUES(?, ?, ?, ?) "
                "ON CONFLICT(source_path) DO UPDATE SET source_sha256=excluded.source_sha256, "
                "imported_at=excluded.imported_at, event_id=excluded.event_id",
                (str(projection_path), source_hash, utc_now(), event_id),
            )
    write_json_projection(projection_path, annotated)
    return annotated


def load_runner_state(projection_path: Path) -> dict[str, Any]:
    db_path = database_path_for_projection(projection_path)
    if db_path.exists():
        with closing(connect(db_path)) as conn:
            projected = load_projection(conn, RUNNER_PROJECTION_NAME)
            if projected:
                return normalize_runner_state(projected)
    if projection_path.exists():
        return import_legacy_runner_json(projection_path, db_path)
    return {}


def _normalize_status(value: Any, *, default: str = "ACTIVE") -> str:
    status = str(value or "").strip().upper()
    return status if status in STATUS_MODEL else default


def _markdown_section(text: str, heading: str) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return ""
    next_heading = re.search(r"^##\s+", text[match.end() :], re.MULTILINE)
    end = match.end() + next_heading.start() if next_heading else len(text)
    return text[match.end() : end]


def _first_section_line(text: str, heading: str) -> str:
    section = _markdown_section(text, heading)
    for raw in section.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        return _brief_text(re.sub(r"^[-*]\s+", "", line), limit=260)
    return ""


def _section_bullets(text: str, heading: str, *, limit: int = BRIEF_ITEM_LIMIT) -> list[str]:
    section = _markdown_section(text, heading)
    bullets: list[str] = []
    in_code = False
    for raw in section.splitlines():
        line = raw.strip()
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not line.startswith("- "):
            continue
        item = _brief_text(line[2:], limit=320)
        if item:
            bullets.append(item)
        if len(bullets) >= limit:
            break
    return bullets


def _keyed_section_value(text: str, heading: str, keys: list[str]) -> str:
    section = _markdown_section(text, heading)
    for key in keys:
        match = re.search(rf"^-\s*{re.escape(key)}:\s*(.+)", section, re.MULTILINE)
        if match:
            value = _brief_text(match.group(1), limit=320)
            if value:
                return value
    return ""


def _task_bool_value(text: str, label: str, *, default: bool) -> bool:
    match = re.search(rf"^-\s*{re.escape(label)}:\s*(true|false)\s*$", text, re.MULTILINE | re.IGNORECASE)
    if not match:
        return default
    return match.group(1).lower() == "true"


def _task_int_value(text: str, label: str, *, default: int, minimum: int = 0, maximum: int = 10) -> int:
    match = re.search(rf"^-\s*{re.escape(label)}:\s*(\d+)\s*$", text, re.MULTILINE | re.IGNORECASE)
    if not match:
        return default
    try:
        value = int(match.group(1))
    except ValueError:
        return default
    return min(max(value, minimum), maximum)


def _validation_check_status(text: str) -> str:
    lower = text.lower().strip()
    if lower.startswith("pass"):
        return "pass"
    if lower.startswith("fail"):
        return "fail"
    if lower.startswith("warn"):
        return "warn"
    if lower.startswith("pending") or lower.startswith("not run") or "not run yet" in lower:
        return "pending"
    if re.search(r"\bpassed\b", lower):
        return "pass"
    if re.search(r"\bfailed\b|\bfailure\b", lower):
        return "fail"
    if re.search(r"\bwarning\b|\bwarned\b", lower):
        return "warn"
    if re.search(r"\bnot run\b", lower):
        return "pending"
    return "info"


def _default_automation_control_from_setup(target: Path) -> dict[str, Any]:
    intake = read_json_file(existing_or_target_path(target, ".agentic/project_intake.json"))
    dashboard = read_json_file(existing_or_target_path(target, ".agentic/dashboard_state.json"))
    setup = {**intake, **dashboard}
    project_name = str(setup.get("project_name") or target.name or "target")
    workers_allowed = bool(setup.get("worker_agents_allowed", True))
    write_workers = bool(setup.get("write_worker_agents_allowed", False)) and workers_allowed
    try:
        max_write_workers = int(setup.get("max_write_worker_count") or (1 if write_workers else 0))
    except (TypeError, ValueError):
        max_write_workers = 1 if write_workers else 0
    run_mode = str(setup.get("automation_run_mode") or "continuous_improvement")
    if run_mode == "ticket_campaign":
        horizon = "T1 Ticket-run readiness"
        milestone = "Confirm the ticket queue, setup, and verification path."
        suggested = "Run ticket readiness checks and select one dependency-ready ticket."
    else:
        horizon = "H1 Runnable baseline"
        milestone = "Create or confirm setup, local run path, and verification."
        suggested = "Run one bootstrap pass that records local verification evidence."
    return {
        "status": "ACTIVE",
        "last_updated": "",
        "horizon": horizon,
        "horizon_decision": "stay",
        "current_assessment": f"{project_name} has typed runtime state initialized; no completed automation run is recorded yet.",
        "best_next_milestone": milestone,
        "suggested_next_task": suggested,
        "known_issue": "No active issue summary.",
        "known_issues": [],
        "bootstrap_status": "pending",
        "worker": {
            "agents_allowed": workers_allowed,
            "write_workers_allowed": write_workers,
            "max_write_worker_count": max(0, max_write_workers if write_workers else 0),
        },
        "source": "setup_json",
        "payload": {
            "project_name": project_name,
            "automation_run_mode": run_mode,
            "role_profile": str(setup.get("automation_role_profile") or ""),
        },
    }


def _automation_setup_available(target: Path) -> bool:
    return any(
        existing_or_target_path(target, rel).exists()
        for rel in (
            ".agentic/project_intake.json",
            ".agentic/dashboard_state.json",
            ".agentic/automation_prompt.md",
            "docs/CODEX_AUTOMATION_TASKS.md",
        )
    ) or (target / ".diffmogger" / "manifest.json").exists()


def _unknown_automation_control(target: Path) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "authority": "none",
        "control_id": AUTOMATION_CONTROL_ID,
        "status": "UNKNOWN",
        "last_updated": "",
        "horizon": "",
        "horizon_decision": "",
        "current_assessment": f"{target.name or 'target'} has no Diffmogger automation state yet.",
        "best_next_milestone": "",
        "suggested_next_task": "",
        "known_issue": "No automation state initialized.",
        "known_issues": [],
        "bootstrap_status": "unknown",
        "bootstrap_pending": False,
        "worker": {
            "agents_allowed": False,
            "write_workers_allowed": False,
            "max_write_worker_count": 0,
        },
        "updated_at": "",
        "payload": {},
    }


def _parse_legacy_task_markdown(text: str, *, source_path: Path) -> dict[str, Any]:
    status_match = re.search(r"^AUTOMATION_STATUS:\s*(\S+)", text, re.MULTILINE)
    updated_match = re.search(r"^Last updated:\s*(.+)", text, re.MULTILINE)
    horizon_match = re.search(r"^-\s*Current horizon:\s*(.+)", text, re.MULTILINE)
    decision_match = re.search(r"^-\s*Advancement decision:\s*(.+)", text, re.MULTILINE)
    current_assessment = _keyed_section_value(
        text,
        "Current Project State",
        ["Current assessment", "Current baseline", "Goal"],
    )
    bootstrap_status = "unknown"
    if re.search(r"Current baseline:\s*not bootstrapped yet", text, re.IGNORECASE):
        bootstrap_status = "pending"
    elif current_assessment:
        bootstrap_status = "bootstrapped"
    known_issues = [
        item
        for item in _section_bullets(text, "Known Issues", limit=25)
        if item.lower() not in {"none", "none.", "no known issues", "no known issues."}
    ]
    write_workers_allowed = _task_bool_value(text, "Write-capable worker agents allowed", default=False)
    worker_agents_allowed = _task_bool_value(text, "Worker agents allowed", default=True)
    max_write_worker_count = _task_int_value(
        text,
        "Max write worker count",
        default=0 if not write_workers_allowed else 1,
    )
    checks = _section_bullets(text, "Checks From Last Run", limit=25)
    validation_items = []
    for index, check in enumerate(checks):
        if check.lower().startswith("preferred commands"):
            continue
        validation_items.append(
            {
                "receipt_id": f"receipt:legacy_task_markdown:{index}",
                "kind": "legacy_task_check",
                "command": check,
                "status": _validation_check_status(check),
                "payload": {
                    "source": "legacy_task_markdown",
                    "source_path": str(source_path),
                    "text": check,
                },
            }
        )
    return {
        "status": _normalize_status(status_match.group(1) if status_match else ""),
        "last_updated": _brief_text(updated_match.group(1), limit=120) if updated_match else "",
        "horizon": _brief_text(horizon_match.group(1), limit=180) if horizon_match else "",
        "horizon_decision": _brief_text(decision_match.group(1), limit=160) if decision_match else "",
        "current_assessment": current_assessment,
        "best_next_milestone": _first_section_line(text, "Best Next Milestone"),
        "suggested_next_task": _first_section_line(text, "Suggested Next Sprint-Sized Task"),
        "known_issue": known_issues[0] if known_issues else "No active issue summary.",
        "known_issues": known_issues,
        "bootstrap_status": bootstrap_status,
        "worker": {
            "agents_allowed": worker_agents_allowed,
            "write_workers_allowed": write_workers_allowed and worker_agents_allowed,
            "max_write_worker_count": max_write_worker_count if write_workers_allowed and worker_agents_allowed else 0,
        },
        "source": "legacy_task_markdown",
        "source_path": str(source_path),
        "validation_items": validation_items,
    }


def _automation_control_payload_from_row(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    payload = _json_cell(row["payload_json"], {})
    payload = payload if isinstance(payload, dict) else {}
    known_issues = payload.get("known_issues") if isinstance(payload.get("known_issues"), list) else []
    worker = payload.get("worker") if isinstance(payload.get("worker"), dict) else {}
    return {
        "schema_version": 1,
        "authority": "sqlite",
        "control_id": str(row["control_id"]),
        "status": str(row["status"]),
        "last_updated": str(row["last_updated"] or row["updated_at"] or ""),
        "horizon": str(row["current_horizon"] or ""),
        "horizon_decision": str(row["horizon_decision"] or ""),
        "current_assessment": str(row["current_assessment"] or ""),
        "best_next_milestone": str(row["best_next_milestone"] or ""),
        "suggested_next_task": str(row["suggested_next_task"] or ""),
        "known_issue": str(payload.get("known_issue") or (known_issues[0] if known_issues else "No active issue summary.")),
        "known_issues": [str(item) for item in known_issues],
        "bootstrap_status": str(row["bootstrap_status"] or ""),
        "bootstrap_pending": str(row["bootstrap_status"] or "").lower() in {"pending", "not_bootstrapped", "not bootstrapped"},
        "worker": {
            "agents_allowed": bool(row["worker_agents_allowed"]),
            "write_workers_allowed": bool(row["write_workers_allowed"]) and bool(row["worker_agents_allowed"]),
            "max_write_worker_count": int(row["max_write_worker_count"] or 0)
            if bool(row["write_workers_allowed"]) and bool(row["worker_agents_allowed"])
            else 0,
        },
        "updated_at": str(row["updated_at"] or ""),
        "payload": payload,
    }


def _upsert_automation_control_conn(
    conn: sqlite3.Connection,
    data: Mapping[str, Any],
    *,
    event_id: int | None,
) -> dict[str, Any]:
    now = utc_now()
    worker = data.get("worker") if isinstance(data.get("worker"), Mapping) else {}
    payload = {
        "known_issue": data.get("known_issue") or "No active issue summary.",
        "known_issues": data.get("known_issues") if isinstance(data.get("known_issues"), list) else [],
        "source": data.get("source") or "typed_state",
        "source_path": data.get("source_path") or "",
        "payload": data.get("payload") if isinstance(data.get("payload"), Mapping) else {},
    }
    conn.execute(
        """
        INSERT INTO automation_control(
            control_id, status, last_updated, current_horizon, horizon_decision,
            current_assessment, best_next_milestone, suggested_next_task, bootstrap_status,
            worker_agents_allowed, write_workers_allowed, max_write_worker_count,
            updated_at, payload_json
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(control_id) DO UPDATE SET
            status=excluded.status,
            last_updated=excluded.last_updated,
            current_horizon=excluded.current_horizon,
            horizon_decision=excluded.horizon_decision,
            current_assessment=excluded.current_assessment,
            best_next_milestone=excluded.best_next_milestone,
            suggested_next_task=excluded.suggested_next_task,
            bootstrap_status=excluded.bootstrap_status,
            worker_agents_allowed=excluded.worker_agents_allowed,
            write_workers_allowed=excluded.write_workers_allowed,
            max_write_worker_count=excluded.max_write_worker_count,
            updated_at=excluded.updated_at,
            payload_json=excluded.payload_json
        """,
        (
            AUTOMATION_CONTROL_ID,
            _normalize_status(data.get("status")),
            str(data.get("last_updated") or now),
            str(data.get("horizon") or data.get("current_horizon") or ""),
            str(data.get("horizon_decision") or "stay"),
            str(data.get("current_assessment") or ""),
            str(data.get("best_next_milestone") or ""),
            str(data.get("suggested_next_task") or ""),
            str(data.get("bootstrap_status") or "unknown"),
            1 if bool(worker.get("agents_allowed", True)) else 0,
            1 if bool(worker.get("write_workers_allowed", False)) else 0,
            int(worker.get("max_write_worker_count") or 0),
            now,
            stable_json(payload),
        ),
    )
    row = conn.execute("SELECT * FROM automation_control WHERE control_id = ?", (AUTOMATION_CONTROL_ID,)).fetchone()
    control = _automation_control_payload_from_row(row)
    replace_projection(conn, name=AUTOMATION_CONTROL_PROJECTION_NAME, payload=control, event_id=event_id)
    return control


def ensure_automation_control_conn(
    conn: sqlite3.Connection,
    target: Path,
    *,
    import_legacy_if_empty: bool = True,
) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM automation_control WHERE control_id = ?", (AUTOMATION_CONTROL_ID,)).fetchone()
    if row is not None:
        control = _automation_control_payload_from_row(row)
        replace_projection(conn, name=AUTOMATION_CONTROL_PROJECTION_NAME, payload=control, event_id=None)
        return control

    target = target.expanduser().resolve()
    source_path = existing_or_target_path(target, "docs/CODEX_AUTOMATION_TASKS.md")
    source_text = _read_text(source_path) if import_legacy_if_empty and source_path.exists() else ""
    if not source_text and not _automation_setup_available(target):
        return _unknown_automation_control(target)
    data = _parse_legacy_task_markdown(source_text, source_path=source_path) if source_text else _default_automation_control_from_setup(target)
    source_hash = sha256_text(source_text) if source_text else sha256_text(stable_json(data))
    event_type = "compatibility.legacy_task_markdown_imported" if source_text else "automation.control_initialized"
    event_id = append_event(
        conn,
        StateEvent(
            stream_id=AUTOMATION_CONTROL_STREAM_ID,
            event_type=event_type,
            actor_role="migration" if source_text else "runtime",
            phase="automation_control",
            status=_normalize_status(data.get("status")),
            task_id=AUTOMATION_CONTROL_TASK_ID,
            payload={
                "source_path": str(source_path) if source_text else "",
                "source_sha256": source_hash,
                "source": data.get("source"),
            },
        ),
    )
    with conn:
        control = _upsert_automation_control_conn(conn, data, event_id=event_id)
        for item in data.get("validation_items") or []:
            if not isinstance(item, dict):
                continue
            upsert_validation_receipt(
                conn,
                receipt_id=str(item.get("receipt_id") or ""),
                work_item_id=CONVEYOR_WORK_ITEM_ID,
                stage="validation",
                kind=str(item.get("kind") or "legacy_task_check"),
                command=str(item.get("command") or ""),
                status=str(item.get("status") or "info"),
                finished_at=str(data.get("last_updated") or ""),
                log_artifact_id=target_rel(target, "docs/CODEX_AUTOMATION_TASKS.md"),
                event_id=event_id,
                payload=item.get("payload") if isinstance(item.get("payload"), Mapping) else {},
            )
        if source_text:
            conn.execute(
                "INSERT INTO compatibility_migrations(source_path, source_sha256, imported_at, event_id) "
                "VALUES(?, ?, ?, ?) "
                "ON CONFLICT(source_path) DO UPDATE SET source_sha256=excluded.source_sha256, "
                "imported_at=excluded.imported_at, event_id=excluded.event_id",
                (f"legacy-task-markdown:{target_rel(target, 'docs/CODEX_AUTOMATION_TASKS.md')}", source_hash, utc_now(), event_id),
            )
        checkpoint_stream(
            conn,
            stream_id=AUTOMATION_CONTROL_STREAM_ID,
            kind="automation_control",
            state=control,
            event_id=event_id,
        )
        return control


def automation_control_state(target: Path, *, import_legacy_if_empty: bool = True) -> dict[str, Any]:
    target = target.expanduser().resolve()
    with closing(connect(database_path_for_target(target))) as conn:
        return ensure_automation_control_conn(conn, target, import_legacy_if_empty=import_legacy_if_empty)


def write_automation_control_state(
    target: Path,
    updates: Mapping[str, Any],
    *,
    actor_role: str = "runtime",
    event_type: str = "automation.control_updated",
) -> dict[str, Any]:
    target = target.expanduser().resolve()
    with closing(connect(database_path_for_target(target))) as conn:
        current = ensure_automation_control_conn(conn, target, import_legacy_if_empty=False)
        merged = {**current, **dict(updates)}
        if "worker" not in merged:
            merged["worker"] = current.get("worker") if isinstance(current.get("worker"), dict) else {}
        event_id = append_event(
            conn,
            StateEvent(
                stream_id=AUTOMATION_CONTROL_STREAM_ID,
                event_type=event_type,
                actor_role=actor_role,
                phase="automation_control",
                status=_normalize_status(merged.get("status")),
                task_id=AUTOMATION_CONTROL_TASK_ID,
                payload={"updates": dict(updates)},
            ),
        )
        with conn:
            control = _upsert_automation_control_conn(conn, merged, event_id=event_id)
            checkpoint_stream(
                conn,
                stream_id=AUTOMATION_CONTROL_STREAM_ID,
                kind="automation_control",
                state=control,
                event_id=event_id,
            )
            return control


def _control_project_payload(control: Mapping[str, Any]) -> dict[str, Any]:
    payload = control.get("payload") if isinstance(control.get("payload"), Mapping) else {}
    nested = payload.get("payload") if isinstance(payload.get("payload"), Mapping) else {}
    if nested:
        return dict(nested)
    project_keys = {"project_name", "automation_run_mode", "role_profile"}
    return {key: payload[key] for key in project_keys if key in payload}


def _target_setup_payload(target: Path) -> dict[str, Any]:
    intake = read_json_file(existing_or_target_path(target, ".agentic/project_intake.json"))
    dashboard = read_json_file(existing_or_target_path(target, ".agentic/dashboard_state.json"))
    return {**intake, **dashboard}


def _control_run_mode(target: Path, control: Mapping[str, Any]) -> str:
    project_payload = _control_project_payload(control)
    for source in (project_payload, _target_setup_payload(target)):
        mode = str(source.get("automation_run_mode") or "").strip()
        if mode:
            return mode
    return ""


def _is_ticket_campaign_control(target: Path, control: Mapping[str, Any]) -> bool:
    if _control_run_mode(target, control) == "ticket_campaign":
        return True
    horizon = str(control.get("horizon") or "").strip()
    return any(horizon.startswith(prefix) for prefix in TICKET_CAMPAIGN_HORIZONS)


def _project_name_for_control(target: Path, control: Mapping[str, Any]) -> str:
    for source in (_control_project_payload(control), _target_setup_payload(target)):
        name = str(source.get("project_name") or "").strip()
        if name:
            return name
    return target.name or "target"


def _ticket_status_counts(tickets: list[dict[str, Any]]) -> dict[str, int]:
    counts = {status: 0 for status in TICKET_ITEM_STATUSES}
    for item in tickets:
        status = str(item.get("status") or "pending").strip().lower()
        status = status if status in TICKET_ITEM_STATUSES else "pending"
        counts[status] = counts.get(status, 0) + 1
    return counts


def _ticket_count_phrase(count: int, noun: str) -> str:
    suffix = "" if count == 1 else "s"
    return f"{count} {noun}{suffix}"


def _first_ticket_summary(tickets: list[dict[str, Any]], statuses: set[str]) -> str:
    for item in tickets:
        status = str(item.get("status") or "pending").strip().lower()
        if status in statuses:
            summary = _brief_text(item.get("summary") or item.get("id") or "", limit=90)
            if summary:
                return summary
    return ""


def _derive_ticket_campaign_control_updates(
    target: Path,
    control: Mapping[str, Any],
    ticket_data: Mapping[str, Any],
) -> dict[str, Any]:
    tickets = [dict(item) for item in ticket_data.get("tickets", []) if isinstance(item, Mapping)]
    counts = _ticket_status_counts(tickets)
    total = len(tickets)
    done = int(counts.get("done", 0))
    pending = int(counts.get("pending", 0))
    in_progress = int(counts.get("in_progress", 0))
    candidate_done = int(counts.get("candidate_done", 0))
    blocked = int(counts.get("blocked", 0))
    active_or_completed = done + in_progress + candidate_done
    all_done = total > 0 and done == total
    all_remaining_blocked = total > 0 and done + blocked == total and blocked > 0
    project_name = _project_name_for_control(target, control)

    status = _normalize_status(control.get("status"))
    if all_remaining_blocked and not all_done and status != "CRITICAL_STOP":
        status = "ACTIVE_WITH_PENDING_USER_INPUT"
    elif status not in {"CRITICAL_STOP", "BLOCKED_ON_USER", "BLOCKED_ON_ENVIRONMENT"}:
        status = "ACTIVE"

    if total == 0:
        horizon = "T1 Ticket-run readiness"
        bootstrap_status = "pending"
        assessment = "Ticket campaign readiness is pending; the canonical ticket queue is empty."
        milestone = f"Populate or confirm the dashboard-backed ticket queue for `{project_name}`."
        suggested = "Add the bounded ticket scope, confirm ticket-run status and next selection, then start one-ticket campaign runs."
    elif all_done:
        horizon = "T4 Completion report and stop"
        bootstrap_status = "complete"
        assessment = f"Ticket campaign has all {total} ticket(s) done; completion reporting can finalize the run."
        milestone = "Finalize the ticket campaign completion report and stop launching new ticket work."
        suggested = "Run the ticket-run halt/finalize flow, review the local report, and leave remote push or PR creation manual."
    elif all_remaining_blocked:
        horizon = "T4 Completion report and stop"
        bootstrap_status = "bootstrapped"
        assessment = f"Ticket campaign has {done}/{total} ticket(s) done and {blocked} blocked; no runnable tickets remain."
        milestone = "Triage blocked tickets and record the human or environment action needed to resume."
        suggested = "Review blocked ticket details, resolve or update blockers, then rerun ticket selection before launching more work."
    elif candidate_done > 0:
        horizon = "T3 Verification and hardening"
        bootstrap_status = "bootstrapped"
        candidate_summary = _first_ticket_summary(tickets, {"candidate_done"})
        target_text = f": {candidate_summary}" if candidate_summary else ""
        assessment = (
            f"Ticket campaign verification is active; {done}/{total} done, "
            f"{candidate_done} candidate, {pending} pending."
        )
        milestone = f"Verify and harden {_ticket_count_phrase(candidate_done, 'candidate ticket')}{target_text}."
        suggested = "Run the hardener/integrator verification path for candidate tickets, reconcile accepted evidence, then continue one-ticket implementation."
    elif active_or_completed > 0 or blocked > 0:
        horizon = "T2 Ticket implementation"
        bootstrap_status = "bootstrapped"
        active_summary = _first_ticket_summary(tickets, {"in_progress"})
        active_text = f": {active_summary}" if active_summary else ""
        assessment = (
            f"Ticket campaign implementation is underway; {done}/{total} done, "
            f"{in_progress} in progress, {pending} pending, {blocked} blocked."
        )
        if in_progress:
            milestone = f"Finish the active ticket{active_text} and record candidate evidence."
            suggested = "Complete the in-progress ticket, mark it candidate_done with evidence or record a typed blocker, then hand it to verification."
        else:
            milestone = f"Implement the next dependency-ready ticket for `{project_name}`."
            suggested = "Use ticket-run next selection, act on one dependency-ready pending ticket, and record candidate evidence or a blocker."
    else:
        horizon = "T1 Ticket-run readiness"
        bootstrap_status = "pending"
        assessment = f"Ticket campaign queue has {total} pending ticket(s), but no implementation ticket has started yet."
        milestone = f"Complete readiness-only ticket bootstrap for `{project_name}` and confirm one-ticket runs can start."
        suggested = "Confirm ticket-run status and next selection, setup docs, checks, and readiness evidence without implementing tickets."

    previous_horizon = str(control.get("horizon") or "").strip()
    horizon_decision = "advance" if previous_horizon and previous_horizon != horizon else "stay"
    if all_remaining_blocked and not all_done:
        horizon_decision = "defer"

    return {
        "status": status,
        "last_updated": utc_now(),
        "horizon": horizon,
        "horizon_decision": horizon_decision,
        "current_assessment": assessment,
        "best_next_milestone": milestone,
        "suggested_next_task": suggested,
        "bootstrap_status": bootstrap_status,
        "payload": {
            **_control_project_payload(control),
            "automation_run_mode": "ticket_campaign",
            "project_name": project_name,
        },
    }


def _sync_ticket_campaign_automation_control_conn(
    conn: sqlite3.Connection,
    target: Path,
    ticket_data: Mapping[str, Any],
    *,
    actor_role: str,
    causation_id: int,
) -> dict[str, Any] | None:
    control = ensure_automation_control_conn(conn, target, import_legacy_if_empty=True)
    if not _is_ticket_campaign_control(target, control):
        return None
    updates = _derive_ticket_campaign_control_updates(target, control, ticket_data)
    comparable_keys = (
        "status",
        "horizon",
        "horizon_decision",
        "current_assessment",
        "best_next_milestone",
        "suggested_next_task",
        "bootstrap_status",
    )
    if all(str(control.get(key) or "") == str(updates.get(key) or "") for key in comparable_keys):
        return control

    merged = {**control, **updates}
    if isinstance(control.get("worker"), Mapping):
        merged["worker"] = control["worker"]
    event_id = append_event(
        conn,
        StateEvent(
            stream_id=AUTOMATION_CONTROL_STREAM_ID,
            event_type="automation.control_updated",
            actor_role=actor_role or "runtime",
            phase="automation_control",
            status=_normalize_status(merged.get("status")),
            task_id=AUTOMATION_CONTROL_TASK_ID,
            causation_id=causation_id,
            payload={"updates": updates, "source": "ticket_run_reconciler"},
        ),
    )
    control = _upsert_automation_control_conn(conn, merged, event_id=event_id)
    checkpoint_stream(
        conn,
        stream_id=AUTOMATION_CONTROL_STREAM_ID,
        kind="automation_control",
        state=control,
        event_id=event_id,
    )
    return control


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _parse_metadata_block(text: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^\s*-\s+([A-Za-z0-9_-]+):\s*(.*)\s*$", line)
        if match:
            metadata[match.group(1).strip()] = match.group(2).strip()
    return metadata


def _extract_markdown_body(section: str) -> str:
    body_match = re.search(r"^#{3,5}\s+Body\s*$", section, flags=re.IGNORECASE | re.MULTILINE)
    if body_match:
        body_start = body_match.end()
        next_heading = re.search(r"^#{3,5}\s+", section[body_start:], flags=re.MULTILINE)
        body_end = body_start + next_heading.start() if next_heading else len(section)
        return section[body_start:body_end].strip()
    stripped_lines = [
        line
        for line in section.splitlines()
        if not re.match(r"^\s*-\s+[A-Za-z0-9_-]+:\s*", line)
        and not re.match(r"^#{1,6}\s+", line)
        and not line.strip().startswith("```")
    ]
    return "\n".join(stripped_lines).strip()


def _human_summary(metadata: Mapping[str, str], body: str) -> str:
    for key in ("summary", "action_taken", "remaining_followup", "blocker", "reason"):
        value = str(metadata.get(key) or "").strip()
        if value:
            return _brief_text(value, limit=180)
    return _brief_text(body, limit=180) if body else "No message body recorded."


def _parse_human_markdown_records(path: Path, prefixes: tuple[str, ...], kind: str) -> list[dict[str, Any]]:
    text = _read_text(path)
    if not text:
        return []
    prefix_pattern = "|".join(re.escape(prefix) for prefix in prefixes)
    heading_pattern = re.compile(
        rf"^(?P<level>##+)\s+(?P<record_id>(?:{prefix_pattern})-[A-Za-z0-9_.:-]+)(?P<title>[^\n]*)$",
        flags=re.MULTILINE,
    )
    matches = list(heading_pattern.finditer(text))
    records: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        record_id = match.group("record_id").strip()
        if "YYYY" in record_id or record_id.endswith("-001`"):
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        section = text[start:end].strip()
        metadata_boundary = re.search(r"^#{3,5}\s+Body\s*$", section, flags=re.IGNORECASE | re.MULTILINE)
        metadata_text = section[: metadata_boundary.start()] if metadata_boundary else section
        metadata = _parse_metadata_block(metadata_text)
        body = _extract_markdown_body(section)
        raw_status = str(metadata.get("status") or "").strip().lower()
        title = match.group("title").strip(" -:\t")
        records.append(
            {
                "id": record_id,
                "kind": kind,
                "title": title or record_id,
                "status": raw_status or ("unhandled" if kind == "note" else "unknown"),
                "intent": metadata.get("parsed_intent") or metadata.get("intent") or "",
                "request_id": metadata.get("request_id", ""),
                "source_inbox_id": metadata.get("source_inbox_id", ""),
                "channel": metadata.get("channel", ""),
                "from": metadata.get("from", ""),
                "to": metadata.get("to", ""),
                "related": {
                    "request": metadata.get("request_id", ""),
                    "ticket": metadata.get("ticket_id") or metadata.get("related_ticket") or metadata.get("ticket") or "",
                    "run": metadata.get("run_id") or metadata.get("related_run") or "",
                    "file": metadata.get("file") or metadata.get("related_file") or metadata.get("path") or "",
                },
                "timestamp": metadata.get("received_at")
                or metadata.get("created_at")
                or metadata.get("requested_at")
                or metadata.get("resolved_at")
                or metadata.get("timestamp")
                or "",
                "body": body,
                "summary": _human_summary(metadata, body),
                "metadata": metadata,
            }
        )
    return records


def _upsert_human_message_conn(conn: sqlite3.Connection, record: Mapping[str, Any], *, now: str) -> None:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    payload = {
        "title": record.get("title") or record.get("id") or "",
        "timestamp": record.get("timestamp") or "",
        "related": record.get("related") if isinstance(record.get("related"), dict) else {},
        "metadata": metadata,
        "source_file_key": record.get("source_file_key") or "",
    }
    created_at = str(record.get("timestamp") or "") or now
    conn.execute(
        """
        INSERT INTO human_messages(
            message_id, kind, status, intent, request_id, source_inbox_id, channel,
            sender, recipient, summary, body, created_at, updated_at, payload_json
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(message_id) DO UPDATE SET
            kind=excluded.kind,
            status=excluded.status,
            intent=excluded.intent,
            request_id=excluded.request_id,
            source_inbox_id=excluded.source_inbox_id,
            channel=excluded.channel,
            sender=excluded.sender,
            recipient=excluded.recipient,
            summary=excluded.summary,
            body=excluded.body,
            updated_at=excluded.updated_at,
            payload_json=excluded.payload_json
        """,
        (
            str(record.get("id") or ""),
            str(record.get("kind") or "note"),
            str(record.get("status") or "unknown"),
            str(record.get("intent") or ""),
            str(record.get("request_id") or ""),
            str(record.get("source_inbox_id") or ""),
            str(record.get("channel") or ""),
            str(record.get("from") or record.get("sender") or ""),
            str(record.get("to") or record.get("recipient") or ""),
            str(record.get("summary") or ""),
            str(record.get("body") or ""),
            created_at,
            now,
            stable_json(payload),
        ),
    )


def import_legacy_human_markdown(target: Path) -> int:
    """Import old human bridge Markdown once so it stops being a live channel."""

    target = target.expanduser().resolve()
    specs = [
        ("docs/HUMAN_REQUESTS.md", ("HR",), "request"),
        ("docs/HUMAN_INBOX.md", ("INBOX",), "note"),
        ("docs/HUMAN_RESPONSES_ARCHIVE.md", ("HR", "INBOX", "ARCHIVE"), "archive"),
        ("docs/HUMAN_OUTBOX.md", ("OUTBOX",), "outbound"),
    ]
    db_path = database_path_for_target(target)
    imported = 0
    with closing(connect(db_path)) as conn:
        for rel, prefixes, kind in specs:
            path = existing_or_target_path(target, rel)
            if not path.exists():
                continue
            source_key = f"legacy-human-markdown:{rel}"
            if conn.execute(
                "SELECT event_id FROM compatibility_migrations WHERE source_path = ?",
                (source_key,),
            ).fetchone():
                continue
            text = _read_text(path)
            source_hash = sha256_text(text)
            records = _parse_human_markdown_records(path, prefixes, kind)
            now = utc_now()
            with conn:
                for record in records:
                    _upsert_human_message_conn(conn, record, now=now)
            event_id = append_event(
                conn,
                StateEvent(
                    stream_id=HUMAN_STREAM_ID,
                    event_type="compatibility.legacy_human_markdown_imported",
                    actor_role="migration",
                    phase="migration",
                    status="ACTIVE",
                    task_id=HUMAN_TASK_ID,
                    payload={"source_path": str(path), "source_rel": rel, "record_count": len(records)},
                ),
            )
            replace_projection(conn, name=HUMAN_PROJECTION_NAME, payload=human_messages_payload(conn), event_id=event_id)
            with conn:
                conn.execute(
                    "INSERT INTO compatibility_migrations(source_path, source_sha256, imported_at, event_id) "
                    "VALUES(?, ?, ?, ?)",
                    (source_key, source_hash, utc_now(), event_id),
                )
            imported += len(records)
    return imported


def _next_human_message_id(conn: sqlite3.Connection, prefix: str, now: str) -> str:
    date_prefix = now[:10]
    pattern = f"{prefix}-{date_prefix}-%"
    rows = conn.execute(
        "SELECT message_id FROM human_messages WHERE message_id LIKE ?",
        (pattern,),
    ).fetchall()
    highest = 0
    for row in rows:
        match = re.search(r"-(\d{3,})$", str(row["message_id"]))
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{prefix}-{date_prefix}-{highest + 1:03d}"


def record_human_message(
    target: Path,
    *,
    kind: str,
    body: str,
    request_id: str = "",
    intent: str = "",
    status: str = "",
    channel: str = "dashboard",
    sender: str = "dashboard",
    recipient: str = "automation",
    summary: str = "",
    message_id: str = "",
    actor_role: str = "dashboard",
) -> dict[str, Any]:
    target = target.expanduser().resolve()
    normalized_kind = str(kind or "note").strip().lower()
    prefix = {"request": "HR", "note": "INBOX", "archive": "ARCHIVE", "outbound": "OUTBOX"}.get(normalized_kind, "INBOX")
    now = utc_now()
    db_path = database_path_for_target(target)
    with closing(connect(db_path)) as conn:
        resolved_id = message_id or _next_human_message_id(conn, prefix, now)
        resolved_status = status or ("unhandled" if normalized_kind == "note" else "active" if normalized_kind == "request" else "sent")
        record = {
            "id": resolved_id,
            "kind": normalized_kind,
            "status": resolved_status,
            "intent": intent,
            "request_id": request_id,
            "channel": channel,
            "from": sender,
            "to": recipient,
            "timestamp": now,
            "body": body,
            "summary": summary or _brief_text(body, limit=180),
            "metadata": {"created_by": actor_role},
        }
        with conn:
            _upsert_human_message_conn(conn, record, now=now)
        event_id = append_event(
            conn,
            StateEvent(
                stream_id=HUMAN_STREAM_ID,
                event_type="human.message_recorded",
                actor_role=actor_role,
                phase="human_bridge",
                status="ACTIVE",
                task_id=HUMAN_TASK_ID,
                payload={"message_id": resolved_id, "kind": normalized_kind, "status": resolved_status},
            ),
        )
        replace_projection(conn, name=HUMAN_PROJECTION_NAME, payload=human_messages_payload(conn), event_id=event_id)
        return human_message_row(conn, resolved_id) or record


def human_message_row(conn: sqlite3.Connection, message_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM human_messages WHERE message_id = ?", (message_id,)).fetchone()
    if row is None:
        return None
    return _human_row_to_record(row)


def _human_ui_state(kind: str, status: str, archived_inbox_ids: set[str]) -> str:
    normalized = status.lower()
    if kind == "request":
        return "handled" if normalized in HUMAN_ARCHIVE_STATUSES else "pending" if normalized in HUMAN_REQUEST_ACTIVE_STATUSES else "unknown"
    if kind == "note":
        if normalized in HUMAN_ARCHIVE_STATUSES or normalized in {"consumed"}:
            return "consumed"
        return "queued" if normalized in HUMAN_NOTE_ACTIVE_STATUSES else "unknown"
    if kind == "outbound":
        return "sent"
    return "archived"


def _human_row_to_record(row: sqlite3.Row, *, archived_inbox_ids: set[str] | None = None) -> dict[str, Any]:
    archived = archived_inbox_ids or set()
    try:
        payload = json.loads(str(row["payload_json"] or "{}"))
    except json.JSONDecodeError:
        payload = {}
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    kind = str(row["kind"] or "")
    status = str(row["status"] or "unknown")
    return {
        "id": str(row["message_id"]),
        "title": str(payload.get("title") or row["message_id"]),
        "kind": kind,
        "status": status,
        "status_label": status.replace("_", " ").title(),
        "timestamp": str(row["created_at"] or ""),
        "request_id": str(row["request_id"] or ""),
        "source_inbox_id": str(row["source_inbox_id"] or ""),
        "intent": str(row["intent"] or ""),
        "channel": str(row["channel"] or ""),
        "from": str(row["sender"] or ""),
        "to": str(row["recipient"] or ""),
        "related": payload.get("related") if isinstance(payload.get("related"), dict) else {},
        "metadata": metadata,
        "body": str(row["body"] or ""),
        "summary": str(row["summary"] or ""),
        "source_file_key": str(payload.get("source_file_key") or ""),
        "truncated": False,
        "ui_state": "archived" if str(row["message_id"]) in archived else _human_ui_state(kind, status, archived),
    }


def human_messages_payload(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute("SELECT * FROM human_messages ORDER BY updated_at DESC, message_id DESC LIMIT 200").fetchall()
    records = [_human_row_to_record(row) for row in rows]
    return {"schema_version": 1, "records": records, "updated_at": utc_now()}


def human_messages_snapshot(target: Path, *, import_legacy: bool = True) -> dict[str, Any]:
    target = target.expanduser().resolve()
    if import_legacy:
        import_legacy_human_markdown(target)
    with closing(connect(database_path_for_target(target))) as conn:
        rows = conn.execute("SELECT * FROM human_messages ORDER BY created_at ASC, message_id ASC").fetchall()
    raw_records = [_human_row_to_record(row) for row in rows]
    archived_inbox_ids = {
        str(record.get("source_inbox_id") or "")
        for record in raw_records
        if record.get("kind") == "archive" and str(record.get("source_inbox_id") or "")
    }
    records = []
    for record in raw_records:
        record = dict(record)
        record["ui_state"] = "archived" if record["id"] in archived_inbox_ids else _human_ui_state(record["kind"], record["status"], archived_inbox_ids)
        records.append(record)
    requests = [record for record in records if record["kind"] == "request"]
    notes = [record for record in records if record["kind"] == "note"]
    archive = [record for record in records if record["kind"] == "archive"]
    outbox = [record for record in records if record["kind"] == "outbound"]
    active_requests = [record for record in requests if record.get("ui_state") == "pending"]
    active_notes = [record for record in notes if record.get("ui_state") in {"queued", "failed", "unknown"}]
    archive_items = [*archive, *[record for record in requests if record.get("ui_state") == "handled"], *[record for record in notes if record.get("ui_state") in {"archived", "consumed"}]]
    return {
        "requests": requests,
        "active_requests": active_requests,
        "notes": notes,
        "active_notes": active_notes,
        "archive": archive_items,
        "outbox": outbox,
        "counts": {
            "pending_requests": len(active_requests),
            "queued_notes": len([record for record in active_notes if record.get("ui_state") == "queued"]),
            "failed_notes": len([record for record in active_notes if record.get("ui_state") == "failed"]),
            "archived_items": len(archive_items),
            "outbound_records": len(outbox),
        },
        "raw_file_keys": [],
    }


def unhandled_human_message_count(target: Path) -> int:
    snapshot = human_messages_snapshot(target)
    counts = snapshot.get("counts") if isinstance(snapshot.get("counts"), dict) else {}
    return int(counts.get("queued_notes") or 0) + int(counts.get("failed_notes") or 0)


def normalize_ticket_run_data(data: Mapping[str, Any] | None) -> dict[str, Any]:
    normalized = dict(data or {})
    normalized.setdefault("run_id", "ticket-run")
    normalized.setdefault("halt_when_complete", True)
    normalized.setdefault("notify_on_complete", True)
    raw = normalized.get("tickets")
    normalized["tickets"] = [dict(item) for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []
    return normalized


def load_ticket_run_state(target: Path, *, read_only: bool = False) -> dict[str, Any] | None:
    target = target.expanduser().resolve()
    db_path = database_path_for_target(target)
    if read_only and not db_path.exists():
        return None
    connector = connect_readonly if read_only else connect
    with closing(connector(db_path)) as conn:
        projected = load_projection(conn, TICKET_RUN_PROJECTION_NAME)
        if projected:
            return normalize_ticket_run_data(projected)
        run = conn.execute("SELECT * FROM ticket_runs ORDER BY updated_at DESC LIMIT 1").fetchone()
        if run is None:
            return None
        items = conn.execute(
            "SELECT * FROM ticket_items WHERE run_id = ? ORDER BY position ASC, ticket_id ASC",
            (run["run_id"],),
        ).fetchall()
    tickets: list[dict[str, Any]] = []
    for item in items:
        try:
            payload = json.loads(str(item["payload_json"] or "{}"))
        except json.JSONDecodeError:
            payload = {}
        ticket = dict(payload)
        ticket.update(
            {
                "id": str(item["ticket_id"]),
                "summary": str(item["summary"] or ""),
                "status": str(item["status"] or "pending"),
                "blocker": str(item["blocker"] or ""),
            }
        )
        tickets.append(ticket)
    try:
        run_payload = json.loads(str(run["payload_json"] or "{}"))
    except json.JSONDecodeError:
        run_payload = {}
    data = dict(run_payload)
    data.update(
        {
            "run_id": str(run["run_id"]),
            "halt_when_complete": bool(run["halt_when_complete"]),
            "notify_on_complete": bool(run["notify_on_complete"]),
            "tickets": tickets,
        }
    )
    if str(run["report_path"] or ""):
        data["report_path"] = str(run["report_path"])
    return normalize_ticket_run_data(data)


def write_ticket_run_state(
    target: Path,
    data: Mapping[str, Any],
    *,
    actor_role: str = "dashboard",
    event_type: str = "ticket.run_updated",
    source_path: str = "",
) -> dict[str, Any]:
    target = target.expanduser().resolve()
    normalized = normalize_ticket_run_data(data)
    run_id = str(normalized.get("run_id") or "ticket-run")
    tickets = normalized["tickets"]
    now = utc_now()
    status_counts: dict[str, int] = {}
    for item in tickets:
        status = str(item.get("status") or "pending").strip().lower()
        status = status if status in TICKET_ITEM_STATUSES else "pending"
        status_counts[status] = status_counts.get(status, 0) + 1
    run_status = "active"
    if tickets and status_counts.get("done", 0) == len(tickets):
        run_status = "complete"
    elif tickets and status_counts.get("done", 0) + status_counts.get("blocked", 0) == len(tickets):
        run_status = "blocked"

    db_path = database_path_for_target(target)
    with closing(connect(db_path)) as conn:
        event_id = append_event(
            conn,
            StateEvent(
                stream_id=TICKET_STREAM_ID,
                event_type=event_type,
                actor_role=actor_role,
                phase="ticket_run",
                status="ACTIVE" if run_status == "active" else "ACTIVE_WITH_PENDING_USER_INPUT",
                task_id=TICKET_TASK_ID,
                run_id=run_id,
                payload={"run_id": run_id, "ticket_count": len(tickets), "status": run_status, "source_path": source_path},
            ),
        )
        with conn:
            conn.execute(
                """
                INSERT INTO ticket_runs(run_id, status, halt_when_complete, notify_on_complete, ticket_file, report_path, updated_at, payload_json)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status=excluded.status,
                    halt_when_complete=excluded.halt_when_complete,
                    notify_on_complete=excluded.notify_on_complete,
                    ticket_file=excluded.ticket_file,
                    report_path=excluded.report_path,
                    updated_at=excluded.updated_at,
                    payload_json=excluded.payload_json
                """,
                (
                    run_id,
                    run_status,
                    1 if bool(normalized.get("halt_when_complete", True)) else 0,
                    1 if bool(normalized.get("notify_on_complete", True)) else 0,
                    source_path,
                    str(normalized.get("report_path") or ""),
                    now,
                    stable_json({key: value for key, value in normalized.items() if key != "tickets"}),
                ),
            )
            conn.execute("DELETE FROM ticket_items WHERE run_id = ?", (run_id,))
            for index, item in enumerate(tickets):
                ticket_id = str(item.get("id") or f"ticket-{index + 1:03d}").strip()
                status = str(item.get("status") or "pending").strip().lower()
                status = status if status in TICKET_ITEM_STATUSES else "pending"
                conn.execute(
                    """
                    INSERT INTO ticket_items(ticket_id, run_id, position, summary, status, blocker, updated_at, payload_json)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(ticket_id) DO UPDATE SET
                        run_id=excluded.run_id,
                        position=excluded.position,
                        summary=excluded.summary,
                        status=excluded.status,
                        blocker=excluded.blocker,
                        updated_at=excluded.updated_at,
                        payload_json=excluded.payload_json
                    """,
                    (
                        ticket_id,
                        run_id,
                        index,
                        str(item.get("summary") or ""),
                        status,
                        str(item.get("blocker") or ""),
                        now,
                        stable_json(dict(item)),
                    ),
                )
            replace_projection(conn, name=TICKET_RUN_PROJECTION_NAME, payload=normalized, event_id=event_id)
            _sync_ticket_campaign_automation_control_conn(
                conn,
                target,
                normalized,
                actor_role=actor_role,
                causation_id=event_id,
            )
            refresh_task_graph_conn(conn, target)
            if _latest_codebase_graph_snapshot_row(conn) is not None:
                refresh_impact_graph_conn(conn, target)
        return normalized


def ticket_run_state_summary(target: Path) -> dict[str, Any]:
    data = load_ticket_run_state(target)
    if not data:
        return {"active": False, "status": "inactive", "total": 0, "counts": {}}
    counts: dict[str, int] = {}
    tickets = data.get("tickets") if isinstance(data.get("tickets"), list) else []
    for item in tickets:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "pending").strip().lower()
        status = status if status in TICKET_ITEM_STATUSES else "pending"
        counts[status] = counts.get(status, 0) + 1
    total = sum(counts.values())
    status = "active"
    if total and counts.get("done", 0) == total:
        status = "complete"
    elif total and counts.get("done", 0) + counts.get("blocked", 0) == total and counts.get("blocked", 0):
        status = "blocked"
    return {"active": True, "run_id": str(data.get("run_id") or "ticket-run"), "status": status, "total": total, "counts": counts}


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in ORCHESTRATION_TABLES:
        try:
            row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
        except sqlite3.Error:
            counts[table] = -1
        else:
            counts[table] = int(row["count"] if row else 0)
    return counts


def recent_events(conn: sqlite3.Connection, *, limit: int = DEFAULT_EVENT_LIMIT) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT event_id, stream_id, sequence, occurred_at, event_type, actor_role, phase,
               status, task_id, run_id, payload_sha256, prev_hash, event_hash
        FROM events
        ORDER BY event_id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def open_blockers(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT blocker_id, task_id, kind, status, summary, resume_token, updated_at, payload_json "
        "FROM blockers WHERE status NOT IN ('closed', 'resolved', 'superseded') "
        "ORDER BY updated_at DESC LIMIT 20"
    ).fetchall()
    blockers: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        payload = _json_cell(item.pop("payload_json", "{}"), {})
        if isinstance(payload, dict):
            review = payload.get("blocker_review") if isinstance(payload.get("blocker_review"), dict) else {}
            if review:
                item["blocker_review"] = review
        blockers.append(item)
    return blockers


def pending_next_actions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT action_id, task_id, owner_role, kind, status, reason, priority, updated_at "
        "FROM next_actions ORDER BY priority ASC, updated_at DESC LIMIT 20"
    ).fetchall()
    return [dict(row) for row in rows]


def schema_migration_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT version, name, applied_at, checksum, status, details_json
        FROM schema_migrations
        ORDER BY version ASC
        """
    ).fetchall()
    migrations: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        details = _json_cell(item.pop("details_json", "{}"), {})
        item["details"] = details if isinstance(details, dict) else {}
        migrations.append(item)
    return migrations


def _invariant_result(
    name: str,
    ok: bool,
    detail: str,
    *,
    failures: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": "pass" if ok else "fail",
        "ok": bool(ok),
        "detail": detail,
        "failures": (failures or [])[:20],
    }


def _event_hash_material(row: sqlite3.Row, payload_sha: str) -> str:
    return stable_json(
        {
            "stream_id": str(row["stream_id"]),
            "sequence": int(row["sequence"]),
            "occurred_at": str(row["occurred_at"]),
            "event_type": str(row["event_type"]),
            "actor_role": str(row["actor_role"]),
            "actor_id": str(row["actor_id"]),
            "phase": str(row["phase"]),
            "status": str(row["status"]),
            "task_id": str(row["task_id"]),
            "run_id": str(row["run_id"]),
            "causation_id": row["causation_id"],
            "correlation_id": str(row["correlation_id"]),
            "payload_sha256": payload_sha,
            "prev_hash": str(row["prev_hash"] or ""),
        }
    )


def _validate_event_sequences(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT event_id, stream_id, sequence FROM events ORDER BY stream_id ASC, sequence ASC"
    ).fetchall()
    failures: list[dict[str, Any]] = []
    expected_by_stream: dict[str, int] = {}
    for row in rows:
        stream_id = str(row["stream_id"])
        expected = expected_by_stream.get(stream_id, 0) + 1
        sequence = int(row["sequence"])
        if sequence != expected:
            failures.append(
                {
                    "stream_id": stream_id,
                    "event_id": int(row["event_id"]),
                    "expected_sequence": expected,
                    "actual_sequence": sequence,
                }
            )
        expected_by_stream[stream_id] = sequence
    stream_rows = conn.execute(
        """
        SELECT s.stream_id, s.current_sequence, COALESCE(MAX(e.sequence), 0) AS max_sequence
        FROM streams s
        LEFT JOIN events e ON e.stream_id = s.stream_id
        GROUP BY s.stream_id, s.current_sequence
        ORDER BY s.stream_id
        """
    ).fetchall()
    for row in stream_rows:
        current_sequence = int(row["current_sequence"])
        max_sequence = int(row["max_sequence"])
        if current_sequence != max_sequence:
            failures.append(
                {
                    "stream_id": str(row["stream_id"]),
                    "expected_current_sequence": max_sequence,
                    "actual_current_sequence": current_sequence,
                }
            )
    return _invariant_result(
        "events.sequence_contiguous",
        not failures,
        "Event sequences are contiguous per stream."
        if not failures
        else f"Event sequence gaps or stream cursor mismatches found: {len(failures)}.",
        failures=failures,
    )


def _validate_event_hash_chain(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT event_id, stream_id, sequence, occurred_at, event_type, actor_role, actor_id,
               phase, status, task_id, run_id, causation_id, correlation_id,
               payload_json, payload_sha256, prev_hash, event_hash
        FROM events
        ORDER BY stream_id ASC, sequence ASC
        """
    ).fetchall()
    failures: list[dict[str, Any]] = []
    previous_hash_by_stream: dict[str, str] = {}
    for row in rows:
        stream_id = str(row["stream_id"])
        event_id = int(row["event_id"])
        payload_sha = sha256_text(str(row["payload_json"] or ""))
        stored_payload_sha = str(row["payload_sha256"] or "")
        if stored_payload_sha != payload_sha:
            failures.append(
                {
                    "stream_id": stream_id,
                    "event_id": event_id,
                    "field": "payload_sha256",
                    "expected": payload_sha,
                    "actual": stored_payload_sha,
                }
            )
        expected_prev_hash = previous_hash_by_stream.get(stream_id, "")
        actual_prev_hash = str(row["prev_hash"] or "")
        if actual_prev_hash != expected_prev_hash:
            failures.append(
                {
                    "stream_id": stream_id,
                    "event_id": event_id,
                    "field": "prev_hash",
                    "expected": expected_prev_hash,
                    "actual": actual_prev_hash,
                }
            )
        expected_event_hash = sha256_text(_event_hash_material(row, payload_sha))
        actual_event_hash = str(row["event_hash"] or "")
        if actual_event_hash != expected_event_hash:
            failures.append(
                {
                    "stream_id": stream_id,
                    "event_id": event_id,
                    "field": "event_hash",
                    "expected": expected_event_hash,
                    "actual": actual_event_hash,
                }
            )
        previous_hash_by_stream[stream_id] = actual_event_hash
    return _invariant_result(
        "events.hash_chain",
        not failures,
        "Event payload hashes, prev_hash links, and event_hash values are valid."
        if not failures
        else f"Event hash-chain violations found: {len(failures)}.",
        failures=failures,
    )


def _validate_projection_event_refs(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT p.name, p.event_id
        FROM projections p
        LEFT JOIN events e ON e.event_id = p.event_id
        WHERE p.event_id IS NOT NULL AND e.event_id IS NULL
        ORDER BY p.name
        """
    ).fetchall()
    failures = [{"projection": str(row["name"]), "event_id": int(row["event_id"])} for row in rows]
    return _invariant_result(
        "projections.event_id_exists",
        not failures,
        "Projection event references all point at existing events."
        if not failures
        else f"Projection event references are missing events: {len(failures)}.",
        failures=failures,
    )


def _expected_owner_roles_for_stage(stage: str) -> set[str]:
    expected = STAGE_TO_OWNER_ROLE.get(stage)
    roles = {expected} if expected else set()
    if stage == "implementation":
        roles.add("single_lane")
    if stage == "handoff":
        roles.add("conveyor")
    return roles


def _validate_current_work_item_owner(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT work_item_id, current_stage, owner_role
        FROM conveyor_work_items
        WHERE work_item_id = ?
        """,
        (CONVEYOR_WORK_ITEM_ID,),
    ).fetchone()
    if row is None:
        return _invariant_result(
            "conveyor.current_stage_owner",
            False,
            "Default conveyor work item is missing.",
            failures=[{"work_item_id": CONVEYOR_WORK_ITEM_ID}],
        )
    stage = str(row["current_stage"] or "")
    owner_role = str(row["owner_role"] or "")
    expected_roles = _expected_owner_roles_for_stage(stage)
    ok = bool(expected_roles) and owner_role in expected_roles
    return _invariant_result(
        "conveyor.current_stage_owner",
        ok,
        f"Current conveyor stage {stage} is owned by {owner_role}."
        if ok
        else f"Current conveyor stage {stage} has owner {owner_role}; expected one of {sorted(expected_roles)}.",
        failures=[]
        if ok
        else [
            {
                "work_item_id": str(row["work_item_id"]),
                "current_stage": stage,
                "owner_role": owner_role,
                "expected_owner_roles": sorted(expected_roles),
            }
        ],
    )


def _has_actionable_payload(payload_json: Any) -> bool:
    payload = _json_cell(payload_json, {})
    if not isinstance(payload, dict) or not payload:
        return False
    for key in ("summary", "reason", "detail", "recommended_action", "next_action", "question", "context"):
        if str(payload.get(key) or "").strip():
            return True
    return bool(payload)


def _validate_open_blockers_and_escalations(conn: sqlite3.Connection) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    blocker_rows = conn.execute(
        """
        SELECT blocker_id, kind, status, summary, resume_token, payload_json
        FROM blockers
        WHERE status NOT IN ('closed', 'resolved', 'superseded')
        ORDER BY updated_at DESC
        """
    ).fetchall()
    for row in blocker_rows:
        has_context = bool(str(row["resume_token"] or "").strip()) or bool(str(row["summary"] or "").strip())
        has_context = has_context or _has_actionable_payload(row["payload_json"])
        if not has_context:
            failures.append(
                {
                    "table": "blockers",
                    "id": str(row["blocker_id"]),
                    "kind": str(row["kind"]),
                    "status": str(row["status"]),
                }
            )
    escalation_rows = conn.execute(
        """
        SELECT escalation_id, kind, status, question, options_json, resume_token, payload_json
        FROM escalations
        WHERE status NOT IN ('closed', 'resolved', 'superseded')
        ORDER BY updated_at DESC
        """
    ).fetchall()
    for row in escalation_rows:
        options = _json_cell(row["options_json"], [])
        has_options = isinstance(options, list) and bool(options)
        has_context = (
            bool(str(row["resume_token"] or "").strip())
            or bool(str(row["question"] or "").strip())
            or has_options
            or _has_actionable_payload(row["payload_json"])
        )
        if not has_context:
            failures.append(
                {
                    "table": "escalations",
                    "id": str(row["escalation_id"]),
                    "kind": str(row["kind"]),
                    "status": str(row["status"]),
                }
            )
    return _invariant_result(
        "open_items.actionable_context",
        not failures,
        "Open blockers and escalations have resume tokens or actionable context."
        if not failures
        else f"Open blockers/escalations without actionable context found: {len(failures)}.",
        failures=failures,
    )


def _validation_receipt_has_reason(payload_json: Any) -> bool:
    payload = _json_cell(payload_json, {})
    if not isinstance(payload, dict):
        return False
    for key in ("reason", "explicit_reason", "summary", "detail", "root_cause", "failure_reason"):
        if str(payload.get(key) or "").strip():
            return True
    record = payload.get("record")
    if isinstance(record, dict):
        return any(str(record.get(key) or "").strip() for key in ("detail", "root_cause", "reason", "summary"))
    return False


def _validate_terminal_validation_receipts(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT receipt_id, status, started_at, finished_at, payload_json
        FROM validation_receipts
        WHERE lower(status) IN ('pass', 'passed', 'fail', 'failed')
        ORDER BY receipt_id
        """
    ).fetchall()
    failures: list[dict[str, Any]] = []
    for row in rows:
        has_timestamps = bool(str(row["started_at"] or "").strip()) and bool(str(row["finished_at"] or "").strip())
        if not has_timestamps and not _validation_receipt_has_reason(row["payload_json"]):
            failures.append(
                {
                    "receipt_id": str(row["receipt_id"]),
                    "status": str(row["status"]),
                    "started_at": str(row["started_at"] or ""),
                    "finished_at": str(row["finished_at"] or ""),
                }
            )
    return _invariant_result(
        "validation_receipts.terminal_evidence",
        not failures,
        "Terminal validation receipts have timestamps or an explicit reason."
        if not failures
        else f"Terminal validation receipts without timestamps or explicit reason found: {len(failures)}.",
        failures=failures,
    )


def state_invariant_results(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        _validate_event_sequences(conn),
        _validate_event_hash_chain(conn),
        _validate_projection_event_refs(conn),
        _validate_current_work_item_owner(conn),
        _validate_open_blockers_and_escalations(conn),
        _validate_terminal_validation_receipts(conn),
    ]


def state_health_summary(invariant_results: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [item for item in invariant_results if not item.get("ok")]
    return {
        "status": "pass" if not failed else "fail",
        "checked_at": utc_now(),
        "passed": len(invariant_results) - len(failed),
        "failed": len(failed),
        "invariant_count": len(invariant_results),
        "failed_invariants": [str(item.get("name") or "unknown") for item in failed],
    }


def validation_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    receipt_rows = conn.execute(
        "SELECT status, COUNT(*) AS count FROM validation_receipts GROUP BY status ORDER BY status"
    ).fetchall()
    receipt_latest = conn.execute(
        "SELECT receipt_id AS validation_id, work_item_id AS task_id, run_id, kind, command, status, finished_at "
        "FROM validation_receipts ORDER BY COALESCE(NULLIF(finished_at, ''), started_at) DESC LIMIT 10"
    ).fetchall()
    if receipt_rows or receipt_latest:
        return {
            "counts": {str(row["status"]): int(row["count"]) for row in receipt_rows},
            "latest": [dict(row) for row in receipt_latest],
            "source": "validation_receipts",
        }
    rows = conn.execute(
        "SELECT status, COUNT(*) AS count FROM validations GROUP BY status ORDER BY status"
    ).fetchall()
    latest = conn.execute(
        "SELECT validation_id, task_id, run_id, kind, command, status, finished_at "
        "FROM validations ORDER BY COALESCE(NULLIF(finished_at, ''), started_at) DESC LIMIT 10"
    ).fetchall()
    return {
        "counts": {str(row["status"]): int(row["count"]) for row in rows},
        "latest": [dict(row) for row in latest],
        "source": "validations",
    }


def sqlite_integrity(conn: sqlite3.Connection) -> str:
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error as exc:
        return f"error: {exc}"
    return str(row[0]) if row else "unknown"


def journal_mode(conn: sqlite3.Connection) -> str:
    try:
        row = conn.execute("PRAGMA journal_mode").fetchone()
    except sqlite3.Error:
        return "unknown"
    return str(row[0]) if row else "unknown"


def state_snapshot(target: Path, *, event_limit: int = DEFAULT_EVENT_LIMIT) -> dict[str, Any]:
    target = target.expanduser().resolve()
    projection_path = conveyor_projection_path_for_target(target)
    state = load_conveyor_state(projection_path)
    runner_projection_path = runner_projection_path_for_target(target)
    runner_state = load_runner_state(runner_projection_path)
    human_state = human_messages_snapshot(target, import_legacy=True)
    ticket_state = ticket_run_state_summary(target)
    db_path = database_path_for_target(target)
    with closing(connect(db_path)) as conn:
        automation_control = ensure_automation_control_conn(conn, target, import_legacy_if_empty=True)
        state = normalize_conveyor_state({**state, "status": automation_control.get("status") or state.get("status") or "ACTIVE"})
        capability = refresh_capability_manifest_conn(conn, target, actor_role="dashboard", append_event_first=True)
        codebase_graph = ensure_codebase_graph_conn(conn, target, capability=capability)
        machine = apply_conveyor_machine_read_models(
            conn,
            target,
            state,
            event_id=None,
            event_type="state.snapshot",
        )
        state = normalize_conveyor_state({**state, "state_machine": machine})
        replace_projection(conn, name=CONVEYOR_MACHINE_PROJECTION_NAME, payload=machine, event_id=None)
        task_graph = refresh_task_graph_conn(conn, target)
        task_graph_readiness = task_graph_read_model(conn)
        impact_graph = refresh_impact_graph_conn(conn, target)
        impact_read_model = impact_graph_read_model(conn, target)
        expire_stale_leases_conn(conn)
        active_leases = active_resource_leases_conn(conn)
        conflicting_leases = current_conflicting_resource_leases_conn(conn)
        lease_suggestions = lease_suggestions_for_next_action_conn(conn, target)
        scheduler_decision = latest_scheduler_decision_conn(conn)
        last_event = conn.execute(
            """
            SELECT event_id, stream_id, sequence, occurred_at, event_type, actor_role,
                   phase, status, task_id, run_id, event_hash
            FROM events
            ORDER BY event_id DESC
            LIMIT 1
            """
        ).fetchone()
        checkpoint = conn.execute(
            "SELECT checkpoint_id, stream_id, sequence, kind, created_at, state_sha256 "
            "FROM checkpoints ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        projection_row = conn.execute(
            "SELECT name, updated_at, payload_sha256, event_id FROM projections WHERE name = ?",
            (CONVEYOR_PROJECTION_NAME,),
        ).fetchone()
        runner_projection_row = conn.execute(
            "SELECT name, updated_at, payload_sha256, event_id FROM projections WHERE name = ?",
            (RUNNER_PROJECTION_NAME,),
        ).fetchone()
        machine_projection_row = conn.execute(
            "SELECT name, updated_at, payload_sha256, event_id FROM projections WHERE name = ?",
            (CONVEYOR_MACHINE_PROJECTION_NAME,),
        ).fetchone()
        capability_projection_row = conn.execute(
            "SELECT name, updated_at, payload_sha256, event_id FROM projections WHERE name = ?",
            (CAPABILITY_PROJECTION_NAME,),
        ).fetchone()
        automation_projection_row = conn.execute(
            "SELECT name, updated_at, payload_sha256, event_id FROM projections WHERE name = ?",
            (AUTOMATION_CONTROL_PROJECTION_NAME,),
        ).fetchone()
        counts = table_counts(conn)
        projection_payload = {
            "name": CONVEYOR_PROJECTION_NAME,
            "path": str(projection_path),
            "exists": projection_path.exists(),
            "updated_at": projection_row["updated_at"] if projection_row else "",
            "payload_sha256": projection_row["payload_sha256"] if projection_row else "",
            "event_id": projection_row["event_id"] if projection_row else None,
        }
        runner_projection_payload = {
            "name": RUNNER_PROJECTION_NAME,
            "path": str(runner_projection_path),
            "exists": runner_projection_path.exists(),
            "updated_at": runner_projection_row["updated_at"] if runner_projection_row else "",
            "payload_sha256": runner_projection_row["payload_sha256"] if runner_projection_row else "",
            "event_id": runner_projection_row["event_id"] if runner_projection_row else None,
        }
        machine_projection_payload = {
            "name": CONVEYOR_MACHINE_PROJECTION_NAME,
            "path": str(db_path),
            "exists": bool(machine_projection_row),
            "updated_at": machine_projection_row["updated_at"] if machine_projection_row else "",
            "payload_sha256": machine_projection_row["payload_sha256"] if machine_projection_row else "",
            "event_id": machine_projection_row["event_id"] if machine_projection_row else None,
        }
        capability_projection_payload = {
            "name": CAPABILITY_PROJECTION_NAME,
            "path": str(db_path),
            "exists": bool(capability_projection_row),
            "updated_at": capability_projection_row["updated_at"] if capability_projection_row else "",
            "payload_sha256": capability_projection_row["payload_sha256"] if capability_projection_row else "",
            "event_id": capability_projection_row["event_id"] if capability_projection_row else None,
        }
        automation_projection_payload = {
            "name": AUTOMATION_CONTROL_PROJECTION_NAME,
            "path": str(db_path),
            "exists": bool(automation_projection_row),
            "updated_at": automation_projection_row["updated_at"] if automation_projection_row else "",
            "payload_sha256": automation_projection_row["payload_sha256"] if automation_projection_row else "",
            "event_id": automation_projection_row["event_id"] if automation_projection_row else None,
        }
        schema_migrations = schema_migration_rows(conn)
        invariant_results = state_invariant_results(conn)
        health_summary = state_health_summary(invariant_results)
        base_ready = counts.get("events", 0) >= 1 and bool(projection_row)
        stale_context_warning = str(impact_read_model.get("stale_context_warning") or "")
        stale_graph_warnings: list[dict[str, Any]] = []
        stale_node_count = int(codebase_graph.get("stale_node_count") or 0) if isinstance(codebase_graph, dict) else 0
        if stale_node_count:
            stale_graph_warnings.append(
                {
                    "kind": "codebase_stale_nodes",
                    "severity": "warn",
                    "count": stale_node_count,
                    "source": "codebase_graph",
                    "message": f"{stale_node_count} indexed codebase node{' is' if stale_node_count == 1 else 's are'} stale.",
                }
            )
        if stale_context_warning:
            stale_graph_warnings.append(
                {
                    "kind": "stale_context",
                    "severity": "warn",
                    "count": 0,
                    "source": "impact_graph",
                    "message": stale_context_warning,
                }
            )
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "authority": "sqlite",
            "status": "ok" if base_ready and health_summary["status"] == "pass" else "invalid" if base_ready else "initializing",
            "database": {
                "path": str(db_path),
                "exists": db_path.exists(),
                "sqlite_version": sqlite3.sqlite_version,
                "user_version": sqlite_user_version(conn),
                "journal_mode": journal_mode(conn),
                "integrity_check": sqlite_integrity(conn),
                "application_id": STATE_APPLICATION_ID,
            },
            "projection": projection_payload,
            "projections": {
                "conveyor": projection_payload,
                "runner": runner_projection_payload,
                "machine": machine_projection_payload,
                "capabilities": capability_projection_payload,
                "automation_control": automation_projection_payload,
            },
            "contract": {
                "tables": list(ORCHESTRATION_TABLES),
                "status_model": list(STATUS_MODEL),
                "conveyor_stages": list(CONVEYOR_STAGES),
                "canonical_runtime_state": "SQLite append-only events + typed conveyor state machine projections",
                "compatibility_surfaces": [
                    "canonical Markdown state brief",
                    "conveyor/runner JSON projections",
                    "Markdown handoffs",
                    "JSON Schema exports",
                ],
            },
            "counts": counts,
            "schema_migrations": schema_migrations,
            "invariant_results": invariant_results,
            "state_health_summary": health_summary,
            "last_event": dict(last_event) if last_event else {},
            "last_checkpoint": dict(checkpoint) if checkpoint else {},
            "recent_events": recent_events(conn, limit=event_limit),
            "open_blockers": open_blockers(conn),
            "next_actions": pending_next_actions(conn),
            "validations": validation_summary(conn),
            "conveyor_state": state,
            "conveyor_machine": machine,
            "automation_control": automation_control,
            "capability_manifest": capability,
            "codebase_graph_summary": codebase_graph,
            "latest_graph_snapshot": codebase_graph.get("latest_graph_snapshot") if isinstance(codebase_graph, dict) else {},
            "graph_refresh_mode": str(codebase_graph.get("graph_refresh_mode") or "") if isinstance(codebase_graph, dict) else "",
            "graph_refresh_reason": str(codebase_graph.get("graph_refresh_reason") or "") if isinstance(codebase_graph, dict) else "",
            "graph_inventory_digest": str(codebase_graph.get("graph_inventory_digest") or "") if isinstance(codebase_graph, dict) else "",
            "graph_inventory_changed": bool(codebase_graph.get("graph_inventory_changed")) if isinstance(codebase_graph, dict) else False,
            "graph_inventory_added_count": int(codebase_graph.get("graph_inventory_added_count") or 0) if isinstance(codebase_graph, dict) else 0,
            "graph_inventory_deleted_count": int(codebase_graph.get("graph_inventory_deleted_count") or 0) if isinstance(codebase_graph, dict) else 0,
            "graph_inventory_structural_count": int(codebase_graph.get("graph_inventory_structural_count") or 0) if isinstance(codebase_graph, dict) else 0,
            "stale_node_count": stale_node_count,
            "indexed_file_count": int(codebase_graph.get("indexed_file_count") or 0) if isinstance(codebase_graph, dict) else 0,
            "command_node_count": int(codebase_graph.get("command_node_count") or 0) if isinstance(codebase_graph, dict) else 0,
            "test_node_count": int(codebase_graph.get("test_node_count") or 0) if isinstance(codebase_graph, dict) else 0,
            "task_graph_summary": task_graph,
            "ready_task_nodes": task_graph_readiness.get("ready_task_nodes", []),
            "blocked_task_nodes": task_graph_readiness.get("blocked_task_nodes", []),
            "dependency_cycles": task_graph_readiness.get("dependency_cycles", []),
            "impact_graph_summary": impact_graph,
            "active_task_code_impacts": impact_read_model.get("active_task_code_impacts", []),
            "context_pack_preview": impact_read_model.get("context_pack_preview", {}),
            "top_impacted_nodes": impact_read_model.get("top_impacted_nodes", []),
            "stale_context_warning": stale_context_warning,
            "stale_graph_warnings": stale_graph_warnings,
            "active_leases": active_leases,
            "conflicting_leases": conflicting_leases,
            "lease_suggestions_for_next_action": lease_suggestions,
            "scheduling_candidates": scheduler_decision.get("scheduling_candidates", []),
            "selected_candidate": scheduler_decision.get("selected_candidate", {}),
            "skipped_candidates": scheduler_decision.get("skipped_candidates", []),
            "selected_scheduler_candidate": scheduler_decision.get("selected_scheduler_candidate")
            or scheduler_decision.get("selected_candidate", {}),
            "skipped_scheduler_candidates": scheduler_decision.get("skipped_scheduler_candidates")
            or scheduler_decision.get("skipped_candidates", []),
            "scheduler_fallback_used": bool(scheduler_decision.get("scheduler_fallback_used")),
            "graph_signals_used": scheduler_decision.get("graph_signals_used", {}),
            "lease_conflicts_considered": scheduler_decision.get("lease_conflicts_considered", []),
            "legacy_result": scheduler_decision.get("legacy_result", {}),
            "runner_state": runner_state,
            "human_messages": human_state,
            "ticket_run": ticket_state,
        }


def _brief_text(value: Any, *, limit: int = BRIEF_TEXT_LIMIT) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        return text[: max(0, limit - 3)].rstrip() + "..."
    return text


def _display_path(target: Path, value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    path = Path(text).expanduser()
    if path.is_absolute():
        try:
            return path.resolve().relative_to(target).as_posix()
        except (OSError, ValueError):
            return f"<redacted:absolute>/{path.name}"
    return normalize_path_for_brief(text)


def normalize_path_for_brief(value: str) -> str:
    rel = str(value).strip().replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    return rel.lstrip("/")


def _brief_bool(value: Any) -> str:
    return "yes" if bool(value) else "no"


def _brief_sha(value: Any) -> str:
    text = str(value or "")
    return text[:12] if text else ""


def _format_key_values(values: Mapping[str, Any]) -> str:
    rendered = []
    for key, value in values.items():
        if value is None or value == "":
            continue
        rendered.append(f"{key}={_brief_text(value)}")
    return ", ".join(rendered) if rendered else "none"


def render_canonical_state_brief(snapshot: Mapping[str, Any], *, target: Path) -> str:
    """Render a bounded Markdown brief from ``state_snapshot`` for Codex agents."""

    target = target.expanduser().resolve()
    generated_at = utc_now()
    database = snapshot.get("database") if isinstance(snapshot.get("database"), dict) else {}
    conveyor_state = snapshot.get("conveyor_state") if isinstance(snapshot.get("conveyor_state"), dict) else {}
    conveyor_machine = snapshot.get("conveyor_machine") if isinstance(snapshot.get("conveyor_machine"), dict) else {}
    machine_work_item = conveyor_machine.get("work_item") if isinstance(conveyor_machine.get("work_item"), dict) else {}
    capability_manifest = snapshot.get("capability_manifest") if isinstance(snapshot.get("capability_manifest"), dict) else {}
    capability_languages = capability_manifest.get("languages") if isinstance(capability_manifest.get("languages"), dict) else {}
    graph_summary = snapshot.get("codebase_graph_summary") if isinstance(snapshot.get("codebase_graph_summary"), dict) else {}
    latest_graph = snapshot.get("latest_graph_snapshot") if isinstance(snapshot.get("latest_graph_snapshot"), dict) else {}
    impact_summary = snapshot.get("impact_graph_summary") if isinstance(snapshot.get("impact_graph_summary"), dict) else {}
    impact_latest = impact_summary.get("latest_graph_snapshot") if isinstance(impact_summary.get("latest_graph_snapshot"), dict) else {}
    context_pack = snapshot.get("context_pack_preview") if isinstance(snapshot.get("context_pack_preview"), dict) else {}
    stale_context_warning = str(snapshot.get("stale_context_warning") or context_pack.get("stale_context_warning") or "")
    selected_scheduler = (
        snapshot.get("selected_scheduler_candidate")
        if isinstance(snapshot.get("selected_scheduler_candidate"), dict)
        else snapshot.get("selected_candidate")
        if isinstance(snapshot.get("selected_candidate"), dict)
        else {}
    )
    skipped_scheduler = (
        snapshot.get("skipped_scheduler_candidates")
        if isinstance(snapshot.get("skipped_scheduler_candidates"), list)
        else snapshot.get("skipped_candidates")
        if isinstance(snapshot.get("skipped_candidates"), list)
        else []
    )
    runner_state = snapshot.get("runner_state") if isinstance(snapshot.get("runner_state"), dict) else {}
    automation_control = snapshot.get("automation_control") if isinstance(snapshot.get("automation_control"), dict) else {}
    human_state = snapshot.get("human_messages") if isinstance(snapshot.get("human_messages"), dict) else {}
    human_counts = human_state.get("counts") if isinstance(human_state.get("counts"), dict) else {}
    ticket_state = snapshot.get("ticket_run") if isinstance(snapshot.get("ticket_run"), dict) else {}
    last_event = snapshot.get("last_event") if isinstance(snapshot.get("last_event"), dict) else {}
    last_checkpoint = snapshot.get("last_checkpoint") if isinstance(snapshot.get("last_checkpoint"), dict) else {}
    validations = snapshot.get("validations") if isinstance(snapshot.get("validations"), dict) else {}
    validation_counts = validations.get("counts") if isinstance(validations.get("counts"), dict) else {}
    validation_latest = validations.get("latest") if isinstance(validations.get("latest"), list) else []
    active_role = conveyor_state.get("active_role_run") if isinstance(conveyor_state.get("active_role_run"), dict) else {}
    last_role = conveyor_state.get("last_active_role_run") if isinstance(conveyor_state.get("last_active_role_run"), dict) else {}
    last_decision = conveyor_state.get("last_decision") if isinstance(conveyor_state.get("last_decision"), dict) else {}
    decision_queue = conveyor_state.get("decision_queue") if isinstance(conveyor_state.get("decision_queue"), list) else []
    projections = snapshot.get("projections") if isinstance(snapshot.get("projections"), dict) else {}
    projection_items = [
        ("conveyor", projections.get("conveyor") if isinstance(projections.get("conveyor"), dict) else snapshot.get("projection")),
        ("runner", projections.get("runner") if isinstance(projections.get("runner"), dict) else {}),
    ]

    status = str(automation_control.get("status") or last_event.get("status") or conveyor_state.get("status") or "ACTIVE")
    if status not in STATUS_MODEL:
        status = "ACTIVE" if str(snapshot.get("status") or "") == "ok" else "ACTIVE_WITH_PENDING_USER_INPUT"

    lines = [
        "# Canonical State Brief",
        "",
        f"- generated_at: {generated_at}",
        "- authority: SQLite orchestration state is canonical; this file is a generated view for agents.",
        f"- database: `{_display_path(target, database.get('path'))}`",
        f"- database_exists: {_brief_bool(database.get('exists'))}",
        f"- sqlite_integrity: {_brief_text(database.get('integrity_check') or 'unknown')}",
        f"- runtime_status: `{status}`",
        f"- current_horizon: {_brief_text(automation_control.get('horizon') or 'unknown')}",
        f"- horizon_decision: {_brief_text(automation_control.get('horizon_decision') or 'unknown')}",
        f"- best_next_milestone: {_brief_text(automation_control.get('best_next_milestone') or 'No milestone recorded yet.')}",
        f"- suggested_next_task: {_brief_text(automation_control.get('suggested_next_task') or 'No sprint task recorded yet.')}",
        "- agent_rule: read this brief at run start; do not inspect or edit the SQLite database manually.",
        "- reconciliation_rule: if Markdown or JSON projections disagree with this brief, regenerate/reconcile through Diffmogger typed state APIs.",
        "",
        "## Last State Change",
        "",
        f"- event: {_format_key_values({'id': last_event.get('event_id'), 'type': last_event.get('event_type'), 'role': last_event.get('actor_role'), 'phase': last_event.get('phase'), 'status': last_event.get('status'), 'at': last_event.get('occurred_at'), 'hash': _brief_sha(last_event.get('event_hash'))})}",
        f"- checkpoint: {_format_key_values({'id': last_checkpoint.get('checkpoint_id'), 'kind': last_checkpoint.get('kind'), 'sequence': last_checkpoint.get('sequence'), 'at': last_checkpoint.get('created_at'), 'sha': _brief_sha(last_checkpoint.get('state_sha256'))})}",
        "",
        "## Runner And Conveyor",
        "",
        f"- conveyor_stage: {_format_key_values({'stage': machine_work_item.get('current_stage') or conveyor_machine.get('current_stage'), 'stage_status': machine_work_item.get('stage_status') or conveyor_machine.get('stage_status'), 'owner': machine_work_item.get('owner_role') or conveyor_machine.get('owner_role'), 'validation': machine_work_item.get('validation_status'), 'continuation': machine_work_item.get('continuation_token')})}",
        f"- repo_capabilities: {_format_key_values({'primary_language': capability_languages.get('primary'), 'manifest_version': capability_manifest.get('version'), 'digest': _brief_sha(capability_manifest.get('digest')), 'commands': len(capability_manifest.get('commands') if isinstance(capability_manifest.get('commands'), list) else [])})}",
        f"- codebase_graph: {_format_key_values({'namespace': graph_summary.get('graph_namespace'), 'digest': _brief_sha(latest_graph.get('digest')), 'files': graph_summary.get('indexed_file_count'), 'commands': graph_summary.get('command_node_count'), 'tests': graph_summary.get('test_node_count'), 'stale': graph_summary.get('stale_node_count')})}",
        f"- impact_graph: {_format_key_values({'namespace': impact_summary.get('graph_namespace'), 'digest': _brief_sha(impact_latest.get('digest')), 'edges': impact_latest.get('edge_count'), 'stale': impact_summary.get('stale_node_count')})}",
        f"- conveyor_cycles: {int(conveyor_state.get('cycles') or 0)}",
        f"- last_decision: {_format_key_values({'role': last_decision.get('role') or 'idle', 'reason': last_decision.get('reason'), 'decided_at': last_decision.get('decided_at')})}",
        f"- active_role: {_format_key_values({'role': active_role.get('role'), 'run_id': active_role.get('run_id'), 'status': active_role.get('status'), 'started_at': active_role.get('started_at'), 'reason': active_role.get('reason')})}",
        f"- last_role_run: {_format_key_values({'role': last_role.get('role'), 'run_id': last_role.get('run_id'), 'status': last_role.get('status'), 'exit_code': last_role.get('exit_code'), 'finished_at': last_role.get('finished_at')})}",
        f"- runner: {_format_key_values({'state': runner_state.get('state'), 'pid': runner_state.get('pid'), 'run_id': runner_state.get('run_id'), 'started_at': runner_state.get('started_at'), 'updated_at': runner_state.get('updated_at')})}",
        f"- human_messages: {_format_key_values({'pending_requests': human_counts.get('pending_requests'), 'queued_notes': human_counts.get('queued_notes'), 'failed_notes': human_counts.get('failed_notes'), 'outbound_records': human_counts.get('outbound_records')})}",
        f"- ticket_run: {_format_key_values({'status': ticket_state.get('status'), 'run_id': ticket_state.get('run_id'), 'total': ticket_state.get('total'), 'counts': stable_json(ticket_state.get('counts')) if isinstance(ticket_state.get('counts'), dict) else ''})}",
        "",
        "## Graph Context For Next Action",
        "",
    ]
    selected_task = context_pack.get("selected_task") if isinstance(context_pack.get("selected_task"), dict) else {}
    lines.append(
        f"- selected_task: {_format_key_values({'kind': selected_task.get('kind'), 'id': selected_task.get('id'), 'status': selected_task.get('status'), 'summary': selected_task.get('summary')})}"
    )
    if stale_context_warning:
        lines.append(f"- stale_warning: {_brief_text(stale_context_warning)}")
    policy_notes = context_pack.get("policy_notes") if isinstance(context_pack.get("policy_notes"), list) else []
    if policy_notes:
        lines.append(f"- policy: {_brief_text('; '.join(str(item) for item in policy_notes), limit=220)}")
    context_items = context_pack.get("items") if isinstance(context_pack.get("items"), list) else []
    if context_items:
        for item in context_items[:BRIEF_ITEM_LIMIT]:
            if not isinstance(item, dict):
                continue
            label = item.get("path") or item.get("name") or item.get("node_id")
            lines.append(
                f"- {str(item.get('category') or item.get('kind') or 'context')}: `{_brief_text(label, limit=140)}` confidence={float(item.get('confidence') or 0):.2f} reason={_brief_text(item.get('reason'), limit=160)} stale={_brief_bool(item.get('is_stale'))}"
            )
    else:
        lines.append("- none")
    lines.extend([
        "",
        "## Scheduler Decision",
        "",
    ])
    if selected_scheduler:
        selected_context = (
            selected_scheduler.get("context_pack_preview")
            if isinstance(selected_scheduler.get("context_pack_preview"), dict)
            else {}
        )
        selected_context_items = (
            selected_context.get("items") if isinstance(selected_context.get("items"), list) else []
        )
        selected_leases = (
            selected_scheduler.get("required_leases")
            if isinstance(selected_scheduler.get("required_leases"), list)
            else []
        )
        selected_reasons = selected_scheduler.get("reasons") if isinstance(selected_scheduler.get("reasons"), list) else []
        lines.append(
            f"- selected_candidate: {_format_key_values({'id': selected_scheduler.get('candidate_id'), 'role': selected_scheduler.get('role'), 'task': selected_scheduler.get('public_task_id') or selected_scheduler.get('task_id'), 'action': selected_scheduler.get('action_kind'), 'score': selected_scheduler.get('score')})}"
        )
        if selected_reasons:
            lines.append(f"- selected_reasons: {_brief_text('; '.join(str(item) for item in selected_reasons[:3]), limit=260)}")
        if selected_context.get("stale_context_warning"):
            lines.append(f"- stale_context_warning: {_brief_text(selected_context.get('stale_context_warning'))}")
        if selected_context_items:
            for item in selected_context_items[:4]:
                if not isinstance(item, dict):
                    continue
                label = item.get("path") or item.get("name") or item.get("category")
                lines.append(
                    f"- context: `{_brief_text(label, limit=120)}` confidence={float(item.get('confidence') or 0):.2f} reason={_brief_text(item.get('reason'), limit=140)}"
                )
        if selected_leases:
            for lease in selected_leases[:4]:
                if not isinstance(lease, dict):
                    continue
                label = lease.get("path") or lease.get("name") or lease.get("scope_node_id")
                lines.append(
                    f"- suggested_lease: {_format_key_values({'scope': lease.get('scope_kind'), 'target': label, 'recommended': _brief_bool(lease.get('recommended')), 'conflicts': lease.get('conflict_count'), 'reason': lease.get('reason')})}"
                )
        else:
            lines.append("- suggested_lease: none")
    else:
        lines.append("- selected_candidate: none")
    if skipped_scheduler:
        for candidate in skipped_scheduler[:BRIEF_ITEM_LIMIT]:
            if not isinstance(candidate, dict):
                continue
            lines.append(
                f"- skipped_candidate: {_format_key_values({'id': candidate.get('candidate_id'), 'role': candidate.get('role'), 'task': candidate.get('public_task_id') or candidate.get('task_id'), 'action': candidate.get('action_kind'), 'reason': candidate.get('skipped_reason')})}"
            )
    else:
        lines.append("- skipped_candidate: none")
    lines.extend([
        "",
        "## Queued Decisions",
        "",
    ])
    if decision_queue:
        for item in decision_queue[:BRIEF_ITEM_LIMIT]:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- {str(item.get('role') or 'idle')}: {str(item.get('state') or 'planned')} - {_brief_text(item.get('reason'))}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Pending Next Actions", ""])
    next_actions = snapshot.get("next_actions") if isinstance(snapshot.get("next_actions"), list) else []
    if next_actions:
        for item in next_actions[:BRIEF_ITEM_LIMIT]:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- {str(item.get('owner_role') or 'idle')}: {str(item.get('status') or 'planned')} - {_brief_text(item.get('reason'))}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Open Blockers", ""])
    blockers = snapshot.get("open_blockers") if isinstance(snapshot.get("open_blockers"), list) else []
    if blockers:
        for item in blockers[:BRIEF_ITEM_LIMIT]:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- {str(item.get('kind') or 'blocker')}: {str(item.get('status') or 'open')} - {_brief_text(item.get('summary'))}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Validation Summary", ""])
    lines.append(f"- counts: {_format_key_values(validation_counts)}")
    if validation_latest:
        for item in validation_latest[:5]:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- latest: {str(item.get('kind') or 'validation')} {str(item.get('status') or 'unknown')} - {_brief_text(item.get('command'), limit=160)}"
            )
    else:
        lines.append("- latest: none")

    lines.extend(["", "## Projection Freshness", ""])
    for name, projection in projection_items:
        projection = projection if isinstance(projection, dict) else {}
        lines.append(
            f"- {name}: path=`{_display_path(target, projection.get('path'))}`, exists={_brief_bool(projection.get('exists'))}, updated_at={_brief_text(projection.get('updated_at') or 'never')}, event_id={projection.get('event_id') or 'none'}, sha={_brief_sha(projection.get('payload_sha256')) or 'none'}"
        )

    return "\n".join(lines).rstrip() + "\n"


def write_canonical_state_brief(target: Path, *, output_path: Path | None = None) -> dict[str, Any]:
    target = target.expanduser().resolve()
    snapshot = state_snapshot(target, event_limit=8)
    if output_path:
        raw_output = output_path.expanduser()
        brief_path = raw_output.resolve() if raw_output.is_absolute() else (target / raw_output).resolve()
    else:
        brief_path = canonical_state_brief_path_for_target(target)
    if target not in brief_path.parents and brief_path != target:
        raise ValueError(f"canonical state brief output must stay inside target: {brief_path}")
    markdown = render_canonical_state_brief(snapshot, target=target)
    brief_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = brief_path.with_name(f".{brief_path.name}.tmp")
    tmp.write_text(markdown, encoding="utf-8")
    tmp.replace(brief_path)
    digest = sha256_text(markdown)
    db_path = database_path_for_target(target)
    with closing(connect(db_path)) as conn:
        replace_projection(
            conn,
            name=CANONICAL_STATE_BRIEF_PROJECTION_NAME,
            payload={
                "format": "markdown",
                "path": str(brief_path),
                "payload_sha256": digest,
                "generated_at": utc_now(),
                "note": "Generated agent-readable view of canonical SQLite state.",
            },
            event_id=None,
        )
    return {
        "path": str(brief_path),
        "relative_path": _display_path(target, brief_path),
        "payload_sha256": digest,
        "markdown": markdown,
        "snapshot": snapshot,
    }


def validate_state_database(target: Path) -> dict[str, Any]:
    snapshot = state_snapshot(target)
    counts = snapshot.get("counts") if isinstance(snapshot.get("counts"), dict) else {}
    missing_tables = [table for table in ORCHESTRATION_TABLES if int(counts.get(table, -1)) < 0]
    machine = snapshot.get("conveyor_machine") if isinstance(snapshot.get("conveyor_machine"), dict) else {}
    work_item = machine.get("work_item") if isinstance(machine.get("work_item"), dict) else {}
    work_payload = work_item.get("payload") if isinstance(work_item.get("payload"), dict) else {}
    active_role_run = work_payload.get("active_role_run") if isinstance(work_payload.get("active_role_run"), dict) else {}
    decision = work_payload.get("decision") if isinstance(work_payload.get("decision"), dict) else {}
    inferred_role = str(active_role_run.get("role") or decision.get("role") or "")
    expected_stage = ROLE_TO_CONVEYOR_STAGE.get(inferred_role, ("", ""))[0]
    actual_stage = str(work_item.get("current_stage") or machine.get("current_stage") or "")
    role_stage_matches = not expected_stage or actual_stage == expected_stage
    invariant_results = snapshot.get("invariant_results") if isinstance(snapshot.get("invariant_results"), list) else []
    items = [
        {
            "ok": snapshot["database"]["exists"],
            "detail": f"Canonical SQLite database exists at {snapshot['database']['path']}.",
        },
        {
            "ok": snapshot["database"]["integrity_check"] == "ok",
            "detail": f"SQLite integrity_check: {snapshot['database']['integrity_check']}.",
        },
        {
            "ok": not missing_tables,
            "detail": "Required typed state tables present."
            if not missing_tables
            else "Missing typed state tables: " + ", ".join(missing_tables),
        },
        {
            "ok": bool(snapshot["projection"]["exists"]),
            "detail": "Compatibility conveyor JSON projection is generated from SQLite."
            if snapshot["projection"]["exists"]
            else "Compatibility conveyor JSON projection is missing.",
        },
        {
            "ok": bool((snapshot.get("conveyor_machine") or {}).get("work_item")),
            "detail": "Typed conveyor work item and current stage are materialized."
            if bool((snapshot.get("conveyor_machine") or {}).get("work_item"))
            else "Typed conveyor work item is missing.",
        },
        {
            "ok": role_stage_matches,
            "detail": f"Typed conveyor stage matches role {inferred_role}: {actual_stage}."
            if role_stage_matches
            else f"Typed conveyor stage mismatch for role {inferred_role}: expected {expected_stage}, got {actual_stage}.",
        },
        {
            "ok": bool((snapshot.get("capability_manifest") or {}).get("digest")),
            "detail": "Repository capability manifest is current in SQLite."
            if bool((snapshot.get("capability_manifest") or {}).get("digest"))
            else "Repository capability manifest is missing.",
        },
        {
            "ok": bool((snapshot.get("codebase_graph_summary") or {}).get("exists")),
            "detail": "Codebase graph snapshot is available in SQLite."
            if bool((snapshot.get("codebase_graph_summary") or {}).get("exists"))
            else "Codebase graph snapshot is missing.",
        },
    ]
    for result in invariant_results:
        if not isinstance(result, dict):
            continue
        items.append(
            {
                "ok": bool(result.get("ok")),
                "detail": f"Invariant {result.get('name')}: {result.get('detail')}",
                "invariant": result.get("name"),
                "failures": result.get("failures") if isinstance(result.get("failures"), list) else [],
            }
        )
    return {
        "status": "pass" if all(item["ok"] for item in items) else "fail",
        "items": items,
        "state_health_summary": snapshot.get("state_health_summary", {}),
        "snapshot": snapshot,
    }
