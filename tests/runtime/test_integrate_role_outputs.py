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
from diffmogger.integrator.queue import load_queued_manifests
from diffmogger.runtime.paths import target_path
from diffmogger.runtime.state_store import (
    connect,
    database_path_for_target,
    load_ticket_run_state,
    record_candidate_lane_conn,
    select_candidate_lane_conn,
    stable_json,
    state_snapshot,
    write_ticket_run_state,
)

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


def ticket_digest(ticket: dict[str, object]) -> str:
    return sha256_text(stable_json(dict(ticket)))


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

    def test_progress_projection_keeps_required_fast_follow_marker(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    (target / "docs").mkdir(parents=True)
                    (target / "docs" / "CODEX_AUTOMATION_TASKS.md").write_text(
                        "AUTOMATION_STATUS: ACTIVE\n",
                        encoding="utf-8",
                    )

                    module.update_progress(
                        target,
                        run_id="integrator-smoke",
                        verification_status="pass",
                        committed=[],
                        deferred_count=0,
                        checkpoint_commit=None,
                        cleanup_summary=[],
                        dry_run=False,
                    )

                    progress = (target / "docs" / "MULTI_ROLE_PROGRESS.md").read_text(encoding="utf-8")
                    self.assertIn("fast-follow replanning", progress)

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

    def test_load_queued_manifests_filters_selected_patch_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            queue_root = target / "target" / "automation_queue" / "builder"
            for run_id, patch_id in [("run-safe", "patch:safe"), ("run-deferred", "patch:deferred")]:
                run_dir = queue_root / run_id
                run_dir.mkdir(parents=True, exist_ok=True)
                (run_dir / "changes.patch").write_text("", encoding="utf-8")
                (run_dir / "manifest.json").write_text(
                    json.dumps(
                        {
                            "role": "builder",
                            "run_id": run_id,
                            "status": "queued",
                            "patch_id": patch_id,
                            "patch_path": str(run_dir / "changes.patch"),
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )

            selected = load_queued_manifests(target, patch_ids=["patch:safe"])
            self.assertEqual(["patch:safe"], [manifest["patch_id"] for _path, manifest in selected])

            previous = os.environ.get("DIFFMOGGER_SELECTED_PATCH_IDS")
            os.environ["DIFFMOGGER_SELECTED_PATCH_IDS"] = "patch:deferred"
            try:
                selected_from_env = load_queued_manifests(target)
            finally:
                if previous is None:
                    os.environ.pop("DIFFMOGGER_SELECTED_PATCH_IDS", None)
                else:
                    os.environ["DIFFMOGGER_SELECTED_PATCH_IDS"] = previous
            self.assertEqual(["patch:deferred"], [manifest["patch_id"] for _path, manifest in selected_from_env])

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

    def git_head(self, target: Path) -> str:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=target,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()

    def commit_all(self, target: Path, message: str) -> str:
        subprocess.run(
            ["git", "add", "-A", "--", ".", ":!target/automation_queue", ":!target/orchestration.sqlite3*"],
            cwd=target,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-m",
                message,
            ],
            cwd=target,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        return self.git_head(target)

    def write_queued_patch_manifest(
        self,
        target: Path,
        *,
        role: str,
        run_id: str,
        patch_path: Path,
        base_commit: str,
        changed_files: list[str],
        extra: dict[str, object] | None = None,
    ) -> Path:
        manifest_path = patch_path.parent / "manifest.json"
        manifest = {
            "role": role,
            "run_id": run_id,
            "base_commit": base_commit,
            "head_before_integration": None,
            "status": "queued",
            "patch_path": str(patch_path),
            "changed_files": changed_files,
            "checks_run": [],
            "summary": (
                "Commit type: fix\n"
                "Commit scope: integration\n"
                f"Commit subject: integrate {run_id}\n"
            ),
            "created_at": "2026-05-14T00:00:00+00:00",
            "integrated_at": None,
        }
        if extra:
            manifest.update(extra)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return manifest_path

    def write_queued_file_patch(
        self,
        target: Path,
        *,
        role: str = "builder",
        run_id: str,
        relative: str,
        new_content: str,
        base_commit: str,
        extra: dict[str, object] | None = None,
    ) -> Path:
        patch = target / "target" / "automation_queue" / role / run_id / "changes.patch"
        patch.parent.mkdir(parents=True, exist_ok=True)
        self.write_patch_for_file(target, relative, new_content, patch)
        return self.write_queued_patch_manifest(
            target,
            role=role,
            run_id=run_id,
            patch_path=patch,
            base_commit=base_commit,
            changed_files=[relative],
            extra=extra,
        )

    def write_speculative_candidate(
        self,
        target: Path,
        *,
        run_id: str,
        candidate_id: str,
        worker_id: str,
        new_content: str,
    ) -> str:
        queue_dir = target_path(target, f"target/automation_queue/builder/{run_id}")
        patch_path = queue_dir / "changes.patch"
        manifest_path = queue_dir / "manifest.json"
        summary_path = queue_dir / "summary.md"
        queue_dir.mkdir(parents=True, exist_ok=True)
        self.write_patch_for_file(target, "src/app.py", new_content, patch_path)
        summary_path.write_text(f"# Candidate {candidate_id}\n", encoding="utf-8")
        base_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=target, text=True, capture_output=True, check=True).stdout.strip()
        patch_id = f"worker-patch:{candidate_id}"
        manifest = {
            "schema_version": 1,
            "role": "builder",
            "run_id": run_id,
            "status": "candidate",
            "source": "speculative_candidate_lane",
            "candidate_id": candidate_id,
            "worker_id": worker_id,
            "base_commit": base_commit,
            "patch_path": f"target/automation_queue/builder/{run_id}/changes.patch",
            "summary_path": f"target/automation_queue/builder/{run_id}/summary.md",
            "changed_files": ["src/app.py"],
            "checks_run": [],
            "validation_evidence": [{"status": "passed", "command": "path:src/** smoke"}],
            "created_at": "2026-05-14T00:00:00+00:00",
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with connect(database_path_for_target(target)) as conn:
            conn.execute(
                """
                INSERT INTO worker_agents(
                    worker_id, execution_group_id, run_id, mode, role, status,
                    started_at, finished_at, payload_json
                )
                VALUES(?, 'execution-group:speculative-integrator', ?, 'write', 'builder',
                       'completed', '2026-05-14T00:00:00+00:00',
                       '2026-05-14T00:00:01+00:00', '{}')
                """,
                (worker_id, run_id),
            )
            conn.execute(
                """
                INSERT INTO worker_patches(
                    patch_id, worker_id, execution_group_id, status, manifest_path,
                    patch_path, changed_files_json, base_commit, leases_json,
                    validation_evidence_json, conflict_signature, created_at,
                    queued_at, integrated_at, payload_json
                )
                VALUES(?, ?, 'execution-group:speculative-integrator', 'candidate',
                       ?, ?, ?, ?, '[]', ?, '', '2026-05-14T00:00:00+00:00',
                       '', '', ?)
                """,
                (
                    patch_id,
                    worker_id,
                    f"target/automation_queue/builder/{run_id}/manifest.json",
                    f"target/automation_queue/builder/{run_id}/changes.patch",
                    json.dumps(["src/app.py"]),
                    base_commit,
                    json.dumps([{"status": "passed", "command": "path:src/** smoke"}]),
                    json.dumps({"schema_version": 1, "speculative_candidate": True}),
                ),
            )
            record_candidate_lane_conn(
                conn,
                target,
                candidate_id=candidate_id,
                task_id="TICKET-ALT",
                execution_group_id="execution-group:speculative-integrator",
                worker_id=worker_id,
                approach_summary=f"Candidate implementation {candidate_id}",
                status="validated",
                patch_id=patch_id,
                validation_summary={"status": "passed", "test_coverage": "path-scoped smoke"},
            )
        return patch_id

    def replace_action(self, rel_path: str, start: str | None, end: str) -> dict[str, object]:
        return {
            "action": "replace_file",
            "path": rel_path,
            "start_hash": sha256_text(start) if start is not None else None,
            "end_hash": sha256_text(end),
            "content": end,
        }

    def test_runtime_state_applies_ticket_update_action(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    current = {
                        "id": "TICKET-001",
                        "summary": "Build the first slice",
                        "status": "pending",
                    }
                    desired = {
                        **current,
                        "status": "done",
                        "evidence": ["pytest passed"],
                        "related_commits": ["abc1234"],
                    }
                    write_ticket_run_state(
                        target,
                        {"run_id": "ticket-run", "tickets": [current]},
                        actor_role="test",
                        event_type="ticket.run_seeded",
                    )
                    manifest = self.write_actions(
                        target,
                        [
                            {
                                "action": "update_ticket",
                                "ticket_id": "TICKET-001",
                                "start_hash": ticket_digest(current),
                                "end_hash": ticket_digest(desired),
                                "ticket": desired,
                            }
                        ],
                    )

                    results = module.apply_runtime_state_actions(target, manifest, dry_run=False)
                    loaded = load_ticket_run_state(target)

                    self.assertEqual(manifest["runtime_state_status"], "applied")
                    self.assertEqual(results[0]["status"], "applied")
                    self.assertEqual("done", loaded["tickets"][0]["status"])
                    self.assertEqual(["pytest passed"], loaded["tickets"][0]["evidence"])

    def test_runtime_state_ticket_hash_conflict_defers_without_mutation(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    current = {
                        "id": "TICKET-001",
                        "summary": "Build the first slice",
                        "status": "pending",
                    }
                    desired = {**current, "status": "done", "evidence": ["pytest passed"]}
                    write_ticket_run_state(
                        target,
                        {"run_id": "ticket-run", "tickets": [current]},
                        actor_role="test",
                        event_type="ticket.run_seeded",
                    )
                    manifest = self.write_actions(
                        target,
                        [
                            {
                                "action": "update_ticket",
                                "ticket_id": "TICKET-001",
                                "start_hash": "not-the-current-ticket-hash",
                                "end_hash": ticket_digest(desired),
                                "ticket": desired,
                            }
                        ],
                    )

                    results = module.apply_runtime_state_actions(target, manifest, dry_run=False)
                    loaded = load_ticket_run_state(target)

                    self.assertEqual(manifest["runtime_state_status"], "deferred")
                    self.assertEqual(results[0]["status"], "conflict")
                    self.assertEqual("pending", loaded["tickets"][0]["status"])

    def test_runtime_state_applies_ticket_delete_action(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    first = {
                        "id": "TICKET-001",
                        "summary": "Remove stale ticket",
                        "status": "pending",
                    }
                    second = {
                        "id": "TICKET-002",
                        "summary": "Keep active ticket",
                        "status": "pending",
                    }
                    write_ticket_run_state(
                        target,
                        {"run_id": "ticket-run", "tickets": [first, second]},
                        actor_role="test",
                        event_type="ticket.run_seeded",
                    )
                    manifest = self.write_actions(
                        target,
                        [
                            {
                                "action": "delete_ticket",
                                "ticket_id": "TICKET-001",
                                "start_hash": ticket_digest(first),
                            }
                        ],
                    )

                    results = module.apply_runtime_state_actions(target, manifest, dry_run=False)
                    loaded = load_ticket_run_state(target)

                    self.assertEqual(manifest["runtime_state_status"], "applied")
                    self.assertEqual(results[0]["status"], "applied")
                    self.assertEqual(["TICKET-002"], [item["id"] for item in loaded["tickets"]])

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

    def test_selected_speculative_candidate_goes_through_integrator_verification(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.init_repo(target, bridge_mode="local_notifier")
                    self.add_committed_file(target, "src/app.py", "VALUE = 'base'\n")
                    (target / ".agentic" / "smoke_commands.txt").write_text(
                        "path:src/** | python3 -c 'print(\"candidate smoke\")'\n",
                        encoding="utf-8",
                    )
                    subprocess.run(["git", "add", ".agentic/smoke_commands.txt"], cwd=target, check=True, stdout=subprocess.DEVNULL)
                    subprocess.run(
                        [
                            "git",
                            "-c",
                            "user.name=Test",
                            "-c",
                            "user.email=test@example.invalid",
                            "commit",
                            "-m",
                            "test: add scoped smoke",
                        ],
                        cwd=target,
                        check=True,
                        stdout=subprocess.DEVNULL,
                    )
                    selected_id = "candidate-lane:selected"
                    rejected_id = "candidate-lane:rejected"
                    self.write_speculative_candidate(
                        target,
                        run_id="candidate-selected",
                        candidate_id=selected_id,
                        worker_id="worker:selected",
                        new_content="VALUE = 'selected'\n",
                    )
                    self.write_speculative_candidate(
                        target,
                        run_id="candidate-rejected",
                        candidate_id=rejected_id,
                        worker_id="worker:rejected",
                        new_content="VALUE = 'rejected'\n",
                    )
                    with connect(database_path_for_target(target)) as conn:
                        selection = select_candidate_lane_conn(
                            conn,
                            target,
                            selected_id,
                            selected_by="planner",
                            comparison_notes="Selected candidate keeps the smaller behavior change.",
                        )

                    exit_code = module.integrate(target, "integrator-candidate", dry_run=False)

                    self.assertEqual("selected", selection["status"])
                    self.assertEqual(0, exit_code)
                    self.assertEqual("VALUE = 'selected'\n", (target / "src/app.py").read_text(encoding="utf-8"))
                    selected_manifest = json.loads((target / "target/automation_queue/builder/candidate-selected/manifest.json").read_text(encoding="utf-8"))
                    rejected_manifest = json.loads((target / "target/automation_queue/builder/candidate-rejected/manifest.json").read_text(encoding="utf-8"))
                    self.assertEqual("applied", selected_manifest["status"])
                    self.assertEqual("superseded", rejected_manifest["status"])
                    self.assertIn("candidate smoke", "\n".join(selected_manifest["checks_run"]))
                    self.assertEqual(selected_id, rejected_manifest["superseded_by_candidate_id"])

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

    def test_npm_ebadengine_warning_does_not_classify_as_missing_env_var(self) -> None:
        output = """
$ npm ci
exit=1
npm warn EBADENGINE Unsupported engine {
npm warn EBADENGINE   package: 'eslint-visitor-keys@5.0.1',
npm warn EBADENGINE   required: { node: '^20.19.0 || ^22.13.0 || >=24' },
npm warn EBADENGINE   current: { node: 'v23.9.0', npm: '10.9.2' }
npm warn EBADENGINE }
AssertionError: expected 1 received 2
""".strip()
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                category, root_cause = module.classify_failure_text("npm ci", output)

                self.assertEqual("test_assertion_failure", category)
                self.assertIn("expected 1 received 2", root_cause)

    def test_successful_ebadengine_warning_does_not_mask_later_failure(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    (target / ".agentic").mkdir(parents=True)
                    (target / "warn_engine.py").write_text(
                        "\n".join(
                            [
                                "import sys",
                                "print('npm warn EBADENGINE Unsupported engine {', file=sys.stderr)",
                                "print('npm warn EBADENGINE   required: { node: \\'^20.19.0 || ^22.13.0 || >=24\\' }', file=sys.stderr)",
                            ]
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    (target / "fail_check.py").write_text(
                        "\n".join(
                            [
                                "import sys",
                                "print('AssertionError: expected 1 received 2', file=sys.stderr)",
                                "sys.exit(1)",
                            ]
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    (target / ".agentic" / "verification_commands.txt").write_text(
                        "python3 warn_engine.py\npython3 fail_check.py\n",
                        encoding="utf-8",
                    )

                    result = module.run_verification(target, {"role": "hardener", "changed_files": ["src/app.ts"]})

                    self.assertFalse(result.ok)
                    self.assertEqual("verification_failure", result.reason)
                    self.assertEqual("test_assertion_failure", result.category)
                    self.assertIn("expected 1 received 2", result.root_cause)
                    self.assertIn("npm warn EBADENGINE", result.detail)

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

    def test_database_url_blocker_requires_forced_recheck_after_env_fix(self) -> None:
        old_database_url = os.environ.pop("DATABASE_URL", None)
        try:
            for path, module in self.modules:
                with self.subTest(path=path.relative_to(ROOT)):
                    os.environ.pop("DATABASE_URL", None)
                    with tempfile.TemporaryDirectory() as tmp:
                        target = Path(tmp)
                        self.init_repo(target, bridge_mode="disabled")
                        (target / ".agentic" / "verification_commands.txt").write_text(
                            "python3 -c 'import os, sys; "
                            'ok = bool(os.environ.get("DATABASE_URL")); '
                            'print("DATABASE_URL missing", file=sys.stderr) if not ok else print("ok"); '
                            "sys.exit(0 if ok else 1)'\n",
                            encoding="utf-8",
                        )
                        head_value = module.head(target)

                        blocked = module.run_baseline_verification(
                            target,
                            head_value=head_value,
                            dry_run=False,
                            force=True,
                        )
                        review = blocked["blocker_review"]
                        self.assertEqual("blocked_environment", blocked["status"])
                        self.assertEqual("missing_env_var", blocked["category"])
                        self.assertEqual("confirmed_blocker", review["verdict"])
                        self.assertTrue(review["is_blocker"])
                        self.assertTrue(
                            any(item.get("kind") == "baseline_verification" for item in state_snapshot(target)["open_blockers"])
                        )

                        (target / ".env").write_text("DATABASE_URL=postgresql://placeholder.invalid/app\n", encoding="utf-8")
                        stale = module.run_baseline_verification(
                            target,
                            head_value=head_value,
                            dry_run=False,
                            force=False,
                        )
                        self.assertEqual("blocked_environment", stale["status"])
                        self.assertEqual(blocked["failure_signature"], stale["failure_signature"])

                        exit_code = module.integrate(
                            target,
                            "database-url-recheck",
                            dry_run=False,
                            force_baseline=True,
                            baseline_only=True,
                        )

                        self.assertEqual(0, exit_code)
                        refreshed = json.loads((target / "target/baseline_verification.json").read_text(encoding="utf-8"))
                        self.assertEqual("passing", refreshed["status"])
                        self.assertFalse(
                            any(item.get("kind") == "baseline_verification" for item in state_snapshot(target)["open_blockers"])
                        )
                        tracked = subprocess.run(
                            ["git", "ls-files"],
                            cwd=target,
                            text=True,
                            capture_output=True,
                            check=True,
                        ).stdout.splitlines()
                        self.assertNotIn(".env", tracked)
        finally:
            if old_database_url is not None:
                os.environ["DATABASE_URL"] = old_database_url
            else:
                os.environ.pop("DATABASE_URL", None)

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

    def test_already_present_patch_after_checkpoint_resolves_without_deferral(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.init_repo(target, bridge_mode="disabled")
                    self.add_committed_file(target, "src/app.txt", "old\n")
                    base_commit = self.git_head(target)
                    manifest_path = self.write_queued_file_patch(
                        target,
                        run_id="run-present-after-checkpoint",
                        relative="src/app.txt",
                        new_content="new\n",
                        base_commit=base_commit,
                    )
                    (target / "src/app.txt").write_text("new\n", encoding="utf-8")

                    exit_code = module.integrate(target, "integrator-already-present", dry_run=False)

                    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
                    self.assertEqual(0, exit_code)
                    self.assertEqual("applied", saved["status"])
                    self.assertEqual("already_applied", saved["integration_resolution"])
                    self.assertEqual("head_already_contained_patch", saved["accepted_commit_source"])
                    self.assertEqual(saved["head_before_integration"], saved["accepted_commit"])
                    self.assertNotEqual("deferred", saved["status"])
                    self.assertEqual("new\n", (target / "src/app.txt").read_text(encoding="utf-8"))

    def test_base_advanced_with_unrelated_files_integrates_directly(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.init_repo(target, bridge_mode="disabled")
                    self.add_committed_file(target, "src/app.txt", "old\n")
                    base_commit = self.git_head(target)
                    manifest_path = self.write_queued_file_patch(
                        target,
                        run_id="run-unrelated-drift",
                        relative="src/app.txt",
                        new_content="new\n",
                        base_commit=base_commit,
                    )
                    self.add_committed_file(target, "docs/notes.md", "unrelated\n")

                    exit_code = module.integrate(target, "integrator-unrelated-drift", dry_run=False)

                    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
                    self.assertEqual(0, exit_code)
                    self.assertEqual("applied", saved["status"])
                    self.assertEqual("direct_apply", saved["integration_resolution"])
                    self.assertTrue(saved["accepted_commit"])
                    self.assertEqual("new\n", (target / "src/app.txt").read_text(encoding="utf-8"))
                    self.assertEqual("unrelated\n", (target / "docs/notes.md").read_text(encoding="utf-8"))

    def test_equivalent_same_file_drift_marks_hardener_patch_applied(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.init_repo(target, bridge_mode="disabled")
                    self.add_committed_file(target, "src/app.txt", "old\n")
                    (target / ".agentic" / "verification_commands.txt").write_text(
                        "python3 -c 'print(\"hardener baseline ok\")'\n",
                        encoding="utf-8",
                    )
                    base_commit = self.git_head(target)
                    manifest_path = self.write_queued_file_patch(
                        target,
                        role="hardener",
                        run_id="run-equivalent-hardener",
                        relative="src/app.txt",
                        new_content="new\n",
                        base_commit=base_commit,
                        extra={
                            "summary": (
                                "Commit type: test\n"
                                "Commit scope: app\n"
                                "Commit subject: harden app fixture\n"
                            )
                        },
                    )
                    (target / "src/app.txt").write_text("new\n", encoding="utf-8")
                    self.commit_all(target, "test: independently apply hardener diff")

                    exit_code = module.integrate(target, "integrator-equivalent-hardener", dry_run=False)

                    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
                    self.assertEqual(0, exit_code)
                    self.assertEqual("applied", saved["status"])
                    self.assertEqual("already_applied", saved["integration_resolution"])
                    self.assertEqual("head_already_contained_patch", saved["accepted_commit_source"])
                    self.assertIsNone(saved["deferral_reason"])

    def test_clean_rebaseable_patch_applies_and_validates(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.init_repo(target, bridge_mode="disabled")
                    self.add_committed_file(target, "src/app.txt", "line 1\nline 2\nline 3\nline 4\nline 5\nvalue = old\nline 7\n")
                    base_commit = self.git_head(target)
                    manifest_path = self.write_queued_file_patch(
                        target,
                        run_id="run-rebaseable",
                        relative="src/app.txt",
                        new_content="line 1\nline 2\nline 3\nline 4\nline 5\nvalue = new\nline 7\n",
                        base_commit=base_commit,
                        extra={"verification_commands": ["python3 -c 'print(\"rebase validation ok\")'"]},
                    )
                    (target / "src/app.txt").write_text(
                        "line 1\nline 2 changed by HEAD\nline 3\nline 4\nline 5\nvalue = old\nline 7\n",
                        encoding="utf-8",
                    )
                    self.commit_all(target, "refactor: update nearby context")

                    exit_code = module.integrate(target, "integrator-rebaseable", dry_run=False)

                    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
                    self.assertEqual(0, exit_code)
                    self.assertEqual("applied", saved["status"])
                    self.assertEqual("rebaseable", saved["integration_resolution"])
                    self.assertIn("rebase validation ok", "\n".join(saved["checks_run"]))
                    self.assertEqual(
                        "line 1\nline 2 changed by HEAD\nline 3\nline 4\nline 5\nvalue = new\nline 7\n",
                        (target / "src/app.txt").read_text(encoding="utf-8"),
                    )

    def test_true_conflict_still_defers_with_concrete_detail(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.init_repo(target, bridge_mode="disabled")
                    self.add_committed_file(target, "src/app.txt", "header\nvalue = old\nfooter\n")
                    base_commit = self.git_head(target)
                    manifest_path = self.write_queued_file_patch(
                        target,
                        run_id="run-true-conflict",
                        relative="src/app.txt",
                        new_content="header\nvalue = worker\nfooter\n",
                        base_commit=base_commit,
                    )
                    (target / "src/app.txt").write_text("header\nvalue = head\nfooter\n", encoding="utf-8")
                    self.commit_all(target, "fix: change same line")

                    exit_code = module.integrate(target, "integrator-true-conflict", dry_run=False)

                    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
                    self.assertEqual(0, exit_code)
                    self.assertEqual("deferred", saved["status"])
                    self.assertEqual("conflict", saved["deferral_reason"])
                    self.assertEqual("true_conflict", saved["integration_resolution"])
                    self.assertIn("conflict", saved["integration_resolution_detail"].lower())
                    self.assertIn("src/app.txt", saved["deferral_detail"])

    def test_already_applied_patch_still_reconciles_runtime_and_ticket_actions(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.init_repo(target, bridge_mode="disabled")
                    self.add_committed_file(target, "src/app.txt", "old\n")
                    (target / ".agentic" / "automation_prompt.md").write_text("prompt v1\n", encoding="utf-8")
                    self.commit_all(target, "chore: add automation prompt")
                    write_ticket_run_state(
                        target,
                        {
                            "schema_version": 1,
                            "tickets": [
                                {
                                    "id": "TICKET-1",
                                    "title": "Generic work",
                                    "summary": "Generic reusable work.",
                                    "status": "todo",
                                    "description": "Reusable test ticket.",
                                }
                            ],
                        },
                        actor_role="test",
                        event_type="ticket.run_seeded",
                        source_path="test",
                    )
                    base_commit = self.git_head(target)
                    patch = target / "target" / "automation_queue" / "builder" / "run-actions" / "changes.patch"
                    patch.parent.mkdir(parents=True, exist_ok=True)
                    self.write_patch_for_file(target, "src/app.txt", "new\n", patch)
                    (target / "src/app.txt").write_text("new\n", encoding="utf-8")
                    self.commit_all(target, "fix: independently apply code diff")
                    runtime_actions = patch.parent / "runtime_state_actions.json"
                    ticket_actions = patch.parent / "ticket_state_actions.json"
                    runtime_actions.write_text(
                        json.dumps(
                            {
                                "schema_version": 1,
                                "actions": [
                                    {
                                        "action": "replace_file",
                                        "path": ".agentic/automation_prompt.md",
                                        "start_hash": sha256_text("prompt v1\n"),
                                        "end_hash": sha256_text("prompt v2\n"),
                                        "content": "prompt v2\n",
                                    }
                                ],
                            },
                            indent=2,
                            sort_keys=True,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    current_ticket = load_ticket_run_state(target)["tickets"][0]
                    next_ticket = {**current_ticket, "status": "done"}
                    ticket_actions.write_text(
                        json.dumps(
                            {
                                "schema_version": 1,
                                "actions": [
                                    {
                                        "action": "update_ticket",
                                        "ticket_id": "TICKET-1",
                                        "start_hash": ticket_digest(current_ticket),
                                        "end_hash": ticket_digest(next_ticket),
                                        "ticket": next_ticket,
                                    }
                                ],
                            },
                            indent=2,
                            sort_keys=True,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    manifest_path = self.write_queued_patch_manifest(
                        target,
                        role="builder",
                        run_id="run-actions",
                        patch_path=patch,
                        base_commit=base_commit,
                        changed_files=["src/app.txt"],
                        extra={
                            "runtime_state_actions_path": str(runtime_actions),
                            "ticket_state_actions_path": str(ticket_actions),
                            "runtime_state_status": "pending",
                            "runtime_state_results": [],
                        },
                    )

                    committed = module.integrate_individually(
                        target,
                        [(manifest_path, json.loads(manifest_path.read_text(encoding="utf-8")))],
                        head_before=self.git_head(target),
                        checkpoint_commit=None,
                        baseline=None,
                        dry_run=False,
                    )

                    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
                    ticket_state = load_ticket_run_state(target)
                    self.assertEqual(1, len(committed))
                    self.assertEqual("applied", saved["status"])
                    self.assertEqual("already_applied", saved["integration_resolution"])
                    self.assertEqual("prompt v2\n", (target / ".agentic" / "automation_prompt.md").read_text(encoding="utf-8"))
                    self.assertEqual("done", ticket_state["tickets"][0]["status"])
                    statuses = [item["status"] for item in saved["runtime_state_results"]]
                    self.assertEqual(["applied", "applied"], statuses)


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
