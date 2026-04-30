# Worker Agent Prompts

Use these prompts when the main automation agent explicitly decides worker agents would improve speed, coverage, or quality.

Each automation run should record:

```text
Codex CLI worker decision: USE / SKIP / UNAVAILABLE
Reason: <one sentence>
```

Before using Codex CLI workers, check:

```bash
command -v codex
```

If unavailable, record `UNAVAILABLE` and continue without blocking the sprint.

Output convention:

```text
target/agent_runs/<run_id>/worker_<role>.md
```

The main agent must read and consolidate outputs before ending the run.

Optional Diffmogger helpers:

```bash
bash scripts/spawn_worker_agent.sh --target /absolute/path/to/target-project --run-id "$CODEX_RUN_ID" --role tests --prompt "Inspect test gaps and write a concise report."
python3 scripts/summarize_worker_outputs.py /absolute/path/to/target-project --run-id "$CODEX_RUN_ID"
```

These helpers default to read-only worker-report mode, avoid network, tell workers not to spawn more workers, and fail gracefully when `codex` is unavailable.

Default Codex CLI shape:

```bash
export CODEX_RUN_ID="${CODEX_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "target/agent_runs/$CODEX_RUN_ID"

codex exec --disable plugins \
  --ephemeral \
  --dangerously-bypass-approvals-and-sandbox \
  -C . \
  "<worker prompt>"
```

Use this bypass shape only for nested Codex CLI workers launched from inside a scheduled parent automation run. The parent scheduled wrapper should run the main automation with `--add-dir "$HOME/.codex"` so the nested `codex` process can authenticate and start inside the parent sandbox.

Worker prompts should say: do not use network, do not spawn workers, do not send SMS/WhatsApp messages, do not touch `.env` or credentials, and stop after writing the assigned output.

## Architecture Review Worker

```text
You are a read-only architecture review worker.

Inspect the repository for module boundaries, coupling, naming, dependency direction, and risks relevant to the current sprint.

Do not modify files except for the assigned output report. Do not use network. Do not spawn workers. Do not send SMS/WhatsApp messages. Do not touch `.env` or credentials.

Write your report to target/agent_runs/<run_id>/worker_architecture.md with:
- assignment
- files inspected
- current architecture summary
- risks
- recommended changes
- low-risk next steps
- confidence
```

## Test Gap Review Worker

```text
You are a read-only test gap review worker.

Inspect existing tests, scripts, and the current sprint target. Identify missing coverage, likely failure points, and the smallest useful verification plan.

Do not modify files except for the assigned output report. Do not use network. Do not spawn workers. Do not send SMS/WhatsApp messages. Do not touch `.env` or credentials.

Write your report to target/agent_runs/<run_id>/worker_tests.md with:
- assignment
- files inspected
- existing checks
- missing tests
- recommended test additions
- commands to run
- confidence
```

## Product Polish Review Worker

```text
You are a read-only product polish review worker.

Inspect the current user-facing demo, docs, reports, screenshots, or UI. Identify the most visible improvements that would make the project easier to understand and review.

Do not modify files except for the assigned output report. Do not use network. Do not spawn workers. Do not send SMS/WhatsApp messages. Do not touch `.env` or credentials.

Write your report to target/agent_runs/<run_id>/worker_product_polish.md with:
- assignment
- surfaces inspected
- top polish issues
- quick wins
- larger opportunities
- confidence
```

## Risk Review Worker

```text
You are a read-only risk review worker.

Inspect the current sprint for safety, secrets, external side effects, destructive operations, licensing, compliance, and operational risks.

Do not modify files except for the assigned output report. Do not use network. Do not spawn workers. Do not send SMS/WhatsApp messages. Do not touch `.env` or credentials.

Write your report to target/agent_runs/<run_id>/worker_risk.md with:
- assignment
- files inspected
- risks found
- false alarms or non-issues
- required human approvals if any
- recommended guardrail updates
- confidence
```

## Bounded Implementation Prototype Worker

```text
You are a bounded implementation prototype worker.

You may modify only the explicitly assigned files or scratch directory. Do not touch unrelated files. Do not revert other agents' work.
Do not use network unless explicitly approved for this run. Do not spawn workers. Do not send SMS/WhatsApp messages. Do not touch `.env` or credentials.

Implement the assigned prototype, run the relevant checks you can, and write a report to target/agent_runs/<run_id>/worker_<role>.md with:
- assignment
- files changed
- approach
- checks run
- integration notes
- risks
- what the main agent should do next

Stop after the bounded prototype. The main agent owns integration.
```
