# Optional MCP Integrations

{{MCP_SETUP_SECTION}}

## Role Scoping

- Planner and Builder may use Context7 for documentation-assisted planning and implementation.
- Context7 inherits `CONTEXT7_API_KEY` when present; set it outside the repo, for example with `launchctl setenv`, and never commit the key.
- Hardener may use Playwright MCP for local browser validation and must call `browser_take_screenshot` for screenshot-backed UI bug reports.
- Integrator uses normal local scripts for patch application; Playwright MCP is requested for validation sessions and screenshot-backed repro evidence.
- Planner may receive Playwright only for frontend, browser, UI, or demo-path planning.
- Builder receives Playwright only when the selected ticket is explicitly frontend, browser, UI, or demo-path scoped.
- Single-lane automation may use enabled MCP servers selectively.
- Role wrappers apply temporary `codex exec -c` MCP overrides from resolved intake/dashboard/manifest state so each lane receives only the optional MCP server it can use. They do not depend on a worktree `.codex/config.toml` file being present.

## Decision Notes

Every role summary must include an MCP decision note:

```text
MCP decision: context7 used|skipped - <reason>; playwright used|skipped - <reason>
```

Use `context7 used` when third-party/library/API docs materially affect planning or implementation. Use `playwright used` when validating browser-facing changes. Use `skipped` only with a concrete reason such as backend-only change, docs-only change, not mounted for this role, or MCP unavailable.

## Verification

```bash
codex mcp list --json
python3 .diffmogger/scripts/diffmogger_browser.py doctor --launch
```

If an MCP server is missing, unauthenticated, timed out, or returns an error, continue with existing Diffmogger behavior and record the fallback only when it affects the sprint evidence.
