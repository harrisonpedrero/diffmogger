# Worker Agents

Worker agents are a force multiplier for complex tasks. They are not a replacement for main-agent judgment.

## Default Policy

- Make an explicit worker decision at the beginning of every automation run:

```text
Codex CLI worker decision: USE / SKIP / UNAVAILABLE
Worker strategy: READ_ONLY_REPORTS / WRITE_WORKERS / INTEGRATION_ONLY / NO_WORKERS
Parallelism budget: <0-N workers>
Reason: <one sentence>
```

- Use one generation of workers by default.
- Prefer read-only worker reports.
- Use write-capable workers only when the generated project intake explicitly enables them.
- Use write-capable workers as bounded acceleration when work can split into reviewable write scopes or isolated work areas.
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

When a generated target project explicitly enables write-capable workers, the same helper supports an explicit write mode:

```bash
bash scripts/spawn_worker_agent.sh \
  --mode write \
  --target /absolute/path/to/target-project \
  --run-id "$CODEX_RUN_ID" \
  --role feature_a \
  --ownership "src/feature-a/** and tests/feature-a/** only" \
  --prompt "Implement the assigned slice using the agreed interface. List changed files and checks run."
```

Read-only remains the default. Write mode requires an ownership scope because the main agent must keep file/module ownership disjoint.

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

## Optional Write Workers

Generated target projects are conservative by default only in the sense that write-capable workers require explicit opt-in. Once enabled, they are meant to accelerate progress when work can split into reviewable lanes.

```json
{
  "write_worker_agents_allowed": true,
  "max_write_worker_count": 10,
  "write_worker_guidance": "Use the most parallelism the task can safely absorb while keeping ownership reviewable."
}
```

`max_write_worker_count` is capped at 10. The main agent should use the most parallelism the task can safely absorb: no workers for tiny or tightly coupled changes, a few workers for normal multi-surface work, and up to the cap for broad implementation, hardening, observability, docs, examples, validation, or competing prototype lanes.

Every run should choose a strategy:

```text
Worker strategy: READ_ONLY_REPORTS / WRITE_WORKERS / INTEGRATION_ONLY / NO_WORKERS
Write-worker count planned: <0-N>
Parallelism budget: <0-N workers>
Reason: <one sentence>
```

Use write workers after the main agent has enough plan to split the work without chaos. Keep coordination lightweight. Before spawning them, define:

- the milestone and implementation plan
- shared contracts, interfaces, data shapes, or command boundaries
- rough file/module ownership for each worker
- an explicit coordination protocol if any ownership overlaps
- verification expected from each worker

Each write worker must be told:

- it is not alone in the codebase
- it may modify only its assigned files/modules or scratch area
- it must not revert unrelated edits or changes made by others
- it must not spawn workers, touch `.env`, handle credentials, use network, send messages, or run destructive cleanup
- it must list changed files, checks run, integration notes, and risks

After write workers finish, the main agent must review diffs, integrate the slices, resolve conflicts, run verification, and update the task file. Worker changes are never accepted blindly.

Integration-only runs with no workers are valid when the main agent can finish faster or more safely. Ambitious local changes may break temporarily, but the breakage must be visible, reviewable, and repaired by the same run or follow-up integration work.

## Multi-Role Automation Is Separate

Multi-role automation is a project-level scheduling mode, not the same thing as write-capable worker agents. It is enabled with:

```json
{
  "multi_role_automations_allowed": true,
  "automation_role_profile": "planner_builder_hardener_integrator"
}
```

In multi-role mode, planner, builder, and hardener run in isolated git worktrees and queue patches. The integrator owns the main checkout, applies patches FIFO, verifies, creates local commits, updates `docs/MULTI_ROLE_PROGRESS.md`, and manages retention.

The worker-agent rules still matter inside each role: read-only worker reports remain the default for exploration, write workers remain optional, and no role may create unbounded recursive agents. Overlapping write ownership still requires an explicit coordination protocol.

Multi-role scripts are local-only. They refuse configured remotes by default, never push, and keep transient role artifacts under `target/automation_queue/`, `target/automation_worktrees/`, and `target/automation_logs/`.

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
- Write workers must not overlap write ownership without a documented coordination protocol.
- Worker changes must not be blindly accepted.
- Workers must not perform destructive cleanup.

## Integration Requirement

Before ending the run, the main agent must state which worker findings were accepted, rejected, or deferred and update the task file accordingly.
