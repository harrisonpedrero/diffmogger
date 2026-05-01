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
VALID_HUMAN_BRIDGE_MODES = {"disabled", "file_only", "local_notifier"}
VALID_PROJECT_MODES = {"fresh_project", "existing_project"}
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
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
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
        "WORKER_AGENTS_ALLOWED": str(normalize_bool(data.get("worker_agents_allowed"), True)).lower(),
        "MEANINGFUL_DELIVERABLE": normalize_lines(data.get("meaningful_deliverable"), "A runnable, verified increment."),
        "BEYOND_MVP": normalize_lines(data.get("beyond_mvp"), "Continue improving core value, demo quality, integrations, and automation reliability."),
        "ASSUMPTIONS": normalize_lines(data.get("assumptions"), "Assumptions should be documented during bootstrap."),
        "CREATED_AT": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
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
        rel = template_path.relative_to(TEMPLATE_ROOT)
        if values.get("HUMAN_BRIDGE_MODE") == "disabled" and rel.as_posix() in HUMAN_BRIDGE_FILES:
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
