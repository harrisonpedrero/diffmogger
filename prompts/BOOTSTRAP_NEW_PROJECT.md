# Bootstrap New Project Prompt

Use this in a fresh target repo after generating project-specific files.

---

You are bootstrapping this project for high-agency recurring Codex automation.

Read first:

1. `README.md` if present.
2. `AGENTS.md` if present.
3. `docs/INITIAL_BOOTSTRAP_PROMPT.md`.
4. `docs/CODEX_AUTOMATION_GUARDRAILS.md` if present.
5. `docs/CODEX_AUTOMATION_TASKS.md` if present.

## Mission

Create the first runnable product baseline and install the automation operating system for this repo.

## Required Work

- Scaffold or refine the project according to `docs/INITIAL_BOOTSTRAP_PROMPT.md`.
- Create or update `AGENTS.md`.
- Create or update `.agentic/automation_prompt.md`.
- Create or update `docs/CODEX_AUTOMATION_TASKS.md`.
- Create or update `docs/CODEX_AUTOMATION_GUARDRAILS.md`.
- Create or update human bridge docs if enabled.
- Create or update `docs/AUTONOMY_EXPERIMENT_LOG.md`.
- Create or update `docs/DAILY_AUTOMATION_REVIEW.md`.
- Create or update local automation helper scripts under `scripts/`: `run_codex_automation.sh`, `acquire_codex_lock.sh`, `release_codex_lock.sh`, `spawn_worker_agent.sh`, `summarize_worker_outputs.py`, and `compact_agent_state.py`.
- Add a one-command local verification or demo path when practical.
- Ensure `.agentic/automation_prompt.md` explains the configured human bridge mode, local lock helpers, wrapper-owned lock behavior with `CODEX_LOCK_ALREADY_ACQUIRED=true`, state compaction, nested child `codex exec --disable plugins --ephemeral --dangerously-bypass-approvals-and-sandbox` worker usage, parent wrapper `--add-dir "$HOME/.codex"` behavior for nested CLI startup, and explicit `Codex CLI worker decision: USE / SKIP / UNAVAILABLE` records.

## Behavior

Build the product, not only plans. Use reasonable defaults. Avoid secrets and real external side effects. Prefer fixtures, mocks, or local seed data for the first demo.

## Verification

Run relevant install, lint, test, build, or demo commands that exist or that you create. Do not claim checks passed unless they ran.

## End Of Run

Update `docs/CODEX_AUTOMATION_TASKS.md` with current state, completed work, checks, generated artifacts, Codex CLI worker decision, worker activity, lock ownership, known issues, pending human requests if enabled, best next milestone, suggested next sprint-sized task, and status.

Do not stop merely because a basic demo exists. This bootstrap is the first horizon, not the finish line.
