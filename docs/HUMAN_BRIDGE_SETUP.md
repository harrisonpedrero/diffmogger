# Human Bridge Setup

This project uses file-only human intervention.

## Local-File-Only Mode

Files:

```text
docs/HUMAN_REQUESTS.md
docs/HUMAN_INBOX.md
docs/HUMAN_OUTBOX.md
docs/HUMAN_RESPONSES_ARCHIVE.md
```

The automation writes active requests to `docs/HUMAN_REQUESTS.md`. The human manually replies in `docs/HUMAN_INBOX.md`. The next run consumes handled replies and archives concise notes.

No Discord, webhook, notifier API, or messaging credentials are used in this mode.

If a human inbox message asks for a summary, status update, report, explanation, or decision record, the automation should satisfy it locally by updating the relevant Markdown file or app artifact.

## Inbox Handling Rules

- Treat `docs/HUMAN_INBOX.md` as an active queue, not a permanent log.
- Handle structured replies such as `HR-001 DONE` and freeform commands.
- Remove handled inbox entries only after the requested action is complete or intentionally deferred.
- Archive concise resolution notes in `docs/HUMAN_RESPONSES_ARCHIVE.md`.
- Keep active inbox files short.
