<p align="center">
  <img src="docs/assets/diffmogger-logo-cropped.png" alt="Diffmogger" width="720">
</p>

Diffmogger provides local automation infrastructure for continuous Codex work. It turns a repo into a stateful automation loop with durable prompts, Markdown state, target-local runtime wrappers, a planner/builder/hardener/integrator conveyor, patch queues, safety checks, human handoff files, review exports, a native dashboard, and a CLI.

It is not a hosted agent platform or a product-specific app. Diffmogger is built for solo and small-team repos that want Codex runs to preserve context, recover from blockers, route work through specialized roles, and compound over time instead of restarting from a blank prompt.

## What It Provides

- A native Tauri dashboard for setup, ticket-campaign queue creation/management, Start/Stop run control, safety checks, review export, inbox messages, and activity monitoring.
- A generated sidecar layout under `.diffmogger/` so target repos keep Diffmogger-owned prompts, state, runtime files, queues, worktrees, logs, and manifests out of product-owned paths.
- Thin target-local Python wrappers under `.diffmogger/scripts/` that import the bundled `.diffmogger/lib/diffmogger/` runtime.
- A continuous planner/builder/hardener/integrator conveyor that chooses the next lane from current state, queued patches, blockers, baseline verification, and human inbox status.
- Stable root CLI command names while implementation lives under `src/diffmogger/`.
- A Markdown operating model with explicit status: `ACTIVE`, `ACTIVE_WITH_PENDING_USER_INPUT`, `BLOCKED_ON_USER`, `BLOCKED_ON_ENVIRONMENT`, and `CRITICAL_STOP`.
- Optional worker agents, optional ticket campaigns, optional Context7/Playwright MCP setup, optional notifier integration, and single-lane fallback for legacy targets.

## Quickstart

```bash
git clone https://github.com/harrisonpedrero/diffmogger.git Diffmogger
cd Diffmogger
bash scripts/validate_starter_kit.sh
cd services/agentic-dashboard/native
npm install
npm run tauri dev
```

In the dashboard:

1. Pick a fresh or existing target repo.
2. Fill in the project intake.
3. Add optional context files.
4. Run **Scaffold & Bootstrap**.
5. Review **Run Safety Check** and **Export Review Bundle** after the first run.

CLI scaffold path:

```bash
python3 scripts/scaffold_project_docs.py \
  --intake examples/generic-web-app/project_intake.md \
  --target /tmp/Diffmogger-smoke \
  --force

python3 scripts/check_required_files.py /tmp/Diffmogger-smoke
```

## Source Layout

```text
src/diffmogger/                 Canonical Python source.
src/diffmogger/kit/             Source-kit tools such as scaffold and validation.
src/diffmogger/runtime/         Target runtime entrypoints and helpers.
src/diffmogger/conveyor/        Continuous conveyor state, decisions, active-role recovery, and runner logic.
src/diffmogger/integrator/      Multi-role integration, git safety, verification, and progress logic.
src/diffmogger/observatory/     Observatory snapshot, scoring, render, and server logic.
src/diffmogger/dashboard/       Native dashboard backend CLI and shared helpers.
scripts/                        Stable root command wrappers.
scripts/runtime/                Source-checkout copies of generated runtime wrappers.
scripts/target/                 Source-checkout copies of target shell helpers.
scripts/validation/             Validation-only wrapper entrypoints.
templates/                      Files rendered into generated target repos.
validation/starter_kit_manifest.json
                                 Source and entrypoint inventory.
services/agentic-dashboard/     Native dashboard docs and Tauri app.
services/agentic-notifier/      Optional local/Discord notifier service.
docs/                           Active Diffmogger documentation.
tests/{kit,runtime,dashboard}/  Source-kit, runtime, and dashboard test groups.
```

Root Python commands are compatibility entrypoints. The supported public names remain:

```bash
python3 scripts/scaffold_project_docs.py
python3 scripts/check_required_files.py
python3 scripts/validate_starter_kit_manifest.py
python3 scripts/check_integration_safety.py
python3 scripts/dashboard_backend_cli.py
```

Implementation belongs in `src/diffmogger/kit/`, `src/diffmogger/runtime/`, `src/diffmogger/conveyor/`, `src/diffmogger/integrator/`, `src/diffmogger/observatory/`, or `src/diffmogger/dashboard/`.

## Generated Targets

New target repos receive a sidecar namespace:

```text
.diffmogger/agentic/      automation prompts and intake
.diffmogger/state/        durable Markdown task, context, bridge, and review state
.diffmogger/scripts/      target-local wrappers and shell helpers
.diffmogger/lib/          bundled Python runtime from src/diffmogger/
.diffmogger/runtime/      logs, queues, locks, worker reports, review state
.diffmogger/manifest.json generated ownership and path manifest
```

The target repo should not need the Diffmogger checkout at runtime. The native dashboard and CLI tools are for creating, validating, and operating target sidecars.

## Dashboard

The native dashboard is the only user-facing dashboard. It lives in `services/agentic-dashboard/native/` and calls `scripts/dashboard_backend_cli.py`, which exposes allowlisted JSON commands for scaffold, diagnostics, Start/Stop automation, safety checks, inbox messages, Observatory snapshots, review bundles, worker controls, and debug bundles.

For ticket-campaign targets, the dashboard manages the canonical `.diffmogger/state/TICKET_RUN.md` through a structured Ticket Queue. Users can seed tickets before scaffold, inspect/edit/delete tickets after scaffold, preview/apply Markdown/CSV/JSON imports, and accept review-only Codex draft candidates stored under `.diffmogger/runtime/ticket_drafts/`.

Useful dashboard commands during development:

```bash
cd services/agentic-dashboard/native
npm test
npm run build
npm run tauri build
```

Backend smoke:

```bash
python3 scripts/dashboard_backend_cli.py diagnostics.environment
```

## First Review Checklist

After scaffolding or before a demo:

1. Run `bash scripts/validate_starter_kit.sh` in the Diffmogger source checkout.
2. Open the target in the native dashboard with **Open Diffmogger Project**.
3. Run **Run Safety Check**.
4. Use **Export Review Bundle** or run `python3 .diffmogger/scripts/run_observatory.py --target . --review-dir /tmp/Diffmogger-review`.
5. Inspect `/tmp/Diffmogger-review/Diffmogger-observatory.html` and `/tmp/Diffmogger-review/Diffmogger-self-review.md`.

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

The manifest enforces source ownership, stable wrapper entrypoints, generated runtime wrappers, ignored build artifacts, and the absence of tracked `templates/scripts/*.py` Python wrappers.

## Safety Defaults

- Keep secrets out of prompts, examples, target state, inboxes, and docs.
- Keep notifier credentials inside `services/agentic-notifier/.env`.
- Use file-only human bridge mode by default.
- Treat notifier, MCP, ticket notifications, and browser automation as optional local features.
- Keep multi-role automation local-only unless a target explicitly opts into local runs in repos with configured remotes.
- Review diffs before trusting autonomous changes.

## Docs

Start with [docs/README.md](docs/README.md). The most-used docs are:

- [docs/FRESH_PROJECT_SETUP.md](docs/FRESH_PROJECT_SETUP.md)
- [docs/DASHBOARD.md](docs/DASHBOARD.md)
- [docs/OPERATING_MODEL.md](docs/OPERATING_MODEL.md)
- [docs/HUMAN_BRIDGE.md](docs/HUMAN_BRIDGE.md)
- [docs/WORKER_AGENTS.md](docs/WORKER_AGENTS.md)
- [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)

## License

Diffmogger is released under the MIT License. See `LICENSE`.
