from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
from diffmogger.runtime.state_store import load_ticket_run_state, write_ticket_run_state

SOURCE_ROLE_RUNNER = ROOT / "scripts" / "target" / "run_role_automation.sh"
TEMPLATE_ROLE_RUNNER = ROOT / "templates" / "scripts" / "run_role_automation.sh"
ROLE_RUNNER_PATHS = [SOURCE_ROLE_RUNNER]
LOAD_ENV_HELPER_PATHS = [
    ROOT / "scripts" / "runtime" / "load_automation_env.py",
]
PLAYWRIGHT_MCP_HELPER_PATHS = [
    ROOT / "scripts" / "target" / "run_playwright_mcp.sh",
    ROOT / "templates" / "scripts" / "run_playwright_mcp.sh",
]
WATCHDOG_HELPER_PATHS = [
    ROOT / "scripts" / "runtime" / "run_process_watchdog.py",
]


class RunRoleAutomationTests(unittest.TestCase):
    def write_text(self, root: Path, relative: str, content: str) -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
        return path

    def seed_git_target(self, target: Path) -> None:
        subprocess.run(["git", "init", "-q"], cwd=target, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=target, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=target, check=True)
        self.write_text(target, "README.md", "# Role Runner Test\n")
        subprocess.run(["git", "add", "README.md"], cwd=target, check=True)
        subprocess.run(["git", "commit", "-m", "init", "-q"], cwd=target, check=True)
        for role in ("planner", "builder", "hardener", "integrator"):
            self.write_text(target, f".agentic/roles/{role}.md", f"# {role} prompt\n")
        self.write_text(target, ".agentic/automation_prompt.md", "# Automation Prompt\n")
        self.write_text(target, "docs/CODEX_AUTOMATION_TASKS.md", "AUTOMATION_STATUS: ACTIVE\n")
        self.write_text(target, "docs/MULTI_ROLE_PROGRESS.md", "# Multi-Role Progress\n")

    def seed_sidecar_git_target(self, target: Path) -> None:
        subprocess.run(["git", "init", "-q"], cwd=target, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=target, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=target, check=True)
        self.write_text(target, "README.md", "# Sidecar Role Runner Test\n")
        subprocess.run(["git", "add", "README.md"], cwd=target, check=True)
        subprocess.run(["git", "commit", "-m", "init", "-q"], cwd=target, check=True)
        for role in ("planner", "builder", "hardener", "integrator"):
            self.write_text(target, f".diffmogger/agentic/roles/{role}.md", f"# {role} prompt\n")
        self.write_text(target, ".diffmogger/agentic/automation_prompt.md", "# Automation Prompt\n")
        self.write_text(target, ".diffmogger/state/CODEX_AUTOMATION_TASKS.md", "AUTOMATION_STATUS: ACTIVE\n")
        self.write_text(target, ".diffmogger/state/MULTI_ROLE_PROGRESS.md", "# Multi-Role Progress\n")
        self.write_text(
            target,
            ".diffmogger/manifest.json",
            json.dumps(
                {
                    "layout": "sidecar_v1",
                    "path_aliases": {
                        ".agentic/automation_prompt.md": ".diffmogger/agentic/automation_prompt.md",
                        ".agentic/roles": ".diffmogger/agentic/roles",
                        ".agentic/roles/builder.md": ".diffmogger/agentic/roles/builder.md",
                        ".agentic/roles/hardener.md": ".diffmogger/agentic/roles/hardener.md",
                        ".agentic/roles/integrator.md": ".diffmogger/agentic/roles/integrator.md",
                        ".agentic/roles/planner.md": ".diffmogger/agentic/roles/planner.md",
                        "docs/CODEX_AUTOMATION_TASKS.md": ".diffmogger/state/CODEX_AUTOMATION_TASKS.md",
                        "docs/MULTI_ROLE_PROGRESS.md": ".diffmogger/state/MULTI_ROLE_PROGRESS.md",
                        "target/automation_logs": ".diffmogger/runtime/automation_logs",
                        "target/automation_queue": ".diffmogger/runtime/automation_queue",
                        "target/automation_worktrees": ".diffmogger/runtime/automation_worktrees",
                        "target/canonical_state_brief.md": ".diffmogger/runtime/canonical_state_brief.md",
                    },
                    "patch_exclude_paths": [".diffmogger/runtime"],
                    "worktree_seed_paths": [
                        ".diffmogger/agentic/automation_prompt.md",
                        ".diffmogger/agentic/roles",
                        ".diffmogger/state/CODEX_AUTOMATION_TASKS.md",
                        ".diffmogger/state/MULTI_ROLE_PROGRESS.md",
                    ],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )

    def write_fake_codex(self, root: Path) -> Path:
        bin_dir = root / "bin"
        codex = bin_dir / "codex"
        bin_dir.mkdir(parents=True, exist_ok=True)
        codex.write_text(
            "#!/usr/bin/env bash\n"
            "if [[ -n \"${FAKE_CODEX_ARG_LOG:-}\" ]]; then\n"
            "  printf '%s\\n' \"$@\" >\"$FAKE_CODEX_ARG_LOG\"\n"
            "fi\n"
            "exit 0\n",
            encoding="utf-8",
        )
        codex.chmod(codex.stat().st_mode | stat.S_IXUSR)
        return bin_dir

    def write_frontend_playwright_skip_codex(self, root: Path) -> Path:
        bin_dir = root / "bin"
        codex = bin_dir / "codex"
        bin_dir.mkdir(parents=True, exist_ok=True)
        codex.write_text(
            "#!/usr/bin/env bash\n"
            "worktree=\"\"\n"
            "while [[ $# -gt 0 ]]; do\n"
            "  if [[ \"$1\" == \"-C\" ]]; then worktree=\"$2\"; shift 2; continue; fi\n"
            "  prompt=\"$1\"\n"
            "  shift\n"
            "done\n"
            "mkdir -p \"$worktree/src\"\n"
            "printf 'export const App = () => <main>Changed</main>;\\n' > \"$worktree/src/App.tsx\"\n"
            "python3 - \"$prompt\" <<'PY'\n"
            "import re\n"
            "import sys\n"
            "from pathlib import Path\n"
            "match = re.search(r'(/[^`\\n]+summary\\.md)', sys.argv[1])\n"
            "if not match:\n"
            "    raise SystemExit(64)\n"
            "summary = Path(match.group(1))\n"
            "summary.parent.mkdir(parents=True, exist_ok=True)\n"
            "summary.write_text('''Commit type: test\\nCommit scope: ui\\nCommit subject: touch frontend without browser validation\\n\\nMCP decision: context7 skipped - not needed; playwright skipped - backend-only change\\n\\n## Summary\\n- Touched src/App.tsx.\\n\\n## Checks\\n- Not run.\\n''', encoding='utf-8')\n"
            "PY\n"
            "exit 0\n",
            encoding="utf-8",
        )
        codex.chmod(codex.stat().st_mode | stat.S_IXUSR)
        return bin_dir

    def write_backend_playwright_skip_codex(self, root: Path) -> Path:
        bin_dir = root / "bin"
        codex = bin_dir / "codex"
        bin_dir.mkdir(parents=True, exist_ok=True)
        codex.write_text(
            "#!/usr/bin/env bash\n"
            "worktree=\"\"\n"
            "while [[ $# -gt 0 ]]; do\n"
            "  if [[ \"$1\" == \"-C\" ]]; then worktree=\"$2\"; shift 2; continue; fi\n"
            "  prompt=\"$1\"\n"
            "  shift\n"
            "done\n"
            "mkdir -p \"$worktree/tests\"\n"
            "printf 'def test_package_import():\\n    import pathlib\\n    assert pathlib.Path is not None\\n' > \"$worktree/tests/test_package_import.py\"\n"
            "python3 - \"$prompt\" <<'PY'\n"
            "import re\n"
            "import sys\n"
            "from pathlib import Path\n"
            "match = re.search(r'(/[^`\\n]+summary\\.md)', sys.argv[1])\n"
            "if not match:\n"
            "    raise SystemExit(64)\n"
            "summary = Path(match.group(1))\n"
            "summary.parent.mkdir(parents=True, exist_ok=True)\n"
            "summary.write_text('''Commit type: test\\nCommit scope: backend\\nCommit subject: add package import coverage\\n\\nMCP decision: context7 skipped - backend-only package/test change; playwright skipped - backend-only package/test change with no browser surface\\n\\nTest change rationale: Keeps package import coverage explicit.\\n\\n## Summary\\n- Added backend package import coverage.\\n\\n## Checks\\n- Not run in fake harness.\\n''', encoding='utf-8')\n"
            "PY\n"
            "exit 0\n",
            encoding="utf-8",
        )
        codex.chmod(codex.stat().st_mode | stat.S_IXUSR)
        return bin_dir

    def write_ticket_action_codex(self, root: Path) -> Path:
        bin_dir = root / "bin"
        codex = bin_dir / "codex"
        bin_dir.mkdir(parents=True, exist_ok=True)
        codex.write_text(
            "#!/usr/bin/env bash\n"
            "if [[ -z \"${DIFFMOGGER_TICKET_STATE_ACTIONS_PATH:-}\" ]]; then\n"
            "  echo 'ticket action path missing' >&2\n"
            "  exit 70\n"
            "fi\n"
            "mkdir -p \"$(dirname \"$DIFFMOGGER_TICKET_STATE_ACTIONS_PATH\")\"\n"
            "cat >\"$DIFFMOGGER_TICKET_STATE_ACTIONS_PATH\" <<'JSON'\n"
            "{\n"
            "  \"schema_version\": 1,\n"
            "  \"actions\": [\n"
            "    {\n"
            "      \"action\": \"update_ticket\",\n"
            "      \"ticket_id\": \"TICKET-001\",\n"
            "      \"start_hash\": \"role-start-hash\",\n"
            "      \"end_hash\": \"role-end-hash\",\n"
            "      \"ticket\": {\n"
            "        \"id\": \"TICKET-001\",\n"
            "        \"summary\": \"Build first slice\",\n"
            "        \"status\": \"candidate_done\"\n"
            "      }\n"
            "    }\n"
            "  ]\n"
            "}\n"
            "JSON\n"
            "exit 0\n",
            encoding="utf-8",
        )
        codex.chmod(codex.stat().st_mode | stat.S_IXUSR)
        return bin_dir

    def write_hanging_codex(self, root: Path) -> Path:
        bin_dir = root / "bin"
        codex = bin_dir / "codex"
        bin_dir.mkdir(parents=True, exist_ok=True)
        codex.write_text(
            "#!/usr/bin/env bash\n"
            "if [[ -n \"${FAKE_CODEX_PID_FILE:-}\" ]]; then\n"
            "  printf '%s\\n' \"$$\" >\"$FAKE_CODEX_PID_FILE\"\n"
            "fi\n"
            "trap '' TERM\n"
            "while true; do sleep 1; done\n",
            encoding="utf-8",
        )
        codex.chmod(codex.stat().st_mode | stat.S_IXUSR)
        return bin_dir

    def write_snapshot_check_codex(self, root: Path) -> Path:
        bin_dir = root / "bin"
        codex = bin_dir / "codex"
        bin_dir.mkdir(parents=True, exist_ok=True)
        codex.write_text(
            "#!/usr/bin/env bash\n"
            "if [[ -z \"${DIFFMOGGER_TICKET_STATE_READONLY_SNAPSHOT:-}\" ]]; then\n"
            "  echo 'ticket snapshot path missing' >&2\n"
            "  exit 72\n"
            "fi\n"
            "python3 - \"$DIFFMOGGER_TICKET_STATE_READONLY_SNAPSHOT\" <<'PY'\n"
            "import json\n"
            "import sys\n"
            "from pathlib import Path\n"
            "payload = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))\n"
            "data = payload.get('data') if isinstance(payload.get('data'), dict) else {}\n"
            "tickets = data.get('tickets') if isinstance(data.get('tickets'), list) else []\n"
            "if not tickets or tickets[0].get('id') != 'TICKET-001':\n"
            "    raise SystemExit('ticket snapshot did not contain canonical ticket')\n"
            "PY\n"
            "exit 0\n",
            encoding="utf-8",
        )
        codex.chmod(codex.stat().st_mode | stat.S_IXUSR)
        return bin_dir

    def write_leaky_child_codex(self, root: Path) -> Path:
        bin_dir = root / "bin"
        codex = bin_dir / "codex"
        bin_dir.mkdir(parents=True, exist_ok=True)
        codex.write_text(
            "#!/usr/bin/env bash\n"
            "if [[ -z \"${FAKE_CODEX_CHILD_PID_FILE:-}\" ]]; then\n"
            "  echo 'child pid file missing' >&2\n"
            "  exit 73\n"
            "fi\n"
            "python3 - \"$FAKE_CODEX_CHILD_PID_FILE\" <<'PY' &\n"
            "import os\n"
            "import sys\n"
            "import time\n"
            "os.setpgrp()\n"
            "with open(sys.argv[1], 'w', encoding='utf-8') as handle:\n"
            "    handle.write(str(os.getpid()) + '\\n')\n"
            "time.sleep(60)\n"
            "PY\n"
            "for _ in 1 2 3 4 5 6 7 8 9 10; do\n"
            "  [[ -s \"$FAKE_CODEX_CHILD_PID_FILE\" ]] && break\n"
            "  sleep 0.05\n"
            "done\n"
            "sleep 1.2\n"
            "exit 0\n",
            encoding="utf-8",
        )
        codex.chmod(codex.stat().st_mode | stat.S_IXUSR)
        return bin_dir

    def write_deferred_hardener_manifest(self, target: Path) -> None:
        path = target / "target" / "automation_queue" / "hardener" / "run-deferred" / "manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "role": "hardener",
                    "run_id": "run-deferred",
                    "status": "deferred",
                    "created_at": "2026-05-04T00:00:00+00:00",
                    "deferral_reason": "guardrail_violation",
                    "deferral_category": "guardrail_violation",
                    "deferral_root_cause": (
                        "Hardener removed or substantially rewrote tests without a "
                        "Test change rationale summary line."
                    ),
                    "deferral_detail": (
                        "Hardener removed or substantially rewrote tests without a "
                        "`Test change rationale:` summary line."
                    ),
                    "changed_files": ["apps/web/tests/api.auth.rate-limit.test.ts"],
                    "summary": "Ticket #76 hardener patch rewrote auth rate-limit tests.",
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    def test_source_and_template_role_runners_keep_target_contract(self) -> None:
        source = SOURCE_ROLE_RUNNER.read_text(encoding="utf-8")
        template = TEMPLATE_ROLE_RUNNER.read_text(encoding="utf-8")
        for marker in [
            "--role",
            "Runtime Summary Contract",
            "scripts/run_role_automation.sh",
            "run_process_watchdog.py",
            "integrate_role_outputs.py",
            "DIFFMOGGER_TICKET_STATE_ACTIONS_PATH",
            "DIFFMOGGER_TICKET_STATE_READONLY_SNAPSHOT",
            "ticket_state_actions_path",
            "ticket_state_snapshot_path",
            "runtime_state_action_count",
        ]:
            self.assertIn(marker, source)
            self.assertIn(marker, template)
        self.assertIn('runtime_script_dir="$script_parent/runtime"', source)
        self.assertIn('scan_roots = [".diffmogger/agentic", ".diffmogger/state"]', source)
        self.assertIn('scan_roots = [".diffmogger/agentic", ".diffmogger/state"]', template)

    def test_source_and_template_playwright_mcp_helpers_stay_synchronized(self) -> None:
        source = PLAYWRIGHT_MCP_HELPER_PATHS[0].read_text(encoding="utf-8")
        template = PLAYWRIGHT_MCP_HELPER_PATHS[1].read_text(encoding="utf-8")
        self.assertEqual(source, template)

    def test_watchdog_helper_is_runtime_wrapper(self) -> None:
        for path in WATCHDOG_HELPER_PATHS:
            text = path.read_text(encoding="utf-8")
            self.assertIn("diffmogger.runtime.run_process_watchdog", text)
            self.assertIn('"lib"', text)

    def test_env_loader_is_runtime_wrapper(self) -> None:
        for path in LOAD_ENV_HELPER_PATHS:
            text = path.read_text(encoding="utf-8")
            self.assertIn("diffmogger.runtime.load_automation_env", text)
            self.assertIn('"lib"', text)

    def test_optional_mcp_role_args_are_scoped_by_role(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            target = tmp_path / "target"
            target.mkdir()
            self.seed_git_target(target)
            self.write_text(
                target,
                ".codex/config.toml",
                """
                [mcp_servers.context7]
                command = "npx"
                args = ["-y", "@upstash/context7-mcp"]
                enabled = false
                env_vars = ["CONTEXT7_API_KEY"]

                [mcp_servers.playwright]
                command = "bash"
                args = ["scripts/run_playwright_mcp.sh"]
                enabled = false
                disabled_tools = ["browser_run_code_unsafe", "browser_file_upload"]
                """,
            )
            self.write_text(target, "scripts/run_playwright_mcp.sh", "#!/usr/bin/env bash\nexit 0\n")
            fake_bin = self.write_fake_codex(tmp_path)

            env = os.environ.copy()
            env["CODEX_AUTOMATION_PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
            env["DIFFMOGGER_BROWSER_PATH"] = "/tmp/diffmogger-browser"

            builder_log = tmp_path / "builder-args.txt"
            builder_env = env.copy()
            builder_env["CODEX_RUN_ID"] = "mcp-builder"
            builder_env["FAKE_CODEX_ARG_LOG"] = str(builder_log)
            builder_result = subprocess.run(
                ["bash", str(ROLE_RUNNER_PATHS[0]), "--target", str(target), "--role", "builder"],
                cwd=ROOT,
                env=builder_env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(builder_result.returncode, 0, builder_result.stdout + builder_result.stderr)
            builder_args = builder_log.read_text(encoding="utf-8")
            self.assertIn('mcp_servers.context7.command="npx"', builder_args)
            self.assertIn('mcp_servers.context7.env_vars=["CONTEXT7_API_KEY"]', builder_args)
            self.assertIn("mcp_servers.playwright.enabled=false", builder_args)
            self.assertNotIn('mcp_servers.playwright.command="bash"', builder_args)

            hardener_log = tmp_path / "hardener-args.txt"
            hardener_env = env.copy()
            hardener_env["CODEX_RUN_ID"] = "mcp-hardener"
            hardener_env["FAKE_CODEX_ARG_LOG"] = str(hardener_log)
            hardener_result = subprocess.run(
                ["bash", str(ROLE_RUNNER_PATHS[0]), "--target", str(target), "--role", "hardener"],
                cwd=ROOT,
                env=hardener_env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(hardener_result.returncode, 0, hardener_result.stdout + hardener_result.stderr)
            hardener_args = hardener_log.read_text(encoding="utf-8")
            self.assertIn('mcp_servers.playwright.command="bash"', hardener_args)
            self.assertIn('mcp_servers.playwright.disabled_tools=["browser_run_code_unsafe","browser_file_upload"]', hardener_args)
            self.assertIn("PLAYWRIGHT_MCP_OUTPUT_DIR", hardener_args)
            self.assertNotIn('mcp_servers.context7.command="npx"', hardener_args)
            self.assertNotIn('mcp_servers.context7.env_vars=["CONTEXT7_API_KEY"]', hardener_args)

    def test_optional_mcp_role_args_do_not_require_codex_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            target = tmp_path / "target"
            target.mkdir()
            self.seed_git_target(target)
            self.write_text(
                target,
                ".agentic/project_intake.json",
                json.dumps({"optional_mcp_servers": ["context7", "playwright"]}) + "\n",
            )
            self.write_text(target, "scripts/run_playwright_mcp.sh", "#!/usr/bin/env bash\nexit 0\n")
            fake_bin = self.write_fake_codex(tmp_path)

            env = os.environ.copy()
            env["CODEX_AUTOMATION_PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
            env["DIFFMOGGER_BROWSER_PATH"] = "/tmp/diffmogger-browser"

            planner_log = tmp_path / "planner-args.txt"
            planner_env = env.copy()
            planner_env["CODEX_RUN_ID"] = "mcp-no-config-planner"
            planner_env["FAKE_CODEX_ARG_LOG"] = str(planner_log)
            planner_result = subprocess.run(
                ["bash", str(ROLE_RUNNER_PATHS[0]), "--target", str(target), "--role", "planner"],
                cwd=ROOT,
                env=planner_env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(planner_result.returncode, 0, planner_result.stdout + planner_result.stderr)
            planner_args = planner_log.read_text(encoding="utf-8")
            self.assertIn('mcp_servers.context7.command="npx"', planner_args)
            self.assertNotIn('mcp_servers.playwright.command="bash"', planner_args)

            hardener_log = tmp_path / "hardener-args.txt"
            hardener_env = env.copy()
            hardener_env["CODEX_RUN_ID"] = "mcp-no-config-hardener"
            hardener_env["FAKE_CODEX_ARG_LOG"] = str(hardener_log)
            hardener_result = subprocess.run(
                ["bash", str(ROLE_RUNNER_PATHS[0]), "--target", str(target), "--role", "hardener"],
                cwd=ROOT,
                env=hardener_env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(hardener_result.returncode, 0, hardener_result.stdout + hardener_result.stderr)
            hardener_args = hardener_log.read_text(encoding="utf-8")
            self.assertIn('mcp_servers.playwright.command="bash"', hardener_args)
            self.assertIn('mcp_servers.playwright.required=false', hardener_args)
            manifest = json.loads((target / "target" / "automation_queue" / "hardener" / "mcp-no-config-hardener" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(["context7", "playwright"], manifest["mcp_enabled_servers"])
            self.assertEqual(["playwright"], manifest["mcp_requested_servers"])
            self.assertEqual(["playwright"], manifest["mcp_mounted_servers"])

    def test_frontend_hardener_cannot_succeed_when_playwright_skipped_without_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            target = tmp_path / "target"
            target.mkdir()
            self.seed_git_target(target)
            self.write_text(
                target,
                ".agentic/project_intake.json",
                json.dumps({"optional_mcp_servers": ["context7", "playwright"], "product_goal": "Build a frontend UI."}) + "\n",
            )
            self.write_text(target, "scripts/run_playwright_mcp.sh", "#!/usr/bin/env bash\nexit 0\n")
            fake_bin = self.write_frontend_playwright_skip_codex(tmp_path)
            env = os.environ.copy()
            env["CODEX_AUTOMATION_PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
            env["CODEX_RUN_ID"] = "frontend-playwright-skipped"
            env["DIFFMOGGER_BROWSER_PATH"] = "/tmp/diffmogger-browser"

            result = subprocess.run(
                ["bash", str(ROLE_RUNNER_PATHS[0]), "--target", str(target), "--role", "hardener"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            manifest = json.loads((target / "target" / "automation_queue" / "hardener" / "frontend-playwright-skipped" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("failed", manifest["status"])
            self.assertEqual("playwright_validation_issue", manifest["deferral_reason"])
            self.assertIn("requires Playwright snapshot/console validation", manifest["playwright_validation_detail"])

    def test_backend_hardener_playwright_skip_note_does_not_force_frontend_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            target = tmp_path / "target"
            target.mkdir()
            self.seed_git_target(target)
            self.write_text(
                target,
                ".agentic/project_intake.json",
                json.dumps({"optional_mcp_servers": ["context7", "playwright"], "product_goal": "Build a frontend UI."}) + "\n",
            )
            self.write_text(target, "scripts/run_playwright_mcp.sh", "#!/usr/bin/env bash\nexit 0\n")
            fake_bin = self.write_backend_playwright_skip_codex(tmp_path)
            env = os.environ.copy()
            env["CODEX_AUTOMATION_PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
            env["CODEX_RUN_ID"] = "backend-playwright-skipped"
            env["DIFFMOGGER_BROWSER_PATH"] = "/tmp/diffmogger-browser"

            result = subprocess.run(
                ["bash", str(ROLE_RUNNER_PATHS[0]), "--target", str(target), "--role", "hardener"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            manifest = json.loads((target / "target" / "automation_queue" / "hardener" / "backend-playwright-skipped" / "manifest.json").read_text(encoding="utf-8"))
            telemetry = json.loads(Path(manifest["mcp_telemetry_path"]).read_text(encoding="utf-8"))
            self.assertEqual("queued", manifest["status"])
            self.assertIsNone(manifest["deferral_reason"])
            self.assertEqual("not_required", manifest["playwright_validation_status"])
            self.assertTrue(telemetry["target_frontend_scope"])
            self.assertFalse(telemetry["ticket_frontend_scope"])

    def test_source_runner_keeps_sidecar_alias_paths_dotted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            target = tmp_path / "target"
            target.mkdir()
            self.seed_sidecar_git_target(target)
            fake_bin = tmp_path / "bin"
            fake_bin.mkdir()
            fake_codex = fake_bin / "codex"
            fake_codex.write_text(
                "#!/usr/bin/env bash\n"
                "worktree=\"\"\n"
                "while [[ $# -gt 0 ]]; do\n"
                "  if [[ \"$1\" == \"-C\" ]]; then worktree=\"$2\"; shift 2; continue; fi\n"
                "  shift\n"
                "done\n"
                "test -f \"$worktree/.diffmogger/agentic/roles/builder.md\" || exit 61\n"
                "test ! -e \"$worktree/diffmogger/agentic/roles/builder.md\" || exit 62\n"
                "printf 'sidecar alias check\\n' > \"$worktree/sidecar-check.txt\"\n"
                "exit 0\n",
                encoding="utf-8",
            )
            fake_codex.chmod(fake_codex.stat().st_mode | stat.S_IXUSR)

            env = os.environ.copy()
            env["CODEX_AUTOMATION_PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
            env["CODEX_RUN_ID"] = "sidecar-paths"

            result = subprocess.run(
                ["bash", str(SOURCE_ROLE_RUNNER), "--target", str(target), "--role", "builder"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse((target / "diffmogger").exists())
            self.assertTrue(
                (
                    target
                    / ".diffmogger"
                    / "runtime"
                    / "automation_queue"
                    / "builder"
                    / "sidecar-paths"
                    / "manifest.json"
                ).exists()
            )

    def test_builder_role_claims_next_pending_ticket_before_codex(self) -> None:
        for path in ROLE_RUNNER_PATHS:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    tmp_path = Path(tmp)
                    target = tmp_path / "target"
                    target.mkdir()
                    self.seed_git_target(target)
                    write_ticket_run_state(
                        target,
                        {
                            "run_id": "ticket-run",
                            "tickets": [
                                {"id": "TICKET-001", "summary": "Build first slice", "status": "pending"},
                                {
                                    "id": "TICKET-002",
                                    "summary": "Follow up",
                                    "status": "pending",
                                    "depends_on": ["TICKET-001"],
                                },
                            ],
                        },
                        actor_role="test",
                        event_type="ticket.run_seeded",
                    )
                    fake_bin = self.write_fake_codex(tmp_path)

                    env = os.environ.copy()
                    env["CODEX_AUTOMATION_PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
                    env["CODEX_RUN_ID"] = "claim-builder-ticket"

                    result = subprocess.run(
                        ["bash", str(path), "--target", str(target), "--role", "builder"],
                        cwd=ROOT,
                        env=env,
                        capture_output=True,
                        text=True,
                        check=False,
                    )

                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    queue_dir = target / "target" / "automation_queue" / "builder" / "claim-builder-ticket"
                    claim = json.loads((queue_dir / "ticket_claim.json").read_text(encoding="utf-8"))
                    loaded = load_ticket_run_state(target)
                    self.assertTrue(claim["claimed"])
                    self.assertEqual("TICKET-001", claim["selected"]["ticket"]["id"])
                    self.assertEqual("in_progress", loaded["tickets"][0]["status"])
                    self.assertEqual("builder", loaded["tickets"][0]["claimed_by"])
                    self.assertEqual("claim-builder-ticket", loaded["tickets"][0]["claimed_run_id"])

    def test_hardener_runtime_prompt_includes_recent_guardrail_deferral(self) -> None:
        for path in ROLE_RUNNER_PATHS:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    tmp_path = Path(tmp)
                    target = tmp_path / "target"
                    target.mkdir()
                    self.seed_git_target(target)
                    self.write_deferred_hardener_manifest(target)
                    fake_bin = self.write_fake_codex(tmp_path)

                    env = os.environ.copy()
                    env["CODEX_AUTOMATION_PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
                    env["CODEX_RUN_ID"] = "prompt-rationale"
                    env["CONVEYOR_DECISION_REASON"] = (
                        "candidate_done ticket cluster needs hardener verification: #76; "
                        "oldest cluster traces to builder run-builder "
                        "(apps/web/tests/api.auth.rate-limit.test.ts)"
                    )

                    result = subprocess.run(
                        ["bash", str(path), "--target", str(target), "--role", "hardener"],
                        cwd=ROOT,
                        env=env,
                        capture_output=True,
                        text=True,
                        check=False,
                    )

                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    prompt = (
                        target
                        / "target"
                        / "automation_queue"
                        / "hardener"
                        / "prompt-rationale"
                        / "runtime_prompt.md"
                    ).read_text(encoding="utf-8")

                    self.assertIn("Recent Deferred Hardener Patch Context", prompt)
                    self.assertIn("matches_current_ticket_or_files: yes", prompt)
                    self.assertIn("deferral_reason: guardrail_violation", prompt)
                    self.assertIn(
                        "deferral_root_cause: Hardener removed or substantially rewrote tests without a Test change rationale summary line.",
                        prompt,
                    )
                    self.assertIn("apps/web/tests/api.auth.rate-limit.test.ts", prompt)
                    self.assertIn("#76", prompt)
                    self.assertIn(
                        "Test change rationale: <one concise reason this preserves or improves meaningful coverage>",
                        prompt,
                    )
                    self.assertIn("whenever this hardener run touches tests", prompt)

    def test_role_worktree_seeds_ticket_run_helper_without_patch_leakage(self) -> None:
        for path in ROLE_RUNNER_PATHS:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    tmp_path = Path(tmp)
                    target = tmp_path / "target"
                    target.mkdir()
                    self.seed_git_target(target)
                    self.write_text(target, "scripts/ticket_run.py", "#!/usr/bin/env python3\nprint('ticket helper')\n")
                    fake_bin = self.write_fake_codex(tmp_path)

                    env = os.environ.copy()
                    env["CODEX_AUTOMATION_PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
                    env["CODEX_RUN_ID"] = "helper-context"

                    result = subprocess.run(
                        ["bash", str(path), "--target", str(target), "--role", "builder"],
                        cwd=ROOT,
                        env=env,
                        capture_output=True,
                        text=True,
                        check=False,
                    )

                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    worktree_helper = (
                        target
                        / "target"
                        / "automation_worktrees"
                        / "builder"
                        / "helper-context"
                        / "scripts"
                        / "ticket_run.py"
                    )
                    self.assertTrue(worktree_helper.exists(), "ticket_run.py was not seeded into the role worktree")
                    self.assertIn("ticket helper", worktree_helper.read_text(encoding="utf-8"))
                    queue_dir = target / "target" / "automation_queue" / "builder" / "helper-context"
                    patch_text = (queue_dir / "changes.patch").read_text(encoding="utf-8")
                    changed_files = (queue_dir / "changed_files.txt").read_text(encoding="utf-8")
                    self.assertNotIn("scripts/ticket_run.py", patch_text)
                    self.assertNotIn("scripts/ticket_run.py", changed_files)

    def test_role_worktree_ticket_actions_queue_without_product_patch(self) -> None:
        for path in ROLE_RUNNER_PATHS:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    tmp_path = Path(tmp)
                    target = tmp_path / "target"
                    target.mkdir()
                    self.seed_git_target(target)
                    fake_bin = self.write_ticket_action_codex(tmp_path)

                    env = os.environ.copy()
                    env["CODEX_AUTOMATION_PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
                    env["CODEX_RUN_ID"] = "ticket-action-only"

                    result = subprocess.run(
                        ["bash", str(path), "--target", str(target), "--role", "builder"],
                        cwd=ROOT,
                        env=env,
                        capture_output=True,
                        text=True,
                        check=False,
                    )

                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("status=queued", result.stdout)
                    queue_dir = target / "target" / "automation_queue" / "builder" / "ticket-action-only"
                    manifest = json.loads((queue_dir / "manifest.json").read_text(encoding="utf-8"))
                    runtime_actions = json.loads((queue_dir / "runtime_state_actions.json").read_text(encoding="utf-8"))
                    ticket_actions = json.loads((queue_dir / "ticket_state_actions.json").read_text(encoding="utf-8"))
                    changed_files = (queue_dir / "changed_files.txt").read_text(encoding="utf-8")
                    patch_text = (queue_dir / "changes.patch").read_text(encoding="utf-8")

                    self.assertEqual("queued", manifest["status"])
                    self.assertEqual("pending", manifest["runtime_state_status"])
                    self.assertEqual(1, manifest["runtime_state_action_count"])
                    self.assertEqual("update_ticket", runtime_actions["actions"][0]["action"])
                    self.assertEqual("update_ticket", ticket_actions["actions"][0]["action"])
                    self.assertEqual("", changed_files)
                    self.assertEqual("", patch_text)

    def test_role_worktree_exports_ticket_state_readonly_snapshot(self) -> None:
        for path in ROLE_RUNNER_PATHS:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    tmp_path = Path(tmp)
                    target = tmp_path / "target"
                    target.mkdir()
                    self.seed_git_target(target)
                    write_ticket_run_state(
                        target,
                        {
                            "run_id": "run-snapshot",
                            "tickets": [
                                {
                                    "id": "TICKET-001",
                                    "summary": "Build first slice",
                                    "status": "pending",
                                }
                            ],
                        },
                        actor_role="test",
                        event_type="ticket.run_seeded",
                    )
                    fake_bin = self.write_snapshot_check_codex(tmp_path)

                    env = os.environ.copy()
                    env["CODEX_AUTOMATION_PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
                    env["CODEX_RUN_ID"] = "ticket-snapshot"

                    result = subprocess.run(
                        ["bash", str(path), "--target", str(target), "--role", "builder"],
                        cwd=ROOT,
                        env=env,
                        capture_output=True,
                        text=True,
                        check=False,
                    )

                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    queue_dir = target / "target" / "automation_queue" / "builder" / "ticket-snapshot"
                    snapshot = json.loads((queue_dir / "ticket_state_snapshot.json").read_text(encoding="utf-8"))
                    tickets = snapshot["data"]["tickets"]
                    self.assertEqual("TICKET-001", tickets[0]["id"])
                    self.assertEqual("in_progress", tickets[0]["status"])

    def test_role_worktree_inherits_loaded_target_env_without_copying_env_files(self) -> None:
        for index, path in enumerate(ROLE_RUNNER_PATHS):
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    tmp_path = Path(tmp)
                    target = tmp_path / "target"
                    target.mkdir()
                    self.seed_git_target(target)
                    self.write_text(target, ".gitignore", ".env*\napps/*/.env*\n")
                    self.write_text(
                        target,
                        "apps/web/.env.local",
                        "AUTH_SECRET=file-secret-value\nAPP_LOCAL_ONLY=file-only-value\n",
                    )
                    helper = target / "scripts" / "load_automation_env.py"
                    helper.parent.mkdir(parents=True, exist_ok=True)
                    helper.write_text(LOAD_ENV_HELPER_PATHS[index].read_text(encoding="utf-8"), encoding="utf-8")
                    fake_bin = tmp_path / "bin"
                    fake_bin.mkdir()
                    fake_codex = fake_bin / "codex"
                    fake_codex.write_text(
                        "#!/usr/bin/env bash\n"
                        "worktree=\"\"\n"
                        "while [[ $# -gt 0 ]]; do\n"
                        "  if [[ \"$1\" == \"-C\" ]]; then\n"
                        "    worktree=\"$2\"\n"
                        "    shift 2\n"
                        "    continue\n"
                        "  fi\n"
                        "  shift\n"
                        "done\n"
                        "if [[ \"${CODEX_AUTOMATION_ENV_LOADED:-}\" != \"1\" ]]; then echo \"env sentinel missing\" >&2; exit 40; fi\n"
                        "if [[ \"${AUTH_SECRET:-}\" != \"shell-secret-value\" ]]; then echo \"auth secret mismatch\" >&2; exit 41; fi\n"
                        "if [[ \"${APP_LOCAL_ONLY:-}\" != \"file-only-value\" ]]; then echo \"app local env missing\" >&2; exit 42; fi\n"
                        "printf 'env inherited\\n' > \"$worktree/env-check.txt\"\n"
                        "exit 0\n",
                        encoding="utf-8",
                    )
                    fake_codex.chmod(fake_codex.stat().st_mode | stat.S_IXUSR)

                    env = os.environ.copy()
                    env["CODEX_AUTOMATION_PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
                    env["CODEX_RUN_ID"] = "env-context"
                    env["AUTH_SECRET"] = "shell-secret-value"

                    result = subprocess.run(
                        ["bash", str(path), "--target", str(target), "--role", "builder"],
                        cwd=ROOT,
                        env=env,
                        capture_output=True,
                        text=True,
                        check=False,
                    )

                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    worktree = target / "target" / "automation_worktrees" / "builder" / "env-context"
                    self.assertTrue((worktree / "env-check.txt").exists())
                    self.assertFalse((worktree / "apps" / "web" / ".env.local").exists())
                    queue_dir = target / "target" / "automation_queue" / "builder" / "env-context"
                    text_outputs = [result.stdout, result.stderr]
                    text_outputs.extend(
                        item.read_text(encoding="utf-8", errors="replace")
                        for item in queue_dir.rglob("*")
                        if item.is_file() and item.suffix not in {".z"}
                    )
                    log_dir = target / "target" / "automation_logs"
                    if log_dir.exists():
                        text_outputs.extend(
                            item.read_text(encoding="utf-8", errors="replace")
                            for item in log_dir.rglob("*")
                            if item.is_file()
                        )
                    combined = "\n".join(text_outputs)
                    self.assertNotIn("file-secret-value", combined)
                    self.assertNotIn("shell-secret-value", combined)

    def test_successful_codex_run_cleans_background_child_process_group(self) -> None:
        for path in ROLE_RUNNER_PATHS:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    tmp_path = Path(tmp)
                    target = tmp_path / "target"
                    target.mkdir()
                    self.seed_git_target(target)
                    fake_bin = self.write_leaky_child_codex(tmp_path)
                    child_pid_file = tmp_path / "codex-child.pid"

                    env = os.environ.copy()
                    env["CODEX_AUTOMATION_PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
                    env["CODEX_RUN_ID"] = "watchdog-child-cleanup"
                    env["FAKE_CODEX_CHILD_PID_FILE"] = str(child_pid_file)

                    result = subprocess.run(
                        ["bash", str(path), "--target", str(target), "--role", "builder"],
                        cwd=ROOT,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=15,
                        check=False,
                    )

                    try:
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        child_pid = int(child_pid_file.read_text(encoding="utf-8").strip())
                        deadline = time.monotonic() + 3
                        while time.monotonic() < deadline:
                            try:
                                os.kill(child_pid, 0)
                            except ProcessLookupError:
                                break
                            time.sleep(0.05)
                        with self.assertRaises(ProcessLookupError):
                            os.kill(child_pid, 0)

                        queue_dir = target / "target" / "automation_queue" / "builder" / "watchdog-child-cleanup"
                        status = json.loads((queue_dir / "codex.watchdog.json").read_text(encoding="utf-8"))
                        self.assertTrue(status["descendant_terminated"])
                        self.assertIn(child_pid, status["descendant_pids"])
                    finally:
                        if child_pid_file.exists():
                            child_pid = int(child_pid_file.read_text(encoding="utf-8").strip())
                            try:
                                os.kill(child_pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass

    def test_hanging_codex_is_timed_out_and_failed_manifest_is_written(self) -> None:
        for path in ROLE_RUNNER_PATHS:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    tmp_path = Path(tmp)
                    target = tmp_path / "target"
                    target.mkdir()
                    self.seed_git_target(target)
                    fake_bin = self.write_hanging_codex(tmp_path)
                    pid_file = tmp_path / "codex.pid"

                    env = os.environ.copy()
                    env["CODEX_AUTOMATION_PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
                    env["CODEX_RUN_ID"] = "watchdog-timeout"
                    env["CODEX_ROLE_TIMEOUT_SECONDS"] = "1"
                    env["CODEX_ROLE_TERMINATION_GRACE_SECONDS"] = "0"
                    env["FAKE_CODEX_PID_FILE"] = str(pid_file)

                    result = subprocess.run(
                        ["bash", str(path), "--target", str(target), "--role", "builder"],
                        cwd=ROOT,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=15,
                        check=False,
                    )

                    self.assertEqual(124, result.returncode, result.stdout + result.stderr)
                    queue_dir = target / "target" / "automation_queue" / "builder" / "watchdog-timeout"
                    status = json.loads((queue_dir / "codex.watchdog.json").read_text(encoding="utf-8"))
                    self.assertTrue(status["timed_out"])
                    self.assertTrue(status["terminated"])
                    self.assertTrue(status["killed"])
                    self.assertEqual(124, status["exit_code"])

                    manifest = json.loads((queue_dir / "manifest.json").read_text(encoding="utf-8"))
                    self.assertEqual("failed", manifest["status"])
                    self.assertTrue(manifest["watchdog_timed_out"])
                    self.assertEqual(124, manifest["watchdog_exit_code"])

                    summary = (queue_dir / "summary.md").read_text(encoding="utf-8")
                    self.assertIn("Watchdog timed out: true", summary)
                    self.assertIn("ROLE_RUN role=builder run_id=watchdog-timeout status=failed", result.stdout)

                    if pid_file.exists():
                        pid = int(pid_file.read_text(encoding="utf-8").strip())
                        deadline = time.monotonic() + 3
                        while time.monotonic() < deadline:
                            try:
                                os.kill(pid, 0)
                            except ProcessLookupError:
                                break
                            time.sleep(0.05)
                        with self.assertRaises(ProcessLookupError):
                            os.kill(pid, 0)

    def test_idle_hanging_codex_is_timed_out_and_marked_idle(self) -> None:
        for path in ROLE_RUNNER_PATHS:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    tmp_path = Path(tmp)
                    target = tmp_path / "target"
                    target.mkdir()
                    self.seed_git_target(target)
                    fake_bin = self.write_hanging_codex(tmp_path)
                    pid_file = tmp_path / "codex.pid"

                    env = os.environ.copy()
                    env["CODEX_AUTOMATION_PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
                    env["CODEX_RUN_ID"] = "watchdog-idle-timeout"
                    env["CODEX_ROLE_TIMEOUT_SECONDS"] = "30"
                    env["CODEX_ROLE_IDLE_TIMEOUT_SECONDS"] = "1"
                    env["CODEX_ROLE_TERMINATION_GRACE_SECONDS"] = "0"
                    env["FAKE_CODEX_PID_FILE"] = str(pid_file)

                    result = subprocess.run(
                        ["bash", str(path), "--target", str(target), "--role", "builder"],
                        cwd=ROOT,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=15,
                        check=False,
                    )

                    self.assertEqual(124, result.returncode, result.stdout + result.stderr)
                    queue_dir = target / "target" / "automation_queue" / "builder" / "watchdog-idle-timeout"
                    status = json.loads((queue_dir / "codex.watchdog.json").read_text(encoding="utf-8"))
                    self.assertTrue(status["idle_timed_out"])
                    self.assertFalse(status["timed_out"])
                    self.assertEqual("idle_timeout", status["termination_reason"])

                    manifest = json.loads((queue_dir / "manifest.json").read_text(encoding="utf-8"))
                    self.assertEqual("failed", manifest["status"])
                    self.assertTrue(manifest["watchdog_idle_timed_out"])
                    self.assertEqual(124, manifest["watchdog_exit_code"])

                    summary = (queue_dir / "summary.md").read_text(encoding="utf-8")
                    self.assertIn("Watchdog idle timed out: true", summary)

                    if pid_file.exists():
                        pid = int(pid_file.read_text(encoding="utf-8").strip())
                        deadline = time.monotonic() + 3
                        while time.monotonic() < deadline:
                            try:
                                os.kill(pid, 0)
                            except ProcessLookupError:
                                break
                            time.sleep(0.05)
                        with self.assertRaises(ProcessLookupError):
                            os.kill(pid, 0)


if __name__ == "__main__":
    unittest.main()
