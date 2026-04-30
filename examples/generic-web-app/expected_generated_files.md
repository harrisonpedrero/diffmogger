# Expected Generated Files: FocusBoard

The generation prompt should produce:

```text
AGENTS.md
.agentic/automation_prompt.md
docs/INITIAL_BOOTSTRAP_PROMPT.md
docs/CODEX_AUTOMATION_TASKS.md
docs/CODEX_AUTOMATION_GUARDRAILS.md
docs/HUMAN_REQUESTS.md
docs/HUMAN_INBOX.md
docs/HUMAN_OUTBOX.md
docs/HUMAN_RESPONSES_ARCHIVE.md
docs/HUMAN_BRIDGE_SETUP.md
docs/AUTONOMY_EXPERIMENT_LOG.md
docs/DAILY_AUTOMATION_REVIEW.md
```

The bootstrap prompt should ask Codex to create a local-first web app with seed data, a weekly board, task completion, daily summary, and verification commands.

The recurring automation prompt should keep improving the planning workflow beyond the first demo, record a Codex CLI worker decision each run, and handle freeform human inbox requests through the notifier when available.
