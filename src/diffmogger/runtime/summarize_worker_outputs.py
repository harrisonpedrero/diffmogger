#!/usr/bin/env python3
"""Summarize bounded worker reports for one automation run.

The script reads the resolved worker-run directory, typically
.diffmogger/runtime/agent_runs/<run_id>/worker_*.md, and writes summary.md
beside the reports. It is intentionally mechanical: the main agent still owns
judgment, integration, and verification.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from diffmogger.runtime.paths import target_path


WORKER_GLOB = "worker_*.md"
INTERESTING_HEADINGS = (
    "findings",
    "risks",
    "recommendations",
    "suggested verification",
    "checks run",
    "integration notes",
)
DISPOSITION_HEADINGS = (
    "accepted findings",
    "rejected findings",
    "deferred findings",
    "unresolved risks",
)


@dataclass(frozen=True)
class WorkerReport:
    path: Path
    role: str
    status: str
    highlights: list[str]
    dispositions: dict[str, list[str]]


def latest_run_id(target: Path) -> str:
    candidates: list[Path] = []
    for runs_dir in agent_runs_dirs(target):
        if runs_dir.exists():
            candidates.extend(path for path in runs_dir.iterdir() if path.is_dir())
    if not candidates:
        searched = ", ".join(str(path) for path in agent_runs_dirs(target))
        raise SystemExit(f"No worker run directories found under {searched}")
    return max(candidates, key=lambda path: path.stat().st_mtime).name


def agent_runs_dirs(target: Path) -> list[Path]:
    canonical = target_path(target, "target/agent_runs")
    legacy = target / "target" / "agent_runs"
    if canonical == legacy:
        return [canonical]
    return [canonical, legacy]


def run_dir_for_summary(target: Path, run_id: str) -> Path:
    candidates = [base / run_id for base in agent_runs_dirs(target)]
    for candidate in candidates:
        if candidate.exists() and any(path.name != "worker_summary.md" for path in candidate.glob(WORKER_GLOB)):
            return candidate
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def section_lines(text: str, heading: str) -> list[str]:
    pattern = re.compile(
        rf"^##+\s+{re.escape(heading)}\s*$\n(.*?)(?=^##+\s+|\Z)",
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        return []
    lines: list[str] = []
    for raw in match.group(1).splitlines():
        line = raw.strip()
        if line.startswith(("- ", "* ")):
            lines.append(line)
        elif line and len(lines) < 3:
            lines.append(f"- {line}")
        if len(lines) >= 8:
            break
    return lines


def infer_status(text: str) -> str:
    match = re.search(r"^- status:\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
    if match:
        return match.group(1).strip()
    if "status: FAILED" in text:
        return "FAILED"
    if "status: UNAVAILABLE" in text:
        return "UNAVAILABLE"
    return "REPORTED"


def summarize_report(path: Path) -> WorkerReport:
    text = path.read_text(encoding="utf-8")
    role = path.stem.removeprefix("worker_")
    highlights: list[str] = []
    for heading in INTERESTING_HEADINGS:
        for line in section_lines(text, heading):
            if line not in highlights:
                highlights.append(line)
            if len(highlights) >= 12:
                break
        if len(highlights) >= 12:
            break
    if not highlights:
        for raw in text.splitlines():
            line = raw.strip()
            if line.startswith(("- ", "* ")) and not line.lower().startswith("- run_id:"):
                highlights.append(line)
            if len(highlights) >= 6:
                break
    dispositions = {heading: section_lines(text, heading) for heading in DISPOSITION_HEADINGS}
    return WorkerReport(
        path=path,
        role=role,
        status=infer_status(text),
        highlights=highlights,
        dispositions=dispositions,
    )


def build_summary(target: Path, run_id: str) -> tuple[Path, str]:
    run_dir = run_dir_for_summary(target, run_id)
    reports = sorted(
        path for path in run_dir.glob(WORKER_GLOB) if path.name != "worker_summary.md"
    )
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = [
        f"# Worker Output Summary: {run_id}",
        "",
        f"- generated_at: {generated_at}",
        f"- run_dir: {run_dir}",
        f"- worker_reports: {len(reports)}",
        "",
    ]

    if not reports:
        lines.extend(
            [
                "## Summary",
                "",
                "No worker reports were found for this run.",
                "",
            ]
        )
        return run_dir / "summary.md", "\n".join(lines)

    lines.extend(["## Reports", ""])
    parsed = [summarize_report(path) for path in reports]
    for report in parsed:
        lines.append(f"- `{report.path.name}`: {report.status}")
    lines.append("")

    lines.extend(["## Consolidated Highlights", ""])
    for report in parsed:
        lines.append(f"### {report.role}")
        lines.append("")
        lines.append(f"- status: {report.status}")
        if report.highlights:
            lines.extend(report.highlights)
        else:
            lines.append("- No concise highlights found; read the full worker report.")
        lines.append("")

    lines.extend(["## Finding Disposition", ""])
    disposition_labels = (
        ("accepted findings", "Accepted Findings"),
        ("rejected findings", "Rejected Findings"),
        ("deferred findings", "Deferred Findings"),
        ("unresolved risks", "Unresolved Risks"),
    )
    for key, label in disposition_labels:
        lines.extend([f"### {label}", ""])
        found = False
        for report in parsed:
            for line in report.dispositions.get(key, []):
                lines.append(f"- {report.role}: {line.removeprefix('- ').removeprefix('* ')}")
                found = True
        if not found:
            lines.append("- Pending main-agent disposition.")
        lines.append("")

    lines.extend(
        [
            "## Integration Reminder",
            "",
            "The main automation agent should decide which findings to accept, reject, or defer, then record that decision in typed runtime state and refresh generated handoff projections.",
            "",
        ]
    )
    return run_dir / "summary.md", "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "target",
        nargs="?",
        default=".",
        help="Target project directory. Default: current directory",
    )
    parser.add_argument("--run-id", help="Run id under the resolved agent_runs directory. Default: latest")
    args = parser.parse_args()

    target = Path(args.target).resolve()
    run_id = args.run_id or latest_run_id(target)
    output_path, summary = build_summary(target, run_id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(summary.rstrip() + "\n", encoding="utf-8")
    print(f"Wrote worker summary: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
