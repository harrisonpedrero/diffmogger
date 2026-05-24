#!/usr/bin/env python3
"""Check that a generated Diffmogger sidecar has the reusable core files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from diffmogger.runtime.paths import existing_or_target_path, load_manifest, sidecar_enabled


BASE_REQUIRED = [
    "AGENTS.md",
    ".agentic/automation_prompt.md",
    ".agentic/verification_commands.txt",
    ".agentic/smoke_commands.txt",
    "scripts/acquire_codex_lock.sh",
    "scripts/release_codex_lock.sh",
    "scripts/run_temporal_worker.sh",
    "scripts/orchestration_cli.py",
    "scripts/run_observatory.py",
    "scripts/build_replay.py",
    "scripts/diffmogger_browser.py",
    "scripts/load_automation_env.py",
    "scripts/state_brief.py",
    "scripts/ticket_run.py",
    "scripts/repair_environment.py",
    "scripts/spawn_worker_agent.sh",
    "scripts/summarize_worker_outputs.py",
    "scripts/compact_agent_state.py",
    "docs/DEVELOPMENT.md",
    "docs/CODEX_AUTOMATION_TASKS.md",
    "docs/CODEX_AUTOMATION_GUARDRAILS.md",
]

MULTI_ROLE_REQUIRED = [
    ".agentic/roles/planner.md",
    ".agentic/roles/builder.md",
    ".agentic/roles/hardener.md",
    ".agentic/roles/integrator.md",
    "scripts/run_role_automation.sh",
    "scripts/integrate_role_outputs.py",
    "scripts/list_deferred_patches.py",
]

MCP_REQUIRED = [".codex/config.toml"]
PLAYWRIGHT_MCP_REQUIRED = ["scripts/run_playwright_mcp.sh"]

RUNTIME_LIBRARY_REQUIRED = [
    ".diffmogger/lib/diffmogger/__init__.py",
    ".diffmogger/lib/diffmogger/contracts.py",
    ".diffmogger/lib/diffmogger/notifications.py",
    ".diffmogger/lib/diffmogger/supervision.py",
    ".diffmogger/lib/diffmogger/orchestration/workflows.py",
    ".diffmogger/lib/diffmogger/orchestration/activities.py",
    ".diffmogger/lib/diffmogger/orchestration/cli.py",
    ".diffmogger/lib/diffmogger/orchestration/scheduler_policy.py",
    ".diffmogger/lib/diffmogger/orchestration/worker.py",
    ".diffmogger/lib/diffmogger/state/db.py",
    ".diffmogger/lib/diffmogger/state/migrations/env.py",
    ".diffmogger/lib/diffmogger/state/migrations/versions/0001_control_plane.py",
    ".diffmogger/lib/diffmogger/state/migrations/versions/0002_adopt_legacy_control_plane_names.py",
    ".diffmogger/lib/diffmogger/state/migrations/versions/0003_restore_dashboard_projection_schema.py",
    ".diffmogger/lib/diffmogger/state/migrations/versions/0004_coexist_legacy_and_typed_tables.py",
    ".diffmogger/lib/diffmogger/state/migrations/versions/0005_parallel_execution_read_models.py",
    ".diffmogger/lib/diffmogger/runtime/code_facts.py",
    ".diffmogger/lib/diffmogger/runtime/paths.py",
]


def rel_path(root: Path, legacy_rel: str) -> Path:
    if legacy_rel.startswith(".diffmogger/"):
        return root / legacy_rel
    return existing_or_target_path(root, legacy_rel)


def check_required(root: Path, *, multi_role: bool, optional_mcp: bool) -> list[str]:
    required = [*BASE_REQUIRED, *RUNTIME_LIBRARY_REQUIRED]
    if multi_role:
        required.extend(MULTI_ROLE_REQUIRED)
    if optional_mcp:
        required.extend(MCP_REQUIRED)
        required.extend(PLAYWRIGHT_MCP_REQUIRED)

    problems: list[str] = []
    if not sidecar_enabled(root):
        problems.append("missing .diffmogger sidecar manifest")

    for rel in required:
        path = rel_path(root, rel)
        if not path.exists():
            problems.append(f"missing required file: {rel} -> {path.relative_to(root) if path.is_absolute() else path}")

    manifest = load_manifest(root)
    features = manifest.get("features") if isinstance(manifest.get("features"), dict) else {}
    if features.get("runtime_bundle") is not True:
        problems.append("manifest does not mark runtime_bundle=true")
    if manifest.get("layout") != "sidecar_v1":
        problems.append("manifest layout is not sidecar_v1")

    for stale in [
        "scripts/run_conveyor_automation.py",
        "scripts/run_conveyor_automation.sh",
        "scripts/run_process_watchdog.py",
        ".diffmogger/lib/diffmogger/conveyor",
    ]:
        if rel_path(root, stale).exists():
            problems.append(f"legacy generated artifact still present: {stale}")

    task = rel_path(root, "docs/CODEX_AUTOMATION_TASKS.md")
    if task.exists():
        text = task.read_text(encoding="utf-8", errors="replace")
        for marker in ["AUTOMATION_STATUS:", "## Scheduler Work", "## Validation And Repair"]:
            if marker not in text:
                problems.append(f"{task.relative_to(root)} missing marker {marker!r}")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target")
    parser.add_argument("--human-bridge-mode", default="")
    parser.add_argument("--multi-role-enabled", action="store_true", default=True)
    parser.add_argument("--optional-mcp-enabled", action="store_true")
    parser.add_argument("--ticket-campaign-enabled", action="store_true")
    args = parser.parse_args()

    root = Path(args.target).expanduser().resolve()
    problems = check_required(
        root,
        multi_role=args.multi_role_enabled,
        optional_mcp=args.optional_mcp_enabled,
    )
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "target": str(root)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
