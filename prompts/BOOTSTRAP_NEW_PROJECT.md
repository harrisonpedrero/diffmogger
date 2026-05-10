# Bootstrap New Project Prompt

Use this in a fresh or newly retrofitted target repo after generating project-specific files.
New generated targets use the `.diffmogger/` sidecar layout. If a target has no
`.diffmogger/manifest.json`, use the equivalent legacy `.agentic/`, `docs/`, and
`target/` paths.

---

You are bootstrapping this project for high-agency recurring Codex automation.

Read first:

1. `README.md` if present.
2. `AGENTS.md` if present.
3. `.diffmogger/state/INITIAL_BOOTSTRAP_PROMPT.md`.
4. `.diffmogger/state/CODEX_AUTOMATION_GUARDRAILS.md` if present.
5. `.diffmogger/state/CODEX_AUTOMATION_TASKS.md` if present.
6. `.diffmogger/state/PROJECT_CONTEXT.md` if present.

## Mission

Create or confirm the first runnable product baseline and install the automation operating system for this repo. If this is an existing project, preserve the local stack, architecture, docs, tests, and project-specific instructions unless the intake explicitly asks for a scoped change.

## Required Work

- Scaffold or refine the project according to `.diffmogger/state/INITIAL_BOOTSTRAP_PROMPT.md`.
- Create or update `AGENTS.md`.
- Create or update `.diffmogger/agentic/automation_prompt.md`.
- Create or update `.diffmogger/state/CODEX_AUTOMATION_TASKS.md`, including explicit product horizon state and a horizon transition log.
- Create or update `.diffmogger/state/CODEX_AUTOMATION_GUARDRAILS.md`.
- Create or update `.diffmogger/state/PROJECT_CONTEXT.md` when supplemental context exists.
- Create or update human bridge docs if enabled.
- Create or update `.diffmogger/state/AUTONOMY_EXPERIMENT_LOG.md`.
- Create or update `.diffmogger/state/DAILY_AUTOMATION_REVIEW.md`.
- Create or update local automation helper scripts under `.diffmogger/scripts/`: `run_codex_automation.sh`, `run_conveyor_automation.sh`, `run_conveyor_automation.py`, `run_observatory.py`, `repair_environment.py`, `update_automation_signals.py`, `acquire_codex_lock.sh`, `release_codex_lock.sh`, `spawn_worker_agent.sh`, `summarize_worker_outputs.py`, and `compact_agent_state.py`. If multi-role mode is enabled, also create or update `run_role_automation.sh`, `integrate_role_outputs.py`, and `list_deferred_patches.py`.
- If automation signals are enabled, create or update `.diffmogger/state/AUTOMATION_SIGNALS.md`.
- If multi-role mode is enabled, create or update `.diffmogger/agentic/roles/planner.md`, `.diffmogger/agentic/roles/builder.md`, `.diffmogger/agentic/roles/hardener.md`, `.diffmogger/agentic/roles/integrator.md`, and `.diffmogger/state/MULTI_ROLE_PROGRESS.md`.
- Add a one-command local verification or demo path when practical.
- Ensure `.diffmogger/agentic/automation_prompt.md` explains the configured human bridge mode, local lock helpers, wrapper-owned lock behavior with `CODEX_LOCK_ALREADY_ACQUIRED=true`, state compaction, nested child `codex exec --disable plugins --ephemeral --dangerously-bypass-approvals-and-sandbox` worker usage, parent wrapper `--add-dir "$HOME/.codex"` behavior for nested CLI startup, explicit `Codex CLI worker decision: USE / SKIP / UNAVAILABLE` records, and explicit worker strategy decisions.
- Preserve read-only worker reports for exploration. If the intake explicitly enables write-capable workers, document the capped maximum, parallelism-budget decision, reviewable ownership rules, lightweight coordination, main-agent integration/review/verification duties, and the option to run integration-only with no workers.
- Preserve single-lane automation as the default. If the intake explicitly enables multi-role automation, document the local-only no-remote rule, fixed staggered role jobs, continuous conveyor option, worktree queue paths, integrator ownership, checkpoint commits, batched verification fallback, deferred-patch schema, observability through `.diffmogger/scripts/run_observatory.py`, and `.diffmogger/state/MULTI_ROLE_PROGRESS.md` responsibilities.

## Behavior

Build the product, not only plans. Use reasonable defaults. Avoid secrets and real external side effects. Prefer fixtures, mocks, or local seed data for the first demo. In existing projects, integrate rather than rewrite.

## Verification

Run relevant install, lint, test, build, or demo commands that exist or that you create. Do not claim checks passed unless they ran.

## End Of Run

Update `.diffmogger/state/CODEX_AUTOMATION_TASKS.md` with current state, product horizon state, horizon advancement evidence, completed work under `## Completed Last Run`, checks under `## Checks From Last Run`, generated artifacts, Codex CLI worker decision, worker activity, lock ownership, known issues, pending human requests if enabled, best next milestone, suggested next sprint-sized task, and status. Keep the scaffolded parser-compatible section headings.

Do not stop merely because a basic demo exists. This bootstrap is the first horizon, not the finish line.
