# Daily Review Prompt

Use this after several automation runs or at the end of a day.

---

Create or update `.diffmogger/state/DAILY_AUTOMATION_REVIEW.md`.

Read:

- `.diffmogger/state/CODEX_AUTOMATION_TASKS.md`
- `.diffmogger/state/AUTONOMY_EXPERIMENT_LOG.md`
- recent generated artifacts
- human bridge files
- worker reports under `.diffmogger/runtime/agent_runs/` if present
- git diff or commit history if available

Write a concise daily capsule:

```markdown
## YYYY-MM-DD

### What changed today

### What became runnable or inspectable

### Checks and demo commands

### Generated artifacts to open

### Human requests pending/resolved

### Worker agents used and whether they helped

### What got worse or riskier

### Best manual review focus

### Is the workflow compounding or drifting?
```

Keep it readable in five minutes. Do not duplicate the whole task file.
