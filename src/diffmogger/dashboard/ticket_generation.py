from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from .jsonio import json_default, read_json_file, read_text_file
from .target import detect_target_context, load_dashboard_state, load_intake
from diffmogger.runtime.paths import existing_or_target_path, normalize_rel


TICKET_COMPLEXITY_RANGES: dict[str, tuple[int, int]] = {
    "tiny": (2, 3),
    "small": (4, 6),
    "medium": (7, 12),
    "large": (12, 18),
}

TICKET_SIZING_POLICY = """Ticket sizing policy:
- A ticket is one reviewable local patch.
- Each ticket must have one primary deliverable.
- Each ticket needs clear acceptance criteria and concrete verification.
- Split a ticket if it spans multiple components or surfaces.
- Split a ticket if its summary says "and" across unrelated work.
- Split a ticket if it combines scaffold, feature, docs, and tests as one broad task.
- Split a ticket if it would require a broad rewrite.
- Complexity tiers:
  - tiny: 2-3 tickets
  - small: 4-6 tickets
  - medium: 7-12 tickets
  - large: 12-18 initial first-demo tickets
- For very large projects, generate first-demo tickets only. Capture deferred follow-ups in intake fields instead of turning them into giant tickets."""

PROJECT_SNAPSHOT_MAX_TREE_ENTRIES = 90
PROJECT_SNAPSHOT_MAX_FILE_BYTES = 6000
PROJECT_SNAPSHOT_MAX_BRIEF_BYTES = 8000

_EXCLUDED_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".agentic",
    ".diffmogger",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "target",
    "vendor",
}
_EXCLUDED_FILE_NAMES = {
    ".DS_Store",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lockb",
    "Cargo.lock",
}
_SUMMARY_FILE_NAMES = {
    "Cargo.toml",
    "Makefile",
    "README",
    "README.md",
    "README.txt",
    "go.mod",
    "makefile",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "setup.cfg",
    "setup.py",
    "tsconfig.json",
}
_SUMMARY_FILE_PREFIXES = ("vite.config.",)
_BROAD_COMPONENT_WORDS = {
    "api",
    "backend",
    "cli",
    "client",
    "controls",
    "database",
    "docs",
    "frontend",
    "server",
    "service",
    "tests",
    "ui",
    "visualizer",
    "worker",
}
_VAGUE_PHRASES = {
    "all the",
    "complete app",
    "complete project",
    "end to end",
    "everything",
    "finish the app",
    "full system",
    "misc",
    "multiple",
    "overall",
    "polish everything",
    "various",
}


def normalize_ticket_complexity(value: Any, *, fallback: str = "small") -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text in TICKET_COMPLEXITY_RANGES:
        return text
    for tier in TICKET_COMPLEXITY_RANGES:
        if re.search(rf"\b{tier}\b", text):
            return tier
    return fallback if fallback in TICKET_COMPLEXITY_RANGES else "small"


def ticket_count_range(complexity: Any) -> tuple[int, int]:
    return TICKET_COMPLEXITY_RANGES[normalize_ticket_complexity(complexity)]


def ticket_count_guidance(complexity: Any) -> str:
    tier = normalize_ticket_complexity(complexity)
    low, high = ticket_count_range(tier)
    if tier == "large":
        return f"Use {low}-{high} initial first-demo tickets for this large project; defer later work in intake fields."
    return f"Use {low}-{high} seed tickets for this {tier} project."


def ticket_sizing_policy_prompt(complexity: Any | None = None) -> str:
    if complexity is None:
        return TICKET_SIZING_POLICY
    return "\n".join([TICKET_SIZING_POLICY, "", f"Current complexity guidance: {ticket_count_guidance(complexity)}"])


def _text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [line.strip() for line in re.split(r"\r?\n|[;|]", value) if line.strip()]
    return []


def _ticket_text(ticket: dict[str, Any]) -> str:
    parts = [
        str(ticket.get("summary") or ""),
        *(_text_list(ticket.get("acceptance_criteria"))),
        *(_text_list(ticket.get("verification_commands"))),
    ]
    return " ".join(parts).lower()


def ticket_quality_warnings(tickets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for index, ticket in enumerate(tickets):
        ticket_id = str(ticket.get("id") or f"ticket[{index}]")
        summary = str(ticket.get("summary") or "").strip()
        summary_lower = summary.lower()
        acceptance = _text_list(ticket.get("acceptance_criteria"))
        verification = _text_list(ticket.get("verification_commands"))
        combined = _ticket_text(ticket)

        if len(acceptance) > 5:
            warnings.append(
                {
                    "ticket_id": ticket_id,
                    "type": "too_many_acceptance_criteria",
                    "detail": "Ticket has more than five acceptance criteria and may need splitting.",
                }
            )
        if len(verification) > 3:
            warnings.append(
                {
                    "ticket_id": ticket_id,
                    "type": "too_many_verification_commands",
                    "detail": "Ticket has more than three verification commands and may span too much work.",
                }
            )

        conjunctions = re.findall(r"\b(?:and|plus|with)\b", summary_lower)
        if len(conjunctions) >= 2 or re.search(r"\b(?:scaffold|build|implement|add)\b.+\band\b.+\b(?:docs?|tests?|visualizer|controls)\b", summary_lower):
            warnings.append(
                {
                    "ticket_id": ticket_id,
                    "type": "broad_conjunction_summary",
                    "detail": "Summary combines multiple work streams; split into one primary deliverable per ticket.",
                }
            )

        components = sorted(word for word in _BROAD_COMPONENT_WORDS if re.search(rf"\b{re.escape(word)}\b", combined))
        if len(components) >= 3:
            warnings.append(
                {
                    "ticket_id": ticket_id,
                    "type": "multiple_components",
                    "detail": f"Ticket mentions multiple components or surfaces: {', '.join(components[:5])}.",
                }
            )

        if any(phrase in combined for phrase in _VAGUE_PHRASES):
            warnings.append(
                {
                    "ticket_id": ticket_id,
                    "type": "vague_scope",
                    "detail": "Ticket uses broad or vague wording that may hide multiple deliverables.",
                }
            )
    return warnings


def _git_status_summary(target: Path) -> dict[str, Any]:
    result = subprocess.run(
        ["git", "status", "--short"],
        cwd=target,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        return {"is_git_repo": False, "changed_files": [], "dirty_count": 0}
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    return {
        "is_git_repo": True,
        "dirty_count": len(lines),
        "changed_files": lines[:40],
        "truncated": len(lines) > 40,
    }


def _excluded_rel(rel: str) -> bool:
    parts = Path(rel).parts
    if not parts:
        return False
    if any(part in _EXCLUDED_DIR_NAMES for part in parts[:-1]):
        return True
    if parts[-1] in _EXCLUDED_DIR_NAMES or parts[-1] in _EXCLUDED_FILE_NAMES:
        return True
    return False


def shallow_file_tree(target: Path, *, max_entries: int = PROJECT_SNAPSHOT_MAX_TREE_ENTRIES, max_depth: int = 3) -> dict[str, Any]:
    entries: list[str] = []
    truncated = False
    try:
        walker = os.walk(target)
        for root_text, dirs, files in walker:
            root = Path(root_text)
            rel_root = normalize_rel(root.relative_to(target)) if root != target else ""
            depth = 0 if not rel_root else len(Path(rel_root).parts)
            dirs[:] = [
                name
                for name in sorted(dirs)
                if not _excluded_rel(normalize_rel(Path(rel_root) / name))
            ]
            files = [
                name
                for name in sorted(files)
                if not _excluded_rel(normalize_rel(Path(rel_root) / name))
            ]
            if depth >= max_depth:
                dirs[:] = []
            for name in dirs:
                rel = normalize_rel(Path(rel_root) / name)
                entries.append(f"{rel}/")
                if len(entries) >= max_entries:
                    truncated = True
                    return {"entries": entries, "truncated": truncated, "max_depth": max_depth}
            for name in files:
                rel = normalize_rel(Path(rel_root) / name)
                entries.append(rel)
                if len(entries) >= max_entries:
                    truncated = True
                    return {"entries": entries, "truncated": truncated, "max_depth": max_depth}
    except OSError as exc:
        return {"entries": entries, "truncated": False, "error": str(exc), "max_depth": max_depth}
    return {"entries": entries, "truncated": truncated, "max_depth": max_depth}


def _summary_candidate(path: Path) -> bool:
    name = path.name
    return name in _SUMMARY_FILE_NAMES or any(name.startswith(prefix) for prefix in _SUMMARY_FILE_PREFIXES)


def _package_json_summary(path: Path) -> dict[str, Any]:
    package = read_json_file(path)
    scripts = package.get("scripts") if isinstance(package.get("scripts"), dict) else {}
    deps = package.get("dependencies") if isinstance(package.get("dependencies"), dict) else {}
    dev_deps = package.get("devDependencies") if isinstance(package.get("devDependencies"), dict) else {}
    return {
        "path": normalize_rel(path.name),
        "kind": "package_json",
        "name": str(package.get("name") or ""),
        "scripts": {str(key): str(value) for key, value in list(scripts.items())[:20]},
        "dependencies": [str(key) for key in list(deps.keys())[:40]],
        "dev_dependencies": [str(key) for key in list(dev_deps.keys())[:40]],
    }


def _text_file_summary(target: Path, path: Path) -> dict[str, Any]:
    text, truncated = read_text_file(path, max_bytes=PROJECT_SNAPSHOT_MAX_FILE_BYTES)
    lines = [line.rstrip() for line in text.splitlines()]
    excerpt = "\n".join(lines[:80]).strip()
    rel = normalize_rel(path.relative_to(target))
    return {
        "path": rel,
        "kind": "text_excerpt",
        "excerpt": excerpt,
        "truncated": truncated or len(lines) > 80,
    }


def project_file_summaries(target: Path) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    try:
        candidates = [path for path in sorted(target.iterdir()) if path.is_file() and _summary_candidate(path)]
    except OSError:
        return summaries
    for path in candidates[:12]:
        try:
            if path.name == "package.json":
                summaries.append(_package_json_summary(path))
            else:
                summaries.append(_text_file_summary(target, path))
        except OSError as exc:
            summaries.append({"path": normalize_rel(path.name), "kind": "unreadable", "error": str(exc)})
    return summaries


def _read_optional_text(path: Path, *, max_bytes: int) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {"exists": False, "path": str(path), "excerpt": ""}
    text, truncated = read_text_file(path, max_bytes=max_bytes)
    return {"exists": True, "path": str(path), "excerpt": text.strip(), "truncated": truncated}


def _ticket_completion_snapshot(target: Path) -> dict[str, Any]:
    completion_path = existing_or_target_path(target, "target/ticket_run_completion.json")
    completion = read_json_file(completion_path)
    reports_dir = existing_or_target_path(target, "target/ticket_run_reports")
    reports: list[dict[str, str]] = []
    if reports_dir.exists() and reports_dir.is_dir():
        try:
            report_paths = sorted(
                [path for path in reports_dir.iterdir() if path.is_file()],
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            for path in report_paths[:3]:
                text, truncated = read_text_file(path, max_bytes=2500)
                reports.append({"path": str(path), "excerpt": text.strip(), "truncated": bool(truncated)})
        except OSError:
            reports = []
    return {
        "completion": completion,
        "completion_path": str(completion_path),
        "recent_reports": reports,
    }


def build_ticket_generation_snapshot(
    target: Path,
    *,
    ticket_data: dict[str, Any] | None = None,
    include_intake: bool = False,
) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "detected": detect_target_context(target),
        "file_tree": shallow_file_tree(target),
        "file_summaries": project_file_summaries(target),
        "git": _git_status_summary(target),
        "canonical_state_brief": _read_optional_text(
            existing_or_target_path(target, "target/canonical_state_brief.md"),
            max_bytes=PROJECT_SNAPSHOT_MAX_BRIEF_BYTES,
        ),
        "ticket_completion": _ticket_completion_snapshot(target),
    }
    if include_intake:
        snapshot["project_intake"] = load_intake(target)
        snapshot["dashboard_draft_intake"] = load_dashboard_state(target).get("brief_draft_intake") or {}
    if ticket_data is not None:
        snapshot["current_ticket_run"] = ticket_data
    return snapshot


def project_snapshot_prompt_block(snapshot: dict[str, Any]) -> str:
    return json.dumps(snapshot, indent=2, sort_keys=True, default=json_default)
