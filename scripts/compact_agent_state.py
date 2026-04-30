#!/usr/bin/env python3
"""Compact long-running Markdown state files in a target project.

What this script compacts:
- docs/HUMAN_INBOX.md: preserves unhandled/unresolved entries and moves handled
  entries into docs/HUMAN_RESPONSES_ARCHIVE.md as concise rollups.
- docs/HUMAN_REQUESTS.md: preserves active/awaiting/unresolved requests and moves
  resolved/skipped/cancelled requests into the archive as concise rollups.
- docs/HUMAN_OUTBOX.md: preserves recent entries and all notifier/provider
  failures; older successful entries become archive rollups.
- docs/HUMAN_RESPONSES_ARCHIVE.md: keeps recent archive entries and replaces
  older entries with a concise compaction rollup.
- docs/CODEX_AUTOMATION_TASKS.md: preserves required headings and trims only
  oversized section bodies, keeping the latest lines.
- docs/AUTONOMY_EXPERIMENT_LOG.md and docs/DAILY_AUTOMATION_REVIEW.md: keep
  recent H2 entries and replace older entries with concise rollups.

The script does not silently delete active human requests. Use --dry-run first
on a new project and review the diff after compaction.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


ACTIVE_STATUS_WORDS = {
    "active",
    "awaiting_user",
    "unhandled",
    "unresolved",
    "pending",
    "notifier_unreachable",
    "provider_send_failed",
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
    "docs/HUMAN_INBOX.md",
    "docs/HUMAN_REQUESTS.md",
    "docs/HUMAN_OUTBOX.md",
    "docs/HUMAN_RESPONSES_ARCHIVE.md",
    "docs/CODEX_AUTOMATION_TASKS.md",
    "docs/AUTONOMY_EXPERIMENT_LOG.md",
    "docs/DAILY_AUTOMATION_REVIEW.md",
]


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
        failure = bool(status_words(entry) & {"notifier_unreachable", "provider_send_failed"})
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
    docs = target / "docs"
    archive = docs / "HUMAN_RESPONSES_ARCHIVE.md"
    changes: list[str] = []

    queue_specs = [
        (docs / "HUMAN_INBOX.md", False),
        (docs / "HUMAN_REQUESTS.md", False),
        (docs / "HUMAN_OUTBOX.md", True),
    ]
    for path, preserve_failures in queue_specs:
        new_text, summaries = compact_active_queue(
            path,
            archive,
            keep_latest=args.keep_latest,
            preserve_failures=preserve_failures,
        )
        if maybe_write(path, new_text, dry_run=args.dry_run):
            if summaries and not args.dry_run:
                append_archive_rollup(archive, f"{path.name} Rollup", summaries)
            changes.append(f"compacted {path.relative_to(target)} ({len(summaries)} entries summarized)")

    if maybe_write(
        archive,
        compact_archive(archive, keep_latest=max(args.keep_latest * 2, args.keep_latest)),
        dry_run=args.dry_run,
    ):
        changes.append(f"compacted {archive.relative_to(target)}")

    for rel in ["AUTONOMY_EXPERIMENT_LOG.md", "DAILY_AUTOMATION_REVIEW.md"]:
        path = docs / rel
        if maybe_write(path, compact_log(path, keep_latest=args.keep_latest), dry_run=args.dry_run):
            changes.append(f"compacted {path.relative_to(target)}")

    task_path = docs / "CODEX_AUTOMATION_TASKS.md"
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
