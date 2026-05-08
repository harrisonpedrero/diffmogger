# Optional MCP Integrations

{{MCP_SETUP_SECTION}}

## Role Scoping

- Planner and Builder may use Context7 for documentation-assisted planning and implementation.
- Context7 inherits `CONTEXT7_API_KEY` when present; set it outside the repo, for example with `launchctl setenv`, and never commit the key.
- Hardener may use Playwright MCP for local browser validation and must call `browser_take_screenshot` for screenshot-backed UI bug reports.
- Integrator uses normal local scripts for patch application; Playwright MCP is available only for validation sessions and screenshot-backed repro evidence.
- Single-lane automation may use enabled MCP servers selectively.
- Role wrappers apply temporary `codex exec -c` MCP overrides from `.codex/config.toml` so each lane receives only the optional MCP server it can use.

## Verification

```bash
codex mcp list --json
python3 .diffmogger/scripts/diffmogger_browser.py doctor --launch
```

If an MCP server is missing, unauthenticated, timed out, or returns an error, continue with existing Diffmogger behavior and record the fallback only when it affects the sprint evidence.
