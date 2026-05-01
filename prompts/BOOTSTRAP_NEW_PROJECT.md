# Bootstrap New Project Prompt

Use this in a fresh or newly retrofitted target repo after generating project-specific files.

---

You are bootstrapping this project for high-agency recurring Codex automation.

Read first:

1. `README.md` if present.
2. `AGENTS.md` if present.
3. `docs/INITIAL_BOOTSTRAP_PROMPT.md`.
4. `docs/CODEX_AUTOMATION_GUARDRAILS.md` if present.
5. `docs/CODEX_AUTOMATION_TASKS.md` if present.
6. `docs/PROJECT_CONTEXT.md` if present.

## Mission

Create or confirm the first runnable product baseline and install the automation operating system for this repo. If this is an existing project, preserve the local stack, architecture, docs, tests, and project-specific instructions unless the intake explicitly asks for a scoped change.

## Required Work

- Scaffold or refine the project according to `docs/INITIAL_BOOTSTRAP_PROMPT.md`.
- Create or update `AGENTS.md`.
- Create or update `.agentic/automation_prompt.md`.
- Create or update `docs/CODEX_AUTOMATION_TASKS.md`, including explicit product horizon state and a horizon transition log.
- Create or update `docs/CODEX_AUTOMATION_GUARDRAILS.md`.
- Create or update `docs/PROJECT_CONTEXT.md` when supplemental context exists.
- Create or update human bridge docs if enabled.
- Create or update `docs/AUTONOMY_EXPERIMENT_LOG.md`.
- Create or update `docs/DAILY_AUTOMATION_REVIEW.md`.
- Create or update local automation helper scripts under `scripts/`: `run_codex_automation.sh`, `acquire_codex_lock.sh`, `release_codex_lock.sh`, `spawn_worker_agent.sh`, `summarize_worker_outputs.py`, and `compact_agent_state.py`.
- Add a one-command local verification or demo path when practical.
- Ensure `.agentic/automation_prompt.md` explains the configured human bridge mode, local lock helpers, wrapper-owned lock behavior with `CODEX_LOCK_ALREADY_ACQUIRED=true`, state compaction, nested child `codex exec --disable plugins --ephemeral --dangerously-bypass-approvals-and-sandbox` worker usage, parent wrapper `--add-dir "$HOME/.codex"` behavior for nested CLI startup, and explicit `Codex CLI worker decision: USE / SKIP / UNAVAILABLE` records.

## Behavior

Build the product, not only plans. Use reasonable defaults. Avoid secrets and real external side effects. Prefer fixtures, mocks, or local seed data for the first demo. In existing projects, integrate rather than rewrite.

## Verification

Run relevant install, lint, test, build, or demo commands that exist or that you create. Do not claim checks passed unless they ran.

## End Of Run

Update `docs/CODEX_AUTOMATION_TASKS.md` with current state, product horizon state, horizon advancement evidence, completed work, checks, generated artifacts, Codex CLI worker decision, worker activity, lock ownership, known issues, pending human requests if enabled, best next milestone, suggested next sprint-sized task, and status.

Do not stop merely because a basic demo exists. This bootstrap is the first horizon, not the finish line.
