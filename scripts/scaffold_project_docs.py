#!/usr/bin/env python3
"""Scaffold generic automation docs into a target project from an intake file."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
KIT_ROOT = SCRIPT_DIR.parent
TEMPLATE_ROOT = KIT_ROOT / "templates"


HEADING_TO_KEY = {
    "summary": "summary",
    "product goal": "product_goal",
    "target user": "target_user",
    "desired first demo": "desired_first_demo",
    "tech preferences": "tech_preferences",
    "constraints": "hard_constraints",
    "hard constraints": "hard_constraints",
    "safety rules": "safety_constraints",
    "safety constraints": "safety_constraints",
    "external services": "external_services",
    "verification": "verification_commands",
    "automation cadence": "desired_cadence",
    "desired cadence": "desired_cadence",
    "human bridge": "human_bridge_enabled",
    "human bridge mode": "human_bridge_mode",
    "human requested text responses": "human_requested_text_responses",
    "worker agents": "worker_agents_allowed",
    "codex cli workers": "codex_cli_workers_expected_on_broad_runs",
    "meaningful deliverable": "meaningful_deliverable",
    "beyond mvp": "beyond_mvp",
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
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    return parse_markdown_intake(path)


def placeholders(data: dict[str, Any]) -> dict[str, str]:
    project_name = str(data.get("project_name") or data.get("summary") or "New Project").strip()
    verification = normalize_lines(
        data.get("verification_commands"),
        "Add project-specific test, lint, build, or demo commands during bootstrap.",
    )
    return {
        "PROJECT_NAME": project_name,
        "PROJECT_SLUG": slugify(project_name),
        "PRODUCT_GOAL": normalize_lines(data.get("product_goal"), "Build a useful local-first product from the intake brief."),
        "TARGET_USER": normalize_lines(data.get("target_user"), "The primary user described in the intake brief."),
        "DESIRED_FIRST_DEMO": normalize_lines(data.get("desired_first_demo"), "A runnable local demo that proves the core workflow."),
        "TECH_PREFERENCES": normalize_lines(data.get("tech_preferences"), "Use the existing repo stack or choose a simple, well-supported default."),
        "HARD_CONSTRAINTS": normalize_lines(data.get("hard_constraints"), "Keep the first demo local-first and reviewable."),
        "SAFETY_CONSTRAINTS": normalize_lines(data.get("safety_constraints"), "No secrets, paid actions, public deploys, or real-world side effects without approval."),
        "EXTERNAL_SERVICES": normalize_lines(data.get("external_services"), "None required for the first demo."),
        "VERIFICATION_COMMANDS": verification,
        "CADENCE": normalize_lines(data.get("desired_cadence"), "hourly"),
        "HUMAN_BRIDGE_ENABLED": str(normalize_bool(data.get("human_bridge_enabled"), False)).lower(),
        "WORKER_AGENTS_ALLOWED": str(normalize_bool(data.get("worker_agents_allowed"), True)).lower(),
        "MEANINGFUL_DELIVERABLE": normalize_lines(data.get("meaningful_deliverable"), "A runnable, verified increment."),
        "BEYOND_MVP": normalize_lines(data.get("beyond_mvp"), "Continue improving core value, demo quality, integrations, and automation reliability."),
        "ASSUMPTIONS": normalize_lines(data.get("assumptions"), "Assumptions should be documented during bootstrap."),
        "CREATED_AT": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def render_template(text: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def scaffold(target: Path, values: dict[str, str], force: bool) -> list[Path]:
    written: list[Path] = []
    for template_path in sorted(TEMPLATE_ROOT.rglob("*")):
        if template_path.is_dir():
            continue
        rel = template_path.relative_to(TEMPLATE_ROOT)
        dest = target / rel
        if dest.exists() and not force:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        rendered = render_template(template_path.read_text(encoding="utf-8"), values)
        dest.write_text(rendered, encoding="utf-8")
        written.append(dest)
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
