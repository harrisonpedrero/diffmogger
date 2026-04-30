# Schedules

Codex automations should be scheduled according to expected run length and review tolerance.

## Recommended Cadences

Hourly:

```text
Run once per hour.
```

Good for substantial engineering sprints.

Every 30 minutes:

```text
Run twice per hour.
```

Good for active experiments after early runs are stable.

Every 15 minutes:

```text
Run four times per hour.
```

Use only with a lock file and short, reliable run boundaries.

## Lock File

Recommended path:

```text
target/codex_automation.lock
```

Use the bundled helpers from the target project working directory:

```bash
export CODEX_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
bash /path/to/Diffmogger/scripts/acquire_codex_lock.sh "scheduled sprint"

codex exec --full-auto "$(cat .agentic/automation_prompt.md)"

bash /path/to/Diffmogger/scripts/release_codex_lock.sh
```

If the scheduler runs from another directory, set `CODEX_LOCK_PATH` to the target project's lock file.

The lock includes:

- run id
- owner PID
- UTC timestamp
- stale-after duration
- host
- command/context

`scripts/acquire_codex_lock.sh` fails cleanly when an active lock exists. It removes stale locks after `CODEX_LOCK_STALE_SECONDS` seconds, defaulting to 4 hours. `scripts/release_codex_lock.sh` prefers a matching `CODEX_RUN_ID` before releasing.

If the lock exists and is fresh, skip code mutation. If stale, document why it was replaced. Lock files reduce overlapping-run risk; they do not remove the need to review diffs.

## Review Cadence

- Review first 3 runs closely.
- Review daily capsules after the workflow stabilizes.
- Run consolidation mode after major milestones or after many automation cycles.
