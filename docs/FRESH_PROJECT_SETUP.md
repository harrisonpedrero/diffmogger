# Fresh Project Setup

Use this checklist to start a new target repo from Diffmogger without keeping a runtime dependency on the Diffmogger repo.

## 1. Create An Intake

Write a project intake file in the target repo or pass one from anywhere:

```bash
python3 /path/to/Diffmogger/scripts/scaffold_project_docs.py \
  --intake project_intake.md \
  --target /path/to/target-project
```

Use `human_bridge_mode: file_only` when you want manual Markdown communication. Use `local_notifier` only when the separate notifier service should send SMS/WhatsApp.

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
scripts/spawn_worker_agent.sh
scripts/summarize_worker_outputs.py
scripts/compact_agent_state.py
```

Scheduled target-project runs should use those local scripts, not scripts from the Diffmogger starter repo.

## 3. Bootstrap The Product

From the target repo:

```bash
codex exec --full-auto "$(cat docs/INITIAL_BOOTSTRAP_PROMPT.md)"
```

Review the first run closely. Confirm the app or workflow is runnable and that `docs/CODEX_AUTOMATION_TASKS.md` has a clear next sprint.

## 4. Schedule Recurring Runs

Run the local wrapper manually once:

```bash
bash scripts/run_codex_automation.sh
```

For macOS `launchd`, point the LaunchAgent at the target repo's wrapper:

```text
/absolute/path/to/target-project/scripts/run_codex_automation.sh
```

Write logs under:

```text
target/automation_logs/stdout.log
target/automation_logs/stderr.log
```

If the repo lives under `~/Documents`, macOS privacy controls may block `launchd` jobs until `/bin/bash` and the Node executable used by Codex have Full Disk Access. A repo under `~/Developer` usually avoids that friction.

## 5. Human Bridge

In `file_only` mode:

- Read `docs/HUMAN_REQUESTS.md` periodically.
- Do the requested manual action if you approve it.
- Reply in `docs/HUMAN_INBOX.md`.
- Let the next automation run remove handled inbox entries and archive concise notes.

In `local_notifier` mode, the separate notifier service owns SMS/WhatsApp credentials and writes inbound replies to `docs/HUMAN_INBOX.md`.

## 6. Worker Agents

Nested Codex CLI workers should use ephemeral sessions:

```bash
codex exec --ephemeral \
  --sandbox workspace-write \
  --ask-for-approval never \
  -c sandbox_workspace_write.network_access=false \
  "<read-only worker prompt>"
```

This avoids `~/.codex/sessions` write failures when child workers are launched from inside a parent automation sandbox.
