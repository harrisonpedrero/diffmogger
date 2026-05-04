from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INTEGRATOR_PATHS = [
    ROOT / "scripts" / "integrate_role_outputs.py",
    ROOT / "templates" / "scripts" / "integrate_role_outputs.py",
]


def load_integrator(path: Path):
    module_name = (
        "integrator_under_test_"
        + path.relative_to(ROOT).as_posix().replace("/", "_").replace(".", "_")
    )
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class RuntimeStateActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.modules = [(path, load_integrator(path)) for path in INTEGRATOR_PATHS]

    def write_actions(self, target: Path, actions: list[dict[str, object]]) -> dict[str, object]:
        path = target / "target" / "automation_queue" / "builder" / "run-001" / "runtime_state_actions.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema_version": 1, "actions": actions}, indent=2) + "\n", encoding="utf-8")
        return {
            "runtime_state_actions_path": str(path),
            "runtime_state_status": "pending",
            "runtime_state_results": [],
        }

    def replace_action(self, rel_path: str, start: str | None, end: str) -> dict[str, object]:
        return {
            "action": "replace_file",
            "path": rel_path,
            "start_hash": sha256_text(start) if start is not None else None,
            "end_hash": sha256_text(end),
            "content": end,
        }

    def test_runtime_state_replace_file_applies_whitelisted_content(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    inbox = target / "docs" / "HUMAN_INBOX.md"
                    inbox.parent.mkdir(parents=True)
                    inbox.write_text("old inbox\n", encoding="utf-8")
                    manifest = self.write_actions(
                        target,
                        [self.replace_action("docs/HUMAN_INBOX.md", "old inbox\n", "new inbox\n")],
                    )

                    results = module.apply_runtime_state_actions(target, manifest, dry_run=False)

                    self.assertEqual(inbox.read_text(encoding="utf-8"), "new inbox\n")
                    self.assertEqual(manifest["runtime_state_status"], "applied")
                    self.assertEqual(results[0]["status"], "applied")

    def test_runtime_state_applies_live_role_prompt_updates(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    prompt = target / ".agentic" / "roles" / "builder.md"
                    prompt.parent.mkdir(parents=True)
                    prompt.write_text("old builder prompt\n", encoding="utf-8")
                    manifest = self.write_actions(
                        target,
                        [
                            self.replace_action(
                                ".agentic/roles/builder.md",
                                "old builder prompt\n",
                                "new builder prompt\n",
                            )
                        ],
                    )

                    results = module.apply_runtime_state_actions(target, manifest, dry_run=False)

                    self.assertEqual(prompt.read_text(encoding="utf-8"), "new builder prompt\n")
                    self.assertEqual(manifest["runtime_state_status"], "applied")
                    self.assertEqual(results[0]["status"], "applied")

    def test_runtime_state_applies_arbitrary_ignored_docs_file(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    subprocess.run(["git", "init"], cwd=target, check=True, stdout=subprocess.DEVNULL)
                    (target / ".gitignore").write_text("docs/LOCAL_RUNTIME.md\n", encoding="utf-8")
                    runtime_doc = target / "docs" / "LOCAL_RUNTIME.md"
                    runtime_doc.parent.mkdir(parents=True)
                    runtime_doc.write_text("old runtime doc\n", encoding="utf-8")
                    manifest = self.write_actions(
                        target,
                        [
                            self.replace_action(
                                "docs/LOCAL_RUNTIME.md",
                                "old runtime doc\n",
                                "new runtime doc\n",
                            )
                        ],
                    )

                    results = module.apply_runtime_state_actions(target, manifest, dry_run=False)

                    self.assertEqual(runtime_doc.read_text(encoding="utf-8"), "new runtime doc\n")
                    self.assertEqual(manifest["runtime_state_status"], "applied")
                    self.assertEqual(results[0]["status"], "applied")

    def test_runtime_state_rejects_env_file_even_when_ignored(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    subprocess.run(["git", "init"], cwd=target, check=True, stdout=subprocess.DEVNULL)
                    (target / ".gitignore").write_text(".env\n", encoding="utf-8")
                    manifest = self.write_actions(target, [self.replace_action(".env", None, "SECRET=value\n")])

                    results = module.apply_runtime_state_actions(target, manifest, dry_run=False)

                    self.assertFalse((target / ".env").exists())
                    self.assertEqual(manifest["runtime_state_status"], "deferred")
                    self.assertEqual(results[0]["status"], "rejected")

    def test_runtime_state_conflict_defers_without_overwrite(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    inbox = target / "docs" / "HUMAN_INBOX.md"
                    inbox.parent.mkdir(parents=True)
                    inbox.write_text("changed after role start\n", encoding="utf-8")
                    manifest = self.write_actions(
                        target,
                        [self.replace_action("docs/HUMAN_INBOX.md", "old inbox\n", "new inbox\n")],
                    )

                    results = module.apply_runtime_state_actions(target, manifest, dry_run=False)

                    self.assertEqual(inbox.read_text(encoding="utf-8"), "changed after role start\n")
                    self.assertEqual(manifest["runtime_state_status"], "deferred")
                    self.assertEqual(results[0]["status"], "conflict")

    def test_runtime_state_rejects_non_whitelisted_path(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    manifest = self.write_actions(
                        target,
                        [self.replace_action("docs/NOT_WHITELISTED.md", None, "nope\n")],
                    )

                    results = module.apply_runtime_state_actions(target, manifest, dry_run=False)

                    self.assertFalse((target / "docs" / "NOT_WHITELISTED.md").exists())
                    self.assertEqual(manifest["runtime_state_status"], "deferred")
                    self.assertEqual(results[0]["status"], "rejected")

    def test_runtime_state_marks_already_applied(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    inbox = target / "docs" / "HUMAN_INBOX.md"
                    inbox.parent.mkdir(parents=True)
                    inbox.write_text("new inbox\n", encoding="utf-8")
                    manifest = self.write_actions(
                        target,
                        [self.replace_action("docs/HUMAN_INBOX.md", "old inbox\n", "new inbox\n")],
                    )

                    results = module.apply_runtime_state_actions(target, manifest, dry_run=False)

                    self.assertEqual(inbox.read_text(encoding="utf-8"), "new inbox\n")
                    self.assertEqual(manifest["runtime_state_status"], "already_applied")
                    self.assertEqual(results[0]["status"], "already_applied")

    def test_semantic_commit_message_describes_observatory_patch(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                manifest = {
                    "role": "builder",
                    "changed_files": [
                        "scripts/run_observatory.py",
                        "templates/scripts/run_observatory.py",
                        "tests/test_run_observatory.py",
                    ],
                }

                message = module.semantic_commit_message(manifest, ROOT, "run-observe")

                self.assertEqual(
                    message,
                    "feat(observatory): surface automation progress details\n\n"
                    "Role: builder\n"
                    "Patch-run: run-observe",
                )

    def test_semantic_commit_message_describes_docs_only_patch(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                manifest = {
                    "role": "planner",
                    "changed_files": ["docs/DASHBOARD.md", "README.md"],
                }

                message = module.semantic_commit_message(manifest, ROOT, "run-docs")

                self.assertEqual(
                    message,
                    "docs(docs): document automation progress\n\n"
                    "Role: planner\n"
                    "Patch-run: run-docs",
                )

    def test_first_summary_line_skips_wrapper_heading(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                summary = """# builder role run run-001

- base_commit: abc
- codex_exit_code: 0

Implemented the useful thing.
"""

                self.assertEqual(module.first_summary_line(summary), "Implemented the useful thing.")


if __name__ == "__main__":
    unittest.main()
