# Automation Signals

Optional recurring nudges for local Diffmogger automation.

Signals do not override guardrails, task state, human requests, or role judgment. They only mark recurring review obligations as due so roles can decide whether to act during a normal sprint.

Runtime state is written to:

```text
target/automation_signals.json
```

Roles can mark a signal handled with:

```bash
python3 .diffmogger/scripts/update_automation_signals.py . --complete <signal-id> --role <role> --note "What was done or why it was enough."
```

## Signal Definitions

```json
{
  "schema_version": 1,
  "signals": [
    {
      "id": "prompt-self-audit",
      "owner_role": "planner",
      "cadence": "weekly",
      "priority": "medium",
      "instructions": "Review whether the recurring automation prompt still matches current project needs without bloating it."
    },
    {
      "id": "validation-sweep",
      "owner_role": "hardener",
      "cadence": "weekly",
      "priority": "medium",
      "instructions": "Run or improve validation coverage around recently changed automation behavior."
    },
    {
      "id": "deferred-patch-triage",
      "owner_role": "integrator",
      "cadence": "weekly",
      "priority": "medium",
      "instructions": "Review deferred queued patches and decide whether to retry, replace, archive, or document them."
    },
    {
      "id": "human-inbox-triage",
      "owner_role": "planner",
      "cadence": "daily",
      "priority": "high",
      "instructions": "Check whether human inbox or request files contain stale entries that need action or cleanup."
    }
  ]
}
```
