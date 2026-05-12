# Development

This is the contributor guide for the Diffmogger source kit. Generated target-project state docs live under `templates/docs/` and should not be edited through root docs.

## Prerequisites

- Git.
- Python 3.10 or newer.
- Codex CLI installed and authenticated.
- Node/npm and Rust when touching the native dashboard.
- A virtual environment for notifier work.

Keep secrets outside prompts, examples, generated state, and public docs. Real notifier values belong only in ignored local `.env` files.

## Common Commands

```bash
bash scripts/validate_starter_kit.sh
python3 scripts/check_integration_safety.py
python3 scripts/validate_starter_kit_manifest.py validation/starter_kit_manifest.json
```

Scaffold smoke:

```bash
python3 scripts/scaffold_project_docs.py \
  --intake examples/generic-web-app/project_intake.md \
  --target /tmp/Diffmogger-smoke \
  --force

python3 scripts/check_required_files.py /tmp/Diffmogger-smoke
```

Native dashboard:

```bash
cd services/agentic-dashboard/native
npm test
npm run build
npm run tauri build
```

Notifier:

```bash
cd services/agentic-notifier
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest
```

## Python Source Ownership

Canonical Python source lives under `src/diffmogger/`.

- `src/diffmogger/kit/`: source-kit tools such as scaffold, required-file check, starter-kit manifest validation, integration-safety check, and native dashboard command guardrails.
- `src/diffmogger/runtime/`: target runtime entrypoints, helpers, and canonical SQLite state store bundled under `.diffmogger/lib/diffmogger/`.
- `src/diffmogger/conveyor/`: continuous conveyor decisions, active-role recovery, ticket stop/finalization, and role runner logic.
- `src/diffmogger/integrator/`: multi-role integration, git safety, verification, baseline, commit, progress, notifier, and cleanup logic.
- `src/diffmogger/observatory/`: observatory snapshot, scoring, render, and server logic bundled with the runtime entrypoint.
- `src/diffmogger/dashboard/`: backend CLI and shared helpers used by the native dashboard.
- `scripts/*.py`: stable public compatibility entrypoints only.
- `scripts/runtime/*.py`: source-checkout copies of generated target runtime wrappers.
- `scripts/target/*.sh`: source-checkout copies of target-local shell helpers.
- `scripts/validation/*.py`: validation-only compatibility entrypoints.
- `templates/scripts/*.sh`: physical shell templates for generated targets.

Keep source-kit implementation in `src/diffmogger/kit/`, conveyor logic in `src/diffmogger/conveyor/`, integrator logic in `src/diffmogger/integrator/`, observatory logic in `src/diffmogger/observatory/`, and target runtime entrypoints in `src/diffmogger/runtime/`. Do not split the ticket, browser, or repair runtime modules unless that refactor is explicitly in scope.

## Generated Target Contract

The generated sidecar layout is the supported target architecture:

```text
.diffmogger/agentic/
.diffmogger/state/
.diffmogger/scripts/
.diffmogger/lib/diffmogger/
.diffmogger/runtime/
.diffmogger/schemas/
.diffmogger/manifest.json
```

Generated target Python wrappers are rendered from `src/diffmogger/kit/wrapper_template.py` and the runtime entrypoint manifest. They import from `.diffmogger/lib`; they are not tracked as templates under `templates/scripts/`.

Shell entrypoints remain physical templates because locks, detached runner launch, role runners, and worker helpers need local executable files in each target.

Canonical live orchestration state is `.diffmogger/runtime/orchestration.sqlite3`. `.diffmogger/runtime/canonical_state_brief.md` is the generated bounded state view agents read at run start. Markdown files under `.diffmogger/state/` and JSON files such as `.diffmogger/runtime/automation_conveyor_state.json` and `.diffmogger/runtime/automation_runner.json` are generated views, prompt inputs, exports, authored surfaces, or compatibility projections.

## Adding Or Moving Source Files

When adding supported source, template, service, test, docs, or native-dashboard files:

1. Put implementation in `src/diffmogger/` when it is Python.
2. Keep root command names stable when users may call them directly.
3. Update `validation/starter_kit_manifest.json`.
4. Put tests under `tests/kit/`, `tests/runtime/`, or `tests/dashboard/` and import package modules, not root wrappers.
5. Run `python3 scripts/validate_starter_kit_manifest.py validation/starter_kit_manifest.json`.
6. Run the relevant focused tests and `bash scripts/validate_starter_kit.sh`.

The manifest is the source inventory. It also enforces ignored artifacts, source entrypoint wrappers, generated runtime wrappers, and the rule that tracked Python wrapper templates do not live under `templates/scripts/`.

## Native Dashboard

The native dashboard is the only user-facing dashboard. The React/Tauri app lives under `services/agentic-dashboard/native/` and calls `scripts/dashboard_backend_cli.py`.

Backend behavior belongs in `src/diffmogger/dashboard/cli.py`, `src/diffmogger/dashboard/commands/`, `src/diffmogger/dashboard/target.py`, `src/diffmogger/dashboard/jsonio.py`, and `src/diffmogger/dashboard/shared/`. `src/diffmogger/dashboard/backend_cli.py` is a compatibility facade. The frontend should call backend commands, including `state.snapshot` for canonical state, instead of scraping Markdown or reimplementing scaffold/automation logic in TypeScript.

The packaged app is source-checkout-backed. `DIFFMOGGER_KIT_ROOT=/path/to/Diffmogger` can point the backend at another checkout for debugging.

Run `bash scripts/validate_native_app.sh` when changing dashboard command contracts, native Rust allowlists, or frontend behavior.

## Docs Policy

Keep root docs short and current.

- `README.md`: project orientation and quickstart.
- `DEVELOPMENT.md`: contributor workflow and source ownership.
- `docs/README.md`: map and ownership guide.
- `docs/DASHBOARD.md`: native dashboard plus backend CLI.
- `docs/archive/`: decision records and compact historical notes with enduring maintenance value only.

Delete obsolete docs. Archive only when the historical decision still helps maintain the current sidecar, native-dashboard, or `src/diffmogger` architecture.

Generated target-state docs under `templates/docs/` are active templates; do not delete them as part of root-doc cleanup unless the generated target contract changes.

## Safety Rules

- No real credentials in examples, docs, generated state, tests, or prompts.
- File-only human bridge remains the safe default.
- Notifier credentials stay in `services/agentic-notifier/.env`.
- Optional MCP setup is project-scoped and advisory; do not mutate user/global Codex config.
- Multi-role and conveyor automation are local-first and must not push, fetch, pull, configure remotes, or set upstream tracking by default.
- Review generated diffs before trusting autonomous changes.

## Release Checklist

Before publishing a source-kit change:

1. Run `bash scripts/validate_starter_kit.sh`.
2. Run `python3 scripts/check_integration_safety.py`.
3. Run native dashboard checks if dashboard code changed.
4. Run notifier tests if notifier code changed.
5. Confirm generated target docs and examples contain placeholders only.
6. Confirm public docs do not describe removed dashboards or obsolete source ownership.
