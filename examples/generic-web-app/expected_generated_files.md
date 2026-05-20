# Expected Generated Files: FocusBoard

The generation prompt should produce:

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
.diffmogger/lib/diffmogger/observatory/snapshots.py
.diffmogger/lib/diffmogger/runtime/__init__.py
.diffmogger/lib/diffmogger/runtime/build_replay.py
.diffmogger/lib/diffmogger/runtime/code_intelligence.py
.diffmogger/lib/diffmogger/runtime/compact_agent_state.py
.diffmogger/lib/diffmogger/runtime/diffmogger_browser.py
.diffmogger/lib/diffmogger/runtime/integrate_role_outputs.py
.diffmogger/lib/diffmogger/runtime/list_deferred_patches.py
.diffmogger/lib/diffmogger/runtime/load_automation_env.py
.diffmogger/lib/diffmogger/runtime/paths.py
.diffmogger/lib/diffmogger/runtime/preflight.py
.diffmogger/lib/diffmogger/runtime/readiness_eval.py
.diffmogger/lib/diffmogger/runtime/repair_environment.py
.diffmogger/lib/diffmogger/runtime/run_conveyor_automation.py
.diffmogger/lib/diffmogger/runtime/run_observatory.py
.diffmogger/lib/diffmogger/runtime/run_process_watchdog.py
.diffmogger/lib/diffmogger/runtime/state_brief.py
.diffmogger/lib/diffmogger/runtime/state_store.py
.diffmogger/lib/diffmogger/runtime/summarize_worker_outputs.py
.diffmogger/lib/diffmogger/runtime/ticket_run.py
.diffmogger/schemas/orchestration_state.schema.json
.diffmogger/agentic/automation_prompt.md
.diffmogger/agentic/smoke_commands.txt
.diffmogger/agentic/verification_commands.txt
.diffmogger/state/CODEX_AUTOMATION_TASKS.md
.diffmogger/state/CODEX_AUTOMATION_GUARDRAILS.md
.diffmogger/state/DEVELOPMENT.md
.diffmogger/scripts/acquire_codex_lock.sh
.diffmogger/scripts/release_codex_lock.sh
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
.diffmogger/scripts/preflight_parallelization_readiness.py
.diffmogger/scripts/state_brief.py
.diffmogger/scripts/ticket_run.py
.diffmogger/scripts/repair_environment.py
.diffmogger/scripts/spawn_worker_agent.sh
.diffmogger/scripts/summarize_worker_outputs.py
.diffmogger/scripts/compact_agent_state.py
```

The Python files under `.diffmogger/scripts/` should be generated from the runtime entrypoint manifest and the canonical wrapper template, not copied from `templates/scripts/`.

The bootstrap prompt should identify this as `fresh_project` mode and ask Codex to create a local-first web app with seed data, a weekly board, task completion, daily summary, and verification commands.

The generated `.diffmogger/agentic/verification_commands.txt` should start with bootstrap-safe commands that pass before the web app package scripts exist; preferred future app checks should stay documented until bootstrap creates them.

The recurring automation prompt should keep improving the planning workflow after the first demo, record intake-derived horizons for weekly boards, daily summaries, review capsules, and optional adapters, record a Codex CLI worker decision each run, use target-local automation scripts, and handle dashboard-backed human messages without notifier API language.
