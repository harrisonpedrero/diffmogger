from __future__ import annotations

import hashlib
import importlib.util
import json
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
INTEGRATOR_PATHS = [
    ROOT / "src" / "diffmogger" / "runtime" / "integrate_role_outputs.py",
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

    def init_repo(self, target: Path, *, bridge_mode: str = "discord_notifier") -> None:
        (target / ".agentic").mkdir(parents=True, exist_ok=True)
        (target / ".agentic" / "project_intake.json").write_text(
            json.dumps({"human_bridge_mode": bridge_mode}, indent=2) + "\n",
            encoding="utf-8",
        )
        (target / "docs").mkdir(parents=True, exist_ok=True)
        (target / "docs" / "CODEX_AUTOMATION_TASKS.md").write_text("tasks v1\n", encoding="utf-8")
        (target / "docs" / "MULTI_ROLE_PROGRESS.md").write_text("progress v1\n", encoding="utf-8")
        (target / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "init"], cwd=target, check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "add", "."], cwd=target, check=True, stdout=subprocess.DEVNULL)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-m",
                "chore: base",
            ],
            cwd=target,
            check=True,
            stdout=subprocess.DEVNULL,
        )

    def add_committed_file(self, target: Path, relative: str, content: str) -> None:
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        subprocess.run(["git", "add", relative], cwd=target, check=True, stdout=subprocess.DEVNULL)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-m",
                f"test: add {Path(relative).name}",
            ],
            cwd=target,
            check=True,
            stdout=subprocess.DEVNULL,
        )

    def write_patch_for_file(self, target: Path, relative: str, new_content: str, patch_path: Path) -> None:
        (target / relative).write_text(new_content, encoding="utf-8")
        result = subprocess.run(
            ["git", "diff", "--binary", "HEAD", "--", relative],
            cwd=target,
            check=True,
            text=True,
            capture_output=True,
        )
        patch_path.write_text(result.stdout, encoding="utf-8")
        subprocess.run(["git", "checkout", "--", relative], cwd=target, check=True, stdout=subprocess.DEVNULL)

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
                    task_doc = target / "docs" / "CODEX_AUTOMATION_TASKS.md"
                    task_doc.parent.mkdir(parents=True)
                    task_doc.write_text("old task state\n", encoding="utf-8")
                    manifest = self.write_actions(
                        target,
                        [self.replace_action("docs/CODEX_AUTOMATION_TASKS.md", "old task state\n", "new task state\n")],
                    )

                    results = module.apply_runtime_state_actions(target, manifest, dry_run=False)

                    self.assertEqual(task_doc.read_text(encoding="utf-8"), "new task state\n")
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
                    task_doc = target / "docs" / "CODEX_AUTOMATION_TASKS.md"
                    task_doc.parent.mkdir(parents=True)
                    task_doc.write_text("changed after role start\n", encoding="utf-8")
                    manifest = self.write_actions(
                        target,
                        [self.replace_action("docs/CODEX_AUTOMATION_TASKS.md", "old task state\n", "new task state\n")],
                    )

                    results = module.apply_runtime_state_actions(target, manifest, dry_run=False)

                    self.assertEqual(task_doc.read_text(encoding="utf-8"), "changed after role start\n")
                    self.assertEqual(manifest["runtime_state_status"], "deferred")
                    self.assertEqual(results[0]["status"], "conflict")

    def test_runtime_state_runner_conflict_does_not_block_docs(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    task_doc = target / "docs" / "CODEX_AUTOMATION_TASKS.md"
                    runner = target / "target" / "automation_runner.json"
                    task_doc.parent.mkdir(parents=True)
                    runner.parent.mkdir(parents=True)
                    task_doc.write_text("old task state\n", encoding="utf-8")
                    runner.write_text("changed by integrator\n", encoding="utf-8")
                    manifest = self.write_actions(
                        target,
                        [
                            self.replace_action("docs/CODEX_AUTOMATION_TASKS.md", "old task state\n", "new task state\n"),
                            self.replace_action(
                                "target/automation_runner.json",
                                "role-start runner\n",
                                "role-end runner\n",
                            ),
                        ],
                    )

                    results = module.apply_runtime_state_actions(target, manifest, dry_run=False)

                    self.assertEqual(task_doc.read_text(encoding="utf-8"), "new task state\n")
                    self.assertEqual(runner.read_text(encoding="utf-8"), "changed by integrator\n")
                    self.assertEqual(manifest["runtime_state_status"], "applied")
                    self.assertEqual(results[0]["status"], "applied")
                    self.assertEqual(results[1]["status"], "skipped_volatile")

    def test_runtime_state_sidecar_conveyor_conflict_does_not_block_state(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    manifest_doc = target / ".diffmogger" / "manifest.json"
                    task_doc = target / ".diffmogger" / "state" / "CODEX_AUTOMATION_TASKS.md"
                    conveyor = target / ".diffmogger" / "runtime" / "automation_conveyor_state.json"
                    manifest_doc.parent.mkdir(parents=True)
                    task_doc.parent.mkdir(parents=True)
                    conveyor.parent.mkdir(parents=True)
                    manifest_doc.write_text(
                        json.dumps(
                            {
                                "layout": "sidecar_v1",
                                "worktree_seed_paths": [
                                    ".diffmogger/state/CODEX_AUTOMATION_TASKS.md",
                                    ".diffmogger/runtime/automation_conveyor_state.json",
                                ],
                            }
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    task_doc.write_text("old task state\n", encoding="utf-8")
                    conveyor.write_text("changed by live conveyor\n", encoding="utf-8")
                    manifest = self.write_actions(
                        target,
                        [
                            self.replace_action(
                                ".diffmogger/state/CODEX_AUTOMATION_TASKS.md",
                                "old task state\n",
                                "new task state\n",
                            ),
                            self.replace_action(
                                ".diffmogger/runtime/automation_conveyor_state.json",
                                "role-start conveyor\n",
                                "role-end conveyor\n",
                            ),
                        ],
                    )

                    results = module.apply_runtime_state_actions(target, manifest, dry_run=False)

                    self.assertEqual(task_doc.read_text(encoding="utf-8"), "new task state\n")
                    self.assertEqual(conveyor.read_text(encoding="utf-8"), "changed by live conveyor\n")
                    self.assertEqual(manifest["runtime_state_status"], "applied")
                    self.assertEqual(results[0]["status"], "applied")
                    self.assertEqual(results[1]["status"], "skipped_volatile")

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
                    task_doc = target / "docs" / "CODEX_AUTOMATION_TASKS.md"
                    task_doc.parent.mkdir(parents=True)
                    task_doc.write_text("new task state\n", encoding="utf-8")
                    manifest = self.write_actions(
                        target,
                        [self.replace_action("docs/CODEX_AUTOMATION_TASKS.md", "old task state\n", "new task state\n")],
                    )

                    results = module.apply_runtime_state_actions(target, manifest, dry_run=False)

                    self.assertEqual(task_doc.read_text(encoding="utf-8"), "new task state\n")
                    self.assertEqual(manifest["runtime_state_status"], "already_applied")
                    self.assertEqual(results[0]["status"], "already_applied")

    def test_semantic_commit_message_describes_observatory_patch(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                manifest = {
                    "role": "builder",
                    "changed_files": [
                        "scripts/run_observatory.py",
                        "src/diffmogger/runtime/run_observatory.py",
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
                    "docs(dashboard): document dashboard workflow\n\n"
                    "Role: planner\n"
                    "Patch-run: run-docs",
                )

    def test_semantic_commit_message_prefers_valid_role_commit_intent(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                manifest = {
                    "role": "builder",
                    "changed_files": [
                        "README.md",
                        "docs/DEVELOPMENT.md",
                        "src/lib/planning.test.ts",
                        "src/lib/planning.ts",
                    ],
                    "summary": "\n".join(
                        [
                            "Commit type: feat",
                            "Commit scope: review",
                            "Commit subject: add baseline comparison guidance to review briefs",
                            "",
                            "## Summary",
                            "- Added stable no-baseline review brief guidance.",
                        ]
                    ),
                }

                message = module.semantic_commit_message(manifest, ROOT, "run-intent")

                self.assertEqual(
                    message,
                    "feat(review): add baseline comparison guidance to review briefs\n\n"
                    "Role: builder\n"
                    "Patch-run: run-intent",
                )

    def test_semantic_commit_message_ignores_docs_scope_for_mixed_product_patch(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    patch = target / "changes.patch"
                    patch.write_text(
                        "diff --git a/src/lib/planning.ts b/src/lib/planning.ts\n"
                        "+  lines.push(\"### Closure Checklist\");\n",
                        encoding="utf-8",
                    )
                    manifest = {
                        "role": "builder",
                        "patch_path": str(patch),
                        "changed_files": [
                            "README.md",
                            "docs/DEVELOPMENT.md",
                            "scripts/browser_smoke.mjs",
                            "src/App.tsx",
                            "src/lib/planning.test.ts",
                            "src/lib/planning.ts",
                            "src/styles.css",
                        ],
                        "summary": "\n".join(
                            [
                                "Commit type: feat",
                                "Commit scope: docs",
                                "Commit subject: integrate builder work",
                            ]
                        ),
                    }

                    message = module.semantic_commit_message(manifest, target, "run-product")

                    self.assertEqual(
                        message,
                        "feat(planning): add review closure checklist\n\n"
                        "Role: builder\n"
                        "Patch-run: run-product",
                    )

    def test_semantic_commit_message_describes_browser_smoke_diagnostics(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    patch = target / "changes.patch"
                    patch.write_text(
                        "diff --git a/scripts/browser_smoke.mjs b/scripts/browser_smoke.mjs\n"
                        "+      status: \"failed_missing_browser\",\n"
                        "+      diagnosticPath: \"target/browser-smoke/chrome-launch-diagnostics.json\",\n",
                        encoding="utf-8",
                    )
                    manifest = {
                        "role": "hardener",
                        "patch_path": str(patch),
                        "changed_files": [
                            "README.md",
                            "docs/DEVELOPMENT.md",
                            "docs/LOCAL_FIRST_BASELINE.md",
                            "package.json",
                            "scripts/browser_smoke.mjs",
                        ],
                        "summary": "# hardener role run run-smoke\n\n- patch: /tmp/changes.patch\n",
                    }

                    message = module.semantic_commit_message(manifest, target, "run-smoke")

                    self.assertEqual(
                        message,
                        "test(browser-smoke): report browser smoke launch diagnostics\n\n"
                        "Role: hardener\n"
                        "Patch-run: run-smoke",
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

    def test_first_summary_line_skips_wrapper_paths_and_commit_intent(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                summary = """# builder role run run-001

Commit type: feat
Commit scope: planning
Commit subject: add review closure checklist
- patch: /tmp/example-project/target/automation_queue/builder/run/changes.patch
Review `/tmp/example-project/target/automation_queue/builder/run/codex.raw.log` for raw Codex output.

## Summary
- Added closure checklist rows to the weekly review handoff.
"""

                self.assertEqual(
                    module.first_summary_line(summary),
                    "Added closure checklist rows to the weekly review handoff.",
                )

    def test_patch_commit_posts_discord_progress_notification(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.init_repo(target)
                    source = target / "src" / "app.py"
                    source.parent.mkdir(parents=True, exist_ok=True)
                    source.write_text("print('hello')\n", encoding="utf-8")
                    manifest = {
                        "role": "builder",
                        "run_id": "builder-run-001",
                        "changed_files": ["src/app.py"],
                        "summary": "\n".join(
                            [
                                "Commit type: feat",
                                "Commit scope: app",
                                "Commit subject: add app workflow",
                                "",
                                "## Summary",
                                "- Added the app workflow.",
                            ]
                        ),
                    }
                    calls: list[dict[str, object]] = []
                    original_post = module.post_notifier
                    try:
                        module.post_notifier = lambda payload: calls.append(payload) or {"ok": True}
                        commit = module.commit_current_patch(
                            target,
                            manifest,
                            "integrator-run-001",
                            dry_run=False,
                        )
                    finally:
                        module.post_notifier = original_post

                    self.assertIsNotNone(commit)
                    self.assertEqual(1, len(calls))
                    payload = calls[0]
                    self.assertEqual("progress", payload["event_kind"])
                    self.assertEqual("automation_commit_progress", payload["type"])
                    self.assertFalse(payload["expects_reply"])
                    self.assertFalse(payload["local_notify"])
                    self.assertIn("feat(app): add app workflow", str(payload["message_body"]))
                    self.assertIn("Added the app workflow.", str(payload["message_body"]))
                    self.assertEqual(f"commit-progress:{commit}", payload["dedupe_key"])

    def test_commit_progress_notification_is_disabled_outside_discord_mode(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.init_repo(target, bridge_mode="local_notifier")
                    calls: list[dict[str, object]] = []
                    original_post = module.post_notifier
                    try:
                        module.post_notifier = lambda payload: calls.append(payload) or {"ok": True}
                        result = module.notify_commit_progress(
                            target,
                            commit_hash="abc123def456",
                            commit_message="feat(app): add thing",
                            description="Added a useful thing.",
                            run_id="integrator-run-001",
                            dry_run=False,
                        )
                    finally:
                        module.post_notifier = original_post

                    self.assertEqual({"status": "disabled", "detail": "human bridge mode is not discord_notifier"}, result)
                    self.assertEqual([], calls)

    def test_checkpoint_and_state_commits_post_discord_progress_notifications(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.init_repo(target)
                    (target / "README.md").write_text("dirty main\n", encoding="utf-8")
                    calls: list[dict[str, object]] = []
                    original_post = module.post_notifier
                    try:
                        module.post_notifier = lambda payload: calls.append(payload) or {"ok": True}
                        checkpoint, dirty_files = module.checkpoint_dirty_main(
                            target,
                            "integrator-run-002",
                            dry_run=False,
                        )
                        (target / "docs" / "CODEX_AUTOMATION_TASKS.md").write_text("tasks v2\n", encoding="utf-8")
                        state_commit = module.commit_automation_state(
                            target,
                            "integrator-run-002",
                            dry_run=False,
                        )
                    finally:
                        module.post_notifier = original_post

                    self.assertIsNotNone(checkpoint)
                    self.assertIn("README.md", dirty_files)
                    self.assertIsNotNone(state_commit)
                    self.assertEqual(2, len(calls))
                    checkpoint_message = subprocess.run(
                        ["git", "log", "-1", "--format=%B", str(checkpoint)],
                        cwd=target,
                        text=True,
                        capture_output=True,
                        check=True,
                    ).stdout
                    self.assertIn(
                        "chore(integrator): checkpoint preexisting local changes",
                        checkpoint_message,
                    )
                    self.assertIn("Run: integrator-run-002", checkpoint_message)
                    bodies = [str(payload["message_body"]) for payload in calls]
                    self.assertIn("checkpoint preexisting local changes", bodies[0])
                    self.assertIn("update multi-role state", bodies[1])
                    self.assertTrue(all(payload["event_kind"] == "progress" for payload in calls))

    def test_preferred_prompt_verification_is_not_used_as_gate(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    (target / ".agentic").mkdir(parents=True)
                    (target / ".agentic" / "automation_prompt.md").write_text(
                        "## Verification\n\n```text\npython3 -c 'import sys; sys.exit(9)'\n```\n",
                        encoding="utf-8",
                    )

                    result = module.run_verification(target, {"role": "builder", "changed_files": ["src/app.ts"]})

                    self.assertTrue(result.ok)
                    self.assertIn("No patch-scoped verification commands configured", "\n".join(result.checks_run))

    def test_builder_patch_does_not_run_full_suite_without_scope_requirement(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    (target / ".agentic").mkdir(parents=True)
                    (target / ".agentic" / "verification_commands.txt").write_text(
                        "python3 -c 'import sys; sys.exit(7)'\n",
                        encoding="utf-8",
                    )

                    result = module.run_verification(target, {"role": "builder", "changed_files": ["src/app.ts"]})

                    self.assertTrue(result.ok)
                    joined = "\n".join(result.checks_run)
                    self.assertIn("Full-suite verification configured", joined)
                    self.assertNotIn("sys.exit(7)", joined)

    def test_not_required_full_suite_note_does_not_hide_typescript_failure(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    (target / ".agentic").mkdir(parents=True)
                    (target / ".agentic" / "verification_commands.txt").write_text(
                        "python3 -c 'import sys; sys.exit(7)'\n",
                        encoding="utf-8",
                    )
                    (target / ".agentic" / "smoke_commands.txt").write_text(
                        "builder | python3 -c 'import sys; "
                        'print("src/app.ts(12,9): error TS2345: Argument of type undefined is not assignable", file=sys.stderr); '
                        "sys.exit(2)'\n",
                        encoding="utf-8",
                    )

                    result = module.run_verification(target, {"role": "builder", "changed_files": ["src/app.ts"]})

                    self.assertFalse(result.ok)
                    self.assertEqual("verification_failure", result.reason)
                    self.assertEqual("typescript_compiler_error", result.category)
                    self.assertIn("TS2345", result.root_cause)
                    joined = "\n".join(result.checks_run)
                    self.assertIn("Full-suite verification configured", joined)
                    self.assertNotIn("sys.exit(7)", joined)

    def test_required_missing_full_suite_config_still_classifies_missing_config(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    (target / ".agentic").mkdir(parents=True)

                    result = module.run_verification(target, {"role": "hardener", "changed_files": ["src/app.ts"]})

                    self.assertFalse(result.ok)
                    self.assertEqual("verification_environment_failure", result.reason)
                    self.assertEqual("missing_verification_config", result.category)
                    self.assertIn(".agentic/verification_commands.txt", result.root_cause)

    def test_smoke_commands_match_changed_files_for_patch_scope(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    (target / ".agentic").mkdir(parents=True)
                    (target / ".agentic" / "smoke_commands.txt").write_text(
                        "path:src/** | python3 -c 'print(\"scoped smoke\")'\n",
                        encoding="utf-8",
                    )

                    result = module.run_verification(target, {"role": "builder", "changed_files": ["src/app.ts"]})

                    self.assertTrue(result.ok, result.detail)
                    self.assertIn("scoped smoke", result.detail)

    def test_hardener_full_suite_classifies_missing_env_var_without_path_category(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    local_path = "/User" + "s/example/project/test.py"
                    (target / ".agentic").mkdir(parents=True)
                    (target / ".agentic" / "verification_commands.txt").write_text(
                        f"python3 -c 'import sys; print(\"Error: DATABASE_URL is not set at {local_path}\", file=sys.stderr); sys.exit(1)'\n",
                        encoding="utf-8",
                    )

                    result = module.run_verification(target, {"role": "hardener", "changed_files": ["src/app.ts"]})

                    self.assertFalse(result.ok)
                    self.assertEqual("verification_environment_failure", result.reason)
                    self.assertEqual("missing_env_var", result.category)
                    self.assertIn("DATABASE_URL", result.root_cause)

    def test_mark_deferred_sanitizes_detail_and_records_root_cause(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    local_path = "/User" + "s/example/project/test.py"
                    manifest_path = target / "target/automation_queue/builder/run-env/manifest.json"
                    manifest = {"role": "builder", "run_id": "run-env", "changed_files": ["src/app.ts"]}

                    module.mark_deferred(
                        manifest_path,
                        manifest,
                        target=target,
                        reason="verification_failure",
                        detail=f"Error: DATABASE_URL is not set at {local_path}",
                        head_before_integration="abc",
                        checkpoint_commit=None,
                        checks_run=["npm test"],
                        dry_run=False,
                    )

                    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
                    self.assertEqual("verification_environment_failure", saved["deferral_reason"])
                    self.assertEqual("missing_env_var", saved["deferral_category"])
                    self.assertIn("DATABASE_URL", saved["deferral_root_cause"])
                    self.assertNotIn("/User" + "s/example", saved["deferral_detail"])
                    self.assertNotIn("local_path_reference", json.dumps(saved))

    def test_baseline_verification_ledger_records_sanitized_failure(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    local_path = "/User" + "s/example/project/test.py"
                    (target / ".agentic").mkdir(parents=True)
                    (target / ".agentic" / "verification_commands.txt").write_text(
                        f"python3 -c 'import sys; print(\"DATABASE_URL missing at {local_path}\"); sys.exit(1)'\n",
                        encoding="utf-8",
                    )

                    record = module.run_baseline_verification(target, head_value="abc123", dry_run=False, force=True)

                    saved = json.loads((target / "target/baseline_verification.json").read_text(encoding="utf-8"))
                    self.assertEqual(record, saved)
                    self.assertEqual("blocked_environment", saved["status"])
                    self.assertEqual("missing_env_var", saved["category"])
                    self.assertIn("verification_environment_failure:missing_env_var", saved["failure_signature"])
                    self.assertNotIn("/User" + "s/example", json.dumps(saved))

    def test_local_postgres_connection_failure_is_repairable_baseline_service(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    (target / ".agentic").mkdir(parents=True)
                    (target / "packages/database/prisma").mkdir(parents=True)
                    (target / "packages/database/prisma/schema.prisma").write_text(
                        'datasource db {\n  provider = "postgresql"\n  url = env("DATABASE_URL")\n}\n',
                        encoding="utf-8",
                    )
                    (target / "apps/web").mkdir(parents=True)
                    (target / "apps/web/.env.test.example").write_text(
                        'DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:5432/app_test"\n',
                        encoding="utf-8",
                    )
                    (target / ".agentic" / "verification_commands.txt").write_text(
                        "python3 -c 'import sys; print(\"Prisma P1001: Can not reach database server at `127.0.0.1:5432`\"); sys.exit(1)'\n",
                        encoding="utf-8",
                    )

                    record = module.run_baseline_verification(target, head_value="abc123", dry_run=False, force=True)

                    self.assertEqual("repairable_local_service", record["status"])
                    self.assertEqual("missing_local_database", record["category"])
                    self.assertIn("local service harness", record["next_action"])

    def test_builder_patch_accepts_scoped_checks_despite_failing_baseline(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.init_repo(target, bridge_mode="disabled")
                    self.add_committed_file(target, "src/app.ts", "old\n")
                    (target / ".agentic" / "verification_commands.txt").write_text(
                        "python3 -c 'import sys; print(\"suite fails\"); sys.exit(5)'\n",
                        encoding="utf-8",
                    )
                    (target / ".agentic" / "smoke_commands.txt").write_text(
                        "builder | python3 -c 'print(\"builder smoke passed\")'\n",
                        encoding="utf-8",
                    )
                    patch = target / "target/automation_queue/builder/run-builder/changes.patch"
                    manifest_path = patch.parent / "manifest.json"
                    patch.parent.mkdir(parents=True, exist_ok=True)
                    self.write_patch_for_file(target, "src/app.ts", "new\n", patch)
                    manifest = {
                        "role": "builder",
                        "run_id": "run-builder",
                        "patch_path": str(patch),
                        "changed_files": ["src/app.ts"],
                        "summary": "Commit type: feat\nCommit scope: app\nCommit subject: update app text\n",
                    }
                    head_before = module.head(target)
                    baseline = {
                        "status": "blocked_environment",
                        "failure_signature": "verification_failure:other:old",
                        "root_cause": "suite fails before patch",
                        "checks_run": ["full suite"],
                    }

                    committed = module.integrate_individually(
                        target,
                        [(manifest_path, manifest)],
                        head_before=head_before,
                        checkpoint_commit=None,
                        baseline=baseline,
                        dry_run=False,
                    )

                    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
                    self.assertEqual(1, len(committed))
                    self.assertEqual("applied", saved["status"])
                    self.assertIn("builder smoke passed", "\n".join(saved["checks_run"]))
                    self.assertNotIn("suite fails", "\n".join(saved["checks_run"]))
                    self.assertEqual("new\n", (target / "src/app.ts").read_text(encoding="utf-8"))

    def test_normal_hardener_patch_defers_on_failing_baseline(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.init_repo(target, bridge_mode="disabled")
                    self.add_committed_file(target, "src/app.ts", "old\n")
                    patch = target / "target/automation_queue/hardener/run-hardener/changes.patch"
                    manifest_path = patch.parent / "manifest.json"
                    patch.parent.mkdir(parents=True, exist_ok=True)
                    self.write_patch_for_file(target, "src/app.ts", "new\n", patch)
                    manifest = {
                        "role": "hardener",
                        "run_id": "run-hardener",
                        "patch_path": str(patch),
                        "changed_files": ["src/app.ts"],
                        "summary": "Commit type: test\nCommit scope: app\nCommit subject: harden app tests\n",
                    }
                    baseline = {
                        "status": "failing_source",
                        "failure_signature": "verification_failure:test_assertion_failure:old",
                        "root_cause": "Expected true, received false",
                        "next_action": "Create a baseline repair patch.",
                        "checks_run": ["python3 -m pytest"],
                    }

                    committed = module.integrate_individually(
                        target,
                        [(manifest_path, manifest)],
                        head_before=module.head(target),
                        checkpoint_commit=None,
                        baseline=baseline,
                        dry_run=False,
                    )

                    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
                    self.assertEqual([], committed)
                    self.assertEqual("deferred", saved["status"])
                    self.assertEqual("baseline_verification_blocker", saved["deferral_reason"])
                    self.assertEqual("failing_source", saved["baseline_status"])
                    self.assertEqual("old\n", (target / "src/app.ts").read_text(encoding="utf-8"))

    def test_baseline_repair_hardener_patch_accepts_test_rationale_and_updates_ledger(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.init_repo(target, bridge_mode="disabled")
                    original_test = "\n".join(f"assert old_{index}" for index in range(12)) + "\n"
                    self.add_committed_file(target, "tests/test_legacy.py", original_test)
                    (target / ".agentic" / "verification_commands.txt").write_text(
                        "python3 -c 'import sys; print(\"Expected fresh baseline, received stale test\"); sys.exit(1)'\n",
                        encoding="utf-8",
                    )
                    (target / ".agentic" / "smoke_commands.txt").write_text(
                        "hardener | python3 -c 'print(\"focused hardener evidence\")'\n",
                        encoding="utf-8",
                    )
                    patch = target / "target/automation_queue/hardener/run-repair/changes.patch"
                    manifest_path = patch.parent / "manifest.json"
                    patch.parent.mkdir(parents=True, exist_ok=True)
                    self.write_patch_for_file(target, "tests/test_legacy.py", "assert fresh_baseline\n", patch)
                    manifest = {
                        "role": "hardener",
                        "run_id": "run-repair",
                        "patch_path": str(patch),
                        "changed_files": ["tests/test_legacy.py"],
                        "verification_scope": "baseline_repair",
                        "test_change_rationale": "Replaces obsolete legacy expectations with the current fixture contract.",
                        "summary": (
                            "Commit type: test\n"
                            "Commit scope: baseline\n"
                            "Commit subject: refresh stale baseline test\n"
                            "Verification scope: baseline_repair\n"
                            "Test change rationale: Replaces obsolete legacy expectations with the current fixture contract.\n"
                        ),
                    }
                    baseline = {
                        "status": "failing_source",
                        "failure_signature": "verification_failure:test_assertion_failure:oldoldold",
                        "root_cause": "Old source failure",
                        "checks_run": ["python3 -m pytest"],
                    }

                    committed = module.integrate_individually(
                        target,
                        [(manifest_path, manifest)],
                        head_before=module.head(target),
                        checkpoint_commit=None,
                        baseline=baseline,
                        dry_run=False,
                    )

                    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
                    ledger = json.loads((target / "target/baseline_verification.json").read_text(encoding="utf-8"))
                    self.assertEqual(1, len(committed))
                    self.assertEqual("applied", saved["status"])
                    self.assertEqual("accepted_changed_failure_signature", saved["baseline_repair_result"])
                    self.assertEqual("failing_source", saved["baseline_status"])
                    self.assertEqual(ledger["failure_signature"], saved["baseline_failure_signature"])
                    self.assertIn("fresh_baseline", (target / "tests/test_legacy.py").read_text(encoding="utf-8"))

    def test_duplicate_deferred_patches_are_triaged_as_superseded_and_replaceable(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    older = target / "target/automation_queue/builder/run-old/manifest.json"
                    newer = target / "target/automation_queue/builder/run-new/manifest.json"
                    for manifest_path, run_id in [(older, "run-old"), (newer, "run-new")]:
                        manifest_path.parent.mkdir(parents=True, exist_ok=True)
                        manifest_path.write_text(
                            json.dumps(
                                {
                                    "role": "builder",
                                    "run_id": run_id,
                                    "status": "deferred",
                                    "deferral_reason": "conflict",
                                    "deferral_category": "apply_conflict",
                                    "deferral_detail": "patch failed",
                                    "changed_files": ["src/query.ts"],
                                    "created_at": f"2026-05-0{1 if run_id == 'run-old' else 2}T00:00:00+00:00",
                                }
                            )
                            + "\n",
                            encoding="utf-8",
                        )

                    summary = module.triage_deferred_equivalents(target, dry_run=False)

                    self.assertTrue(summary)
                    older_saved = json.loads(older.read_text(encoding="utf-8"))
                    newer_saved = json.loads(newer.read_text(encoding="utf-8"))
                    self.assertEqual("superseded", older_saved["status"])
                    self.assertEqual("superseded", older_saved["deferral_triage_status"])
                    self.assertEqual("deferred", newer_saved["status"])
                    self.assertEqual("replace-from-current-HEAD", newer_saved["deferral_triage_status"])


class GitIndexLockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.modules = [(path, load_integrator(path)) for path in INTEGRATOR_PATHS]

    def init_repo(self, target: Path) -> None:
        (target / ".agentic").mkdir(parents=True, exist_ok=True)
        (target / ".agentic" / "project_intake.json").write_text(
            json.dumps({"human_bridge_mode": "disabled"}, indent=2) + "\n",
            encoding="utf-8",
        )
        (target / "docs").mkdir(parents=True, exist_ok=True)
        (target / "docs" / "CODEX_AUTOMATION_TASKS.md").write_text("tasks v1\n", encoding="utf-8")
        (target / "docs" / "MULTI_ROLE_PROGRESS.md").write_text("progress v1\n", encoding="utf-8")
        (target / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "init"], cwd=target, check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "add", "."], cwd=target, check=True, stdout=subprocess.DEVNULL)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-m",
                "chore: base",
            ],
            cwd=target,
            check=True,
            stdout=subprocess.DEVNULL,
        )

    def make_lock(self, target: Path, *, age_seconds: int = 0) -> Path:
        lock = target / ".git" / "index.lock"
        lock.write_text("", encoding="utf-8")
        if age_seconds:
            stamp = time.time() - age_seconds
            os.utime(lock, (stamp, stamp))
        return lock

    def add_committed_file(self, target: Path, relative: str, content: str) -> None:
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        subprocess.run(["git", "add", relative], cwd=target, check=True, stdout=subprocess.DEVNULL)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-m",
                f"test: add {Path(relative).name}",
            ],
            cwd=target,
            check=True,
            stdout=subprocess.DEVNULL,
        )

    def write_patch_for_file(self, target: Path, relative: str, new_content: str, patch_path: Path) -> None:
        (target / relative).write_text(new_content, encoding="utf-8")
        result = subprocess.run(
            ["git", "diff", "--binary", "HEAD", "--", relative],
            cwd=target,
            check=True,
            text=True,
            capture_output=True,
        )
        patch_path.write_text(result.stdout, encoding="utf-8")
        subprocess.run(["git", "checkout", "--", relative], cwd=target, check=True, stdout=subprocess.DEVNULL)

    def test_no_lock_allows_mutating_git_command(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.init_repo(target)
                    (target / "README.md").write_text("changed\n", encoding="utf-8")

                    result = module.git(target, "add", "-A", check=True, lock_wait_seconds=0)

                    self.assertEqual(0, result.returncode)
                    staged = subprocess.run(
                        ["git", "diff", "--cached", "--name-only"],
                        cwd=target,
                        text=True,
                        capture_output=True,
                        check=True,
                    ).stdout
                    self.assertIn("README.md", staged)

    def test_fresh_lock_fails_without_deleting_lock(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.init_repo(target)
                    lock = self.make_lock(target)
                    (target / "README.md").write_text("changed\n", encoding="utf-8")

                    with self.assertRaises(module.GitIndexLockBlocked) as raised:
                        module.git(target, "add", "-A", check=True, lock_wait_seconds=0)

                    self.assertTrue(lock.exists())
                    message = str(raised.exception)
                    self.assertIn(str(lock), message)
                    self.assertIn("age_seconds=", message)
                    self.assertIn("Manual action:", message)
                    self.assertIn("recent", message)

    def test_stale_unowned_lock_is_removed_and_command_proceeds(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.init_repo(target)
                    lock = self.make_lock(target, age_seconds=300)
                    (target / "README.md").write_text("changed\n", encoding="utf-8")

                    result = module.git(target, "add", "-A", check=True, lock_wait_seconds=0)

                    self.assertEqual(0, result.returncode)
                    self.assertFalse(lock.exists())
                    staged = subprocess.run(
                        ["git", "diff", "--cached", "--name-only"],
                        cwd=target,
                        text=True,
                        capture_output=True,
                        check=True,
                    ).stdout
                    self.assertIn("README.md", staged)

    def test_stale_open_lock_is_not_removed(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.init_repo(target)
                    lock = self.make_lock(target, age_seconds=300)
                    (target / "README.md").write_text("changed\n", encoding="utf-8")
                    original = module.lock_open_process_details
                    try:
                        module.lock_open_process_details = lambda _lock: (
                            ["pid=12345 command=python holding index.lock"],
                            ["test probe"],
                            "",
                        )
                        with self.assertRaises(module.GitIndexLockBlocked) as raised:
                            module.git(target, "add", "-A", check=True, lock_wait_seconds=0)
                    finally:
                        module.lock_open_process_details = original

                    self.assertTrue(lock.exists())
                    self.assertIn("open_processes=", str(raised.exception))

    def test_integrator_reports_actionable_message_when_lock_remains(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.init_repo(target)
                    lock = self.make_lock(target)
                    (target / "README.md").write_text("dirty main\n", encoding="utf-8")
                    old_wait = os.environ.get("DIFFMOGGER_GIT_INDEX_LOCK_WAIT_SECONDS")
                    old_retry = os.environ.get("DIFFMOGGER_GIT_INDEX_LOCK_RETRY_SECONDS")
                    os.environ["DIFFMOGGER_GIT_INDEX_LOCK_WAIT_SECONDS"] = "0"
                    os.environ["DIFFMOGGER_GIT_INDEX_LOCK_RETRY_SECONDS"] = "0"
                    stderr = io.StringIO()
                    try:
                        with contextlib.redirect_stderr(stderr):
                            exit_code = module.integrate(target, "run-lock", dry_run=False)
                    finally:
                        if old_wait is None:
                            os.environ.pop("DIFFMOGGER_GIT_INDEX_LOCK_WAIT_SECONDS", None)
                        else:
                            os.environ["DIFFMOGGER_GIT_INDEX_LOCK_WAIT_SECONDS"] = old_wait
                        if old_retry is None:
                            os.environ.pop("DIFFMOGGER_GIT_INDEX_LOCK_RETRY_SECONDS", None)
                        else:
                            os.environ["DIFFMOGGER_GIT_INDEX_LOCK_RETRY_SECONDS"] = old_retry

                    self.assertEqual(1, exit_code)
                    self.assertTrue(lock.exists())
                    output = stderr.getvalue()
                    self.assertIn("INTEGRATOR_GIT_INDEX_LOCK_BLOCKED", output)
                    self.assertIn(str(lock), output)
                    self.assertIn("Manual action:", output)
                    manifest_path = target / "target" / "automation_queue" / "integrator" / "run-lock" / "manifest.json"
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    self.assertEqual("failed", manifest["status"])
                    self.assertIn(str(lock), manifest["deferral_detail"])
                    self.assertIn("Manual action:", manifest["deferral_detail"])

    def test_integrator_recovers_stale_lock_while_applying_patch(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.init_repo(target)
                    self.add_committed_file(target, "src/app.txt", "old\n")
                    base_commit = module.head(target)
                    patch = target / "target" / "automation_queue" / "builder" / "run-stale" / "changes.patch"
                    manifest_path = patch.parent / "manifest.json"
                    patch.parent.mkdir(parents=True, exist_ok=True)
                    self.write_patch_for_file(target, "src/app.txt", "new\n", patch)
                    manifest_path.write_text(
                        json.dumps(
                            {
                                "role": "builder",
                                "run_id": "run-stale",
                                "base_commit": base_commit,
                                "head_before_integration": None,
                                "status": "queued",
                                "patch_path": str(patch),
                                "changed_files": ["src/app.txt"],
                                "checks_run": [],
                                "summary": (
                                    "Commit type: fix\n"
                                    "Commit scope: app\n"
                                    "Commit subject: update app fixture\n"
                                ),
                                "created_at": "2026-05-04T00:00:00+00:00",
                                "integrated_at": None,
                            }
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    lock = self.make_lock(target, age_seconds=300)

                    exit_code = module.integrate(target, "integrator-stale", dry_run=False)

                    self.assertEqual(0, exit_code)
                    self.assertFalse(lock.exists())
                    self.assertEqual("new\n", (target / "src/app.txt").read_text(encoding="utf-8"))
                    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
                    self.assertEqual("applied", saved["status"])
                    self.assertTrue(saved["accepted_commit"])


if __name__ == "__main__":
    unittest.main()
