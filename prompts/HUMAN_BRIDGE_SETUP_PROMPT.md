# Human Bridge Setup Prompt

Use this when wiring a target project to Diffmogger's bundled `services/agentic-notifier` local service.

---

You are setting up a local human-intervention bridge for a Codex automation project.

Goal: keep messaging credentials outside the product repo while letting Codex request meaningful human input.

Implement or document these modes:

## Mode A: File Queue

The target project contains:

```text
.diffmogger/state/HUMAN_REQUESTS.md
.diffmogger/state/HUMAN_INBOX.md
.diffmogger/state/HUMAN_OUTBOX.md
.diffmogger/state/HUMAN_RESPONSES_ARCHIVE.md
```

Codex writes requests. The human replies manually in `HUMAN_INBOX.md`. Codex consumes and archives handled entries on the next run.

If a freeform inbox message asks the automation to `send me`, `message me`, `reply with`, provide a `status update`, answer `what have you done so far?`, or `summarize progress`, answer locally in Markdown/app artifacts in file-only mode. In notifier modes, treat it as a request for outbound `event_kind: "message"` delivery. Human-unlock requests, blockers that require user input, and replies to user messages also use `event_kind: "message"` so they route to the messaging channel. Do not claim delivery unless the notifier reports success or dry-run intent.

## Mode B: Local Desktop Notifier

The target project may call:

```text
POST http://127.0.0.1:8765/api/notify
```

Diffmogger's notifier service owns:

- native local desktop notification delivery
- local notify API delivery results
- dedupe state
- dry-run mode
- optional JSONL queues

## Mode C: Discord Notifier

Diffmogger's notifier service also supports Discord:

- Discord bot token
- progress channel routing
- messaging channel routing
- inbound bot mention/reply capture
- dedupe state
- dry-run mode
- optional JSONL queues

The notifier writes inbound replies to:

```text
.diffmogger/state/HUMAN_INBOX.md
```

The target project must not read notifier `.env` files or handle Discord credentials.

The target automation must fall back to writing `.diffmogger/state/HUMAN_REQUESTS.md` if the notifier is unavailable, use `ACTIVE_WITH_PENDING_USER_INPUT` when useful work remains, and use `BLOCKED_ON_USER` only when no useful work remains.

For human-unlock requests, document the structured request payload. For direct human-requested status/update responses, document the optional `message_body` and `expects_reply: false` payload. If the notifier is unavailable, require the automation to write the intended outbound message to `.diffmogger/state/HUMAN_OUTBOX.md` with status `NOTIFIER_UNREACHABLE` and not claim delivery.

In Discord notifier mode, document that the multi-role integrator sends a brief `event_kind: "progress"` notification after each local automation commit it creates, including the commit subject and short work summary.

Create setup docs, sample payloads, dry-run instructions, inbox cleanup rules, freeform command handling, and troubleshooting. If implementing code, use tests that do not send real Discord messages or require desktop notification delivery.
