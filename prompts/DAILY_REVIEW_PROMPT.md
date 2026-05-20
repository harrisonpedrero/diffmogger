# Daily Review Prompt

Use this after several automation runs or at the end of a day.

---

Create a concise local review note only when a human explicitly asks for one. Do not add it to the generated target scaffold.

Read:

- `.diffmogger/runtime/canonical_state_brief.md`
- `.diffmogger/state/CODEX_AUTOMATION_TASKS.md`
- recent generated artifacts
- typed human-message state
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

Keep it readable in five minutes. Do not duplicate the whole generated task projection.
