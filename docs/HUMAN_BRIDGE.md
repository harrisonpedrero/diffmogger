# Human Bridge

The human bridge lets automation ask for real manual input without freezing unrelated work. Human input is typed target state first; notifications are delivery aids.

## When To Ask

Ask for account setup, paid-tier approval, production/deploy actions, risky side effects, or high-impact direction. For routine implementation choices, choose a reversible default and record the assumption.

## Modes

- `file_only`: dashboard-backed typed human-message state only.
- `apprise_notifier`: typed state plus outbound delivery through the loopback Apprise notifier service.
- `local_notifier`: compatibility alias for local Apprise routes such as `macosx://`.
- `disabled`: no human bridge queue required.

In `file_only` mode, summary or status requests are answered through the dashboard or an explicitly requested local artifact. No Apprise, webhook, notifier API, or messaging credentials are used in this mode.

## Runtime State

Canonical bridge records live in `.diffmogger/runtime/orchestration.sqlite3` and are exposed by the dashboard. Generated Markdown/JSONL inbox and outbox files are projections for audit and migration. A message is resolved only after the requested action is complete or intentionally deferred with a concise note.

Human input is planning context. If useful independent work remains, the scheduler should create or continue setup, fixture, mock, repair, defer, split, reframe, review, documentation, or alternate validation work instead of stopping.

## Apprise Notifier

The reusable service lives in:

```text
services/agentic-notifier/
```

Target automation may call:

```text
POST http://127.0.0.1:8765/api/notify
```

The service owns Apprise URLs, outbound dedupe, dry-run behavior, loopback/API-token safety, and audit projections. Target projects must not import notifier internals or store notifier credentials.

Example direct message:

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

If the notifier is unavailable, do not claim delivery. Record the intended message in typed human-message state with `NOTIFIER_UNREACHABLE`, keep unresolved input active if a reply is still required, and continue useful work where possible.

## Setup

```bash
cd services/agentic-notifier
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python -m agentic_notifier.run_service
```

The example config starts with `DRY_RUN=true`; change it only after target-side state handling and Apprise routes are verified.
