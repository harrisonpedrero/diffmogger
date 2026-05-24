from __future__ import annotations

from .common import *

def post_notifier(payload: dict[str, Any]) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    token = os.getenv("LOCAL_NOTIFY_API_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        os.getenv("DIFFMOGGER_NOTIFY_URL", NOTIFIER_URL),
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        body = response.read().decode("utf-8", errors="replace")
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return {"ok": True, "raw_body": body[:500]}
    return data if isinstance(data, dict) else {"ok": False, "raw_body": body[:500]}

def commit_subject(message: str) -> str:
    for raw in message.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if line:
            return line[:160]
    return "local automation commit"

def notify_commit_progress(
    target: Path,
    *,
    commit_hash: str | None,
    commit_message: str,
    description: str,
    run_id: str,
    dry_run: bool,
) -> dict[str, Any]:
    if dry_run:
        return {"status": "dry_run"}
    if not commit_hash:
        return {"status": "no_commit"}
    if human_bridge_mode(target) not in {"apprise_notifier", "local_notifier"}:
        return {"status": "disabled", "detail": "human bridge mode does not use notifier delivery"}

    short_hash = commit_hash[:12]
    subject = commit_subject(commit_message)
    body = (
        f"New local automation commit `{short_hash}`\n\n"
        f"Commit: {subject}\n"
        f"Work: {progress_inline(description, target, limit=500)}"
    )
    payload = {
        "request_id": f"COMMIT-{short_hash}",
        "type": "automation_commit_progress",
        "priority": "normal",
        "summary": f"New local commit: {subject}",
        "event_kind": "progress",
        "context": f"Integrator run {run_id} created local commit {short_hash}.",
        "message_body": body,
        "agent_recommendation": "Review the local commit when convenient; no reply required.",
        "minimum_user_action": "None.",
        "reply_format": "No reply required.",
        "unblocked_work_remaining": [],
        "dedupe_key": f"commit-progress:{commit_hash}",
        "expects_reply": False,
    }
    try:
        delivered = post_notifier(payload)
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        print(f"WARN: commit progress notification failed for {short_hash}: {exc}", file=sys.stderr)
        return {"status": "notifier_unreachable", "detail": str(exc)}
    if not delivered.get("ok"):
        print(
            f"WARN: commit progress notification was not delivered for {short_hash}: "
            f"{json.dumps(delivered, sort_keys=True)[:500]}",
            file=sys.stderr,
        )
        return {"status": "notifier_failed", "detail": delivered}
    return {"status": "sent_notifier", "detail": delivered}
