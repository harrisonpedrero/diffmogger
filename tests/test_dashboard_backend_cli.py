from __future__ import annotations

import json
import argparse
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from diffmogger_paths import sidecar_rel

CLI = ROOT / "scripts" / "dashboard_backend_cli.py"
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

    def load_cli_module(self):
        spec = importlib.util.spec_from_file_location("dashboard_backend_cli_test", CLI)
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

    def test_backend_dotenv_loader_uses_run_dashboard_parser_without_overriding_env(self) -> None:
        module = self.load_cli_module()
        with tempfile.TemporaryDirectory() as tmp:
            kit_root = Path(tmp)
            scripts_dir = kit_root / "scripts"
            scripts_dir.mkdir()
            (scripts_dir / "run_dashboard.py").write_text(
                (ROOT / "scripts" / "run_dashboard.py").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
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

    def test_schedule_remove_deletes_managed_plists_and_records_state_idempotently(self) -> None:
        module = self.load_cli_module()

        class FakeDashboard:
            LAUNCHD_LABEL_PREFIX = "com.diffmogger.automation"

            def __init__(self, launch_agents: Path) -> None:
                self.launch_agents = launch_agents

            def launchd_plist_path(self, label: str) -> Path:
                return self.launch_agents / f"{label}.plist"

            def launchd_service_target(self, label: str) -> str:
                return f"gui/501/{label}"

            def launchd_domain_target(self) -> str:
                return "gui/501"

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            target.mkdir()
            launch_agents = Path(tmp) / "LaunchAgents"
            launch_agents.mkdir()
            existing_plist = launch_agents / "com.diffmogger.single.plist"
            existing_plist.write_text("<plist></plist>\n", encoding="utf-8")
            fake_dashboard = FakeDashboard(launch_agents)
            launchctl_calls: list[list[str]] = []

            def fake_launchctl(args: list[str], _dashboard_app, *, allow_failure: bool = False) -> dict[str, object]:
                launchctl_calls.append(args)
                return {"exit_code": 0, "stdout": "", "stderr": "", "allow_failure": allow_failure}

            with (
                mock.patch.object(module.sys, "platform", "darwin"),
                mock.patch.object(module, "load_dashboard_module", return_value=fake_dashboard),
                mock.patch.object(module, "all_schedule_labels", return_value=["com.diffmogger.single", "com.diffmogger.conveyor"]),
                mock.patch.object(module, "launchd_loaded", side_effect=lambda label, _dashboard: label == "com.diffmogger.single"),
                mock.patch.object(module, "launchctl", side_effect=fake_launchctl),
                mock.patch.object(module, "schedule_status_snapshot", return_value={"state": "not_installed", "can_remove": False}),
            ):
                payload = module.command_schedule_remove(argparse.Namespace(target=str(target), stream_jsonl=False))
                second_payload = module.command_schedule_remove(argparse.Namespace(target=str(target), stream_jsonl=False))

            self.assertFalse(existing_plist.exists())
            self.assertEqual(1, payload["removed_count"])
            self.assertEqual("com.diffmogger.single", payload["removed"][0]["label"])
            self.assertTrue(any(item["label"] == "com.diffmogger.conveyor" for item in payload["missing"]))
            self.assertEqual(0, second_payload["removed_count"])
            self.assertTrue(any(call[0] == "bootout" for call in launchctl_calls))
            self.assertTrue(any(call[0] == "disable" for call in launchctl_calls))
            self.assertTrue(any(call[0] == "enable" for call in launchctl_calls))
            state = json.loads(generated_path(target, ".agentic/dashboard_state.json").read_text(encoding="utf-8"))
            self.assertEqual("schedule_removed", state["last_action"])

    def test_schedule_remove_deletes_discovered_conveyor_plist_for_target(self) -> None:
        module = self.load_cli_module()

        class FakeDashboard:
            LAUNCHD_LABEL_PREFIX = "com.diffmogger.automation"

            def __init__(self, launch_agents: Path) -> None:
                self.launch_agents = launch_agents

            def launchd_plist_path(self, label: str) -> Path:
                return self.launch_agents / f"{label}.plist"

            def launchd_service_target(self, label: str) -> str:
                return f"gui/501/{label}"

            def launchd_domain_target(self) -> str:
                return "gui/501"

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            target.mkdir()
            home = Path(tmp) / "home"
            launch_agents = home / "Library" / "LaunchAgents"
            launch_agents.mkdir(parents=True)
            stale_label = "com.diffmogger.automation.target.legacy.conveyor"
            stale_plist = launch_agents / f"{stale_label}.plist"
            stale_plist.write_bytes(
                module.plistlib.dumps(
                    {
                        "Label": stale_label,
                        "ProgramArguments": ["/bin/bash", str(target / "scripts" / "run_conveyor_automation.sh")],
                        "WorkingDirectory": str(target),
                    }
                )
            )
            fake_dashboard = FakeDashboard(launch_agents)

            with (
                mock.patch.object(module.sys, "platform", "darwin"),
                mock.patch.object(module.Path, "home", return_value=home),
                mock.patch.object(module, "load_dashboard_module", return_value=fake_dashboard),
                mock.patch.object(module, "all_schedule_labels", return_value=["com.diffmogger.single"]),
                mock.patch.object(module, "launchd_loaded", return_value=False),
                mock.patch.object(module, "launchctl", return_value={"exit_code": 0, "stdout": "", "stderr": ""}),
                mock.patch.object(module, "schedule_status_snapshot", return_value={"state": "not_installed", "can_remove": False}),
            ):
                payload = module.command_schedule_remove(argparse.Namespace(target=str(target), stream_jsonl=False))

            self.assertFalse(stale_plist.exists())
            self.assertEqual(1, payload["removed_count"])
            self.assertEqual(stale_label, payload["removed"][0]["label"])

    def test_schedule_remove_discovers_plist_from_target_environment_without_working_directory(self) -> None:
        module = self.load_cli_module()

        class FakeDashboard:
            LAUNCHD_LABEL_PREFIX = "com.diffmogger.automation"

            def __init__(self, launch_agents: Path) -> None:
                self.launch_agents = launch_agents

            def launchd_plist_path(self, label: str) -> Path:
                return self.launch_agents / f"{label}.plist"

            def launchd_service_target(self, label: str) -> str:
                return f"gui/501/{label}"

            def launchd_domain_target(self) -> str:
                return "gui/501"

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            target.mkdir()
            home = Path(tmp) / "home"
            launch_agents = home / "Library" / "LaunchAgents"
            launch_agents.mkdir(parents=True)
            stale_label = "com.diffmogger.automation.target.env-only"
            stale_plist = launch_agents / f"{stale_label}.plist"
            stale_plist.write_bytes(
                module.plistlib.dumps(
                    {
                        "Label": stale_label,
                        "ProgramArguments": ["/bin/bash", "scripts/run_conveyor_automation.sh"],
                        "EnvironmentVariables": {"TARGET": str(target)},
                    }
                )
            )
            fake_dashboard = FakeDashboard(launch_agents)

            with (
                mock.patch.object(module.sys, "platform", "darwin"),
                mock.patch.object(module.Path, "home", return_value=home),
                mock.patch.object(module, "load_dashboard_module", return_value=fake_dashboard),
                mock.patch.object(module, "all_schedule_labels", return_value=["com.diffmogger.single"]),
                mock.patch.object(module, "launchd_loaded", return_value=False),
                mock.patch.object(module, "launchctl", return_value={"exit_code": 0, "stdout": "", "stderr": ""}),
                mock.patch.object(module, "schedule_status_snapshot", return_value={"state": "not_installed", "can_remove": False}),
            ):
                payload = module.command_schedule_remove(argparse.Namespace(target=str(target), stream_jsonl=False))

            self.assertFalse(stale_plist.exists())
            self.assertEqual(1, payload["removed_count"])
            self.assertEqual(stale_label, payload["removed"][0]["label"])

    def test_launchd_disabled_parser_accepts_boolean_and_worded_states(self) -> None:
        module = self.load_cli_module()

        label = "com.diffmogger.automation.project.123"
        self.assertTrue(module.launchd_disabled_in_output(f'\t"{label}" => true\n', label))
        self.assertTrue(module.launchd_disabled_in_output(f'\t"{label}" => disabled\n', label))
        self.assertFalse(module.launchd_disabled_in_output(f'\t"{label}" => enabled\n', label))

    def test_schedule_status_only_allows_pause_for_loaded_jobs(self) -> None:
        module = self.load_cli_module()

        class FakeDashboard:
            LAUNCHD_LABEL_PREFIX = "com.diffmogger.automation"
            MULTI_ROLE_ROLES = ("planner", "builder", "hardener", "integrator")
            SCHEDULE_STRATEGY_SINGLE = "single_lane_interval"
            SCHEDULE_STRATEGY_FIXED_MULTI_ROLE = "fixed_multi_role"
            SCHEDULE_STRATEGY_CONVEYOR = "continuous_conveyor"
            SCHEDULE_STRATEGY_LABELS = {SCHEDULE_STRATEGY_SINGLE: "Periodic sprint"}

            def __init__(self, launch_agents: Path) -> None:
                self.launch_agents = launch_agents

            def launchd_label(self, _target: Path) -> str:
                return "com.diffmogger.single"

            def launchd_conveyor_label(self, _target: Path) -> str:
                return "com.diffmogger.conveyor"

            def launchd_role_label(self, _target: Path, role: str) -> str:
                return f"com.diffmogger.{role}"

            def launchd_plist_path(self, label: str) -> Path:
                return self.launch_agents / f"{label}.plist"

            def launchd_log_dir(self, target: Path) -> Path:
                return target / "target" / "automation_logs"

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            target.mkdir()
            launch_agents = Path(tmp) / "LaunchAgents"
            launch_agents.mkdir()
            (launch_agents / "com.diffmogger.single.plist").write_text("<plist></plist>\n", encoding="utf-8")
            fake_dashboard = FakeDashboard(launch_agents)

            with (
                mock.patch.object(module.sys, "platform", "darwin"),
                mock.patch.object(module, "automation_ready", return_value=(True, "Ready.")),
                mock.patch.object(module, "target_schedule_strategy", return_value=fake_dashboard.SCHEDULE_STRATEGY_SINGLE),
                mock.patch.object(module, "target_cadence_seconds", return_value=3600),
                mock.patch.object(module, "launchd_loaded", return_value=False),
                mock.patch.object(module, "launchd_disabled", return_value=False),
            ):
                snapshot = module.schedule_status_snapshot(target, fake_dashboard)

            self.assertEqual("installed", snapshot["state"])
            self.assertFalse(snapshot["can_pause"])
            self.assertTrue(snapshot["can_remove"])

    def test_schedule_pause_is_noop_when_no_schedule_is_loaded(self) -> None:
        module = self.load_cli_module()

        class FakeDashboard:
            LAUNCHD_LABEL_PREFIX = "com.diffmogger.automation"

            def __init__(self, launch_agents: Path) -> None:
                self.launch_agents = launch_agents

            def launchd_plist_path(self, label: str) -> Path:
                return self.launch_agents / f"{label}.plist"

            def launchd_service_target(self, label: str) -> str:
                return f"gui/501/{label}"

            def launchd_domain_target(self) -> str:
                return "gui/501"

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            target.mkdir()
            launch_agents = Path(tmp) / "LaunchAgents"
            launch_agents.mkdir()
            (launch_agents / "com.diffmogger.single.plist").write_text("<plist></plist>\n", encoding="utf-8")
            fake_dashboard = FakeDashboard(launch_agents)
            launchctl_calls: list[list[str]] = []

            def fake_launchctl(args: list[str], _dashboard_app, *, allow_failure: bool = False) -> dict[str, object]:
                launchctl_calls.append(args)
                return {"exit_code": 0, "stdout": "", "stderr": "", "allow_failure": allow_failure}

            with (
                mock.patch.object(module.sys, "platform", "darwin"),
                mock.patch.object(module, "load_dashboard_module", return_value=fake_dashboard),
                mock.patch.object(module, "all_schedule_labels", return_value=["com.diffmogger.single"]),
                mock.patch.object(module, "launchd_loaded", return_value=False),
                mock.patch.object(module, "launchctl", side_effect=fake_launchctl),
                mock.patch.object(module, "schedule_status_snapshot", return_value={"state": "installed", "can_pause": False}),
            ):
                payload = module.command_schedule_pause(argparse.Namespace(target=str(target), stream_jsonl=False))

            self.assertFalse(payload["found"])
            self.assertEqual([], launchctl_calls)

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
            self.assertFalse(data["run"]["controls"]["can_run_now"])
            self.assertIn(data["run"]["schedule"]["state"], {"not_ready", "unavailable"})

    def test_unconfigured_target_smoke_supports_initial_native_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _brief_result, brief = self.run_cli("brief.load", "--target", tmp)
            self.assertTrue(brief["ok"])
            self.assertFalse(brief["data"]["target"]["is_diffmogger_project"])

            _run_result, run = self.run_cli("run.load", "--target", tmp)
            self.assertTrue(run["ok"])
            self.assertFalse(run["data"]["controls"]["is_scaffolded"])
            self.assertFalse(run["data"]["controls"]["can_run_now"])

            _diagnostics_result, diagnostics = self.run_cli("diagnostics.run_checks", "--target", tmp)
            self.assertTrue(diagnostics["ok"])
            self.assertIn("prerequisites", diagnostics["data"])
            self.assertIn("backend", diagnostics["data"])
            self.assertIn("runtime_environment", diagnostics["data"])
            self.assertIn("fix_suggestions", diagnostics["data"])
            prereq_items = diagnostics["data"]["prerequisites"]["items"]
            legacy_tk = [item for item in prereq_items if item["name"] == "Legacy Tkinter dashboard runtime"]
            self.assertEqual(1, len(legacy_tk))
            self.assertFalse(legacy_tk[0]["required"])

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
                "desired_cadence": "every 45 minutes",
                "human_bridge_enabled": True,
                "human_bridge_mode": "file_only",
                "worker_agents_allowed": True,
                "write_worker_agents_allowed": True,
                "max_write_worker_count": 2,
                "multi_role_automations_allowed": True,
                "automation_schedule_strategy": "continuous_conveyor",
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
                "desired_cadence": "every 60 minutes",
                "human_bridge_enabled": True,
                "human_bridge_mode": "file_only",
                "worker_agents_allowed": True,
                "codex_cli_workers_expected_on_broad_runs": True,
                "write_worker_agents_allowed": False,
                "max_write_worker_count": 0,
                "multi_role_automations_allowed": False,
                "automation_signals_enabled": False,
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
            self.assertEqual("pass", scaffold_payload["data"]["required_files"]["status"])
            self.assertIn(scaffold_payload["data"]["native_next_state"]["state"], {"FIRST_REVIEW_NEEDED", "READY_TO_RUN"})
            self.assertGreater(len(scaffold_payload["data"]["log"]), 0)
            self.assertTrue(generated_path(Path(tmp), ".agentic/project_intake.json").exists())
            self.assertTrue(generated_path(Path(tmp), "docs/INITIAL_BOOTSTRAP_PROMPT.md").exists())
            _run_result, run_payload = self.run_cli("run.load", "--target", tmp)
            self.assertTrue(run_payload["data"]["controls"]["can_run_now"])

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
                "automation_signals_enabled": False,
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
            self.assertIn("schedule", run["data"])
            self.assertIn("run_log", run["data"])
            self.assertIn("worker_controls", run["data"])
            self.assertTrue(run["data"]["controls"]["is_scaffolded"])
            self.assertTrue(run["data"]["controls"]["can_run_now"])
            self.assertIn("can_start", run["data"]["schedule"])
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
- file: docs/TICKET_RUN.md

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

            inbox_text = (docs / "HUMAN_INBOX.md").read_text(encoding="utf-8")
            self.assertIn("channel: manual-dashboard", inbox_text)
            self.assertIn("request_id: demo-polish", inbox_text)
            self.assertIn("request_id: HR-2026-05-03-001", inbox_text)
            self.assertIn("parsed_intent: approve", inbox_text)
            self.assertIn("Expected automation behavior", inbox_text)

            _load_result, load_payload = self.run_cli("inbox.load", "--target", tmp)
            self.assertEqual(2, load_payload["data"]["counts"]["queued_notes"])

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
            self.assertIn("nudges", snapshot["signals"])

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
