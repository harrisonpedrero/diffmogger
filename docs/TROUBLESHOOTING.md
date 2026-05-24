# Troubleshooting

## Start Fails

Run the dashboard environment check:

```bash
python3 scripts/dashboard_backend_cli.py diagnostics.environment
```

Generated targets must contain `.diffmogger/scripts/run_temporal_worker.sh`, `.diffmogger/scripts/orchestration_cli.py`, `.diffmogger/runtime/orchestration.sqlite3`, and a git `HEAD`. On macOS, inspect launchd state through the dashboard or `launchctl print gui/$UID/<label>` using the label recorded in the runner projection.

## Stop Does Not Stop The Runner

Dashboard Stop asks launchd to stop the target job when launchd owns it. If the portable fallback was used, Stop terminates the recorded process group. Inspect `.diffmogger/runtime/automation_runner.json` and `.diffmogger/runtime/automation_logs/` before forcing cleanup.

## Temporal Dev Server Fails

Install the root dependencies and rerun the local cycle smoke:

```bash
python -m pip install -r requirements.txt
PYTHONPATH=src python -m diffmogger.orchestration.cli temporal-cycle --target /tmp/Diffmogger-temporal --run-id smoke
```

If the Temporal SDK cannot download or start its local test server, use `policy-cycle` to verify scheduler policy while treating Temporal startup as local setup work.

## Alembic Migration Fails

Run:

```bash
PYTHONPATH=src python -m pytest tests/test_new_architecture.py -q
```

Do not hand-edit `PRAGMA user_version` or generated SQLite tables. Add or fix an Alembic revision, then rerun the migration smoke.

## Apprise Sends Nothing

Check:

- `APPRISE_URLS` is set in `services/agentic-notifier/.env`
- `DRY_RUN=false` only after testing
- `curl http://127.0.0.1:8765/health` reports `apprise_configured: true`
- the API is bound to loopback unless `LOCAL_NOTIFY_API_TOKEN` is configured

The target automation should record `NOTIFIER_UNREACHABLE` or `APPRISE_SEND_FAILED` in typed human-message state and continue useful work where possible.

## Tree-Sitter Facts Are Missing

Tree-sitter facts are deterministic when parser packages are installed. If a parser is unavailable, Diffmogger records an explicit fallback fact instead of guessing from regex. Treat fallback facts as a setup or indexing improvement opportunity, not as a reason to stop unrelated work.

## Browser Or MCP Validation Fails

Prefer managed local setup, fixtures, mocks, alternate validation, or deferred QA work. Record the failed command and evidence path in typed validation receipts. Do not loop on the same failing external dependency.

## Automation Does Too Little

Check scheduler decisions and tickets in SQLite. If tickets remain, the scheduler should produce build, repair, setup, mock, fixture, defer, split, reframe, review, documentation, validation, or integration work unless a real safety boundary applies.

## Human Replies Reappear

The target automation owns message resolution. It must mark handled dashboard messages resolved only after the requested action is complete or intentionally deferred, then record concise notes in typed human-message state.

## Context Bloat

Generated Markdown projections are bounded views. Compact or regenerate projections from SQLite instead of preserving long historical handoff files as authority.
