# Expected Generated Files: PatchQueue

The generation prompt should produce the standard automation file set plus the ticket source:

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

The generated bootstrap prompt should keep ticket-campaign bootstrap readiness-only: it may confirm setup, ticket parsing, and verification state, but must not implement ticket acceptance criteria or mark tickets done.

The generated `.diffmogger/agentic/verification_commands.txt` should contain bootstrap-safe commands that pass before any ticket implementation work starts. Desired future project checks may remain in the ticket source or sidecar state until the project surfaces that run them exist.

The generated recurring prompt should use bounded ticket-run phases: ticket-run readiness, one dependency-aware ticket implementation per run, verification and hardening, completion report, and stop.

The generated task projection should keep `## Product Horizon State`, but its current horizon should be a ticket-run phase and its backlog section should be `## Deferred / Follow-Up Tickets`.

The generated prompt and task file should not use product-roadmap language such as `MVP`, `Beyond MVP`, or `Ambitious extensions`. The dashboard-backed SQLite ticket queue is the source of truth for scope, optional `depends_on` arrays order dependent tickets, and automation should stop launching new work only after all tickets are done with evidence. Blocked tickets should become unblocker DAG work.
