# AGENTS.md

This repo is `{{PROJECT_NAME}}`.

## Mission

{{PRODUCT_GOAL}}

Target user: {{TARGET_USER}}

## Read Before Meaningful Work

```text
docs/CODEX_AUTOMATION_TASKS.md
docs/CODEX_AUTOMATION_GUARDRAILS.md
.agentic/automation_prompt.md
```

If human bridge files exist, also read:

```text
docs/HUMAN_REQUESTS.md
docs/HUMAN_INBOX.md
docs/HUMAN_OUTBOX.md
docs/HUMAN_RESPONSES_ARCHIVE.md
```

## Working Rules

- Build the product; do not only write plans.
- Treat MVP as an early milestone, not the finish line.
- Use safe local defaults, fixtures, mocks, or seed data unless the task explicitly enables external integration.
- Do not read `.env` files or handle secrets.
- Do not spend money, deploy publicly, or trigger real-world side effects without explicit approval.
- Use worker agents only for bounded work and record their outputs.
- Process human inbox messages, including freeform commands.
- If the human asks to be texted, messaged, or sent a status update, use the local notifier when available instead of only writing Markdown.
- Process handled human inbox messages only after completing or intentionally deferring the requested action, then archive concise notes.
- Record `Codex CLI worker decision: USE / SKIP / UNAVAILABLE` every automation run.
- Update `docs/CODEX_AUTOMATION_TASKS.md` at the end of every automation run.

## Verification

Preferred commands:

```text
{{VERIFICATION_COMMANDS}}
```

Use the commands that actually exist. Do not claim checks passed unless they ran.
