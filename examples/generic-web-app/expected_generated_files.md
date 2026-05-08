# Expected Generated Files: FocusBoard

The generation prompt should produce:

```text
AGENTS.md
.diffmogger/manifest.json
.diffmogger/agentic/automation_prompt.md
.diffmogger/agentic/smoke_commands.txt
.diffmogger/agentic/verification_commands.txt
.diffmogger/state/INITIAL_BOOTSTRAP_PROMPT.md
.diffmogger/state/PROJECT_CONTEXT.md
.diffmogger/state/CODEX_AUTOMATION_TASKS.md
.diffmogger/state/CODEX_AUTOMATION_GUARDRAILS.md
.diffmogger/state/HUMAN_REQUESTS.md
.diffmogger/state/HUMAN_INBOX.md
.diffmogger/state/HUMAN_OUTBOX.md
.diffmogger/state/HUMAN_RESPONSES_ARCHIVE.md
.diffmogger/state/HUMAN_BRIDGE_SETUP.md
.diffmogger/state/AUTONOMY_EXPERIMENT_LOG.md
.diffmogger/state/DAILY_AUTOMATION_REVIEW.md
.diffmogger/scripts/acquire_codex_lock.sh
.diffmogger/scripts/release_codex_lock.sh
.diffmogger/scripts/run_codex_automation.sh
.diffmogger/scripts/run_process_watchdog.py
.diffmogger/scripts/run_conveyor_automation.py
.diffmogger/scripts/run_conveyor_automation.sh
.diffmogger/scripts/run_observatory.py
.diffmogger/scripts/diffmogger_browser.py
.diffmogger/scripts/diffmogger_paths.py
.diffmogger/scripts/load_automation_env.py
.diffmogger/scripts/ticket_run.py
.diffmogger/scripts/repair_environment.py
.diffmogger/scripts/update_automation_signals.py
.diffmogger/scripts/spawn_worker_agent.sh
.diffmogger/scripts/summarize_worker_outputs.py
.diffmogger/scripts/compact_agent_state.py
```

The bootstrap prompt should identify this as `fresh_project` mode and ask Codex to create a local-first web app with seed data, a weekly board, task completion, daily summary, and verification commands.

The generated `.diffmogger/agentic/verification_commands.txt` should start with bootstrap-safe commands that pass before the web app package scripts exist; preferred future app checks should stay documented until bootstrap creates them.

The recurring automation prompt should keep improving the planning workflow after the first demo, record intake-derived horizons for weekly boards, daily summaries, review capsules, and optional adapters, record a Codex CLI worker decision each run, use target-local automation scripts, and handle file-only human inbox requests without notifier API language.
