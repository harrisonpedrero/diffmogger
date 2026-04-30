# Diffmogger

A Markdown-first operating system for recurring AI coding agents.

Diffmogger is for solo and small-team projects that want recurring Codex automation to compound instead of restarting from scratch. It externalizes agent state into repo-local Markdown so scheduled runs can preserve context, verify their own work, ask for human unlocks asynchronously, and keep moving around blockers.

It is different from a pile of prompt files or a basic scheduled agent run because it includes the operating plumbing around the agent: task state, guardrails, inbox/outbox files, archives, lock files, worker reports, validation markers, and a local optional human bridge. The goal is not enterprise autonomy infrastructure. Diffmogger is alpha, local-first, git-diffable workflow scaffolding for ambitious personal and small-team engineering work.

Model/runtime note: Diffmogger was designed and tested with Codex running GPT-5.5. Other Codex models or non-Codex agent runtimes may work, but they have not been validated and may require prompt or workflow tuning. The templates are intentionally local-first and text-based so they can be adapted over time.

## Who This Is For

Diffmogger is a fit for:

- solo founders
- indie builders
- students
- lab engineers
- small teams
- people running ambitious recurring agent work on personal or small-team repos

Diffmogger is not a fit for teams that need enterprise autonomy infrastructure today. It does not provide RBAC, a formal audit pipeline, an SLO story, or a multi-user governance model. It is not appropriate for production autonomous deploys without additional review, compliance, release, and incident-response infrastructure.

## Core Idea

Diffmogger splits recurring agent work into stable instructions and mutable state:

- Stable prompt: durable recurring behavior.
- Static guardrails: constraints that should not churn every run.
- Dynamic task file: current state, checks, blockers, pending human requests, and next sprint.
- Verification: tests, builds, demos, screenshots, reports, or an honest note about what could not run.
- Lock files: reduce overlapping scheduled mutations of the same checkout.
- Worker helpers: bounded reports by default, integrated by the main agent.
- Human bridge: manual Markdown queues first, optional local notifier later.

The operating model is:

```text
stable automation prompt
+ static guardrails
+ dynamic Markdown task file
+ scheduled sprint runs
+ verification
+ lock files
+ optional bounded worker agents
+ optional decoupled human bridge
```

Generated target projects stay decoupled from Diffmogger. They use generated docs/prompts and, optionally, call a loopback notifier API. They should not import notifier code.

The status model is explicit and preserved across generated prompts:

```text
ACTIVE
ACTIVE_WITH_PENDING_USER_INPUT
BLOCKED_ON_USER
BLOCKED_ON_ENVIRONMENT
CRITICAL_STOP
```

## How This Is Different

| Compared with | Practical difference |
| --- | --- |
| `AGENTS.md`, `.cursorrules`, and static prompt files | Those are mostly static instructions. Diffmogger adds dynamic state plumbing: task file, inbox, archive, lock, compaction, worker reports, and validation. |
| Codex Automations and scheduled-run features | Those provide a scheduler. Diffmogger provides an operating model for making scheduled runs compound: externalized state, sprint sizing, status model, human bridge protocol, worker-agent conventions, verification, and backlog rewriting. |
| Interactive agents such as Cursor, Cline, and Aider | Those assume a human is in the loop every turn. Diffmogger targets unattended recurring runs where the agent must preserve state, verify, ask for unlocks asynchronously, and continue around blockers. |
| Agent frameworks such as LangGraph, CrewAI, AutoGen, and AutoGPT | Those are runtimes and frameworks. Diffmogger is a workflow scaffold layered on top of an existing CLI agent, with no new runtime lock-in. |
| Hosted autonomy tools | Hosted systems may hide state or bind users to a vendor workflow. Diffmogger is local-first, repo-local, and git-diffable. |

## What Is Novel Here

These are design choices, not claims of magic:

- Markdown-first state: agent state lives in repo-local Markdown files that can be reviewed, diffed, compacted, and resumed after context resets.
- Decoupled human bridge: the agent does not touch messaging credentials. Twilio, signature validation, and webhook hosting live in a separate service, while target projects interact through loopback HTTP and Markdown inbox/outbox files.
- Marker-enforced contracts: validation scripts assert that load-bearing prompt and template strings exist, so prose and code expectations do not silently drift.
- Explicit failure modes: the prompt names quiet recurring-agent failures such as under-scoping, doc-only work, ignoring "send me" requests, unbounded worker agents, and context bloat.

## What Diffmogger Creates

- automation prompt template
- guardrails template
- dynamic task file template
- bootstrap prompt
- autonomy experiment log
- human request, inbox, outbox, and archive templates
- validation scripts
- scaffold script
- lock scripts: `scripts/acquire_codex_lock.sh`, `scripts/release_codex_lock.sh`
- scheduled-run wrapper template: `scripts/run_codex_automation.sh`
- worker helper scripts: `scripts/spawn_worker_agent.sh`, `scripts/summarize_worker_outputs.py`
- state compaction script: `scripts/compact_agent_state.py`
- bundled local notifier service in `services/agentic-notifier/`

Repository layout:

```text
docs/                         Kit documentation.
prompts/                      Reusable prompts.
templates/                    Files scaffolded into target projects.
examples/                     Example intake briefs.
schemas/                      Reference JSON Schemas.
scripts/                      Validation, scaffolding, lock, worker, and compaction helpers.
services/agentic-notifier/    Reusable local SMS/WhatsApp bridge.
```

## Quickstart

Use a virtual environment for Python work. Homebrew Python may reject system-wide `pip` installs because of externally managed environment protections.

```bash
git clone https://github.com/harrisonpedrero/diffmogger.git Diffmogger
cd Diffmogger
bash scripts/validate_starter_kit.sh
```

Scaffold target docs:

```bash
python3 scripts/scaffold_project_docs.py \
  --intake examples/generic-web-app/project_intake.md \
  --target ../my-project

python3 scripts/check_required_files.py ../my-project
```

The scaffold includes target-local runtime scripts under `../my-project/scripts/`. Scheduled target-project runs should use those local scripts rather than depending on the Diffmogger checkout.

Then open `../my-project/docs/INITIAL_BOOTSTRAP_PROMPT.md` and use it for the first manual Codex bootstrap run. After the target repo has a runnable baseline, schedule `../my-project/scripts/run_codex_automation.sh` as the recurring Codex automation.

For a fuller first-project checklist, see `docs/FRESH_PROJECT_SETUP.md`.

## Validation

Run the full local validation:

```bash
bash scripts/validate_starter_kit.sh
```

Validation is intentionally marker- and smoke-test based. It checks that load-bearing files, markers, schemas, scaffold paths, and notifier tests are present and runnable. It does not prove semantic correctness, production safety, or that a generated automation will make good decisions.

Run a scaffold smoke test:

```bash
python3 scripts/scaffold_project_docs.py \
  --intake examples/generic-web-app/project_intake.md \
  --target /tmp/Diffmogger-smoke \
  --force

python3 scripts/check_required_files.py /tmp/Diffmogger-smoke
```

Run notifier tests:

```bash
cd services/agentic-notifier

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pytest
```

Tests use fake Twilio clients and dry-run paths. They do not require real credentials, ngrok, or real SMS.

## Worker Agents

Worker agents are bounded helpers. The main agent remains the integrator.

Use workers for independent review, architecture checks, test-gap analysis, risk review, product polish review, or isolated prototypes. Prefer read-only reports first.

Outputs go under:

```text
target/agent_runs/<run_id>/worker_<role>.md
```

Optional helpers:

```bash
export CODEX_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"

bash scripts/spawn_worker_agent.sh \
  --target ../my-project \
  --run-id "$CODEX_RUN_ID" \
  --role tests \
  --prompt "Inspect the current sprint for test gaps and write a concise report."

python3 scripts/summarize_worker_outputs.py ../my-project --run-id "$CODEX_RUN_ID"
```

The helpers use `codex exec --ephemeral` when available, avoid network, tell workers not to spawn more workers, and fail gracefully if the Codex CLI is unavailable. They are optional convenience scripts, not mandatory magic.

Codex CLI must be available for `codex exec` helpers:

```bash
command -v codex
```

## Human Bridge

Diffmogger supports two modes.

Mode A: manual file-only bridge.

- Target automation writes requests to `docs/HUMAN_REQUESTS.md`.
- The human manually replies in `docs/HUMAN_INBOX.md`.
- The next automation run consumes handled replies, removes them from the inbox, and archives concise notes in `docs/HUMAN_RESPONSES_ARCHIVE.md`.

This mode needs no SMS, no webhook, and no credentials. It is a valid long-term mode.

In file-only mode, status or summary requests are satisfied locally in Markdown or app artifacts. The automation should not try to send SMS/WhatsApp unless the project is explicitly switched to notifier mode.

Mode B: local notifier API.

- Target project calls `POST http://127.0.0.1:8765/api/notify`.
- `services/agentic-notifier` owns Twilio credentials.
- Twilio inbound webhook goes to `http://127.0.0.1:8787/twilio/inbound` through ngrok.
- The notifier writes replies to target `docs/HUMAN_INBOX.md`.
- Target automation resolves and archives handled replies.

Notifier provider failures return structured JSON and write `PROVIDER_SEND_FAILED` to `docs/HUMAN_OUTBOX.md` when target paths are configured. If the notifier API itself is unreachable, target automations should record `NOTIFIER_UNREACHABLE` and keep working where possible.

## Notifier Setup

Use a virtual environment. Do not install packages into Homebrew/system Python; a venv avoids externally managed environment errors on modern macOS Python setups.

```bash
cd services/agentic-notifier

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

cp .env.example .env
python -m pytest
python -m agentic_notifier.run_service
```

Real Twilio values belong only in `services/agentic-notifier/.env`. Keep secrets out of target project docs, prompts, task files, and examples.

Expose only the webhook port with ngrok:

```bash
ngrok http 8787
```

Do not expose the local notify API unless you know why.

Practical SMS notes:

- `TWILIO_MESSAGING_SERVICE_SID` is supported.
- If set, the notifier sends with `messaging_service_sid` and does not pass `from_`.
- If absent, the notifier falls back to `TWILIO_FROM`.
- SMS via +1 10DLC may require A2P 10DLC approval.
- Twilio error `30034` usually means the sender or campaign is not registered or ready.
- WhatsApp sandbox can be used as an alternative if configured.
- Diffmogger does not require SMS to work.

## Lock Files And State Compaction

Short cadences need lock behavior. Generated target repos include `scripts/run_codex_automation.sh`, which wraps lock acquire/release around `codex exec`:

```bash
bash scripts/run_codex_automation.sh
```

Default path:

```text
target/codex_automation.lock
```

The wrapper sets `CODEX_LOCK_ALREADY_ACQUIRED=true` so the automation prompt does not acquire a second lock. Set `TARGET=/absolute/path/to/target-project` when running from outside the target repo. The lock includes PID, timestamp, run id, host, stale threshold, and context. Stale detection defaults to 4 hours and can be tuned with `CODEX_LOCK_STALE_SECONDS`.

Lock scripts reduce overlapping-run risk. They do not remove the need to review diffs.

Long-running Markdown state can become context bloat. Diffmogger includes:

```bash
python3 scripts/compact_agent_state.py --dry-run ../my-project
python3 scripts/compact_agent_state.py ../my-project
```

It supports:

- `docs/HUMAN_INBOX.md`
- `docs/HUMAN_REQUESTS.md`
- `docs/HUMAN_OUTBOX.md`
- `docs/HUMAN_RESPONSES_ARCHIVE.md`
- `docs/CODEX_AUTOMATION_TASKS.md`
- `docs/AUTONOMY_EXPERIMENT_LOG.md`
- `docs/DAILY_AUTOMATION_REVIEW.md`

The script preserves unresolved human requests, keeps recent useful state, and archives concise rollups instead of silently deleting active data. Review the diff after compaction.

## Safety Defaults

- no secrets in prompts, task files, inboxes, or examples
- target automations should not read `.env`
- no spending, public publishing, deployment, messaging real users, or external side effects without approval
- integrations mocked, optional, or dry-run by default
- human bridge credentials stay in the notifier service, not product repos
- review diffs before trusting autonomous changes
- increase autonomy only after early runs produce useful, verifiable changes

## What It Is Not

- not production-ready autonomy infrastructure
- not enterprise autonomy infrastructure
- not a secret manager
- not a replacement for human review
- not a guarantee that agents make good decisions
- not a way to bypass platform rules
- not a deployment or incident-response system
- not appropriate for unsafe real-world side effects without review

## Known Limitations

- alpha and local-first
- Codex behavior can vary
- scheduled runs still need review
- Twilio/A2P setup can block SMS
- JSON schemas may be reference-only where runtime enforcement is not wired yet
- state compaction should be reviewed
- worker agents can create noise if overused
- Diffmogger has not been validated across other coding models or non-Codex agent runtimes
- no RBAC, formal audit pipeline, SLO story, or multi-user governance model

## Roadmap

- stronger schema/runtime alignment
- better worker output consolidation
- better state compaction
- example target projects
- richer case studies
- local dashboard for automation state
- more notifier channels such as Slack, email, and Discord

## Example Validation

Diffmogger includes fictional example intakes that exercise the generated automation workflow without binding the kit to one product domain.

Use `examples/generic-web-app/` for a straightforward product brief and `examples/trendlab-signal-intelligence/` for a more involved signal-intelligence brief with fixture data, scoring, reports, and human-in-the-loop requests.

## Schemas And Runtime

`schemas/` contains reference JSON Schemas for intake, automation state, and human bridge payloads. For the notifier API, the runtime Pydantic model in `services/agentic-notifier/agentic_notifier/models.py` is authoritative. A notifier test checks `schemas/human_request.schema.json` against that model so field drift is visible.

Known gap: not every schema is fully enforced at runtime yet. The roadmap includes stronger schema/runtime alignment.

## License

Diffmogger is released under the MIT License. See `LICENSE`.
