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

Scheduled runs should acquire `target/codex_automation.lock` before code mutation. Prefer Diffmogger's `scripts/acquire_codex_lock.sh` and `scripts/release_codex_lock.sh` helpers when available, with `CODEX_RUN_ID` set for the run.

## Human Bridge

Human bridge enabled: {{HUMAN_BRIDGE_ENABLED}}

Start with file-only mode. Use the local notifier API only after manual file mode works.

If the human asks to be texted, messaged, or sent a status update, the automation should call `POST http://127.0.0.1:8765/api/notify` when the notifier is running. If it is unavailable, record the intended message in `docs/HUMAN_OUTBOX.md` with status `NOTIFIER_UNREACHABLE`.

## Worker Agents

Worker agents allowed: {{WORKER_AGENTS_ALLOWED}}

Use read-only worker reports first and record outputs under `target/agent_runs/<run_id>/`.

Optional Diffmogger helpers:

```bash
bash /path/to/Diffmogger/scripts/spawn_worker_agent.sh --target . --run-id "$CODEX_RUN_ID" --role review --prompt "Write a concise read-only review report."
python3 /path/to/Diffmogger/scripts/summarize_worker_outputs.py . --run-id "$CODEX_RUN_ID"
```

Every automation run should record:

```text
Codex CLI worker decision: USE / SKIP / UNAVAILABLE
Reason: <one sentence>
```

## State Compaction

Use Diffmogger's state compaction helper when Markdown handoff files become long:

```bash
python3 /path/to/Diffmogger/scripts/compact_agent_state.py --dry-run .
```

Review the diff before running without `--dry-run`; unresolved human requests must stay active.
