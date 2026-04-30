# Diffmogger Agentic Notifier

Agentic Notifier is Diffmogger's reusable local SMS/WhatsApp bridge. A target project can call a loopback HTTP API when its Codex automation needs human input; this service owns Twilio credentials, webhook handling, duplicate suppression, and writes replies back into the target project's handoff files.

Target projects should not import this code. They only need:

- `POST http://127.0.0.1:8765/api/notify`
- the target markdown paths where requests, outbox entries, and inbound replies are written

## Install

```bash
cd services/agentic-notifier

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Create local configuration:

```bash
cp .env.example .env
```

Edit `.env` locally. Real Twilio values belong in this service's local `.env`, never in a generated target project and never in Codex-visible task files.

Use a virtual environment. Do not install packages into Homebrew/system Python if it reports an externally managed environment.

## Target Project Paths

Set `TARGET_REPO_DIR` to the absolute path of the target project. If explicit paths are left unset, the service uses these files under that repo:

```text
docs/HUMAN_INBOX.md
docs/HUMAN_REQUESTS.md
docs/HUMAN_OUTBOX.md
docs/HUMAN_RESPONSES_ARCHIVE.md
```

The notifier creates these files if missing. The target automation is responsible for consuming handled inbox entries and archiving concise resolution notes.

Optional JSONL queues can also be enabled:

```text
TARGET_QUEUE_DIR=/absolute/path/to/target-project/queue
```

When set, the notifier appends `human_requests.jsonl`, `human_outbox.jsonl`, and `human_responses.jsonl` in that directory in addition to Markdown.

## Run

Default one-process runner:

```bash
python -m agentic_notifier.run_service
```

Default ports:

- Local target-project API: `http://127.0.0.1:8765`
- Twilio webhook receiver: `http://127.0.0.1:8787`

## Twilio Sender Configuration

The notifier supports either a Twilio Messaging Service SID or a direct sender:

```text
TWILIO_MESSAGING_SERVICE_SID=MGxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_FROM=+15555555555
```

If `TWILIO_MESSAGING_SERVICE_SID` is set, outbound sends use `messaging_service_sid` and do not pass `from_`. If it is empty, sends fall back to `TWILIO_FROM`.

SMS via US +1 10DLC may require A2P 10DLC approval before real outbound sends work. Twilio error `30034` usually means the sender or campaign is not registered or ready. File-only mode, `DRY_RUN=true`, or WhatsApp sandbox mode are valid while SMS setup is pending.

If you prefer separate processes:

```bash
python -m agentic_notifier.api_app
python -m agentic_notifier.webhook_app
```

## Health

```bash
curl http://127.0.0.1:8765/health
```

## Notify API

Target projects call:

```text
POST http://127.0.0.1:8765/api/notify
```

Human-unlock request payload:

```json
{
  "request_id": "HR-2026-04-29-001",
  "type": "api_key_setup",
  "priority": "unlocking",
  "summary": "Add Service X read-only API key",
  "context": "This unlocks the next source adapter while offline fixtures remain available.",
  "agent_recommendation": "Use read-only/data-only access. Do not add trading or write permissions.",
  "minimum_user_action": "Add SERVICE_X_API_KEY to your local secret store and reply HR-001 DONE.",
  "reply_format": "HR-001 DONE or HR-001 SKIP",
  "unblocked_work_remaining": [
    "Continue fixture-based dashboard work",
    "Continue report polish"
  ],
  "dedupe_key": "HR-2026-04-29-001:v1"
}
```

Direct human-requested status/update payload:

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

Use `message_body` for concise SMS/WhatsApp responses to freeform human requests such as "send me a status update". Use `expects_reply: false` when the outbound message is a response, not a new request to track in `docs/HUMAN_REQUESTS.md`.

Response:

```json
{
  "ok": true,
  "request_id": "HR-2026-04-29-001",
  "sent": true,
  "dry_run": false,
  "deduped": false,
  "message_preview": "Need input: HR-001 ..."
}
```

Provider/config failures return structured JSON and are recorded in the target outbox when target paths are configured:

```json
{
  "detail": {
    "ok": false,
    "error_type": "provider_send_failed",
    "provider": "twilio",
    "provider_error_code": "30034",
    "message": "Twilio rejected the message because the A2P 10DLC campaign is not ready or the sender is not registered for this route.",
    "hint": "Twilio error 30034 usually means the A2P 10DLC campaign is not ready or the sender is not registered for this route."
  }
}
```

The outbox status for provider failures is `PROVIDER_SEND_FAILED`; target automations should not claim a text was sent.

If `LOCAL_NOTIFY_API_TOKEN` is set, include:

```text
Authorization: Bearer <token>
```

Without a token, the API must remain bound to loopback.

## Dry-Run Outbound Test

Start the service with `DRY_RUN=true` or use the test script, which forces `"dry_run": true` unless `--real-send` is passed:

```bash
python scripts/send_test_notification.py
```

Test the direct status/update payload:

```bash
python scripts/send_test_notification.py --direct
```

This writes target Markdown handoff files and does not send real SMS.

## Inbound Webhook

Expose only the webhook port:

```bash
ngrok http 8787
```

Configure the Twilio inbound webhook to:

```text
https://<ngrok-domain>/twilio/inbound
```

Set:

```text
WEBHOOK_PUBLIC_BASE_URL=https://<ngrok-domain>
```

Do not expose `http://127.0.0.1:8765/api/notify` through ngrok.

The webhook endpoint is:

```text
POST http://127.0.0.1:8787/twilio/inbound
```

It validates Twilio signatures, parses the reply, dedupes by `MessageSid`, and appends unhandled entries to `docs/HUMAN_INBOX.md`.

## Dry-Run Inbound Test

Exercise inbox writing without Twilio or ngrok:

```bash
python scripts/dry_run_inbound.py "HR-001 DONE. Key added locally."
```

To test the HTTP webhook locally, set `AGENTIC_NOTIFIER_TEST_MODE=true` and post form fields with:

```text
X-Agentic-Notifier-Test-Bypass: true
```

## Reply Parsing

Supported examples:

- `HR-001 DONE`
- `HR-2026-04-29-001 DONE`
- `DONE HR-001`
- `skip HR-001`
- `approve HR-001`
- `reject HR-001`
- free text containing a request id

Parsed intents:

```text
done
skip
approve
reject
info
unknown
```

## Duplicate Suppression

Runtime state lives under:

```text
runtime/sent_notifications.jsonl
runtime/inbound_message_sids.jsonl
```

Outbound notifications dedupe by `dedupe_key`. Inbound webhook retries dedupe by `MessageSid`.

## Tests

```bash
python -m pytest
```

Tests use fake Twilio clients or test bypasses. They do not require real credentials, ngrok, or real SMS.

## Security Notes

- Do not commit `.env`.
- Do not print secrets.
- Keep the notify API bound to `127.0.0.1` unless you configure a token and understand the risk.
- Expose only the webhook port through ngrok.
- Use dry-run mode while wiring a new target project.
