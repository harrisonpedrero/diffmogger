from __future__ import annotations

from .common import *

def queue_snapshot(target: Path) -> dict[str, Any]:
    queue_root = runtime_path(target, "target/automation_queue")
    counts: dict[str, dict[str, int]] = {
        role: {status: 0 for status in QUEUE_STATUSES} for role in ROLES
    }
    totals = {status: 0 for status in QUEUE_STATUSES}
    manifests: list[dict[str, Any]] = []

    for manifest_path in sorted(queue_root.glob("*/*/manifest.json")):
        manifest = read_json(manifest_path)
        role = str(manifest.get("role") or manifest_path.parent.parent.name)
        if role not in counts:
            continue
        status = str(manifest.get("status") or "unknown")
        if status in counts[role]:
            counts[role][status] += 1
            totals[status] += 1
        timestamp = manifest.get("integrated_at") or manifest.get("created_at") or ""
        manifests.append(
            {
                "role": role,
                "run_id": clean_text(manifest.get("run_id") or manifest_path.parent.name, limit=80),
                "status": status,
                "created_at": clean_text(manifest.get("created_at"), limit=80),
                "timestamp": clean_text(timestamp, limit=80),
                "summary": clean_text(manifest.get("summary") or "No summary.", limit=180),
                "deferral_reason": clean_text(manifest.get("deferral_reason"), limit=80),
                "deferral_root_cause": clean_text(manifest.get("deferral_root_cause"), limit=180),
                "baseline_status": clean_text(manifest.get("baseline_status"), limit=80),
                "baseline_failure_signature": clean_text(manifest.get("baseline_failure_signature"), limit=120),
                "changed_files": [
                    clean_text(item, limit=80)
                    for item in list(manifest.get("changed_files") or [])[:5]
                ],
            }
        )

    def manifest_sort_key(item: dict[str, Any]) -> tuple[int, str]:
        status_rank = {"queued": 0, "deferred": 1}.get(str(item.get("status")), 4)
        return status_rank, str(item.get("timestamp") or item.get("created_at") or "")

    actionable = [item for item in manifests if item.get("status") in {"queued", "deferred"}]
    outcomes = [item for item in manifests if item.get("status") in {"applied", "failed", "skipped"}]

    return {
        "counts_by_role": counts,
        "totals": totals,
        "manifests": sorted(actionable, key=manifest_sort_key)[:MAX_MANIFESTS],
        "recent_outcomes": sorted(
            outcomes,
            key=lambda item: str(item.get("timestamp") or item.get("created_at") or ""),
            reverse=True,
        )[:MAX_OUTCOMES],
    }

def decision_queue(conveyor: dict[str, Any], queue: dict[str, Any]) -> list[dict[str, Any]]:
    raw = conveyor.get("decision_queue")
    if isinstance(raw, list) and raw:
        return [
            {
                "role": clean_text(item.get("role") or "idle", limit=40),
                "state": clean_text(item.get("state") or "planned", limit=40),
                "reason": clean_text(item.get("reason") or "", limit=180),
            }
            for item in raw[:8]
            if isinstance(item, dict)
        ]

    last = conveyor.get("last_decision") if isinstance(conveyor.get("last_decision"), dict) else {}
    role = str(last.get("role") or "idle")
    has_last_decision = bool(last.get("role") or last.get("reason"))
    reason = str(last.get("reason") or EMPTY_STATES["next_up"])
    entries = [
        {
            "role": role,
            "state": "next" if has_last_decision else "first-run",
            "reason": clean_text(reason, limit=180),
        }
    ]
    totals = queue.get("totals") if isinstance(queue.get("totals"), dict) else {}
    if int(totals.get("queued", 0) or 0):
        entries.insert(0, {"role": "integrator", "state": "ready", "reason": f"{totals.get('queued')} queued patch(es) need integration"})
    return entries[:8]

def active_run(conveyor: dict[str, Any]) -> dict[str, Any]:
    active = conveyor.get("active_role_run")
    if not isinstance(active, dict):
        return {}
    alive = process_alive(active.get("pid"))
    return {
        "role": clean_text(active.get("role") or "unknown", limit=40),
        "run_id": clean_text(active.get("run_id") or "unknown", limit=80),
        "reason": clean_text(active.get("reason") or "", limit=180),
        "started_at": clean_text(active.get("started_at") or "", limit=80),
        "pid": active.get("pid"),
        "alive": alive,
        "status": "running" if alive else "stale",
    }

def conveyor_health(conveyor: dict[str, Any]) -> dict[str, Any]:
    history = conveyor.get("history") if isinstance(conveyor.get("history"), list) else []
    roles = [
        str(item.get("role") or "")
        for item in history
        if isinstance(item, dict) and item.get("role")
    ]
    recent = roles[-6:]
    churn_sequences = (
        ["hardener", "integrator", "hardener", "integrator"],
        ["integrator", "hardener", "integrator", "hardener"],
    )
    churn = any(recent[-4:] == sequence for sequence in churn_sequences) if len(recent) >= 4 else False
    if churn:
        return {
            "status": "warning",
            "summary": "hardener/integrator churn detected; builder-first policy should route the next idle cycle to builder.",
            "recent_roles": recent,
        }
    return {
        "status": "ok",
        "summary": "planner deferral fast-follow and builder-first conveyor policy active; hardener runs once after integrated builder work.",
        "recent_roles": recent,
    }

def no_progress_summary(no_progress: dict[str, Any]) -> str:
    if not no_progress.get("active"):
        return ""
    streak = int(no_progress.get("streak", 0) or 0)
    threshold = int(no_progress.get("threshold", 0) or 0)
    reason = clean_text(no_progress.get("reason") or "integrator made no patch progress", limit=260)
    if threshold:
        summary = f"No-progress circuit breaker active after {streak}/{threshold} integrator no-progress cycle(s): {reason}"
    else:
        summary = f"No-progress circuit breaker active after {streak} integrator no-progress cycle(s): {reason}"
    planner_requested = clean_text(no_progress.get("planner_requested_at") or "", limit=80)
    if planner_requested:
        summary += f"; planner handoff requested at {planner_requested}"
    return summary

def normalized_deferral_reason(value: Any) -> str:
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

def deferred_backlog_items(target: Path) -> list[str]:
    items: list[str] = []
    queue_root = runtime_path(target, "target/automation_queue")
    for manifest_path in sorted(queue_root.glob("*/*/manifest.json")):
        manifest = read_json(manifest_path)
        if manifest.get("status") != "deferred":
            continue
        role = clean_text(manifest.get("role") or manifest_path.parent.parent.name, limit=40)
        run_id = clean_text(manifest.get("run_id") or manifest_path.parent.name, limit=80)
        reason = clean_text(manifest.get("deferral_reason") or "other", limit=80)
        detail = clean_text(
            manifest.get("deferral_root_cause")
            or manifest.get("deferral_detail")
            or manifest.get("summary")
            or "No detail recorded.",
            limit=320,
        )
        items.append(f"{role} `{run_id}`: {reason}; {detail}")
        if len(items) >= MAX_MANIFESTS:
            break
    return items

def parse_deferred_backlog_item(item: str) -> dict[str, str]:
    text = clean_text(item, limit=520)
    structured = re.match(
        r"^(?P<role>[A-Za-z0-9_-]+)\s+`(?P<run_id>[^`]+)`:\s*(?P<reason>[A-Za-z0-9_-]+)\s*;\s*(?P<detail>.+)$",
        text,
    )
    if structured:
        role = structured.group("role")
        run_id = structured.group("run_id")
        raw_reason = structured.group("reason")
        detail = structured.group("detail")
    else:
        role_match = re.match(r"^(?P<role>[A-Za-z0-9_-]+)\b", text)
        role = role_match.group("role") if role_match and role_match.group("role") in ROLES else "unknown"
        run_match = re.search(r"`([^`]+)`", text)
        run_id = run_match.group(1) if run_match else "unknown"
        raw_reason = text
        detail = text
    reason = normalized_deferral_reason(raw_reason)
    return {
        "role": clean_text(role, limit=40),
        "run_id": clean_text(run_id, limit=80),
        "reason": reason,
        "raw_reason": clean_text(raw_reason, limit=80),
        "detail": clean_text(detail, limit=320),
        "raw": text,
    }

def compact_counts(counts: dict[str, int], *, empty: str) -> str:
    parts = [f"{name} {count}" for name, count in sorted(counts.items()) if count]
    return ", ".join(parts) if parts else empty

def deferred_backlog_triage(backlog_items: list[str]) -> dict[str, Any]:
    entries = [parse_deferred_backlog_item(item) for item in backlog_items]
    if not entries:
        return {
            "summary": "No deferred patch backlog recorded.",
            "recommended_next_action": "No local deferred-patch triage action is needed.",
            "groups": [],
            "items": [],
        }

    buckets: dict[str, list[dict[str, str]]] = {}
    for entry in entries:
        buckets.setdefault(entry["reason"], []).append(entry)

    def reason_sort_key(reason: str) -> tuple[int, str]:
        try:
            return DEFERRAL_REASON_ORDER.index(reason), reason
        except ValueError:
            return len(DEFERRAL_REASON_ORDER), reason

    groups: list[dict[str, Any]] = []
    for reason in sorted(buckets, key=reason_sort_key):
        reason_entries = buckets[reason]
        role_counts: dict[str, int] = {}
        for entry in reason_entries:
            role_counts[entry["role"]] = role_counts.get(entry["role"], 0) + 1
        examples = [
            f"{entry['role']} `{entry['run_id']}`: {entry['detail']}"
            for entry in reason_entries[:2]
        ]
        groups.append(
            {
                "reason": reason,
                "count": len(reason_entries),
                "roles": compact_counts(role_counts, empty="unknown"),
                "action": DEFERRAL_REASON_ACTIONS.get(reason, DEFERRAL_REASON_ACTIONS["other"]),
                "examples": examples,
            }
        )

    summary = f"{len(entries)} deferred backlog item(s): " + ", ".join(
        f"{group['count']} {group['reason']}" for group in groups
    ) + "."
    top = groups[0]
    recommended = f"Start with `{top['reason']}` ({top['count']} item(s)): {top['action']}"
    return {
        "summary": summary,
        "recommended_next_action": recommended,
        "groups": groups,
        "items": entries,
    }

def progress_snapshot(target: Path) -> dict[str, Any]:
    accepted_by_role = {role: 0 for role in ROLES if role != "integrator"}
    deferred_by_role = {role: 0 for role in ROLES if role != "integrator"}
    integrator_runs = 0
    latest_activity: tuple[str, str] | None = None
    queue_root = runtime_path(target, "target/automation_queue")
    for manifest_path in sorted(queue_root.glob("*/*/manifest.json")):
        manifest = read_json(manifest_path)
        role = str(manifest.get("role") or manifest_path.parent.parent.name)
        status = str(manifest.get("status") or "")
        timestamp = str(manifest.get("integrated_at") or manifest.get("created_at") or "")
        summary = clean_text(manifest.get("summary") or "No summary recorded.", limit=260)
        if role == "integrator":
            integrator_runs += 1
        if role in accepted_by_role and status == "applied":
            accepted_by_role[role] += 1
        if role in deferred_by_role and status == "deferred":
            deferred_by_role[role] += 1
        if timestamp and (latest_activity is None or timestamp >= latest_activity[0]):
            latest_activity = (timestamp, f"{role} `{manifest.get('run_id') or manifest_path.parent.name}` {status or 'recorded'}: {summary}")
    backlog = deferred_backlog_items(target)
    deferred_depth = len(backlog)
    return {
        "recent_activity": latest_activity[1] if latest_activity else "No multi-role activity recorded yet.",
        "integrator_runs": integrator_runs,
        "accepted_by_role": accepted_by_role,
        "accepted_total": sum(accepted_by_role.values()),
        "deferred_by_role": deferred_by_role,
        "deferred_total": sum(deferred_by_role.values()),
        "deferred_queue_depth": deferred_depth,
        "deferred_backlog": backlog,
        "deferred_triage": deferred_backlog_triage(backlog),
    }

def role_count_summary(counts: dict[str, int], *, empty: str) -> str:
    parts = [f"{role} {int(counts.get(role, 0) or 0)}" for role in ROLES if role in counts and int(counts.get(role, 0) or 0)]
    return ", ".join(parts) if parts else empty
