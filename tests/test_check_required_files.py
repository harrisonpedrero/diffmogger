from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCAFFOLD_SCRIPT = ROOT / "scripts" / "scaffold_project_docs.py"
CHECK_SCRIPT = ROOT / "scripts" / "check_required_files.py"
GENERIC_INTAKE = ROOT / "examples" / "generic-web-app" / "project_intake.md"
TRENDLAB_INTAKE = ROOT / "examples" / "trendlab-signal-intelligence" / "project_intake.md"


class RequiredFilesCheckTests(unittest.TestCase):
    def scaffold_target(self, target: Path, intake: Path = GENERIC_INTAKE) -> None:
        subprocess.run(
            [
                sys.executable,
                str(SCAFFOLD_SCRIPT),
                "--intake",
                str(intake),
                "--target",
                str(target),
            ],
            check=True,
            text=True,
            capture_output=True,
        )

    def run_check(self, target: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(CHECK_SCRIPT),
                "--human-bridge-mode",
                "file_only",
                str(target),
            ],
            text=True,
            capture_output=True,
        )

    def test_scaffolded_target_keeps_first_review_checklist_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_target(target)

            result = self.run_check(target)

            self.assertEqual("", result.stderr)
            self.assertEqual(0, result.returncode)

    def test_scaffold_without_optional_mcp_omits_mcp_state_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_target(target)

            for rel in [
                ".codex/config.toml",
                "docs/MCP_INTEGRATIONS.md",
                "docs/backlog/README.md",
                "scripts/run_playwright_mcp.sh",
            ]:
                self.assertFalse((target / rel).exists(), rel)

            result = self.run_check(target)

            self.assertEqual("", result.stderr)
            self.assertEqual(0, result.returncode)

    def test_optional_mcp_scaffold_generates_role_scoped_config_and_guardrails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.NamedTemporaryFile("w", suffix=".json") as intake:
            target = Path(tmp)
            intake.write(
                """
{
  "project_name": "MCP Smoke",
  "product_goal": "Validate optional MCP scaffolding.",
  "target_user": "Automation tester.",
  "desired_first_demo": "Generated docs only.",
  "human_bridge_enabled": false,
  "human_bridge_mode": "disabled",
  "multi_role_automations_allowed": true,
  "automation_role_profile": "planner_builder_hardener_integrator",
  "optional_mcp_servers": ["context7", "playwright"],
  "verification_commands": ["npm test"]
}
""".strip()
            )
            intake.flush()

            self.scaffold_target(target, Path(intake.name))
            config = (target / ".codex" / "config.toml").read_text(encoding="utf-8")
            role_runner = (target / "scripts" / "run_role_automation.sh").read_text(encoding="utf-8")
            single_lane_runner = (target / "scripts" / "run_codex_automation.sh").read_text(encoding="utf-8")
            helper = (target / "scripts" / "run_playwright_mcp.sh").read_text(encoding="utf-8")

            self.assertIn("[mcp_servers.context7]", config)
            self.assertIn('args = ["-y", "@upstash/context7-mcp"]', config)
            self.assertIn('env_vars = ["CONTEXT7_API_KEY"]', config)
            self.assertIn("[mcp_servers.playwright]", config)
            self.assertIn('disabled_tools = ["browser_run_code_unsafe", "browser_file_upload"]', config)
            self.assertIn("[profiles.diffmogger-planner.mcp_servers.context7]", config)
            self.assertIn("[profiles.diffmogger-builder.mcp_servers.context7]", config)
            self.assertIn("[profiles.diffmogger-hardener.mcp_servers.playwright]", config)
            self.assertIn("[profiles.diffmogger-integrator.mcp_servers.playwright]", config)
            self.assertIn('mcp_servers.context7.command="npx"', role_runner)
            self.assertIn('mcp_servers.context7.env_vars=["CONTEXT7_API_KEY"]', role_runner)
            self.assertIn('mcp_servers.playwright.command="bash"', role_runner)
            self.assertIn('mcp_servers.playwright.disabled_tools=["browser_run_code_unsafe","browser_file_upload"]', role_runner)
            self.assertIn('mcp_servers.context7.enabled=false', role_runner)
            self.assertIn('mcp_servers.playwright.enabled=false', role_runner)
            self.assertIn("PLAYWRIGHT_MCP_OUTPUT_DIR", single_lane_runner)
            self.assertIn("--codegen", helper)

            planner = (target / ".agentic" / "roles" / "planner.md").read_text(encoding="utf-8")
            builder = (target / ".agentic" / "roles" / "builder.md").read_text(encoding="utf-8")
            hardener = (target / ".agentic" / "roles" / "hardener.md").read_text(encoding="utf-8")
            integrator = (target / ".agentic" / "roles" / "integrator.md").read_text(encoding="utf-8")
            self.assertIn("auth errors", planner)
            self.assertIn("do not halt", builder)
            self.assertIn("browser_take_screenshot", hardener)
            self.assertIn("docs/backlog/ui_artifacts", integrator)

            result = subprocess.run(
                [
                    sys.executable,
                    str(CHECK_SCRIPT),
                    "--human-bridge-mode",
                    "disabled",
                    "--multi-role-enabled",
                    "--optional-mcp-enabled",
                    str(target),
                ],
                text=True,
                capture_output=True,
            )

            self.assertEqual("", result.stderr)
            self.assertEqual(0, result.returncode)

    def test_continuous_scaffold_uses_intake_specific_horizons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_target(target)
            prompt = (target / ".agentic" / "automation_prompt.md").read_text(encoding="utf-8")
            task = (target / "docs" / "CODEX_AUTOMATION_TASKS.md").read_text(encoding="utf-8")

            self.assertIn("H2 Local-first demo", prompt)
            self.assertIn("weekly board", prompt)
            self.assertIn("recurring review capsules", prompt)
            self.assertIn("## Improvement Backlog", task)
            self.assertNotIn("H2 Offline/local demo", prompt)

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_target(target, TRENDLAB_INTAKE)
            prompt = (target / ".agentic" / "automation_prompt.md").read_text(encoding="utf-8")

            self.assertIn("scored signals", prompt)
            self.assertIn("generated brief", prompt)
            self.assertIn("source-quality attribution", prompt)

    def test_ticket_campaign_scaffold_uses_ticket_phases_without_product_roadmap_language(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.NamedTemporaryFile("w", suffix=".json") as intake:
            target = Path(tmp)
            intake.write(
                """
{
  "project_name": "Ticket Campaign Smoke",
  "product_goal": "Resolve a bounded set of local tickets.",
  "target_user": "Maintainer reviewing local patches.",
  "desired_first_demo": "All listed tickets completed or blocked with evidence.",
  "human_bridge_enabled": false,
  "human_bridge_mode": "disabled",
  "automation_run_mode": "ticket_campaign",
  "verification_commands": ["npm test"]
}
""".strip()
            )
            intake.flush()

            self.scaffold_target(target, Path(intake.name))
            prompt = (target / ".agentic" / "automation_prompt.md").read_text(encoding="utf-8")
            bootstrap = (target / "docs" / "INITIAL_BOOTSTRAP_PROMPT.md").read_text(encoding="utf-8")
            task = (target / "docs" / "CODEX_AUTOMATION_TASKS.md").read_text(encoding="utf-8")
            combined = prompt + "\n" + bootstrap + "\n" + task

            self.assertIn("T1 Ticket-run readiness", combined)
            self.assertIn("T4 Completion report and stop", combined)
            self.assertIn("Ticket-campaign bootstrap is readiness-only", bootstrap)
            self.assertIn("Do not implement ticket acceptance criteria", bootstrap)
            self.assertIn("python3 scripts/ticket_run.py . next --json", prompt)
            self.assertIn("act on at most one dependency-ready ticket per run", prompt)
            self.assertIn("## Deferred / Follow-Up Tickets", task)
            for forbidden in ["MVP", "Beyond MVP", "Ambitious extensions"]:
                self.assertNotIn(forbidden, combined)

            result = subprocess.run(
                [
                    sys.executable,
                    str(CHECK_SCRIPT),
                    "--human-bridge-mode",
                    "disabled",
                    "--ticket-campaign-enabled",
                    str(target),
                ],
                text=True,
                capture_output=True,
            )

            self.assertEqual("", result.stderr)
            self.assertEqual(0, result.returncode)

            inferred_result = subprocess.run(
                [
                    sys.executable,
                    str(CHECK_SCRIPT),
                    "--ticket-campaign-enabled",
                    str(target),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual("", inferred_result.stderr)
            self.assertEqual(0, inferred_result.returncode)

    def test_missing_development_file_fails_required_files_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_target(target)
            (target / "docs" / "DEVELOPMENT.md").unlink()

            result = self.run_check(target)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("docs/DEVELOPMENT.md: missing", result.stderr)

    def test_development_checklist_marker_regression_fails_required_files_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_target(target)
            development = target / "docs" / "DEVELOPMENT.md"
            development.write_text(
                development.read_text(encoding="utf-8").replace(
                    "Run Safety Check",
                    "Run local checks",
                ),
                encoding="utf-8",
            )

            result = self.run_check(target)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("docs/DEVELOPMENT.md: missing marker 'Run Safety Check'", result.stderr)

    def test_development_review_bundle_command_regression_fails_required_files_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_target(target)
            development = target / "docs" / "DEVELOPMENT.md"
            development.write_text(
                development.read_text(encoding="utf-8").replace(
                    "--review-dir /tmp/Diffmogger-review",
                    "--review-output /tmp/Diffmogger-self-review.md",
                ),
                encoding="utf-8",
            )

            result = self.run_check(target)

            self.assertNotEqual(0, result.returncode)
            self.assertIn(
                "docs/DEVELOPMENT.md: missing marker 'python3 scripts/run_observatory.py --target . --review-dir /tmp/Diffmogger-review'",
                result.stderr,
            )

    def test_observatory_first_review_marker_regression_fails_required_files_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_target(target)
            observatory = target / "scripts" / "run_observatory.py"
            observatory.write_text(
                observatory.read_text(encoding="utf-8").replace(
                    "First Review Readiness",
                    "Review Readiness",
                ),
                encoding="utf-8",
            )

            result = self.run_check(target)

            self.assertNotEqual(0, result.returncode)
            self.assertIn(
                "scripts/run_observatory.py: missing marker 'First Review Readiness'",
                result.stderr,
            )

    def test_scaffolded_runner_uses_target_local_lock_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_target(target)
            runner = target / "scripts" / "run_codex_automation.sh"
            runner_text = runner.read_text(encoding="utf-8")

            self.assertIn("CODEX_LOCK_CONTEXT", runner_text)
            self.assertIn('target_name="$(basename "$TARGET")"', runner_text)
            self.assertNotIn("Diffmogger Self Improvement scheduled sprint", runner_text)

            result = self.run_check(target)

            self.assertEqual("", result.stderr)
            self.assertEqual(0, result.returncode)

    def test_self_run_lock_context_regression_fails_required_files_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_target(target)
            runner = target / "scripts" / "run_codex_automation.sh"
            runner.write_text(
                runner.read_text(encoding="utf-8").replace(
                    'bash scripts/acquire_codex_lock.sh "$lock_context" || exit 0',
                    'bash scripts/acquire_codex_lock.sh "Diffmogger Self Improvement scheduled sprint" || exit 0',
                ),
                encoding="utf-8",
            )

            result = self.run_check(target)

            self.assertNotEqual(0, result.returncode)
            self.assertIn(
                "scripts/run_codex_automation.sh: forbidden self-run marker",
                result.stderr,
            )


if __name__ == "__main__":
    unittest.main()
