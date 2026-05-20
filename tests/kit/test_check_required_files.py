from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from diffmogger.runtime.paths import sidecar_rel

SCAFFOLD_SCRIPT = ROOT / "scripts" / "scaffold_project_docs.py"
CHECK_SCRIPT = ROOT / "scripts" / "check_required_files.py"
GENERIC_INTAKE = ROOT / "examples" / "generic-web-app" / "project_intake.md"
TRENDLAB_INTAKE = ROOT / "examples" / "trendlab-signal-intelligence" / "project_intake.md"


def generated_path(target: Path, legacy_rel: str) -> Path:
    if legacy_rel.startswith("scripts/"):
        return target / ".diffmogger" / legacy_rel
    return target / sidecar_rel(legacy_rel)


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

    def test_scaffolded_target_uses_lean_state_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_target(target)
            manifest = json.loads((target / ".diffmogger" / "manifest.json").read_text(encoding="utf-8"))

            result = self.run_check(target)

            self.assertIn("AGENTS.md", manifest["worktree_seed_paths"])
            state_files = {
                path.relative_to(target).as_posix()
                for path in (target / ".diffmogger" / "state").rglob("*")
                if path.is_file()
            }
            self.assertEqual(
                {
                    ".diffmogger/state/CODEX_AUTOMATION_GUARDRAILS.md",
                    ".diffmogger/state/CODEX_AUTOMATION_TASKS.md",
                    ".diffmogger/state/DEVELOPMENT.md",
                },
                state_files,
            )
            for stale in [
                ".diffmogger/state/PROJECT_CONTEXT.md",
                ".diffmogger/state/MULTI_ROLE_PROGRESS.md",
                ".diffmogger/state/AUTONOMY_EXPERIMENT_LOG.md",
                ".diffmogger/state/DAILY_AUTOMATION_REVIEW.md",
                ".diffmogger/state/HUMAN_BRIDGE_SETUP.md",
                ".diffmogger/state/MCP_INTEGRATIONS.md",
            ]:
                self.assertNotIn(stale, manifest["owned_paths"])
            self.assertEqual("", result.stderr)
            self.assertEqual(0, result.returncode)

    def test_default_scaffold_generates_supported_mcp_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_target(target)

            for rel in [
                ".codex/config.toml",
            ]:
                self.assertTrue(generated_path(target, rel).exists(), rel)
            self.assertTrue(generated_path(target, "scripts/run_playwright_mcp.sh").exists())
            intake = json.loads(generated_path(target, ".agentic/project_intake.json").read_text(encoding="utf-8"))
            self.assertEqual(["context7", "playwright"], intake["optional_mcp_servers"])

            result = subprocess.run(
                [
                    sys.executable,
                    str(CHECK_SCRIPT),
                    "--human-bridge-mode",
                    "file_only",
                    "--multi-role-enabled",
                    "--optional-mcp-enabled",
                    str(target),
                ],
                text=True,
                capture_output=True,
            )

            self.assertEqual("", result.stderr)
            self.assertEqual(0, result.returncode)

    def test_explicit_optional_mcp_opt_out_omits_mcp_state_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.NamedTemporaryFile("w", suffix=".json") as intake:
            target = Path(tmp)
            intake.write(
                """
{
  "project_name": "MCP Opt Out",
  "product_goal": "Validate explicit MCP opt-out.",
  "target_user": "Automation tester.",
  "desired_first_demo": "Generated docs only.",
  "human_bridge_enabled": false,
  "human_bridge_mode": "disabled",
  "automation_role_profile": "planner_builder_hardener_integrator",
  "optional_mcp_servers": [],
  "verification_commands": ["npm test"]
}
""".strip()
            )
            intake.flush()

            self.scaffold_target(target, Path(intake.name))

            for rel in [
                ".codex/config.toml",
                "docs/MCP_INTEGRATIONS.md",
                "docs/backlog/README.md",
                "scripts/run_playwright_mcp.sh",
            ]:
                self.assertFalse(generated_path(target, rel).exists(), rel)

            result = subprocess.run(
                [
                    sys.executable,
                    str(CHECK_SCRIPT),
                    "--human-bridge-mode",
                    "disabled",
                    "--multi-role-enabled",
                    str(target),
                ],
                text=True,
                capture_output=True,
            )

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
  "automation_role_profile": "planner_builder_hardener_integrator",
  "optional_mcp_servers": ["context7", "playwright"],
  "verification_commands": ["npm test"]
}
""".strip()
            )
            intake.flush()

            self.scaffold_target(target, Path(intake.name))
            config = generated_path(target, ".codex/config.toml").read_text(encoding="utf-8")
            role_runner = generated_path(target, "scripts/run_role_automation.sh").read_text(encoding="utf-8")
            helper = generated_path(target, "scripts/run_playwright_mcp.sh").read_text(encoding="utf-8")

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
            self.assertIn("codex exec --sandbox danger-full-access", role_runner)
            self.assertIn('approval_policy="never"', role_runner)
            self.assertNotIn("--full-auto", role_runner)
            self.assertIn("PLAYWRIGHT_MCP_OUTPUT_DIR", role_runner)
            self.assertIn("--codegen", helper)

            planner = generated_path(target, ".agentic/roles/planner.md").read_text(encoding="utf-8")
            builder = generated_path(target, ".agentic/roles/builder.md").read_text(encoding="utf-8")
            hardener = generated_path(target, ".agentic/roles/hardener.md").read_text(encoding="utf-8")
            integrator = generated_path(target, ".agentic/roles/integrator.md").read_text(encoding="utf-8")
            self.assertIn("auth errors", planner)
            self.assertIn("do not halt", builder)
            self.assertIn("local browser validation", hardener)
            self.assertIn("CODEX_AUTOMATION_TASKS", integrator)

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

    def test_legacy_single_lane_intake_still_scaffolds_conveyor_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.NamedTemporaryFile("w", suffix=".json") as intake:
            target = Path(tmp)
            intake.write(
                """
{
  "project_name": "Single Lane Smoke",
  "product_goal": "Run continuous solo automation for reusable docs and reports.",
  "target_user": "Automation tester.",
  "desired_first_demo": "Generated docs only.",
  "human_bridge_enabled": false,
  "human_bridge_mode": "disabled",
  "automation_role_profile": "single_lane",
  "verification_commands": ["npm test"]
}
""".strip()
            )
            intake.flush()

            self.scaffold_target(target, Path(intake.name))

            self.assertTrue(generated_path(target, "scripts/run_conveyor_automation.sh").exists())
            self.assertFalse(generated_path(target, "scripts/run_codex_automation.sh").exists())
            for rel in [
                ".agentic/roles/planner.md",
                ".agentic/roles/builder.md",
                ".agentic/roles/hardener.md",
                ".agentic/roles/integrator.md",
                "scripts/run_role_automation.sh",
                "scripts/integrate_role_outputs.py",
                "scripts/list_deferred_patches.py",
            ]:
                self.assertTrue(generated_path(target, rel).exists(), rel)

            agents = (target / "AGENTS.md").read_text(encoding="utf-8")
            task = generated_path(target, "docs/CODEX_AUTOMATION_TASKS.md").read_text(encoding="utf-8")
            guardrails = generated_path(target, "docs/CODEX_AUTOMATION_GUARDRAILS.md").read_text(encoding="utf-8")
            manifest = (target / ".diffmogger" / "manifest.json").read_text(encoding="utf-8")
            self.assertIn("Blockers are node metadata", agents)
            self.assertIn("## Scheduler Work", task)
            self.assertIn("Only unsafe corruption or destructive risk", task)
            self.assertIn("Diffmogger is a work generator", guardrails)
            self.assertIn('"automation_role_profile": "planner_builder_hardener_integrator"', manifest)

            result = subprocess.run(
                [
                    sys.executable,
                    str(CHECK_SCRIPT),
                    "--human-bridge-mode",
                    "disabled",
                    str(target),
                ],
                text=True,
                capture_output=True,
            )

            self.assertEqual("", result.stderr)
            self.assertEqual(0, result.returncode)

    def test_continuous_scaffold_uses_intake_specific_brief(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_target(target)
            prompt = generated_path(target, ".agentic/automation_prompt.md").read_text(encoding="utf-8")
            task = generated_path(target, "docs/CODEX_AUTOMATION_TASKS.md").read_text(encoding="utf-8")
            combined = prompt + "\n" + task

            self.assertIn("weekly board", combined)
            self.assertIn("recurring review capsules", combined)
            self.assertIn("## Improvement Backlog", task)
            self.assertNotIn("H2 Offline/local demo", combined)

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_target(target, TRENDLAB_INTAKE)
            prompt = generated_path(target, ".agentic/automation_prompt.md").read_text(encoding="utf-8")
            task = generated_path(target, "docs/CODEX_AUTOMATION_TASKS.md").read_text(encoding="utf-8")
            combined = prompt + "\n" + task

            self.assertIn("scored signals", combined)
            self.assertIn("generated brief", combined)
            self.assertIn("source-quality attribution", combined)

    def test_ticket_campaign_scaffold_uses_lean_ticket_guidance_without_product_roadmap_language(self) -> None:
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
  "campaign_mode": "bounded",
  "verification_commands": ["npm test"]
}
""".strip()
            )
            intake.flush()

            self.scaffold_target(target, Path(intake.name))
            prompt = generated_path(target, ".agentic/automation_prompt.md").read_text(encoding="utf-8")
            task = generated_path(target, "docs/CODEX_AUTOMATION_TASKS.md").read_text(encoding="utf-8")
            combined = prompt + "\n" + task

            self.assertIn("Campaign mode: `bounded`", combined)
            self.assertIn("Halt only when every ticket is done with evidence", combined)
            self.assertFalse(generated_path(target, "docs/INITIAL_BOOTSTRAP_PROMPT.md").exists())
            self.assertIn("Scaffold seeds and validates the ticket queue", combined)
            self.assertIn("python3 .diffmogger/scripts/ticket_run.py . next --json", prompt)
            self.assertIn("execution DAG", prompt)
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
            generated_path(target, "docs/DEVELOPMENT.md").unlink()

            result = self.run_check(target)

            self.assertNotEqual(0, result.returncode)
            self.assertIn(f"{sidecar_rel('docs/DEVELOPMENT.md')}: missing", result.stderr)

    def test_development_verification_marker_regression_fails_required_files_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_target(target)
            development = generated_path(target, "docs/DEVELOPMENT.md")
            development.write_text(
                development.read_text(encoding="utf-8").replace(
                    "## Verification",
                    "## Checks",
                ),
                encoding="utf-8",
            )

            result = self.run_check(target)

            self.assertNotEqual(0, result.returncode)
            self.assertIn(f"{sidecar_rel('docs/DEVELOPMENT.md')}: missing marker '## Verification'", result.stderr)

    def test_development_browser_helper_regression_fails_required_files_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_target(target)
            development = generated_path(target, "docs/DEVELOPMENT.md")
            development.write_text(
                development.read_text(encoding="utf-8").replace(
                    "python3 .diffmogger/scripts/diffmogger_browser.py doctor --launch",
                    "python3 .diffmogger/scripts/diffmogger_browser.py env",
                ),
                encoding="utf-8",
            )

            result = self.run_check(target)

            self.assertNotEqual(0, result.returncode)
            self.assertIn(
                f"{sidecar_rel('docs/DEVELOPMENT.md')}: missing marker 'python3 .diffmogger/scripts/diffmogger_browser.py doctor --launch'",
                result.stderr,
            )

    def test_observatory_first_review_marker_regression_fails_required_files_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_target(target)
            observatory = target / ".diffmogger" / "lib" / "diffmogger" / "observatory"
            for path in observatory.glob("*.py"):
                path.write_text(
                    path.read_text(encoding="utf-8").replace(
                        "First Review Readiness",
                        "Review Readiness",
                    ),
                    encoding="utf-8",
                )

            result = self.run_check(target)

            self.assertNotEqual(0, result.returncode)
            self.assertIn(
                ".diffmogger/scripts/run_observatory.py: missing marker 'First Review Readiness'",
                result.stderr,
            )

    def test_scaffold_does_not_generate_single_lane_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_target(target)
            self.assertFalse(generated_path(target, "scripts/run_codex_automation.sh").exists())
            self.assertTrue(generated_path(target, "scripts/run_conveyor_automation.sh").exists())
            self.assertTrue(generated_path(target, "scripts/run_role_automation.sh").exists())

            result = self.run_check(target)

            self.assertEqual("", result.stderr)
            self.assertEqual(0, result.returncode)

if __name__ == "__main__":
    unittest.main()
