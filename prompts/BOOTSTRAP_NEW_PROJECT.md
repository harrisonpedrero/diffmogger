# Bootstrap New Project Prompt

Use this in a fresh or newly retrofitted target repo after generating project-specific files.
New generated targets use the `.diffmogger/` sidecar layout.

---

You are bootstrapping this project for high-agency recurring Codex automation.

Read first:

1. `README.md` if present.
2. `AGENTS.md` if present.
3. `.diffmogger/state/CODEX_AUTOMATION_GUARDRAILS.md` if present.
4. `.diffmogger/runtime/canonical_state_brief.md` if present.
5. `.diffmogger/state/CODEX_AUTOMATION_TASKS.md` if present.
6. Relevant files listed in intake/dashboard context records.

## Mission

Create or confirm the first runnable product baseline and install the automation operating system for this repo. If this is an existing project, preserve the local stack, architecture, docs, tests, and project-specific instructions unless the intake explicitly asks for a scoped change.

## Required Work

- Scaffold or refine the project according to the intake and canonical state brief.
- Create or update `AGENTS.md`.
- Create or update `.diffmogger/agentic/automation_prompt.md`.
- Seed or update typed automation control state in `.diffmogger/runtime/orchestration.sqlite3`, including explicit product horizon state and a horizon transition log, then refresh `.diffmogger/state/CODEX_AUTOMATION_TASKS.md` as a prompt/handoff projection.
- Create or update `.diffmogger/state/CODEX_AUTOMATION_GUARDRAILS.md`.
- Track supplemental context through `.diffmogger/context/` plus intake/dashboard state; do not create a separate project-context Markdown index.
- Keep human input in typed SQLite/dashboard records; do not create separate human-bridge setup docs.
- Create or update local automation helper scripts under `.diffmogger/scripts/`: `run_conveyor_automation.sh`, `run_conveyor_automation.py`, `run_role_automation.sh`, `integrate_role_outputs.py`, `list_deferred_patches.py`, `run_observatory.py`, `repair_environment.py`, `state_brief.py`, `acquire_codex_lock.sh`, `release_codex_lock.sh`, `spawn_worker_agent.sh`, `summarize_worker_outputs.py`, and `compact_agent_state.py`.
- Ensure the runtime can initialize `.diffmogger/runtime/orchestration.sqlite3`, materialize typed automation control, execution DAG nodes/edges, repo capability manifest, validation receipts, blockers, and next actions, regenerate `.diffmogger/runtime/canonical_state_brief.md`, and include `.diffmogger/schemas/orchestration_state.schema.json`.
- If multi-role mode is enabled, create or update `.diffmogger/agentic/roles/planner.md`, `.diffmogger/agentic/roles/builder.md`, `.diffmogger/agentic/roles/hardener.md`, and `.diffmogger/agentic/roles/integrator.md`.
- Add a one-command local verification or demo path when practical.
- Ensure `.diffmogger/agentic/automation_prompt.md` explains the configured human bridge mode, local lock helpers, wrapper-owned lock behavior with `CODEX_LOCK_ALREADY_ACQUIRED=true`, canonical typed SQLite runtime state, generated projection compaction, nested child `codex exec --disable plugins --ephemeral --dangerously-bypass-approvals-and-sandbox` worker usage, parent wrapper `--add-dir "$HOME/.codex"` behavior for nested CLI startup, explicit `Codex CLI worker decision: USE / SKIP / UNAVAILABLE` records, and explicit worker strategy decisions.
- Preserve read-only worker reports for exploration and document write-capable workers as always available, optional per run, capped by `max_write_worker_count`, and governed by parallelism-budget decisions, reviewable ownership rules, lightweight coordination, main-agent integration/review/verification duties, and the option to run integration-only with no workers.
- Preserve the execution DAG scheduler architecture with the `planner_builder_hardener_integrator` role profile. Document bounded vs ongoing campaign behavior, the DAG scheduler config fields, local-only no-remote rule, worktree queue paths, integrator ownership, SQLite checkpoints/events, batched verification fallback, deferred-patch schema, liveness-first unblocker work, and observability through `.diffmogger/scripts/run_observatory.py`.

## Behavior

Build the product, not only plans. Use reasonable defaults. Avoid secrets and real external side effects. Prefer fixtures, mocks, or local seed data for runnable local milestones. In existing projects, integrate rather than rewrite.

## Verification

Run relevant install, lint, test, build, or demo commands that exist or that you create. Do not claim checks passed unless they ran.

## End Of Run

Update typed automation control, validation receipts, human-message state, blockers, and next actions in `.diffmogger/runtime/orchestration.sqlite3`, regenerate `.diffmogger/runtime/canonical_state_brief.md`, then refresh `.diffmogger/state/CODEX_AUTOMATION_TASKS.md` with current state, product horizon state, horizon advancement evidence, completed work under `## Completed Last Run`, checks under `## Checks From Last Run`, generated artifacts, Codex CLI worker decision, worker activity, lock ownership, known issues, pending human requests if enabled, best next milestone, suggested next sprint-sized task, and status. Keep the Markdown as a generated projection, not live state authority; agents should read `.diffmogger/runtime/canonical_state_brief.md` rather than inspecting SQLite manually.

Do not stop merely because a basic demo exists. This bootstrap is the first horizon, not the finish line.
