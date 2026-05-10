from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import textwrap
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
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
        ]:
            self.assertIn(marker, source)
            self.assertIn(marker, template)
        self.assertIn('runtime_script_dir="$script_parent/runtime"', source)

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


if __name__ == "__main__":
    unittest.main()
