# Development

This is the operator manual for Diffmogger.

## Prerequisites

- Git.
- Python 3.10 or newer.
- Codex CLI installed and authenticated.
- Node/npm and Rust when developing the native dashboard.
- Optional: Discord bot configuration for progress/message channels, plus macOS local desktop notifications.

Keep secrets outside target repos. Do not paste API keys into prompts, task files, inbox files, or generated docs.

## Use Diffmogger For A New Project

Recommended layout:

```text
work/
  Diffmogger/
  my-project/
```

Recommended native dashboard path:

```bash
cd services/agentic-dashboard/native
npm install
npm run tauri dev
```

Legacy Tkinter dashboard path, still useful for compatibility checks:

```bash
python3 scripts/run_dashboard.py
```

The native dashboard uses `scripts/dashboard_backend_cli.py` and the same scaffold contracts as the legacy launcher. It checks prerequisites, gathers the intake, copies optional context files into the target, scaffolds required files, validates them, and starts the first bootstrap run through a single `Scaffold & Bootstrap` action.

Create a target repo:

```bash
mkdir ../my-project
cd ../my-project
git init
```

Create or edit an intake brief. You can start from:

```text
Diffmogger/examples/generic-web-app/project_intake.md
```

Scaffold generic automation docs:

```bash
cd ../Diffmogger
python3 scripts/scaffold_project_docs.py \
  --intake examples/generic-web-app/project_intake.md \
  --target ../my-project

python3 scripts/check_required_files.py ../my-project
```

Then in the target repo, run the bootstrap prompt with Codex:

```text
.diffmogger/state/INITIAL_BOOTSTRAP_PROMPT.md
```

The bootstrap run should create the first runnable product baseline, verification commands, and a useful first task-file state.

## Retrofit An Existing Repo

1. Read the existing README, package/build files, scripts, tests, docs, and architecture.
2. Use `prompts/REVIEW_EXISTING_PROJECT.md`.
3. Generate or scaffold the automation files.
4. Edit the generated task file so it describes the real repo state.
5. Start with an hourly cadence and review the first three runs.

Do not force the existing repo into a new stack. The automation should follow local conventions.

## Project Intake

Use `prompts/PROJECT_INTAKE_PROMPT.md` to turn a vague idea into a usable brief.

The intake should cover:

- project name
- project mode: fresh project or existing project integration
- product goal
- target user
- desired first demo
- tech preferences
- hard constraints
- safety constraints
- automation must-never-do rules
- external services
- additional context files when useful
- verification commands
- cadence
- human bridge preference
- worker-agent preference
- meaningful deliverable definition
- beyond-MVP direction

If values are missing, the generation prompt should make reasonable defaults and document assumptions.

For existing projects, keep the intake explicit about the current stack, verification commands, files that should not be rewritten, and the first integrated deliverable. Diffmogger updates existing `AGENTS.md` and `docs/DEVELOPMENT.md` through managed sections instead of replacing the whole file.

## Generate Project-Specific Prompts

Use:

```text
prompts/GENERATE_PROJECT_AUTOMATION_PROMPTS.md
```

It should produce sidecar files for new targets:

```text
AGENTS.md
.diffmogger/manifest.json
.diffmogger/agentic/automation_prompt.md
.diffmogger/state/INITIAL_BOOTSTRAP_PROMPT.md
.diffmogger/state/PROJECT_CONTEXT.md
.diffmogger/state/CODEX_AUTOMATION_TASKS.md
.diffmogger/state/CODEX_AUTOMATION_GUARDRAILS.md
.diffmogger/state/HUMAN_REQUESTS.md
.diffmogger/state/HUMAN_OUTBOX.md
.diffmogger/state/HUMAN_INBOX.md
.diffmogger/state/HUMAN_RESPONSES_ARCHIVE.md
.diffmogger/state/HUMAN_BRIDGE_SETUP.md
.diffmogger/state/AUTONOMY_EXPERIMENT_LOG.md
.diffmogger/state/DAILY_AUTOMATION_REVIEW.md
```

The scaffold script creates generic versions of the same files. The prompt route is smarter; the script is a convenience and CI smoke test.

## Validate Generated Output

```bash
python3 scripts/check_required_files.py ../my-project
```

Check that the target automation prompt references:

- `.diffmogger/state/HUMAN_INBOX.md`
- `.diffmogger/state/HUMAN_RESPONSES_ARCHIVE.md`
- `POST http://127.0.0.1:8765/api/notify`
- `NOTIFIER_UNREACHABLE`
- `Codex CLI worker decision: USE / SKIP / UNAVAILABLE`
- `ACTIVE_WITH_PENDING_USER_INPUT`
- `BLOCKED_ON_USER`
- `.diffmogger/runtime/codex_automation.lock`

## Wire Codex Automations

In the Codex app, create a recurring automation for the target repo and use the contents of:

```text
.diffmogger/agentic/automation_prompt.md
```

For scripted runs:

```bash
codex exec --full-auto "$(cat .diffmogger/agentic/automation_prompt.md)"
```

Generated target repos should usually run `.diffmogger/scripts/run_codex_automation.sh` instead of calling `codex exec` directly. The wrapper handles lock acquire/release, runs Codex through `.diffmogger/scripts/run_process_watchdog.py`, and adds `$HOME/.codex` as a writable directory so nested Codex CLI workers can authenticate and start inside the parent sandbox. The default hard timeout is 90 minutes; set `CODEX_ROLE_TIMEOUT_SECONDS` when a target needs a different budget.

Choose sandbox and approval settings deliberately. Read-only is appropriate for reviews. Workspace-write/full-auto is appropriate only when you expect edits and trust the local environment.

## Local Vs Worktree Runs

Local runs operate directly in the target checkout. They are simplest and easiest to inspect.

Worktree runs isolate automation changes in separate worktrees. They are better when multiple automations or humans may edit the same repo. If using high cadence or multiple agents, prefer worktrees or strict lock files.

## Schedules And Lock Files

Cadence guidance:

- Hourly: default.
- Every 30 minutes: after stable early runs.
- Every 15 minutes: only with lock-file behavior.

Recommended lock path:

```text
.diffmogger/runtime/codex_automation.lock
```

Each run should:

1. Check for a fresh lock before mutating files.
2. Create a lock with run id and timestamp.
3. Skip mutation if another run is active.
4. Treat stale locks conservatively and document why they were replaced.
5. Release the lock at the end.

## Worker Agents

Use workers for bounded tasks that benefit from parallel review or exploration:

- architecture review
- test gap review
- product polish review
- risk review
- isolated implementation prototype

Write-capable workers are optional and disabled in generated projects unless the intake explicitly enables them. Keep read-only reports as the default; use write workers only with disjoint ownership, a contract-first plan, and main-agent integration.

Default output:

```text
.diffmogger/runtime/agent_runs/<run_id>/worker_<role>.md
```

Every recurring run should explicitly record:

```text
Codex CLI worker decision: USE / SKIP / UNAVAILABLE
Reason: <one sentence>
```

Check availability before using Codex CLI workers:

```bash
command -v codex
```

Default read-only worker command shape:

```bash
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p ".diffmogger/runtime/agent_runs/$RUN_ID"

codex exec --disable plugins \
  --ephemeral \
  --dangerously-bypass-approvals-and-sandbox \
  -C . \
  "You are a read-only worker for this project. Read the repo and write a concise test-gap report to .diffmogger/runtime/agent_runs/$RUN_ID/test_gap_worker.md. Do not modify source files except for that output report. Do not use network. Do not spawn workers. Stop after writing the report."
```

Use the bypass shape only for nested child workers launched inside a scheduled parent Codex run. The parent remains the outer sandbox boundary.

Rules:

- one generation of workers by default
- read-only reports first
- implementation workers need disjoint write scopes or isolation
- workers do not send Discord/local notifier messages
- workers do not touch `.env`, credentials, or external services
- main agent owns integration
- task file records worker activity

## Human Bridge Mode A: Manual Files

Generated target projects include:

```text
.diffmogger/state/HUMAN_REQUESTS.md
.diffmogger/state/HUMAN_OUTBOX.md
.diffmogger/state/HUMAN_INBOX.md
.diffmogger/state/HUMAN_RESPONSES_ARCHIVE.md
.diffmogger/state/HUMAN_BRIDGE_SETUP.md
```

The automation writes requests. The human manually replies in `HUMAN_INBOX.md`. The next automation run reads the inbox, handles replies, removes handled entries, and appends concise archive notes.

Use this mode first. It has no credentials and no webhook.

Freeform inbox commands still matter in file-only mode. If the human writes `send me a summary`, `status update`, or similar, the automation should answer locally in Markdown or an app artifact. It should not call notifier APIs or record `NOTIFIER_UNREACHABLE` unless notifier mode is configured.

## Human Bridge Mode B: Bundled Notifier

The reusable notifier lives at:

```text
services/agentic-notifier/
```

Install:

```bash
cd services/agentic-notifier
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Configure `.env`:

```text
DISCORD_BOT_TOKEN=replace-with-your-discord-bot-token
DISCORD_PROGRESS_CHANNEL_ID=123456789012345678
DISCORD_MESSAGING_CHANNEL_ID=123456789012345679
LOCAL_NOTIFICATIONS_ENABLED=true
TARGET_REPO_DIR=/absolute/path/to/target-project
TARGET_HUMAN_INBOX_PATH=/absolute/path/to/target-project/.diffmogger/state/HUMAN_INBOX.md
TARGET_HUMAN_REQUESTS_PATH=/absolute/path/to/target-project/.diffmogger/state/HUMAN_REQUESTS.md
TARGET_HUMAN_OUTBOX_PATH=/absolute/path/to/target-project/.diffmogger/state/HUMAN_OUTBOX.md
TARGET_HUMAN_ARCHIVE_PATH=/absolute/path/to/target-project/.diffmogger/state/HUMAN_RESPONSES_ARCHIVE.md
DRY_RUN=true
```

Run:

```bash
python -m agentic_notifier.run_service
```

Default endpoints:

```text
GET  http://127.0.0.1:8765/health
POST http://127.0.0.1:8765/api/notify
```

Discord mode posts `event_kind: "progress"` notifications to the configured progress channel and `event_kind: "message"` notifications to the configured messaging channel. It writes captured bot mentions/replies from the messaging channel to the target project's `.diffmogger/state/HUMAN_INBOX.md`. The target automation consumes and clears handled entries.

The target project stays decoupled from the notifier. It calls the loopback API and reads/writes target docs only. It should not import notifier code, inspect notifier internals during normal runs, or handle Discord credentials.

## Notifier Tests

```bash
cd services/agentic-notifier
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest
```

Tests use fake Discord senders and dry-run local-notification paths. They do not require real Discord credentials.

## Target Project Notify Call

Human-unlock request payload:

```json
{
  "request_id": "HR-2026-04-29-001",
  "type": "api_key_setup",
  "priority": "unlocking",
  "summary": "Add Service X read-only API key",
  "context": "This unlocks the next source adapter while offline fixtures remain available.",
  "agent_recommendation": "Use read-only/data-only access. Do not grant write, billing, admin, or production permissions.",
  "minimum_user_action": "Add SERVICE_X_API_KEY to your local secret store and reply HR-001 DONE.",
  "reply_format": "HR-001 DONE or HR-001 SKIP",
  "unblocked_work_remaining": [
    "Continue fixture-based dashboard work",
    "Continue report polish"
  ],
  "dedupe_key": "HR-2026-04-29-001:v1"
}
```

Direct status/update response payload:

```json
{
  "request_id": "MSG-2026-04-29-001",
  "type": "human_requested_summary",
  "priority": "normal",
  "summary": "Progress summary requested by human",
  "message_body": "Project update: Built X, Y, and Z. Checks passing: tests/build. Current blocker: none. Next sprint: improve the report path.",
  "agent_recommendation": "No action needed unless you want to review the generated artifacts.",
  "minimum_user_action": "None.",
  "reply_format": "Optional follow-up request.",
  "unblocked_work_remaining": [
    "Continue current automation sprint"
  ],
  "dedupe_key": "MSG-2026-04-29-001:v1",
  "expects_reply": false
}
```

If the notifier is unavailable, the target automation should write/update `.diffmogger/state/HUMAN_REQUESTS.md` for unlock requests, record attempted outbound messages in `.diffmogger/state/HUMAN_OUTBOX.md` with status `NOTIFIER_UNREACHABLE`, set `ACTIVE_WITH_PENDING_USER_INPUT` only when the unresolved item matters and other work remains, and continue.

## Keep Secrets Outside Codex

- Target automations must not read `.env`.
- Notifier `.env` is local and ignored.
- Use read-only/data-only keys when possible.
- Do not include credentials in notifier messages.
- Do not commit `.diffmogger/runtime/` files.

## Context Hygiene

Active files should stay short:

- `.diffmogger/state/HUMAN_INBOX.md`: unhandled messages only.
- `.diffmogger/state/HUMAN_REQUESTS.md`: active unresolved requests.
- `.diffmogger/state/HUMAN_RESPONSES_ARCHIVE.md`: concise handled responses.
- `.diffmogger/state/CODEX_AUTOMATION_TASKS.md`: current state, not a museum.

Archive old worker reports and stale tasks periodically.

## Troubleshooting

Automation does too little:
Strengthen sprint sizing and point the task file at one substantial next milestone.

Automation drifts:
Tighten guardrails, rewrite the next milestone, and record the decision.

Stale tasks repeat:
Require task-file pruning at end of run.

Automation keeps asking the human:
Use safe defaults for reversible decisions. Ask only for manual unlocks, paid actions, risky side effects, or high-impact product choices.

Automation never asks the human:
Add a pending unlock in the task file and use the human bridge protocol.

Notifier outbound works but inbound does not:
Check the Discord messaging channel id, Message Content Intent, bot permissions, bot mention/reply capture behavior, target inbox path, and inbound dedupe state.

Codex cannot read/write files:
Check current working directory, sandbox mode, approval policy, file permissions, and nested `AGENTS.md` instructions.

Context bloat:
Move handled inbox items to archive, prune stale tasks, and consolidate worker reports.

## Validate Diffmogger

```bash
bash scripts/validate_starter_kit.sh
```

The validation script checks required files, schemas, templates, scaffold output, and notifier tests when dependencies are available.
