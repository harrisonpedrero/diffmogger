# Expected Generated Files: FocusBoard

The generation prompt should produce:

```text
AGENTS.md
.agentic/automation_prompt.md
docs/INITIAL_BOOTSTRAP_PROMPT.md
docs/PROJECT_CONTEXT.md
docs/CODEX_AUTOMATION_TASKS.md
docs/CODEX_AUTOMATION_GUARDRAILS.md
docs/HUMAN_REQUESTS.md
docs/HUMAN_INBOX.md
docs/HUMAN_OUTBOX.md
docs/HUMAN_RESPONSES_ARCHIVE.md
docs/HUMAN_BRIDGE_SETUP.md
docs/AUTONOMY_EXPERIMENT_LOG.md
docs/DAILY_AUTOMATION_REVIEW.md
scripts/acquire_codex_lock.sh
scripts/release_codex_lock.sh
scripts/run_codex_automation.sh
scripts/run_conveyor_automation.py
scripts/run_conveyor_automation.sh
scripts/run_observatory.py
scripts/diffmogger_browser.py
scripts/repair_environment.py
scripts/update_automation_signals.py
scripts/spawn_worker_agent.sh
scripts/summarize_worker_outputs.py
scripts/compact_agent_state.py
```

The bootstrap prompt should identify this as `fresh_project` mode and ask Codex to create a local-first web app with seed data, a weekly board, task completion, daily summary, and verification commands.

The recurring automation prompt should keep improving the planning workflow beyond the first demo, record a Codex CLI worker decision each run, use target-local automation scripts, and handle file-only human inbox requests without SMS/notifier language.
