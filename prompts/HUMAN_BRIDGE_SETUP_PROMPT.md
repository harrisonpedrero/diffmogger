# Human Bridge Setup Prompt

Use this when wiring a target project to Diffmogger's bundled `services/agentic-notifier` local service.

---

You are setting up a local human-intervention bridge for a Codex automation project.

Goal: keep messaging credentials outside the product repo while letting Codex request meaningful human input.

Implement or document these modes:

## Mode A: Dashboard Queue

The target project stores human requests, replies, outbound delivery records, and resolution notes in typed SQLite state exposed through the Diffmogger dashboard.

Codex writes requests. The human replies in the dashboard. Codex consumes and marks handled entries resolved on the next run.

If a freeform dashboard message asks the automation to `send me`, `message me`, `reply with`, provide a `status update`, answer `what have you done so far?`, or `summarize progress`, answer through the dashboard or requested artifact in file-only mode. In notifier modes, treat it as a request for outbound `event_kind: "message"` delivery. Do not claim delivery unless the notifier reports success or dry-run intent.

## Mode B: Apprise Notifier

The target project may call:

```text
POST http://127.0.0.1:8765/api/notify
```

Diffmogger's notifier service owns:

- Apprise route URLs and delivery credentials
- outbound delivery results
- dedupe state
- dry-run mode
- audit Markdown/JSONL projections

`local_notifier` is a compatibility label for local Apprise routes such as `macosx://`. `apprise_notifier` is the preferred mode name.

The target project must not read notifier `.env` files or handle Apprise credentials.

The target automation must fall back to typed human-message state if the notifier is unavailable. When the current compatibility status vocabulary is in use, `ACTIVE_WITH_PENDING_USER_INPUT` can annotate pending input while independent work remains, and `BLOCKED_ON_USER` should be rare because repair, setup, mock, defer, split, reframe, review, documentation, or alternate-ticket work usually remains possible.

For human-unlock requests, document the structured request payload. For direct human-requested status/update responses, document the optional `message_body` and `expects_reply: false` payload. If the notifier is unavailable, require the automation to record the intended outbound message in typed human-message state with status `NOTIFIER_UNREACHABLE` and not claim delivery.

In Apprise notifier mode, document that the integrator can send a brief `event_kind: "progress"` notification after local automation commits, including the commit subject and short work summary.

Create setup docs, sample payloads, dry-run instructions, inbox cleanup rules, freeform command handling, and troubleshooting. If implementing code, use tests that do not send real Apprise messages.
