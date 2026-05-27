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
- Prefer read-only worker reports for exploration and review.
- Treat write-capable workers as always available but optional per run.
- Use write-capable workers as bounded acceleration when work can split into reviewable write scopes or isolated work areas.
- The main agent owns integration and verification.
- Record worker activity in typed runtime state and refresh `.diffmogger/state/CODEX_AUTOMATION_TASKS.md` only as the generated handoff projection.

Check Codex CLI availability before using CLI workers:

```bash
command -v codex
```

If unavailable, record `Codex CLI worker decision: UNAVAILABLE` and continue the sprint without blocking on worker support.

## Output Convention

```text
.diffmogger/runtime/agent_runs/<run_id>/worker_<role>.md
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
bash .diffmogger/scripts/spawn_worker_agent.sh \
  --target /absolute/path/to/target-project \
  --run-id "$CODEX_RUN_ID" \
  --role tests \
  --prompt "Inspect the current sprint for test gaps and write a concise report."

python3 .diffmogger/scripts/summarize_worker_outputs.py /absolute/path/to/target-project --run-id "$CODEX_RUN_ID"
```

`spawn_worker_agent.sh` creates `.diffmogger/runtime/agent_runs/<run_id>/`, defaults to read-only report mode, tells the worker not to spawn more workers, and writes an unavailable/failure report if the CLI cannot run.

The same helper supports an explicit write mode:

```bash
bash .diffmogger/scripts/spawn_worker_agent.sh \
  --mode write \
  --target /absolute/path/to/target-project \
  --run-id "$CODEX_RUN_ID" \
  --role feature_a \
  --ownership "src/feature-a/** and tests/feature-a/** only" \
  --prompt "Implement the assigned slice using the agreed interface. List changed files and checks run."
```

Read-only remains the default. Write mode requires an ownership scope because the main agent must keep file/module ownership disjoint.

Generated automation wrappers grant the parent Codex run access to `$HOME/.codex` with `--add-dir`. That parent permission matters because nested `codex` processes may touch `state_5.sqlite`, `shell_snapshots`, and `sessions` during startup even when the child worker uses `--ephemeral`.

Generated worker helpers run the nested child with `--disable plugins --ephemeral --dangerously-bypass-approvals-and-sandbox`. The bypass is only for the nested child process; the parent automation run remains the outer sandbox boundary. This avoids macOS nested `sandbox-exec` failures while still keeping automation constrained by the parent run.

`summarize_worker_outputs.py` writes `.diffmogger/runtime/agent_runs/<run_id>/summary.md` by mechanically consolidating worker report highlights. The main agent still decides which findings to accept, reject, or defer.

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

If workers are skipped on a broad task, record the reason in typed automation control state so the canonical brief and generated handoff projection reflect it.

## Optional Write Workers

Generated target projects allow write-capable workers by default. They are meant to accelerate progress when work can split into reviewable lanes, but using zero write workers is still valid for tiny or tightly coupled changes.

```json
{
  "max_write_worker_count": 10,
  "write_worker_guidance": "Use the most parallelism the task can safely absorb while keeping ownership reviewable."
}
```

`max_write_worker_count` defaults to 3 and is capped at 10. `write_worker_agents_allowed` is a deprecated compatibility field and no longer disables write workers when false. The main agent should use the most parallelism the task can safely absorb: no workers for tiny or tightly coupled changes, a few workers for normal multi-surface work, and up to the cap for broad implementation, hardening, observability, docs, examples, validation, or competing prototype lanes.

## Runtime Budgets

Diffmogger stores current scheduler decisions, execution groups, leases, conflict telemetry, validation groups, worker runs, and scheduler telemetry in SQLite. Intake worker settings still shape local caps, but the current implementation treats caps as scheduler evidence rather than a separate doctrine.

- read-only worker budget is enabled when `worker_agents_allowed` is true
- write worker budget is enabled by default
- write worker capacity comes from `max_write_worker_count`
- validation and integration have conservative local caps

Runtime helpers check ownership and cap evidence before manual workers, execution groups, or validation jobs start. A read-only scope never authorizes write-capable workers.

Validation fanout classifies commands before launch. Unit tests, lint, typecheck, smoke checks, docs checks, and generated helper checks may run concurrently when they are local and read-only. Setup/repair, browser, build, unknown, and explicitly exclusive commands stay in a serial validation lane. Each `validation_jobs` row and matching receipt records the classification, lane, resource profile, and any reusable target-local setup cache that was detected.

## Read-Only Fanout

Diffmogger can launch read-only workers from proposed execution groups. The launcher consumes a read-only scope group, records `worker_runs`, and writes each worker report under `.diffmogger/runtime/agent_runs/<run_id>/`.

When a ready ticket is too weakly scoped for parallel write work, the scheduler prefers a bounded read-only scope evidence group before serial builder fallback. These workers collect ownership evidence, likely paths, likely symbols, validation hints, and risk notes. The evidence contract lives in typed SQLite execution-group and worker-output payloads; worker Markdown reports are review artifacts, not canonical state.

Scope/review workers may include a fenced JSON `scope_evidence_records` block in their report. Diffmogger normalizes those records into `scope_evidence_records` rows with candidate paths, symbols, confidence, stale-context warnings, likely tests, and reasons. Only accepted rows that resolve against the current codebase graph and meet the promotion threshold can raise future DAG ownership confidence. Ambiguous, stale, unresolved, unsafe, or low-confidence records remain auditable but do not authorize write leases.

Each worker receives a bounded context-pack preview: paths, reasons, confidence, and stale-context warnings only. Raw source contents are not embedded by default. Contracts forbid source writes, network access, credential access, external messages, and spawning more workers. The main agent remains responsible for consolidating reports and marking findings accepted, rejected, or deferred.

Worker report state is visible in `state.snapshot` as active read-only workers, pending reports, completed reports, and whether finding disposition is still required.

## Write-Worker Fanout

Write-worker fanout is always available, respects `max_write_worker_count`, and launches from a proposed write-worker execution group whose likely write surfaces are disjoint.

Before any write worker starts, Diffmogger acquires active resource leases for the worker's ownership scope. A worker without leases, without an ownership scope, or with an overlapping active lease is blocked. Lease scopes may be file, directory, tests-only, docs-only, symbol, module, or package shaped when the codebase graph can verify that ownership safely; otherwise Diffmogger falls back to narrower file leases or blocks the wave. Workers run in isolated scratch/worktree space and produce queue artifacts rather than changing the main checkout.

Same-wave write workers must have non-overlapping ownership. Overlapping source, module, package, directory, symbol, docs, or test scopes are serialized unless the parent run records an explicit coordination protocol and integration still remains serialized through the integrator.

Each write worker produces:

- a typed `worker_agents` row
- a `worker_contracts` row with ownership scope, allowed paths, denied paths/actions, expected patch output, and verification expectations
- a `worker_patches` row linked to the worker, leases, base commit, changed files, validation evidence, and any conflict signature
- a normal integrator queue manifest under `.diffmogger/runtime/automation_queue/builder/<run_id>/`

The serialized integrator remains the only path that applies patches to the main checkout. Parallel worker patches are visible in `state.snapshot` as queued worker patches, write-worker conflicts, lease conflict summary, and the integration backlog from parallel workers.

Before launching serialized integration, Diffmogger records `worker_patch_integration_preflight` in SQLite and snapshots. That preflight predicts safe order, likely overlap conflicts, stale-base risk, missing metadata, and DAG dependency readiness from normalized patch metadata; Markdown worker text never authorizes writes by itself.

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
- rough file/module/package/docs/tests ownership for each worker
- an explicit coordination protocol if any ownership overlaps
- verification expected from each worker

Each write worker must be told:

- it is not alone in the codebase
- it may modify only its assigned files/modules or scratch area
- it must not revert unrelated edits or changes made by others
- it must not spawn workers, touch `.env`, handle credentials, use network, send messages, or run destructive cleanup
- it must list changed files, checks run, integration notes, and risks

After write workers finish, the main agent must review diffs, integrate the slices, resolve conflicts, run verification, update typed runtime state, and refresh generated handoff projections. Worker changes are never accepted blindly.

Integration-only runs with no workers are valid when the main agent can finish faster or more safely. Ambitious local changes may break temporarily, but the breakage must be visible, reviewable, and repaired by the same run or follow-up integration work.

## Multi-Role Automation Is Separate

Multi-role automation is a project-level role mode, not the same thing as write-capable worker agents. It is enabled with:

```json
{
  "automation_role_profile": "planner_builder_hardener_integrator"
}
```

In multi-role mode, planner, designer when UI-heavy or opted in, builder, and hardener run in isolated git worktrees and queue patches. The integrator owns the main checkout, applies patches FIFO, verifies, creates filtered local project-change commits when `automation_checkpoint_commits` is enabled, records accepted commit hashes in typed SQLite ticket state, refreshes the canonical state brief plus `.diffmogger/state/CODEX_AUTOMATION_TASKS.md`, and manages retention.

The worker-agent rules still matter inside each role: read-only worker reports remain the default for exploration, write workers remain optional, and no role may create unbounded recursive agents. Overlapping write ownership still requires an explicit coordination protocol.

Multi-role scripts are local-only. They refuse configured remotes by default, never push, and keep transient role artifacts under `.diffmogger/runtime/automation_queue/`, `.diffmogger/runtime/automation_worktrees/`, and `.diffmogger/runtime/automation_logs/`.

Local checkpoint commits only stage project-owned source, tests, docs, fixtures, config, lockfiles, and intentional demo artifacts. They skip `.env`, secret/key material, dependency folders, caches, build output, Diffmogger runtime logs, raw agent logs, queues, worktrees, and generated runtime projections.

## Codex CLI Pattern

Use read-only reports by default:

```bash
export CODEX_RUN_ID="${CODEX_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p ".diffmogger/runtime/agent_runs/$CODEX_RUN_ID"

codex exec --disable plugins \
  --ephemeral \
  --dangerously-bypass-approvals-and-sandbox \
  -C . \
  "You are a read-only worker for this project. Read the repo and write a concise test-gap report to .diffmogger/runtime/agent_runs/$CODEX_RUN_ID/worker_tests.md. Do not modify source files except for that output report. Do not use network. Do not spawn workers. Stop after writing the report."
```

Use this command shape for nested Codex CLI workers launched from an automation run. The parent automation run should also allow `$HOME/.codex` with `--add-dir`; without that parent allowance, a child worker may fail while starting inside the parent run's sandbox.

Worker rules:

- Workers must not spawn additional workers.
- Workers must not send Apprise, local notifier, email, or other external messages.
- Workers must not touch `.env` or credentials.
- Read-only scope workers must not acquire write leases or mutate source, generated projections, or runtime state.
- Workers must not use network unless explicitly approved for that run.
- The main automation agent must read and consolidate worker findings before implementation is considered complete.
- Write workers must not overlap write ownership without a documented coordination protocol.
- Worker changes must not be blindly accepted.
- Workers must not perform destructive cleanup.

## Integration Requirement

Before ending the run, the main agent must state which worker findings were accepted, rejected, or deferred, update typed runtime state, and refresh generated handoff projections accordingly.
