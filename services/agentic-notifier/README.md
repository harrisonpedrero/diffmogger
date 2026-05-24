# Diffmogger Agentic Notifier

Agentic Notifier is Diffmogger's reusable local outbound notification service. It exposes a loopback HTTP API, records typed-friendly audit projections for target repos, dedupes outbound messages, and delegates delivery to [Apprise](https://github.com/caronc/apprise).

Target projects should not import this package or store notifier secrets. They call:

```text
POST http://127.0.0.1:8765/api/notify
```

Canonical human-message state belongs in the target's `.diffmogger/runtime/orchestration.sqlite3`. Markdown and JSONL files written by this service are audit projections and migration aids.

## Install

```bash
cd services/agentic-notifier
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

Real Apprise URLs belong only in `services/agentic-notifier/.env`.

## Configure

The example config starts with `DRY_RUN=true`.

```text
APPRISE_URLS=macosx://
TARGET_REPO_DIR=/absolute/path/to/target-project
NOTIFIER_API_HOST=127.0.0.1
NOTIFIER_API_PORT=8765
LOCAL_NOTIFY_API_TOKEN=
DRY_RUN=true
```

Use any Apprise URL supported by your local environment, such as `macosx://`, a webhook route, email, or a chat provider URL. Multiple routes can be comma-separated or newline-separated. Keep all credentials local and out of target repos, prompts, and generated task files.

Bind the API to `127.0.0.1` unless `LOCAL_NOTIFY_API_TOKEN` is configured. When a token is set, callers must send:

```text
Authorization: Bearer <token>
```

## Run

```bash
python -m agentic_notifier.run_service
curl http://127.0.0.1:8765/health
```

In dry-run mode, `/api/notify` writes audit records and returns an Apprise dry-run delivery without sending.

## Notify API

Progress payload:

```json
{
  "request_id": "PROG-2026-04-29-001",
  "type": "automation_progress",
  "priority": "normal",
  "summary": "Integrated one patch",
  "event_kind": "progress",
  "message_body": "Integrated one patch and verification passed.",
  "dedupe_key": "PROG-2026-04-29-001:v1",
  "expects_reply": false,
  "dry_run": true
}
```

Human-message payload:

```json
{
  "request_id": "MSG-2026-04-29-001",
  "type": "human_requested_summary",
  "priority": "normal",
  "summary": "Progress summary requested",
  "event_kind": "message",
  "message_body": "Project update: checks are passing and no action is needed.",
  "minimum_user_action": "None.",
  "reply_format": "Optional follow-up request.",
  "dedupe_key": "MSG-2026-04-29-001:v1",
  "expects_reply": false,
  "dry_run": true
}
```

Response:

```json
{
  "ok": true,
  "request_id": "MSG-2026-04-29-001",
  "sent": false,
  "dry_run": true,
  "deduped": false,
  "message_preview": "Project update: checks are passing...",
  "deliveries": {
    "apprise": {
      "enabled": true,
      "ok": true,
      "sent": false,
      "dry_run": true,
      "status": "dry_run",
      "detail": "Apprise delivery skipped by dry-run mode."
    }
  }
}
```

Delivery failures use statuses such as `APPRISE_SEND_FAILED` or `NOTIFIER_UNREACHABLE`. Target automations should record those statuses in typed human-message state and should not claim delivery unless the notifier response shows success or dry-run intent.

## Target Audit Files

When `TARGET_REPO_DIR` points at a sidecar target, the service writes audit projections under:

```text
.diffmogger/state/HUMAN_INBOX.md
.diffmogger/state/HUMAN_REQUESTS.md
.diffmogger/state/HUMAN_OUTBOX.md
.diffmogger/state/HUMAN_RESPONSES_ARCHIVE.md
```

Older targets without a sidecar use `docs/` paths. Optional JSONL audit queues can be enabled with:

```text
TARGET_QUEUE_DIR=/absolute/path/to/target-project/queue
```

## Dry-Run Helpers

```bash
python scripts/send_test_notification.py --progress
python scripts/send_test_notification.py
python scripts/dry_run_inbound.py "HR-001 DONE. Key added locally."
```

`dry_run_inbound.py` writes a generic inbound audit record only. It does not run a chat listener; inbound handling should be represented in typed target state before automation treats a response as resolved.

## Safety

- Keep Apprise URLs and API tokens only in local service config.
- Keep `DRY_RUN=true` until routes and target audit paths are verified.
- Bind to loopback unless a bearer token is configured.
- Treat notifier files as projections, not target runtime authority.
- Keep generated target repos decoupled from this service implementation.

## Tests

```bash
python -m pytest
```

Tests use dry-run Apprise paths and local files. They do not require real notification credentials.
