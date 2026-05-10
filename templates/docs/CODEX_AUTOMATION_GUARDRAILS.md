# Codex Automation Guardrails

These guardrails apply to every continuous or manual high-agency Codex run in this repo.

## Scope Boundaries

Build `{{PROJECT_NAME}}`: {{PRODUCT_GOAL}}

Project mode: {{PROJECT_MODE_LABEL}}

{{PROJECT_MODE_GUIDANCE}}

Stay aligned with the target user: {{TARGET_USER}}

Do not build unrelated apps or large unrelated systems.

## Automation Must Never Do

{{AUTOMATION_MUST_NEVER_DO}}

## Secrets Policy

{{ENV_ACCESS_GUARDRAILS_POLICY}}
- Use placeholders in docs and examples.
- If credentials are needed but direct env access is not enabled or the value is unavailable, create a human request and continue with mock/local work.
- Generated wrappers may load target `.env*` values into the process environment for local commands and isolated role worktrees, but agents must not print, summarize, commit, or copy secret values or `.env*` files.

## External Side Effects Policy

- Do not spend money, deploy publicly, publish externally, contact real users, or trigger real-world side effects without explicit approval.
- Prefer fixtures, mocks, local seed data, and dry-run modes.
- External integrations must be optional, documented, and testable without live credentials.
- Optional MCP servers must never be required for progress. Context7 auth errors, startup failures, timeouts, empty results, or tool errors should fall back to normal web search, repo docs, package metadata, or existing knowledge.

## Quality Policy

- Run relevant checks when possible.
- Diagnose missing local tooling, dependencies, or repairable project-local services before declaring `BLOCKED_ON_ENVIRONMENT`; missing local databases with project-owned test configuration should become baseline repair work, not a terminal human blocker.
- Do not install dependencies globally; use ignored local venvs, `node_modules`, or other project-local runtime state.
- For browser-backed smoke checks, visual QA, or documentation research, prefer `.diffmogger/scripts/diffmogger_browser.py` and the exported `DIFFMOGGER_BROWSER_PATH`/`CHROME_PATH` over ambient system Chrome.
- If Playwright MCP is enabled, use it only for local browser validation and save deferred UI failure screenshots under `docs/backlog/ui_artifacts/<run_id>/` with Markdown links in task/progress state.
- If repeated browser launches fail before DevTools is ready, record `BLOCKED_ON_ENVIRONMENT` with diagnostics and use an equivalent manual or managed-browser QA path instead of looping on the same launch command.
- In `ticket_campaign` mode, do not implement tickets during bootstrap, use `.diffmogger/scripts/ticket_run.py . next --json` for dependency-aware ticket selection, act on at most one selected ticket per normal run, and do not expand scope after the listed tickets are done or blocked; run `.diffmogger/scripts/ticket_run.py` finalization and leave push/PR creation to the human.
- Do not delete tests just to pass checks.
- Do not hide broad classes of errors with blanket suppressions.
- Keep changes scoped to the current sprint.

## Worker-Agent Policy

- Use worker agents only for bounded subtasks.
- Make an explicit `Codex CLI worker decision: USE / SKIP / UNAVAILABLE` every run.
- Make an explicit worker strategy decision every run: `READ_ONLY_REPORTS`, `WRITE_WORKERS`, `INTEGRATION_ONLY`, or `NO_WORKERS`.
- Choose and record a parallelism budget every run.
- Check `command -v codex` before using Codex CLI workers.
- Prefer read-only worker reports.
- Main agent owns integration.
- Record worker outputs under `target/agent_runs/<run_id>/`.
- Use local `.diffmogger/scripts/spawn_worker_agent.sh` and `.diffmogger/scripts/summarize_worker_outputs.py` helpers when available; otherwise use equivalent bounded nested-child `codex exec --disable plugins --ephemeral --dangerously-bypass-approvals-and-sandbox` commands from inside the parent automation run.
- Do not create unbounded recursive agent loops.
- Workers must not send Discord, notifier, email, or other external messages, spawn additional workers, or use network unless explicitly approved for that run.
- {{WORKER_ENV_ACCESS_RULE}}
{{WRITE_WORKER_GUARDRAILS_POLICY}}

## Multi-Role Automation Policy

{{MULTI_ROLE_GUARDRAILS_POLICY}}

## Lock-File Policy

- Acquire `target/codex_automation.lock` before mutating code in automation runs.
- Scheduled runs should use local `.diffmogger/scripts/run_codex_automation.sh`, which owns lock acquire/release.
- If `CODEX_LOCK_ALREADY_ACQUIRED=true`, do not acquire, overwrite, manually create, or release the lock inside the Codex run.
- Manual runs should use local `.diffmogger/scripts/acquire_codex_lock.sh` and `.diffmogger/scripts/release_codex_lock.sh`.
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
- Use local `.diffmogger/scripts/compact_agent_state.py --dry-run .` before compacting long-running Markdown state.
- Never silently delete active or unresolved human requests.
- Keep this guardrails file lean.
