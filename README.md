<p align="center">
  <img src="docs/assets/diffmogger-logo-cropped.png" alt="Diffmogger" width="720">
</p>

Diffmogger is a local orchestration engine for Codex, backed by a directed execution graph.

It scaffolds a self-contained `.diffmogger/` sidecar into a target repo, keeps live automation state in SQLite, and runs Codex work through typed graph actions such as `scope`, `build`, `review`, `validate`, `repair`, and `integrate`.

Diffmogger is not a hosted agent platform or a product-specific app. It is reusable local infrastructure for repos where Codex work needs durable state, clear handoffs, inspectable progress, safe parallelism, and reviewable outcomes across repeated runs.

## What It Does

Diffmogger gives a target repo:

- a native dashboard for project setup, automation control, ticket/action queues, human input records, safety checks, and scheduler inspection
- a `.diffmogger/` sidecar for automation-owned prompts, runtime state, logs, queues, worktrees, schemas, manifests, and generated projections
- a canonical SQLite state store at `.diffmogger/runtime/orchestration.sqlite3`
- target-local wrappers under `.diffmogger/scripts/` and a bundled runtime under `.diffmogger/lib/diffmogger/`
- optional worker fanout, notifier integration, Context7/Playwright MCP setup, and local observatory exports

Generated Markdown and JSON files are projections. The SQLite graph is the runtime authority.

## Quickstart

```bash
git clone https://github.com/harrisonpedrero/diffmogger.git Diffmogger
cd Diffmogger
bash scripts/validate_starter_kit.sh
bash scripts/build_native_dashboard_app.sh
open Diffmogger.app
```

In the dashboard:

1. Pick a fresh or existing target folder.
2. Fill in the project intake.
3. Add optional context files.
4. Run **Scaffold**.
5. Open **Automation** and click **Start**.
6. Use **Run Safety Check** and the target-local observatory helper when you need review artifacts.

CLI scaffold path:

```bash
python3 scripts/scaffold_project_docs.py \
  --intake examples/generic-web-app/project_intake.md \
  --target /tmp/Diffmogger-smoke \
  --force

python3 scripts/check_required_files.py /tmp/Diffmogger-smoke
```

Scaffold initializes git and creates a local `chore: initial commit` automatically when the target does not already have `HEAD`.

## Execution Model

Diffmogger materializes target automation state into a directed execution graph stored in SQLite. It is a work generator, not a blocker detector. Runtime inputs include tickets, dependencies, blockers, human messages, validation receipts, worker outputs, repository capability data, codebase graph signals, active leases, and execution budgets.

Those inputs become typed DAG nodes and edges. Common node types include `orchestrate`, `decompose`, `scope`, `build`, `review`, `validate`, `repair`, `integrate`, `audit`, `calibrate`, `blocker`, and `completion`.

Hard edges block only the downstream node they guard. Advisory edges preserve context without stopping execution. Blockers are planning inputs that should create repair, setup, mock, fixture, defer, split, reframe, review, documentation, or alternate-ticket DAG work while tickets remain.

On each scheduler cycle, Diffmogger refreshes the graph, computes runnable nodes, records scheduler candidates, and selects the next execution action. If tickets remain, the scheduler should produce work. Actions can launch read-only scope work, launch write work with leases, run validation groups, review queued patches, create repair/setup/harness/mock/defer nodes, reconcile worker outputs, or integrate accepted patches.

Parallel write execution is gated by typed ownership. Diffmogger only launches write groups when it can derive non-overlapping resource leases from direct paths, exact symbol ownership, or accepted scope evidence. Integration remains serialized so the main checkout stays coherent.

## Generated Targets

New target repos receive a sidecar namespace:

```text
.diffmogger/agentic/      prompts, intake, role instructions, and dashboard preferences
.diffmogger/context/      imported project context files
.diffmogger/lib/          bundled Diffmogger Python runtime
.diffmogger/runtime/      SQLite state, logs, queues, worktrees, leases, reports, review artifacts
.diffmogger/scripts/      target-local command wrappers and shell helpers
.diffmogger/schemas/      exported state contracts
.diffmogger/state/        generated human and agent-facing projections
.diffmogger/manifest.json sidecar ownership and path manifest
```

The generated target repo should not need the Diffmogger source checkout at runtime. The source checkout and native dashboard are used to scaffold, operate, validate, and inspect target sidecars.

## Dashboard

The native dashboard lives in `services/agentic-dashboard/native/` and calls `scripts/dashboard_backend_cli.py`. The app has two surfaces: **Setup** for choosing/configuring a target and **Automation** for scheduler next action, tickets/actions, generated unblocker work, human input records, and Start/Stop/Safety commands. The backend exposes allowlisted JSON commands for project setup, scaffold, run control, ticket queues, canonical state snapshots, execution graph progress, worker controls, validation jobs, safety checks, execution-group debug bundles, and task projection opening.

Useful dashboard commands:

```bash
bash scripts/build_native_dashboard_app.sh
cd services/agentic-dashboard/native
npm test
npm run build
npm run tauri build
```

Backend smoke:

```bash
python3 scripts/dashboard_backend_cli.py diagnostics.environment
python3 scripts/dashboard_backend_cli.py state.snapshot --target /path/to/target
```

First review checklist: after scaffold, run **Run Safety Check** and render observatory artifacts from the target helper when needed. The helper writes `Diffmogger-observatory.html` and `Diffmogger-self-review.md`.

```bash
python3 .diffmogger/scripts/run_observatory.py --target . --review-dir /tmp/Diffmogger-review
```

## Source Layout

```text
src/diffmogger/                 Canonical Python source
src/diffmogger/kit/             Source-kit scaffold and validation tools
src/diffmogger/runtime/         Target runtime entrypoints, state helpers, and scheduler controls
src/diffmogger/integrator/      Serialized patch integration, git safety, verification, and progress logic
src/diffmogger/observatory/     Snapshot, scoring, render, review, and local server logic
src/diffmogger/dashboard/       Native dashboard backend CLI and command handlers
scripts/                        Stable root command wrappers
templates/                      Files rendered into generated target repos
schemas/ and validation/starter_kit_manifest.json  Schemas and source inventory
services/agentic-dashboard/     Native dashboard docs and Tauri app
services/agentic-notifier/      Optional local/Discord notifier service
docs/                           Active Diffmogger documentation
tests/{kit,runtime,dashboard}/  Source-kit, runtime, and dashboard test groups
```

## Safety Defaults

- Keep secrets out of prompts, examples, target state, inboxes, and docs.
- Use placeholders only in public examples.
- Keep notifier credentials inside `services/agentic-notifier/.env`.
- Treat notifier, MCP, ticket notifications, and browser automation as optional local features.
- Keep automation local-only unless a target explicitly opts into local runs with configured remotes.
- Review diffs before trusting autonomous changes.

Status values are `ACTIVE`, `ACTIVE_WITH_PENDING_USER_INPUT`, `BLOCKED_ON_USER`, `BLOCKED_ON_ENVIRONMENT`, and `CRITICAL_STOP`. `BLOCKED_ON_USER` and `BLOCKED_ON_ENVIRONMENT` do not pause automation while any independent or unblocker work can continue; only complete ticket exhaustion stops automation.

Failed validation is scheduler input, not a stop state. Required check failures create repair work; missing tools create setup/harness work; external services create mock, local-fixture, or defer work; browser/MCP failures create alternate validation or deferred QA work; repeated failures create planner split/reframe/defer work. Only unsafe, destructive, or corrupt states may become `CRITICAL_STOP`.

## Validation

Run the full local validation before publishing kit changes:

```bash
bash scripts/validate_starter_kit.sh
```

Useful focused checks:

```bash
python3 scripts/validate_starter_kit_manifest.py validation/starter_kit_manifest.json
python3 scripts/check_integration_safety.py
python3 -m unittest tests.kit.test_check_required_files tests.kit.test_check_integration_safety tests.kit.test_starter_kit_manifest
```

If scaffolding behavior changes, also run the scaffold smoke:

```bash
python3 scripts/scaffold_project_docs.py --intake examples/generic-web-app/project_intake.md --target /tmp/Diffmogger-smoke --force
python3 scripts/check_required_files.py /tmp/Diffmogger-smoke
```

## Docs

Start with [docs/README.md](docs/README.md). Most-used docs:

- [Fresh Project Setup](docs/FRESH_PROJECT_SETUP.md)
- [Dashboard](docs/DASHBOARD.md)
- [Operating Model](docs/OPERATING_MODEL.md)
- [Human Bridge](docs/HUMAN_BRIDGE.md)
- [Worker Agents](docs/WORKER_AGENTS.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

Architecture notes: [Native Dashboard](docs/architecture/native-dashboard.md), [DAG Symbol Scheduler Audit](docs/architecture/dag-symbol-scheduler-audit.md), [Symbol Identity Contract](docs/architecture/symbol-identity-contract.md), and [Concurrency Readiness Audit](docs/architecture/concurrency-readiness-audit.md).

## License

Diffmogger is released under the MIT License. See `LICENSE`.
