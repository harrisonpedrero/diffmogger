# Diffmogger Dashboard

The Diffmogger Dashboard is a standalone local configuration wizard and automation monitor.

Launch it from the starter repo:

```bash
python3 scripts/run_dashboard.py
```

It opens a native desktop window using Python's standard-library Tkinter runtime. It does not require opening a browser.

## What It Does

- collects a project intake
- splits intake into Basics, Product, Rules, Run Config, Progression, and Context steps instead of a long scroll
- supports fresh-project and existing-project integration modes
- covers constraints, safety rules, automation prohibitions, human bridge choices, worker settings, optional bounded write-worker acceleration settings, optional automation signals, optional multi-role automation, deliverable definition, and beyond-MVP direction
- copies optional context files into `docs/context/`
- writes `docs/PROJECT_CONTEXT.md`
- scaffolds Diffmogger target-project files
- runs the required-file check
- starts the first `codex exec --full-auto --skip-git-repo-check` bootstrap run through one `Scaffold & Bootstrap` action
- persists dashboard state in the selected target at `.agentic/dashboard_state.json`
- reopens Diffmogger-managed targets through `Open Diffmogger Project`
- enables `Start Scheduled Automation` only after the target appears bootstrapped
- installs and loads macOS launchd jobs for periodic sprint, fixed multi-role cadence, or continuous conveyor scheduling
- pauses scheduled automation by unloading and disabling dashboard-managed LaunchAgent jobs
- removes dashboard-managed schedules by deleting the target LaunchAgent plist(s)
- renders selected automation Markdown files
- launches an optional local browser observatory for active signal nudges, conveyor health, active roles, queued/deferred patches, the latest recorded integration-safety result, recent outcomes, and timeline events
- runs `scripts/check_integration_safety.py` from the Monitor tab with **Run Safety Check** and shows the output in the bounded dashboard log
- lets a human send file-only messages to the next automation run when SMS/WhatsApp is disabled or unavailable
- displays prerequisites as readiness checks instead of raw command output

In existing-project mode, pre-existing `AGENTS.md` and `docs/DEVELOPMENT.md` files receive a managed Diffmogger automation section instead of being replaced wholesale.

## First Review Checklist

Use the dashboard Monitor tab to tie the local review together:

1. Run `bash scripts/validate_starter_kit.sh` from the Diffmogger starter-kit source.
2. Open the target with **Open Diffmogger Project**.
3. Click **Run Safety Check** and review the dashboard log.
4. Launch the observatory or run `python3 scripts/run_observatory.py --target . --once --output /tmp/Diffmogger-observatory.html`.
5. Export `python3 scripts/run_observatory.py --target . --review-output /tmp/Diffmogger-self-review.md` for a durable Markdown self-review.
6. Check first-review readiness, safety status, validation state, active role or queue, known issues, and the next-lane action plan in the observatory or Markdown export.

## Prerequisites

Before starting automation, the dashboard checks for:

- Python 3.10+
- Tkinter
- Codex CLI installed and signed in
- `bash`
- `git`
- writable target parent directory
- Codex home availability for nested workers
- macOS Full Disk Access advisory when the target lives under `~/Documents`
- optional local notifier health when `local_notifier` mode is selected
- initialized git repo before starting multi-role scheduling
- explicit local-only remote opt-in before multi-role or conveyor scheduling in repos with configured git remotes

The dashboard keeps notifier credentials out of target projects. In local-notifier mode, use `services/agentic-notifier/` for Twilio configuration.
