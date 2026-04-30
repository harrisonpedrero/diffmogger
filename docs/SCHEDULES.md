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

Generated target projects include a local wrapper:

```bash
bash scripts/run_codex_automation.sh
```

The wrapper sets `CODEX_RUN_ID`, sets `CODEX_LOCK_PATH`, acquires the lock with local `scripts/acquire_codex_lock.sh`, exports `CODEX_LOCK_ALREADY_ACQUIRED=true`, runs `codex exec --full-auto`, and releases the lock with local `scripts/release_codex_lock.sh` when the run exits.

If a scheduler runs from another directory, call the absolute path to the target project's `scripts/run_codex_automation.sh` or set `TARGET=/absolute/path/to/target-project`.

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
