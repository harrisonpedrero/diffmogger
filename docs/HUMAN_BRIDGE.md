# Human Bridge

The human bridge lets Codex ask for meaningful manual unlocks without blocking the whole automation workflow.

## When To Ask

Ask the human for:

- account/API setup
- paid-tier approval
- deployment/domain setup
- high-impact product direction
- risky external side effects
- environment fixes only the human can perform

Do not ask for routine implementation choices. Pick a safe default and document it.

## Style A: File Queue

This is the recommended first mode.

```text
docs/HUMAN_REQUESTS.md
docs/HUMAN_INBOX.md
docs/HUMAN_OUTBOX.md
docs/HUMAN_RESPONSES_ARCHIVE.md
```

Codex writes a request. The human manually writes a reply in `HUMAN_INBOX.md`. The next run handles the reply, removes it from the inbox, and appends a concise archive entry.

`HUMAN_INBOX.md` is also where freeform human commands may appear. If the human writes `send me a summary`, `text me the current blocker`, `status update`, or similar, the automation should interpret that as a request for an outbound SMS/WhatsApp response when the notifier is available. It should not satisfy that request only by writing a local Markdown note.

## Style B: Bundled Local Notifier Service

Diffmogger includes a reusable notifier service:

```text
services/agentic-notifier/
```

Advanced users can run it locally. The target project automation may call:

```text
POST http://127.0.0.1:8765/api/notify
```

The notifier sends SMS/WhatsApp through Twilio and writes replies into the configured target project file:

```text
docs/HUMAN_INBOX.md
```

The notifier owns:

- Twilio credentials
- external webhook server
- ngrok or public tunnel
- signature validation
- outbound and inbound dedupe
- dry-run mode
- optional JSONL queue files

The target project owns:

- request files
- inbox processing
- archive cleanup
- automation status
- interpreting freeform human commands
- fallback records when the notifier is unavailable

## Human-Unlock Request Shape

Each request should include:

- request id
- type
- priority
- summary
- context
- agent recommendation
- minimum user action
- reply format
- work the agent can continue meanwhile
- dedupe key

Example payload:

```json
{
  "request_id": "HR-2026-04-29-001",
  "type": "api_key_setup",
  "priority": "unlocking",
  "summary": "Add Service X read-only API key",
  "context": "This unlocks the next source adapter while offline fixtures remain available.",
  "agent_recommendation": "Use read-only/data-only access. Do not grant write, billing, admin, or production permissions.",
  "minimum_user_action": "Add SERVICE_X_API_KEY to your local secret store and reply HR-001 DONE.",
  "reply_format": "HR-001 DONE or HR-001 SKIP",
  "unblocked_work_remaining": [
    "Continue fixture-based dashboard work",
    "Continue report polish"
  ],
  "dedupe_key": "HR-2026-04-29-001:v1"
}
```

## Direct Status/Update Message Shape

When a human inbox entry asks for a summary, status update, or direct reply by text, use a direct outbound message payload if the notifier supports `message_body`:

```json
{
  "request_id": "MSG-2026-04-29-001",
  "type": "human_requested_summary",
  "priority": "normal",
  "summary": "Progress summary requested by human",
  "message_body": "Project update: Built X, Y, and Z. Checks passing: tests/build. Current blocker: none. Next sprint: improve the report path.",
  "agent_recommendation": "No action needed unless you want to review the generated artifacts.",
  "minimum_user_action": "None.",
  "reply_format": "Optional follow-up request.",
  "unblocked_work_remaining": [
    "Continue current automation sprint"
  ],
  "dedupe_key": "MSG-2026-04-29-001:v1",
  "expects_reply": false
}
```

If the notifier is unavailable:

1. Do not claim a text was sent.
2. Write the intended message to `docs/HUMAN_OUTBOX.md` with status `NOTIFIER_UNREACHABLE`.
3. Keep or annotate the inbox entry as unresolved if a response is still required.
4. Continue useful work where possible.

## Inbound Handling

At the start of every run:

1. Read `docs/HUMAN_INBOX.md`.
2. Match unhandled replies to active requests.
3. Classify freeform commands as outbound text, local artifact creation, product direction, or request resolution.
4. Apply safe responses.
5. Send a notifier response when the human asked to be texted or sent a status update.
6. Remove handled inbox entries only after the requested action has been completed or intentionally deferred.
7. Append concise archive entries.
8. Update automation status.

Outbound SMS/WhatsApp responses should target 300-900 characters, use at most five short bullets, avoid raw stack traces, avoid secrets or sensitive environment details, and avoid embedded URLs unless explicitly necessary and allowed by the messaging setup.

## Twilio Notes

Twilio inbound messaging webhooks send request parameters such as sender, recipient, message body, and message SID to your application. Twilio recommends using SDK signature validation rather than writing custom validation. Configure the inbound webhook URL in the Twilio Console or Messaging REST API.

For WhatsApp through Twilio, inbound customer messages can also be delivered to your application by webhook. WhatsApp notification workflows may require approved templates or session rules depending on the use case.

For outbound SMS, the notifier supports either `TWILIO_MESSAGING_SERVICE_SID` or `TWILIO_FROM`. If `TWILIO_MESSAGING_SERVICE_SID` is set, the service sends with `messaging_service_sid` and does not pass `from_`; otherwise it falls back to `TWILIO_FROM`.

SMS via US +1 10DLC may require A2P 10DLC approval before sends work. Twilio error `30034` usually means the sender or campaign is not registered or ready. The notifier returns structured JSON for provider failures and writes `PROVIDER_SEND_FAILED` to `docs/HUMAN_OUTBOX.md` when target paths are configured.

Diffmogger does not require SMS. File-only mode is valid, and WhatsApp sandbox mode can be used when configured.

## Running The Bundled Service

```bash
cd services/agentic-notifier
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python -m agentic_notifier.run_service
```

Expose only the webhook port:

```bash
ngrok http 8787
```

Configure Twilio inbound webhook:

```text
https://<ngrok-domain>/twilio/inbound
```

Set `WEBHOOK_PUBLIC_BASE_URL` to the same ngrok origin.

## Official Sources

- [Twilio incoming message webhook request](https://www.twilio.com/docs/messaging/guides/webhook-request)
- [Twilio messaging webhooks](https://www.twilio.com/docs/usage/webhooks/messaging-webhooks)
- [Twilio Messages resource](https://www.twilio.com/docs/sms/api/message)
- [Twilio WhatsApp overview](https://www.twilio.com/docs/sms/whatsapp/api)
