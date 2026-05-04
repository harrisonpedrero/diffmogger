# Dashboard

Diffmogger includes a standalone local configuration wizard and automation dashboard.

Launch it from the starter repo:

```bash
python3 scripts/run_dashboard.py
```

The dashboard opens a native desktop window with Python's standard-library Tkinter runtime. It does not require opening a browser.

## Before Starting Automation

The dashboard checks and lists prerequisites before the combined scaffold/bootstrap run starts:

- Python 3.10+
- Tkinter GUI support
- Codex CLI installed and signed in
- `bash`
- `git`
- writable target parent directory
- Codex home availability for nested workers
- macOS Full Disk Access advisory when a target lives under `~/Documents`
- optional local notifier health when `local_notifier` mode is selected

If a required check fails, the dashboard will not start the bootstrap run.

## Configuration Wizard

The wizard is split into setup steps rather than one long scrolling form:

- Basics
- Product
- Rules
- Run Config
- Progression
- Context

It collects the same project intake fields supported by `schemas/project_intake.schema.json`. The main idea fields include inline guidance so new users know how much detail to provide:

- project name
- project type: fresh project or existing project integration
- target directory
- product goal: the problem, workflow, value, product shape, and first useful version
- target user: who uses it, their situation, pain, technical comfort, and success criteria
- desired first demo: the exact local demo path, user actions, fixture data, and visible result
- tech preferences: language, framework, storage, testing, styling, dependencies, and repo conventions
- hard constraints
- safety constraints
- external services
- what the automation must never do
- additional context files
- verification commands
- cadence in whole minutes greater than 30
- scheduling strategy: periodic sprint, fixed multi-role cadence, or continuous conveyor
- whether the human bridge is enabled
- human bridge mode
- whether freeform human requests should receive SMS/WhatsApp responses when the notifier is available
- worker-agent settings, including optional bounded write-worker acceleration disabled by default
- optional recurring local automation signals, disabled by default
- advanced multi-role automation settings, disabled by default, including a local-only remote opt-in for repos that already have git remotes configured
- meaningful deliverable
- beyond-MVP direction
- assumptions

## Fresh Or Existing Projects

For a fresh project, choose a new or empty target directory and describe the product you want Diffmogger to bootstrap.

For an existing project, choose the existing repo directory and select **Integrating into an existing project**. In that mode, use the intake to describe what already exists, which stack and commands should be preserved, and what the first integrated deliverable should prove.

Existing `AGENTS.md` and `docs/DEVELOPMENT.md` files are handled conservatively. When those files already exist, Diffmogger adds or updates a clearly marked managed automation block instead of replacing the whole file. Keep project-owned guidance outside that managed block.

For a project that already has Diffmogger files, click:

```text
Open Diffmogger Project
```

or choose its target directory with **Browse**. The dashboard loads `.agentic/project_intake.json` and `.agentic/dashboard_state.json` when present, refreshes the monitor, and recomputes the launchd label from the selected target path. This lets you reopen the dashboard after closing it and pause, restart, or remove a running or paused schedule without repeating setup.

Dashboard UI state is target-local:

```text
.agentic/dashboard_state.json
```

The starter repo does not keep per-project dashboard state.

You can also add supplemental context files such as PDFs, research notes, CSVs, design docs, or Markdown files. The dashboard copies selected files into:

```text
docs/context/
```

and writes an index at:

```text
docs/PROJECT_CONTEXT.md
```

Do not add secrets, credential exports, private production data, or paid-account dumps as context files.

## Scaffold & Bootstrap

The main action is a single button:

```text
Scaffold & Bootstrap
```

It performs the setup pipeline:

1. writes `.agentic/project_intake.json` in the target
2. copies selected context files into `docs/context/`
3. scaffolds target automation docs and scripts
4. runs `scripts/check_required_files.py`
5. starts the initial `codex exec --full-auto --skip-git-repo-check` bootstrap run

The scaffold script remains the source of truth for generated files. The dashboard is a convenience layer over that contract.

The dashboard keeps its visible run log bounded and starts dashboard-launched subprocesses in their own process group. When a bootstrap/check command exits or is cancelled, the dashboard terminates lingering child processes from that group so a temporary dev server started for smoke testing does not keep running after the dashboard run finishes.

After the scaffold/bootstrap pipeline completes and the target has the required generated files plus updated task state, the dashboard enables:

```text
Start Scheduled Automation
```

That button writes macOS LaunchAgent plist(s) under `~/Library/LaunchAgents/`, loads them with `launchctl`, and points them at the target project's own local wrappers.

For periodic sprint mode, the job points at:

```bash
bash scripts/run_codex_automation.sh
```

The launchd job uses the dashboard's **Automation Cadence Minutes** control as its `StartInterval` in seconds, sets `RunAtLoad`, and writes logs under:

```text
target/automation_logs/
```

If the intake enables multi-role automation and the strategy is **Fixed multi-role cadence**, the same button writes one LaunchAgent per role instead of the single-lane job. The jobs point at:

```bash
bash scripts/run_role_automation.sh --role planner
bash scripts/run_role_automation.sh --role builder
bash scripts/run_role_automation.sh --role hardener
bash scripts/run_role_automation.sh --role integrator
```

The fixed multi-role schedule uses `StartCalendarInterval`: planner at `:00`, builder at `:10` and `:40`, hardener at `:20` and `:50`, and integrator at `:25` and `:55`. The dashboard requires the target to be an initialized git repo before starting this schedule.

If the strategy is **Continuous conveyor**, the dashboard writes one LaunchAgent that points at:

```bash
bash scripts/run_conveyor_automation.sh
```

The conveyor sets `RunAtLoad`, keeps running locally, and chooses the next runnable lane instead of using exact role times. It prioritizes queued integration first, fast-follow replanning after a planner patch is newly deferred or a planner deferral is resolved, due planning second, builder momentum by default, and one hardener pass after integrated builder work. Conveyor state stays in `target/automation_conveyor_state.json`; its duplicate-dispatcher lock is `target/automation_conveyor.lock`.

The monitor tab can also launch:

```text
Launch Observatory
```

This opens a local browser page backed by `scripts/run_observatory.py`. The page is meant for live demos and reviews: it shows active signal nudges, conveyor health, no-progress circuit breaker state, the active role, upcoming lanes, queued and deferred patches, recent outcomes, progress pulse, and bounded log tails. It reads only target-local files and does not require external services.

The observatory also includes a compact self-review panel and scorecard that pull from local task state, role progress metrics, signal state, queue manifests, conveyor circuit-breaker state, and human bridge files. Use it as the first stop in a local review: it summarizes the current assessment, validation results, accepted and deferred patch pressure, deferred-patch triage reasons with local next actions, an explicit next-lane action plan, active nudges, queue/conveyor state, known issues, and next sprint recommendation without requiring a tour through every Markdown file.

For a durable local review artifact, render the same state to Markdown:

```bash
python3 scripts/run_observatory.py --target . --review-output /tmp/Diffmogger-self-review.md
```

For multi-role jobs in repos with configured git remotes, the dashboard blocks scheduling unless the advanced **Allow local-only multi-role automation when this repo has git remotes** option is checked. When checked, LaunchAgents receive `MULTI_ROLE_ALLOW_REMOTES=1`; scripts still refuse pushes, fetches, pulls, remote configuration, and remote-touching git commands.

Pause and remove controls manage all dashboard-owned jobs for that target: periodic, fixed-role, and conveyor.

Use:

```text
Pause Scheduled Automation
```

to unload and disable the LaunchAgent, stopping future scheduled runs across login/reboot until you start the schedule again. The pause action does not delete generated project files. The **Cancel Current Dashboard Run** button terminates the currently running dashboard-launched bootstrap/check process group; it is not the scheduler control.

Use:

```text
Remove Schedule
```

to unload the LaunchAgent, clear its disabled state, and delete the plist from `~/Library/LaunchAgents/`. This removes the recurring schedule only; it does not delete generated project files or automation docs.

## Dashboard View

The dashboard renders a small allowlist of Markdown files that are useful while automation is running:

- `docs/CODEX_AUTOMATION_TASKS.md`
- `docs/PROJECT_CONTEXT.md`
- `docs/HUMAN_REQUESTS.md`
- `docs/HUMAN_INBOX.md`
- `docs/HUMAN_OUTBOX.md`
- `docs/DAILY_AUTOMATION_REVIEW.md`
- `docs/AUTONOMY_EXPERIMENT_LOG.md`
- `docs/INITIAL_BOOTSTRAP_PROMPT.md`
- `.agentic/automation_prompt.md`

It also shows a compact status summary from the task file, including automation status, current product horizon, horizon advancement decision, and human bridge counts.

## Messages

When SMS/WhatsApp is disabled or unavailable, use the Messages tab to write to the next automation run. The dashboard uses friendly labels:

- Requests From Automation
- Messages Waiting For Next Run
- Sent Updates & Delivery Log
- Resolved Conversation History

Internally, these still map to the Markdown files the automation reads. When you send a message, the dashboard appends a structured unhandled entry to:

```text
docs/HUMAN_INBOX.md
```

The next automation run should process that inbox entry, remove it only after the requested action is complete or intentionally deferred, and archive a concise note in `docs/HUMAN_RESPONSES_ARCHIVE.md`.

For `local_notifier` mode, the dashboard can check whether the notifier health endpoint is reachable, but Twilio credentials still belong only in:

```text
services/agentic-notifier/.env
```
