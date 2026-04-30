# Development

This is the operator manual for Diffmogger.

## Prerequisites

- Git.
- Python 3.10 or newer.
- Codex CLI installed and authenticated.
- Optional: Twilio account, Twilio SMS or WhatsApp sender, and ngrok for phone-based human replies.

Keep secrets outside target repos. Do not paste API keys into prompts, task files, inbox files, or generated docs.

## Use Diffmogger For A New Project

Recommended layout:

```text
work/
  Diffmogger/
  my-project/
```

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
docs/INITIAL_BOOTSTRAP_PROMPT.md
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
- product goal
- target user
- desired first demo
- tech preferences
- hard constraints
- safety constraints
- external services
- verification commands
- cadence
- human bridge preference
- worker-agent preference
- meaningful deliverable definition
- beyond-MVP direction

If values are missing, the generation prompt should make reasonable defaults and document assumptions.

## Generate Project-Specific Prompts

Use:

```text
prompts/GENERATE_PROJECT_AUTOMATION_PROMPTS.md
```

It should produce:

```text
AGENTS.md
.agentic/automation_prompt.md
docs/INITIAL_BOOTSTRAP_PROMPT.md
docs/CODEX_AUTOMATION_TASKS.md
docs/CODEX_AUTOMATION_GUARDRAILS.md
docs/HUMAN_REQUESTS.md
docs/HUMAN_OUTBOX.md
docs/HUMAN_INBOX.md
docs/HUMAN_RESPONSES_ARCHIVE.md
docs/HUMAN_BRIDGE_SETUP.md
docs/AUTONOMY_EXPERIMENT_LOG.md
docs/DAILY_AUTOMATION_REVIEW.md
```

The scaffold script creates generic versions of the same files. The prompt route is smarter; the script is a convenience and CI smoke test.

## Validate Generated Output

```bash
python3 scripts/check_required_files.py ../my-project
```

Check that the target automation prompt references:

- `docs/HUMAN_INBOX.md`
- `docs/HUMAN_RESPONSES_ARCHIVE.md`
- `POST http://127.0.0.1:8765/api/notify`
- `NOTIFIER_UNREACHABLE`
- `Codex CLI worker decision: USE / SKIP / UNAVAILABLE`
- `ACTIVE_WITH_PENDING_USER_INPUT`
- `BLOCKED_ON_USER`
- `target/codex_automation.lock`

## Wire Codex Automations

In the Codex app, create a recurring automation for the target repo and use the contents of:

```text
.agentic/automation_prompt.md
```

For scripted runs:

```bash
codex exec --full-auto "$(cat .agentic/automation_prompt.md)"
```

Generated target repos should usually run `scripts/run_codex_automation.sh` instead of calling `codex exec` directly. The wrapper handles lock acquire/release and adds `$HOME/.codex` as a writable directory so nested Codex CLI workers can authenticate and start inside the parent sandbox.

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
target/codex_automation.lock
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

Default output:

```text
target/agent_runs/<run_id>/worker_<role>.md
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
mkdir -p "target/agent_runs/$RUN_ID"

codex exec --disable plugins \
  --ephemeral \
  --dangerously-bypass-approvals-and-sandbox \
  -C . \
  "You are a read-only worker for this project. Read the repo and write a concise test-gap report to target/agent_runs/$RUN_ID/test_gap_worker.md. Do not modify source files except for that output report. Do not use network. Do not spawn workers. Stop after writing the report."
```

Use the bypass shape only for nested child workers launched inside a scheduled parent Codex run. The parent remains the outer sandbox boundary.

Rules:

- one generation of workers by default
- read-only reports first
- implementation workers need disjoint write scopes or isolation
- workers do not send SMS/WhatsApp messages
- workers do not touch `.env`, credentials, or external services
- main agent owns integration
- task file records worker activity

## Human Bridge Mode A: Manual Files

Generated target projects include:

```text
docs/HUMAN_REQUESTS.md
docs/HUMAN_OUTBOX.md
docs/HUMAN_INBOX.md
docs/HUMAN_RESPONSES_ARCHIVE.md
docs/HUMAN_BRIDGE_SETUP.md
```

The automation writes requests. The human manually replies in `HUMAN_INBOX.md`. The next automation run reads the inbox, handles replies, removes handled entries, and appends concise archive notes.

Use this mode first. It has no credentials and no webhook.

Freeform inbox commands still matter in file-only mode. If the human writes `send me a summary`, `status update`, or similar, the automation should answer locally in Markdown or an app artifact. It should not send SMS/WhatsApp or record `NOTIFIER_UNREACHABLE` unless Mode B is configured.

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
TARGET_REPO_DIR=/absolute/path/to/target-project
TARGET_HUMAN_INBOX_PATH=/absolute/path/to/target-project/docs/HUMAN_INBOX.md
TARGET_HUMAN_REQUESTS_PATH=/absolute/path/to/target-project/docs/HUMAN_REQUESTS.md
TARGET_HUMAN_OUTBOX_PATH=/absolute/path/to/target-project/docs/HUMAN_OUTBOX.md
TARGET_HUMAN_ARCHIVE_PATH=/absolute/path/to/target-project/docs/HUMAN_RESPONSES_ARCHIVE.md
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
POST http://127.0.0.1:8787/twilio/inbound
```

Expose only the webhook port:

```bash
ngrok http 8787
```

Configure Twilio inbound webhook:

```text
https://<ngrok-domain>/twilio/inbound
```

Set:

```text
WEBHOOK_PUBLIC_BASE_URL=https://<ngrok-domain>
```

The notifier writes inbound replies to the target project's `docs/HUMAN_INBOX.md`. The target automation consumes and clears handled entries.

The target project stays decoupled from the notifier. It calls the loopback API and reads/writes target docs only. It should not import notifier code, inspect notifier internals during normal runs, or handle Twilio credentials.

## Notifier Tests

```bash
cd services/agentic-notifier
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest
```

Tests do not send real SMS and do not require real Twilio credentials.

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

If the notifier is unavailable, the target automation should write/update `docs/HUMAN_REQUESTS.md` for unlock requests, record attempted outbound messages in `docs/HUMAN_OUTBOX.md` with status `NOTIFIER_UNREACHABLE`, set `ACTIVE_WITH_PENDING_USER_INPUT` only when the unresolved item matters and other work remains, and continue.

## Keep Secrets Outside Codex

- Target automations must not read `.env`.
- Notifier `.env` is local and ignored.
- Use read-only/data-only keys when possible.
- Do not include credentials in SMS replies.
- Do not commit runtime queue files.

## Context Hygiene

Active files should stay short:

- `docs/HUMAN_INBOX.md`: unhandled messages only.
- `docs/HUMAN_REQUESTS.md`: active unresolved requests.
- `docs/HUMAN_RESPONSES_ARCHIVE.md`: concise handled responses.
- `docs/CODEX_AUTOMATION_TASKS.md`: current state, not a museum.

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
Check ngrok target port, Twilio webhook URL, `WEBHOOK_PUBLIC_BASE_URL`, Twilio signature validation, and target inbox path.

Codex cannot read/write files:
Check current working directory, sandbox mode, approval policy, file permissions, and nested `AGENTS.md` instructions.

Context bloat:
Move handled inbox items to archive, prune stale tasks, and consolidate worker reports.

## Validate Diffmogger

```bash
bash scripts/validate_starter_kit.sh
```

The validation script checks required files, schemas, templates, scaffold output, and notifier tests when dependencies are available.
