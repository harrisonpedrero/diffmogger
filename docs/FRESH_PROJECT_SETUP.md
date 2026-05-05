# Fresh Project Setup

Use this checklist to start a new target repo from Diffmogger without keeping a runtime dependency on the Diffmogger repo. The same flow can retrofit an existing repo when project mode is set to `existing_project`.

## 1. Launch The Dashboard Or Create An Intake

Recommended path:

```bash
python3 /path/to/Diffmogger/scripts/run_dashboard.py
```

The standalone dashboard opens a native local window. Before automation starts, review the prerequisite list:

- Python 3.10+
- Tkinter GUI support
- Codex CLI installed and signed in
- `bash`
- `git`
- writable target parent directory
- Codex home availability for nested workers
- macOS Full Disk Access advisory for targets under `~/Documents`
- optional local notifier health when using `local_notifier`
- optional macOS desktop notification command when ticket completion notifications are enabled

Fill in the wizard, choose the target directory, optionally add context files such as PDFs or research notes, then click **Scaffold & Bootstrap**. Choose fresh-project mode for a new target directory. Choose existing-project mode when the target is an existing repo and describe the first integrated change in the intake. The dashboard writes `.agentic/project_intake.json`, copies context files into `docs/context/`, creates `docs/PROJECT_CONTEXT.md`, scaffolds required files, validates them, and starts the initial Codex bootstrap run.

When integrating into an existing repo, Diffmogger preserves existing `AGENTS.md` and `docs/DEVELOPMENT.md` content by adding or updating a managed Diffmogger section. Keep repo-owned instructions outside the managed section.

CLI path:

Write a project intake file in the target repo or pass one from anywhere:

```bash
python3 /path/to/Diffmogger/scripts/scaffold_project_docs.py \
  --intake project_intake.md \
  --target /path/to/target-project
```

Use `human_bridge_mode: file_only` when you want manual Markdown communication, `local_notifier` for native desktop notifications, or `discord_notifier` for Discord progress/messages plus optional desktop notifications.

Use `project_mode: existing_project` when scaffolding into a repo that already has app code, docs, or project-specific instructions.

Write-capable worker agents are disabled unless the intake explicitly enables them. CLI intakes can use:

```json
{
  "write_worker_agents_allowed": true,
  "max_write_worker_count": 10,
  "write_worker_guidance": "Use the most parallelism the task can safely absorb while keeping ownership reviewable."
}
```

The scaffold caps `max_write_worker_count` at 10. Read-only worker reports remain available separately through `worker_agents_allowed`.

Multi-role automation is also disabled unless explicitly enabled. CLI intakes can use:

```json
{
  "multi_role_automations_allowed": true,
  "automation_role_profile": "planner_builder_hardener_integrator",
  "automation_checkpoint_commits": true,
  "multi_role_base_cadence_minutes": 30,
  "automation_schedule_strategy": "continuous_conveyor",
  "multi_role_allow_remotes": false,
  "automation_signals_enabled": true
}
```

Multi-role and continuous conveyor scheduling require the target to be an initialized git repo with an initial commit before scheduling starts.

For bounded ticket work, enable **Ticket Campaign** in the dashboard run config or set these intake fields:

```json
{
  "automation_run_mode": "ticket_campaign",
  "ticket_run_file": "docs/TICKET_RUN.md",
  "ticket_completion_notify": true
}
```

The dashboard scaffolds `docs/TICKET_RUN.md` but does not edit tickets directly. Populate that Markdown file with ticket IDs, acceptance criteria, verification commands, evidence fields, and blockers before leaving automation unattended. Completion notifications use the laptop's native desktop notification system when enabled; failures are recorded in `docs/HUMAN_OUTBOX.md`.

For CLI validation of a ticket-campaign target, add `--ticket-campaign-enabled` to `scripts/check_required_files.py`.

## 2. Validate The Scaffold

```bash
python3 /path/to/Diffmogger/scripts/check_required_files.py \
  --human-bridge-mode file_only \
  /path/to/target-project
```

Generated target repos include local runtime helpers:

```text
scripts/acquire_codex_lock.sh
scripts/release_codex_lock.sh
scripts/run_codex_automation.sh
scripts/run_conveyor_automation.py
scripts/run_conveyor_automation.sh
scripts/run_observatory.py
scripts/ticket_run.py
scripts/repair_environment.py
scripts/update_automation_signals.py
scripts/spawn_worker_agent.sh
scripts/summarize_worker_outputs.py
scripts/compact_agent_state.py
```

When multi-role mode is enabled, generated targets also include:

```text
.agentic/verification_commands.txt
.agentic/smoke_commands.txt
scripts/run_role_automation.sh
scripts/integrate_role_outputs.py
scripts/list_deferred_patches.py
```

Use `python3 scripts/list_deferred_patches.py . --markdown` for grouped local deferred queue triage. Add `--decision-template` when the integrator needs a per-manifest worksheet for archive, replace-from-current-HEAD, repair-and-retry, retry-as-is, or keep-deferred decisions.

`Preferred commands` in docs are not an unconditional multi-role gate. Full-suite gates come from `.agentic/verification_commands.txt` and are used for hardener/finalization or explicit full-suite manifests. Builder/planner patches should carry focused checks or match `.agentic/smoke_commands.txt` selectors.

The integrator records clean-HEAD full-suite baseline verification in `target/baseline_verification.json`. If that baseline fails before a patch is applied, normal hardener/finalization patches are deferred as `baseline_verification_blocker` until a `Verification scope: baseline_repair` patch or local environment repair clears the baseline. Missing project-local services, such as an unavailable local PostgreSQL test database in a repo with Prisma/Postgres test configuration, are routed as `repairable_local_service` baseline repair instead of a terminal human blocker. Builder/planner patches with passing focused checks can still integrate when unrelated to the baseline failure.

Scheduled target-project runs should use those local scripts, not scripts from the Diffmogger starter repo.

When `automation_signals_enabled` is true, generated targets also include `docs/AUTOMATION_SIGNALS.md`. Runtime signal state is local and ignored under `target/automation_signals.json`.

## 3. Bootstrap The Product

From the target repo:

```bash
codex exec --full-auto --skip-git-repo-check "$(cat docs/INITIAL_BOOTSTRAP_PROMPT.md)"
```

Review the first run closely. Confirm the app or workflow is runnable and that `docs/CODEX_AUTOMATION_TASKS.md` has a clear next sprint.

## 4. Schedule Recurring Runs

Recommended path: use the dashboard's **Start Scheduled Automation** button after bootstrap completes. In periodic sprint mode it writes, enables, and loads one macOS LaunchAgent for the selected target project, using the **Automation Cadence Minutes** value as the launchd interval. The dashboard accepts only whole-minute cadences greater than 30. Use **Pause Scheduled Automation** to unload and disable the job, stopping future scheduled runs across login/reboot.

If multi-role mode is enabled, the dashboard writes four role-specific LaunchAgents instead:

- planner: minute `0`
- builder: minutes `10` and `40`
- hardener: minutes `20` and `50`
- integrator: minutes `25` and `55`

Pause and remove controls apply to the whole role group.

If the scheduling strategy is continuous conveyor, the dashboard writes one LaunchAgent that runs:

```bash
bash scripts/run_conveyor_automation.sh
```

The conveyor keeps running locally, chooses the next runnable lane from current state, and records state in `target/automation_conveyor_state.json`. It prioritizes queued integration first, baseline verification preflight or repair routing when needed, fast-follow replanning after a planner patch is newly deferred or a planner deferral is resolved, due planning second, builder momentum by default, and one hardener pass after integrated builder work. It falls back to `scripts/run_codex_automation.sh` when multi-role files are absent.

The target wrapper can still be run manually for debugging:

```bash
bash scripts/run_codex_automation.sh
bash scripts/run_conveyor_automation.sh --dry-run
bash scripts/run_conveyor_automation.sh --once
python3 scripts/run_observatory.py --open
```

The observatory is a local browser page for demos and live monitoring. It reads
target-local state, including `target/automation_conveyor_state.json`,
`target/automation_signals.json`, `target/automation_queue/`, automation logs, and progress docs,
then shows active signal nudges, the latest recorded integration-safety check result,
accepted/deferred patch scorecard metrics, deferred-patch triage reasons with local next
actions, an explicit next-lane action plan, action-plan
follow-through status from recent conveyor or queue outcomes, bounded recommendation-history
records, a next-run worker strategy recommendation, the active conveyor role, upcoming lanes,
queued/deferred patches, no-progress circuit breaker state, recent outcomes, and timeline
events without requiring external services.

For a first-run review bundle from the same local state, run:

```bash
python3 scripts/run_observatory.py --target . --review-dir /tmp/Diffmogger-review
```

This writes `/tmp/Diffmogger-review/Diffmogger-observatory.html` and
`/tmp/Diffmogger-review/Diffmogger-self-review.md`. Markdown review exports update
`target/action_plan_history.json` so repeated recommendations and follow-through outcomes
remain visible across local conveyor cycles.

### First Review Checklist

After the first bootstrap, use one local review path:

1. From the Diffmogger starter-kit source, run `bash scripts/validate_starter_kit.sh`.
2. Open the dashboard with `python3 /path/to/Diffmogger/scripts/run_dashboard.py`, reopen the target, and click **Run Safety Check** in the Monitor tab.
3. Click **Export Review Bundle** or, from the target repo, run `python3 scripts/run_observatory.py --target . --review-dir /tmp/Diffmogger-review`.
4. Open `/tmp/Diffmogger-review/Diffmogger-observatory.html` and inspect `/tmp/Diffmogger-review/Diffmogger-self-review.md`.
5. Confirm the review shows first-review readiness, safety status, validation state, active role or queue, known issues, the next sprint recommendation, and the next-run worker strategy.

The dashboard writes the safety-check result to the target-local
`target/integration_safety_check.json` file before the export reads it. That file is runtime state,
not source.

The generated wrapper runs the parent automation with:

```bash
--add-dir "$HOME/.codex"
```

Nested Codex startup may touch `state_5.sqlite`, `shell_snapshots`, and `sessions`, so the sessions-only allowance is too narrow. Workers still use `codex exec --ephemeral`, but the generated helper disables the child worker's inner macOS sandbox so the scheduled parent remains the single outer sandbox boundary.

For manual macOS `launchd` setup, point the LaunchAgent at the target repo's wrapper:

```text
/absolute/path/to/target-project/scripts/run_codex_automation.sh
```

For a manual multi-role run, use:

```bash
bash scripts/run_role_automation.sh --role planner
bash scripts/run_role_automation.sh --role builder
bash scripts/run_role_automation.sh --role hardener
bash scripts/run_role_automation.sh --role integrator
```

Write logs under:

```text
target/automation_logs/stdout.log
target/automation_logs/stderr.log
target/automation_logs/conveyor.stdout.log
target/automation_logs/conveyor.stderr.log
target/automation_logs/<role>.stdout.log
target/automation_logs/<role>.stderr.log
```

If the repo lives under `~/Documents`, macOS privacy controls may block `launchd` jobs until `/bin/bash` and the Node executable used by Codex have Full Disk Access. A repo under `~/Developer` usually avoids that friction.

## 5. Human Bridge

In `file_only` mode:

- Read `docs/HUMAN_REQUESTS.md` periodically.
- Do the requested manual action if you approve it.
- Reply in `docs/HUMAN_INBOX.md`.
- Let the next automation run remove handled inbox entries and archive concise notes.

In `local_notifier` mode, the separate notifier service owns native desktop notification delivery. In `discord_notifier` mode, it owns Discord credentials, posts progress/messages to configured channels, and writes captured bot mentions/replies to `docs/HUMAN_INBOX.md`.

## 6. Worker Agents

Nested Codex CLI workers should use ephemeral sessions:

```bash
codex exec --disable plugins \
  --ephemeral \
  --dangerously-bypass-approvals-and-sandbox \
  -C . \
  "<read-only worker prompt>"
```

The parent scheduled wrapper must also allow `$HOME/.codex` with `--add-dir`. `--ephemeral` reduces child session persistence, but the nested CLI may still touch Codex state and shell snapshot files during startup.

Read-only worker reports are the default for exploration and review. When write workers are explicitly enabled in the intake, generated prompts allow bounded write mode as acceleration for work that can split into reviewable lanes:

```bash
bash scripts/spawn_worker_agent.sh \
  --mode write \
  --target . \
  --run-id "$CODEX_RUN_ID" \
  --role feature_a \
  --ownership "src/feature-a/** and tests/feature-a/** only" \
  --prompt "Implement the assigned slice and report changed files/checks."
```

The main automation agent still owns planning, reviewable ownership, necessary contract definitions, integration, conflict resolution, verification, and final task-state updates. Integration-only runs with no workers are valid when faster or safer.
