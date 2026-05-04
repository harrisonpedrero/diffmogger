from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER_PATHS = [
    ROOT / "scripts" / "list_deferred_patches.py",
    ROOT / "templates" / "scripts" / "list_deferred_patches.py",
]


def load_helper(path: Path):
    module_name = (
        "list_deferred_under_test_"
        + path.relative_to(ROOT).as_posix().replace("/", "_").replace(".", "_")
    )
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class ListDeferredPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.modules = [(path, load_helper(path)) for path in HELPER_PATHS]

    def write_manifest(
        self,
        target: Path,
        *,
        role: str,
        run_id: str,
        status: str = "deferred",
        created_at: str = "2026-05-04T00:00:00+00:00",
        deferral_reason: str | None = "conflict",
        deferral_detail: str = "docs changed after role start",
        changed_files: list[str] | None = None,
    ) -> Path:
        path = target / "target" / "automation_queue" / role / run_id / "manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, object] = {
            "role": role,
            "run_id": run_id,
            "status": status,
            "created_at": created_at,
            "deferral_detail": deferral_detail,
            "changed_files": changed_files or ["docs/CODEX_AUTOMATION_TASKS.md"],
        }
        if deferral_reason is not None:
            payload["deferral_reason"] = deferral_reason
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return path

    def test_source_and_template_helpers_stay_byte_identical(self) -> None:
        source = HELPER_PATHS[0].read_text(encoding="utf-8")
        template = HELPER_PATHS[1].read_text(encoding="utf-8")
        self.assertEqual(source, template)

    def test_json_listing_keeps_existing_deferred_manifest_contract(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.write_manifest(
                        target,
                        role="builder",
                        run_id="run-new",
                        deferral_reason=None,
                        created_at="2026-05-04T00:02:00+00:00",
                    )
                    self.write_manifest(
                        target,
                        role="planner",
                        run_id="run-queued",
                        status="queued",
                        created_at="2026-05-04T00:01:00+00:00",
                    )

                    records = module.deferred_manifests(target)

                    self.assertEqual(len(records), 1)
                    self.assertEqual(records[0]["role"], "builder")
                    self.assertEqual(records[0]["run_id"], "run-new")
                    self.assertEqual(records[0]["deferral_reason"], "other")
                    self.assertEqual(
                        records[0]["manifest_path"],
                        "target/automation_queue/builder/run-new/manifest.json",
                    )

    def test_markdown_report_groups_actions_and_scrubs_local_paths(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.write_manifest(
                        target,
                        role="builder",
                        run_id="run-conflict",
                        deferral_reason="conflict",
                        deferral_detail=(
                            f"current file hash differs under {target}/docs and "
                            + "/User"
                            + "s/example/project"
                        ),
                        changed_files=[
                            "docs/HUMAN_INBOX.md",
                            "docs/CODEX_AUTOMATION_TASKS.md",
                            "docs/MULTI_ROLE_PROGRESS.md",
                            "target/automation_signals.json",
                            "docs/HUMAN_OUTBOX.md",
                        ],
                    )
                    self.write_manifest(
                        target,
                        role="planner",
                        run_id="run-stale",
                        deferral_reason="staleness",
                        deferral_detail="Patch base no longer matches HEAD.",
                    )

                    report = module.render_markdown(module.deferred_manifests(target), target)

                    self.assertIn("# Deferred Patch Triage", report)
                    self.assertIn("- deferred_count: 2", report)
                    self.assertIn("recommended_next_action: Start with `staleness`", report)
                    self.assertLess(report.index("## staleness"), report.index("## conflict"))
                    self.assertIn("Refresh or recreate the patch from current HEAD", report)
                    self.assertIn("builder `run-conflict`", report)
                    self.assertIn("docs/HUMAN_INBOX.md, docs/CODEX_AUTOMATION_TASKS.md", report)
                    self.assertIn("+1 more", report)
                    self.assertIn("<target>/docs", report)
                    self.assertIn("<local-path>/example/project", report)
                    self.assertNotIn(str(target), report)

    def test_markdown_cli_reports_empty_backlog(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    output = StringIO()
                    with redirect_stdout(output):
                        exit_code = module.main([tmp, "--markdown"])

                    self.assertEqual(exit_code, 0)
                    self.assertIn("- deferred_count: 0", output.getvalue())
                    self.assertIn("No deferred patches found.", output.getvalue())


if __name__ == "__main__":
    unittest.main()
