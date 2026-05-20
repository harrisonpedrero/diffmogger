from __future__ import annotations

from .queue_state import (
    format_file_list,
    manifest_file_list,
    manifest_summary_line,
    queued_manifests,
    role_manifest_records,
)
from .state import *
from diffmogger.runtime import ticket_run as ticket_runtime

def project_intake(target: Path) -> dict[str, Any]:
    path = dpath(target, ".agentic/project_intake.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}

def load_ticket_run(target: Path) -> dict[str, Any] | None:
    try:
        data, _path, _text = ticket_runtime.load_ticket_run(target)
    except SystemExit:
        return None
    return data if isinstance(data, dict) else None

def _normalize_campaign_mode(value: Any, legacy_run_mode: Any = None) -> str:
    raw = value if value is not None else legacy_run_mode
    text = str(raw or "ongoing").strip().lower().replace("-", "_").replace(" ", "_")
    if text in {"bounded", "ongoing"}:
        return text
    if text == "ticket_campaign":
        return "bounded"
    if text == "continuous_improvement":
        return "ongoing"
    return "ongoing"

def campaign_mode(target: Path, ticket_data: dict[str, Any] | None = None) -> str:
    if isinstance(ticket_data, dict):
        explicit = ticket_data.get("campaign_mode")
        legacy = ticket_data.get("automation_run_mode")
        if explicit is not None or legacy is not None:
            return _normalize_campaign_mode(explicit, legacy)
        if "halt_when_complete" in ticket_data:
            return "bounded" if bool(ticket_data.get("halt_when_complete")) else "ongoing"
    intake = project_intake(target)
    return _normalize_campaign_mode(intake.get("campaign_mode"), intake.get("automation_run_mode"))

def ticket_status(ticket: dict[str, Any]) -> str:
    status = str(ticket.get("status") or "pending").strip().lower()
    return status if status in {"pending", "in_progress", "candidate_done", "done", "blocked"} else "pending"

def ticket_has_evidence(ticket: dict[str, Any]) -> bool:
    for key in ("evidence", "checks_run", "related_commits"):
        value = ticket.get(key)
        if isinstance(value, list) and any(str(item).strip() for item in value):
            return True
        if isinstance(value, str) and value.strip():
            return True
    return False

def list_text_values(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []

def ticket_identifier(ticket: dict[str, Any], index: int) -> str:
    ticket_id = str(ticket.get("id") or "").strip()
    return ticket_id or f"ticket[{index}]"

def ticket_has_hardener_or_final_verification(ticket: dict[str, Any]) -> bool:
    for key in ("hardener_evidence", "final_evidence", "verification_evidence"):
        if list_text_values(ticket.get(key)):
            return True
    evidence_text = "\n".join(
        item
        for key in ("evidence", "checks_run", "related_commits")
        for item in list_text_values(ticket.get(key))
    )
    return bool(FINAL_VERIFICATION_RE.search(evidence_text))

def ticket_search_tokens(ticket: dict[str, Any]) -> list[str]:
    tokens: list[str] = []
    ticket_id = str(ticket.get("id") or "").strip()
    if ticket_id:
        tokens.append(ticket_id.lower())
    summary = re.sub(r"\s+", " ", str(ticket.get("summary") or "")).strip().lower()
    if len(summary) >= 16:
        tokens.append(summary[:120])
    for key in ("evidence", "checks_run", "related_commits"):
        for value in list_text_values(ticket.get(key)):
            lowered = value.lower()
            if len(lowered) >= 16:
                tokens.append(lowered[:120])
    return tokens

def manifest_references_ticket(manifest: dict[str, Any], ticket: dict[str, Any]) -> bool:
    tokens = ticket_search_tokens(ticket)
    if not tokens:
        return False
    haystack = "\n".join(
        [
            str(manifest.get("summary") or ""),
            "\n".join(manifest_file_list(manifest)),
        ]
    ).lower()
    return any(token in haystack for token in tokens)

def find_builder_manifest_for_ticket(target: Path, ticket: dict[str, Any]) -> dict[str, Any] | None:
    for _path, manifest in reversed(role_manifest_records(target, "builder", {"applied"})):
        if manifest_references_ticket(manifest, ticket):
            return manifest
    return None

def unverified_candidate_done_cluster_info(target: Path) -> dict[str, Any] | None:
    data = load_ticket_run(target)
    if not data:
        return None
    raw_tickets = data.get("tickets")
    items = [item for item in raw_tickets if isinstance(item, dict)] if isinstance(raw_tickets, list) else []
    unverified = [
        (index, item)
        for index, item in enumerate(items)
        if ticket_status(item) == "candidate_done" and not ticket_has_hardener_or_final_verification(item)
    ]
    if not unverified:
        return None
    first_index, first_ticket = unverified[0]
    manifest = find_builder_manifest_for_ticket(target, first_ticket)
    cluster = [(first_index, first_ticket)]
    if manifest:
        matching = [(index, item) for index, item in unverified if manifest_references_ticket(manifest, item)]
        cluster = matching or cluster
    ticket_ids = [ticket_identifier(item, index) for index, item in cluster]
    info: dict[str, Any] = {
        "ticket_ids": ticket_ids,
        "count": len(ticket_ids),
    }
    if manifest:
        info.update(
            {
                "builder_run_id": str(manifest.get("run_id") or "unknown"),
                "files": manifest_file_list(manifest),
                "summary": manifest_summary_line(manifest),
            }
        )
    return info

def candidate_done_hardener_catchup_reason(info: dict[str, Any]) -> str:
    tickets = ", ".join(str(item) for item in info.get("ticket_ids") or []) or "oldest candidate_done ticket"
    builder_run = str(info.get("builder_run_id") or "")
    if builder_run:
        files = [str(item) for item in info.get("files") or []]
        return (
            f"candidate_done ticket cluster needs hardener verification: {tickets}; "
            f"oldest cluster traces to builder {builder_run} ({format_file_list(files)})"
        )
    return f"candidate_done ticket needs hardener verification: {tickets}"

def _next_auto_ticket_id(tickets: list[dict[str, Any]]) -> str:
    max_number = 0
    for item in tickets:
        ticket_id = str(item.get("id") or "")
        match = re.search(r"(\d+)$", ticket_id)
        if match:
            max_number = max(max_number, int(match.group(1)))
    return f"AUTO-{max_number + 1:03d}"

def _ongoing_campaign_needs_ticket(tickets: list[dict[str, Any]]) -> bool:
    if not tickets:
        return True
    return all(
        ticket_status(item) == "blocked"
        or (ticket_status(item) == "done" and ticket_has_evidence(item))
        for item in tickets
    )

def _verification_fallback(target: Path) -> list[str]:
    commands = project_intake(target).get("verification_commands")
    if isinstance(commands, list):
        normalized = [str(item).strip() for item in commands if str(item).strip()]
        if normalized:
            return normalized
    if isinstance(commands, str) and commands.strip():
        return [line.strip() for line in commands.splitlines() if line.strip()]
    return ["Run the most relevant local verification command available, or create unblocker work if verification cannot run yet."]

def _append_ongoing_campaign_ticket(target: Path, data: dict[str, Any], reason: str) -> dict[str, Any]:
    tickets = [dict(item) for item in data.get("tickets", []) if isinstance(item, dict)]
    ticket_id = _next_auto_ticket_id(tickets)
    if "blocked" in reason:
        summary = "Create unblocker work from current planning inputs"
        criteria = [
            "Current planning inputs are converted into repair, setup, mock, fixture, defer, split, reframe, review, documentation, or alternate-ticket work.",
            "A dependency-ready next action is recorded with evidence.",
        ]
    else:
        summary = "Draft and complete the next safe campaign increment"
        criteria = [
            "A small project-agnostic improvement is chosen from intake, runtime state, repo context, validation receipts, or completed work.",
            "The increment is implemented or converted into follow-up DAG work with typed evidence.",
        ]
    tickets.append(
        {
            "id": ticket_id,
            "summary": summary,
            "depends_on": [],
            "status": "pending",
            "acceptance_criteria": criteria,
            "verification_commands": _verification_fallback(target),
            "evidence": [],
            "related_commits": [],
            "blocker": "",
            "drafted_by": "ongoing_campaign",
            "draft_reason": reason,
        }
    )
    updated = {
        **data,
        "campaign_mode": "ongoing",
        "halt_when_complete": False,
        "tickets": tickets,
    }
    return ticket_runtime.write_ticket_run_state(
        target,
        updated,
        actor_role="conveyor",
        event_type="ticket.run_auto_drafted",
    )

def ensure_ongoing_campaign_has_work(target: Path, data: dict[str, Any]) -> tuple[dict[str, Any], str]:
    if campaign_mode(target, data) != "ongoing":
        return data, "bounded campaign"
    raw_tickets = data.get("tickets")
    tickets = [item for item in raw_tickets if isinstance(item, dict)] if isinstance(raw_tickets, list) else []
    if not _ongoing_campaign_needs_ticket(tickets):
        return data, "ongoing campaign has active tickets"
    statuses = [ticket_status(item) for item in tickets]
    if statuses and any(status == "blocked" for status in statuses):
        reason = "blocked tickets require unblocker work"
    elif statuses:
        reason = "completed ticket set left no dependency-ready work"
    else:
        reason = "empty ongoing campaign queue"
    return _append_ongoing_campaign_ticket(target, data, reason), reason

def ticket_campaign_terminal(target: Path) -> tuple[str | None, str]:
    data = load_ticket_run(target)
    if not data:
        return None, "campaign inactive"
    mode = campaign_mode(target, data)
    if mode == "ongoing":
        data, reason = ensure_ongoing_campaign_has_work(target, data)
        return None, f"ongoing campaign active: {reason}"
    if not bool(data.get("halt_when_complete", True)):
        return None, "bounded campaign inactive"
    if queued_manifests(target):
        return None, "bounded campaign has queued role patches"
    raw_tickets = data.get("tickets")
    items = [item for item in raw_tickets if isinstance(item, dict)] if isinstance(raw_tickets, list) else []
    if not items:
        return None, "bounded campaign has no tickets"
    statuses = [ticket_status(item) for item in items]
    all_done = all(status == "done" for status in statuses) and all(ticket_has_evidence(item) for item in items)
    if all_done:
        return "complete", "bounded campaign complete"
    if all(status in {"done", "blocked"} for status in statuses) and any(status == "blocked" for status in statuses):
        return None, "bounded campaign has blocked tickets requiring unblocker work"
    return None, "bounded campaign active"

def finalize_ticket_campaign(target: Path) -> None:
    helper = script_path(target, "scripts/ticket_run.py")
    if not helper.exists():
        return
    result = subprocess.run(
        [sys.executable, str(helper), str(target), "should-halt", "--finalize"],
        cwd=target,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.stdout.strip():
        print(result.stdout.strip(), flush=True)
    if result.returncode not in {0, 1} and result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr, flush=True)
