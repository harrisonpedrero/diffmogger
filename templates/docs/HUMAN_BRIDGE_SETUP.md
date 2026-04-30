# Human Bridge Setup

This project can ask the human owner for important manual unlocks.

## Style A: Local-File-Only Mode

Files:

```text
docs/HUMAN_REQUESTS.md
docs/HUMAN_INBOX.md
docs/HUMAN_OUTBOX.md
docs/HUMAN_RESPONSES_ARCHIVE.md
```

The automation writes active requests. The human manually replies in `docs/HUMAN_INBOX.md`. The next run consumes handled replies and archives concise notes.

This is the recommended first-time setup.

## Style B: Local Diffmogger Notifier Mode

Advanced users may run Diffmogger's bundled local notifier service from the Diffmogger repo:

```text
services/agentic-notifier/
```

Project automation calls:

```text
POST http://127.0.0.1:8765/api/notify
```

The notifier sends SMS/WhatsApp through Twilio and writes replies to this target project file:

```text
docs/HUMAN_INBOX.md
```

The notifier owns credentials, dedupe state, optional JSONL queues, and external webhooks. This repo must not read notifier `.env` files or handle Twilio credentials.

The target automation must read `docs/HUMAN_INBOX.md` at the start of each run, remove handled inbox entries, and archive concise resolution notes in `docs/HUMAN_RESPONSES_ARCHIVE.md`.

If a human inbox message asks the automation to `send me`, `text me`, `message me`, `reply with`, provide a `status update`, or summarize progress, the target automation should send a concise SMS/WhatsApp response through the notifier. It should not satisfy that request only by writing Markdown.

If the notifier is unavailable, the automation must not claim a text was sent. It should write the intended outbound message to `docs/HUMAN_OUTBOX.md` with status `NOTIFIER_UNREACHABLE`, keep unresolved inbox entries active when needed, and continue safe work.

Twilio sender notes:

- Prefer `TWILIO_MESSAGING_SERVICE_SID` when using a Twilio Messaging Service; the notifier will send with `messaging_service_sid` and omit `TWILIO_FROM`.
- If no Messaging Service SID is configured, the notifier falls back to `TWILIO_FROM`.
- SMS via +1 10DLC may require A2P 10DLC approval before outbound messages work.
- Twilio error `30034` usually means the sender or A2P campaign is not registered or ready.
- WhatsApp sandbox can be used instead of SMS when configured.

## Example Payload

Human-unlock request:

```json
{
  "request_id": "HR-YYYY-MM-DD-001",
  "type": "api_key_setup",
  "priority": "unlocking",
  "summary": "Add read-only API key for Service X",
  "context": "This unlocks a safe optional integration while local fixtures remain available.",
  "agent_recommendation": "Use read-only/data-only access. Do not add trading or write permissions.",
  "minimum_user_action": "Add SERVICE_X_API_KEY to your local secret store and reply HR-001 DONE.",
  "reply_format": "HR-001 DONE or HR-001 SKIP",
  "unblocked_work_remaining": ["Continue fixture-based product work"],
  "dedupe_key": "HR-YYYY-MM-DD-001:v1"
}
```

Direct status/update response, if the notifier supports `message_body`:

```json
{
  "request_id": "MSG-YYYY-MM-DD-001",
  "type": "human_requested_summary",
  "priority": "normal",
  "summary": "Progress summary requested by human",
  "message_body": "{{PROJECT_NAME}} update: Built X, Y, Z. Checks passing: A/B/C. Current blocker: none. Next sprint: <short next task>.",
  "minimum_user_action": "None.",
  "reply_format": "Optional follow-up request.",
  "unblocked_work_remaining": ["Continue current automation sprint"],
  "dedupe_key": "MSG-YYYY-MM-DD-001:v1",
  "expects_reply": false
}
```

## Inbox Handling Rules

- Treat `docs/HUMAN_INBOX.md` as an active queue, not a permanent log.
- Handle structured replies such as `HR-001 DONE` and freeform commands.
- Remove handled inbox entries only after the requested action is complete or intentionally deferred.
- Archive concise resolution notes in `docs/HUMAN_RESPONSES_ARCHIVE.md`.
- Record outbound messages and notifier failures in `docs/HUMAN_OUTBOX.md`.

## Notifier Safety

- Bind local notify API to `127.0.0.1`.
- Expose only the inbound webhook receiver through ngrok or another tunnel.
- Do not expose `http://127.0.0.1:8765/api/notify` through ngrok.
- Validate Twilio webhook signatures with the official SDK.
- Dedupe outbound requests and inbound webhook retries.
- Support dry-run mode.
- Keep active inbox files short.
