#!/usr/bin/env python3
"""Shared path helpers for legacy and sidecar Diffmogger target layouts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SIDECAR_LAYOUT = "sidecar_v1"
MANIFEST_REL = ".diffmogger/manifest.json"

PATH_ALIASES: dict[str, str] = {
    ".agentic/automation_prompt.md": ".diffmogger/agentic/automation_prompt.md",
    ".agentic/smoke_commands.txt": ".diffmogger/agentic/smoke_commands.txt",
    ".agentic/verification_commands.txt": ".diffmogger/agentic/verification_commands.txt",
    ".agentic/project_intake.json": ".diffmogger/agentic/project_intake.json",
    ".agentic/dashboard_state.json": ".diffmogger/agentic/dashboard_state.json",
    ".agentic/reviewed.json": ".diffmogger/agentic/reviewed.json",
    ".agentic/roles/planner.md": ".diffmogger/agentic/roles/planner.md",
    ".agentic/roles/builder.md": ".diffmogger/agentic/roles/builder.md",
    ".agentic/roles/hardener.md": ".diffmogger/agentic/roles/hardener.md",
    ".agentic/roles/integrator.md": ".diffmogger/agentic/roles/integrator.md",
    ".codex/config.toml": ".diffmogger/agentic/codex_config.toml",
    "docs/AUTONOMY_EXPERIMENT_LOG.md": ".diffmogger/state/AUTONOMY_EXPERIMENT_LOG.md",
    "docs/CODEX_AUTOMATION_GUARDRAILS.md": ".diffmogger/state/CODEX_AUTOMATION_GUARDRAILS.md",
    "docs/CODEX_AUTOMATION_TASKS.md": ".diffmogger/state/CODEX_AUTOMATION_TASKS.md",
    "docs/DAILY_AUTOMATION_REVIEW.md": ".diffmogger/state/DAILY_AUTOMATION_REVIEW.md",
    "docs/DEVELOPMENT.md": ".diffmogger/state/DEVELOPMENT.md",
    "docs/HUMAN_BRIDGE_SETUP.md": ".diffmogger/state/HUMAN_BRIDGE_SETUP.md",
    "docs/HUMAN_INBOX.md": ".diffmogger/state/HUMAN_INBOX.md",
    "docs/HUMAN_OUTBOX.md": ".diffmogger/state/HUMAN_OUTBOX.md",
    "docs/HUMAN_REQUESTS.md": ".diffmogger/state/HUMAN_REQUESTS.md",
    "docs/HUMAN_RESPONSES_ARCHIVE.md": ".diffmogger/state/HUMAN_RESPONSES_ARCHIVE.md",
    "docs/INITIAL_BOOTSTRAP_PROMPT.md": ".diffmogger/state/INITIAL_BOOTSTRAP_PROMPT.md",
    "docs/MCP_INTEGRATIONS.md": ".diffmogger/state/MCP_INTEGRATIONS.md",
    "docs/MULTI_ROLE_PROGRESS.md": ".diffmogger/state/MULTI_ROLE_PROGRESS.md",
    "docs/PROJECT_CONTEXT.md": ".diffmogger/state/PROJECT_CONTEXT.md",
    "docs/TICKET_RUN.md": ".diffmogger/state/TICKET_RUN.md",
    "docs/backlog/README.md": ".diffmogger/state/backlog/README.md",
    "docs/context": ".diffmogger/context",
    "target/action_plan_history.json": ".diffmogger/runtime/action_plan_history.json",
    "target/agent_runs": ".diffmogger/runtime/agent_runs",
    "target/automation_conveyor.lock": ".diffmogger/runtime/automation_conveyor.lock",
    "target/automation_conveyor_state.json": ".diffmogger/runtime/automation_conveyor_state.json",
    "target/automation_logs": ".diffmogger/runtime/automation_logs",
    "target/automation_queue": ".diffmogger/runtime/automation_queue",
    "target/automation_runner.json": ".diffmogger/runtime/automation_runner.json",
    "target/automation_venvs": ".diffmogger/runtime/automation_venvs",
    "target/automation_worktrees": ".diffmogger/runtime/automation_worktrees",
    "target/baseline_verification.json": ".diffmogger/runtime/baseline_verification.json",
    "target/codex_automation.lock": ".diffmogger/runtime/codex_automation.lock",
    "target/first-review": ".diffmogger/runtime/first-review",
    "target/integration_safety_check.json": ".diffmogger/runtime/integration_safety_check.json",
    "target/prisma-cache": ".diffmogger/runtime/prisma-cache",
    "target/ticket_run_completion.json": ".diffmogger/runtime/ticket_run_completion.json",
    "target/ticket_drafts": ".diffmogger/runtime/ticket_drafts",
    "target/ticket_run_reports": ".diffmogger/runtime/ticket_run_reports",
}


TEXT_REPLACEMENTS = sorted(PATH_ALIASES.items(), key=lambda item: len(item[0]), reverse=True)


def normalize_rel(path: str | Path) -> str:
    rel = Path(str(path).replace("\\", "/")).as_posix()
    while rel.startswith("./"):
        rel = rel[2:]
    return rel.lstrip("/")


def sidecar_rel(path: str | Path) -> str:
    rel = normalize_rel(path)
    if rel in PATH_ALIASES:
        return PATH_ALIASES[rel]
    for old, new in PATH_ALIASES.items():
        if rel.startswith(old.rstrip("/") + "/"):
            return new.rstrip("/") + rel[len(old.rstrip("/")) :]
    return rel


def sidecarize_text(text: str) -> str:
    for old, new in TEXT_REPLACEMENTS:
        text = text.replace(old, new)
    return text


def alias_target_rel(aliases: dict[str, Any], rel: str) -> str | None:
    if rel in aliases:
        return normalize_rel(str(aliases[rel]))
    for old, new in sorted(aliases.items(), key=lambda item: len(str(item[0])), reverse=True):
        old_rel = normalize_rel(str(old)).rstrip("/")
        new_rel = normalize_rel(str(new)).rstrip("/")
        if old_rel and rel.startswith(old_rel + "/"):
            return new_rel + rel[len(old_rel) :]
    return None


def manifest_path(target: Path) -> Path:
    return target / MANIFEST_REL


def load_manifest(target: Path) -> dict[str, Any]:
    try:
        data = json.loads(manifest_path(target).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def sidecar_enabled(target: Path) -> bool:
    return load_manifest(target).get("layout") == SIDECAR_LAYOUT


def target_rel(target: Path, legacy_rel: str | Path) -> str:
    rel = normalize_rel(legacy_rel)
    if sidecar_enabled(target):
        aliases = load_manifest(target).get("path_aliases")
        if isinstance(aliases, dict):
            aliased = alias_target_rel(aliases, rel)
            if aliased is not None:
                return aliased
        return sidecar_rel(rel)
    return rel


def target_path(target: Path, legacy_rel: str | Path) -> Path:
    return target / target_rel(target, legacy_rel)


def existing_target_path(target: Path, legacy_rel: str | Path) -> Path:
    sidecar = target / sidecar_rel(legacy_rel)
    if sidecar.exists():
        return sidecar
    return target / normalize_rel(legacy_rel)


def existing_or_target_path(target: Path, legacy_rel: str | Path) -> Path:
    if sidecar_enabled(target):
        return target_path(target, legacy_rel)
    return existing_target_path(target, legacy_rel)


def preferred_target_path(target: Path, legacy_rel: str | Path) -> Path:
    legacy = target / normalize_rel(legacy_rel)
    if not sidecar_enabled(target) and legacy.exists():
        return legacy
    return target / sidecar_rel(legacy_rel)


def manifest_list(manifest: dict[str, Any], key: str) -> list[str]:
    raw = manifest.get(key)
    if not isinstance(raw, list):
        return []
    return [normalize_rel(item) for item in raw if str(item).strip()]


def sidecar_manifest(
    *,
    owned_paths: list[str],
    runtime_paths: list[str],
    worktree_seed_paths: list[str],
    patch_exclude_paths: list[str],
    human_state_paths: list[str],
    features: dict[str, Any],
    path_aliases: dict[str, str] | None = None,
) -> dict[str, Any]:
    aliases = PATH_ALIASES if path_aliases is None else path_aliases
    return {
        "schema_version": 1,
        "layout": SIDECAR_LAYOUT,
        "owned_paths": sorted(set(map(normalize_rel, owned_paths))),
        "runtime_paths": sorted(set(map(normalize_rel, runtime_paths))),
        "worktree_seed_paths": sorted(set(map(normalize_rel, worktree_seed_paths))),
        "patch_exclude_paths": sorted(set(map(normalize_rel, patch_exclude_paths))),
        "human_state_paths": sorted(set(map(normalize_rel, human_state_paths))),
        "path_aliases": dict(sorted((normalize_rel(k), normalize_rel(v)) for k, v in aliases.items())),
        "features": features,
    }
