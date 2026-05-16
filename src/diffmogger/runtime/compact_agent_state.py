#!/usr/bin/env python3
"""Compact long-running generated Markdown projections in a target project.

What this script compacts:
- docs/CODEX_AUTOMATION_TASKS.md: preserves required headings and trims only
  oversized section bodies, keeping the latest lines.
- docs/AUTONOMY_EXPERIMENT_LOG.md and docs/DAILY_AUTOMATION_REVIEW.md: keep
  recent H2 entries and replace older entries with concise rollups.

Human messages and ticket campaigns live in typed SQLite state and are not
compacted through Markdown files for new targets.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
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

from diffmogger.runtime.paths import existing_or_target_path, target_path


ACTIVE_STATUS_WORDS = {
    "active",
    "awaiting_user",
    "unhandled",
    "unresolved",
    "pending",
    "notifier_unreachable",
    "discord_send_failed",
    "local_notification_failed",
    "blocked",
}

RESOLVED_STATUS_WORDS = {
    "resolved",
    "handled",
    "done",
    "skipped",
    "cancelled",
    "canceled",
    "sent",
    "outbound_recorded",
}

STATE_FILES = [
    "docs/CODEX_AUTOMATION_TASKS.md",
    "docs/MULTI_ROLE_PROGRESS.md",
    "docs/AUTONOMY_EXPERIMENT_LOG.md",
    "docs/DAILY_AUTOMATION_REVIEW.md",
]

MULTI_ROLE_ROLES = ("planner", "builder", "hardener")
MULTI_ROLE_PROGRESS_SOFT_FLOOR_BYTES = 20_000


@dataclass(frozen=True)
class Entry:
    heading: str
    body: str

    @property
    def text(self) -> str:
        return f"{self.heading}\n{self.body}".rstrip() + "\n"


def now_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")


def split_h2_entries(text: str) -> tuple[str, list[Entry]]:
    matches = list(re.finditer(r"^##\s+.+$", text, re.MULTILINE))
    if not matches:
        return text.rstrip() + "\n", []
    header = text[: matches[0].start()].rstrip() + "\n\n"
    entries: list[Entry] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[match.start() : end].rstrip()
        lines = block.splitlines()
        heading = lines[0].strip()
        body = "\n".join(lines[1:]).strip()
        entries.append(Entry(heading=heading, body=body))
    return header, entries


def status_words(entry: Entry) -> set[str]:
    statuses: set[str] = set()
    for match in re.finditer(r"^\s*-\s*status:\s*([A-Za-z0-9_-]+)", entry.body, re.MULTILINE):
        statuses.add(match.group(1).strip().lower())
    return statuses


def is_active_entry(entry: Entry, *, default_active: bool) -> bool:
    statuses = status_words(entry)
    if statuses & ACTIVE_STATUS_WORDS:
        return True
    if statuses & RESOLVED_STATUS_WORDS:
        return False
    return default_active


def entry_summary(path: Path, entry: Entry) -> str:
    label = entry.heading.replace("##", "", 1).strip()
    status = ", ".join(sorted(status_words(entry))) or "unknown"
    summary = ""
    summary_match = re.search(
        r"^###\s+Summary\s*$\n(.*?)(?=^###\s+|\Z)",
        entry.body,
        re.MULTILINE | re.DOTALL,
    )
    if summary_match:
        summary = first_text_line(summary_match.group(1))
    if not summary:
        summary = first_text_line(entry.body)
    return f"- {path.name} `{label}` status={status}: {summary or 'No summary text.'}"


def first_text_line(text: str) -> str:
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("- "):
            continue
        return re.sub(r"\s+", " ", line)[:220]
    return ""


def append_archive_rollup(archive_path: Path, title: str, summaries: list[str]) -> None:
    if not summaries:
        return
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    if archive_path.exists():
        text = archive_path.read_text(encoding="utf-8").rstrip()
    else:
        text = "# Human Responses Archive\n\nConcise resolution notes archived by automation."
    entry = "\n".join(
        [
            "",
            "",
            f"## COMPACTION-{now_id()} {title}",
            "",
            "- status: compacted",
            f"- entries_summarized: {len(summaries)}",
            "",
            "### Summaries",
            "",
            *summaries,
        ]
    )
    archive_path.write_text(text + entry.rstrip() + "\n", encoding="utf-8")


def write_entries(path: Path, header: str, entries: list[Entry]) -> str:
    body = "\n".join(entry.text.rstrip() for entry in entries).strip()
    return (header.rstrip() + "\n\n" + body + "\n").rstrip() + "\n"


def compact_active_queue(
    path: Path,
    archive_path: Path,
    *,
    keep_latest: int,
    preserve_failures: bool = False,
) -> tuple[str | None, list[str]]:
    if not path.exists():
        return None, []
    original = path.read_text(encoding="utf-8")
    header, entries = split_h2_entries(original)
    if not entries:
        return None, []

    kept: list[Entry] = []
    moved: list[Entry] = []
    recent_boundary = max(len(entries) - keep_latest, 0)
    for index, entry in enumerate(entries):
        active = is_active_entry(entry, default_active=True)
        failure = bool(status_words(entry) & {"notifier_unreachable", "discord_send_failed", "local_notification_failed"})
        recent = index >= recent_boundary
        if active or recent or (preserve_failures and failure):
            kept.append(entry)
        else:
            moved.append(entry)

    if not moved:
        return None, []

    summaries = [entry_summary(path, entry) for entry in moved]
    return write_entries(path, header, kept), summaries


def compact_archive(path: Path, *, keep_latest: int) -> str | None:
    if not path.exists():
        return None
    original = path.read_text(encoding="utf-8")
    header, entries = split_h2_entries(original)
    if len(entries) <= keep_latest:
        return None
    older = entries[: -keep_latest]
    recent = entries[-keep_latest:]
    rollup = Entry(
        heading=f"## COMPACTION-{now_id()} Older Archive Rollup",
        body="\n".join(
            [
                "- status: compacted",
                f"- entries_summarized: {len(older)}",
                "",
                "### Summaries",
                "",
                *[entry_summary(path, entry) for entry in older],
            ]
        ),
    )
    return write_entries(path, header, [rollup, *recent])


def compact_log(path: Path, *, keep_latest: int) -> str | None:
    if not path.exists():
        return None
    original = path.read_text(encoding="utf-8")
    header, entries = split_h2_entries(original)
    if len(entries) <= keep_latest:
        return None
    older = entries[: -keep_latest]
    recent = entries[-keep_latest:]
    rollup = Entry(
        heading=f"## COMPACTION-{now_id()} Older Log Rollup",
        body="\n".join(
            [
                "- status: compacted",
                f"- entries_summarized: {len(older)}",
                "",
                "### Summaries",
                "",
                *[entry_summary(path, entry) for entry in older],
            ]
        ),
    )
    return write_entries(path, header, [rollup, *recent])


def split_sections(text: str) -> tuple[str, list[Entry]]:
    return split_h2_entries(text)


def compact_task_file(path: Path, *, max_section_lines: int) -> str | None:
    if not path.exists():
        return None
    original = path.read_text(encoding="utf-8")
    header, sections = split_sections(original)
    if not sections:
        return None
    changed = False
    compacted: list[Entry] = []
    for section in sections:
        lines = section.body.splitlines()
        meaningful = [line for line in lines if line.strip()]
        if len(meaningful) <= max_section_lines:
            compacted.append(section)
            continue
        keep_count = max(20, max_section_lines // 2)
        kept = lines[-keep_count:]
        body = "\n".join(
            [
                f"- Compacted on {datetime.now(timezone.utc).isoformat(timespec='seconds')}; kept latest {keep_count} lines from an oversized section.",
                "",
                *kept,
            ]
        ).strip()
        compacted.append(Entry(heading=section.heading, body=body))
        changed = True
    if not changed:
        return None
    return write_entries(path, header, compacted)


def split_h3_entries(text: str) -> tuple[str, list[Entry]]:
    matches = list(re.finditer(r"^###\s+.+$", text, re.MULTILINE))
    if not matches:
        return text.rstrip(), []
    header = text[: matches[0].start()].rstrip()
    entries: list[Entry] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[match.start() : end].rstrip()
        lines = block.splitlines()
        entries.append(Entry(heading=lines[0].strip(), body="\n".join(lines[1:]).strip()))
    return header, entries


def compact_multi_role_progress(
    path: Path,
    *,
    keep_latest: int,
    soft_floor_bytes: int,
) -> str | None:
    if not path.exists() or path.stat().st_size < soft_floor_bytes:
        return None
    original = path.read_text(encoding="utf-8")
    header, sections = split_sections(original)
    by_heading = {section.heading.replace("##", "", 1).strip(): section for section in sections}
    recent = by_heading.get("Recent Activity Log")
    historical = by_heading.get("Historical Summary")
    if recent is None or historical is None:
        return None
    recent_header, entries = split_h3_entries(recent.body)
    if len(entries) <= keep_latest:
        return None
    older = entries[: -keep_latest]
    kept = entries[-keep_latest:]
    range_start = older[0].heading.replace("###", "", 1).strip()
    range_end = older[-1].heading.replace("###", "", 1).strip()
    rollup = Entry(
        heading=f"### COMPACTION-{now_id()} Multi-Role Recent Activity",
        body="\n".join(
            [
                "- status: compacted",
                f"- entries_summarized: {len(older)}",
                f"- time_range: {range_start} to {range_end}",
                "",
                "#### Summaries",
                "",
                *[entry_summary(path, entry) for entry in older],
            ]
        ),
    )
    recent.body = ("\n\n".join([recent_header, *[entry.text.rstrip() for entry in kept]]).strip() or "- No recent activity.")
    historical.body = (historical.body.rstrip() + "\n\n" + rollup.text.rstrip()).strip()
    return write_entries(path, header, sections)


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def append_multi_role_history(progress_path: Path, summaries: list[str], *, dry_run: bool) -> None:
    if not summaries:
        return
    if progress_path.exists():
        text = progress_path.read_text(encoding="utf-8")
    else:
        text = "# Multi-Role Progress\n\nGenerated dashboard/export projection for optional multi-role automation. SQLite runtime state is the live authority.\n\nContinuous DAG scheduler mode prioritizes queued integration, baseline repair, typed human-message triage, fast-follow replanning after planner deferral changes, review/hardening, validation, targeted repairs, and compatible build waves.\n\n## Historical Summary\n\n- No compacted multi-role history yet.\n"
    header, sections = split_sections(text)
    found = False
    for section in sections:
        label = section.heading.replace("##", "", 1).strip()
        if label == "Historical Summary":
            found = True
            section.body = (
                section.body.rstrip()
                + "\n\n"
                + f"### COMPACTION-{now_id()} Multi-Role Artifacts\n\n"
                + "- status: compacted\n"
                + f"- summaries_recorded: {len(summaries)}\n\n"
                + "#### Summaries\n\n"
                + "\n".join(summaries)
            ).strip()
            break
    if not found:
        sections.append(
            Entry(
                heading="## Historical Summary",
                body="\n".join(
                    [
                        f"### COMPACTION-{now_id()} Multi-Role Artifacts",
                        "",
                        "- status: compacted",
                        f"- summaries_recorded: {len(summaries)}",
                        "",
                        "#### Summaries",
                        "",
                        *summaries,
                    ]
                ),
            )
        )
    if not dry_run:
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.write_text(write_entries(progress_path, header, sections), encoding="utf-8")


def compact_multi_role_artifacts(target: Path, *, dry_run: bool) -> list[str]:
    now = datetime.now(timezone.utc).timestamp()
    seven_days = 7 * 24 * 60 * 60
    thirty_days = 30 * 24 * 60 * 60
    queue_root = target_path(target, "target/automation_queue")
    worktree_root = target_path(target, "target/automation_worktrees")
    summaries: list[str] = []

    for role in MULTI_ROLE_ROLES:
        role_root = queue_root / role
        if not role_root.exists():
            continue
        run_dirs = [path for path in role_root.iterdir() if path.is_dir()]
        indexed: list[tuple[Path, dict, float]] = []
        for run_dir in run_dirs:
            indexed.append((run_dir, read_json(run_dir / "manifest.json"), run_dir.stat().st_mtime))
        successful = [item for item in indexed if item[1].get("status") == "applied"]
        successful.sort(key=lambda item: item[2], reverse=True)
        keep_success = {item[0].name for item in successful[:5]}
        keep_run_ids = set(keep_success)
        deleted = 0
        preserved_deferred = 0
        for run_dir, manifest, mtime in indexed:
            status = manifest.get("status")
            recent = now - mtime < seven_days
            if status == "deferred":
                preserved_deferred += 1
                keep_run_ids.add(run_dir.name)
                continue
            if recent or status == "queued" or run_dir.name in keep_success:
                keep_run_ids.add(run_dir.name)
                continue
            summary = f"- {role} `{run_dir.name}` status={status or 'unknown'} summarized before artifact cleanup."
            summaries.append(summary)
            if not dry_run:
                shutil.rmtree(run_dir)
            deleted += 1
        if deleted or preserved_deferred:
            summaries.append(
                f"- {role}: deleted {deleted} transient run dirs; preserved {preserved_deferred} deferred run dirs."
            )

        wt_role_root = worktree_root / role
        if not wt_role_root.exists():
            continue
        deleted_worktrees = 0
        for worktree in wt_role_root.iterdir():
            if not worktree.is_dir():
                continue
            recent = now - worktree.stat().st_mtime < seven_days
            if recent or worktree.name in keep_run_ids:
                continue
            if not dry_run:
                result = subprocess.run(
                    ["git", "worktree", "remove", "--force", str(worktree)],
                    cwd=target,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode != 0 and worktree.exists():
                    shutil.rmtree(worktree)
            deleted_worktrees += 1
        if deleted_worktrees:
            summaries.append(f"- {role}: deleted {deleted_worktrees} transient worktrees.")

    log_root = target_path(target, "target/automation_logs")
    if log_root.exists():
        deleted_logs = 0
        for log_path in log_root.glob("*.log"):
            if now - log_path.stat().st_mtime < thirty_days:
                continue
            summaries.append(f"- log `{log_path.relative_to(target)}` summarized before deletion.")
            if not dry_run:
                log_path.unlink(missing_ok=True)
            deleted_logs += 1
        if deleted_logs:
            summaries.append(f"- deleted {deleted_logs} role logs older than 30 days.")

    if summaries:
        append_multi_role_history(existing_or_target_path(target, "docs/MULTI_ROLE_PROGRESS.md"), summaries, dry_run=dry_run)
    if not dry_run and (target / ".git").exists():
        subprocess.run(["git", "worktree", "prune"], cwd=target, capture_output=True, text=True, check=False)
    return summaries


def maybe_write(path: Path, new_text: str | None, *, dry_run: bool) -> bool:
    if new_text is None:
        return False
    old_text = path.read_text(encoding="utf-8") if path.exists() else ""
    if new_text == old_text:
        return False
    if not dry_run:
        path.write_text(new_text, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", default=".", help="Target project directory")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing")
    parser.add_argument("--keep-latest", type=int, default=20, help="Recent H2 entries to keep")
    parser.add_argument(
        "--max-task-section-lines",
        type=int,
        default=80,
        help="Trim oversized task-file sections above this many nonblank lines",
    )
    parser.add_argument(
        "--multi-role-progress-soft-floor-bytes",
        type=int,
        default=MULTI_ROLE_PROGRESS_SOFT_FLOOR_BYTES,
        help="Do not compact docs/MULTI_ROLE_PROGRESS.md recent activity below this size.",
    )
    parser.add_argument(
        "--list-files",
        action="store_true",
        help="Print the supported files and exit",
    )
    args = parser.parse_args()

    if args.list_files:
        for rel in STATE_FILES:
            print(rel)
        return 0

    if args.keep_latest < 1:
        raise SystemExit("--keep-latest must be at least 1")

    target = Path(args.target).resolve()
    changes: list[str] = []

    for rel in ["AUTONOMY_EXPERIMENT_LOG.md", "DAILY_AUTOMATION_REVIEW.md"]:
        path = existing_or_target_path(target, f"docs/{rel}")
        if maybe_write(path, compact_log(path, keep_latest=args.keep_latest), dry_run=args.dry_run):
            changes.append(f"compacted {path.relative_to(target)}")

    progress_path = existing_or_target_path(target, "docs/MULTI_ROLE_PROGRESS.md")
    if maybe_write(
        progress_path,
        compact_multi_role_progress(
            progress_path,
            keep_latest=args.keep_latest,
            soft_floor_bytes=args.multi_role_progress_soft_floor_bytes,
        ),
        dry_run=args.dry_run,
    ):
        changes.append(f"compacted {progress_path.relative_to(target)} recent activity")

    multi_role_summaries = compact_multi_role_artifacts(target, dry_run=args.dry_run)
    if multi_role_summaries:
        changes.append(f"processed multi-role transient artifacts ({len(multi_role_summaries)} summaries)")

    task_path = existing_or_target_path(target, "docs/CODEX_AUTOMATION_TASKS.md")
    if maybe_write(
        task_path,
        compact_task_file(task_path, max_section_lines=args.max_task_section_lines),
        dry_run=args.dry_run,
    ):
        changes.append(f"trimmed oversized sections in {task_path.relative_to(target)}")

    prefix = "DRY RUN: " if args.dry_run else ""
    if changes:
        for change in changes:
            print(prefix + change)
    else:
        print(prefix + "no compaction changes needed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
