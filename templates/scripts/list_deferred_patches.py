#!/usr/bin/env python3
"""List deferred multi-role automation patches as JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from diffmogger_paths import target_path


ROLES = ("planner", "builder", "hardener")
DEFERRAL_REASON_FIELD = "deferral_reason"
DEFERRAL_REASON_ACTIONS = {
    "staleness": "Refresh or recreate the patch from current HEAD, then retry only if the change still matters.",
    "conflict": "Inspect the listed files and replace the patch with a freshly reconciled local change.",
    "verification_failure": "Re-run the failing command locally, fix the source or test issue, then submit a new verified patch.",
    "verification_environment_failure": "Repair project-local tooling or fixtures first, then rerun verification before retrying.",
    "baseline_verification_blocker": "Repair the clean-HEAD full-suite baseline, then retry full-suite-required patches.",
    "guardrail_violation": "Do not apply as-is; replace it with a guardrail-compliant local patch or archive it.",
    "other": "Inspect the manifest and summary, then choose retry, replacement, archival, or documentation.",
}
DEFERRAL_REASON_DECISIONS = {
    "staleness": "replace_from_current_head",
    "conflict": "replace_from_current_head",
    "verification_failure": "retry_after_fix",
    "verification_environment_failure": "retry_after_environment_repair",
    "baseline_verification_blocker": "retry_after_baseline_repair",
    "guardrail_violation": "archive",
    "other": "keep_deferred",
}
DEFERRAL_REASON_ORDER = tuple(DEFERRAL_REASON_ACTIONS)
DECISION_OPTIONS = (
    "archive",
    "replace_from_current_head",
    "retry_after_fix",
    "retry_after_environment_repair",
    "retry_after_baseline_repair",
    "retry_as_is",
    "keep_deferred",
)
LOCAL_PATH_MARKERS = ("/User" + "s/", "/private/var/", "/var/folders/", "/tmp/")


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def deferred_manifests(target: Path) -> list[dict[str, Any]]:
    queue = target_path(target, "target/automation_queue")
    records: list[dict[str, Any]] = []
    for role in ROLES:
        role_dir = queue / role
        if not role_dir.exists():
            continue
        for manifest_path in sorted(role_dir.glob("*/manifest.json")):
            manifest = load_json(manifest_path)
            if not manifest or manifest.get("status") != "deferred":
                continue
            manifest = dict(manifest)
            manifest.setdefault(DEFERRAL_REASON_FIELD, "other")
            manifest["manifest_path"] = manifest_path.relative_to(target).as_posix()
            records.append(manifest)
    records.sort(key=lambda item: str(item.get("created_at") or ""))
    return records


def clean_text(value: Any, *, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        return text[: max(0, limit - 3)].rstrip() + "..."
    return text


def scrub_local_references(value: Any, target: Path, *, limit: int = 320) -> str:
    text = clean_text(value, limit=limit)
    target_text = str(target)
    if target_text:
        text = text.replace(target_text, "<target>")
    for marker in LOCAL_PATH_MARKERS:
        if marker in text:
            text = text.replace(marker, "<local-path>/")
    return clean_text(text, limit=limit)


def normalize_deferral_reason(value: Any) -> str:
    reason = clean_text(value, limit=120).lower().replace("-", "_")
    if reason in {"stale", "staleness"}:
        return "staleness"
    if reason in DEFERRAL_REASON_ACTIONS:
        return reason
    if "environment" in reason and ("verification" in reason or "validation" in reason):
        return "verification_environment_failure"
    if "verification" in reason or "validation" in reason:
        return "verification_failure"
    if "conflict" in reason:
        return "conflict"
    if "stale" in reason:
        return "staleness"
    if "guardrail" in reason or "unsafe" in reason:
        return "guardrail_violation"
    return "other"


def summarize_changed_files(manifest: dict[str, Any]) -> str:
    raw_files = manifest.get("changed_files")
    if not isinstance(raw_files, list):
        return "none recorded"
    files = [clean_text(item, limit=120) for item in raw_files if clean_text(item, limit=120)]
    if not files:
        return "none recorded"
    if len(files) <= 4:
        return ", ".join(files)
    return ", ".join(files[:4]) + f", +{len(files) - 4} more"


def summarize_deferral_detail(manifest: dict[str, Any], target: Path) -> str:
    root_cause = clean_text(manifest.get("deferral_root_cause"), limit=220)
    baseline_status = clean_text(manifest.get("baseline_status"), limit=80)
    baseline_signature = clean_text(manifest.get("baseline_failure_signature"), limit=120)
    base = manifest.get("deferral_detail") or manifest.get("summary") or "No deferral detail recorded."
    detail = scrub_local_references(base, target, limit=320)
    if root_cause:
        detail = f"{root_cause} Detail: {detail}"
    if baseline_status:
        detail = f"baseline_status={baseline_status}; {detail}"
    if baseline_signature:
        detail = f"{detail} baseline_signature={baseline_signature}"
    return clean_text(detail, limit=420)


def reason_sort_key(reason: str) -> tuple[int, str]:
    try:
        return DEFERRAL_REASON_ORDER.index(reason), reason
    except ValueError:
        return len(DEFERRAL_REASON_ORDER), reason


def recommended_decision(reason: str) -> str:
    return DEFERRAL_REASON_DECISIONS.get(reason, DEFERRAL_REASON_DECISIONS["other"])


def triage_groups(records: list[dict[str, Any]], target: Path) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        reason = normalize_deferral_reason(record.get(DEFERRAL_REASON_FIELD))
        buckets.setdefault(reason, []).append(record)

    groups: list[dict[str, Any]] = []
    for reason in sorted(buckets, key=reason_sort_key):
        manifests = sorted(
            buckets[reason],
            key=lambda item: (
                str(item.get("role") or ""),
                str(item.get("created_at") or ""),
                str(item.get("run_id") or ""),
            ),
        )
        role_counts: dict[str, int] = {}
        for manifest in manifests:
            role = clean_text(manifest.get("role") or "unknown", limit=40)
            role_counts[role] = role_counts.get(role, 0) + 1
        groups.append(
            {
                "reason": reason,
                "count": len(manifests),
                "roles": ", ".join(f"{role} {count}" for role, count in sorted(role_counts.items())),
                "action": DEFERRAL_REASON_ACTIONS.get(reason, DEFERRAL_REASON_ACTIONS["other"]),
                "recommended_decision": recommended_decision(reason),
                "manifests": [
                    {
                        "role": clean_text(manifest.get("role") or "unknown", limit=40),
                        "run_id": clean_text(manifest.get("run_id") or "unknown", limit=80),
                        "manifest_path": clean_text(manifest.get("manifest_path") or "", limit=180),
                        "changed_files": summarize_changed_files(manifest),
                        "recommended_decision": recommended_decision(reason),
                        "detail": summarize_deferral_detail(manifest, target),
                    }
                    for manifest in manifests
                ],
            }
        )
    return groups


def render_markdown(records: list[dict[str, Any]], target: Path) -> str:
    groups = triage_groups(records, target)
    lines = [
        "# Deferred Patch Triage",
        "",
        f"- deferred_count: {len(records)}",
    ]
    if not groups:
        lines.extend(
            [
                "- recommended_next_action: No local deferred-patch triage action is needed.",
                "",
                "No deferred patches found.",
            ]
        )
        return "\n".join(lines).rstrip() + "\n"

    top = groups[0]
    lines.extend(
        [
            f"- recommended_next_action: Start with `{top['reason']}` ({top['count']} item(s)): {top['action']}",
            "",
        ]
    )
    for group in groups:
        lines.extend(
            [
                f"## {group['reason']}",
                "",
                f"- count: {group['count']}",
                f"- roles: {group['roles']}",
                f"- action: {group['action']}",
                f"- recommended_decision: {group['recommended_decision']}",
                "- manifests:",
            ]
        )
        for manifest in group["manifests"]:
            lines.extend(
                [
                    f"  - {manifest['role']} `{manifest['run_id']}`: {manifest['manifest_path']}",
                    f"    - changed_files: {manifest['changed_files']}",
                    f"    - triage_decision: pending; recommendation={manifest['recommended_decision']}",
                    f"    - detail: {manifest['detail']}",
                ]
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_decision_template(records: list[dict[str, Any]], target: Path) -> str:
    groups = triage_groups(records, target)
    lines = [
        "# Deferred Patch Decision Worksheet",
        "",
        f"- deferred_count: {len(records)}",
        f"- decision_options: {', '.join(DECISION_OPTIONS)}",
        "- usage: Fill decisions during integrator triage, then update or archive queue items from the main checkout.",
        "",
    ]
    if not groups:
        lines.append("No deferred patches found.")
        return "\n".join(lines).rstrip() + "\n"

    for group in groups:
        lines.extend(
            [
                f"## {group['reason']}",
                "",
                f"- group_recommendation: {group['recommended_decision']}",
                f"- local_next_action: {group['action']}",
                "",
            ]
        )
        for manifest in group["manifests"]:
            lines.extend(
                [
                    f"### {manifest['role']} `{manifest['run_id']}`",
                    "",
                    f"- manifest_path: {manifest['manifest_path']}",
                    f"- changed_files: {manifest['changed_files']}",
                    f"- detail: {manifest['detail']}",
                    f"- recommended_decision: {manifest['recommended_decision']}",
                    "- decision: pending",
                    "- decision_rationale:",
                    "- action_taken:",
                    "- follow_up:",
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", default=".", help="Target project directory")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    parser.add_argument("--markdown", action="store_true", help="Render a grouped Markdown triage report")
    parser.add_argument(
        "--decision-template",
        action="store_true",
        help="Render a per-manifest Markdown worksheet for recording integrator triage decisions",
    )
    args = parser.parse_args(argv)

    target = Path(args.target).resolve()
    records = deferred_manifests(target)
    if args.decision_template:
        print(render_decision_template(records, target), end="")
        return 0
    if args.markdown:
        print(render_markdown(records, target), end="")
        return 0
    indent = 2 if args.pretty else None
    print(json.dumps(records, indent=indent, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
