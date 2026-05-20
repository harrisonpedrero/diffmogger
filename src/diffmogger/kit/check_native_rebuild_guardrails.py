#!/usr/bin/env python3
"""Guardrails for the simplified Diffmogger native dashboard inventory.

This check couples the native dashboard command inventory to the backend command
surface. If a future edit removes or renames a required Setup/Automation command,
this script fails before dashboard behavior silently disappears.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path
from typing import Any


def find_kit_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "services" / "agentic-dashboard" / "native").is_dir() and (
            parent / "validation" / "starter_kit_manifest.json"
        ).is_file():
            return parent
    return Path(__file__).resolve().parents[3]


ROOT = find_kit_root()
INVENTORY = ROOT / "docs" / "archive" / "native-dashboard-command-inventory.md"
NATIVE_RUST = ROOT / "services" / "agentic-dashboard" / "native" / "src-tauri" / "src" / "lib.rs"


FEATURE_COMMAND_REQUIREMENTS: dict[str, list[str]] = {
    "prerequisite checks": ["diagnostics.environment", "diagnostics.run_checks"],
    "fresh-project setup": ["brief.load", "brief.save_draft", "brief.scaffold_preview", "brief.scaffold"],
    "existing-project setup": ["brief.scaffold_preview", "brief.scaffold"],
    "project intake fields": ["brief.load", "brief.generate_intake", "brief.save_draft", "brief.scaffold"],
    "context-file import": ["context.import"],
    "project-context generation": ["context.import"],
    "scaffold/start": ["brief.scaffold_preview", "brief.scaffold", "automation.start"],
    "continuous automation start/stop": ["project.load_snapshot", "automation.start", "automation.stop"],
    "run safety check": ["safety.run_check"],
    "ticket queue": [
        "ticket.load",
        "ticket.add",
        "ticket.update",
        "ticket.delete",
        "ticket.import",
        "ticket.draft_from_intake",
        "ticket.accept_draft",
        "ticket.split_preview",
        "ticket.accept_split",
    ],
    "runtime state": ["state.snapshot", "state.brief", "state.validate", "state.watch"],
    "worker and parallel controls": [
        "worker.run_read_only",
        "worker.run_write",
        "worker.run_integrator",
        "worker.launch_read_only_group",
        "worker.launch_write_group",
        "execution_group.load",
        "execution_group.start",
        "execution_group.cancel",
        "execution_group.retry_failed",
        "execution_group.export_debug_bundle",
        "validation_jobs.load",
        "lease.release_stale",
    ],
    "human input records": ["project.load_snapshot", "state.snapshot"],
    "Multi-role and DAG scheduler intake settings": ["brief.save_draft", "brief.scaffold", "project.load_snapshot", "state.snapshot"],
    "Context7 and Playwright MCP options": ["brief.load", "brief.save_draft", "brief.scaffold"],
    "dashboard state persistence": ["project.load_snapshot", "brief.load", "brief.save_draft"],
    "parallel debug bundle": ["execution_group.export_debug_bundle"],
}


def load_backend_commands() -> set[str]:
    src_dir = ROOT / "src"
    src_text = str(src_dir)
    if src_text not in sys.path:
        sys.path.insert(0, src_text)
    module = importlib.import_module("diffmogger.dashboard.backend_cli")
    parser = module.build_parser()
    for action in parser._actions:  # noqa: SLF001 - argparse exposes subcommands this way.
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            return set(action.choices)
    raise RuntimeError("Backend CLI parser did not expose subcommands")


def check_guardrails() -> list[str]:
    inventory_text = INVENTORY.read_text(encoding="utf-8")
    inventory_lower = inventory_text.lower()
    native_rust = NATIVE_RUST.read_text(encoding="utf-8")
    backend_commands = load_backend_commands()
    failures: list[str] = []

    for feature, commands in FEATURE_COMMAND_REQUIREMENTS.items():
        if feature.lower() not in inventory_lower:
            failures.append(f"Inventory is missing preserved feature text: {feature}")
        for command in commands:
            if command not in inventory_text:
                failures.append(f"Inventory feature '{feature}' does not document backend command {command}")
            if command not in backend_commands:
                failures.append(f"Backend CLI does not expose required command {command} for feature '{feature}'")
            if command not in native_rust:
                failures.append(f"Native Rust allowlist does not include backend command {command}")

    for required_phrase in [
        "services/agentic-dashboard/native",
        "scripts/dashboard_backend_cli.py",
        "Setup",
        "Automation",
    ]:
        if required_phrase not in inventory_text:
            failures.append(f"Inventory is missing migration anchor: {required_phrase}")

    return failures


def main() -> int:
    failures = check_guardrails()
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print(
        "OK: native dashboard guardrails verified "
        f"{len(FEATURE_COMMAND_REQUIREMENTS)} feature groups against backend/native command surfaces"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
