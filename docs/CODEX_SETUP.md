# Codex Setup

This page summarizes platform setup decisions for projects using the kit. Recheck official docs before production use because Codex features evolve quickly.

## Codex CLI

Install or update:

```bash
npm i -g @openai/codex@latest
codex
```

The Codex CLI runs locally from your terminal and can inspect, edit, and run code in the selected directory. On Windows, current docs describe native PowerShell support and WSL2 as options.

## AGENTS.md

Codex reads `AGENTS.md` files before doing work. It layers global instructions from the Codex home directory with project instructions from the repo root down to the current working directory. Files closer to the current directory take precedence because they are added later.

Use `AGENTS.md` for durable repo guidance:

- layout and important directories
- setup commands
- build, lint, and test commands
- conventions and constraints
- done/verification expectations

Keep project instructions concise. If they are too large, split specialized guidance into nested directories.

## Non-Interactive Mode

`codex exec` runs Codex from scripts and CI without opening the interactive TUI:

```bash
codex exec "summarize the repository structure"
```

For recurring local automation, use explicit sandbox and approval settings. Current docs say `codex exec` defaults to read-only. Use `--full-auto` only when edits and workspace commands are expected:

```bash
codex exec --full-auto "$(cat .agentic/automation_prompt.md)"
```

For read-only worker reports from an automation run, prefer an explicit bounded command:

```bash
command -v codex

export CODEX_RUN_ID="${CODEX_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "target/agent_runs/$CODEX_RUN_ID"

codex exec \
  --sandbox workspace-write \
  --ask-for-approval never \
  -c sandbox_workspace_write.network_access=false \
  "You are a read-only worker for this project. Read the repo and write a concise report to target/agent_runs/$CODEX_RUN_ID/worker_review.md. Do not modify source files except for that output report. Do not use network. Do not spawn workers. Stop after writing the report."
```

Diffmogger also includes optional helper scripts:

```bash
bash /path/to/Diffmogger/scripts/spawn_worker_agent.sh --target . --run-id "$CODEX_RUN_ID" --role review --prompt "Write a concise read-only review report."
python3 /path/to/Diffmogger/scripts/summarize_worker_outputs.py . --run-id "$CODEX_RUN_ID"
```

If `command -v codex` fails, record `Codex CLI worker decision: UNAVAILABLE` in the task file and continue without blocking the sprint.

## Automations

Codex Automations run recurring tasks on a schedule. Good automation instructions are specific, repeatable, and easy to review. Local automations work best when the machine is awake and Codex is running.

This kit recommends keeping the automation task prompt stable and putting changing project state in `docs/CODEX_AUTOMATION_TASKS.md`.

For scheduled runs, wrap mutation with the lock helpers:

```bash
export CODEX_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
bash /path/to/Diffmogger/scripts/acquire_codex_lock.sh "scheduled sprint"
codex exec --full-auto "$(cat .agentic/automation_prompt.md)"
bash /path/to/Diffmogger/scripts/release_codex_lock.sh
```

If the scheduler does not run from the target repo, set `CODEX_LOCK_PATH=/absolute/path/to/target/target/codex_automation.lock`.

## Subagents

Current Codex docs describe subagent workflows that spawn specialized agents in parallel and collect their results. Codex only spawns subagents when explicitly asked, and subagents inherit the parent sandbox policy. Use them deliberately and record their outputs.

Recommended project convention:

```text
target/agent_runs/<run_id>/worker_<role>.md
```

## Sandboxing And Approvals

Codex security controls combine sandbox mode with approval policy. Current docs describe defaults that keep network access off and limit writes to the active workspace unless configured otherwise.

Common local choices:

- Read-only: exploration, reviews, and audits.
- Workspace-write/full-auto: trusted local implementation runs.
- Danger full access: only inside a controlled isolated environment.

Never treat sandboxing as a reason to expose secrets to Codex.

## Official Sources

- [Codex CLI](https://developers.openai.com/codex/cli)
- [AGENTS.md guide](https://developers.openai.com/codex/guides/agents-md)
- [Non-interactive mode](https://developers.openai.com/codex/noninteractive)
- [Subagents](https://developers.openai.com/codex/subagents)
- [Agent approvals and security](https://developers.openai.com/codex/agent-approvals-security)
- [Codex Automations](https://openai.com/academy/codex-automations/)
