# Schedules

Codex automations should be scheduled according to expected run length and review tolerance.

## Recommended Cadences

60 minutes:

```text
Run once per hour.
```

Good for substantial engineering sprints.

Multi-role mode:

```text
Planner :00, builder :10/:40, hardener :20/:50, integrator :25/:55.
```

Good for opt-in high-throughput local automation after the target is an initialized git repo with an initial commit.

Continuous conveyor:

```text
One local dispatcher chooses the next runnable lane as soon as the previous lane exits.
```

Good when you want work-conserving local automation instead of exact role times after the target has an initial git commit. The conveyor prioritizes queued integration first, clean-HEAD baseline verification preflight or repair routing when needed, fast-follow replanning after a planner patch is newly deferred or a planner deferral is resolved, due planning second, builder momentum by default, and one hardener pass after integrated builder work. It records state in `target/automation_conveyor_state.json`, including the active role run and next decision queue, and uses `target/automation_conveyor.lock` so only one dispatcher runs.

45 minutes:

```text
Run once every 45 minutes.
```

Good for active experiments after early runs are stable.

31 minutes:

```text
Shortest dashboard-accepted cadence.
```

Use only with a lock file and short, reliable run boundaries. The dashboard accepts only integer minute values greater than 30 and passes them to launchd as `StartInterval` seconds.

## Lock File

Recommended path:

```text
target/codex_automation.lock
```

Generated target projects include a local wrapper:

```bash
bash scripts/run_codex_automation.sh
```

The wrapper sets `CODEX_RUN_ID`, sets `CODEX_LOCK_PATH`, acquires the lock with local `scripts/acquire_codex_lock.sh`, exports `CODEX_LOCK_ALREADY_ACQUIRED=true`, runs `codex exec --full-auto --skip-git-repo-check`, grants `$HOME/.codex` access for nested Codex CLI startup, and releases the lock with local `scripts/release_codex_lock.sh` when the run exits.

If a scheduler runs from another directory, call the absolute path to the target project's `scripts/run_codex_automation.sh` or set `TARGET=/absolute/path/to/target-project`.

Generated targets also include an optional conveyor wrapper:

```bash
bash scripts/run_conveyor_automation.sh --dry-run
bash scripts/run_conveyor_automation.sh --once
python3 scripts/run_observatory.py --open
```

When multi-role files are present, the conveyor invokes `scripts/run_role_automation.sh --role <role>`. Without multi-role files, it falls back to `scripts/run_codex_automation.sh`.

## Dashboard LaunchAgent Controls

On macOS, the dashboard can manage the recurring schedule directly after bootstrap:

- **Start Scheduled Automation** writes target-specific plist(s) under `~/Library/LaunchAgents/`, clears any disabled state when possible, loads with `launchctl bootstrap`, enables with `launchctl enable`, and starts the selected scheduling strategy.
- **Pause Scheduled Automation** unloads that LaunchAgent with `launchctl bootout` and disables it with `launchctl disable`, stopping future scheduled runs across login/reboot until the schedule is started again.
- **Remove Schedule** unloads that LaunchAgent, clears its disabled state, and deletes the plist from `~/Library/LaunchAgents/`. It does not delete generated project files.
- **Cancel Current Dashboard Run** only terminates a bootstrap/check process launched by the dashboard itself. It is not the launchd scheduler control.

Dashboard-managed jobs use labels shaped like:

```text
com.diffmogger.automation.<target-name>.<hash>
```

Multi-role dashboard-managed jobs append the role:

```text
com.diffmogger.automation.<target-name>.<hash>.planner
com.diffmogger.automation.<target-name>.<hash>.builder
com.diffmogger.automation.<target-name>.<hash>.hardener
com.diffmogger.automation.<target-name>.<hash>.integrator
```

Those jobs use `StartCalendarInterval`, not `StartInterval`, and point at `scripts/run_role_automation.sh --role <role>`.

Continuous conveyor jobs use one LaunchAgent:

```text
com.diffmogger.automation.<target-name>.<hash>.conveyor
```

The job points at `scripts/run_conveyor_automation.sh`, sets `RunAtLoad`, and does not use `StartInterval` or `StartCalendarInterval` because the dispatcher stays running until paused, removed, blocked, or stopped by a critical status.

In `ticket_campaign` mode, the conveyor also exits when `scripts/ticket_run.py` determines that every ticket in `docs/TICKET_RUN.md` is done with evidence or that all remaining tickets are blocked. It finalizes the local report and sends a native desktop notification, or records a durable fallback in `docs/HUMAN_OUTBOX.md`, before stopping.

Logs are written under the target repo:

```text
target/automation_logs/stdout.log
target/automation_logs/stderr.log
target/automation_logs/<role>.stdout.log
target/automation_logs/<role>.stderr.log
```

The lock includes:

- run id
- owner PID
- UTC timestamp
- stale-after duration
- host
- command/context

Target-local `scripts/acquire_codex_lock.sh` fails cleanly when an active lock exists. It removes stale locks after `CODEX_LOCK_STALE_SECONDS` seconds, defaulting to 4 hours. `scripts/release_codex_lock.sh` prefers a matching `CODEX_RUN_ID` before releasing.

The automation prompt should not acquire or release a second lock when `CODEX_LOCK_ALREADY_ACQUIRED=true`; the wrapper owns the lock for scheduled runs.

If the lock exists and is fresh, skip code mutation. If stale, document why it was replaced. Lock files reduce overlapping-run risk; they do not remove the need to review diffs.

## Review Cadence

- Review first 3 runs closely.
- Review daily capsules after the workflow stabilizes.
- Run consolidation mode after major milestones or after many automation cycles.
