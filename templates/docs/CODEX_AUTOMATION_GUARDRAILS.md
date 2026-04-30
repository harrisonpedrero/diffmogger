# Codex Automation Guardrails

These guardrails apply to every scheduled or manual high-agency Codex run in this repo.

## Scope Boundaries

Build `{{PROJECT_NAME}}`: {{PRODUCT_GOAL}}

Stay aligned with the target user: {{TARGET_USER}}

Do not build unrelated apps or large unrelated systems.

## Secrets Policy

- Do not read `.env` files.
- Do not request, print, store, or commit secrets.
- Use placeholders in docs and examples.
- If credentials are needed, create a human request and continue with mock/local work.

## External Side Effects Policy

- Do not spend money, deploy publicly, publish externally, contact real users, or trigger real-world side effects without explicit approval.
- Prefer fixtures, mocks, local seed data, and dry-run modes.
- External integrations must be optional, documented, and testable without live credentials.

## Quality Policy

- Run relevant checks when possible.
- Do not delete tests just to pass checks.
- Do not hide broad classes of errors with blanket suppressions.
- Keep changes scoped to the current sprint.

## Worker-Agent Policy

- Use worker agents only for bounded subtasks.
- Make an explicit `Codex CLI worker decision: USE / SKIP / UNAVAILABLE` every run.
- Check `command -v codex` before using Codex CLI workers.
- Prefer read-only worker reports.
- Main agent owns integration.
- Record worker outputs under `target/agent_runs/<run_id>/`.
- Use local `scripts/spawn_worker_agent.sh` and `scripts/summarize_worker_outputs.py` helpers when available; otherwise use equivalent bounded nested-child `codex exec --disable plugins --ephemeral --dangerously-bypass-approvals-and-sandbox` commands from inside the scheduled parent run.
- Do not create unbounded recursive agent loops.
- Workers must not send SMS/WhatsApp messages, touch `.env`, handle credentials, spawn additional workers, or use network unless explicitly approved for that run.

## Lock-File Policy

- Acquire `target/codex_automation.lock` before mutating code in scheduled runs.
- Scheduled runs should use local `scripts/run_codex_automation.sh`, which owns lock acquire/release.
- If `CODEX_LOCK_ALREADY_ACQUIRED=true`, do not acquire, overwrite, manually create, or release the lock inside the Codex run.
- Manual runs should use local `scripts/acquire_codex_lock.sh` and `scripts/release_codex_lock.sh`.
- Set `CODEX_RUN_ID` before acquire/release so the lock can identify the current run.
- If an active lock exists, do not mutate code.
- If a stale lock is removed, record that decision in `docs/CODEX_AUTOMATION_TASKS.md`.

## Human-Intervention Policy

- Ask the human only for meaningful unlocks.
- For reversible choices, choose a safe default and document it.
- Use `ACTIVE_WITH_PENDING_USER_INPUT` when work can continue around a pending request.
{{HUMAN_GUARDRAILS_POLICY}}

## Status Policy

Allowed statuses:

```text
ACTIVE
ACTIVE_WITH_PENDING_USER_INPUT
BLOCKED_ON_USER
BLOCKED_ON_ENVIRONMENT
CRITICAL_STOP
```

Use `CRITICAL_STOP` only when continuing autonomously is unsafe.

## Context-Bloat Policy

- Keep active files short.
- Remove handled messages from `docs/HUMAN_INBOX.md`.
- Archive concise handled responses in `docs/HUMAN_RESPONSES_ARCHIVE.md`.
- Prune stale tasks from `docs/CODEX_AUTOMATION_TASKS.md`.
- Use local `scripts/compact_agent_state.py --dry-run .` before compacting long-running Markdown state.
- Never silently delete active or unresolved human requests.
- Keep this guardrails file lean.
