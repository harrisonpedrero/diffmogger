#!/usr/bin/env python3
"""Scaffold generic automation docs into a target project from an intake file."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
KIT_ROOT = SCRIPT_DIR.parent
TEMPLATE_ROOT = KIT_ROOT / "templates"
HUMAN_BRIDGE_FILES = {
    "docs/HUMAN_REQUESTS.md",
    "docs/HUMAN_INBOX.md",
    "docs/HUMAN_OUTBOX.md",
    "docs/HUMAN_RESPONSES_ARCHIVE.md",
    "docs/HUMAN_BRIDGE_SETUP.md",
}
AUTOMATION_SIGNAL_FILES = {
    "docs/AUTOMATION_SIGNALS.md",
}
VALID_HUMAN_BRIDGE_MODES = {"disabled", "file_only", "local_notifier"}
VALID_PROJECT_MODES = {"fresh_project", "existing_project"}
MAX_WRITE_WORKER_COUNT = 10
DEFAULT_MAX_WRITE_WORKER_COUNT = 3
VALID_ROLE_PROFILES = {"single_lane", "planner_builder_hardener_integrator"}
VALID_SCHEDULE_STRATEGIES = {"single_lane_interval", "fixed_multi_role", "continuous_conveyor"}
DEFAULT_MULTI_ROLE_CADENCE_MINUTES = 30
MULTI_ROLE_FILES = {
    ".agentic/roles/planner.md",
    ".agentic/roles/builder.md",
    ".agentic/roles/hardener.md",
    ".agentic/roles/integrator.md",
    "docs/MULTI_ROLE_PROGRESS.md",
    "scripts/run_role_automation.sh",
    "scripts/integrate_role_outputs.py",
    "scripts/list_deferred_patches.py",
}
MANAGED_EXISTING_PROJECT_FILES = {
    "AGENTS.md": "AGENTS",
    "docs/DEVELOPMENT.md": "DEVELOPMENT",
}


HEADING_TO_KEY = {
    "summary": "summary",
    "project mode": "project_mode",
    "project type": "project_mode",
    "target project mode": "project_mode",
    "product goal": "product_goal",
    "target user": "target_user",
    "desired first demo": "desired_first_demo",
    "tech preferences": "tech_preferences",
    "constraints": "hard_constraints",
    "hard constraints": "hard_constraints",
    "safety rules": "safety_constraints",
    "safety constraints": "safety_constraints",
    "automation must never do": "automation_must_never_do",
    "must never do": "automation_must_never_do",
    "external services": "external_services",
    "additional context": "additional_context_files",
    "additional context files": "additional_context_files",
    "context files": "additional_context_files",
    "verification": "verification_commands",
    "automation cadence": "desired_cadence",
    "desired cadence": "desired_cadence",
    "human bridge": "human_bridge_enabled",
    "human bridge mode": "human_bridge_mode",
    "human requested text responses": "human_requested_text_responses",
    "worker agents": "worker_agents_allowed",
    "codex cli workers": "codex_cli_workers_expected_on_broad_runs",
    "write worker agents": "write_worker_agents_allowed",
    "write-capable worker agents": "write_worker_agents_allowed",
    "bounded write workers": "write_worker_agents_allowed",
    "bounded write worker agents": "write_worker_agents_allowed",
    "max write workers": "max_write_worker_count",
    "maximum write workers": "max_write_worker_count",
    "max write worker count": "max_write_worker_count",
    "maximum write worker count": "max_write_worker_count",
    "write worker guidance": "write_worker_guidance",
    "write-worker guidance": "write_worker_guidance",
    "multi-role automations": "multi_role_automations_allowed",
    "multi role automations": "multi_role_automations_allowed",
    "multi-role automation": "multi_role_automations_allowed",
    "multi role automation": "multi_role_automations_allowed",
    "automation role profile": "automation_role_profile",
    "role profile": "automation_role_profile",
    "automation checkpoint commits": "automation_checkpoint_commits",
    "checkpoint commits": "automation_checkpoint_commits",
    "multi-role base cadence": "multi_role_base_cadence_minutes",
    "multi role base cadence": "multi_role_base_cadence_minutes",
    "multi-role cadence": "multi_role_base_cadence_minutes",
    "multi role cadence": "multi_role_base_cadence_minutes",
    "automation schedule strategy": "automation_schedule_strategy",
    "schedule strategy": "automation_schedule_strategy",
    "scheduling strategy": "automation_schedule_strategy",
    "multi-role allow remotes": "multi_role_allow_remotes",
    "multi role allow remotes": "multi_role_allow_remotes",
    "allow multi-role remotes": "multi_role_allow_remotes",
    "allow multi role remotes": "multi_role_allow_remotes",
    "automation signals": "automation_signals_enabled",
    "automation pulse": "automation_signals_enabled",
    "automation pulses": "automation_signals_enabled",
    "automation signal system": "automation_signals_enabled",
    "meaningful deliverable": "meaningful_deliverable",
    "beyond mvp": "beyond_mvp",
    "assumptions": "assumptions",
}


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "new-project"


def normalize_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"yes", "true", "enabled", "allow", "allowed", "on"}:
        return True
    if text in {"no", "false", "disabled", "disallow", "off"}:
        return False
    if any(word in text for word in ["enabled", "allowed", "yes", "true"]):
        return True
    if any(word in text for word in ["disabled", "not allowed", "no", "false"]):
        return False
    return default


def normalize_lines(value: Any, fallback: str) -> str:
    if value is None:
        return fallback
    if isinstance(value, list):
        return "\n".join(f"- {item}" for item in value) or fallback
    text = str(value).strip()
    return text or fallback


def normalize_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if value is None:
        return default
    match = re.search(r"-?\d+", str(value))
    if not match:
        return default
    return int(match.group(0))


def normalize_write_worker_count(value: Any, enabled: bool) -> int:
    if not enabled:
        return 0
    count = normalize_int(value, DEFAULT_MAX_WRITE_WORKER_COUNT)
    return max(1, min(MAX_WRITE_WORKER_COUNT, count))


def normalize_role_profile(value: Any, multi_role_enabled: bool) -> str:
    if not multi_role_enabled:
        return "single_lane"
    text = str(value or "planner_builder_hardener_integrator").strip().lower()
    text = text.replace("-", "_").replace(" ", "_")
    if text in VALID_ROLE_PROFILES:
        return text
    return "planner_builder_hardener_integrator"


def normalize_multi_role_cadence(value: Any) -> int:
    return max(30, normalize_int(value, DEFAULT_MULTI_ROLE_CADENCE_MINUTES))


def normalize_schedule_strategy(value: Any, multi_role_enabled: bool) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not text:
        return "fixed_multi_role" if multi_role_enabled else "single_lane_interval"
    if text in VALID_SCHEDULE_STRATEGIES:
        return text
    if any(term in text for term in ("conveyor", "continuous", "work_conserving", "workconserving")):
        return "continuous_conveyor"
    if any(term in text for term in ("fixed", "staggered", "calendar", "role")):
        return "fixed_multi_role"
    if any(term in text for term in ("single", "interval", "periodic", "cadence")):
        return "single_lane_interval"
    return "fixed_multi_role" if multi_role_enabled else "single_lane_interval"


def normalize_mode(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    if text in VALID_HUMAN_BRIDGE_MODES:
        return text
    return None


def human_bridge_mode(data: dict[str, Any]) -> str:
    explicit = normalize_mode(data.get("human_bridge_mode"))
    if explicit:
        return explicit

    bridge_text = " ".join(
        str(data.get(key) or "")
        for key in ("human_bridge_enabled", "human_bridge_mode")
    ).lower()
    if any(term in bridge_text for term in ("disabled", "off", "no human", "none")):
        return "disabled"
    if "file" in bridge_text or "manual" in bridge_text:
        return "file_only"
    if "notifier" in bridge_text or "sms" in bridge_text or "whatsapp" in bridge_text:
        return "local_notifier"
    if normalize_bool(data.get("human_bridge_enabled"), False):
        return "file_only"
    return "disabled"


def project_mode(data: dict[str, Any]) -> str:
    raw = str(data.get("project_mode") or data.get("project_type") or "").strip().lower()
    text = raw.replace("-", "_").replace(" ", "_")
    if text in VALID_PROJECT_MODES:
        return text
    if any(term in text for term in ("existing", "integrat", "retrofit", "current_repo", "current")):
        return "existing_project"
    return "fresh_project"


def project_mode_label(mode: str) -> str:
    return "Existing project integration" if mode == "existing_project" else "Fresh project"


def project_mode_guidance(mode: str) -> str:
    if mode == "existing_project":
        return (
            "Integrate Diffmogger into the selected existing project. Preserve the existing "
            "architecture, package manager, tests, docs, and project-specific instructions unless "
            "the intake explicitly asks for a scoped change. Treat the desired first demo as an "
            "integrated increment inside the current codebase, not a greenfield rewrite."
        )
    return (
        "Create a new target project from the intake. Choose simple local-first defaults, create "
        "the initial repo structure, and document setup and verification as part of bootstrap."
    )


def bridge_values(mode: str, text_responses: bool) -> dict[str, str]:
    enabled = mode != "disabled"
    file_reads = ""
    if enabled:
        file_reads = """docs/HUMAN_REQUESTS.md
docs/HUMAN_INBOX.md
docs/HUMAN_OUTBOX.md
docs/HUMAN_RESPONSES_ARCHIVE.md"""

    if mode == "local_notifier":
        agents_read = """If human bridge files exist, also read:

```text
docs/HUMAN_REQUESTS.md
docs/HUMAN_INBOX.md
docs/HUMAN_OUTBOX.md
docs/HUMAN_RESPONSES_ARCHIVE.md
```"""
        agents_rules = """- Process human inbox messages, including freeform commands.
- If the human asks to be texted, messaged, or sent a status update, use the local notifier when available instead of only writing Markdown.
- Process handled human inbox messages only after completing or intentionally deferring the requested action, then archive concise notes."""
        run_steps = """1. Classify and handle new human inbox messages, including freeform commands.
1. If a human message asks to be texted, messaged, or sent a summary/status update, send a concise SMS/WhatsApp response through the local notifier service; do not merely write a local Markdown summary.
1. Resolve any handled human replies from `docs/HUMAN_INBOX.md`.
1. Remove handled messages from `docs/HUMAN_INBOX.md` only after the requested action has actually been completed or intentionally deferred.
1. Archive concise notes to `docs/HUMAN_RESPONSES_ARCHIVE.md`."""
        protocol = """Human bridge enabled: true

Human bridge mode: `local_notifier`

Use the human owner as an asynchronous resource for manual unlocks and high-leverage direction, not as an implementation worker.

This project may use a separate local notifier service if it is running:

```text
POST http://127.0.0.1:8765/api/notify
```

The notifier owns SMS/WhatsApp credentials, Twilio webhook handling, and reply writing. This target project must not inspect, clone, import, or modify the notifier service during normal automation runs. This project must not handle messaging credentials.

### Human Inbox Interpretation

At the beginning of every run, read `docs/HUMAN_INBOX.md`.

Human inbox entries can be structured replies such as `HR-001 DONE` or freeform instructions such as `send me a summary of what you've accomplished so far`. Interpret natural language intent; do not treat every freeform message as a request to create a local file.

If the human says any of the following, the expected behavior is to send a text message through the local notifier service:

- `send me ...`
- `text me ...`
- `message me ...`
- `reply with ...`
- `give me a quick summary`
- `what have you done so far?`
- `summarize progress`
- `status update`
- `how is it going?`

For those requests, create a concise phone-friendly response and send it via `POST http://127.0.0.1:8765/api/notify`. Do not satisfy a `send me` request only by writing a local Markdown file. You may also update local docs, but the primary requested action is outbound messaging.

If the human explicitly asks for a local document, report, Markdown file, artifact, or dashboard page, create the local artifact. Text only if the human also asked for a text response.

### Outbound Text Style

SMS/WhatsApp responses should be concise but useful:

- target 300-900 characters
- maximum 5 short bullets
- no long reports
- no raw stack traces unless urgently needed
- no embedded URLs unless explicitly necessary and allowed by the messaging setup
- no secrets or sensitive environment details

Default summary shape:

```text
{{PROJECT_NAME}} update: Built X, Y, Z. Checks passing: A/B/C. Current blocker: none / one-line blocker. Next sprint: <short next task>. Full details are in docs/CODEX_AUTOMATION_TASKS.md.
```

When input is needed:

1. Create or update `docs/HUMAN_REQUESTS.md`.
2. Include request id, type, priority, context, recommendation, minimum action, reply format, and dedupe key.
3. If the local notifier is running, call `POST http://127.0.0.1:8765/api/notify`.
4. If the notifier is unavailable or rejects the request, fall back to writing/updating `docs/HUMAN_REQUESTS.md` and continue.
5. Continue other useful work in the same run.
6. Use `ACTIVE_WITH_PENDING_USER_INPUT` when work can continue and `BLOCKED_ON_USER` only when it cannot.

Payload shape for direct human-requested outbound responses, if the notifier supports `message_body`:

```json
{
  "request_id": "MSG-YYYY-MM-DD-001",
  "type": "human_requested_summary",
  "priority": "normal",
  "summary": "Progress summary requested by human",
  "message_body": "{{PROJECT_NAME}} update: <concise summary body>",
  "agent_recommendation": "No action needed unless you want to review the generated artifacts.",
  "minimum_user_action": "None.",
  "reply_format": "Optional: reply with a follow-up request.",
  "unblocked_work_remaining": ["Continue current automation sprint"],
  "dedupe_key": "MSG-YYYY-MM-DD-001:v1",
  "expects_reply": false
}
```

If the notifier is not reachable:

1. Do not claim a text was sent.
2. Write the intended outbound message to `docs/HUMAN_OUTBOX.md` with status `NOTIFIER_UNREACHABLE`.
3. Keep or annotate the inbox entry as unresolved if a response is required.
4. Continue useful offline/product work.
5. Set status to `ACTIVE_WITH_PENDING_USER_INPUT` only if the unresolved item matters and useful work remains."""
        guardrails = """- Ask the human only for meaningful unlocks.
- For reversible choices, choose a safe default and document it.
- Use `ACTIVE_WITH_PENDING_USER_INPUT` when work can continue around a pending request.
- Use `POST http://127.0.0.1:8765/api/notify` when the local notifier is available; otherwise fall back to `docs/HUMAN_REQUESTS.md`.
- The notifier owns messaging credentials. This repo must not import notifier code or read notifier `.env` files.
- If the human asks to be texted, messaged, or sent a summary/status update, send a concise SMS/WhatsApp response through the notifier rather than only writing Markdown.
- If the notifier is unreachable, do not claim a text was sent. Record `NOTIFIER_UNREACHABLE` in `docs/HUMAN_OUTBOX.md` and continue useful work.
- Remove handled entries from `docs/HUMAN_INBOX.md` only after the requested action is complete or intentionally deferred, and archive concise notes in `docs/HUMAN_RESPONSES_ARCHIVE.md`."""
        task_notes = """Human bridge mode: `local_notifier`

- The automation must read `docs/HUMAN_INBOX.md` at run start, interpret structured replies and freeform commands, remove handled entries only after completion or intentional deferral, and archive concise notes in `docs/HUMAN_RESPONSES_ARCHIVE.md`.
- If the local notifier is running, this project may call `POST http://127.0.0.1:8765/api/notify`.
- If a human asks to be texted, messaged, or sent a status update, the automation should use the local notifier rather than only writing Markdown.
- If the notifier is unavailable, record the intended outbound message in `docs/HUMAN_OUTBOX.md` with status `NOTIFIER_UNREACHABLE` and continue useful work."""
        inbox = """# Human Inbox

Active inbox for replies from the human owner.

The separate local notifier service may write inbound SMS/WhatsApp replies here. The human may also paste replies here manually.

At the start of every automation run, Codex should:

1. read this file
2. handle any `status: unhandled` messages, including structured replies and freeform commands
3. update related requests in `docs/HUMAN_REQUESTS.md`
4. send a notifier response if the human asked to be texted, messaged, or sent a status update
5. remove handled messages from this file only after the requested action is complete or intentionally deferred
6. append concise records to `docs/HUMAN_RESPONSES_ARCHIVE.md`

Freeform messages such as `send me a summary`, `text me the blockers`, `status update`, or `what have you done so far?` should result in a concise SMS/WhatsApp response through `POST http://127.0.0.1:8765/api/notify` when the notifier is available. Do not satisfy those messages only by writing local Markdown.

If the notifier is unavailable, record the attempted outbound response in `docs/HUMAN_OUTBOX.md` with status `NOTIFIER_UNREACHABLE`.

Keep this file short. It is not a permanent log.

## Active Inbound Messages

None.

## Entry Template

```markdown
### INBOX-YYYY-MM-DD-001

- received_at: YYYY-MM-DDTHH:MM:SS
- channel: sms
- from: +15555555555
- request_id: HR-YYYY-MM-DD-001
- parsed_intent: done
- message_sid: SMxxxxxxxxxxxxxxxx
- status: unhandled

#### Body

HR-001 DONE. Key added locally.
```"""
        outbox = """# Human Outbox

Lightweight audit log of outbound human requests sent or attempted through the local notifier service.

Use this file for:

- human-unlock requests sent through the notifier
- direct status/update responses sent because the human asked to be texted
- failed notifier attempts with status `NOTIFIER_UNREACHABLE`

Do not write secrets, raw stack traces, or long reports here.

## Outbound Notifications

None yet.

## Entry Template

```markdown
### OUTBOX-YYYY-MM-DD-001

- sent_at: YYYY-MM-DDTHH:MM:SS
- request_id: MSG-YYYY-MM-DD-001
- type: human_requested_summary
- status: sent | dry_run | NOTIFIER_UNREACHABLE
- dedupe_key: MSG-YYYY-MM-DD-001:v1

#### Message

Concise phone-friendly message body.
```"""
        setup = """# Human Bridge Setup

This project uses local notifier mode.

## Local Diffmogger Notifier Mode

Advanced users may run Diffmogger's bundled local notifier service separately:

```text
services/agentic-notifier/
```

Project automation calls:

```text
POST http://127.0.0.1:8765/api/notify
```

The notifier sends SMS/WhatsApp through Twilio and writes replies to this target project file:

```text
docs/HUMAN_INBOX.md
```

The notifier owns credentials, dedupe state, optional JSONL queues, and external webhooks. This repo must not read notifier `.env` files or handle Twilio credentials.

The target automation must read `docs/HUMAN_INBOX.md` at the start of each run, remove handled inbox entries, and archive concise resolution notes in `docs/HUMAN_RESPONSES_ARCHIVE.md`.

If a human inbox message asks the automation to `send me`, `text me`, `message me`, `reply with`, provide a `status update`, or summarize progress, the target automation should send a concise SMS/WhatsApp response through the notifier. It should not satisfy that request only by writing Markdown.

If the notifier is unavailable, the automation must not claim a text was sent. It should write the intended outbound message to `docs/HUMAN_OUTBOX.md` with status `NOTIFIER_UNREACHABLE`, keep unresolved inbox entries active when needed, and continue safe work.

Twilio sender notes:

- Prefer `TWILIO_MESSAGING_SERVICE_SID` when using a Twilio Messaging Service; the notifier will send with `messaging_service_sid` and omit `TWILIO_FROM`.
- If no Messaging Service SID is configured, the notifier falls back to `TWILIO_FROM`.
- SMS via +1 10DLC may require A2P 10DLC approval before outbound messages work.
- Twilio error `30034` usually means the sender or A2P campaign is not registered or ready.
- WhatsApp sandbox can be used instead of SMS when configured.

## Inbox Handling Rules

- Treat `docs/HUMAN_INBOX.md` as an active queue, not a permanent log.
- Handle structured replies such as `HR-001 DONE` and freeform commands.
- Remove handled inbox entries only after the requested action is complete or intentionally deferred.
- Archive concise resolution notes in `docs/HUMAN_RESPONSES_ARCHIVE.md`.
- Record outbound messages and notifier failures in `docs/HUMAN_OUTBOX.md`.

## Notifier Safety

- Bind local notify API to `127.0.0.1`.
- Expose only the inbound webhook receiver through ngrok or another tunnel.
- Do not expose `http://127.0.0.1:8765/api/notify` through ngrok.
- Validate Twilio webhook signatures with the official SDK.
- Dedupe outbound requests and inbound webhook retries.
- Support dry-run mode."""
    elif mode == "file_only":
        agents_read = """If human bridge files exist, also read:

```text
docs/HUMAN_REQUESTS.md
docs/HUMAN_INBOX.md
docs/HUMAN_OUTBOX.md
docs/HUMAN_RESPONSES_ARCHIVE.md
```"""
        agents_rules = """- Process human inbox messages, including freeform commands.
- If the human asks for a summary, status update, explanation, or report, satisfy it locally in Markdown or app artifacts.
- Do not use SMS, WhatsApp, Twilio, or notifier APIs unless the human explicitly changes bridge mode.
- Process handled human inbox messages only after completing or intentionally deferring the requested action, then archive concise notes."""
        run_steps = """1. Classify and handle new human inbox messages, including freeform commands.
1. Resolve any handled human replies from `docs/HUMAN_INBOX.md`.
1. Remove handled messages from `docs/HUMAN_INBOX.md` only after the requested action has actually been completed or intentionally deferred.
1. Archive concise notes to `docs/HUMAN_RESPONSES_ARCHIVE.md`."""
        protocol = """Human bridge enabled: true

Human bridge mode: `file_only`

Use file-only human intervention. Do not use SMS, WhatsApp, Twilio, or the local notifier service for this project unless the human explicitly changes the bridge mode later.

The human owner will periodically inspect `docs/HUMAN_REQUESTS.md`, perform any manual action, and reply in `docs/HUMAN_INBOX.md`.

Use the human owner as an asynchronous resource for manual unlocks and high-leverage direction, not as an implementation worker.

### Human Inbox Interpretation

At the beginning of every run, read `docs/HUMAN_INBOX.md`.

Human inbox entries can be structured replies such as `HR-001 DONE` or freeform instructions such as `try a different direction` or `focus on real data next`. Interpret natural language intent.

If the human asks for a summary, status update, explanation, local report, or decision record, satisfy that request locally by updating the relevant Markdown file or app artifact. Do not attempt to send a text message.

After handling an inbox entry:

1. Complete or intentionally defer the requested action.
2. Archive a concise note in `docs/HUMAN_RESPONSES_ARCHIVE.md`.
3. Remove the handled entry from `docs/HUMAN_INBOX.md`.
4. Note the resolved message in `docs/CODEX_AUTOMATION_TASKS.md`.

If the inbox entry cannot be resolved yet, leave it in `docs/HUMAN_INBOX.md` with a brief annotation or carry it forward in `docs/CODEX_AUTOMATION_TASKS.md`.

### Human Requests

When input is needed:

1. Create or update `docs/HUMAN_REQUESTS.md`.
2. Include request id, type, priority, context, recommendation, minimum action, reply format, and dedupe key.
3. Continue other useful work in the same run.
4. Use `ACTIVE_WITH_PENDING_USER_INPUT` when work can continue and `BLOCKED_ON_USER` only when it cannot."""
        guardrails = """- Ask the human only for meaningful unlocks.
- For reversible choices, choose a safe default and document it.
- Use `ACTIVE_WITH_PENDING_USER_INPUT` when work can continue around a pending request.
- Use file-only handoff files: write requests to `docs/HUMAN_REQUESTS.md`, read replies from `docs/HUMAN_INBOX.md`, and archive handled replies in `docs/HUMAN_RESPONSES_ARCHIVE.md`.
- Do not use SMS, WhatsApp, Twilio, or notifier APIs unless the human explicitly changes the bridge mode.
- If the human asks for a summary or status update, answer locally in the requested Markdown/app artifact.
- Remove handled entries from `docs/HUMAN_INBOX.md` only after the requested action is complete or intentionally deferred."""
        task_notes = """Human bridge mode: `file_only`

- The automation must read `docs/HUMAN_INBOX.md` at run start, interpret structured replies and freeform commands, remove handled entries only after completion or intentional deferral, and archive concise notes in `docs/HUMAN_RESPONSES_ARCHIVE.md`.
- The human manually inspects `docs/HUMAN_REQUESTS.md` and replies in `docs/HUMAN_INBOX.md`.
- Do not use SMS, WhatsApp, Twilio, or notifier APIs in this mode."""
        inbox = """# Human Inbox

Active inbox for replies from the human owner.

In file-only mode, the human manually pastes replies here after reading `docs/HUMAN_REQUESTS.md`.

At the start of every automation run, Codex should:

1. read this file
2. handle any `status: unhandled` messages, including structured replies and freeform commands
3. update related requests in `docs/HUMAN_REQUESTS.md`
4. satisfy summary/status/report requests locally in Markdown or app artifacts
5. remove handled messages from this file only after the requested action is complete or intentionally deferred
6. append concise records to `docs/HUMAN_RESPONSES_ARCHIVE.md`

Do not use SMS, WhatsApp, Twilio, or notifier APIs in file-only mode.

Keep this file short. It is not a permanent log.

## Active Inbound Messages

None.

## Entry Template

```markdown
### INBOX-YYYY-MM-DD-001

- received_at: YYYY-MM-DDTHH:MM:SS
- channel: manual
- request_id: HR-YYYY-MM-DD-001
- parsed_intent: done
- status: unhandled

#### Body

HR-001 DONE. Key added locally.
```"""
        outbox = """# Human Outbox

File-only audit log of local outbound human-facing notes.

Use this file for concise records of local status summaries, request notices, or artifacts produced because the human asked for an update. Do not use it as an SMS/WhatsApp delivery log in file-only mode.

Do not write secrets, raw stack traces, or long reports here.

## Outbound Records

None yet.

## Entry Template

```markdown
### OUTBOX-YYYY-MM-DD-001

- created_at: YYYY-MM-DDTHH:MM:SS
- request_id: MSG-YYYY-MM-DD-001
- type: human_requested_summary
- status: local_record
- dedupe_key: MSG-YYYY-MM-DD-001:v1

#### Message

Concise local summary or pointer to the generated artifact.
```"""
        setup = """# Human Bridge Setup

This project uses file-only human intervention.

## Local-File-Only Mode

Files:

```text
docs/HUMAN_REQUESTS.md
docs/HUMAN_INBOX.md
docs/HUMAN_OUTBOX.md
docs/HUMAN_RESPONSES_ARCHIVE.md
```

The automation writes active requests to `docs/HUMAN_REQUESTS.md`. The human manually replies in `docs/HUMAN_INBOX.md`. The next run consumes handled replies and archives concise notes.

No SMS, WhatsApp, Twilio, webhook, ngrok, notifier API, or messaging credentials are used in this mode.

If a human inbox message asks for a summary, status update, report, explanation, or decision record, the automation should satisfy it locally by updating the relevant Markdown file or app artifact.

## Inbox Handling Rules

- Treat `docs/HUMAN_INBOX.md` as an active queue, not a permanent log.
- Handle structured replies such as `HR-001 DONE` and freeform commands.
- Remove handled inbox entries only after the requested action is complete or intentionally deferred.
- Archive concise resolution notes in `docs/HUMAN_RESPONSES_ARCHIVE.md`.
- Keep active inbox files short.
"""
    else:
        agents_read = "Human bridge files are not required unless the human later enables the bridge."
        agents_rules = "- Human bridge is disabled; do not create human request queues unless the human later enables the bridge."
        run_steps = "1. Skip human inbox processing because the human bridge is disabled for this project."
        protocol = """Human bridge enabled: false

Human bridge mode: `disabled`

Do not create human requests or wait for human replies during normal automation runs. If work becomes unsafe or impossible without the human, record the blocker in `docs/CODEX_AUTOMATION_TASKS.md` and use `BLOCKED_ON_USER` only when no useful work can continue."""
        guardrails = """- Human bridge is disabled.
- Do not create human request queues during normal runs.
- For reversible choices, choose a safe default and document it.
- Use `BLOCKED_ON_USER` only when no valuable work can continue without the human."""
        task_notes = "Human bridge mode: `disabled`. No human request queue is active."
        inbox = "# Human Inbox\n\nHuman bridge disabled for this project.\n"
        outbox = "# Human Outbox\n\nHuman bridge disabled for this project.\n"
        setup = "# Human Bridge Setup\n\nHuman bridge disabled for this project.\n"

    end_requirements = "- human requests created or resolved\n"
    if mode == "local_notifier":
        end_requirements += "- human messages sent, including whether notifier delivery succeeded, failed, or was unavailable\n"
    elif mode == "file_only":
        end_requirements += "- human inbox messages handled and local response artifacts created\n"
    else:
        end_requirements = ""

    development = f"""Human bridge enabled: {str(enabled).lower()}

Human bridge mode: `{mode}`

{('The human reads `docs/HUMAN_REQUESTS.md` and replies in `docs/HUMAN_INBOX.md`. The automation handles replies on later runs and archives them in `docs/HUMAN_RESPONSES_ARCHIVE.md`.' if mode == 'file_only' else 'The project may call `POST http://127.0.0.1:8765/api/notify` when the local notifier service is running. Keep notifier credentials outside this repo.' if mode == 'local_notifier' else 'No human bridge files are required for normal runs.')}
"""

    bootstrap = f"""Human bridge enabled: {str(enabled).lower()}

Human bridge mode: `{mode}`

{('Use file-only mode. Create project-side human bridge files and do not use SMS, WhatsApp, Twilio, or notifier APIs unless the human explicitly changes mode later.' if mode == 'file_only' else 'Use local notifier mode. This repo may call `POST http://127.0.0.1:8765/api/notify` when the separate notifier service is running, but must not handle messaging credentials.' if mode == 'local_notifier' else 'Human bridge disabled. Do not create human request queues unless the human later enables the bridge.')}
"""

    return {
        "HUMAN_BRIDGE_ENABLED": str(enabled).lower(),
        "HUMAN_BRIDGE_MODE": mode,
        "HUMAN_FILE_READS": file_reads,
        "HUMAN_AGENTS_READ_BLOCK": agents_read,
        "HUMAN_AGENTS_RULES": agents_rules,
        "HUMAN_RUN_STEPS": run_steps,
        "HUMAN_PROTOCOL": protocol,
        "HUMAN_GUARDRAILS_POLICY": guardrails,
        "HUMAN_TASK_NOTES": task_notes,
        "HUMAN_INBOX_CONTENT": inbox,
        "HUMAN_OUTBOX_CONTENT": outbox,
        "HUMAN_BRIDGE_SETUP_CONTENT": setup,
        "HUMAN_END_REQUIREMENTS": end_requirements.rstrip(),
        "HUMAN_DEVELOPMENT_SECTION": development.strip(),
        "HUMAN_BOOTSTRAP_SECTION": bootstrap.strip(),
        "HUMAN_REQUESTED_TEXT_RESPONSES": str(text_responses).lower(),
    }


def worker_values(data: dict[str, Any]) -> dict[str, str]:
    workers_allowed = normalize_bool(data.get("worker_agents_allowed"), True)
    codex_workers_expected = normalize_bool(
        data.get("codex_cli_workers_expected_on_broad_runs"),
        True,
    )
    write_workers_enabled = workers_allowed and normalize_bool(
        data.get("write_worker_agents_allowed"),
        False,
    )
    max_write_workers = normalize_write_worker_count(
        data.get("max_write_worker_count"),
        write_workers_enabled,
    )
    guidance = normalize_lines(
        data.get("write_worker_guidance"),
        (
            "Use the most parallelism the task can safely absorb. Write workers are "
            "optional acceleration for broad work with reviewable ownership boundaries; "
            "keep coordination lightweight and let the main agent integrate and verify."
        ),
    )

    if write_workers_enabled:
        orchestration = f"""Write-worker guidance:

{guidance}

Write workers are optional, never mandatory, and should be used as bounded acceleration. Default to the most useful parallelism the task can safely absorb: no workers for tiny or tightly coupled changes, a few workers for normal multi-surface work, and up to {max_write_workers} workers for broad implementation, audit, hardening, observability, docs, examples, validation, or competing prototype lanes.

The goal is to maximize validated useful diff per unit time while preserving local-first safety and reviewability. Prefer reviewable progress and repairable local breakage over over-planning a run into tiny changes.

At the beginning of every run, make an explicit strategy decision in addition to the Codex CLI availability decision:

```text
Worker strategy: READ_ONLY_REPORTS / WRITE_WORKERS / INTEGRATION_ONLY / NO_WORKERS
Write-worker count planned: <0-{max_write_workers}>
Parallelism budget: <0-{max_write_workers} workers>
Reason: <one sentence>
```

Use read-only workers by default for exploration, review, risk checks, product polish, and test-gap analysis.

Use write workers when the work can be split into useful bounded lanes and the main agent can integrate the results. Before spawning write workers, keep the plan lightweight but concrete:

- choose the milestone
- assign rough file/module ownership for each worker
- define only the shared contracts, interfaces, data shapes, or command boundaries that matter
- document a coordination protocol only when ownership overlaps
- choose expected checks

```text
Write-worker ownership plan:
- worker_<role_a>: owns <files/modules>; contract <interface/data shape>; must not touch <out of scope>
- worker_<role_b>: owns <files/modules>; contract <interface/data shape>; must not touch <out of scope>
Coordination protocol: <how shared interfaces, generated artifacts, or conflicts will be handled>
```

Example bounded write-worker helper:

```bash
bash scripts/spawn_worker_agent.sh \\
  --mode write \\
  --target . \\
  --run-id "$CODEX_RUN_ID" \\
  --role feature_a \\
  --ownership "src/feature-a/** and tests/feature-a/** only" \\
  --prompt "Implement the assigned slice using the agreed interface. List changed files and checks run."
```

Every write-worker assignment must tell the worker:

- You are not alone in the codebase.
- Modify only your assigned files/modules or scratch area.
- Do not revert unrelated edits or changes made by others.
- Adjust your implementation to documented contracts and other workers' outputs.
- Do not spawn workers, use network, touch `.env`, handle credentials, send messages, or run destructive cleanup.
- Stop after the bounded assignment and write `target/agent_runs/<run_id>/worker_<role>.md`.
- List changed files, checks run, integration notes, and risks.

After write workers finish, the main agent must:

- inspect each worker report and changed-file list
- review diffs rather than blindly accepting changes
- resolve conflicts and contract mismatches
- integrate the slices into one coherent change
- run relevant verification
- update `docs/CODEX_AUTOMATION_TASKS.md` with worker strategy, workers used, changed files, checks, accepted/rejected/deferred outputs, and final status"""
        guardrails = f"""- Write-capable workers are enabled but optional; use them as bounded acceleration when work can split into reviewable lanes.
- Spawn at most {max_write_workers} write workers in one run, and use the most parallelism the task can safely absorb.
- Define enough contracts/interfaces and file/module ownership for workers to avoid chaotic overlap, without turning planning into ceremony.
- Do not allow overlapping write ownership unless an explicit coordination protocol is documented first.
- Do not create unbounded recursive agent loops. Workers must not spawn workers.
- Do not blindly accept worker changes; the main agent must review, integrate, resolve conflicts, and verify.
- Do not use destructive cleanup, history rewrites, mass deletion, or broad formatting as a worker cleanup shortcut."""
        task_notes = f"""Write-capable worker agents allowed: true

- Max write worker count: {max_write_workers}
- Parallelism budget: choose 0-{max_write_workers} workers based on how much useful parallelism the task can absorb.
- Write workers are optional acceleration for broad work with reviewable ownership boundaries.
- Read-only workers remain the default for exploration and review.
- Integration-only runs with no workers are valid when faster or safer.
- The main agent must assign ownership, reject weak output, integrate strong output, verify, and update task state."""
        development = f"""Write-capable worker agents allowed: true

Max write worker count: {max_write_workers}

Write workers are optional acceleration. Use the most parallelism the task can safely absorb while keeping ownership reviewable and the main agent responsible for integration. The helper supports `--mode write`, but it does not replace code review or conflict resolution."""
        bootstrap = f"""Worker agents allowed: {str(workers_allowed).lower()}

Write-capable worker agents allowed: true

Max write worker count: {max_write_workers}

Recurring automation should use read-only worker reports for exploration and use bounded write workers as acceleration when work can split into useful parallel lanes. Keep planning lightweight, but make ownership, verification, and integration responsibilities clear."""
    else:
        orchestration = """Write workers are disabled for this project. Do not spawn nested workers that modify source files or docs. Use read-only worker reports when useful, and let the main agent implement, integrate, verify, and update task state directly.

Integration-only runs with no workers are valid."""
        guardrails = """- Write-capable workers are disabled unless the project intake is explicitly updated to enable them.
- Use read-only worker reports when workers are useful.
- Do not spawn nested workers that modify source files or docs."""
        task_notes = """Write-capable worker agents allowed: false

- Max write worker count: 0
- Read-only worker reports remain available when worker agents are allowed.
- The main agent performs implementation, integration, verification, and task-state updates."""
        development = """Write-capable worker agents allowed: false

Use read-only worker reports first. The main agent owns implementation and integration unless the project intake is explicitly updated to enable bounded write workers."""
        bootstrap = f"""Worker agents allowed: {str(workers_allowed).lower()}

Write-capable worker agents allowed: false

Generated automation should preserve read-only worker-report behavior and keep implementation responsibility with the main agent unless the intake is explicitly updated later."""

    return {
        "WORKER_AGENTS_ALLOWED": str(workers_allowed).lower(),
        "CODEX_CLI_WORKERS_EXPECTED_ON_BROAD_RUNS": str(codex_workers_expected).lower(),
        "WRITE_WORKER_AGENTS_ALLOWED": str(write_workers_enabled).lower(),
        "MAX_WRITE_WORKER_COUNT": str(max_write_workers),
        "WRITE_WORKER_GUIDANCE": guidance,
        "WRITE_WORKER_ORCHESTRATION": orchestration.strip(),
        "WRITE_WORKER_GUARDRAILS_POLICY": guardrails.strip(),
        "WRITE_WORKER_TASK_NOTES": task_notes.strip(),
        "WRITE_WORKER_DEVELOPMENT_SECTION": development.strip(),
        "WORKER_BOOTSTRAP_SECTION": bootstrap.strip(),
    }


def multi_role_values(data: dict[str, Any]) -> dict[str, str]:
    enabled = normalize_bool(data.get("multi_role_automations_allowed"), False)
    profile = normalize_role_profile(data.get("automation_role_profile"), enabled)
    checkpoint_commits = normalize_bool(data.get("automation_checkpoint_commits"), True)
    cadence_minutes = normalize_multi_role_cadence(data.get("multi_role_base_cadence_minutes"))
    schedule_strategy = normalize_schedule_strategy(data.get("automation_schedule_strategy"), enabled)
    allow_remotes = normalize_bool(data.get("multi_role_allow_remotes"), False)

    if enabled:
        automation_section = f"""Multi-role automations allowed: true

Role profile: `{profile}`

Automation schedule strategy: `{schedule_strategy}`

Planner cadence: hourly at minute `0`

Builder cadence: minutes `10` and `40`

Hardener cadence: minutes `20` and `50`

Integrator cadence: minutes `25` and `55`

The current single-lane automation remains valid for manual runs. Scheduled multi-role mode uses local role prompts under `.agentic/roles/`, isolated git worktrees under `target/automation_worktrees/`, queued patches under `target/automation_queue/`, and durable progress state in `docs/MULTI_ROLE_PROGRESS.md`.

Dashboard scheduling can use the fixed multi-role cadence or the continuous conveyor. The conveyor is one local launchd job that chooses the next runnable lane from current state, prioritizing queued integration first, fast-follow replanning after a planner patch is newly deferred or a planner deferral is resolved, due planning second, builder momentum by default, and one hardener pass after integrated builder work.

Multi-role mode is local-only. Roles must never push, fetch, pull, clone with remote tracking, configure remotes, set upstream tracking, or run any git command that touches a remote. Local commits, local branches, local tags, and local worktrees are allowed. Any remote-touching attempt is a `CRITICAL_STOP`.

Planner, builder, and hardener start from the latest main `HEAD` at run start. They may see partially integrated state from earlier patches in the same cycle; this is accepted. The integrator owns the main checkout, applies queued patches FIFO, verifies, creates local checkpoint commits, updates `docs/CODEX_AUTOMATION_TASKS.md`, updates `docs/MULTI_ROLE_PROGRESS.md`, and enforces retention."""
        guardrails = """- Multi-role automation is enabled but optional; the single-lane wrapper remains valid.
- Multi-role role runs require an initialized local git repo.
- Multi-role mode is local-only: never push, fetch, pull, clone with remote tracking, configure remotes, set upstream tracking, or run git commands that touch a remote.
- Role scripts must refuse to run when `git remote -v` is non-empty unless `MULTI_ROLE_ALLOW_REMOTES=1`.
- Integrator owns main-checkout mutation, local checkpoint commits, FIFO patch application, verification, task-state updates, and `docs/MULTI_ROLE_PROGRESS.md`.
- Planner, builder, and hardener must use isolated worktrees and queue patches instead of mutating the main checkout.
- Integrator must checkpoint dirty main changes as-is before applying queued patches; do not revert or discard human changes.
- Integrator must defer conflicting, stale, guardrail-violating, or verification-failing patches with machine-readable deferral reasons."""
        task_notes = f"""Multi-role automations allowed: true

- Role profile: `{profile}`
- Automation schedule strategy: `{schedule_strategy}`
- Planner runs hourly at minute `0`; builder, hardener, and integrator run on staggered half-hour offsets.
- Continuous conveyor mode is available through `scripts/run_conveyor_automation.sh`; it prioritizes queued integration first, fast-follow replanning after a planner patch is newly deferred or a planner deferral is resolved, due planning second, builder momentum by default, and one hardener pass after integrated builder work.
- Integrator maintains `docs/MULTI_ROLE_PROGRESS.md` and local checkpoint commits.
- Deferred patches remain visible through `scripts/list_deferred_patches.py`; use `python3 scripts/list_deferred_patches.py . --markdown` for grouped local triage.
- Local-only safety: no pushes, fetches, pulls, remote configuration, upstream tracking, or remote-touching git commands."""
        development = f"""Multi-role automations allowed: true

Role profile: `{profile}`

Automation schedule strategy: `{schedule_strategy}`

Use dashboard scheduling for staggered role jobs or the continuous conveyor. The conveyor keeps work moving by running the next useful lane as soon as the previous lane finishes:

```bash
bash scripts/run_conveyor_automation.sh --dry-run
bash scripts/run_conveyor_automation.sh --once
```

You can still run a role manually:

```bash
bash scripts/run_role_automation.sh --role planner
bash scripts/run_role_automation.sh --role builder
bash scripts/run_role_automation.sh --role hardener
bash scripts/run_role_automation.sh --role integrator
```

Review deferred backlog triage without mutating the repo:

```bash
python3 scripts/list_deferred_patches.py . --markdown
```

The target must be an initialized git repo. Multi-role mode creates local worktrees, local queue artifacts, and local commits only. It never pushes."""
        bootstrap = f"""Multi-role automations allowed: true

Role profile: `{profile}`

Automation schedule strategy: `{schedule_strategy}`

After bootstrap, ensure this target is an initialized git repo before enabling scheduled multi-role automation. The recurring role prompts, conveyor, and helpers are generated locally; no remote git operations are allowed."""
    else:
        automation_section = """Multi-role automations allowed: false

This project uses the default single-lane automation wrapper unless the intake is explicitly updated to enable multi-role mode. The continuous conveyor wrapper is still available as an optional local scheduler; without multi-role files it falls back to the single-lane wrapper."""
        guardrails = "- Multi-role automations are disabled unless the project intake explicitly enables them."
        task_notes = """Multi-role automations allowed: false

- Use the default single-lane scheduled automation."""
        development = """Multi-role automations allowed: false

Use the default `scripts/run_codex_automation.sh` schedule unless the project intake is explicitly updated."""
        bootstrap = """Multi-role automations allowed: false

Use the default single-lane automation after bootstrap."""

    return {
        "MULTI_ROLE_AUTOMATIONS_ALLOWED": str(enabled).lower(),
        "AUTOMATION_ROLE_PROFILE": profile,
        "AUTOMATION_CHECKPOINT_COMMITS": str(checkpoint_commits).lower(),
        "MULTI_ROLE_BASE_CADENCE_MINUTES": str(cadence_minutes),
        "AUTOMATION_SCHEDULE_STRATEGY": schedule_strategy,
        "MULTI_ROLE_ALLOW_REMOTES": str(allow_remotes).lower(),
        "MULTI_ROLE_AUTOMATION_SECTION": automation_section.strip(),
        "MULTI_ROLE_GUARDRAILS_POLICY": guardrails.strip(),
        "MULTI_ROLE_TASK_NOTES": task_notes.strip(),
        "MULTI_ROLE_DEVELOPMENT_SECTION": development.strip(),
        "MULTI_ROLE_BOOTSTRAP_SECTION": bootstrap.strip(),
    }


def automation_signal_values(data: dict[str, Any]) -> dict[str, str]:
    enabled = normalize_bool(data.get("automation_signals_enabled"), False)
    if enabled:
        section = """Automation signals enabled: true

At run start, refresh recurring signal state with:

```bash
python3 scripts/update_automation_signals.py . --refresh --summary
```

Signals are local nudges defined in `docs/AUTOMATION_SIGNALS.md` and tracked at runtime in `target/automation_signals.json`. They do not override guardrails or task state. When a role acts on a signal, it should mark it complete with `scripts/update_automation_signals.py --complete` and record the decision in its normal summary."""
        development = """Automation signals enabled: true

Signal definitions live in `docs/AUTOMATION_SIGNALS.md`; runtime state lives in `target/automation_signals.json`.

```bash
python3 scripts/update_automation_signals.py . --refresh --summary
python3 scripts/update_automation_signals.py . --complete prompt-self-audit --role planner --note "Reviewed prompt scope."
```"""
        task_notes = """Automation signals enabled: true

- Signal definitions: `docs/AUTOMATION_SIGNALS.md`
- Runtime state: `target/automation_signals.json`
- Signals are recurring nudges only; they never override guardrails, active human requests, or the current sprint."""
        bootstrap = """Automation signals enabled: true

Use `docs/AUTOMATION_SIGNALS.md` for recurring local review nudges such as prompt self-audits, validation sweeps, deferred-patch triage, and human inbox triage."""
        file_reads = """docs/AUTOMATION_SIGNALS.md
target/automation_signals.json"""
    else:
        section = """Automation signals enabled: false

Use normal task-file and human-inbox state unless the project intake explicitly enables recurring automation signals."""
        development = """Automation signals enabled: false

The signal updater script is available for future opt-in, but no signal definitions are generated by default."""
        task_notes = """Automation signals enabled: false

- Use normal task-file state unless the intake explicitly enables signals."""
        bootstrap = """Automation signals enabled: false

Use normal task-file state unless the project intake explicitly enables recurring automation signals."""
        file_reads = ""

    return {
        "AUTOMATION_SIGNALS_ENABLED": str(enabled).lower(),
        "AUTOMATION_SIGNALS_SECTION": section.strip(),
        "AUTOMATION_SIGNALS_DEVELOPMENT_SECTION": development.strip(),
        "AUTOMATION_SIGNALS_TASK_NOTES": task_notes.strip(),
        "AUTOMATION_SIGNALS_BOOTSTRAP_SECTION": bootstrap.strip(),
        "AUTOMATION_SIGNAL_FILE_READS": file_reads,
    }


def parse_markdown_intake(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    data: dict[str, Any] = {}

    title = re.search(r"^#\s+Project Intake:\s*(.+)$", text, re.MULTILINE)
    if title:
        data["project_name"] = title.group(1).strip()

    matches = list(re.finditer(r"^##\s+(.+?)\s*$", text, re.MULTILINE))
    for index, match in enumerate(matches):
        heading = match.group(1).strip().lower()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        key = HEADING_TO_KEY.get(heading)
        if key:
            data[key] = text[start:end].strip()
    return data


def parse_intake(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json" or text.lstrip().startswith(("{", "[")):
        return json.loads(text)
    return parse_markdown_intake(path)


def placeholders(data: dict[str, Any]) -> dict[str, str]:
    project_name = str(data.get("project_name") or data.get("summary") or "New Project").strip()
    mode = project_mode(data)
    bridge_mode = human_bridge_mode(data)
    text_responses = bridge_mode == "local_notifier" and normalize_bool(
        data.get("human_requested_text_responses"),
        True,
    )
    verification = normalize_lines(
        data.get("verification_commands"),
        "Add project-specific test, lint, build, or demo commands during bootstrap.",
    )
    values = {
        "PROJECT_NAME": project_name,
        "PROJECT_SLUG": slugify(project_name),
        "PROJECT_MODE": mode,
        "PROJECT_MODE_LABEL": project_mode_label(mode),
        "PROJECT_MODE_GUIDANCE": project_mode_guidance(mode),
        "PRODUCT_GOAL": normalize_lines(data.get("product_goal"), "Build a useful local-first product from the intake brief."),
        "TARGET_USER": normalize_lines(data.get("target_user"), "The primary user described in the intake brief."),
        "DESIRED_FIRST_DEMO": normalize_lines(data.get("desired_first_demo"), "A runnable local demo that proves the core workflow."),
        "TECH_PREFERENCES": normalize_lines(data.get("tech_preferences"), "Use the existing repo stack or choose a simple, well-supported default."),
        "HARD_CONSTRAINTS": normalize_lines(data.get("hard_constraints"), "Keep the first demo local-first and reviewable."),
        "SAFETY_CONSTRAINTS": normalize_lines(data.get("safety_constraints"), "No secrets, paid actions, public deploys, or real-world side effects without approval."),
        "AUTOMATION_MUST_NEVER_DO": normalize_lines(data.get("automation_must_never_do"), "Never read secrets, spend money, deploy publicly, publish externally, contact real users, or trigger real-world side effects without explicit approval."),
        "EXTERNAL_SERVICES": normalize_lines(data.get("external_services"), "None required for the first demo."),
        "ADDITIONAL_CONTEXT_FILES": normalize_lines(data.get("additional_context_files"), "No additional context files provided."),
        "VERIFICATION_COMMANDS": verification,
        "CADENCE": normalize_lines(data.get("desired_cadence"), "every 60 minutes"),
        "MEANINGFUL_DELIVERABLE": normalize_lines(data.get("meaningful_deliverable"), "A runnable, verified increment."),
        "BEYOND_MVP": normalize_lines(data.get("beyond_mvp"), "Continue improving core value, demo quality, integrations, and automation reliability."),
        "ASSUMPTIONS": normalize_lines(data.get("assumptions"), "Assumptions should be documented during bootstrap."),
        "CREATED_AT": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    values.update(worker_values(data))
    values.update(multi_role_values(data))
    values.update(automation_signal_values(data))
    values.update(bridge_values(bridge_mode, text_responses))
    return values


def render_template(text: str, values: dict[str, str]) -> str:
    # Some mode-specific blocks contain ordinary placeholders such as
    # {{PROJECT_NAME}}. A short fixed-point pass keeps the template language
    # simple without requiring conditionals.
    for _ in range(3):
        before = text
        for key, value in values.items():
            text = text.replace("{{" + key + "}}", value)
        if text == before:
            break
    return text


def managed_section_bounds(kind: str) -> tuple[str, str]:
    return (f"<!-- DIFFMOGGER:START {kind} -->", f"<!-- DIFFMOGGER:END {kind} -->")


def demote_markdown_headings(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
    demoted: list[str] = []
    for line in lines:
        if line.startswith("#"):
            hashes = len(line) - len(line.lstrip("#"))
            if hashes > 0 and len(line) > hashes and line[hashes] == " ":
                line = "#" + line
        demoted.append(line)
    return "\n".join(demoted).strip()


def render_managed_section(kind: str, rendered: str) -> str:
    start, end = managed_section_bounds(kind)
    body = demote_markdown_headings(rendered)
    return (
        f"{start}\n"
        "## Diffmogger Automation\n\n"
        "This block is managed by Diffmogger. Keep project-owned instructions outside this block.\n\n"
        f"{body}\n"
        f"{end}\n"
    )


def upsert_managed_section(existing: str, section: str, kind: str) -> str:
    start, end = managed_section_bounds(kind)
    pattern = re.compile(
        rf"{re.escape(start)}.*?{re.escape(end)}\s*",
        re.DOTALL,
    )
    if pattern.search(existing):
        return pattern.sub(section, existing).rstrip() + "\n"
    separator = "\n\n" if existing.rstrip() else ""
    return existing.rstrip() + separator + section


def scaffold(target: Path, values: dict[str, str], force: bool) -> list[Path]:
    written: list[Path] = []
    mode = values.get("PROJECT_MODE", "fresh_project")
    for template_path in sorted(TEMPLATE_ROOT.rglob("*")):
        if template_path.is_dir():
            continue
        if "__pycache__" in template_path.parts or template_path.suffix == ".pyc":
            continue
        rel = template_path.relative_to(TEMPLATE_ROOT)
        if values.get("HUMAN_BRIDGE_MODE") == "disabled" and rel.as_posix() in HUMAN_BRIDGE_FILES:
            continue
        if values.get("AUTOMATION_SIGNALS_ENABLED") != "true" and rel.as_posix() in AUTOMATION_SIGNAL_FILES:
            continue
        if values.get("MULTI_ROLE_AUTOMATIONS_ALLOWED") != "true" and rel.as_posix() in MULTI_ROLE_FILES:
            continue
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        rendered = render_template(template_path.read_text(encoding="utf-8"), values)
        managed_kind = MANAGED_EXISTING_PROJECT_FILES.get(rel.as_posix())
        if mode == "existing_project" and managed_kind and dest.exists():
            existing = dest.read_text(encoding="utf-8", errors="replace")
            section = render_managed_section(managed_kind, rendered)
            dest.write_text(upsert_managed_section(existing, section, managed_kind), encoding="utf-8")
            written.append(dest)
            continue
        if dest.exists() and not force:
            continue
        dest.write_text(rendered, encoding="utf-8")
        if rel.parts and rel.parts[0] == "scripts" and dest.suffix in {".sh", ".py"}:
            dest.chmod(0o755)
        written.append(dest)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intake", required=True, help="Markdown or JSON project intake file")
    parser.add_argument("--target", required=True, help="Target project directory")
    parser.add_argument("--force", action="store_true", help="Overwrite existing files")
    args = parser.parse_args()

    intake_path = Path(args.intake).resolve()
    target = Path(args.target).resolve()
    data = parse_intake(intake_path)
    values = placeholders(data)
    written = scaffold(target, values, args.force)

    print(f"Scaffolded {len(written)} files into {target}")
    for path in written:
        print(path.relative_to(target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
