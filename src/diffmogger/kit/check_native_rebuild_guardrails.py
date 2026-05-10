#!/usr/bin/env python3
"""Guardrails for the Diffmogger native dashboard preservation inventory.

This check intentionally couples the archived migration inventory to the backend
command surface. If a future edit removes or renames a preserved feature command,
this script fails before dashboard behavior silently disappears from the native
app path.
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
    "fresh-project setup": ["brief.load", "brief.save_draft", "brief.scaffold_preview", "brief.scaffold_bootstrap"],
    "existing-project setup": ["brief.scaffold_preview", "brief.scaffold_bootstrap"],
    "project intake fields": ["brief.load", "brief.save_draft", "brief.scaffold_bootstrap"],
    "context-file import": ["context.import"],
    "project-context generation": ["context.import"],
    "scaffold/bootstrap": ["brief.scaffold_preview", "brief.scaffold_bootstrap"],
    "continuous automation start/stop": ["run.load", "automation.start", "automation.stop"],
    "run safety check": ["safety.run_check"],
    "review export": ["review.load", "review.export_bundle", "review.mark_reviewed"],
    "observatory launch": ["observatory.snapshot", "observatory.generate_html", "observatory.load_html"],
    "worker strategy controls": ["run.load", "worker.run_read_only", "worker.run_write", "worker.run_integrator"],
    "Human bridge and file-only messaging": ["inbox.load", "inbox.send_note", "inbox.reply_request"],
    "markdown file monitor/editor": [
        "advanced.list_files",
        "advanced.load_file",
        "advanced.save_file",
        "advanced.validate_file",
    ],
    "Multi-role and conveyor intake settings": ["brief.save_draft", "brief.scaffold_bootstrap", "run.load"],
    "Context7 and Playwright MCP options": ["brief.load", "brief.save_draft", "brief.scaffold_bootstrap"],
    "dashboard state persistence": ["project.load_snapshot", "brief.load", "brief.save_draft"],
    "debug bundle": ["advanced.export_debug_bundle"],
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
        "Diffmogger Autonomous Build Log",
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
