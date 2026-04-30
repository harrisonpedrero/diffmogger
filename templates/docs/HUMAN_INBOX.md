# Human Inbox

Active inbox for replies from the human owner.

The separate local notifier service may write inbound SMS/WhatsApp replies here. In file-only mode, the human can paste replies here manually.

At the start of every automation run, Codex should:

1. read this file
2. handle any `status: unhandled` messages, including structured replies and freeform commands
3. update related requests in `docs/HUMAN_REQUESTS.md`
4. send a notifier response if the human asked to be texted, messaged, or sent a status update
5. remove handled messages from this file only after the requested action is complete or intentionally deferred
6. append concise records to `docs/HUMAN_RESPONSES_ARCHIVE.md`

Freeform messages such as `send me a summary`, `text me the blockers`, `status update`, or `what have you done so far?` should result in a concise SMS/WhatsApp response through `POST http://127.0.0.1:8765/api/notify` when the notifier is available. Do not satisfy those messages only by writing local Markdown.

If the notifier is unavailable, record the attempted outbound response in `docs/HUMAN_OUTBOX.md` with status `NOTIFIER_UNREACHABLE`.

Keep this file short. It is not a permanent log.

## Active Inbound Messages

None.

## Entry Template

```markdown
### INBOX-YYYY-MM-DD-001

- received_at: YYYY-MM-DDTHH:MM:SS
- channel: sms
- from: +15555555555
- request_id: HR-YYYY-MM-DD-001
- parsed_intent: done
- message_sid: SMxxxxxxxxxxxxxxxx
- status: unhandled

#### Body

HR-001 DONE. Key added locally.
```
