from __future__ import annotations

import json
import argparse
import contextlib
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
from diffmogger.dashboard.shared import PrerequisiteItem as SharedPrerequisiteItem
from diffmogger.runtime.paths import sidecar_rel
from diffmogger.runtime.state_store import database_path_for_target, load_ticket_run_state, write_ticket_run_state

CLI = ROOT / "scripts" / "dashboard_backend_cli.py"
CLI_MODULE = ROOT / "src" / "diffmogger" / "dashboard" / "backend_cli.py"
SCAFFOLD = ROOT / "scripts" / "scaffold_project_docs.py"
GENERIC_INTAKE = ROOT / "examples" / "generic-web-app" / "project_intake.md"


def generated_path(target: Path, legacy_rel: str) -> Path:
    return target / sidecar_rel(legacy_rel)


class DashboardBackendCliTests(unittest.TestCase):
    def run_cli(
        self,
        *args: str,
        env: dict[str, str] | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        result = subprocess.run(
            [sys.executable, str(CLI), *args],
            cwd=ROOT,
            env={**os.environ, **(env or {})},
            capture_output=True,
            text=True,
            check=False,
        )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:  # pragma: no cover - assertion helper.
            self.fail(f"CLI did not return JSON stdout: {exc}\nstdout={result.stdout!r}\nstderr={result.stderr!r}")
        self.assertEqual("", result.stderr)
        self.assertIn("ok", payload)
        self.assertEqual(1, payload.get("schema_version"))
        return result, payload

    def scaffold_target(self, target: Path) -> None:
        subprocess.run(
            [
                sys.executable,
                str(SCAFFOLD),
                "--intake",
                str(GENERIC_INTAKE),
                "--target",
                str(target),
                "--force",
            ],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )

    def test_state_snapshot_initializes_canonical_sqlite_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_target(target)

            result, payload = self.run_cli("state.snapshot", "--target", str(target))

            self.assertEqual(0, result.returncode)
            self.assertTrue(payload["ok"])
            data = payload["data"]
            assert isinstance(data, dict)
            state = data["state"]
            assert isinstance(state, dict)
            self.assertEqual("sqlite", state["authority"])
            self.assertEqual("ok", state["status"])
            self.assertGreaterEqual(state["counts"]["events"], 1)
            self.assertTrue(Path(state["database"]["path"]).exists())
            self.assertEqual("sqlite", state["conveyor_machine"]["authority"])
            self.assertEqual("intake", state["conveyor_machine"]["current_stage"])
            self.assertTrue(state["capability_manifest"]["digest"])

    def test_state_brief_command_writes_agent_readable_view(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_target(target)

            result, payload = self.run_cli("state.brief", "--target", str(target))

            self.assertEqual(0, result.returncode)
            self.assertTrue(payload["ok"])
            data = payload["data"]
            assert isinstance(data, dict)
            brief = data["brief"]
            assert isinstance(brief, dict)
            self.assertTrue(Path(str(brief["path"])).exists())
            self.assertEqual(sidecar_rel("target/canonical_state_brief.md"), brief["relative_path"])
            self.assertIn("# Canonical State Brief", brief["markdown"])
            self.assertIn("agent_rule: read this brief", brief["markdown"])

    def scaffold_ticket_target(self, target: Path) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as intake:
            intake.write(
                json.dumps(
                    {
                        "project_name": "Ticket UX Smoke",
                        "project_mode": "fresh_project",
                        "product_goal": "Manage a bounded local ticket campaign.",
                        "target_user": "Maintainers",
                        "desired_first_demo": "Tickets can be inspected and edited locally.",
                        "human_bridge_enabled": False,
                        "human_bridge_mode": "disabled",
                        "automation_run_mode": "ticket_campaign",
                        "verification_commands": ["python3 -m unittest"],
                        "ticket_run_seed_tickets": [
                            {
                                "id": "TICKET-001",
                                "summary": "Create the local queue",
                                "status": "pending",
                                "acceptance_criteria": ["Queue is visible"],
                                "verification_commands": ["python3 -m unittest"],
                            },
                            {
                                "id": "TICKET-002",
                                "summary": "Document the queue",
                                "depends_on": ["TICKET-001"],
                                "status": "pending",
                            },
                        ],
                    }
                )
            )
            intake_path = Path(intake.name)
        try:
            subprocess.run(
                [
                    sys.executable,
                    str(SCAFFOLD),
                    "--intake",
                    str(intake_path),
                    "--target",
                    str(target),
                    "--force",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
            )
        finally:
            intake_path.unlink(missing_ok=True)

    def load_cli_module(self):
        spec = importlib.util.spec_from_file_location("dashboard_backend_cli_test", CLI_MODULE)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_environment_diagnostics_runs_without_target_and_uses_effective_path(self) -> None:
        path_override = "/tmp/diffmogger-test-bin"
        result, payload = self.run_cli(
            "diagnostics.environment",
            env={"CODEX_AUTOMATION_PATH": path_override},
        )

        self.assertEqual(0, result.returncode)
        self.assertTrue(payload["ok"])
        data = payload["data"]
        self.assertEqual("guide_and_copy", data["setup_mode"])
        runtime = data["runtime_environment"]
        self.assertEqual(path_override, runtime["codex_automation_path_override"])
        self.assertEqual(path_override, runtime["effective_path"].split(os.pathsep)[0])
        self.assertIn("backend_python_version", runtime)
        self.assertIn("kit_root", runtime)
        self.assertIsInstance(runtime["tools"], list)
        self.assertTrue(any(item["name"] == "python3" for item in runtime["tools"]))
        self.assertTrue(any(item["id"] == "rerun-native-checks" for item in data["fix_suggestions"]))

    def test_backend_dotenv_loader_uses_shared_parser_without_overriding_env(self) -> None:
        module = self.load_cli_module()
        with tempfile.TemporaryDirectory() as tmp:
            kit_root = Path(tmp)
            (kit_root / ".env").write_text(
                "DIFFMOGGER_DOTENV_TEST_VALUE=from-dotenv\n"
                "DIFFMOGGER_DOTENV_EXISTING_VALUE=from-dotenv\n",
                encoding="utf-8",
            )

            old_new_value = os.environ.pop("DIFFMOGGER_DOTENV_TEST_VALUE", None)
            old_existing_value = os.environ.get("DIFFMOGGER_DOTENV_EXISTING_VALUE")
            os.environ["DIFFMOGGER_DOTENV_EXISTING_VALUE"] = "from-env"
            try:
                with mock.patch.object(module, "KIT_ROOT", kit_root):
                    loaded = module.load_repo_dotenv_for_backend()

                self.assertEqual(1, loaded)
                self.assertEqual("from-dotenv", os.environ.get("DIFFMOGGER_DOTENV_TEST_VALUE"))
                self.assertEqual("from-env", os.environ.get("DIFFMOGGER_DOTENV_EXISTING_VALUE"))
            finally:
                if old_new_value is None:
                    os.environ.pop("DIFFMOGGER_DOTENV_TEST_VALUE", None)
                else:
                    os.environ["DIFFMOGGER_DOTENV_TEST_VALUE"] = old_new_value
                if old_existing_value is None:
                    os.environ.pop("DIFFMOGGER_DOTENV_EXISTING_VALUE", None)
                else:
                    os.environ["DIFFMOGGER_DOTENV_EXISTING_VALUE"] = old_existing_value

    def write_ready_automation_target(self, target: Path) -> None:
        files = {
            ".agentic/project_intake.json": '{"multi_role_automations_allowed": false}\n',
            ".agentic/automation_prompt.md": "# Automation\n",
            "docs/INITIAL_BOOTSTRAP_PROMPT.md": "# Bootstrap\n",
            "docs/CODEX_AUTOMATION_TASKS.md": "AUTOMATION_STATUS: ACTIVE\n\nCurrent baseline: bootstrapped.\n",
            "scripts/run_codex_automation.sh": "#!/usr/bin/env bash\nexit 0\n",
            "scripts/run_conveyor_automation.py": "print('conveyor')\n",
            "scripts/run_conveyor_automation.sh": (
                "#!/usr/bin/env bash\n"
                "trap 'exit 0' TERM INT\n"
                "while true; do sleep 1; done\n"
            ),
        }
        for rel, content in files.items():
            path = generated_path(target, rel)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def write_populated_ticket_campaign_target(self, target: Path) -> None:
        self.write_ready_automation_target(target)
        generated_path(target, ".agentic/project_intake.json").write_text(
            json.dumps(
                {
                    "multi_role_automations_allowed": False,
                    "automation_run_mode": "ticket_campaign",
                    "ticket_run_file": "",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        generated_path(target, "docs/CODEX_AUTOMATION_TASKS.md").write_text(
            """AUTOMATION_STATUS: ACTIVE

## Current Project State

- Current baseline: not bootstrapped yet.

## Known Issues

- Ticket queue still needs to be populated or confirmed.
- Verification commands may need adjustment after bootstrap.
""",
            encoding="utf-8",
        )
        write_ticket_run_state(
            target,
            {
                "run_id": "test-ticket-campaign",
                "halt_when_complete": True,
                "tickets": [
                    {
                        "id": "TICKET-001",
                        "summary": "Build the first useful slice",
                        "status": "pending",
                        "acceptance_criteria": ["A useful slice exists"],
                        "verification_commands": ["python3 -m unittest"],
                    }
                ],
            },
            actor_role="test",
            event_type="ticket.run_seeded",
        )

    def fake_dashboard_for_automation(self):
        module = self.load_cli_module()

        class FakeDashboard:
            STARTABLE_STATUSES = {"ACTIVE", "ACTIVE_WITH_PENDING_USER_INPUT"}
            WORKER_REPORT_STRATEGIES = {"READ_ONLY_REPORTS", "WRITE_WORKERS"}

            PrerequisiteItem = SharedPrerequisiteItem

            def target_has_initial_commit(self, _target: Path) -> bool:
                return True

            def check_prerequisites(self, *_args, **_kwargs) -> list[object]:
                return []

            def optional_mcp_servers_from_value(self, _value: object) -> list[str]:
                return []

            def required_failures(self, items: list[object]) -> list[object]:
                return [item for item in items if getattr(item, "required", False) and not getattr(item, "ok", False)]

            def automation_environment(self, _target: Path, *, allow_remotes: bool = False) -> dict[str, str]:
                return {"PATH": os.environ.get("PATH", ""), "HOME": str(Path.home())}

            def dashboard_run_id(self, prefix: str) -> str:
                return f"{prefix}-test"

            def latest_worker_result(self, _target: Path) -> dict[str, object]:
                return {"label": "Latest worker result: none yet."}

        return module, FakeDashboard()

    def test_populated_ticket_campaign_can_start_initial_bootstrap(self) -> None:
        from diffmogger.observatory.snapshots import build_snapshot

        module, fake_dashboard = self.fake_dashboard_for_automation()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            target.mkdir()
            self.write_populated_ticket_campaign_target(target)

            ready, reason = module.automation_ready(target, fake_dashboard)
            snapshot = build_snapshot(target)

            self.assertTrue(ready)
            self.assertIn("TICKET-001", reason)
            self.assertNotIn("Ticket queue still needs to be populated or confirmed.", snapshot["task"]["known_issues"])
            self.assertEqual("Verification commands may need adjustment after bootstrap.", snapshot["task"]["known_issue"])

    def test_automation_ready_uses_typed_status_not_task_markdown(self) -> None:
        module, fake_dashboard = self.fake_dashboard_for_automation()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            target.mkdir()
            self.write_ready_automation_target(target)

            first_ready, _first_reason = module.automation_ready(target, fake_dashboard)
            generated_path(target, "docs/CODEX_AUTOMATION_TASKS.md").write_text(
                "AUTOMATION_STATUS: CRITICAL_STOP\n",
                encoding="utf-8",
            )
            second_ready, second_reason = module.automation_ready(target, fake_dashboard)

            self.assertTrue(first_ready)
            self.assertTrue(second_ready)
            self.assertEqual("Ready.", second_reason)

    def test_resolved_role_worktree_ticket_issue_is_filtered(self) -> None:
        from diffmogger.observatory.snapshots import build_snapshot

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            target.mkdir()
            self.write_populated_ticket_campaign_target(target)
            generated_path(target, ".diffmogger/manifest.json").write_text(
                json.dumps({"schema_version": 1, "layout": "sidecar_v1"}),
                encoding="utf-8",
            )
            write_ticket_run_state(
                target,
                {
                    "run_id": "test-ticket-campaign",
                    "halt_when_complete": True,
                    "tickets": [
                        {
                            "id": "TICKET-001",
                            "summary": "Build the first useful slice",
                            "status": "pending",
                        }
                    ],
                },
                actor_role="test",
                event_type="ticket.run_seeded",
            )
            generated_path(target, "docs/CODEX_AUTOMATION_TASKS.md").write_text(
                """AUTOMATION_STATUS: ACTIVE

## Current Project State

- Current baseline: ticket helper repaired.

## Known Issues

- Canonical state reports 4 pending tickets, but the isolated role-worktree `ticket_run.py . status --json` helper currently reports 0 tickets from `target/orchestration.sqlite3`.
- Invoking the ticket helper against the main target path from this role sandbox fails to open the canonical SQLite database, so role worktrees cannot currently mutate dashboard ticket state directly.
- Canonical ticket helper read-only commands currently fail in this role worktree with `sqlite3.OperationalError: unable to open database file`.
- Isolated builder/hardener worktrees cannot currently run canonical `ticket_run.py . status --json` or `next --json` because opening the canonical SQLite path fails under the role sandbox.
- Verification commands may need adjustment after bootstrap.
""",
                encoding="utf-8",
            )
            helper = (
                generated_path(target, "target/automation_worktrees")
                / "builder"
                / "run-1"
                / ".diffmogger"
                / "lib"
                / "diffmogger"
                / "runtime"
                / "ticket_run.py"
            )
            helper.parent.mkdir(parents=True)
            helper.write_text(
                "def canonical_target_from_role_worktree(path):\n    return None\n"
                "def resolve_ticket_target(path):\n    return path\n",
                encoding="utf-8",
            )

            snapshot = build_snapshot(target)

            self.assertNotIn("Canonical state reports", " ".join(snapshot["task"]["known_issues"]))
            self.assertNotIn("role worktrees cannot currently mutate", " ".join(snapshot["task"]["known_issues"]))
            self.assertNotIn("Canonical ticket helper read-only commands", " ".join(snapshot["task"]["known_issues"]))
            self.assertNotIn("worktrees cannot currently run canonical", " ".join(snapshot["task"]["known_issues"]))
            self.assertEqual("Verification commands may need adjustment after bootstrap.", snapshot["task"]["known_issue"])

    def test_automation_start_stop_and_idempotent_running_state(self) -> None:
        module, fake_dashboard = self.fake_dashboard_for_automation()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            target.mkdir()
            self.write_ready_automation_target(target)
            args = argparse.Namespace(target=str(target), stream_jsonl=False)

            with mock.patch.object(module, "load_dashboard_module", return_value=fake_dashboard):
                started = module.command_automation_start(args)
                second = module.command_automation_start(args)
                stopped = module.command_automation_stop(args)

            self.assertTrue(started["started"])
            self.assertFalse(second["started"])
            self.assertEqual(started["runner"]["pid"], second["runner"]["pid"])
            self.assertTrue(stopped["stopped"])
            self.assertEqual("stopped", stopped["runner"]["state"])
            self.assertTrue((target / "target/automation_logs/conveyor.runner.stdout.log").exists())

    def test_automation_start_recovers_stale_runner_pid(self) -> None:
        module, fake_dashboard = self.fake_dashboard_for_automation()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            target.mkdir()
            self.write_ready_automation_target(target)
            module.write_runner_state(target, {"state": "running", "pid": 999999999, "started_at": "old"})
            args = argparse.Namespace(target=str(target), stream_jsonl=False)

            with mock.patch.object(module, "load_dashboard_module", return_value=fake_dashboard):
                payload = module.command_automation_start(args)
                stopped = module.command_automation_stop(args)

            self.assertTrue(payload["started"])
            self.assertNotEqual(999999999, payload["runner"]["pid"])
            self.assertTrue(stopped["stopped"])

    def test_automation_stop_is_noop_when_runner_is_not_alive(self) -> None:
        module, fake_dashboard = self.fake_dashboard_for_automation()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            target.mkdir()
            self.write_ready_automation_target(target)
            args = argparse.Namespace(target=str(target), stream_jsonl=False)

            with mock.patch.object(module, "load_dashboard_module", return_value=fake_dashboard):
                payload = module.command_automation_stop(args)

            self.assertFalse(payload["stopped"])
            self.assertEqual("automation_stop_noop", json.loads(generated_path(target, ".agentic/dashboard_state.json").read_text(encoding="utf-8"))["last_action"])

    def test_run_load_exposes_baseline_recheck_blocker_action(self) -> None:
        module, fake_dashboard = self.fake_dashboard_for_automation()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            target.mkdir()
            self.write_ready_automation_target(target)
            baseline_path = generated_path(target, "target/baseline_verification.json")
            baseline_path.parent.mkdir(parents=True, exist_ok=True)
            baseline_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "status": "blocked_environment",
                        "category": "missing_env_var",
                        "root_cause": "Missing required environment variable DATABASE_URL.",
                        "failure_signature": "verification_environment_failure:missing_env_var:abc",
                        "checks_run": ["npm test"],
                        "detail": "$ npm test\nexit=1\nDATABASE_URL missing",
                    }
                ),
                encoding="utf-8",
            )
            args = argparse.Namespace(target=str(target), stream_jsonl=False)

            with mock.patch.object(module, "load_dashboard_module", return_value=fake_dashboard):
                payload = module.command_run_load(args)

            blockers = payload["environment_blockers"]
            baseline = next(item for item in blockers if item.get("kind") == "baseline_verification")
            self.assertEqual("Recheck blocker", baseline["recheck_label"])
            self.assertEqual("blocker.recheck_baseline", baseline["recheck_command"])
            self.assertTrue(baseline["can_recheck"])

    def test_blocker_recheck_baseline_runs_forced_loaded_recheck(self) -> None:
        module, fake_dashboard = self.fake_dashboard_for_automation()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            target.mkdir()
            self.write_ready_automation_target(target)
            calls: list[dict[str, object]] = []

            def fake_run_subprocess(args, command, *, cwd, stage, env=None):
                calls.append({"command": command, "cwd": cwd, "stage": stage, "env": env})
                baseline_path = target / "target" / "baseline_verification.json"
                baseline_path.parent.mkdir(parents=True, exist_ok=True)
                baseline_path.write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "status": "passing",
                            "category": "",
                            "root_cause": "",
                            "checks_run": ["python3 -m unittest"],
                            "detail": "ok",
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                return {"command": "baseline recheck", "exit_code": 0, "stdout": "ok", "stderr": ""}

            args = argparse.Namespace(target=str(target), stream_jsonl=False)
            with (
                mock.patch.object(module, "load_dashboard_module", return_value=fake_dashboard),
                mock.patch.object(module._run_control, "run_subprocess_streamed", side_effect=fake_run_subprocess),
            ):
                payload = module.command_blocker_recheck_baseline(args)

            self.assertEqual("pass", payload["status"])
            self.assertEqual("passing", payload["baseline_verification"]["status"])
            command = [str(item) for item in calls[0]["command"]]
            self.assertIn("load_automation_env.py", " ".join(command))
            self.assertIn("--force-baseline", command)
            self.assertIn("--baseline-only", command)
            dashboard_state = json.loads(generated_path(target, ".agentic/dashboard_state.json").read_text(encoding="utf-8"))
            self.assertEqual("baseline_recheck_passed", dashboard_state["last_action"])

    def test_missing_target_returns_structured_json_error(self) -> None:
        missing = Path(tempfile.gettempdir()) / "diffmogger-backend-missing-target"

        result, payload = self.run_cli("project.load_snapshot", "--target", str(missing))

        self.assertNotEqual(0, result.returncode)
        self.assertFalse(payload["ok"])
        self.assertEqual("project.load_snapshot", payload["command"])
        self.assertIn("Target path does not exist", payload["message"])
        self.assertEqual("invalid_target", payload["error"]["type"])

    def test_empty_target_returns_structured_json_error(self) -> None:
        result, payload = self.run_cli("project.load_snapshot", "--target", "")

        self.assertEqual(2, result.returncode)
        self.assertFalse(payload["ok"])
        self.assertEqual("project.load_snapshot", payload["command"])
        self.assertEqual("invalid_target", payload["error"]["type"])
        self.assertIn("target path is required", payload["message"].lower())

    def test_file_target_returns_structured_json_error(self) -> None:
        with tempfile.NamedTemporaryFile() as tmp:
            result, payload = self.run_cli("project.load_snapshot", "--target", tmp.name)

        self.assertEqual(2, result.returncode)
        self.assertFalse(payload["ok"])
        self.assertEqual("project.load_snapshot", payload["command"])
        self.assertEqual("invalid_target", payload["error"]["type"])
        self.assertIn("must be a directory", payload["message"])

    def test_missing_required_argument_returns_json_error(self) -> None:
        result, payload = self.run_cli("brief.load")

        self.assertEqual(2, result.returncode)
        self.assertFalse(payload["ok"])
        self.assertIn("required", payload["message"])

    def test_project_snapshot_supports_empty_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result, payload = self.run_cli("project.load_snapshot", "--target", tmp)

            self.assertEqual(0, result.returncode)
            self.assertTrue(payload["ok"])
            data = payload["data"]
            self.assertEqual(Path(tmp).resolve().name, data["target"]["name"])
            self.assertFalse(data["target"]["is_diffmogger_project"])
            self.assertEqual("UNKNOWN", data["home"]["automation_status"])
            self.assertIn("run", data)
            self.assertFalse(data["run"]["controls"]["is_scaffolded"])
            self.assertNotIn("can_run_now", data["run"]["controls"])
            self.assertEqual("not_ready", data["run"]["automation"]["state"])

    def test_unconfigured_target_smoke_supports_initial_native_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _brief_result, brief = self.run_cli("brief.load", "--target", tmp)
            self.assertTrue(brief["ok"])
            self.assertFalse(brief["data"]["target"]["is_diffmogger_project"])

            _run_result, run = self.run_cli("run.load", "--target", tmp)
            self.assertTrue(run["ok"])
            self.assertFalse(run["data"]["controls"]["is_scaffolded"])
            self.assertNotIn("can_run_now", run["data"]["controls"])

            _diagnostics_result, diagnostics = self.run_cli("diagnostics.run_checks", "--target", tmp)
            self.assertTrue(diagnostics["ok"])
            self.assertIn("prerequisites", diagnostics["data"])
            self.assertIn("backend", diagnostics["data"])
            self.assertIn("runtime_environment", diagnostics["data"])
            self.assertIn("fix_suggestions", diagnostics["data"])
            prereq_items = diagnostics["data"]["prerequisites"]["items"]
            self.assertFalse(any("retired dashboard" in item["name"].lower() for item in prereq_items))

            _list_result, files = self.run_cli("advanced.list_files", "--target", tmp)
            self.assertTrue(files["ok"])
            file_keys = {item["key"] for item in files["data"]["files"]}
            self.assertIn("state.dashboard", file_keys)
            self.assertIn("monitor.automation_tasks", file_keys)

            save_result, save_payload = self.run_cli(
                "advanced.save_file",
                "--target",
                tmp,
                "--file-key",
                "state.dashboard",
                "--content",
                "{}\n",
            )
            self.assertEqual(0, save_result.returncode)
            self.assertTrue(save_payload["ok"])

            _load_result, loaded = self.run_cli(
                "advanced.load_file",
                "--target",
                tmp,
                "--file-key",
                "state.dashboard",
            )
            self.assertTrue(loaded["ok"])
            self.assertEqual("{}\n", loaded["data"]["content"])

    def test_brief_draft_save_and_load_round_trips_dashboard_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intake = {
                "project_name": "Draft Round Trip",
                "project_mode": "existing_project",
                "product_goal": "Keep a reusable dashboard intake draft.",
                "target_user": "Automation maintainers",
                "desired_first_demo": "A saved draft can be reopened.",
                "tech_preferences": ["Python", "React"],
                "verification_commands": ["python -m unittest"],
                "safety_constraints": ["Do not store secrets."],
                "automation_must_never_do": ["Push without review."],
                "human_bridge_enabled": True,
                "human_bridge_mode": "file_only",
                "worker_agents_allowed": True,
                "write_worker_agents_allowed": True,
                "max_write_worker_count": 2,
                "multi_role_automations_allowed": True,
                "automation_run_mode": "continuous_improvement",
                "optional_mcp_servers": ["context7"],
                "additional_context_files": [],
            }

            save_result, save_payload = self.run_cli(
                "brief.save_draft",
                "--target",
                tmp,
                "--intake-json",
                json.dumps(intake),
            )
            self.assertEqual(0, save_result.returncode)
            self.assertTrue(save_payload["ok"])
            state_path = Path(save_payload["data"]["dashboard_state_path"])
            self.assertTrue(state_path.exists())

            _load_result, load_payload = self.run_cli("brief.load", "--target", tmp)
            self.assertEqual("Draft Round Trip", load_payload["data"]["draft_intake"]["project_name"])
            self.assertEqual("existing_project", load_payload["data"]["project_mode"])
            self.assertEqual("brief_draft_saved", load_payload["data"]["dashboard_state"]["last_action"])
            self.assertEqual("pnpm" if (Path(tmp) / "pnpm-lock.yaml").exists() else "unknown", load_payload["data"]["detected"]["package_manager"])

    def test_brief_generate_intake_uses_low_cortisol_ticket_defaults(self) -> None:
        from diffmogger.dashboard.commands import brief as brief_commands

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            prompts: list[str] = []

            def fake_intake_generation(prompt, **_kwargs):
                prompts.append(prompt)
                if "Generate Diffmogger ticket_run_seed_tickets" in prompt:
                    stdout = json.dumps(
                        {
                            "ticket_run_seed_tickets": [
                                {
                                    "id": "TICKET-001",
                                    "summary": "Create the first planning flow",
                                    "status": "pending",
                                }
                            ]
                        }
                    )
                else:
                    stdout = json.dumps(
                        {
                            "project_name": "Gentle Intake",
                            "project_mode": "fresh_project",
                            "product_goal": "Build a tiny fictional planning app.",
                            "target_user": "Solo builders",
                            "desired_first_demo": "A user can create a plan.",
                            "human_bridge_mode": "local_notifier",
                            "optional_mcp_servers": ["context7", "playwright"],
                            "automation_run_mode": "continuous_improvement",
                            "automation_role_profile": "planner_builder_hardener_integrator",
                            "ticket_generation_complexity": "tiny",
                            "ticket_generation_decomposition_brief": "First normalize the app shell, then add the planning flow.",
                            "ticket_run_seed_tickets": [
                                {
                                    "id": "TICKET-999",
                                    "summary": "This pass should not be used",
                                    "status": "pending",
                                }
                            ],
                        }
                    )
                return subprocess.CompletedProcess(
                    ["codex", "exec", prompt],
                    0,
                    stdout=stdout,
                    stderr="",
                )

            args = argparse.Namespace(target=str(target), body="Build a tiny fictional planning app.", stream_jsonl=False)
            with mock.patch.object(brief_commands, "_run_codex_intake_generation", side_effect=fake_intake_generation):
                payload = brief_commands.command_brief_generate_intake(args)

            intake = payload["intake"]
            self.assertEqual("ticket_campaign", intake["automation_run_mode"])
            self.assertEqual("", intake["ticket_run_file"])
            self.assertEqual([], intake["optional_mcp_servers"])
            self.assertEqual("file_only", intake["human_bridge_mode"])
            self.assertTrue(intake["multi_role_automations_allowed"])
            self.assertEqual("planner_builder_hardener_integrator", intake["automation_role_profile"])
            self.assertEqual(1, payload["ticket_count"])
            self.assertEqual("tiny", payload["ticket_generation_complexity"])
            self.assertEqual(["TICKET-001"], [ticket["id"] for ticket in intake["ticket_run_seed_tickets"]])
            self.assertEqual(2, len(prompts))
            self.assertIn("Do not return final seed tickets", prompts[0])
            self.assertIn("Ticket sizing policy", prompts[0])
            self.assertIn("tiny: 2-3 tickets", prompts[1])
            dashboard_state = json.loads(generated_path(target, ".agentic/dashboard_state.json").read_text(encoding="utf-8"))
            self.assertEqual("low_cortisol_intake_generated", dashboard_state["last_action"])
            self.assertEqual("Gentle Intake", dashboard_state["brief_draft_intake"]["project_name"])

    def test_brief_generate_intake_streams_two_pass_progress(self) -> None:
        from diffmogger.dashboard.commands import brief as brief_commands

        def fake_generation(prompt, **_kwargs):
            if "Generate Diffmogger ticket_run_seed_tickets" in prompt:
                stdout = json.dumps(
                    {
                        "ticket_run_seed_tickets": [
                            {
                                "id": "TICKET-001",
                                "summary": "Create the first local workflow",
                                "status": "pending",
                            },
                            {
                                "id": "TICKET-002",
                                "summary": "Add the first verification command",
                                "status": "pending",
                                "depends_on": ["TICKET-001"],
                            },
                        ]
                    }
                )
            else:
                stdout = json.dumps(
                    {
                        "project_name": "Two Pass Intake",
                        "product_goal": "Build a small local workflow.",
                        "target_user": "Maintainers",
                        "desired_first_demo": "A workflow runs locally.",
                        "ticket_generation_complexity": "tiny",
                    }
                )
            return subprocess.CompletedProcess(["codex", "exec", prompt], 0, stdout=stdout, stderr="")

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(brief_commands, "_run_codex_intake_generation", side_effect=fake_generation):
            args = argparse.Namespace(target=tmp, body="Build a small local workflow.", stream_jsonl=True)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                payload = brief_commands.command_brief_generate_intake(args)

        events = [json.loads(line) for line in output.getvalue().splitlines() if line.strip()]
        self.assertEqual(["intake-generate", "ticket-generate"], [event["stage"] for event in events])
        self.assertEqual(["Generating intake.", "Generating tickets."], [event["message"] for event in events])
        self.assertEqual(2, payload["ticket_count"])

    def test_brief_generate_intake_runs_codex_without_plugins(self) -> None:
        from diffmogger.dashboard.commands import brief as brief_commands

        seen: dict[str, object] = {}

        class FakePopen:
            pid = 12345
            returncode = 0

            def __init__(self, command, **kwargs):
                seen["command"] = command
                seen["kwargs"] = kwargs

            def communicate(self, *, timeout=None):
                seen["timeout"] = timeout
                return ("{}", "")

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(brief_commands.subprocess, "Popen", FakePopen):
            result = brief_commands._run_codex_intake_generation("prompt", cwd=Path(tmp), timeout_seconds=42)

        command = seen["command"]
        kwargs = seen["kwargs"]
        self.assertEqual(0, result.returncode)
        self.assertIn("--ephemeral", command)
        self.assertIn("--ignore-user-config", command)
        self.assertIn("--ignore-rules", command)
        self.assertIn("--disable", command)
        self.assertIn("plugins", command)
        self.assertTrue(kwargs["start_new_session"])
        self.assertEqual(42, seen["timeout"])

    def test_ticket_generation_policy_ranges_and_quality_gate(self) -> None:
        from diffmogger.dashboard.ticket_generation import ticket_count_range, ticket_quality_warnings, ticket_sizing_policy_prompt

        self.assertEqual((2, 3), ticket_count_range("tiny"))
        self.assertEqual((4, 6), ticket_count_range("small"))
        self.assertEqual((7, 12), ticket_count_range("medium"))
        self.assertEqual((12, 18), ticket_count_range("large"))
        self.assertIn("one reviewable local patch", ticket_sizing_policy_prompt("large"))
        self.assertIn("12-18 initial first-demo tickets", ticket_sizing_policy_prompt("large"))

        warnings = ticket_quality_warnings(
            [
                {
                    "id": "TICKET-001",
                    "summary": "Build backend and frontend and visualizer controls",
                    "acceptance_criteria": ["one", "two", "three", "four", "five", "six"],
                    "verification_commands": ["test", "lint", "build", "smoke"],
                }
            ]
        )
        self.assertIn("broad_conjunction_summary", {item["type"] for item in warnings})
        self.assertIn("too_many_acceptance_criteria", {item["type"] for item in warnings})
        self.assertIn("too_many_verification_commands", {item["type"] for item in warnings})

    def test_context_import_copies_files_and_updates_project_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as source_tmp:
            source = Path(source_tmp) / "Research Notes.md"
            source.write_text("# Research\n\nReusable context.\n", encoding="utf-8")
            intake = {
                "project_name": "Context Import",
                "project_mode": "fresh_project",
                "product_goal": "Import project notes.",
                "target_user": "Builders",
                "desired_first_demo": "Context index exists.",
                "additional_context_files": [],
            }
            self.run_cli(
                "brief.save_draft",
                "--target",
                tmp,
                "--intake-json",
                json.dumps(intake),
            )

            import_result, import_payload = self.run_cli(
                "context.import",
                "--target",
                tmp,
                "--files-json",
                json.dumps([str(source)]),
                "--project-name",
                "Context Import",
            )

            self.assertEqual(0, import_result.returncode)
            self.assertTrue(import_payload["ok"])
            records = import_payload["data"]["records"]
            self.assertEqual(1, len(records))
            copied = Path(tmp) / records[0]["rel_path"]
            self.assertTrue(copied.exists())
            self.assertEqual("# Research\n\nReusable context.\n", copied.read_text(encoding="utf-8"))
            context_index = generated_path(Path(tmp), "docs/PROJECT_CONTEXT.md")
            self.assertTrue(context_index.exists())
            index_text = context_index.read_text(encoding="utf-8")
            self.assertIn("Research Notes.md", index_text)
            self.assertIn(records[0]["rel_path"], index_text)

            _load_result, load_payload = self.run_cli("brief.load", "--target", tmp)
            self.assertIn(records[0]["rel_path"], load_payload["data"]["draft_intake"]["additional_context_files"])

    def test_brief_scaffold_bootstrap_scaffolds_without_codex_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intake = {
                "project_name": "Scaffold Smoke",
                "project_mode": "fresh_project",
                "product_goal": "Build a tiny fictional workspace.",
                "target_user": "Solo builders",
                "desired_first_demo": "A generated first run prompt.",
                "tech_preferences": ["Python"],
                "hard_constraints": ["Keep it generic."],
                "safety_constraints": ["No secrets."],
                "automation_must_never_do": ["Deploy production changes."],
                "external_services": ["None"],
                "env_access_policy": "project_commands_only",
                "verification_commands": ["python -m unittest"],
                "human_bridge_enabled": True,
                "human_bridge_mode": "file_only",
                "worker_agents_allowed": True,
                "codex_cli_workers_expected_on_broad_runs": True,
                "write_worker_agents_allowed": False,
                "max_write_worker_count": 0,
                "multi_role_automations_allowed": False,
                "automation_run_mode": "continuous_improvement",
                "optional_mcp_servers": [],
                "meaningful_deliverable": "A usable scaffold.",
                "beyond_mvp": "More automation.",
                "assumptions": ["Temporary smoke target."],
                "additional_context_files": [],
            }

            scaffold_result, scaffold_payload = self.run_cli(
                "brief.scaffold_bootstrap",
                "--target",
                tmp,
                "--intake-json",
                json.dumps(intake),
            )

            self.assertEqual(0, scaffold_result.returncode)
            self.assertTrue(scaffold_payload["ok"])
            self.assertEqual("skipped", scaffold_payload["data"]["codex"]["status"])
            self.assertEqual("created_initial_commit", scaffold_payload["data"]["git"]["status"])
            self.assertTrue(scaffold_payload["data"]["git"]["initialized"])
            self.assertTrue(scaffold_payload["data"]["git"]["committed"])
            self.assertEqual("pass", scaffold_payload["data"]["required_files"]["status"])
            self.assertIn(scaffold_payload["data"]["native_next_state"]["state"], {"FIRST_REVIEW_NEEDED", "READY_TO_RUN"})
            self.assertGreater(len(scaffold_payload["data"]["log"]), 0)
            self.assertTrue(generated_path(Path(tmp), ".agentic/project_intake.json").exists())
            self.assertTrue(generated_path(Path(tmp), "docs/INITIAL_BOOTSTRAP_PROMPT.md").exists())
            self.assertFalse(generated_path(Path(tmp), "scripts/run_role_automation.sh").exists())
            head = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=tmp, capture_output=True, text=True, check=False)
            self.assertEqual(0, head.returncode, head.stderr)
            subject = subprocess.run(["git", "log", "-1", "--pretty=%s"], cwd=tmp, capture_output=True, text=True, check=False)
            self.assertEqual("chore: initial commit", subject.stdout.strip())
            dashboard_state = json.loads(generated_path(Path(tmp), ".agentic/dashboard_state.json").read_text(encoding="utf-8"))
            self.assertEqual("single_lane", dashboard_state["automation_role_profile"])
            self.assertFalse(dashboard_state["multi_role_automations_allowed"])
            _run_result, run_payload = self.run_cli("run.load", "--target", tmp)
            self.assertNotIn("can_run_now", run_payload["data"]["controls"])

    def test_brief_scaffold_bootstrap_commits_existing_unborn_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=target, check=True)
            (target / "README.md").write_text("# Existing target\n", encoding="utf-8")
            intake = {
                "project_name": "Unborn Repo",
                "project_mode": "existing_project",
                "product_goal": "Prepare an existing local folder.",
                "target_user": "Maintainers",
                "desired_first_demo": "Automation can start from a real HEAD.",
                "human_bridge_enabled": True,
                "human_bridge_mode": "file_only",
                "worker_agents_allowed": True,
                "write_worker_agents_allowed": False,
                "multi_role_automations_allowed": False,
                "automation_run_mode": "continuous_improvement",
                "optional_mcp_servers": [],
                "additional_context_files": [],
            }

            scaffold_result, scaffold_payload = self.run_cli(
                "brief.scaffold_bootstrap",
                "--target",
                tmp,
                "--intake-json",
                json.dumps(intake),
            )

            self.assertEqual(0, scaffold_result.returncode)
            self.assertTrue(scaffold_payload["ok"])
            self.assertEqual("created_initial_commit", scaffold_payload["data"]["git"]["status"])
            self.assertFalse(scaffold_payload["data"]["git"]["initialized"])
            self.assertTrue(scaffold_payload["data"]["git"]["committed"])
            tracked = subprocess.run(["git", "ls-files"], cwd=target, capture_output=True, text=True, check=False)
            self.assertIn("README.md", tracked.stdout.splitlines())
            self.assertNotIn(".diffmogger/manifest.json", tracked.stdout.splitlines())

    def test_scaffold_preview_marks_existing_project_managed_sections_and_skips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target / "docs").mkdir()
            (target / "AGENTS.md").write_text("# Existing guidance\n", encoding="utf-8")
            (target / "docs" / "DEVELOPMENT.md").write_text("# Existing dev docs\n", encoding="utf-8")
            (target / "docs" / "PROJECT_CONTEXT.md").write_text("# Project Context\n\nExisting notes.\n", encoding="utf-8")
            (target / "package.json").write_text('{"scripts":{"test":"echo ok"}}\n', encoding="utf-8")
            subprocess.run(["git", "init"], cwd=target, check=True, text=True, capture_output=True)
            intake = {
                "project_name": "Existing Preview",
                "project_mode": "existing_project",
                "product_goal": "Integrate into an existing fictional repo.",
                "target_user": "Maintainers",
                "desired_first_demo": "Existing docs keep their content.",
                "human_bridge_enabled": True,
                "human_bridge_mode": "file_only",
                "optional_mcp_servers": [],
                "additional_context_files": [],
            }

            preview_result, preview_payload = self.run_cli(
                "brief.scaffold_preview",
                "--target",
                tmp,
                "--intake-json",
                json.dumps(intake),
            )

            self.assertEqual(0, preview_result.returncode)
            files = {item["rel_path"]: item for item in preview_payload["data"]["files"]}
            self.assertFalse(any(path.endswith(".DS_Store") for path in files))
            self.assertEqual("managed_section_update", files["AGENTS.md"]["action"])
            self.assertTrue(files["AGENTS.md"]["managed_section"])
            self.assertEqual("create", files[sidecar_rel("docs/DEVELOPMENT.md")]["action"])
            self.assertEqual("create", files[sidecar_rel("docs/PROJECT_CONTEXT.md")]["action"])
            self.assertIn("update_local_exclude", preview_payload["data"]["summary"])
            self.assertTrue(any(item["type"] == "dirty_git" for item in preview_payload["data"]["warnings"]))

    def test_existing_project_scaffold_preserves_existing_file_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target / "docs").mkdir()
            (target / "AGENTS.md").write_text("# Existing guidance\n\nKeep this.\n", encoding="utf-8")
            (target / "docs" / "DEVELOPMENT.md").write_text("# Existing dev docs\n\nKeep this too.\n", encoding="utf-8")
            intake = {
                "project_name": "Existing Scaffold",
                "project_mode": "existing_project",
                "product_goal": "Integrate into an existing fictional repo.",
                "target_user": "Maintainers",
                "desired_first_demo": "Managed sections are inserted.",
                "human_bridge_enabled": True,
                "human_bridge_mode": "file_only",
                "worker_agents_allowed": True,
                "write_worker_agents_allowed": False,
                "multi_role_automations_allowed": False,
                "automation_run_mode": "continuous_improvement",
                "optional_mcp_servers": [],
                "additional_context_files": [],
            }

            scaffold_result, scaffold_payload = self.run_cli(
                "brief.scaffold_bootstrap",
                "--target",
                tmp,
                "--intake-json",
                json.dumps(intake),
            )

            self.assertEqual(0, scaffold_result.returncode)
            self.assertTrue(scaffold_payload["ok"])
            agents_text = (target / "AGENTS.md").read_text(encoding="utf-8")
            dev_text = (target / "docs" / "DEVELOPMENT.md").read_text(encoding="utf-8")
            sidecar_dev_text = generated_path(target, "docs/DEVELOPMENT.md").read_text(encoding="utf-8")
            self.assertIn("Keep this.", agents_text)
            self.assertIn("DIFFMOGGER:START AGENTS", agents_text)
            self.assertIn("Keep this too.", dev_text)
            self.assertIn("First Review Checklist", sidecar_dev_text)

    def test_scaffold_bootstrap_streams_jsonl_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intake = {
                "project_name": "Stream Smoke",
                "project_mode": "fresh_project",
                "product_goal": "Stream scaffold logs.",
                "target_user": "Maintainers",
                "desired_first_demo": "JSONL progress events.",
                "human_bridge_enabled": True,
                "human_bridge_mode": "file_only",
                "optional_mcp_servers": [],
                "additional_context_files": [],
            }
            result = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "--stream-jsonl",
                    "brief.scaffold_bootstrap",
                    "--target",
                    tmp,
                    "--intake-json",
                    json.dumps(intake),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual("", result.stderr)
            lines = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
            self.assertEqual(0, result.returncode)
            self.assertTrue(any(line.get("event") == "log" and line.get("stage") == "scaffold" for line in lines))
            self.assertTrue(lines[-1]["ok"])
            self.assertEqual("brief.scaffold_bootstrap", lines[-1]["command"])

    def test_scaffolded_target_exposes_brief_run_files_and_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_target(target)

            _brief_result, brief = self.run_cli("brief.load", "--target", tmp)
            self.assertTrue(brief["ok"])
            self.assertEqual(target.resolve().name, brief["data"]["target"]["name"])

            _run_result, run = self.run_cli("run.load", "--target", tmp)
            self.assertTrue(run["ok"])
            self.assertEqual("ACTIVE", run["data"]["task"]["status"])
            self.assertIn("worker_strategy", run["data"])
            self.assertIn("controls", run["data"])
            self.assertIn("automation", run["data"])
            self.assertIn("run_log", run["data"])
            self.assertIn("worker_controls", run["data"])
            self.assertTrue(run["data"]["controls"]["is_scaffolded"])
            self.assertNotIn("can_run_now", run["data"]["controls"])
            self.assertIn("can_start", run["data"]["automation"])
            self.assertIn("git", run["data"])
            self.assertIn("progress", run["data"])
            self.assertIn("first_review", run["data"])

            _list_result, files = self.run_cli("advanced.list_files", "--target", tmp)
            file_keys = {item["key"]: item for item in files["data"]["files"]}
            self.assertTrue(file_keys["monitor.automation_tasks"]["exists"])

            _load_result, loaded = self.run_cli(
                "advanced.load_file",
                "--target",
                tmp,
                "--file-key",
                "monitor.automation_tasks",
            )
            self.assertTrue(loaded["ok"])
            self.assertIn("AUTOMATION_STATUS: ACTIVE", loaded["data"]["content"])

            _diagnostics_result, diagnostics = self.run_cli("diagnostics.run_checks", "--target", tmp)
            self.assertTrue(diagnostics["ok"])
            self.assertEqual("pass", diagnostics["data"]["required_files"]["status"])
            self.assertIn("prerequisites", diagnostics["data"])

    def test_ticket_commands_manage_scaffolded_ticket_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_ticket_target(target)

            load_result, load_payload = self.run_cli("ticket.load", "--target", tmp)
            self.assertEqual(0, load_result.returncode)
            self.assertTrue(load_payload["ok"])
            self.assertEqual(2, len(load_payload["data"]["tickets"]))
            self.assertEqual(str(database_path_for_target(target)), load_payload["data"]["ticket_file"])

            add_result, add_payload = self.run_cli(
                "ticket.add",
                "--target",
                tmp,
                "--ticket-json",
                json.dumps({"id": "TICKET-003", "summary": "Verify manual add"}),
            )
            self.assertEqual(0, add_result.returncode)
            self.assertTrue(add_payload["ok"])
            self.assertEqual(3, len(add_payload["data"]["tickets"]))

            update_result, update_payload = self.run_cli(
                "ticket.update",
                "--target",
                tmp,
                "--ticket-id",
                "TICKET-003",
                "--ticket-json",
                json.dumps({"summary": "Verify manual update", "status": "blocked", "blocker": "Needs a decision"}),
            )
            self.assertEqual(0, update_result.returncode)
            updated = {ticket["id"]: ticket for ticket in update_payload["data"]["tickets"]}
            self.assertEqual("blocked", updated["TICKET-003"]["status"])

            preview_result, preview_payload = self.run_cli(
                "ticket.import",
                "--target",
                tmp,
                "--format",
                "markdown",
                "--mode",
                "append",
                "--input-text",
                "TICKET-004: Preview imported ticket",
                "--preview",
            )
            self.assertEqual(0, preview_result.returncode)
            self.assertTrue(preview_payload["data"]["preview"])
            self.assertFalse(preview_payload["data"]["written"])

            import_result, import_payload = self.run_cli(
                "ticket.import",
                "--target",
                tmp,
                "--format",
                "json",
                "--mode",
                "append",
                "--input-json",
                json.dumps([{"id": "TICKET-004", "summary": "Applied imported ticket"}]),
            )
            self.assertEqual(0, import_result.returncode)
            self.assertTrue(import_payload["ok"])
            self.assertEqual(4, len(import_payload["data"]["tickets"]))

            delete_result, delete_payload = self.run_cli(
                "ticket.delete",
                "--target",
                tmp,
                "--ticket-id",
                "TICKET-004",
            )
            self.assertEqual(0, delete_result.returncode)
            self.assertEqual(3, len(delete_payload["data"]["tickets"]))

            _list_result, files = self.run_cli("advanced.list_files", "--target", tmp)
            file_keys = {item["key"] for item in files["data"]["files"]}
            self.assertNotIn("monitor.ticket_run", file_keys)

    def test_ticket_draft_from_intake_is_review_only_append_only_and_accepts_candidates(self) -> None:
        from diffmogger.dashboard.commands import tickets as ticket_commands

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_ticket_target(target)
            before_state = load_ticket_run_state(target)

            def fake_run(cmd, **_kwargs):
                if cmd[:2] == ["git", "status"]:
                    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
                if cmd[:2] == ["codex", "exec"]:
                    return subprocess.CompletedProcess(
                        cmd,
                        0,
                        stdout=json.dumps([
                            {
                                "id": "TICKET-001",
                                "summary": "Create the local queue",
                                "status": "pending",
                            },
                            {
                                "id": "TICKET-002",
                                "summary": "Drafted from intake",
                                "status": "done",
                                "depends_on": ["TICKET-001", "MISSING-001"],
                            },
                            {
                                "summary": "Second drafted ticket",
                                "status": "blocked",
                                "depends_on": ["TICKET-002", "MISSING-002"],
                            }
                        ]),
                        stderr="",
                    )
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

            args = argparse.Namespace(target=str(target), stream_jsonl=False, ticket_file="")
            with mock.patch.object(ticket_commands.subprocess, "run", side_effect=fake_run):
                draft = ticket_commands.command_ticket_draft_from_intake(args)

            self.assertEqual("append", draft["generation_mode"])
            self.assertEqual(2, draft["candidate_count"])
            self.assertEqual(1, draft["dropped_existing_count"])
            self.assertEqual(2, draft["renumbered_count"])
            self.assertEqual(2, draft["dropped_dependency_count"])
            self.assertEqual(["TICKET-003", "TICKET-004"], [ticket["id"] for ticket in draft["candidates"]])
            self.assertEqual(["pending", "pending"], [ticket["status"] for ticket in draft["candidates"]])
            self.assertEqual(["TICKET-001"], draft["candidates"][0]["depends_on"])
            self.assertEqual(["TICKET-002"], draft["candidates"][1]["depends_on"])
            self.assertEqual(before_state, load_ticket_run_state(target))
            before_accept = self.run_cli("ticket.load", "--target", tmp)[1]["data"]["tickets"]
            self.assertFalse(any(ticket["id"] == "TICKET-003" for ticket in before_accept))

            accept_result, accept_payload = self.run_cli(
                "ticket.accept_draft",
                "--target",
                tmp,
                "--draft-id",
                draft["draft_id"],
                "--mode",
                "append",
            )
            self.assertEqual(0, accept_result.returncode)
            tickets_by_id = {ticket["id"]: ticket for ticket in accept_payload["data"]["tickets"]}
            self.assertEqual(4, len(tickets_by_id))
            self.assertIn("TICKET-003", tickets_by_id)
            self.assertIn("TICKET-004", tickets_by_id)
            self.assertEqual("pending", tickets_by_id["TICKET-001"]["status"])
            self.assertEqual("pending", tickets_by_id["TICKET-002"]["status"])

    def test_ticket_draft_from_intake_includes_optional_direction_in_prompt(self) -> None:
        from diffmogger.dashboard.commands import tickets as ticket_commands

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_ticket_target(target)
            (target / "README.md").write_text("# Ticket test target\n\nReusable local workflow.\n", encoding="utf-8")
            (target / "package.json").write_text(
                json.dumps({"scripts": {"test": "vitest run"}, "dependencies": {"react": "latest"}}),
                encoding="utf-8",
            )
            captured_prompts: list[str] = []

            def fake_run(cmd, **_kwargs):
                if cmd[:2] == ["git", "status"]:
                    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
                if cmd[:2] == ["codex", "exec"]:
                    captured_prompts.append(cmd[-1])
                    return subprocess.CompletedProcess(
                        cmd,
                        0,
                        stdout=json.dumps([
                            {
                                "id": "TICKET-003",
                                "summary": "Add guided ticket drafting",
                                "status": "pending",
                            }
                        ]),
                        stderr="",
                    )
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

            args = argparse.Namespace(
                target=str(target),
                stream_jsonl=False,
                ticket_file="",
                direction="Focus on onboarding setup tickets and skip reporting polish.",
            )
            with mock.patch.object(ticket_commands.subprocess, "run", side_effect=fake_run):
                draft = ticket_commands.command_ticket_draft_from_intake(args)

            self.assertEqual(1, draft["candidate_count"])
            self.assertEqual(1, len(captured_prompts))
            self.assertIn("User-provided draft direction:", captured_prompts[0])
            self.assertIn("Focus on onboarding setup tickets and skip reporting polish.", captured_prompts[0])
            self.assertIn("preserving the append-only rules", captured_prompts[0])
            self.assertIn("Ticket sizing policy", captured_prompts[0])
            self.assertIn("Bounded project snapshot JSON:", captured_prompts[0])
            self.assertIn("README.md", captured_prompts[0])
            self.assertIn("vitest run", captured_prompts[0])
            self.assertIn("Ground every candidate in observed project structure", captured_prompts[0])

    def test_ticket_draft_from_intake_returns_empty_append_draft_when_nothing_new(self) -> None:
        from diffmogger.dashboard.commands import tickets as ticket_commands

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_ticket_target(target)

            def fake_run(cmd, **_kwargs):
                if cmd[:2] == ["git", "status"]:
                    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
                if cmd[:2] == ["codex", "exec"]:
                    return subprocess.CompletedProcess(
                        cmd,
                        0,
                        stdout=json.dumps([
                            {
                                "id": "TICKET-001",
                                "summary": "Create the local queue",
                                "status": "pending",
                            },
                            {
                                "id": "TICKET-002",
                                "summary": "Document the queue",
                                "status": "pending",
                            },
                        ]),
                        stderr="",
                    )
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

            args = argparse.Namespace(target=str(target), stream_jsonl=False, ticket_file="")
            with mock.patch.object(ticket_commands.subprocess, "run", side_effect=fake_run):
                draft = ticket_commands.command_ticket_draft_from_intake(args)

            self.assertEqual("append", draft["generation_mode"])
            self.assertEqual(0, draft["candidate_count"])
            self.assertEqual(2, draft["dropped_existing_count"])
            self.assertEqual("No new draft tickets were found.", draft["message"])

    def test_ticket_split_preview_and_accept_replaces_pending_ticket(self) -> None:
        from diffmogger.dashboard.commands import tickets as ticket_commands

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_ticket_target(target)
            prompts: list[str] = []

            def fake_run(cmd, **_kwargs):
                if cmd[:2] == ["git", "status"]:
                    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
                if cmd[:2] == ["codex", "exec"]:
                    prompts.append(cmd[-1])
                    return subprocess.CompletedProcess(
                        cmd,
                        0,
                        stdout=json.dumps(
                            [
                                {
                                    "id": "TICKET-001",
                                    "summary": "Create queue storage",
                                    "status": "pending",
                                    "acceptance_criteria": ["Queue storage is initialized"],
                                    "verification_commands": ["python3 -m unittest"],
                                },
                                {
                                    "id": "TICKET-004",
                                    "summary": "Render queue list",
                                    "status": "pending",
                                    "depends_on": ["TICKET-001"],
                                    "acceptance_criteria": ["Queue list reads from storage"],
                                    "verification_commands": ["python3 -m unittest"],
                                },
                            ]
                        ),
                        stderr="",
                    )
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

            args = argparse.Namespace(target=str(target), stream_jsonl=False, ticket_file="", ticket_id="TICKET-001")
            with mock.patch.object(ticket_commands.subprocess, "run", side_effect=fake_run):
                preview = ticket_commands.command_ticket_split_preview(args)

            self.assertEqual("split", preview["generation_mode"])
            self.assertEqual(2, preview["candidate_count"])
            self.assertEqual("TICKET-001", preview["source_ticket_id"])
            self.assertEqual(["TICKET-003", "TICKET-004"], [ticket["id"] for ticket in preview["candidates"]])
            self.assertEqual(["TICKET-003"], preview["candidates"][1]["depends_on"])
            self.assertIn("Split one pending Diffmogger ticket", prompts[0])
            self.assertIn("Ticket sizing policy", prompts[0])
            self.assertIn("Bounded project snapshot JSON:", prompts[0])

            before_accept = self.run_cli("ticket.load", "--target", tmp)[1]["data"]["tickets"]
            self.assertFalse(any(ticket["id"] == "TICKET-003" for ticket in before_accept))

            accept_result, accept_payload = self.run_cli(
                "ticket.accept_split",
                "--target",
                tmp,
                "--draft-id",
                preview["draft_id"],
            )

            self.assertEqual(0, accept_result.returncode)
            tickets_by_id = {ticket["id"]: ticket for ticket in accept_payload["data"]["tickets"]}
            self.assertNotIn("TICKET-001", tickets_by_id)
            self.assertIn("TICKET-003", tickets_by_id)
            self.assertIn("TICKET-004", tickets_by_id)
            self.assertEqual(["TICKET-004"], tickets_by_id["TICKET-002"]["depends_on"])
            self.assertEqual(["TICKET-003"], tickets_by_id["TICKET-004"]["depends_on"])

    def test_ticket_split_preview_rejects_done_ticket(self) -> None:
        from diffmogger.dashboard.commands import tickets as ticket_commands

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_ticket_target(target)
            state = load_ticket_run_state(target)
            assert isinstance(state, dict)
            state["tickets"][0]["status"] = "done"
            state["tickets"][0]["evidence"] = ["Already verified"]
            write_ticket_run_state(target, state, actor_role="test", event_type="ticket.done")

            args = argparse.Namespace(target=str(target), stream_jsonl=False, ticket_file="", ticket_id="TICKET-001")
            with self.assertRaises(Exception) as raised:
                ticket_commands.command_ticket_split_preview(args)

            self.assertIn("Only pending tickets can be split", str(raised.exception))

    def test_safety_run_check_records_target_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_target(target)

            safety_result, safety = self.run_cli("safety.run_check", "--target", tmp)

            self.assertEqual(0, safety_result.returncode)
            self.assertTrue(safety["ok"])
            record_path = Path(safety["data"]["record_path"])
            self.assertTrue(record_path.exists())
            record = json.loads(record_path.read_text(encoding="utf-8"))
            self.assertEqual("dashboard_run_safety_check", record["source"])
            self.assertIn(record["status"], {"pass", "fail"})
            state = json.loads(generated_path(target, ".agentic/dashboard_state.json").read_text(encoding="utf-8"))
            self.assertIn(state["last_action"], {"safety_check_completed", "safety_check_failed"})

    def test_inbox_load_parses_human_bridge_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            docs = target / "docs"
            docs.mkdir()
            (target / ".agentic").mkdir()
            (target / ".agentic" / "project_intake.json").write_text(
                json.dumps({"human_bridge_enabled": True, "human_bridge_mode": "file_only"}) + "\n",
                encoding="utf-8",
            )
            (docs / "HUMAN_REQUESTS.md").write_text(
                """# Human Requests

## HR-2026-05-03-001

- status: active
- requested_at: 2026-05-03T12:00:00+00:00
- run_id: builder-17
- ticket_id: T-7

### Body

Please confirm whether ticket T-7 can use mock data.

## HR-2026-05-03-002

- status: resolved
- resolved_at: 2026-05-04T12:00:00+00:00

### Body

The API key question was answered.
""",
                encoding="utf-8",
            )
            (docs / "HUMAN_INBOX.md").write_text(
                """# Human Inbox

## INBOX-2026-05-03-001

- received_at: 2026-05-03T13:00:00+00:00
- request_id: HR-2026-05-03-001
- parsed_intent: info
- status: unhandled

### Body

Use mocked data for now.
""",
                encoding="utf-8",
            )
            (docs / "HUMAN_RESPONSES_ARCHIVE.md").write_text(
                """# Human Responses Archive

## HR-2026-05-03-002 resolved

- resolved_at: 2026-05-04T12:00:00+00:00
- source_inbox_id: INBOX-2026-05-02-001
- parsed_intent: done
- action_taken: Marked the API key request resolved.
""",
                encoding="utf-8",
            )
            (docs / "HUMAN_OUTBOX.md").write_text(
                """# Human Outbox

## OUTBOX-2026-05-03-001

- status: sent
""",
                encoding="utf-8",
            )

            result, payload = self.run_cli("inbox.load", "--target", tmp)

            self.assertEqual(0, result.returncode)
            self.assertTrue(payload["ok"])
            data = payload["data"]
            self.assertEqual("file_only", data["bridge_mode"])
            self.assertEqual(1, data["counts"]["pending_requests"])
            self.assertEqual(1, data["counts"]["queued_notes"])
            self.assertEqual(1, data["counts"]["outbound_records"])
            self.assertEqual("HR-2026-05-03-001", data["active_requests"][0]["id"])
            self.assertEqual("builder-17", data["active_requests"][0]["related"]["run"])
            self.assertIn("mock data", data["active_requests"][0]["body"])
            self.assertTrue(any(item["id"] == "HR-2026-05-03-002" for item in data["archive"]))

    def test_inbox_send_note_and_reply_write_old_dashboard_queue_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            docs = target / "docs"
            docs.mkdir()
            (docs / "HUMAN_REQUESTS.md").write_text(
                """# Human Requests

## HR-2026-05-03-001

- status: active

### Body

Need a decision.
""",
                encoding="utf-8",
            )

            note_result, note_payload = self.run_cli(
                "inbox.send_note",
                "--target",
                tmp,
                "--body",
                "Please focus on the local demo next.",
                "--intent",
                "info",
                "--related",
                "demo-polish",
            )
            self.assertEqual(0, note_result.returncode)
            self.assertTrue(note_payload["ok"])
            self.assertEqual("queued", note_payload["data"]["status"])

            reply_result, reply_payload = self.run_cli(
                "inbox.reply_request",
                "--target",
                tmp,
                "--request-id",
                "HR-2026-05-03-001",
                "--body",
                "Approved. Use mock data for the next run.",
                "--intent",
                "approve",
            )
            self.assertEqual(0, reply_result.returncode)
            self.assertTrue(reply_payload["ok"])

            _load_result, load_payload = self.run_cli("inbox.load", "--target", tmp)
            self.assertEqual(2, load_payload["data"]["counts"]["queued_notes"])
            note_bodies = "\n".join(item["body"] for item in load_payload["data"]["active_notes"])
            self.assertIn("Please focus on the local demo next.", note_bodies)
            self.assertIn("Approved. Use mock data for the next run.", note_bodies)

    def test_observatory_html_and_review_bundle_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as review_tmp:
            target = Path(tmp)
            review_dir = Path(review_tmp) / "review"
            self.scaffold_target(target)

            html_result, html_payload = self.run_cli(
                "observatory.generate_html",
                "--target",
                tmp,
                "--review-dir",
                str(review_dir),
            )
            self.assertEqual(0, html_result.returncode)
            html_path = Path(html_payload["data"]["html_path"])
            self.assertTrue(html_path.exists())
            self.assertIn("Diffmogger Autonomous Build Log", html_path.read_text(encoding="utf-8"))

            load_result, load_payload = self.run_cli(
                "observatory.load_html",
                "--target",
                tmp,
                "--review-dir",
                str(review_dir),
            )
            self.assertEqual(0, load_result.returncode)
            self.assertTrue(load_payload["ok"])
            self.assertTrue(load_payload["data"]["embeddable"])
            self.assertTrue(load_payload["data"]["title_marker_present"])
            self.assertTrue(load_payload["data"]["visual_markers_present"])
            self.assertIn("Diffmogger Autonomous Build Log", load_payload["data"]["html"])

            snapshot_result, snapshot_payload = self.run_cli("observatory.snapshot", "--target", tmp)
            self.assertEqual(0, snapshot_result.returncode)
            self.assertTrue(snapshot_payload["ok"])
            snapshot = snapshot_payload["data"]
            self.assertEqual("Diffmogger Autonomous Build Log", snapshot["title"])
            self.assertEqual("ACTIVE", snapshot["mission"]["automation_status"])
            self.assertEqual(4, len(snapshot["conveyor"]["roles"]))
            self.assertIn("queued", snapshot["patches"]["queue_totals"])
            self.assertIn("validation", snapshot["validation_safety"])
            self.assertNotIn("signals", snapshot)

            bundle_result, bundle_payload = self.run_cli(
                "review.export_bundle",
                "--target",
                tmp,
                "--review-dir",
                str(review_dir),
            )
            self.assertEqual(0, bundle_result.returncode)
            self.assertTrue(Path(bundle_payload["data"]["html_path"]).exists())
            markdown_path = Path(bundle_payload["data"]["markdown_path"])
            self.assertTrue(markdown_path.exists())
            self.assertIn("# Diffmogger Self-Review Snapshot", markdown_path.read_text(encoding="utf-8"))

    def test_review_load_and_mark_reviewed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_target(target)

            load_result, load_payload = self.run_cli("review.load", "--target", tmp)

            self.assertEqual(0, load_result.returncode)
            self.assertTrue(load_payload["ok"])
            data = load_payload["data"]
            self.assertIn("latest_run", data)
            self.assertIn("changed_files", data)
            self.assertGreater(len(data["changed_files"]), 0)
            self.assertIn("verification", data)
            self.assertIn("safety", data)
            self.assertIn("review_fingerprint", data)
            self.assertIn("# Diffmogger Self-Review Snapshot", data["self_review"]["markdown_preview"])
            self.assertFalse(data["reviewed"]["exists"])

            mark_result, mark_payload = self.run_cli(
                "review.mark_reviewed",
                "--target",
                tmp,
                "--note",
                "Looks trustworthy enough for the next run.",
            )

            self.assertEqual(0, mark_result.returncode)
            self.assertTrue(mark_payload["ok"])
            marker_path = Path(mark_payload["data"]["marker_path"])
            self.assertTrue(marker_path.exists())
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            self.assertEqual("native_review_page", marker["source"])
            self.assertIn("trustworthy", marker["note"])
            self.assertEqual(data["review_fingerprint"], marker["review_fingerprint"])

            reload_result, reload_payload = self.run_cli("review.load", "--target", tmp)
            self.assertEqual(0, reload_result.returncode)
            self.assertTrue(reload_payload["ok"])
            self.assertTrue(reload_payload["data"]["reviewed"]["is_current_snapshot"])

    def test_review_load_suppresses_stale_pending_integration_safety_when_safety_passed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_target(target)
            task_path = generated_path(target, "docs/CODEX_AUTOMATION_TASKS.md")
            task_path.write_text(
                """
                # Codex Automation Tasks

                AUTOMATION_STATUS: ACTIVE

                ## Current Project State

                - Current assessment: Local checks passed.

                ## Product Horizon State

                - Current horizon: H1

                ## Checks From Last Run

                - `python3 -m pytest` passed.
                - Not run: integration safety (`python3 scripts/check_integration_safety.py`) because no such project script exists yet.
                """,
                encoding="utf-8",
            )
            safety_path = generated_path(target, "target/integration_safety_check.json")
            safety_path.parent.mkdir(parents=True, exist_ok=True)
            safety_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "checked_at": "2026-05-10T22:12:32+00:00",
                        "source": "dashboard_run_safety_check",
                        "status": "pass",
                        "exit_code": 0,
                        "command": "python3 scripts/check_integration_safety.py .",
                        "summary": "Dashboard Run Safety Check passed.",
                    }
                ),
                encoding="utf-8",
            )

            result, payload = self.run_cli("review.load", "--target", tmp)

            self.assertEqual(0, result.returncode)
            self.assertEqual("pass", payload["data"]["safety"]["status"])
            limitation_text = "\n".join(item.get("text", "") for item in payload["data"]["limitations"])
            self.assertNotIn("Not run: integration safety", limitation_text)
            verification_text = "\n".join(item.get("text", "") for item in payload["data"]["verification"]["items"])
            self.assertNotIn("Not run: integration safety", verification_text)

    def test_advanced_save_validate_and_debug_bundle_are_allowlisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as bundle_tmp:
            target = Path(tmp)
            (target / ".env").write_text("API_TOKEN=do-not-ship\n", encoding="utf-8")

            save_result, save_payload = self.run_cli(
                "advanced.save_file",
                "--target",
                tmp,
                "--file-key",
                "state.dashboard",
                "--content",
                json.dumps({"normal": "ok", "discord_webhook": "https://secret.example/hook"}) + "\n",
            )
            self.assertEqual(0, save_result.returncode)
            self.assertTrue(save_payload["ok"])
            self.assertTrue(Path(save_payload["data"]["file"]["path"]).exists())

            _load_result, load_payload = self.run_cli(
                "advanced.load_file",
                "--target",
                tmp,
                "--file-key",
                "state.dashboard",
            )
            self.assertIn("discord_webhook", load_payload["data"]["content"])

            validate_result, validate_payload = self.run_cli(
                "advanced.validate_file",
                "--target",
                tmp,
                "--file-key",
                "state.dashboard",
            )
            self.assertEqual(0, validate_result.returncode)
            self.assertEqual("pass", validate_payload["data"]["status"])

            invalid_result, invalid_payload = self.run_cli(
                "advanced.save_file",
                "--target",
                tmp,
                "--file-key",
                "review.observatory_html",
                "--content",
                "<html></html>",
            )
            self.assertNotEqual(0, invalid_result.returncode)
            self.assertFalse(invalid_payload["ok"])
            self.assertEqual("file_read_only", invalid_payload["error"]["type"])

            bundle_result, bundle_payload = self.run_cli(
                "advanced.export_debug_bundle",
                "--target",
                tmp,
                "--output-dir",
                bundle_tmp,
            )
            self.assertEqual(0, bundle_result.returncode)
            self.assertTrue(bundle_payload["ok"])
            bundle_path = Path(bundle_payload["data"]["bundle_path"])
            self.assertTrue(bundle_path.exists())

            with zipfile.ZipFile(bundle_path) as archive:
                names = set(archive.namelist())
                self.assertNotIn(".env", names)
                self.assertIn("debug-summary.json", names)
                self.assertIn("dashboard-state.json", names)
                combined = "\n".join(
                    archive.read(name).decode("utf-8", errors="replace")
                    for name in names
                )
            self.assertNotIn("do-not-ship", combined)
            self.assertNotIn("https://secret.example/hook", combined)
            self.assertIn("[REDACTED]", combined)

    def test_project_list_recent_returns_stable_shape(self) -> None:
        result, payload = self.run_cli("project.list_recent")

        self.assertEqual(0, result.returncode)
        self.assertTrue(payload["ok"])
        self.assertIsInstance(payload["data"]["projects"], list)


if __name__ == "__main__":
    unittest.main()
