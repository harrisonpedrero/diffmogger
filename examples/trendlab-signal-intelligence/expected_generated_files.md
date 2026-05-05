# Expected Generated Files: TrendLab

The generation prompt should produce the standard automation file set:

```text
AGENTS.md
.agentic/automation_prompt.md
.agentic/smoke_commands.txt
.agentic/verification_commands.txt
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
scripts/ticket_run.py
scripts/repair_environment.py
scripts/update_automation_signals.py
scripts/spawn_worker_agent.sh
scripts/summarize_worker_outputs.py
scripts/compact_agent_state.py
```

The bootstrap prompt should identify this as `fresh_project` mode and ask for fixture-first scoring, evidence display, report generation, and a one-command demo/test path.

The recurring automation prompt should continue through explicit intake-derived product horizon state: local scored-signal demo, scoring depth, evidence-backed reports, safe adapters, showcase quality, long-run research capsules, and automation process improvement. Each run should record whether it stayed in the current horizon or advanced with evidence.

It should also make explicit Codex CLI worker decisions, use target-local runtime scripts, and distinguish file-only Markdown responses from notifier-mode outbound status texts.

This example exercises a more involved automation workflow without copying assumptions from a real product.
