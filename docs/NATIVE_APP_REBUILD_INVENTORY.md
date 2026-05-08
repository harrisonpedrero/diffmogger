# Native App Rebuild Inventory

This is a historical preservation inventory for the native dashboard migration. The native Tauri app
is now the active dashboard path; keep this file as a guardrail checklist for behavior that must stay
available through backend commands and tests.

Legacy path note: this inventory intentionally documents the pre-sidecar dashboard contracts and may mention generated `.agentic/`, `docs/`, or `target/` paths. New generated targets resolve those surfaces through `.diffmogger/manifest.json` and store Diffmogger-owned files under `.diffmogger/`.

## Scope

- Old dashboard launcher: `python3 scripts/run_dashboard.py`
- Old dashboard implementation: `services/agentic-dashboard/agentic_dashboard/app.py`
- Observatory generator/server: `scripts/run_observatory.py` and `templates/scripts/run_observatory.py`
- Scaffold source of truth: `scripts/scaffold_project_docs.py`, `templates/`, and `schemas/project_intake.schema.json`
- Validation and tests: `scripts/validate_starter_kit.sh`, `scripts/check_required_files.py`, `scripts/check_integration_safety.py`, and `tests/`

Do not remove legacy dashboard/backend helpers unless the native app has equivalent backend commands
and coverage for the preserved behavior below.

## Implemented First-Step Backend Commands

The first migration step added `scripts/dashboard_backend_cli.py`, a JSON-only backend CLI for the
Tauri v2 frontend. It wraps existing dashboard, scaffold-validation, and Observatory helpers behind
the native command boundary.

Implemented commands:

- `project.load_snapshot --target <path>`: returns a Home-like target snapshot with brief, run,
  registered file, and compact action summary data.
- `project.list_recent`: returns a stable recent-project list shape, currently sourced from
  dashboard-owned LaunchAgent plists and `DIFFMOGGER_RECENT_PROJECTS`.
- `brief.load --target <path>`: returns target metadata, `.agentic/project_intake.json` when present,
  `.agentic/dashboard_state.json` when present, autosaved draft intake, and detected repo/package
  command context.
- `brief.save_draft --target <path> --intake-json <json>`: writes dashboard-compatible draft state
  into target-local `.agentic/dashboard_state.json` without scaffolding.
- `context.import --target <path> --files-json <json> --project-name <name>`: copies selected
  source files into target `docs/context/`, updates the managed context index in
  `docs/PROJECT_CONTEXT.md`, and updates intake/draft context-file references.
- `inbox.load --target <path>`: parses the file-only human bridge into requests, queued notes,
  archive records, outbox records, and counts without requiring the frontend to scrape Markdown.
- `inbox.send_note --target <path> --body <text> --intent <intent> [--related <id>]`: reuses the
  old dashboard human-bridge writer to queue a note for the next automation run.
- `inbox.reply_request --target <path> --request-id <id> --body <text> --intent <intent>`: reuses
  the old dashboard reply writer to queue a structured reply linked to an automation request.
- `brief.scaffold_preview --target <path> --intake-json <json> [--force]`: returns the scaffold
  file plan, managed-section vs skip/overwrite actions, dirty-git warnings, and prerequisite
  warnings without writing target files.
- `brief.scaffold_bootstrap --target <path> --intake-json <json> [--force] [--run-codex]`: writes
  `.agentic/project_intake.json`, runs the existing scaffold generator and required-file
  validation, streams JSONL progress when requested, and only runs Codex bootstrap when explicitly
  requested.
- `run.load --target <path>`: returns the Observatory-derived task, human, queue, conveyor,
  scorecard, worker-strategy, review, baseline verification, run-control enablement, schedule
  status, latest log, worker controls, and environment blocker state.
- `run.load_log --target <path>`: loads the latest target-local automation log from the
  dashboard-managed automation log directory.
- `run.once --target <path>`: streams one target-local `.diffmogger/scripts/run_codex_automation.sh` run and
  records completion/failure in `.agentic/dashboard_state.json`.
- `schedule.start --target <path>`: preserves the old dashboard launchd start path for single-lane,
  fixed multi-role, and continuous conveyor schedules.
- `schedule.pause --target <path>`: preserves the old dashboard launchd pause/disable path.
- `schedule.remove --target <path>`: unloads, clears disabled launchd state, deletes
  dashboard-managed LaunchAgent plists, and records `last_action=schedule_removed` without deleting
  generated project files.
- `safety.run_check --target <path>`: runs the existing integration-safety check and records
  `target/integration_safety_check.json` plus dashboard last-action state.
- `worker.run_read_only --target <path>`, `worker.run_write --target <path> --ownership <scope>`,
  and `worker.run_integrator --target <path>`: wrap the existing worker command builders and gate
  launches by the Observatory worker strategy.
- `observatory.generate_html --target <path> --review-dir <path>`: writes only
  `Diffmogger-observatory.html` from the existing Observatory renderer.
- `observatory.snapshot --target <path>`: returns the native Observatory data model for mission
  state, automation status, horizon, scorecard, conveyor roles, active run, progress story, landed
  work, queue/deferred status, validation/safety, and signal nudges.
- `observatory.load_html --target <path> --review-dir <path>`: writes the same Observatory HTML
  artifact and returns the generated HTML so review bundles and browser inspection keep the old
  dark Observatory export intact.
- `review.load --target <path>`: returns trust-review data for latest run summary, changed files,
  landed commits, verification, safety, limitations, self-review preview, bundle paths, and reviewed
  marker state.
- `review.export_bundle --target <path> --review-dir <path>`: writes
  `Diffmogger-observatory.html`, `Diffmogger-self-review.md`, and updates
  `target/action_plan_history.json` through the existing Observatory export path.
- `review.mark_reviewed --target <path> [--note <text>]`: writes a target-local
  `.agentic/reviewed.json` marker without mutating source-checkout state.
- `diagnostics.environment`: returns targetless native setup checks, effective automation/backend
  PATH, resolved tool paths, backend Python version, kit root, and copyable fix commands.
- `diagnostics.run_checks --target <path>`: returns native automation prerequisite checks, generated
  required-file validation when applicable, the existing integration-safety check result, runtime
  environment details, and copyable fix commands. Tkinter is reported as legacy-dashboard advisory
  context instead of blocking native automation controls.
- `advanced.list_files --target <path>`: returns the allowlisted dashboard/bridge/state files a
  native frontend may load.
- `advanced.load_file --target <path> --file-key <key>`: loads only an allowlisted file key, never an
  arbitrary path.
- `advanced.save_file --target <path> --file-key <key> --content <text>`: writes only editable
  allowlisted managed files and refuses read-only artifacts or the Diffmogger source checkout.
- `advanced.validate_file --target <path> --file-key <key>`: runs registered per-file validation
  such as JSON parsing or required-file validation.
- `advanced.export_debug_bundle --target <path> --output-dir <path>`: writes a redacted ZIP with
  diagnostics, backend command metadata, dashboard state, project intake, latest safety record, and
  latest run log when present; `.env` contents and secret-like values are omitted/redacted.

All command results use `{ "schema_version": 1, "ok": true|false, ... }`. Command errors are
structured JSON on stdout with non-zero exit codes. Target paths are resolved and validated before
read/write operations.

## Implemented Native Shell

The second migration step added `services/agentic-dashboard/native`, a Tauri v2 + React/TypeScript
app shell. It is intentionally a thin native client over `scripts/dashboard_backend_cli.py`; the
legacy `python3 scripts/run_dashboard.py` launcher remains available as a compatibility surface.

Implemented shell surfaces:

- Tauri v2 app with React/TypeScript, hidden platform titlebar, and custom titlebar controls.
- Left navigation: Home, Brief, Run, Observatory, Inbox, Review, Advanced.
- Top bar: compact project chip, status pill, refresh button, command palette button.
- Native folder picker through Rust `rfd::FileDialog`; no large target path input in the frontend.
- App-local recent target config at the Tauri app config directory, stored separately from
  target-local `.agentic/dashboard_state.json`.
- Narrow Rust command layer exposing only app-local recents, folder selection, and an allowlisted
  subprocess wrapper around the Python backend CLI.
- Initial frontend API client in `src/api/backend.ts` for `selectProjectFolder`, `listRecentProjects`,
  `loadProjectSnapshot`, and `runBackendCommand`.
- Initial UI states for no target selected, target loaded, backend error, and loading.
- Implemented Home page state model and UI, replacing the vague Overview concept with project,
  activity, next-action, safety/readiness, progress, and human-bridge cards derived from the backend
  snapshot.
- Implemented Brief as a guided intake wizard with old dashboard fields reorganized into Project,
  Goal, Stack, Automation Mode, Guardrails, Context Files, and Review & scaffold steps.
- Brief autosaves draft state to target-local `.agentic/dashboard_state.json`, imports context files
  through the backend CLI into `docs/context/`, and uses a native file picker for context imports.
- Brief owns the `Scaffold & Bootstrap` pipeline: it previews file actions before writing, marks
  existing-project managed-section updates separately from files that will not be overwritten,
  surfaces dirty-git/prerequisite warnings, streams backend progress logs, and reports
  `FIRST_REVIEW_NEEDED` or `READY_TO_RUN` after the generated target contract validates.
- Implemented Run as the canonical automation controls page. It gates unscaffolded projects with
  "Finish the Brief before running automation", exposes Run Once Now, Start Schedule, Pause
  Schedule, Run Safety Check, Review export navigation, schedule status, current/latest run state,
  a dark terminal-style log with copy/open-log actions, worker strategy controls, raw strategy
  disclosure, and environment blockers.
- Implemented Inbox as a developer-friendly file-only bridge surface with Requests, Notes to next
  run, and Archive tabs. It loads automation-originated requests, queues replies/notes through
  backend commands, reflects queued/archived/failed note state, and keeps raw Markdown file access
  in Advanced rather than making raw files the primary inbox UI.
- Implemented Review as the trust surface: latest run summary, changed files, landed commits,
  verification, safety, skipped/environment limitations, self-review Markdown preview/open action,
  review bundle export, reviewed marker, and follow-up note to the next run through the Inbox
  backend path.
- Implemented the Observatory page as native dark React components over `observatory.snapshot`,
  preserving the old `Diffmogger Autonomous Build Log` visual identity with dense mission,
  conveyor, progress, landed-work, outcome, signal, patch, and metrics panels. The page still keeps
  the existing HTML export path through `observatory.load_html` and provides Refresh, Open in
  Browser, Export Bundle, and Copy path actions.
- Implemented Advanced as the power-user surface for allowlisted raw file editing, diagnostics,
  app-local settings, and redacted debug bundles. Raw file operations use backend commands and
  native open/reveal actions validate managed file keys before touching local paths.
- Implemented a native command palette on Cmd+K/Ctrl+K with searchable project, Brief, Run,
  Observatory, Review, Inbox, and Advanced commands. Commands share the same backend/native wrappers
  as visible buttons, disabled commands explain their state gate, and higher-risk commands confirm
  or route back to their owning page.
- Added native Observatory state-mapping and server-rendered component tests for empty state,
  active builder, queued patch, blocked user, and critical stop cases.
- Added frontend state-mapping tests for Home primary CTA behavior across no target, unconfigured,
  scaffolded/no-run, running, blocked-on-user, and blocked-on-environment states.
- Added frontend state-mapping tests for Run control enablement and worker strategy translation.

Security posture:

- The frontend does not receive shell/process permissions.
- The Tauri shell does not enable broad filesystem plugins.
- Target paths are validated in Rust before invoking the Python backend.
- The only process execution path is `python3 scripts/dashboard_backend_cli.py` with allowlisted
  backend command names.

## Feature Preservation Table

| Feature | User value | Current implementation | State files touched | Proposed backend command | Existing tests | Missing tests |
| --- | --- | --- | --- | --- | --- | --- |
| Dashboard launcher and repo `.env` loading | Launches the local dashboard/backend while inheriting optional runtime values such as `CONTEXT7_API_KEY` without printing or copying secrets. | `scripts/run_dashboard.py`: `load_repo_dotenv`, `load_dotenv_file`, `main`. Backend CLI entry: `scripts/dashboard_backend_cli.py`. Native Rust process wrapper resolves the backend Python/PATH before invoking it. | Reads starter repo `.env`; mutates dashboard/backend process environment only. | Implemented: backend CLI loads the repo `.env` with the old launcher parser before handling commands; Rust keeps `DIFFMOGGER_KIT_ROOT` override support for alternate checkouts. | `tests/test_run_dashboard_env.py`; `tests/test_dashboard_backend_cli.py` covers backend dotenv loading/no override; `scripts/validate_starter_kit.sh` py-compile and marker checks. | End-to-end packaged-app test proving the spawned backend inherits loaded values and never logs secret values. |
| Prerequisite checks | Blocks unsafe bootstrap when required local tools are missing and surfaces optional advisories before scheduling. | `app.py`: `check_prerequisites`, `format_prerequisites`, `required_failures`, `refresh_prerequisites`, `_schedule_prerequisites`, `command_detail`, `fetch_notifier_health`, `codex_mcp_detail`, `managed_browser_path`. Backend CLI: `diagnostics.environment`, `diagnostics.run_checks`. | Reads PATH, Python/Tk state, target parent permissions, `~/.codex`, optional notifier health endpoint, optional Codex MCP list, optional browser cache; no target writes. | Implemented: targetless `diagnostics.environment`; target-scoped `diagnostics.run_checks --target <path>` with `runtime_environment` and `fix_suggestions`. Tkinter is legacy-dashboard advisory for native. | Dashboard smoke marker in `scripts/validate_starter_kit.sh`; safety affordance tests in `tests/test_check_integration_safety.py`; docs coverage in `docs/DASHBOARD.md`; CLI smoke and native-Tk reclassification in `tests/test_dashboard_backend_cli.py`. | Direct matrix tests for every required/advisory item, including missing Codex, unwritable target parent, Context7 key, Playwright browser, notifier health, and macOS Documents advisory. |
| Fresh-project setup | Gives a guided path for creating a new target project from a reusable intake. | `app.py`: setup wizard variables, `collect_intake`, `start_scaffold_bootstrap`, `_scaffold_bootstrap_worker`; `scripts/scaffold_project_docs.py`: `placeholders`, `scaffold`; native `src/BriefWizard.tsx`. | Writes target `.agentic/project_intake.json`, `.agentic/`, `docs/`, `scripts/`, optional `.git/info/exclude`, and `.agentic/dashboard_state.json`; may run initial Codex bootstrap. | Implemented: `brief.scaffold_preview --target --intake-json [--force]`; `brief.scaffold_bootstrap --target --intake-json [--force] [--run-codex]`. Future alias: `project scaffold-bootstrap --target --intake-json --mode fresh_project --context-file ... --force --bootstrap`. | `tests/test_check_required_files.py`; generic smoke in `scripts/validate_starter_kit.sh`; example intakes; `tests/test_dashboard_backend_cli.py` scaffold smoke, preview, and JSONL stream tests without Codex auth. | Fake `codex` test proving bootstrap command shape and cancellation/process cleanup. |
| Existing-project setup | Adds Diffmogger to an existing repo without replacing project-owned guidance. | `app.py`: `existing_project_var`, `collect_intake`; `scaffold_project_docs.py`: `MANAGED_EXISTING_PROJECT_FILES`, `render_managed_section`, `upsert_managed_section`, `install_diffmogger_local_excludes`; backend CLI `scaffold_file_preview`. | Updates existing `AGENTS.md` and `docs/DEVELOPMENT.md` inside managed blocks; writes target Diffmogger files; updates `.git/info/exclude`. | Implemented through `brief.scaffold_preview` and `brief.scaffold_bootstrap` with `project_mode: existing_project`. Future alias: `project scaffold --target --intake-json --mode existing_project --force-policy managed-blocks`. | Existing-project local exclude smoke in `scripts/validate_starter_kit.sh`; `tests/test_dashboard_backend_cli.py` covers managed-section preview and preservation of pre-existing content. | Idempotent managed-block tests across repeated native runs and dashboard/native reopen tests for existing projects. |
| Project intake fields | Captures all project-agnostic setup data needed by scaffold, scheduling, human bridge, workers, MCP, ticket mode, and long-run direction. | `schemas/project_intake.schema.json`; `app.py`: `collect_intake`, `_apply_intake_to_form`, `_apply_dashboard_state`; `scaffold_project_docs.py`: `HEADING_TO_KEY`, normalization helpers, `placeholders`; native `src/BriefWizard.tsx`. | Reads/writes `.agentic/project_intake.json`; duplicates UI state into `.agentic/dashboard_state.json`; autosaved draft uses `brief_draft_intake`. | Implemented: `brief.load --target`, `brief.save_draft --target --intake-json`, `brief.scaffold_bootstrap --target --intake-json`. Future aliases: `intake get|validate|write --target --json`; `intake defaults --json`. | Schema marker checks in `scripts/validate_starter_kit.sh`; scaffold examples in `tests/test_check_required_files.py`; `tests/test_dashboard_backend_cli.py` draft save/load round trip. | Full round-trip test for every schema field through dashboard/native state, including booleans, list fields, MCP options, schedule strategy, ticket campaign, environment access, and write-worker caps. |
| Context-file import | Lets users add PDFs, notes, CSVs, designs, and other reusable context without depending on the starter checkout at runtime. | `app.py`: `add_context_files`, `remove_context_file`, `safe_context_filename`, `copy_context_files`; backend CLI `command_context_import`; native `src/BriefWizard.tsx` plus Rust `select_context_files`. | Copies selected files into target `docs/context/`; updates intake/draft `additional_context_files`; updates `docs/PROJECT_CONTEXT.md`. | Implemented: `context.import --target --files-json --project-name`. Future alias: `context import --target --file ... --json`. | Public docs and README mention the behavior; generic scaffold includes context markers; `tests/test_dashboard_backend_cli.py` covers copy plus context index and draft update. | Tests for duplicate names, existing target files, binary files, missing files, and explicit "no secrets" warning behavior. |
| Project-context generation and context index | Gives bootstrap and recurring runs a durable, Markdown-first index of imported context. | `app.py`: `render_project_context`, `render_context_imports_section`, `upsert_context_imports`; template `templates/docs/PROJECT_CONTEXT.md`; backend CLI `update_context_index`. | Writes or updates `docs/PROJECT_CONTEXT.md`; uses managed `DIFFMOGGER:CONTEXT-IMPORTS` markers when preserving an existing context file. | Implemented through `context.import --target --files-json --project-name`. Future split: `context index --target --project-name --records-json --merge`. | `scripts/validate_starter_kit.sh` checks `PROJECT_CONTEXT` template markers; `tests/test_dashboard_backend_cli.py` covers initial context index render. | Tests for managed-section upsert, preservation of user-authored context notes, and repeated imports. |
| Scaffold/bootstrap pipeline | One action turns intake into a target-local automation kit and starts the initial bootstrap run. | `app.py`: `start_scaffold_bootstrap`, `_scaffold_bootstrap_worker`, `_run_command`, `_terminate_process_group`; `scaffold_project_docs.py`; `check_required_files.py`; backend CLI `command_brief_scaffold_bootstrap`; native Tauri `run_backend_command_streamed`. | Writes target automation files, context files, `.agentic/project_intake.json`, `.agentic/dashboard_state.json`, `.git/info/exclude`; streams command output to dashboard/native log. | Implemented: `brief.scaffold_bootstrap --target --intake-json [--force] [--run-codex]`, with `--stream-jsonl` for progress. Future alias: `bootstrap run --target --intake-json --context-file ... --force --start-codex --json-events`. | `tests/test_check_required_files.py`; `scripts/validate_starter_kit.sh` scaffold/check smokes; dashboard smoke check; `tests/test_dashboard_backend_cli.py` JSONL progress and fresh/existing scaffold coverage. | Fake-process integration test for cancellation, child process cleanup, and long Codex output streaming. |
| Bounded dashboard run log and cancel | Keeps long command output usable and stops dashboard-launched process groups, including smoke-test child servers. | `app.py`: `_append_log`, `_run_command`, `_read_available_process_output`, `_terminate_process_group`, `cancel_process`; constants `MAX_DASHBOARD_LOG_LINES`, `MAX_DASHBOARD_LOG_LINE_CHARS`. | UI log only; may terminate subprocess groups created by dashboard commands. | `process run --cwd --json-events`; `process cancel --run-id`. | Marker checks in `scripts/validate_starter_kit.sh` for `start_new_session=True`, `MAX_DASHBOARD_LOG_LINES`, and `os.killpg`. | Unit tests for log truncation, long line truncation, SIGTERM/SIGKILL fallback, and child process cleanup. |
| Dashboard state persistence | Reopens target projects without repeating setup and preserves schedule settings, worker toggles, MCP options, and last action. | `app.py`: `DASHBOARD_STATE_FILE`, `dashboard_state_path`, `write_dashboard_state`, `load_project_state`, `_apply_dashboard_state`, `_target_has_dashboard_state`, `close_dashboard`; native Rust app-local `NativeConfig` for recents and Advanced preferences. | Reads/writes target `.agentic/dashboard_state.json`; reads `.agentic/project_intake.json` and generated docs; native app settings stay in the Tauri app config directory. | Implemented project state through `brief.save_draft`, `brief.scaffold_bootstrap`, `project.load_snapshot`, and native `get_advanced_settings`/`update_advanced_settings` for app-local preferences. | Marker checks in `scripts/validate_starter_kit.sh`; docs in `docs/DASHBOARD.md` and service README; CLI draft round-trip in `tests/test_dashboard_backend_cli.py`. | Direct corrupt JSON recovery tests, schedule status serialization tests, and native config migration tests for older config files. |
| Scheduled automation start/pause/remove | Lets users manage recurring local automation without manually editing LaunchAgents. | `app.py`: `start_scheduled_automation`, `pause_scheduled_automation`, `remove_scheduled_automation`, `_launchctl`, `_set_run_automation_state`, `write_launchd_plist`, `launchd_*` helpers. Backend CLI: `schedule.start`, `schedule.pause`, `schedule.remove`, `run.load` schedule snapshot. Native UI: `RunPage`. | Writes/deletes `~/Library/LaunchAgents/com.diffmogger...plist`; writes `target/automation_logs/`; updates `.agentic/dashboard_state.json`; calls `launchctl`. | Implemented: `schedule.start --target <path>`, `schedule.pause --target <path>`, `schedule.remove --target <path>`, and read-only schedule status in `run.load --target <path>`. | Marker checks in `scripts/validate_starter_kit.sh`; readiness tests in `tests/test_check_integration_safety.py`; mocked remove/idempotency test in `tests/test_dashboard_backend_cli.py`; frontend Run/command-palette state tests in `src/runModel.test.ts` and `src/commandPaletteModel.test.ts`. | Plist snapshot tests for every schedule strategy and a non-macOS command behavior test. |
| Fixed multi-role scheduling | Supports local planner, builder, hardener, and integrator lanes on staggered LaunchAgent schedules. | `app.py`: `write_role_launchd_plist`, `MULTI_ROLE_START_MINUTES`, `start_scheduled_automation`; `scaffold_project_docs.py`: `multi_role_values`. | Writes four role LaunchAgent plists, role logs under `target/automation_logs/`, generated `.agentic/roles/*`, `docs/MULTI_ROLE_PROGRESS.md`, role scripts. | `schedule install --strategy fixed_multi_role --target --allow-remotes=false --json`. | Multi-role scaffold and role runner checks in `scripts/validate_starter_kit.sh`; `tests/test_run_role_automation.py`. | Plist snapshot tests for each role, remote opt-in environment tests, and schedule status tests when some role jobs are loaded/disabled. |
| Continuous conveyor scheduling | Runs one local scheduler that chooses the next useful lane from local state. | `app.py`: `write_conveyor_launchd_plist`, schedule strategy helpers; `scripts/run_conveyor_automation.py`; `scripts/run_conveyor_automation.sh`. | Writes conveyor LaunchAgent, `target/automation_conveyor_state.json`, `target/automation_conveyor.lock`, logs, queue state via conveyor runtime. | `schedule install --strategy continuous_conveyor --target --json`; `conveyor status --target --json`. | `tests/test_run_conveyor_automation.py`; scaffold/marker checks in `scripts/validate_starter_kit.sh`; readiness tests require initial commit. | Dashboard/native command tests for conveyor plist, initial-commit gate, remote opt-in gate, and status reporting from existing conveyor state. |
| Automation readiness and schedule gating | Prevents scheduling before required files, acceptable status, bootstrap/schedule readiness, or initial git commit are ready while still allowing a manual first run when the generated run script exists. | `app.py`: `_automation_ready`, `_target_*` readers, `SCHEDULABLE_STATUSES`. Backend CLI: `run_once_ready`, `automation_ready`, `run_controls_snapshot`. Native UI: `runModel.ts`. | Reads `.agentic/project_intake.json`, `.agentic/dashboard_state.json`, generated scripts/docs, `docs/CODEX_AUTOMATION_TASKS.md`, and git `HEAD`. | Implemented read surface: `run.load --target <path>` returns `controls`; implemented action: `run.once --target <path>`. Future split: `automation readiness --target --json`. | `tests/test_check_integration_safety.py` covers conveyor initial-commit reject/accept; `check_required_files.py` validates generated file sets; `tests/test_dashboard_backend_cli.py` covers run-control JSON for empty/scaffolded targets; `src/runModel.test.ts` covers enabled/disabled button states. | Matrix tests for each status model value, missing required files by strategy, ticket mode, multi-role mode, and malformed task files. |
| Run Safety Check | Gives reviewers a one-click local safety audit and records the result for Observatory/review exports. | `app.py`: `has_integration_safety_tree`, `resolve_integration_safety_target`, `integration_safety_command`, `write_integration_safety_record`, `run_integration_safety_check`, `_integration_safety_worker`; `scripts/check_integration_safety.py`. Backend CLI: `safety.run_check`. Native UI: Run page control. | Writes target `target/integration_safety_check.json`; updates `.agentic/dashboard_state.json`; reads kit or selected target safety files. | Implemented: `safety.run_check --target <path>`. Future alias: `safety check --selected-target --json --record`. | `tests/test_check_integration_safety.py`; `tests/test_run_observatory.py` verifies dashboard safety record feeds first-review readiness; `tests/test_dashboard_backend_cli.py` records safety state through the backend CLI. | Test for selected target disappearing before record write and structured failure display in native UI. |
| Review export and trust review | Produces durable local HTML/Markdown review artifacts and gives the native app an evidence-first "should I trust it?" surface. | `app.py`: `review_bundle_command`, `export_review_bundle`, `_review_bundle_worker`; `run_observatory.py`: `write_review_bundle`, `render_review_markdown`, `persist_recommendation_history`. Backend CLI: `review.load`, `review.export_bundle`, `review.mark_reviewed`. Native UI: `ReviewPage.tsx`. | Writes review artifacts under the selected review directory, target `target/action_plan_history.json`, and optional `.agentic/reviewed.json`; reads task state, git status/commits, validation, integration safety, generated files, and review Markdown. | Implemented: `review.load --target`, `review.export_bundle --target --review-dir`, `review.mark_reviewed --target [--note]`. | `tests/test_run_observatory.py` covers `--review-dir`, Markdown export, and recommendation history; `tests/test_check_integration_safety.py` covers command shape; `tests/test_dashboard_backend_cli.py` covers CLI JSON/artifacts plus review load and reviewed marker writes. | UI component tests for Review action states and tests for unwritable output directory/action-history merge edge cases. |
| Observatory launch and live server | Preserves the old dark browser page headed "Diffmogger Autonomous Build Log" for demos and reviews. | `app.py`: `launch_observatory`; `run_observatory.py`: `run_server`, `ObservatoryHandler`, `render_html`, `REPLAY_HTML_TEMPLATE`. Backend CLI generates static HTML via `observatory.generate_html` and `observatory.load_html`; native `ObservatoryPage.tsx` renders React components from `observatory.snapshot` and keeps browser/export actions. | Reads target state; writes generated HTML under the selected review directory; serves `/` and `/state.json` only in the old live server; review export can also write Markdown and `target/action_plan_history.json`. | Implemented: `observatory.generate_html --target <path> --review-dir <path>`, `observatory.load_html --target <path> --review-dir <path>`, and `observatory.snapshot --target <path>`. Future live command: `observatory serve --target ... --json`. | `tests/test_run_observatory.py` covers snapshot/render; `check_required_files.py` checks observatory markers and source/template identity; `tests/test_dashboard_backend_cli.py` covers HTML generation and native snapshot return; native Rust validates browser-open paths are generated Observatory HTML; `src/observatoryModel.test.ts` and `src/ObservatoryPage.test.tsx` cover native state/component cases. | HTTP endpoint smoke test, no-browser `--open` behavior test, and visual/DOM regression test comparing the native dark Observatory against the old HTML sections. |
| Observatory snapshot, scorecard, and self-review | Summarizes task state, validation, safety, human bridge, signals, queue, conveyor, baseline verification, action plan, follow-through, and next-run worker strategy. | `run_observatory.py`: `build_snapshot`, `parse_task_state`, `queue_snapshot`, `signals_snapshot`, `conveyor_health`, `scorecard_snapshot`, `self_review_snapshot`, `worker_strategy_snapshot`, `render_review_markdown`. Backend CLI: `project.load_snapshot`, `run.load`, and native-specific `observatory.snapshot`. | Reads `docs/CODEX_AUTOMATION_TASKS.md`, `docs/MULTI_ROLE_PROGRESS.md`, human bridge docs, `target/automation_queue/`, `target/automation_signals.json`, `target/automation_conveyor_state.json`, logs, git history; may write `target/action_plan_history.json` during exports. | Implemented: `project.load_snapshot --target <path>`, `run.load --target <path>`, and `observatory.snapshot --target <path>`. Future split: `observatory snapshot --target --json`. | Broad coverage in `tests/test_run_observatory.py`; CLI empty/scaffolded target tests in `tests/test_dashboard_backend_cli.py`; `src/observatoryModel.test.ts` and `src/ObservatoryPage.test.tsx` cover empty, active builder, queued patch, blocked user, and critical stop native mappings. | Formal JSON schema/golden contract for `observatory.snapshot` and visual regression for key first-viewport sections. |
| Worker Strategy Controls | Lets users act on the Observatory's next-run worker recommendation from the dashboard. | `app.py`: `dashboard_worker_strategy`, `worker_strategy_summary`, `read_only_worker_command`, `write_worker_command`, `integration_only_command`, `latest_worker_result`, `run_read_only_worker_report`, `run_write_worker_lane`, `run_integration_only_lane`, `_summarize_worker_run`. Backend CLI: `worker.run_read_only`, `worker.run_write`, `worker.run_integrator`. Native UI: Run worker strategy card. | Reads target state and `target/agent_runs/`; writes worker reports and summaries through target helper scripts; records latest worker run ID in `.agentic/dashboard_state.json`. | Implemented: `worker.run_read_only --target`, `worker.run_write --target --ownership`, `worker.run_integrator --target`, plus `run.load` worker-control snapshot. Future alias: `workers strategy|run-read-only|run-write|run-integrator|summarize --target --json-events`. | `tests/test_check_integration_safety.py` covers command builders and latest summary; `tests/test_run_observatory.py` covers worker strategy recommendations; `tests/test_summarize_worker_outputs.py`; `src/runModel.test.ts` covers READ_ONLY_REPORTS human translation and button gating. | Backend tests for recommendation-gated launch errors, missing helper scripts, failed worker run summary behavior, and write-worker ownership UX. |
| Human bridge and file-only messaging | Gives the human a dashboard path to read automation requests, reply, leave next-run notes, and inspect handled history when notifier delivery is disabled or unavailable. | `app.py`: `HUMAN_DOC_CHOICES`, `INTENT_CHOICES`, `append_manual_inbox_entry`, `next_inbox_id`, `add_inbox_reply`, `check_notifier_health`; `scaffold_project_docs.py`: `bridge_values`. Backend CLI: `inbox.load`, `inbox.send_note`, `inbox.reply_request`. Native UI: `InboxPage.tsx`. | Writes `docs/HUMAN_INBOX.md`; reads/views `docs/HUMAN_REQUESTS.md`, `docs/HUMAN_INBOX.md`, `docs/HUMAN_OUTBOX.md`, `docs/HUMAN_RESPONSES_ARCHIVE.md`; optional notifier health read. | Implemented: `inbox.load --target`, `inbox.send_note --target --body --intent [--related]`, `inbox.reply_request --target --request-id --body --intent`. Future aliases: `human inbox append --target --request-id --intent --body --json`; `human docs read --target --doc-key`; `human notifier-health --json`. | Observatory human counts in `tests/test_run_observatory.py`; generated bridge mode smokes in `scripts/validate_starter_kit.sh`; notifier service tests; `tests/test_dashboard_backend_cli.py` covers human bridge parsing plus note/reply writes through the old dashboard helper. | UI component tests for Inbox tab rendering and mocked send failures; notifier health command tests remain future. |
| Markdown file monitor/editor | Lets users inspect and carefully edit the Markdown-first operating state without hunting through files. Raw editing is preserved but moved out of the primary workflow. | `app.py`: `DOC_CHOICES`, `load_selected_doc`, `_load_markdown_file`, `_render_markdown`, `_configure_markdown_tags`, `refresh_monitor`; docs list monitored files. Backend CLI: `advanced.list_files`, `advanced.load_file`, `advanced.save_file`, `advanced.validate_file`; native `AdvancedPage.tsx`. | Reads allowlisted docs such as `docs/CODEX_AUTOMATION_TASKS.md`, `docs/PROJECT_CONTEXT.md`, human bridge docs, `docs/DAILY_AUTOMATION_REVIEW.md`, `.agentic/automation_prompt.md`; writes only editable allowlisted files through backend path validation. | Implemented: `advanced.list_files --target <path>`, `advanced.load_file --target <path> --file-key <key>`, `advanced.save_file --target --file-key --content`, `advanced.validate_file --target --file-key`. Future alias: `markdown read|write|validate --target --doc-key --json`. | `tests/test_dashboard_backend_cli.py` covers allowlisted load, save, validation, and read-only refusal; validation markers cover native Advanced UI. | UI interaction tests for dirty/save/discard state and missing-file edge cases. |
| Advanced diagnostics, settings, and debug bundle | Keeps power-user readiness checks, launchd/notifier details, app preferences, and support bundles available without making them the main experience. | `app.py`: prerequisite and schedule helpers; backend CLI `diagnostics.environment`, `diagnostics.run_checks`, `advanced.export_debug_bundle`; native Rust settings/open/reveal commands; native `AdvancedPage.tsx`. | Reads diagnostics inputs and managed state; writes app-local native settings; debug bundle writes only to chosen output directory and includes redacted diagnostics/state/log metadata. | Implemented: `diagnostics.environment`, `diagnostics.run_checks --target`, `advanced.export_debug_bundle --target --output-dir`, native `get_advanced_settings`, `update_advanced_settings`, `select_settings_directory`, `open_managed_file`, `reveal_managed_file`. | `tests/test_dashboard_backend_cli.py` covers setup doctor output, debug bundle export, and redaction; `scripts/validate_starter_kit.sh` checks UI/backend command markers. | Mocked native command tests for app-local settings persistence, OS open/reveal failure cases, and debug bundle contents from scaffolded active-run targets. |
| Monitor status summary | Shows automation status, horizon, pending human counts, outbox count, worker report counts, and worker strategy in one line. | `app.py`: `refresh_monitor`, `_count_marker`, `dashboard_worker_strategy`, `latest_worker_result`. Backend CLI derives state through Observatory with `project.load_snapshot` and `run.load`. | Reads `docs/CODEX_AUTOMATION_TASKS.md`, `docs/HUMAN_REQUESTS.md`, `docs/HUMAN_INBOX.md`, `docs/HUMAN_OUTBOX.md`, `target/agent_runs/`. | Implemented: `project.load_snapshot --target <path>` and `run.load --target <path>`. Future alias: `monitor summary --target --json`. | Human counts and worker strategy are indirectly covered by `tests/test_run_observatory.py`; CLI tests cover empty/scaffolded Home-like snapshots. | Direct tests for regex extraction, missing task file, malformed task fields, and worker count consistency. |
| Multi-role and conveyor intake settings | Preserves advanced local-only role automation settings across scaffold, schedule, and dashboard state. | `app.py`: `multi_role_automations_var`, `automation_role_profile_var`, `automation_checkpoint_commits_var`, `multi_role_base_cadence_var`, `schedule_strategy_from_value`, `_target_multi_role_enabled`, `_target_schedule_strategy`; `scaffold_project_docs.py`: `multi_role_values`. | Writes `.agentic/project_intake.json`, `.agentic/dashboard_state.json`, `.agentic/roles/*`, `docs/MULTI_ROLE_PROGRESS.md`, role/conveyor scripts. | Covered by `intake write`, `automation readiness`, and `schedule install`; optional `multi-role config --target --json`. | `tests/test_check_required_files.py`, `tests/test_run_role_automation.py`, `tests/test_run_conveyor_automation.py`, `scripts/validate_starter_kit.sh`. | Dashboard/native state round-trip tests and validation of schedule strategy transitions after reopening a target. |
| Context7 and Playwright MCP options | Generates project-scoped optional MCP config and advisory readiness without mutating global Codex config. | `app.py`: `context7_mcp_var`, `playwright_mcp_var`, `optional_mcp_servers`, `optional_mcp_servers_from_value`, `codex_mcp_detail`, `managed_browser_path`; `scaffold_project_docs.py`: `mcp_values`; `templates/.codex/config.toml`, `templates/docs/MCP_INTEGRATIONS.md`, `templates/scripts/run_playwright_mcp.sh`. | Writes optional `.codex/config.toml`, `docs/MCP_INTEGRATIONS.md`, `scripts/run_playwright_mcp.sh`, `docs/backlog/README.md`; reads `CONTEXT7_API_KEY`, Codex MCP list, browser cache. | `mcp plan --target --servers context7,playwright --json`; `mcp doctor --target --servers ... --json`. | `tests/test_check_required_files.py` optional MCP scaffold test; `tests/test_run_role_automation.py` role-scoped MCP overrides; validation script smokes. | Prerequisite matrix tests and explicit test that backend does not call `codex mcp add/login` or modify user/global config. |
| Environment access policy | Lets users choose whether automation may read `.env*` files directly or only through project commands. | `app.py`: `env_access_policy_from_value`, `collect_intake`, `_apply_intake_to_form`; `scaffold_project_docs.py`: `env_access_policy`, `env_access_values`. | Writes intake and generated prompt/guardrail docs; no secret values copied. | `intake validate/write`; optional `env-policy explain --policy --json`. | Schema marker checks and validation script markers for env loader/denylist. | Round-trip tests and generated prompt assertions for both policies. |
| Ticket-campaign controls | Supports bounded ticket campaigns with readiness-only bootstrap, dependency-aware ticket selection, and optional completion notification. | `app.py`: `ticket_campaign_enabled_var`, `ticket_run_file_var`, `ticket_completion_notify_var`, `_target_ticket_campaign_enabled`, `_target_ticket_completion_notify_enabled`; `scaffold_project_docs.py`: `ticket_run_values`; `scripts/ticket_run.py`. | Writes `.agentic/project_intake.json`, optional `docs/TICKET_RUN.md`; runtime writes `target/ticket_run_completion.json`, `target/ticket_run_reports/`, human outbox fallback. | `ticket status|next|should-halt|finalize --target --json`; intake handles enablement. | `tests/test_ticket_run.py`; `tests/test_check_required_files.py`; validation script ticket-campaign smokes. | Dashboard/native round-trip tests for ticket fields and prerequisite tests for desktop notification advisory. |
| Automation signals | Optional recurring local nudges feed dashboards, Observatory, and role runs without overriding task state. | `app.py`: `automation_signals_enabled_var`; `scaffold_project_docs.py`: `automation_signal_values`; `scripts/update_automation_signals.py`; `run_observatory.py`: `signals_snapshot`. | Writes optional `docs/AUTOMATION_SIGNALS.md`; runtime writes `target/automation_signals.json`. | `signals refresh|complete|status --target --json`. | Validation script signal smokes; `tests/test_run_observatory.py` signal snapshot coverage. | Native/dashboard state round-trip tests and command tests for malformed signal definitions and merge-state behavior. |

## Minimum Backend Command Surface

The native UI should be a thin client over a small command API. These commands are the minimum safe
surface; they can initially wrap the existing Python functions and scripts, then be refactored later:

1. `doctor prerequisites --target --bridge-mode --optional-mcp --schedule-strategy --json`
2. `intake get|validate|write --target --json`
3. `context import --target --file ... --json` and `context index --target --records-json`
4. `project scaffold --target --intake-json --force --json-events`
5. `bootstrap run --target --intake-json --context-file ... --force --json-events`
6. `automation readiness --target --json` (currently surfaced through `run.load.controls`)
7. `run once --target --json-events` (currently `run.once`)
8. `schedule status|install|pause|remove --target --strategy --cadence-minutes --json` (currently `run.load`, `schedule.start`, `schedule.pause`, `schedule.remove`)
9. `monitor summary --target --json` and `markdown read --target --doc-key --json`
10. `human inbox append --target --request-id --intent --body --json`, `human inbox load --target --json`, and `human notifier-health --json` (currently `inbox.load`, `inbox.send_note`, and `inbox.reply_request`)
11. `safety check --selected-target --record --json-events` (currently `safety.run_check`)
12. `review load|export|mark-reviewed --target --review-dir --json-events` (currently `review.load`, `review.export_bundle`, and `review.mark_reviewed`)
13. `observatory snapshot|serve|render-html|load-html|render-review --target --json` (currently `observatory.snapshot`, `observatory.generate_html`, and `observatory.load_html`)
14. `workers strategy|run-read-only|run-write|run-integrator|summarize --target --json-events` (currently `run.load` plus `worker.run_*`)
15. `advanced files|read|write|validate --target --file-key --json` and `debug-bundle export --target --output-dir --json` (currently `advanced.list_files`, `advanced.load_file`, `advanced.save_file`, `advanced.validate_file`, `advanced.export_debug_bundle`)
16. `signals status|refresh|complete --target --json`
17. `ticket status|next|should-halt|finalize --target --json`

All mutating commands should return machine-readable results, include paths touched, avoid printing
secret values, and keep generated target repos decoupled from the Diffmogger source checkout at
runtime.

## Safe Backend Entry Points

These existing functions and scripts are safe starting points for the native backend because they are
already non-UI or nearly non-UI:

- `scripts/run_dashboard.py`: dotenv parsing/loading only.
- `app.py` pure helpers: `check_prerequisites`, `write_launchd_plist`, `write_role_launchd_plist`, `write_conveyor_launchd_plist`, `target_has_initial_commit`, `copy_context_files`, `render_project_context`, `upsert_context_imports`, `append_manual_inbox_entry`, `integration_safety_command`, `write_integration_safety_record`, `review_bundle_command`, worker command builders.
- `scripts/scaffold_project_docs.py`: `parse_intake`, `placeholders`, `scaffold`.
- `scripts/check_required_files.py`: generated target validation.
- `scripts/check_integration_safety.py`: safety verifier.
- `scripts/run_observatory.py`: `build_snapshot`, `render_html`, `render_review_markdown`, `write_review_bundle`, `run_server`.
- Target-local helpers scaffolded into projects: `.diffmogger/scripts/run_codex_automation.sh`, `.diffmogger/scripts/run_conveyor_automation.sh`, `.diffmogger/scripts/run_role_automation.sh`, `.diffmogger/scripts/spawn_worker_agent.sh`, `.diffmogger/scripts/summarize_worker_outputs.py`, `.diffmogger/scripts/ticket_run.py`, `.diffmogger/scripts/update_automation_signals.py`, `.diffmogger/scripts/list_deferred_patches.py`.

## UI-Only Behavior To Move Behind Commands

The Tkinter class currently owns several operations that a Tauri UI should not reimplement in
JavaScript or call through widget methods:

- Intake collection and form-state normalization: move `collect_intake`, `_apply_intake_to_form`, and `_apply_dashboard_state` behind `intake` and `dashboard-state` commands.
- Combined scaffold/bootstrap orchestration: move `_scaffold_bootstrap_worker` behind `project scaffold` and `bootstrap run`.
- Schedule management: move `start_scheduled_automation`, `pause_scheduled_automation`, `remove_scheduled_automation`, `_set_run_automation_state`, `_schedule_prerequisites`, and `_launchctl` behind `schedule` commands.
- Monitor summary: move `refresh_monitor` behind `monitor summary`.
- Markdown document loading: move `load_selected_doc` and `load_selected_human_doc` behind allowlisted `markdown read` and `human docs read`.
- Human inbox append: move `add_inbox_reply` behind `human inbox append`.
- Safety check, review export, Observatory launch, and worker controls: expose command/event streams instead of starting threads from UI callbacks.
- Bounded log, subprocess lifecycle, and cancellation: centralize process-group handling behind backend run IDs.

## Coverage Priorities

1. Preserve the old Observatory snapshot, native dark React experience, and dark HTML export with golden JSON and DOM/visual checks.
2. Add backend command tests before wiring Tauri UI controls.
3. Cover all state-writing commands with touched-path assertions.
4. Add mocked launchd tests so scheduling behavior is testable off macOS CI.
5. Add dashboard/native state round-trip tests for every project intake field.
6. Add explicit tests that optional MCP setup remains project-scoped and advisory.
7. Add file-only human messaging tests for ID sequencing and Markdown entry shape.
