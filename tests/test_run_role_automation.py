from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROLE_RUNNER_PATHS = [
    ROOT / "scripts" / "run_role_automation.sh",
    ROOT / "templates" / "scripts" / "run_role_automation.sh",
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
        codex.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
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

    def test_source_and_template_role_runners_stay_byte_identical(self) -> None:
        source = ROLE_RUNNER_PATHS[0].read_text(encoding="utf-8")
        template = ROLE_RUNNER_PATHS[1].read_text(encoding="utf-8")
        self.assertEqual(source, template)

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


if __name__ == "__main__":
    unittest.main()
