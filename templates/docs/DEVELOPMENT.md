# Development

Project: `{{PROJECT_NAME}}`

Mode: {{PROJECT_MODE_LABEL}}

Goal: {{PRODUCT_GOAL}}

{{PROJECT_MODE_GUIDANCE}}

## Setup

Document local setup here after bootstrap.

## Verification

Preferred commands:

```text
{{VERIFICATION_COMMANDS}}
```

Update this section when commands change.

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
bash scripts/run_codex_automation.sh
```

The wrapper sets `CODEX_RUN_ID`, acquires `target/codex_automation.lock`, runs `codex exec --full-auto --skip-git-repo-check`, grants `$HOME/.codex` access for nested Codex CLI startup, and releases the lock when the run exits.

Optional continuous conveyor scheduling uses:

```bash
bash scripts/run_conveyor_automation.sh --dry-run
bash scripts/run_conveyor_automation.sh --once
python3 scripts/run_observatory.py --open
```

The conveyor records local state under `target/automation_conveyor_state.json`, uses `target/automation_conveyor.lock` to avoid duplicate dispatchers, and delegates actual work to the target-local single-lane or multi-role wrappers. The observatory reads the same local state plus `target/automation_signals.json` to show active signal nudges, conveyor health, no-progress circuit breaker state, deferred-patch triage reasons with local next actions, an explicit next-lane action plan, action-plan follow-through status from recent conveyor or queue outcomes, bounded recommendation-history records, the active role, upcoming lanes, queued/deferred patches, recent outcomes, and timeline events.

For a durable first-run self-review artifact, render the same local state to Markdown:

```bash
python3 scripts/run_observatory.py --target . --review-output /tmp/Diffmogger-self-review.md
```

Markdown review exports update `target/action_plan_history.json` so repeated recommendations and follow-through outcomes remain visible across local conveyor cycles.

### First Review Checklist

After the first bootstrap, use one local review path:

1. In the Diffmogger starter-kit source, run `bash scripts/validate_starter_kit.sh` when reviewing kit or scaffold behavior.
2. Open the dashboard with `python3 /path/to/Diffmogger/scripts/run_dashboard.py`, reopen this target, and click **Run Safety Check** in the Monitor tab.
3. From this target repo, render the observatory with `python3 scripts/run_observatory.py --target . --once --output /tmp/Diffmogger-observatory.html`.
4. Export the Markdown self-review with `python3 scripts/run_observatory.py --target . --review-output /tmp/Diffmogger-self-review.md`.
5. Confirm the review shows first-review readiness, safety status, validation state, active role or queue, known issues, and the next sprint recommendation.

## Human Bridge

{{HUMAN_DEVELOPMENT_SECTION}}

## Worker Agents

Worker agents allowed: {{WORKER_AGENTS_ALLOWED}}

{{WRITE_WORKER_DEVELOPMENT_SECTION}}

Use read-only worker reports first and record outputs under `target/agent_runs/<run_id>/`.

Local helpers:

```bash
bash scripts/spawn_worker_agent.sh --target . --run-id "$CODEX_RUN_ID" --role review --prompt "Write a concise read-only review report."
python3 scripts/summarize_worker_outputs.py . --run-id "$CODEX_RUN_ID"
```

Every automation run should record:

```text
Codex CLI worker decision: USE / SKIP / UNAVAILABLE
Reason: <one sentence>
```

## Multi-Role Automation

{{MULTI_ROLE_DEVELOPMENT_SECTION}}

## Automation Signals

{{AUTOMATION_SIGNALS_DEVELOPMENT_SECTION}}

## State Compaction

Use the local state compaction helper when Markdown handoff files become long:

```bash
python3 scripts/compact_agent_state.py --dry-run .
```

Review the diff before running without `--dry-run`; unresolved human requests must stay active.
