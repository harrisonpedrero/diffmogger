# Fresh Project Setup

Use this checklist to start a new target folder from Diffmogger without keeping a runtime dependency on the Diffmogger repo. The same flow can retrofit an existing repo when project mode is set to `existing_project`.

## 1. Launch The Dashboard Or Create An Intake

Recommended path:

```bash
cd /path/to/Diffmogger
bash scripts/build_native_dashboard_app.sh
open Diffmogger.app
```

The native dashboard opens a local window and calls the Diffmogger backend command layer. Before automation starts, review the prerequisite list:

- Python 3.10+
- Codex CLI installed and signed in
- `bash`
- `git`
- writable target parent directory
- Codex home availability for nested workers
- macOS Full Disk Access advisory for targets under `~/Documents`
- optional local notifier health when using `local_notifier`
- optional macOS desktop notification command when ticket completion notifications are enabled

Fill in the wizard, choose the target directory, optionally add context files such as PDFs or research notes, then click **Scaffold**. Choose fresh-project mode for a new target directory. Choose existing-project mode when the target already has project files and describe the first integrated change in the intake. The dashboard writes `.diffmogger/agentic/project_intake.json`, copies context files into `.diffmogger/context/`, creates `.diffmogger/state/PROJECT_CONTEXT.md`, scaffolds required files, validates them, and ensures the target has a local git repo with an initial `chore: initial commit` when `HEAD` does not exist. Then open **Run** and click **Start** to launch the actual automation.

When integrating into an existing repo, Diffmogger preserves project-owned files by keeping Diffmogger state under `.diffmogger/`. If root `AGENTS.md` exists, Diffmogger adds or updates a managed block that points Codex at the sidecar prompt. Keep repo-owned instructions outside that managed block.

CLI path:

Write a project intake file in the target repo or pass one from anywhere:

```bash
python3 /path/to/Diffmogger/scripts/scaffold_project_docs.py \
  --intake project_intake.md \
  --target /path/to/target-project
```

Use `human_bridge_mode: file_only` when you want manual Markdown communication, `local_notifier` for native desktop notifications, or `discord_notifier` for Discord progress/messages plus optional desktop notifications.

Use `project_mode: existing_project` when scaffolding into a repo that already has app code, docs, or project-specific instructions.

Write-capable worker agents are always available and optional per run. CLI intakes can tune the cap and guidance with:

```json
{
  "max_write_worker_count": 10,
  "write_worker_guidance": "Use the most parallelism the task can safely absorb while keeping ownership reviewable."
}
```

The scaffold caps `max_write_worker_count` at 10 and defaults it to 3. `write_worker_agents_allowed` is a deprecated compatibility field and no longer disables write workers when false.

DAG scheduler automation is the standard mode. CLI intakes can use:

```json
{
  "automation_role_profile": "planner_builder_hardener_integrator",
  "parallel_execution_mode": "aggressive",
  "symbol_graph_languages": ["python", "typescript", "javascript"],
  "parallel_write_min_confidence": 0.75,
  "parallel_write_direct_confidence": 0.75,
  "max_parallel_write_workers": 3,
  "max_parallel_scope_workers": 2,
  "automation_checkpoint_commits": true,
  "multi_role_allow_remotes": false
}
```

Diffmogger always scaffolds the `planner_builder_hardener_integrator` role profile on top of the execution DAG scheduler. Legacy intakes may still include `multi_role_automations_allowed`; new intakes should use `campaign_mode` for campaign scope and the `parallel_*`, `symbol_graph_languages`, and `max_parallel_*` fields for scheduler policy.

`parallel_execution_mode` defaults to `aggressive` for automatic ready-wave planning. `symbol_graph_languages` controls symbol extraction for Python and TypeScript/JavaScript while preserving file-level graph fallback. `parallel_write_min_confidence` is the write-wave threshold, `parallel_write_direct_confidence` is the confidence expected from direct path or exact-symbol ownership signals, `max_parallel_write_workers` caps same-wave write launches, and `max_parallel_scope_workers` caps scoping/read-only fanout. Scoping/read-only candidates use a lower default confidence threshold of `0.55`; when direct write confidence is missing, bounded read-only scope workers gather ownership evidence, likely paths, likely symbols, validation hints, and risk notes before serial builder fallback. Structured scope evidence is normalized into SQLite before it can raise later write confidence; stale, ambiguous, unresolved, unsafe, or low-confidence records stay advisory.

Scaffold creates a local git repo and initial `chore: initial commit` automatically when the selected target does not already have `HEAD`. Continuous automation still checks this before the runner starts.

For bounded ticket work, choose **Bounded campaign** in the dashboard run config or set these intake fields:

```json
{
  "campaign_mode": "bounded",
  "ticket_run_seed_tickets": [],
  "ticket_completion_notify": true
}
```

The native dashboard provides a **Ticket Queue** panel before scaffold when bounded campaign is selected. Low-cortisol generation creates a full-scope seed queue by splitting the described project into reviewable local patches with no fixed ticket-count ceiling. Use the queue panel to add/edit/delete seed tickets, paste Markdown/CSV/JSON imports, or ask Codex to draft review-only follow-up candidates from current project state. CLI intakes can also include `ticket_run_seed_tickets`; scaffold writes those into the target-local SQLite ticket queue.

After scaffold, the Run page has the same Ticket Queue controls: inspect, add, edit, delete, preview/apply imports transactionally, draft from intake, and accept selected draft candidates. Runtime decisions, execution DAG progress, repo capability manifest, events, blockers, and next actions remain canonical in `.diffmogger/runtime/orchestration.sqlite3`. Scaffold initializes ticket readiness, and Start launches actual automation directly. Normal campaign runs use `python3 .diffmogger/scripts/ticket_run.py . next --json` for dependency-aware ticket context; the DAG scheduler may launch compatible ready nodes across tickets when dependencies, confidence, and ownership scopes allow. Ongoing campaigns draft/enqueue safe follow-up tickets from typed runtime context when no dependency-ready tickets remain. Completion notifications use the laptop's native desktop notification system when enabled; failures are recorded in typed human-message state.

For CLI validation of a ticket-campaign target, add `--ticket-campaign-enabled` to `scripts/check_required_files.py`.

Diffmogger enables all supported optional MCP servers by default for new scaffolded targets. Set `optional_mcp_servers` only when you want to be explicit:

```json
{
  "optional_mcp_servers": ["context7", "playwright"]
}
```

Use an explicit empty array to opt out:

```json
{
  "optional_mcp_servers": []
}
```

Diffmogger generates project-scoped `.diffmogger/agentic/codex_config.toml` and `.diffmogger/state/MCP_INTEGRATIONS.md`, but never runs `codex mcp add`, `codex mcp login`, or edits user/global Codex config. Context7 uses stdio `npx -y @upstash/context7-mcp` by default and inherits `CONTEXT7_API_KEY` when that environment variable is present; dashboard-launched backend processes also load optional runtime variables from the Diffmogger starter repo's root `.env`. The key itself is never stored in generated files. Remote OAuth setup is manual/optional. Planner/Builder wrappers mount Context7. Playwright MCP mounts for Hardener/Integrator validation lanes, and for Planner/Builder only when the target or selected ticket is frontend, browser, UI, or demo-path scoped. Context7 auth failures, startup failures, timeouts, empty results, and tool errors are fallback-only events, not blockers. Playwright UI failure screenshots belong under `.diffmogger/state/backlog/ui_artifacts/<run_id>/<issue-slug>.png`.

## 2. Validate The Scaffold

```bash
python3 /path/to/Diffmogger/scripts/check_required_files.py \
  --human-bridge-mode file_only \
  /path/to/target-project
```

Generated target repos include local runtime helpers:

```text
.diffmogger/scripts/acquire_codex_lock.sh
.diffmogger/scripts/release_codex_lock.sh
.diffmogger/scripts/run_conveyor_automation.py
.diffmogger/scripts/run_conveyor_automation.sh
.diffmogger/scripts/run_role_automation.sh
.diffmogger/scripts/integrate_role_outputs.py
.diffmogger/scripts/list_deferred_patches.py
.diffmogger/scripts/run_observatory.py
.diffmogger/scripts/ticket_run.py
.diffmogger/scripts/repair_environment.py
.diffmogger/scripts/spawn_worker_agent.sh
.diffmogger/scripts/summarize_worker_outputs.py
.diffmogger/scripts/compact_agent_state.py
```

Generated targets also include the DAG scheduler role prompts and progress projection:

```text
.diffmogger/agentic/verification_commands.txt
.diffmogger/agentic/smoke_commands.txt
```

For new sidecar targets, those prompt/config files are generated under `.diffmogger/agentic/`; legacy targets without `.diffmogger/manifest.json` may still use `.agentic/`.

Use `python3 .diffmogger/scripts/list_deferred_patches.py . --markdown` for grouped local deferred queue triage. Add `--decision-template` when the integrator needs a per-manifest worksheet for archive, replace-from-current-HEAD, repair-and-retry, retry-as-is, or keep-deferred decisions.

`Preferred commands` in docs are not an unconditional multi-role gate. Full-suite gates come from `.diffmogger/agentic/verification_commands.txt` and are used for hardener/finalization or explicit full-suite manifests. Builder/planner patches should carry focused checks or match `.diffmogger/agentic/smoke_commands.txt` selectors.

The integrator records clean-HEAD full-suite baseline verification in `.diffmogger/runtime/baseline_verification.json` for new targets. If that baseline fails before a patch is applied, normal hardener/finalization patches are deferred as `baseline_verification_blocker` until a `Verification scope: baseline_repair` patch or local environment repair clears the baseline. Missing project-local services, such as an unavailable local PostgreSQL test database in a repo with Prisma/Postgres test configuration, are routed as `repairable_local_service` baseline repair instead of a terminal human blocker. Builder/planner patches with passing focused checks can still integrate when unrelated to the baseline failure.

Target-project automation runs should use those local scripts, not scripts from the Diffmogger starter repo.

## 3. First Run

The dashboard handles this from **Run** when the user clicks **Start**. For debugging, start the target-local automation directly:

```bash
python3 .diffmogger/scripts/run_conveyor_automation.py .
```

Review the first run closely. Confirm the app or workflow is runnable and that `.diffmogger/runtime/canonical_state_brief.md` shows a clear next sprint; `.diffmogger/state/CODEX_AUTOMATION_TASKS.md` should match it as a generated handoff projection.

## 4. Start Continuous Automation

Recommended path: use the dashboard's **Start** button. If first-run preparation is still pending, Start runs that guarded phase first, stops on preparation failure, and only then launches one detached target-scoped runner for:

```bash
bash .diffmogger/scripts/run_conveyor_automation.sh
```

The DAG scheduler runner keeps running locally, chooses the next runnable node or compatible wave from canonical SQLite execution DAG state, and records events, DAG nodes/edges, repo capability manifests, checkpoints, blockers, validations, and next actions in `.diffmogger/runtime/orchestration.sqlite3`. `.diffmogger/runtime/canonical_state_brief.md` is regenerated before role Codex runs; `.diffmogger/runtime/automation_conveyor_state.json` and `.diffmogger/runtime/automation_runner.json` are regenerated as compatibility projections. The scheduler prioritizes queued integration, baseline verification preflight or repair routing when needed, fast-follow replanning after planner deferral changes, review/hardening, validation, targeted repairs, and compatible build waves. Role Codex subprocesses run under `.diffmogger/scripts/run_process_watchdog.py`; the scheduler also clears orphaned or over-time `active_role_run` state when restarted.

The target wrapper can still be run manually for debugging:

```bash
bash .diffmogger/scripts/run_conveyor_automation.sh --dry-run
bash .diffmogger/scripts/run_conveyor_automation.sh --once
python3 .diffmogger/scripts/run_observatory.py --open
```

The observatory is a local browser page for demos and live monitoring. It reads
canonical state from `.diffmogger/runtime/orchestration.sqlite3` plus generated projections and runtime artifacts such as `.diffmogger/runtime/automation_queue/`, automation logs, and progress docs,
then shows runner state, the latest recorded integration-safety check result,
accepted/deferred patch scorecard metrics, deferred-patch triage reasons with local next
actions, an explicit next-lane action plan, action-plan
follow-through status from recent DAG scheduler or queue outcomes, bounded recommendation-history
records, a next-run worker strategy recommendation, the active role, upcoming DAG lanes,
queued/deferred patches, no-progress circuit breaker state, recent outcomes, and timeline
events without requiring external services.

For a first-run review bundle from the same local state, run:

```bash
python3 .diffmogger/scripts/run_observatory.py --target . --review-dir /tmp/Diffmogger-review
```

This writes `/tmp/Diffmogger-review/Diffmogger-observatory.html` and
`/tmp/Diffmogger-review/Diffmogger-self-review.md`. Markdown review exports update
`.diffmogger/runtime/action_plan_history.json` so repeated recommendations and follow-through outcomes
remain visible across local DAG scheduler cycles.

### First Review Checklist

After the first automation run, use one local review path:

1. From the Diffmogger starter-kit source, run `bash scripts/validate_starter_kit.sh`.
2. Open the native dashboard, reopen the target, and click **Run Safety Check**.
3. Click **Export Review Bundle** or, from the target repo, run `python3 .diffmogger/scripts/run_observatory.py --target . --review-dir /tmp/Diffmogger-review`.
4. Open `/tmp/Diffmogger-review/Diffmogger-observatory.html` and inspect `/tmp/Diffmogger-review/Diffmogger-self-review.md`.
5. Confirm the review shows first-review readiness, safety status, validation state, active role or queue, known issues, the next sprint recommendation, and the next-run worker strategy.

The dashboard writes the safety-check result to the target-local
`.diffmogger/runtime/integration_safety_check.json` file before the export reads it. That file is runtime state,
not source.

The generated wrapper runs the parent automation with:

```bash
--add-dir "$HOME/.codex"
```

Nested Codex startup may touch `state_5.sqlite`, `shell_snapshots`, and `sessions`, so the sessions-only allowance is too narrow. Workers still use `codex exec --ephemeral`, but the generated helper disables the child worker's inner macOS sandbox so the parent automation run remains the single outer sandbox boundary.

Existing Diffmogger LaunchAgents are legacy. The current dashboard does not create or manage them; remove old `com.diffmogger.automation.*` plist files manually from `~/Library/LaunchAgents/` only after confirming they are not needed.

For a manual multi-role run, use:

```bash
bash .diffmogger/scripts/run_role_automation.sh --role planner
bash .diffmogger/scripts/run_role_automation.sh --role builder
bash .diffmogger/scripts/run_role_automation.sh --role hardener
bash .diffmogger/scripts/run_role_automation.sh --role integrator
```

Write logs under:

```text
.diffmogger/runtime/automation_logs/stdout.log
.diffmogger/runtime/automation_logs/stderr.log
.diffmogger/runtime/automation_logs/conveyor.stdout.log
.diffmogger/runtime/automation_logs/conveyor.stderr.log
.diffmogger/runtime/automation_logs/<role>.stdout.log
.diffmogger/runtime/automation_logs/<role>.stderr.log
```

If the repo lives under `~/Documents`, macOS privacy controls may block local automation jobs until `/bin/bash` and the Node executable used by Codex have Full Disk Access. A repo under `~/Developer` usually avoids that friction.

## 5. Human Bridge

In `file_only` mode, use the dashboard Inbox to review automation requests and send replies. Let the next automation run mark handled messages resolved only after the requested action is complete or intentionally deferred.

In `local_notifier` mode, the separate notifier service owns native desktop notification delivery. In `discord_notifier` mode, it owns Discord credentials and posts progress/messages to configured channels; dashboard/SQLite remains the target-side message state.

## 6. Worker Agents

Nested Codex CLI workers should use ephemeral sessions:

```bash
codex exec --disable plugins \
  --ephemeral \
  --dangerously-bypass-approvals-and-sandbox \
  -C . \
  "<read-only worker prompt>"
```

The parent automation wrapper must also allow `$HOME/.codex` with `--add-dir`. `--ephemeral` reduces child session persistence, but the nested CLI may still touch Codex state and shell snapshot files during startup.

Read-only worker reports are the default for exploration and review. Generated prompts also allow bounded write mode as acceleration for work that can split into reviewable lanes:

```bash
bash .diffmogger/scripts/spawn_worker_agent.sh \
  --mode write \
  --target . \
  --run-id "$CODEX_RUN_ID" \
  --role feature_a \
  --ownership "src/feature-a/** and tests/feature-a/** only" \
  --prompt "Implement the assigned slice and report changed files/checks."
```

The main automation agent still owns planning, reviewable ownership, necessary contract definitions, integration, conflict resolution, verification, and final task-state updates. Integration-only runs with no workers are valid when faster or safer.
