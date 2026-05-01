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

Fill in the wizard, choose the target directory, optionally add context files such as PDFs or research notes, then click **Scaffold & Bootstrap**. Choose fresh-project mode for a new target directory. Choose existing-project mode when the target is an existing repo and describe the first integrated change in the intake. The dashboard writes `.agentic/project_intake.json`, copies context files into `docs/context/`, creates `docs/PROJECT_CONTEXT.md`, scaffolds required files, validates them, and starts the initial Codex bootstrap run.

When integrating into an existing repo, Diffmogger preserves existing `AGENTS.md` and `docs/DEVELOPMENT.md` content by adding or updating a managed Diffmogger section. Keep repo-owned instructions outside the managed section.

CLI path:

Write a project intake file in the target repo or pass one from anywhere:

```bash
python3 /path/to/Diffmogger/scripts/scaffold_project_docs.py \
  --intake project_intake.md \
  --target /path/to/target-project
```

Use `human_bridge_mode: file_only` when you want manual Markdown communication. Use `local_notifier` only when the separate notifier service should send SMS/WhatsApp.

Use `project_mode: existing_project` when scaffolding into a repo that already has app code, docs, or project-specific instructions.

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
codex exec --full-auto --skip-git-repo-check "$(cat docs/INITIAL_BOOTSTRAP_PROMPT.md)"
```

Review the first run closely. Confirm the app or workflow is runnable and that `docs/CODEX_AUTOMATION_TASKS.md` has a clear next sprint.

## 4. Schedule Recurring Runs

Recommended path: use the dashboard's **Start Scheduled Automation** button after bootstrap completes. It writes, enables, and loads a macOS LaunchAgent for the selected target project, using the **Automation Cadence Minutes** value as the launchd interval. The dashboard accepts only whole-minute cadences greater than 30. Use **Pause Scheduled Automation** to unload and disable the job, stopping future scheduled runs across login/reboot.

The target wrapper can still be run manually for debugging:

```bash
bash scripts/run_codex_automation.sh
```

The generated wrapper runs the parent automation with:

```bash
--add-dir "$HOME/.codex"
```

Nested Codex startup may touch `state_5.sqlite`, `shell_snapshots`, and `sessions`, so the sessions-only allowance is too narrow. Workers still use `codex exec --ephemeral`, but the generated helper disables the child worker's inner macOS sandbox so the scheduled parent remains the single outer sandbox boundary.

For manual macOS `launchd` setup, point the LaunchAgent at the target repo's wrapper:

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
codex exec --disable plugins \
  --ephemeral \
  --dangerously-bypass-approvals-and-sandbox \
  -C . \
  "<read-only worker prompt>"
```

The parent scheduled wrapper must also allow `$HOME/.codex` with `--add-dir`. `--ephemeral` reduces child session persistence, but the nested CLI may still touch Codex state and shell snapshot files during startup.
