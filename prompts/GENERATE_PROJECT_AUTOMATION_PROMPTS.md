# Generate Project Automation Prompts

Use this prompt after a project intake brief exists. It is the main starter prompt for creating project-specific prompts and automation docs.

---

You are generating project-specific Codex automation files from a project intake brief.

Read the intake brief first. If values are missing, make reasonable defaults and document assumptions. Do not ask questions unless a missing value would make the workflow unsafe.

Create these files as complete Markdown drafts:

```text
docs/INITIAL_BOOTSTRAP_PROMPT.md
.agentic/automation_prompt.md
AGENTS.md
docs/CODEX_AUTOMATION_TASKS.md
docs/CODEX_AUTOMATION_GUARDRAILS.md
docs/HUMAN_REQUESTS.md
docs/HUMAN_INBOX.md
docs/HUMAN_OUTBOX.md
docs/HUMAN_RESPONSES_ARCHIVE.md
docs/HUMAN_BRIDGE_SETUP.md
docs/AUTONOMY_EXPERIMENT_LOG.md
docs/DAILY_AUTOMATION_REVIEW.md
scripts/acquire_codex_lock.sh
scripts/release_codex_lock.sh
scripts/run_codex_automation.sh
scripts/spawn_worker_agent.sh
scripts/summarize_worker_outputs.py
scripts/compact_agent_state.py
```

## Requirements

The generated `docs/INITIAL_BOOTSTRAP_PROMPT.md` is used once or a few times. It should be project-specific, scaffold the product, create automation docs, create verification commands, and get to a first runnable demo.

The generated `.agentic/automation_prompt.md` is used for recurring automation. It should be durable and behavioral. It must tell Codex to read the dynamic task file and guardrails every run, continue beyond MVP, support worker agents, support the human bridge, use lock files, compact state when needed, verify work, and update state.

It must explicitly read and follow:

```text
docs/CODEX_AUTOMATION_TASKS.md
docs/CODEX_AUTOMATION_GUARDRAILS.md
docs/HUMAN_REQUESTS.md if present
docs/HUMAN_INBOX.md if present
docs/HUMAN_OUTBOX.md if present
docs/HUMAN_RESPONSES_ARCHIVE.md if present
docs/AUTONOMY_EXPERIMENT_LOG.md if present
```

It must say that the task file is dynamic and rewritten at the end of every run. It must say the guardrails file is static and should not be rewritten unless the user explicitly asks or the current task is specifically to improve guardrails.

The automation prompt must include this exact language:

```text
Treat each run as a substantial engineering sprint.
Do not finish after a tiny task if there is obvious adjacent work that can be completed safely in the same run.
If the selected task finishes quickly, immediately choose the next highest-value adjacent task and continue.
Do not stop merely because a basic demo exists. A working baseline is not the finish line.
If all listed tasks are done, inspect the project and generate the next valuable backlog yourself, staying aligned with the mission and guardrails.
```

The task file must include:

- `AUTOMATION_STATUS: ACTIVE`
- current project state
- completed last run
- checks from last run
- worker-agent activity
- known issues
- pending human requests
- best next milestone
- suggested next sprint-sized task
- ambitious ideas backlog
- continue/block/critical-stop rationale

The guardrails file must stay lean and include:

- scope boundaries
- secrets policy
- external side effects policy
- quality policy
- worker-agent policy
- human-intervention policy
- status policy
- context-bloat policy

The human bridge docs and automation prompt must support three modes:

1. disabled
2. local-file-only mode
3. Diffmogger local notifier service mode: `POST http://127.0.0.1:8765/api/notify`

For `file_only`, the generated docs must say the human manually reads `docs/HUMAN_REQUESTS.md`, replies in `docs/HUMAN_INBOX.md`, and summary/status requests are satisfied locally in Markdown or app artifacts. It must not tell Codex to send SMS, WhatsApp, or notifier messages in file-only mode.

For `local_notifier`, the generated automation prompt must say that if the notifier is unavailable, Codex should fall back to `docs/HUMAN_REQUESTS.md`, continue useful work, and use `ACTIVE_WITH_PENDING_USER_INPUT` unless no useful work remains.

The generated automation prompt must read `docs/HUMAN_INBOX.md` at the start of each run, remove handled inbox messages, and archive concise notes in `docs/HUMAN_RESPONSES_ARCHIVE.md`.

The generated automation prompt must classify freeform human inbox commands. In `local_notifier` mode, if the human asks to `send me`, `text me`, `message me`, `reply with`, provide a `status update`, explain `what have you done so far?`, or `summarize progress`, the automation must send a concise SMS/WhatsApp response through the local notifier when available. It must not satisfy that request only by writing Markdown. If the notifier is unavailable, it must record the intended outbound message in `docs/HUMAN_OUTBOX.md` with status `NOTIFIER_UNREACHABLE` and continue useful work.

For direct human-requested outbound responses, include this payload option if the notifier supports it:

```json
{
  "request_id": "MSG-YYYY-MM-DD-001",
  "type": "human_requested_summary",
  "priority": "normal",
  "summary": "Progress summary requested by human",
  "message_body": "<concise phone-friendly response>",
  "minimum_user_action": "None.",
  "reply_format": "Optional follow-up request.",
  "dedupe_key": "MSG-YYYY-MM-DD-001:v1",
  "expects_reply": false
}
```

Outbound text should target 300-900 characters, use at most five short bullets, avoid raw stack traces, avoid secrets, and avoid embedded URLs unless explicitly necessary and allowed by the messaging setup.

Worker-agent instructions must use this output convention:

```text
target/agent_runs/<run_id>/worker_<role>.md
```

Main-agent ownership rule: worker agents may explore, review, or prototype, but the main automation agent owns integration and verification.

The generated automation prompt must make an explicit Codex CLI worker decision at the beginning of every run:

```text
Codex CLI worker decision: USE / SKIP / UNAVAILABLE
Reason: <one sentence>
```

It must check availability with `command -v codex` before using Codex CLI workers, record `UNAVAILABLE` if the command is missing, and continue the sprint. For broad or multi-module runs, Codex CLI worker usage should be expected unless skipped with a clear reason. Include the target repo's local `scripts/spawn_worker_agent.sh` and `scripts/summarize_worker_outputs.py` helper pattern and a read-only nested-child `codex exec --disable plugins --ephemeral --dangerously-bypass-approvals-and-sandbox -C .` fallback pattern. Also ensure the scheduled wrapper runs the parent automation with `--add-dir "$HOME/.codex"` so nested Codex CLI workers can authenticate and start inside the parent sandbox.

Lock-file instructions should reference the target repo's local `scripts/run_codex_automation.sh`, `scripts/acquire_codex_lock.sh`, and `scripts/release_codex_lock.sh` helpers, the default `target/codex_automation.lock` path, `CODEX_LOCK_PATH` overrides, stale-lock detection, `CODEX_RUN_ID` identity for safe release, and `CODEX_LOCK_ALREADY_ACQUIRED=true` for wrapper-owned scheduled runs.

State-compaction instructions should reference `scripts/compact_agent_state.py --dry-run <target-project>`, preserve unresolved human requests, and archive concise rollups rather than silently deleting active state.

## Output

Return each file in a separate fenced Markdown block with a filename heading. Keep the files ready to paste into the target repo.
