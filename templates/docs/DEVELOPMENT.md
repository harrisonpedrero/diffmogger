# Development

Project: `{{PROJECT_NAME}}`

Mode: {{PROJECT_MODE_LABEL}}

Goal: {{PRODUCT_GOAL}}

{{PROJECT_MODE_GUIDANCE}}

## Setup

Document local setup here after bootstrap.

## Verification

Full-suite commands are stored in:

```text
.agentic/verification_commands.txt
```

The commands in that file are the clean-HEAD baseline gate. They must pass on
the current checkout; keep future desired commands out of this file until the
corresponding scripts, packages, services, or Make targets exist.

Patch-scoped or sprint-scoped smoke checks may be configured in:

```text
.agentic/smoke_commands.txt
```

Preferred commands:

```text
{{VERIFICATION_COMMANDS}}
```

Bootstrap-safe baseline commands:

```text
{{BOOTSTRAP_BASELINE_COMMANDS}}
```

Update this section and `.agentic/verification_commands.txt` when full-suite commands change.

The integrator records clean-HEAD full-suite baseline verification in `target/baseline_verification.json`. If that baseline fails before a queued patch is applied, normal hardener/finalization patches are deferred as `baseline_verification_blocker`; builder/planner patches can still integrate when focused checks pass and the failure is unrelated. Baseline repair patches should include `Verification scope: baseline_repair` in the role summary. Local service failures that the repo can reasonably repair, such as a missing local PostgreSQL test database with Prisma/Postgres configuration, should be classified as `repairable_local_service` and routed to a harness/setup patch before `BLOCKED_ON_ENVIRONMENT`.

## Automation

Recurring automation prompt:

```text
.agentic/automation_prompt.md
```

Dynamic task file:

```text
docs/CODEX_AUTOMATION_TASKS.md
```

Guardrails:

```text
docs/CODEX_AUTOMATION_GUARDRAILS.md
```

Project context:

```text
docs/PROJECT_CONTEXT.md
```

Scheduled runs should use the local wrapper:

```bash
bash .diffmogger/scripts/run_codex_automation.sh
```

The wrapper sets `CODEX_RUN_ID`, acquires `target/codex_automation.lock`, runs `codex exec --full-auto --skip-git-repo-check` through `.diffmogger/scripts/run_process_watchdog.py`, grants `$HOME/.codex` access for nested Codex CLI startup, and releases the lock when the run exits. Set `CODEX_ROLE_TIMEOUT_SECONDS` to override the 90-minute hard timeout and `CODEX_ROLE_TERMINATION_GRACE_SECONDS` to tune graceful shutdown.

## Automation Environment Loading

The local wrappers load target env files into the automation process before launching Codex, conveyor, role worktrees, or child workers. Values are inherited through the process environment; `.env*` files are not copied into isolated worktrees or queued patches.

Default env files include root `.env`, `.env.local`, `.env.development`, `.env.development.local`, and matching `apps/*/.env*` development files. Already-exported shell variables win over file values.

Use `CODEX_AUTOMATION_ENV_FILES` for an explicit comma- or colon-separated file list. Use `CODEX_AUTOMATION_ENV_DENYLIST` for comma- or colon-separated variable names that should not be inherited. Never print, summarize, commit, or copy secret values.

Continuous conveyor automation uses:

```bash
bash .diffmogger/scripts/run_conveyor_automation.sh --dry-run
bash .diffmogger/scripts/run_conveyor_automation.sh --once
python3 .diffmogger/scripts/run_observatory.py --open
```

Continuous conveyor automation requires this target to be an initialized git repo with an initial commit. Diffmogger scaffold creates the local repo and first `chore: initial commit` automatically when `HEAD` is missing.

The conveyor records canonical local state in `target/orchestration.sqlite3`, regenerates `target/canonical_state_brief.md` before Codex runs, keeps `target/automation_conveyor_state.json` and `target/automation_runner.json` as generated compatibility projections, uses `target/automation_conveyor.lock` to avoid duplicate dispatchers, and delegates actual work to the target-local single-lane or multi-role wrappers. The observatory reads canonical state plus `target/baseline_verification.json` to show runner state, baseline verification state, conveyor health, no-progress circuit breaker state, deferred-patch triage reasons with local next actions, an explicit next-lane action plan, action-plan follow-through status from recent conveyor or queue outcomes, bounded recommendation-history records, a next-run worker strategy recommendation, the active role, upcoming lanes, queued/deferred patches, recent outcomes, and timeline events.

## Managed Browser Runtime

Browser-backed automation should prefer Diffmogger's managed local browser over ambient system Chrome:

```bash
python3 .diffmogger/scripts/diffmogger_browser.py doctor --launch
python3 .diffmogger/scripts/diffmogger_browser.py install
python3 .diffmogger/scripts/diffmogger_browser.py env
```

The helper checks `DIFFMOGGER_BROWSER_PATH`, `CHROME_PATH`, and the managed cache at
`DIFFMOGGER_BROWSER_CACHE` or `~/.cache/diffmogger/browsers`. Automation wrappers export
the managed path for child Codex runs when it exists. Do not make browser smoke checks depend only on system
Chrome; use `python3 .diffmogger/scripts/diffmogger_browser.py resolve` or the exported `CHROME_PATH`.

## Optional MCP Integrations

Optional MCP servers:

```text
{{OPTIONAL_MCP_SERVERS}}
```

When optional MCP is enabled, project-scoped config lives in `.codex/config.toml`. Diffmogger never runs `codex mcp add`, `codex mcp login`, or mutates user/global Codex config.

Context7 is documentation-only and should fall back to normal web search, repo docs, package metadata, or existing knowledge on auth errors, startup failures, timeouts, empty results, or tool errors. The generated MCP config inherits `CONTEXT7_API_KEY` when it is present for higher rate limits, but never stores the key.

Playwright MCP uses Diffmogger's managed browser when available. UI failure screenshots should be saved under:

```text
docs/backlog/ui_artifacts/<run_id>/<issue-slug>.png
```

## Ticket Campaigns

{{TICKET_CAMPAIGN_DEVELOPMENT_SECTION}}

For a durable first-run review bundle, render the same local state to HTML and Markdown:

```bash
python3 .diffmogger/scripts/run_observatory.py --target . --review-dir /tmp/Diffmogger-review
```

This writes `/tmp/Diffmogger-review/Diffmogger-observatory.html` and
`/tmp/Diffmogger-review/Diffmogger-self-review.md`. Markdown review exports update
`target/action_plan_history.json` so repeated recommendations and follow-through outcomes
remain visible across local conveyor cycles.

### First Review Checklist

After the first bootstrap, use one local review path:

1. In the Diffmogger starter-kit source, run `bash scripts/validate_starter_kit.sh` when reviewing kit or scaffold behavior.
2. Open the native dashboard from the Diffmogger checkout, reopen this target, and click **Run Safety Check** on the Run page.
3. Click **Export Review Bundle** or, from this target repo, run `python3 .diffmogger/scripts/run_observatory.py --target . --review-dir /tmp/Diffmogger-review`.
4. Open `/tmp/Diffmogger-review/Diffmogger-observatory.html` and inspect `/tmp/Diffmogger-review/Diffmogger-self-review.md`.
5. Confirm the review shows first-review readiness, safety status, validation state, active role or queue, known issues, the next sprint recommendation, and the next-run worker strategy.

The dashboard writes the safety-check result to `.diffmogger/runtime/integration_safety_check.json`
before the export reads it. That file is runtime state, not source.

## Human Bridge

{{HUMAN_DEVELOPMENT_SECTION}}

## Worker Agents

Worker agents allowed: {{WORKER_AGENTS_ALLOWED}}

{{WRITE_WORKER_DEVELOPMENT_SECTION}}

Use read-only worker reports first and record outputs under `target/agent_runs/<run_id>/`.

Local helpers:

```bash
bash .diffmogger/scripts/spawn_worker_agent.sh --target . --run-id "$CODEX_RUN_ID" --role review --prompt "Write a concise read-only review report."
python3 .diffmogger/scripts/summarize_worker_outputs.py . --run-id "$CODEX_RUN_ID"
```

Every automation run should record:

```text
Codex CLI worker decision: USE / SKIP / UNAVAILABLE
Reason: <one sentence>
```

## Multi-Role Automation

{{MULTI_ROLE_DEVELOPMENT_SECTION}}

## State Compaction

Use the local state compaction helper when Markdown handoff files become long:

```bash
python3 .diffmogger/scripts/compact_agent_state.py --dry-run .
```

Review the diff before running without `--dry-run`; unresolved human requests must stay active.
