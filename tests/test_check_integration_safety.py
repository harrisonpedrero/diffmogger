from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "check_integration_safety.py"
DASHBOARD_APP_PATH = ROOT / "services" / "agentic-dashboard" / "agentic_dashboard" / "app.py"


def load_checker():
    spec = importlib.util.spec_from_file_location("check_integration_safety", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_dashboard():
    spec = importlib.util.spec_from_file_location("dashboard_under_test", DASHBOARD_APP_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class IntegrationSafetyCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_checker()

    def write_text(self, root: Path, rel_path: str, text: str) -> None:
        path = root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def seed_minimal_safe_tree(self, root: Path) -> None:
        self.write_text(
            root,
            "services/agentic-notifier/agentic_notifier/config.py",
            '\n'.join(
                [
                    'notifier_api_host: str = "127.0.0.1"',
                    'webhook_host: str = "127.0.0.1"',
                    "dry_run: bool = True",
                    'dry_run=_truthy(os.getenv("DRY_RUN", "true"))',
                ]
            ),
        )
        self.write_text(
            root,
            "services/agentic-notifier/.env.example",
            '\n'.join(
                [
                    "TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                    "TWILIO_FROM=+15555555555",
                    "HUMAN_TO=+15555555555",
                    "NOTIFIER_API_HOST=127.0.0.1",
                    "WEBHOOK_HOST=127.0.0.1",
                    "WEBHOOK_PUBLIC_BASE_URL=https://example.ngrok-free.app",
                    "DRY_RUN=true",
                ]
            ),
        )
        self.write_text(
            root,
            "services/agentic-notifier/agentic_notifier/api_app.py",
            'LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}\n'
            "LOCAL_NOTIFY_API_TOKEN is required when API host is not loopback\n",
        )
        self.write_text(
            root,
            "services/agentic-notifier/scripts/send_test_notification.py",
            '"dry_run": not args.real_send\n',
        )
        self.write_text(
            root,
            "services/agentic-notifier/README.md",
            "The example config starts with `DRY_RUN=true`\n"
            "Do not expose `http://127.0.0.1:8765/api/notify` through ngrok.\n",
        )
        self.write_text(root, "scripts/scaffold_project_docs.py", 'return "file_only"\n')
        self.write_text(
            root,
            "docs/HUMAN_BRIDGE_SETUP.md",
            "No SMS, WhatsApp, Twilio, webhook, ngrok, notifier API, or messaging credentials are used in this mode.\n",
        )
        self.write_text(
            root,
            "services/agentic-dashboard/agentic_dashboard/app.py",
            "File-only handoff remains available if notifier setup is incomplete.\n"
            "allow_remotes: bool = False\n",
        )
        self.write_text(root, "README.md", "# Safe placeholder docs\n")

    def test_current_repo_passes_integration_safety(self) -> None:
        problems = self.module.check_integration_safety(ROOT)
        self.assertEqual([], problems)

    def test_detects_realistic_secret_and_non_placeholder_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.seed_minimal_safe_tree(target)
            self.write_text(
                target,
                "docs/HUMAN_BRIDGE.md",
                "Live bad values: AC" "0123456789abcdef0123456789abcdef and https://team.ngrok-free.app\n",
            )

            problems = self.module.check_integration_safety(target)

            details = "\n".join(problem.detail for problem in problems)
            self.assertIn("concrete-looking Twilio Account SID", details)
            self.assertIn("non-placeholder ngrok URL", details)

    def test_detects_missing_dry_run_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.seed_minimal_safe_tree(target)
            config = target / "services/agentic-notifier/agentic_notifier/config.py"
            config.write_text(
                config.read_text(encoding="utf-8").replace("dry_run: bool = True", "dry_run: bool = False"),
                encoding="utf-8",
            )

            problems = self.module.check_integration_safety(target)

            self.assertTrue(
                any(problem.detail == "notifier settings must default to dry-run" for problem in problems)
            )


class DashboardIntegrationSafetyAffordanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_dashboard()

    def seed_multi_role_target(self, target: Path, *, schedule_strategy: str = "continuous_conveyor") -> None:
        (target / ".agentic" / "roles").mkdir(parents=True)
        (target / "docs").mkdir()
        (target / "scripts").mkdir()
        (target / ".agentic" / "project_intake.json").write_text(
            json.dumps(
                {
                    "automation_schedule_strategy": schedule_strategy,
                    "multi_role_automations_allowed": True,
                    "human_bridge_enabled": False,
                    "human_bridge_mode": "disabled",
                }
            ),
            encoding="utf-8",
        )
        (target / ".agentic" / "automation_prompt.md").write_text("prompt", encoding="utf-8")
        for role in ("planner", "builder", "hardener", "integrator"):
            (target / ".agentic" / "roles" / f"{role}.md").write_text(role, encoding="utf-8")
        (target / "docs" / "INITIAL_BOOTSTRAP_PROMPT.md").write_text("bootstrap", encoding="utf-8")
        (target / "docs" / "CODEX_AUTOMATION_TASKS.md").write_text("AUTOMATION_STATUS: ACTIVE\n", encoding="utf-8")
        (target / "docs" / "MULTI_ROLE_PROGRESS.md").write_text("# Multi-Role Progress\n", encoding="utf-8")
        for script in (
            "run_codex_automation.sh",
            "run_conveyor_automation.sh",
            "run_conveyor_automation.py",
            "run_role_automation.sh",
            "integrate_role_outputs.py",
            "list_deferred_patches.py",
        ):
            (target / "scripts" / script).write_text("# placeholder\n", encoding="utf-8")

    def test_dashboard_smoke_check_requires_integration_safety_script(self) -> None:
        self.assertEqual(0, self.module.smoke_check())

    def test_target_has_initial_commit_rejects_unborn_git_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=target, check=True)

            self.assertFalse(self.module.target_has_initial_commit(target))

    def test_target_has_initial_commit_accepts_repo_with_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=target, check=True)
            subprocess.run(["git", "config", "user.email", "t@example.test"], cwd=target, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=target, check=True)
            subprocess.run(["git", "commit", "--allow-empty", "-m", "chore: initial commit", "-q"], cwd=target, check=True)

            self.assertTrue(self.module.target_has_initial_commit(target))

    def test_automation_ready_rejects_conveyor_target_without_initial_commit(self) -> None:
        if not hasattr(self.module, "DiffmoggerDashboard"):
            self.skipTest("Tk dashboard class is unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.seed_multi_role_target(target, schedule_strategy="continuous_conveyor")
            subprocess.run(["git", "init", "-q"], cwd=target, check=True)
            dashboard = object.__new__(self.module.DiffmoggerDashboard)

            ready, reason = dashboard._automation_ready(target)

            self.assertFalse(ready)
            self.assertIn("initial commit", reason)

    def test_automation_ready_accepts_conveyor_target_with_initial_commit(self) -> None:
        if not hasattr(self.module, "DiffmoggerDashboard"):
            self.skipTest("Tk dashboard class is unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.seed_multi_role_target(target, schedule_strategy="continuous_conveyor")
            subprocess.run(["git", "init", "-q"], cwd=target, check=True)
            subprocess.run(["git", "config", "user.email", "t@example.test"], cwd=target, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=target, check=True)
            subprocess.run(["git", "commit", "--allow-empty", "-m", "chore: initial commit", "-q"], cwd=target, check=True)
            dashboard = object.__new__(self.module.DiffmoggerDashboard)

            ready, reason = dashboard._automation_ready(target)

            self.assertTrue(ready)
            self.assertEqual("Ready.", reason)

    def test_integration_safety_command_uses_selected_kit_like_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target / "scripts").mkdir()
            (target / "scripts" / "check_integration_safety.py").write_text("", encoding="utf-8")
            (target / "services" / "agentic-notifier").mkdir(parents=True)

            command = self.module.integration_safety_command(target)

            self.assertEqual(sys.executable, command[0])
            self.assertEqual(str(self.module.INTEGRATION_SAFETY_SCRIPT), command[1])
            self.assertEqual(str(target.resolve()), command[2])

    def test_integration_safety_command_falls_back_to_kit_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            command = self.module.integration_safety_command(Path(tmp))

            self.assertEqual(str(ROOT), command[2])

    def test_write_integration_safety_record_creates_target_local_marker(self) -> None:
        with tempfile.TemporaryDirectory() as selected_tmp, tempfile.TemporaryDirectory() as checked_tmp:
            selected = Path(selected_tmp)
            checked = Path(checked_tmp)
            command = [sys.executable, str(self.module.INTEGRATION_SAFETY_SCRIPT), str(checked)]

            record_path = self.module.write_integration_safety_record(selected, checked, command, 0)

            self.assertEqual(selected.resolve() / self.module.INTEGRATION_SAFETY_RECORD_RELATIVE, record_path)
            record = json.loads(record_path.read_text(encoding="utf-8"))
            self.assertEqual(1, record["schema_version"])
            self.assertEqual("dashboard_run_safety_check", record["source"])
            self.assertEqual("pass", record["status"])
            self.assertEqual(0, record["exit_code"])
            self.assertEqual(str(selected.resolve()), record["selected_target"])
            self.assertEqual(str(checked.resolve()), record["checked_target"])
            self.assertIn("check_integration_safety.py", record["command"])
            self.assertIn("Dashboard Run Safety Check passed", record["summary"])

    def test_review_bundle_command_exports_standard_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)

            command = self.module.review_bundle_command(target)

            self.assertEqual(sys.executable, command[0])
            self.assertEqual(str(self.module.OBSERVATORY_SCRIPT), command[1])
            self.assertIn("--target", command)
            self.assertIn(str(target.resolve()), command)
            self.assertIn("--review-dir", command)
            self.assertIn("/tmp/Diffmogger-review", command)

    def test_worker_strategy_summary_formats_dashboard_state(self) -> None:
        strategy = {
            "strategy": "WRITE_WORKERS",
            "parallelism_budget": 2,
            "action_lane": "builder",
            "summary": "Use up to two bounded write workers when the work splits cleanly.",
        }

        summary = self.module.worker_strategy_summary(strategy)

        self.assertIn("WRITE_WORKERS / budget 2 / lane builder", summary)
        self.assertIn("Use up to two bounded write workers", summary)

    def test_worker_summary_command_uses_target_helper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)

            command = self.module.worker_summary_command(target, "dashboard-worker-run")

            self.assertEqual(sys.executable, command[0])
            self.assertEqual(str(target.resolve() / "scripts" / "summarize_worker_outputs.py"), command[1])
            self.assertIn(str(target.resolve()), command)
            self.assertEqual("dashboard-worker-run", command[-1])

    def test_latest_worker_result_surfaces_ready_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            run_dir = target / "target" / "agent_runs" / "run-001"
            run_dir.mkdir(parents=True)
            (run_dir / "worker_review.md").write_text("# Worker Report\n", encoding="utf-8")
            summary = run_dir / "summary.md"
            summary.write_text("# Worker Output Summary\n", encoding="utf-8")

            result = self.module.latest_worker_result(target)

            self.assertEqual("run-001", result["run_id"])
            self.assertEqual(1, result["report_count"])
            self.assertTrue(result["summary_exists"])
            self.assertEqual(str(summary.resolve()), result["summary_path"])
            self.assertIn("summary ready", result["label"])

    def test_latest_worker_result_uses_newest_worker_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            old_run = target / "target" / "agent_runs" / "old-run"
            new_run = target / "target" / "agent_runs" / "new-run"
            old_run.mkdir(parents=True)
            new_run.mkdir(parents=True)
            old_report = old_run / "worker_review.md"
            new_report = new_run / "worker_builder.md"
            old_report.write_text("# old\n", encoding="utf-8")
            new_report.write_text("# new\n", encoding="utf-8")
            os.utime(old_report, (1, 1))
            os.utime(new_report, (2, 2))

            result = self.module.latest_worker_result(target)

            self.assertEqual("new-run", result["run_id"])
            self.assertFalse(result["summary_exists"])
            self.assertIn("summary not generated yet", result["label"])

    def test_read_only_worker_command_uses_target_helper_and_strategy_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            strategy = {
                "strategy": "READ_ONLY_REPORTS",
                "parallelism_budget": 1,
                "action_lane": "hardener",
                "summary": "Use one read-only worker report for broad hardener review.",
                "next_steps": ["Inspect validation gaps."],
            }

            command = self.module.read_only_worker_command(target, strategy, run_id="dashboard-test")

            self.assertEqual("bash", command[0])
            self.assertEqual(str(target.resolve() / "scripts" / "spawn_worker_agent.sh"), command[1])
            self.assertIn("--read-only", command)
            self.assertIn("hardener_strategy", command)
            self.assertIn("dashboard-test", command)
            self.assertIn("Inspect validation gaps.", command[-1])

    def test_write_worker_command_requires_explicit_ownership_argument(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            strategy = {
                "strategy": "WRITE_WORKERS",
                "parallelism_budget": 2,
                "action_lane": "builder",
            }

            command = self.module.write_worker_command(
                target,
                strategy,
                "services/example/** and tests/example/** only",
                run_id="dashboard-write-test",
            )

            self.assertEqual(str(target.resolve() / "scripts" / "spawn_worker_agent.sh"), command[1])
            self.assertIn("--write", command)
            self.assertIn("--ownership", command)
            self.assertIn("services/example/** and tests/example/** only", command)
            self.assertIn("dashboard-write-test", command)

    def test_write_worker_command_rejects_blank_ownership_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)

            with self.assertRaisesRegex(ValueError, "ownership scope"):
                self.module.write_worker_command(
                    target,
                    {"strategy": "WRITE_WORKERS", "action_lane": "builder"},
                    " \n\t ",
                    run_id="dashboard-write-test",
                )

    def test_write_worker_command_normalizes_ownership_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)

            command = self.module.write_worker_command(
                target,
                {"strategy": "WRITE_WORKERS", "action_lane": "builder"},
                "  services/example/**\n  and tests/example/** only  ",
                run_id="dashboard-write-test",
            )

            ownership_index = command.index("--ownership") + 1
            self.assertEqual("services/example/** and tests/example/** only", command[ownership_index])

    def test_integration_only_command_runs_target_local_integrator_role(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)

            command = self.module.integration_only_command(target, run_id="dashboard-integrator-test")

            self.assertEqual("env", command[0])
            self.assertIn("CODEX_RUN_ID=dashboard-integrator-test", command)
            self.assertIn(str(target.resolve() / "scripts" / "run_role_automation.sh"), command)
            self.assertEqual("integrator", command[-1])


if __name__ == "__main__":
    unittest.main()
