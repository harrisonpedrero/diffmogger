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

def ticket_run_file(target: Path) -> Path:
    configured = str(project_intake(target).get("ticket_run_file") or "").strip()
    if configured:
        return target / configured
    legacy = dpath(target, "docs/TICKET_RUN.md")
    if legacy.exists():
        return legacy
    return ticket_runtime.ticket_state_path(target)

def load_ticket_run(target: Path) -> dict[str, Any] | None:
    try:
        data, _path, _text = ticket_runtime.load_ticket_run(target)
    except SystemExit:
        return None
    return data if isinstance(data, dict) else None

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

def ticket_campaign_terminal(target: Path) -> tuple[str | None, str]:
    data = load_ticket_run(target)
    if not data or not bool(data.get("halt_when_complete", True)):
        return None, "ticket campaign inactive"
    if queued_manifests(target):
        return None, "ticket campaign has queued role patches"
    raw_tickets = data.get("tickets")
    items = [item for item in raw_tickets if isinstance(item, dict)] if isinstance(raw_tickets, list) else []
    if not items:
        return None, "ticket campaign has no tickets"
    statuses = [ticket_status(item) for item in items]
    all_done = all(status == "done" for status in statuses) and all(ticket_has_evidence(item) for item in items)
    if all_done:
        return "complete", "ticket campaign complete"
    all_terminal = all(status in {"done", "blocked"} for status in statuses)
    if all_terminal and any(status == "blocked" for status in statuses):
        return "blocked", "ticket campaign blocked"
    return None, "ticket campaign active"

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
