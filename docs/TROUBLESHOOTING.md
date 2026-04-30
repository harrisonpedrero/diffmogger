# Troubleshooting

## Automation Does Too Little

Strengthen sprint sizing. Make sure the automation prompt contains the required adjacent-task continuation language and the task file names a substantial next milestone.

## Automation Drifts

Rewrite `docs/CODEX_AUTOMATION_TASKS.md` around one best next milestone. Tighten scope boundaries in guardrails. Add a decision record if direction changed.

## Automation Writes Docs Instead Of Product

Require an integrated deliverable each run: code, tests, report, demo command, fixture, screenshot, UX improvement, or verification result.

In file-only human bridge mode, summary/status requests should be satisfied locally in Markdown or app artifacts. In local-notifier mode, if the human asked to be texted or sent a status update, writing a local Markdown summary is insufficient; the automation should call `POST http://127.0.0.1:8765/api/notify` when the notifier is available.

## Automation Keeps Asking The Human

Reserve human requests for manual unlocks. Tell Codex to choose safe defaults for reversible decisions and document assumptions.

## Automation Never Asks The Human

Add a human-as-resource reminder to the task file. If API keys, paid services, deploys, or major product choices would unlock value, create a request.

## Worker Outputs Pile Up

Require consolidation before final summary. Move stale worker reports out of the active handoff and record accepted/rejected/deferred findings in the task file.

Use:

```bash
python3 scripts/summarize_worker_outputs.py /absolute/path/to/target-project --run-id "$CODEX_RUN_ID"
```

## Broad Runs Skip Workers Without Explanation

Require the task file to include:

```text
Codex CLI worker decision: USE / SKIP / UNAVAILABLE
Reason: <one sentence>
```

Check availability with `command -v codex`. If Codex CLI is unavailable, continue without blocking the sprint and record `UNAVAILABLE`.

## Nested Codex Worker Cannot Start Or Write Reports

If a worker report says `~/.codex/sessions`, `~/.codex/state_5.sqlite`, or `~/.codex/shell_snapshots` is not writable, the parent automation sandbox likely blocked the child CLI before the child worker could start. Generated scheduled wrappers should grant the parent run access to Codex's home directory:

```bash
--add-dir "$HOME/.codex"
```

If startup works but the worker fails with:

```text
sandbox-exec: sandbox_apply: Operation not permitted
```

the child Codex process is hitting a macOS nested sandbox failure. Generated worker helpers avoid that second sandbox layer with:

```bash
codex exec --disable plugins \
  --ephemeral \
  --dangerously-bypass-approvals-and-sandbox \
  -C "$target" \
  "<worker prompt>"
```

The bypass is for the nested child only. The scheduled parent remains the outer sandbox boundary.

For existing target repos, update `scripts/run_codex_automation.sh` to add `$HOME/.codex` and update `scripts/spawn_worker_agent.sh` to use the nested-child command shape above. Then rerun the scheduled job. If worker startup still fails, record `Codex CLI worker decision: UNAVAILABLE` and continue the sprint with in-session or main-agent review.

## Notifier Outbound Works But Inbound Does Not

Check:

- ngrok or tunnel points at the webhook port, not the local notify API port
- Twilio inbound webhook URL includes the correct path
- `WEBHOOK_PUBLIC_BASE_URL` matches the public ngrok origin
- webhook handler validates the same URL Twilio used
- inbound writes use the target project path
- dedupe is not suppressing new messages incorrectly

## Notifier Sends Real SMS During Testing

Set `DRY_RUN=true`, use `python scripts/send_test_notification.py` without `--real-send`, and run tests with fake Twilio clients. Unit tests should never require real credentials.

## Notifier Provider Failure Mentions A2P Or 30034

For SMS via US +1 10DLC, Twilio may reject outbound sends until the sender and A2P 10DLC campaign are registered and ready. Error `30034` usually means that setup is not complete for the route. Use file-only mode, dry-run mode, or a configured WhatsApp sandbox while SMS setup is pending.

## Target Project Cannot Reach The Notifier

Check that `python -m agentic_notifier.run_service` is running, `GET http://127.0.0.1:8765/health` succeeds, and the API is bound to loopback. If `LOCAL_NOTIFY_API_TOKEN` is set, include the bearer token.

The target automation should not claim a message was sent if the API is unreachable. It should write the intended message to `docs/HUMAN_OUTBOX.md` with status `NOTIFIER_UNREACHABLE`.

## Inbound Replies Are Written But Codex Keeps Re-reading Them

The target automation owns inbox cleanup. It must remove handled entries from `docs/HUMAN_INBOX.md` only after the requested action is complete or intentionally deferred, then append concise notes to `docs/HUMAN_RESPONSES_ARCHIVE.md`.

## Human Asked For A Text But Got Only A File

In file-only mode, this is expected: the automation should answer locally. In local-notifier mode, treat it as an automation-process bug. Update `.agentic/automation_prompt.md` so freeform inbox requests such as `send me a summary`, `text me the blocker`, `status update`, or `what have you done so far?` are handled through the notifier. If still relevant, send the concise outbound response and archive the handled inbox entry.

## Codex Cannot Read Or Write Expected Files

Check:

- current working directory
- Git root
- sandbox mode
- approval policy
- file permissions
- `AGENTS.md` or nested override instructions

## Context Bloat

Keep active files short. Archive handled inbox items and stale tasks. Put long history in logs or archives, not in files read every run.

Review compaction before writing:

```bash
python3 scripts/compact_agent_state.py --dry-run /absolute/path/to/target-project
```

Then run without `--dry-run` only after confirming unresolved human requests remain active.

## Lock Will Not Release

`scripts/release_codex_lock.sh` prefers a matching `CODEX_RUN_ID`. If release fails, inspect `target/codex_automation.lock` and confirm you are not removing another active run. Use `CODEX_LOCK_FORCE_RELEASE=true` only after review.

If a scheduled run already exports `CODEX_LOCK_ALREADY_ACQUIRED=true`, the Codex prompt should not acquire or release another lock. The target repo's `scripts/run_codex_automation.sh` owns lock release for scheduled runs.
