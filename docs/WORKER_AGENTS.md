# Worker Agents

Worker agents are a force multiplier for complex tasks. They are not a replacement for main-agent judgment.

## Default Policy

- Make an explicit worker decision at the beginning of every automation run:

```text
Codex CLI worker decision: USE / SKIP / UNAVAILABLE
Reason: <one sentence>
```

- Use one generation of workers by default.
- Prefer read-only worker reports.
- Use implementation workers only with disjoint write scopes or isolated work areas.
- The main agent owns integration and verification.
- Record worker activity in `docs/CODEX_AUTOMATION_TASKS.md`.

Check Codex CLI availability before using CLI workers:

```bash
command -v codex
```

If unavailable, record `Codex CLI worker decision: UNAVAILABLE` and continue the sprint without blocking on worker support.

## Output Convention

```text
target/agent_runs/<run_id>/worker_<role>.md
```

Each worker report should include:

- assignment
- files inspected
- findings
- recommendations
- risks
- suggested verification
- confidence

## Helper Scripts

Diffmogger includes optional worker helpers. They are wrappers around explicit bounded behavior, not mandatory orchestration:

```bash
bash scripts/spawn_worker_agent.sh \
  --target /absolute/path/to/target-project \
  --run-id "$CODEX_RUN_ID" \
  --role tests \
  --prompt "Inspect the current sprint for test gaps and write a concise report."

python3 scripts/summarize_worker_outputs.py /absolute/path/to/target-project --run-id "$CODEX_RUN_ID"
```

`spawn_worker_agent.sh` creates `target/agent_runs/<run_id>/`, defaults to read-only report mode, tells the worker not to spawn more workers, and writes an unavailable/failure report if the CLI cannot run.

Generated scheduled wrappers grant the parent Codex run access to `$HOME/.codex` with `--add-dir`. That parent permission matters because nested `codex` processes may touch `state_5.sqlite`, `shell_snapshots`, and `sessions` during startup even when the child worker uses `--ephemeral`.

Generated worker helpers run the nested child with `--disable plugins --ephemeral --dangerously-bypass-approvals-and-sandbox`. The bypass is only for the nested child process; the scheduled parent remains the outer sandbox boundary. This avoids macOS nested `sandbox-exec` failures while still keeping scheduled automation constrained by the parent run.

`summarize_worker_outputs.py` writes `target/agent_runs/<run_id>/summary.md` by mechanically consolidating worker report highlights. The main agent still decides which findings to accept, reject, or defer.

## Good Worker Roles

- Architecture review.
- Test gap review.
- Product polish review.
- Risk review.
- Fixture/data generation review.
- Isolated implementation prototype.

## When To Spawn

Spawn workers when the task is large, unclear, multi-module, or benefits from independent review.

Prefer 1-3 workers for:

- multi-module features
- broad UX/reporting improvements
- nontrivial architecture decisions
- major test/coverage reviews
- difficult debugging where independent diagnosis helps
- review of recent automation behavior
- runs expected to use most of the automation window

Skip workers for tiny bugs, simple test reruns, or cases where delegation overhead is higher than the work.

If workers are skipped on a broad task, record the reason in `docs/CODEX_AUTOMATION_TASKS.md`.

## Codex CLI Pattern

Use read-only reports by default:

```bash
export CODEX_RUN_ID="${CODEX_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "target/agent_runs/$CODEX_RUN_ID"

codex exec --disable plugins \
  --ephemeral \
  --dangerously-bypass-approvals-and-sandbox \
  -C . \
  "You are a read-only worker for this project. Read the repo and write a concise test-gap report to target/agent_runs/$CODEX_RUN_ID/worker_tests.md. Do not modify source files except for that output report. Do not use network. Do not spawn workers. Stop after writing the report."
```

Use this command shape for nested Codex CLI workers launched from an automation run. The parent scheduled run should also allow `$HOME/.codex` with `--add-dir`; without that parent allowance, a child worker may fail while starting inside the parent run's sandbox.

Worker rules:

- Workers must not spawn additional workers.
- Workers must not send SMS/WhatsApp messages.
- Workers must not touch `.env` or credentials.
- Workers must not use network unless explicitly approved for that run.
- The main automation agent must read and consolidate worker findings before implementation is considered complete.

## Integration Requirement

Before ending the run, the main agent must state which worker findings were accepted, rejected, or deferred and update the task file accordingly.
