# Human Outbox

Lightweight audit log of outbound human requests sent or attempted through the local notifier service.

Use this file for:

- human-unlock requests sent through the notifier
- direct status/update responses sent because the human asked to be texted
- failed notifier attempts with status `NOTIFIER_UNREACHABLE`

Do not write secrets, raw stack traces, or long reports here.

## Outbound Notifications

None yet.

## Entry Template

```markdown
### OUTBOX-YYYY-MM-DD-001

- sent_at: YYYY-MM-DDTHH:MM:SS
- request_id: MSG-YYYY-MM-DD-001
- type: human_requested_summary
- status: sent | dry_run | NOTIFIER_UNREACHABLE
- dedupe_key: MSG-YYYY-MM-DD-001:v1

#### Message

Concise phone-friendly message body.
```
