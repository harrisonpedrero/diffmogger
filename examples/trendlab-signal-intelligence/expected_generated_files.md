# Expected Generated Files: TrendLab

The generation prompt should produce the standard automation file set:

```text
AGENTS.md
.diffmogger/manifest.json
.diffmogger/lib/diffmogger/__init__.py
.diffmogger/lib/diffmogger/conveyor/__init__.py
.diffmogger/lib/diffmogger/conveyor/active_role.py
.diffmogger/lib/diffmogger/conveyor/baseline.py
.diffmogger/lib/diffmogger/conveyor/cli.py
.diffmogger/lib/diffmogger/conveyor/decisions.py
.diffmogger/lib/diffmogger/conveyor/locks.py
.diffmogger/lib/diffmogger/conveyor/progress.py
.diffmogger/lib/diffmogger/conveyor/queue_state.py
.diffmogger/lib/diffmogger/conveyor/runner.py
.diffmogger/lib/diffmogger/conveyor/state.py
.diffmogger/lib/diffmogger/conveyor/tickets.py
.diffmogger/lib/diffmogger/integrator/__init__.py
.diffmogger/lib/diffmogger/integrator/baseline.py
.diffmogger/lib/diffmogger/integrator/cleanup.py
.diffmogger/lib/diffmogger/integrator/cli.py
.diffmogger/lib/diffmogger/integrator/commits.py
.diffmogger/lib/diffmogger/integrator/common.py
.diffmogger/lib/diffmogger/integrator/git_safety.py
.diffmogger/lib/diffmogger/integrator/locks.py
.diffmogger/lib/diffmogger/integrator/notifier.py
.diffmogger/lib/diffmogger/integrator/patching.py
.diffmogger/lib/diffmogger/integrator/progress.py
.diffmogger/lib/diffmogger/integrator/queue.py
.diffmogger/lib/diffmogger/integrator/runtime_state.py
.diffmogger/lib/diffmogger/integrator/verification.py
.diffmogger/lib/diffmogger/observatory/__init__.py
.diffmogger/lib/diffmogger/observatory/cli.py
.diffmogger/lib/diffmogger/observatory/common.py
.diffmogger/lib/diffmogger/observatory/git_state.py
.diffmogger/lib/diffmogger/observatory/html_render.py
.diffmogger/lib/diffmogger/observatory/markdown_render.py
.diffmogger/lib/diffmogger/observatory/queue_state.py
.diffmogger/lib/diffmogger/observatory/scoring.py
.diffmogger/lib/diffmogger/observatory/self_review.py
.diffmogger/lib/diffmogger/observatory/server.py
.diffmogger/lib/diffmogger/observatory/signals.py
.diffmogger/lib/diffmogger/observatory/snapshots.py
.diffmogger/lib/diffmogger/runtime/__init__.py
.diffmogger/lib/diffmogger/runtime/build_replay.py
.diffmogger/lib/diffmogger/runtime/compact_agent_state.py
.diffmogger/lib/diffmogger/runtime/diffmogger_browser.py
.diffmogger/lib/diffmogger/runtime/integrate_role_outputs.py
.diffmogger/lib/diffmogger/runtime/list_deferred_patches.py
.diffmogger/lib/diffmogger/runtime/load_automation_env.py
.diffmogger/lib/diffmogger/runtime/paths.py
.diffmogger/lib/diffmogger/runtime/repair_environment.py
.diffmogger/lib/diffmogger/runtime/run_conveyor_automation.py
.diffmogger/lib/diffmogger/runtime/run_observatory.py
.diffmogger/lib/diffmogger/runtime/run_process_watchdog.py
.diffmogger/lib/diffmogger/runtime/summarize_worker_outputs.py
.diffmogger/lib/diffmogger/runtime/ticket_run.py
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
.diffmogger/state/DEVELOPMENT.md
.diffmogger/scripts/acquire_codex_lock.sh
.diffmogger/scripts/release_codex_lock.sh
.diffmogger/scripts/run_codex_automation.sh
.diffmogger/scripts/build_replay.py
.diffmogger/scripts/run_process_watchdog.py
.diffmogger/scripts/run_conveyor_automation.py
.diffmogger/scripts/run_conveyor_automation.sh
.diffmogger/scripts/run_observatory.py
.diffmogger/scripts/diffmogger_browser.py
.diffmogger/scripts/diffmogger_paths.py
.diffmogger/scripts/integrate_role_outputs.py
.diffmogger/scripts/list_deferred_patches.py
.diffmogger/scripts/load_automation_env.py
.diffmogger/scripts/ticket_run.py
.diffmogger/scripts/repair_environment.py
.diffmogger/scripts/spawn_worker_agent.sh
.diffmogger/scripts/summarize_worker_outputs.py
.diffmogger/scripts/compact_agent_state.py
```

The Python files under `.diffmogger/scripts/` should be generated from the runtime entrypoint manifest and the canonical wrapper template, not copied from `templates/scripts/`.

The bootstrap prompt should identify this as `fresh_project` mode and ask for fixture-first scoring, evidence display, report generation, and a one-command demo/test path.

The generated `.diffmogger/agentic/verification_commands.txt` should start with bootstrap-safe commands that pass before product-specific package scripts exist; preferred future checks should stay documented until bootstrap creates them.

The recurring automation prompt should continue through explicit intake-derived product horizon state: local scored-signal demo, scoring depth, evidence-backed reports, safe adapters, showcase quality, long-run research capsules, and automation process improvement. Each run should record whether it stayed in the current horizon or advanced with evidence.

It should also make explicit Codex CLI worker decisions, use target-local runtime scripts, and distinguish file-only Markdown responses from notifier-mode outbound status texts.

This example exercises a more involved automation workflow without copying assumptions from a real product.
