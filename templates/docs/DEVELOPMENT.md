# Development

Project: `{{PROJECT_NAME}}`

Goal: {{PRODUCT_GOAL}}

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

Scheduled runs should use the local wrapper:

```bash
bash scripts/run_codex_automation.sh
```

The wrapper sets `CODEX_RUN_ID`, acquires `target/codex_automation.lock`, runs `codex exec --full-auto`, and releases the lock when the run exits.

## Human Bridge

{{HUMAN_DEVELOPMENT_SECTION}}

## Worker Agents

Worker agents allowed: {{WORKER_AGENTS_ALLOWED}}

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

## State Compaction

Use the local state compaction helper when Markdown handoff files become long:

```bash
python3 scripts/compact_agent_state.py --dry-run .
```

Review the diff before running without `--dry-run`; unresolved human requests must stay active.
