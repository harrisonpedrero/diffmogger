from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
from diffmogger.runtime.state_store import (
    acquire_resource_lease,
    connect,
    database_path_for_target,
    latest_scheduler_decision_conn,
    load_ticket_run_state,
    record_human_message,
    scheduler_candidates_read_model,
    state_snapshot,
    write_canonical_state_brief,
    write_ticket_run_state,
)
CONVEYOR_PATHS = [
    ROOT / "src" / "diffmogger" / "runtime" / "run_conveyor_automation.py",
]


def load_conveyor(path: Path):
    module_name = (
        "conveyor_under_test_"
        + path.relative_to(ROOT).as_posix().replace("/", "_").replace(".", "_")
    )
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ConveyorDecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.modules = [(path, load_conveyor(path)) for path in CONVEYOR_PATHS]

    def write_text(self, root: Path, relative: str, content: str) -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
        return path

    def seed_target(self, root: Path) -> None:
        self.write_text(
            root,
            "docs/CODEX_AUTOMATION_TASKS.md",
            """
            # Codex Automation Tasks

            AUTOMATION_STATUS: ACTIVE
            """,
        )
        self.write_text(root, "scripts/run_role_automation.sh", "#!/usr/bin/env bash\n")
        for role in ("planner", "builder", "hardener", "integrator"):
            self.write_text(root, f".agentic/roles/{role}.md", f"# {role}\n")

    def write_manifest(
        self,
        root: Path,
        *,
        role: str,
        run_id: str,
        status: str,
        summary: str = "",
        changed_files: list[str] | None = None,
        runtime_state_changed_files: list[str] | None = None,
        deferral_reason: str | None = None,
        deferral_category: str | None = None,
        deferral_root_cause: str = "",
        deferral_detail: str = "",
        deferral_triage_status: str | None = None,
        deferral_next_action: str = "",
    ) -> Path:
        path = root / "target" / "automation_queue" / role / run_id / "manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, object] = {
            "role": role,
            "run_id": run_id,
            "status": status,
            "summary": summary,
            "changed_files": changed_files or [],
            "runtime_state_changed_files": runtime_state_changed_files or [],
            "created_at": "2026-05-04T00:00:00+00:00",
            "integrated_at": "2026-05-04T00:00:00+00:00",
        }
        if deferral_reason is not None:
            payload["deferral_reason"] = deferral_reason
        if deferral_category is not None:
            payload["deferral_category"] = deferral_category
        if deferral_root_cause:
            payload["deferral_root_cause"] = deferral_root_cause
        if deferral_detail:
            payload["deferral_detail"] = deferral_detail
        if deferral_triage_status is not None:
            payload["deferral_triage_status"] = deferral_triage_status
        if deferral_next_action:
            payload["deferral_next_action"] = deferral_next_action
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def conveyor_state(
        self,
        module,
        *,
        accepted_by_role: dict[str, int] | None = None,
        deferred_delta_by_role: dict[str, int] | None = None,
    ) -> dict[str, object]:
        accepted = accepted_by_role or {"planner": 0, "builder": 0, "hardener": 0}
        deferred_delta = deferred_delta_by_role or {"planner": 0, "builder": 0, "hardener": 0}
        return {
            "schema_version": 1,
            "cycles": 1,
            "role_counts": {},
            "last_completed_role": "integrator",
            "last_success_by_role": {"planner": module.utc_now()},
            "history": [
                {
                    "role": "integrator",
                    "metadata": {
                        "accepted_by_role": accepted,
                        "deferred_delta_by_role": deferred_delta,
                    },
                }
            ],
        }

    def test_conveyor_ignores_task_markdown_after_typed_status_seeded(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.assertEqual("ACTIVE", module.automation_status(target))
                    self.write_text(
                        target,
                        "docs/CODEX_AUTOMATION_TASKS.md",
                        """
                        # Codex Automation Tasks

                        AUTOMATION_STATUS: CRITICAL_STOP
                        """,
                    )

                    role, reason, stop = module.choose_next(target, self.conveyor_state(module), 2)

                    self.assertEqual("builder", role)
                    self.assertIn("builder", reason)
                    self.assertFalse(stop)

    def test_planner_deferral_changes_fast_follow_transition(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)

                    role, reason, stop = module.choose_next(
                        target,
                        self.conveyor_state(
                            module,
                            deferred_delta_by_role={"planner": 1, "builder": 0, "hardener": 0},
                        ),
                        2,
                    )
                    self.assertEqual(role, "planner")
                    self.assertIn("planner patch deferred", reason)
                    self.assertIn("fast-follow replanning", reason)
                    self.assertFalse(stop)

                    role, reason, stop = module.choose_next(
                        target,
                        self.conveyor_state(
                            module,
                            deferred_delta_by_role={"planner": -1, "builder": 0, "hardener": 0},
                        ),
                        2,
                    )
                    self.assertEqual(role, "planner")
                    self.assertIn("planner deferred patch resolved", reason)
                    self.assertIn("fast-follow replanning", reason)
                    self.assertFalse(stop)

    def test_no_progress_projection_keeps_required_fast_follow_marker(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)

                    module.write_no_progress_progress_note(
                        target,
                        {
                            "streak": 2,
                            "reason": "integrator accepted no patches",
                        },
                    )

                    progress = (target / "docs" / "MULTI_ROLE_PROGRESS.md").read_text(encoding="utf-8")
                    self.assertIn("fast-follow replanning", progress)

    def test_non_planner_deferral_does_not_preempt_builder_hardening(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)

                    role, reason, stop = module.choose_next(
                        target,
                        self.conveyor_state(
                            module,
                            accepted_by_role={"planner": 0, "builder": 1, "hardener": 0},
                            deferred_delta_by_role={"planner": 0, "builder": 1, "hardener": 0},
                        ),
                        2,
                    )

                    self.assertEqual(role, "hardener")
                    self.assertIn("builder patch integrated", reason)
                    self.assertFalse(stop)

    def test_post_builder_hardener_survives_noop_baseline_preflight(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    state = self.conveyor_state(
                        module,
                        accepted_by_role={"planner": 0, "builder": 1, "hardener": 0},
                    )
                    state["history"].append(
                        {
                            "role": "integrator",
                            "exit_code": 0,
                            "metadata": {
                                "accepted_by_role": {"planner": 0, "builder": 0, "hardener": 0},
                                "deferred_delta_by_role": {"planner": 0, "builder": 0, "hardener": 0},
                            },
                        }
                    )

                    role, reason, stop = module.choose_next(target, state, 2)

                    self.assertEqual("hardener", role)
                    self.assertIn("post-builder verification pass", reason)
                    self.assertFalse(stop)

    def test_hardener_attempt_after_builder_integration_rotates_to_planner(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    state = self.conveyor_state(
                        module,
                        accepted_by_role={"planner": 0, "builder": 1, "hardener": 0},
                    )
                    state["history"].append({"role": "hardener", "exit_code": 1})
                    state["last_completed_role"] = "hardener"

                    role, reason, stop = module.choose_next(target, state, 2)

                    self.assertEqual("planner", role)
                    self.assertIn("planner gets the next state-machine pass", reason)
                    self.assertFalse(stop)

    def test_legacy_single_lane_profile_is_ignored_by_conveyor(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.write_text(
                        target,
                        ".diffmogger/manifest.json",
                        json.dumps(
                            {
                                "features": {
                                    "automation_role_profile": "single_lane",
                                    "multi_role": False,
                                }
                            }
                        ),
                    )

                    role, reason, stop = module.choose_next(target, self.conveyor_state(module), 2)
                    queue = module.conveyor_decision_queue(target, self.conveyor_state(module), role, reason, 2)

                    self.assertEqual("builder", role)
                    self.assertIn("builder", reason)
                    self.assertFalse(stop)
                    self.assertNotIn("single_lane", {entry["role"] for entry in queue})

    def test_role_profile_wins_over_legacy_multi_role_flag(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.write_text(
                        target,
                        ".agentic/project_intake.json",
                        json.dumps(
                            {
                                "automation_role_profile": "planner_builder_hardener_integrator",
                                "multi_role_automations_allowed": False,
                            }
                        ),
                    )

                    role, reason, stop = module.choose_next(target, self.conveyor_state(module), 2)

                    self.assertEqual("builder", role)
                    self.assertIn("builder", reason)
                    self.assertFalse(stop)

    def test_missing_multi_role_files_blocks_instead_of_single_lane_fallback(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.write_text(
                        target,
                        "docs/CODEX_AUTOMATION_TASKS.md",
                        """
                        # Codex Automation Tasks

                        AUTOMATION_STATUS: ACTIVE
                        """,
                    )

                    role, reason, stop = module.choose_next(target, self.conveyor_state(module), 2)

                    self.assertIsNone(role)
                    self.assertIn("multi-role conveyor files not found", reason)
                    self.assertFalse(stop)

    def test_queued_patches_preempt_pending_post_builder_hardener(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.write_manifest(target, role="builder", run_id="run-queued", status="queued")
                    state = self.conveyor_state(
                        module,
                        accepted_by_role={"planner": 0, "builder": 1, "hardener": 0},
                    )

                    role, reason, stop = module.choose_next(target, state, 2)

                    self.assertEqual("integrator", role)
                    self.assertIn("queued role patch", reason)
                    self.assertFalse(stop)

    def test_stale_baseline_preflight_preempts_pending_post_builder_hardener(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.write_text(target, ".agentic/verification_commands.txt", "python3 -m pytest\n")
                    state = self.conveyor_state(
                        module,
                        accepted_by_role={"planner": 0, "builder": 1, "hardener": 0},
                    )

                    role, reason, stop = module.choose_next(target, state, 2)

                    self.assertEqual("integrator", role)
                    self.assertIn("baseline verification ledger", reason)
                    self.assertFalse(stop)

    def test_candidate_done_without_final_evidence_gets_hardener_catchup(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.write_ticket_run(
                        target,
                        """
                        {
                          "run_id": "campaign-active",
                          "halt_when_complete": true,
                          "tickets": [
                            {"id": "T-1", "status": "candidate_done", "summary": "Add saved searches", "evidence": ["builder implemented local UI"]},
                            {"id": "T-2", "status": "pending", "summary": "Add exports"}
                          ]
                        }
                        """,
                    )
                    state = self.conveyor_state(module)

                    role, reason, stop = module.choose_next(target, state, 2)

                    self.assertEqual("hardener", role)
                    self.assertIn("candidate_done ticket", reason)
                    self.assertIn("T-1", reason)
                    self.assertFalse(stop)

    def test_decision_queue_plans_post_builder_hardener_after_baseline_preflight(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.write_text(target, ".agentic/verification_commands.txt", "python3 -m pytest\n")
                    state = self.conveyor_state(
                        module,
                        accepted_by_role={"planner": 0, "builder": 1, "hardener": 0},
                    )
                    role, reason, _stop = module.choose_next(target, state, 2)

                    queue = module.conveyor_decision_queue(target, state, role, reason, 2)

                    self.assertEqual("integrator", queue[0]["role"])
                    self.assertTrue(
                        any(item["role"] == "hardener" and item["state"] == "planned" for item in queue),
                        queue,
                    )

    def test_decision_queue_exposes_planner_fast_follow(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    state = self.conveyor_state(
                        module,
                        deferred_delta_by_role={"planner": -1, "builder": 0, "hardener": 0},
                    )
                    role, reason, _stop = module.choose_next(target, state, 2)

                    queue = module.conveyor_decision_queue(target, state, role, reason, 2)

                    self.assertEqual(queue[0]["role"], "planner")
                    self.assertEqual(queue[0]["state"], "next")
                    self.assertIn("planner deferred patch resolved", queue[0]["reason"])

    def write_ticket_run(self, root: Path, payload: str) -> None:
        write_ticket_run_state(
            root,
            json.loads(textwrap.dedent(payload)),
            actor_role="test",
            event_type="ticket.run_seeded",
        )

    def context_node_id(self, target: Path, path: str) -> str:
        snapshot = state_snapshot(target)
        pack = snapshot.get("context_pack_preview") if isinstance(snapshot.get("context_pack_preview"), dict) else {}
        for item in pack.get("items", []) if isinstance(pack.get("items"), list) else []:
            if isinstance(item, dict) and item.get("path") == path:
                return str(item.get("node_id") or "")
        self.fail(f"context node not found for {path}")

    def codebase_graph_snapshot_count(self, target: Path) -> int:
        with closing(connect(database_path_for_target(target))) as conn:
            return int(
                conn.execute(
                    "SELECT COUNT(*) AS count FROM graph_snapshots WHERE graph_namespace = 'codebase'"
                ).fetchone()["count"]
            )

    def test_graph_scheduler_selects_ready_ticket_with_free_lease(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.write_text(target, "src/auth.py", "def login():\n    return True\n")
                    self.write_ticket_run(
                        target,
                        """
                        {
                          "run_id": "campaign-active",
                          "halt_when_complete": true,
                          "tickets": [
                            {"id": "T-1", "status": "pending", "summary": "Update src/auth.py login flow"}
                          ]
                        }
                        """,
                    )

                    role, reason, stop = module.choose_next(target, self.conveyor_state(module), 2)
                    snapshot = state_snapshot(target)

                    self.assertEqual("builder", role)
                    self.assertIn("graph-aware scheduler selected ready ticket", reason)
                    self.assertFalse(stop)
                    self.assertFalse(snapshot["scheduler_fallback_used"])
                    self.assertEqual("implement_ready_ticket", snapshot["selected_candidate"]["action_kind"])
                    self.assertEqual("T-1", snapshot["selected_candidate"]["public_task_id"])
                    self.assertEqual(snapshot["selected_candidate"], snapshot["selected_scheduler_candidate"])
                    self.assertTrue(snapshot["selected_candidate"]["required_leases"])
                    self.assertEqual(snapshot["selected_candidate"]["required_leases"], snapshot["selected_candidate"]["suggested_leases"])
                    self.assertEqual([], snapshot["selected_candidate"]["acquired_leases"])
                    self.assertTrue(snapshot["selected_candidate"]["candidate_id"].startswith("scheduler-candidate:"))
                    self.assertTrue(all(item.get("candidate_id") for item in snapshot["scheduling_candidates"]))
                    self.assertTrue(snapshot["graph_signals_used"]["graph_can_select"])
                    with closing(connect(database_path_for_target(target))) as conn:
                        latest = latest_scheduler_decision_conn(conn)
                        read_model = scheduler_candidates_read_model(conn)
                    self.assertEqual(latest["decision_id"], read_model["decision_id"])
                    self.assertEqual(snapshot["selected_candidate"]["candidate_id"], latest["selected_candidate"]["candidate_id"])
                    before_count = self.codebase_graph_snapshot_count(target)
                    self.write_text(target, "src/new_after_decision.py", "VALUE = 1\n")
                    with closing(connect(database_path_for_target(target))) as conn:
                        reread = latest_scheduler_decision_conn(conn)
                    self.assertEqual(latest["decision_id"], reread["decision_id"])
                    self.assertEqual(before_count, self.codebase_graph_snapshot_count(target))

                    brief = write_canonical_state_brief(target)
                    markdown = Path(brief["path"]).read_text(encoding="utf-8")
                    self.assertIn("## Scheduler Decision", markdown)
                    self.assertIn("selected_candidate", markdown)
                    self.assertIn("T-1", markdown)
                    self.assertIn("context:", markdown)
                    self.assertIn("suggested_lease", markdown)

    def test_graph_scheduler_skips_task_with_conflicting_lease(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.write_text(target, "src/auth.py", "VALUE = 1\n")
                    self.write_ticket_run(
                        target,
                        """
                        {
                          "run_id": "campaign-active",
                          "halt_when_complete": true,
                          "tickets": [
                            {"id": "T-1", "status": "pending", "summary": "Update src/auth.py"}
                          ]
                        }
                        """,
                    )
                    auth_node_id = self.context_node_id(target, "src/auth.py")
                    acquire_resource_lease(
                        target,
                        task_id="OTHER",
                        owner_role="builder",
                        run_id="run-other",
                        scope_kind="file",
                        scope_node_id=auth_node_id,
                    )

                    role, reason, stop = module.choose_next(target, self.conveyor_state(module), 2)
                    snapshot = state_snapshot(target)
                    queue = module.conveyor_decision_queue(target, self.conveyor_state(module), role, reason, 2)

                    self.assertEqual("builder", role)
                    self.assertFalse(stop)
                    self.assertTrue(snapshot["scheduler_fallback_used"])
                    self.assertTrue(snapshot["lease_conflicts_considered"])
                    self.assertEqual(snapshot["skipped_candidates"], snapshot["skipped_scheduler_candidates"])
                    self.assertTrue(
                        any(
                            item.get("public_task_id") == "T-1"
                            and "resource lease conflict" in str(item.get("skipped_reason"))
                            for item in snapshot["skipped_candidates"]
                        ),
                        snapshot["skipped_candidates"],
                    )
                    self.assertTrue(any(item["state"] == "skipped" and "resource lease conflict" in item["reason"] for item in queue))

    def test_graph_scheduler_queued_patch_outranks_normal_builder_work(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.write_text(target, "src/auth.py", "VALUE = 1\n")
                    self.write_manifest(target, role="builder", run_id="run-queued", status="queued")
                    self.write_ticket_run(
                        target,
                        """
                        {
                          "run_id": "campaign-active",
                          "halt_when_complete": true,
                          "tickets": [
                            {"id": "T-1", "status": "pending", "summary": "Update src/auth.py"}
                          ]
                        }
                        """,
                    )

                    role, reason, stop = module.choose_next(target, self.conveyor_state(module), 2)
                    snapshot = state_snapshot(target)

                    self.assertEqual("integrator", role)
                    self.assertIn("queued role patch", reason)
                    self.assertFalse(stop)
                    self.assertEqual("integrate_queued_patch", snapshot["selected_candidate"]["action_kind"])
                    self.assertEqual("integrate_queued_patch", snapshot["selected_scheduler_candidate"]["action_kind"])
                    self.assertFalse(snapshot["scheduler_fallback_used"])
                    self.assertEqual("integrator", snapshot["legacy_result"]["role"])
                    self.assertTrue(
                        any("outranks graph-normal work" in str(item.get("skipped_reason")) for item in snapshot["skipped_candidates"])
                    )

    def test_graph_scheduler_baseline_preflight_outranks_normal_builder_work(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.write_text(target, ".agentic/verification_commands.txt", "python3 -m pytest\n")
                    self.write_text(target, "src/auth.py", "VALUE = 1\n")
                    self.write_ticket_run(
                        target,
                        """
                        {
                          "run_id": "campaign-active",
                          "halt_when_complete": true,
                          "tickets": [
                            {"id": "T-1", "status": "pending", "summary": "Update src/auth.py"}
                          ]
                        }
                        """,
                    )

                    role, reason, stop = module.choose_next(target, self.conveyor_state(module), 2)
                    snapshot = state_snapshot(target)

                    self.assertEqual("integrator", role)
                    self.assertIn("baseline verification ledger", reason)
                    self.assertFalse(stop)
                    self.assertEqual("baseline_preflight", snapshot["selected_candidate"]["action_kind"])
                    self.assertFalse(snapshot["scheduler_fallback_used"])
                    self.assertEqual("baseline_preflight", snapshot["legacy_result"]["action_kind"])

    def test_graph_scheduler_human_messages_outrank_normal_builder_work(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.write_text(target, "src/auth.py", "VALUE = 1\n")
                    self.write_ticket_run(
                        target,
                        """
                        {
                          "run_id": "campaign-active",
                          "halt_when_complete": true,
                          "tickets": [
                            {"id": "T-1", "status": "pending", "summary": "Update src/auth.py"}
                          ]
                        }
                        """,
                    )
                    record_human_message(
                        target,
                        kind="note",
                        body="Please clarify whether auth should support recovery codes.",
                        actor_role="test",
                    )

                    role, reason, stop = module.choose_next(target, self.conveyor_state(module), 2)
                    snapshot = state_snapshot(target)

                    self.assertEqual("planner", role)
                    self.assertIn("human message", reason)
                    self.assertFalse(stop)
                    self.assertEqual("human_triage", snapshot["selected_candidate"]["action_kind"])
                    self.assertFalse(snapshot["scheduler_fallback_used"])

    def test_graph_scheduler_fallback_preserves_current_behavior_without_ready_task(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)

                    role, reason, stop = module.choose_next(target, self.conveyor_state(module), 2)
                    snapshot = state_snapshot(target)

                    self.assertEqual("builder", role)
                    self.assertIn("builder-first policy", reason)
                    self.assertFalse(stop)
                    self.assertTrue(snapshot["scheduler_fallback_used"])
                    self.assertEqual("normal_builder_work", snapshot["selected_candidate"]["action_kind"])

    def test_ticket_campaign_complete_stops_conveyor(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.write_ticket_run(
                        target,
                        """
                        {
                          "run_id": "campaign-complete",
                          "halt_when_complete": true,
                          "tickets": [
                            {"id": "T-1", "status": "done", "evidence": ["test passed"]}
                          ]
                        }
                        """,
                    )

                    role, reason, stop = module.choose_next(target, self.conveyor_state(module), 2)

                    self.assertIsNone(role)
                    self.assertEqual(reason, "bounded campaign complete")
                    self.assertTrue(stop)

    def test_ticket_campaign_blocked_stops_conveyor(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.write_ticket_run(
                        target,
                        """
                        {
                          "run_id": "campaign-blocked",
                          "halt_when_complete": true,
                          "tickets": [
                            {"id": "T-1", "status": "done", "evidence": ["test passed"]},
                            {"id": "T-2", "status": "blocked", "blocker": "needs API key"}
                          ]
                        }
                        """,
                    )

                    role, reason, stop = module.choose_next(target, self.conveyor_state(module), 2)

                    self.assertIsNone(role)
                    self.assertEqual(reason, "bounded campaign blocked")
                    self.assertTrue(stop)

    def test_active_ticket_campaign_does_not_preempt_normal_conveyor(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.write_ticket_run(
                        target,
                        """
                        {
                          "run_id": "campaign-active",
                          "halt_when_complete": true,
                          "tickets": [
                            {"id": "T-1", "status": "pending"}
                          ]
                        }
                        """,
                    )

                    role, reason, stop = module.choose_next(target, self.conveyor_state(module), 2)

                    self.assertEqual(role, "builder")
                    self.assertIn("builder-first policy", reason)
                    self.assertFalse(stop)

    def test_ongoing_campaign_drafts_next_ticket_without_approval_pause(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.write_ticket_run(
                        target,
                        """
                        {
                          "run_id": "ongoing-campaign",
                          "campaign_mode": "ongoing",
                          "halt_when_complete": false,
                          "tickets": [
                            {"id": "T-1", "status": "done", "evidence": ["test passed"]}
                          ]
                        }
                        """,
                    )

                    role, reason, stop = module.choose_next(target, self.conveyor_state(module), 2)
                    ticket_run = load_ticket_run_state(target)
                    tickets = ticket_run["tickets"] if ticket_run else []

                    self.assertEqual(role, "builder")
                    self.assertIn("builder-first policy", reason)
                    self.assertFalse(stop)
                    self.assertTrue(any(ticket.get("id") == "AUTO-002" for ticket in tickets))
                    self.assertTrue(any(ticket.get("status") == "pending" for ticket in tickets))

    def test_deferral_signature_uses_root_cause_before_local_paths(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                local_path = "/User" + "s/example/project/test.ts"
                signature = module.normalized_deferral_signature(
                    {
                        "deferral_reason": "verification_failure",
                        "deferral_detail": f"Error in {local_path}: DATABASE_URL is not set",
                    }
                )

                self.assertEqual("verification_failure:missing_env_var", signature)
                self.assertNotIn("local_path_reference", signature)

    def test_duplicate_builder_deferrals_route_to_integrator_triage(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    for run_id in ("run-a", "run-b"):
                        manifest = target / "target" / "automation_queue" / "builder" / run_id / "manifest.json"
                        manifest.parent.mkdir(parents=True, exist_ok=True)
                        manifest.write_text(
                            textwrap.dedent(
                                f"""
                                {{
                                  "role": "builder",
                                  "run_id": "{run_id}",
                                  "status": "deferred",
                                  "deferral_reason": "verification_failure",
                                  "deferral_category": "missing_env_var",
                                  "changed_files": ["src/query.ts"],
                                  "created_at": "2026-05-04T00:00:00+00:00"
                                }}
                                """
                            ).strip()
                            + "\n",
                            encoding="utf-8",
                        )

                    role, reason, stop = module.choose_next(target, self.conveyor_state(module), 2)

                    self.assertEqual("integrator", role)
                    self.assertIn("duplicate builder deferred patches need triage", reason)
                    self.assertFalse(stop)

    def test_repeated_hardener_guardrail_deferrals_route_to_planner_repair(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.write_ticket_run(
                        target,
                        """
                        {
                          "run_id": "campaign-active",
                          "halt_when_complete": true,
                          "tickets": [
                            {"id": "#76", "status": "candidate_done", "summary": "Harden auth rate limit", "evidence": ["builder touched auth rate limit tests"]}
                          ]
                        }
                        """,
                    )
                    for run_id in ("run-hardener-a", "run-hardener-b"):
                        self.write_manifest(
                            target,
                            role="hardener",
                            run_id=run_id,
                            status="deferred",
                            summary="Ticket #76 hardener patch rewrote auth rate-limit tests.",
                            changed_files=["apps/web/tests/api.auth.rate-limit.test.ts"],
                            deferral_reason="guardrail_violation",
                            deferral_category="guardrail_violation",
                            deferral_root_cause="Hardener removed or substantially rewrote tests without a Test change rationale summary line.",
                            deferral_detail="Hardener removed or substantially rewrote tests without a `Test change rationale:` summary line.",
                        )

                    state = self.conveyor_state(module)
                    role, reason, stop = module.choose_next(target, state, 2)
                    queue = module.conveyor_decision_queue(target, state, role, reason, 2)

                    self.assertEqual("planner", role)
                    self.assertIn("repeated hardener guardrail deferrals", reason)
                    self.assertIn("guardrail_violation", reason)
                    self.assertIn("Test change rationale", reason)
                    self.assertFalse(stop)
                    self.assertEqual("planner", queue[0]["role"])
                    self.assertIn("repair", queue[0]["reason"])

    def test_missing_baseline_ledger_routes_to_integrator_preflight(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.write_text(target, ".agentic/verification_commands.txt", "python3 -m pytest\n")

                    role, reason, stop = module.choose_next(target, self.conveyor_state(module), 2)

                    self.assertEqual("integrator", role)
                    self.assertIn("baseline verification ledger", reason)
                    self.assertFalse(stop)

    def test_integrator_role_uses_role_wrapper_command(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)

                    command = module.command_for_role(target, "integrator")

                    self.assertEqual("bash", command[0])
                    self.assertEqual("--role", command[-2])
                    self.assertEqual("integrator", command[-1])
                    self.assertTrue(command[1].endswith("scripts/run_role_automation.sh"))

    def test_false_positive_baseline_blocker_routes_to_preflight_refresh(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.write_text(target, ".agentic/verification_commands.txt", "npm ci\n")
                    self.write_text(
                        target,
                        "target/baseline_verification.json",
                        """
                        {
                          "schema_version": 1,
                          "head": "abc",
                          "verification_config_hash": "missing",
                          "status": "blocked_environment",
                          "category": "missing_env_var",
                          "root_cause": "Missing required environment variable `EBADENGINE`.",
                          "failure_signature": "verification_environment_failure:missing_env_var:abc",
                          "checks_run": ["npm ci"],
                          "detail": "$ npm ci\\nexit=0\\nnpm warn EBADENGINE Unsupported engine {\\nnpm warn EBADENGINE   required: { node: '^20.19.0 || ^22.13.0 || >=24' }\\nnpm warn EBADENGINE }"
                        }
                        """,
                    )

                    role, reason, stop = module.choose_next(target, self.conveyor_state(module), 2)

                    self.assertEqual("integrator", role)
                    self.assertIn("baseline verification ledger", reason)
                    self.assertFalse(stop)

    def test_baseline_source_failure_routes_to_repair_lane(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.write_text(target, ".agentic/verification_commands.txt", "python3 -m pytest\n")
                    self.write_text(
                        target,
                        "target/baseline_verification.json",
                        """
                        {
                          "schema_version": 1,
                          "head": "abc",
                          "verification_config_hash": "missing",
                          "status": "failing_source",
                          "root_cause": "Expected category to match fixture",
                          "failure_signature": "verification_failure:test_assertion_failure:abc"
                        }
                        """,
                    )

                    role, reason, stop = module.choose_next(target, self.conveyor_state(module), 2)

                    self.assertEqual("planner", role)
                    self.assertIn("verification_scope=baseline_repair", reason)
                    self.assertFalse(stop)

    def test_repairable_local_service_routes_from_planner_to_builder(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.write_text(target, ".agentic/verification_commands.txt", "corepack pnpm test\n")
                    self.write_text(
                        target,
                        "target/baseline_verification.json",
                        """
                        {
                          "schema_version": 1,
                          "head": "abc",
                          "verification_config_hash": "missing",
                          "status": "repairable_local_service",
                          "root_cause": "Local PostgreSQL is unavailable at 127.0.0.1:5432.",
                          "failure_signature": "verification_environment_failure:missing_local_database:abc"
                        }
                        """,
                    )
                    state = self.conveyor_state(module)
                    state["last_completed_role"] = "planner"

                    role, reason, stop = module.choose_next(target, state, 2)

                    self.assertEqual("builder", role)
                    self.assertIn("local service harness", reason)
                    self.assertIn("verification_scope=baseline_repair", reason)
                    self.assertFalse(stop)

    def test_repairable_local_service_routes_from_accepted_planner_handoff_to_builder(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.write_text(target, ".agentic/verification_commands.txt", "corepack pnpm test\n")
                    self.write_ticket_run(
                        target,
                        """
                        {
                          "run_id": "campaign-blocked",
                          "halt_when_complete": true,
                          "tickets": [
                            {"id": "T-1", "status": "blocked", "evidence": ["focused checks passed"], "blocker": "local database unavailable"}
                          ]
                        }
                        """,
                    )
                    self.write_text(
                        target,
                        "target/baseline_verification.json",
                        """
                        {
                          "schema_version": 1,
                          "head": "abc",
                          "verification_config_hash": "missing",
                          "status": "repairable_local_service",
                          "root_cause": "Local PostgreSQL is unavailable at 127.0.0.1:5432.",
                          "failure_signature": "verification_environment_failure:missing_local_database:abc"
                        }
                        """,
                    )
                    state = self.conveyor_state(
                        module,
                        accepted_by_role={"planner": 1, "builder": 0, "hardener": 0},
                    )

                    role, reason, stop = module.choose_next(target, state, 2)

                    self.assertEqual("builder", role)
                    self.assertIn("local service harness", reason)
                    self.assertIn("verification_scope=baseline_repair", reason)
                    self.assertFalse(stop)

    def test_repairable_local_service_ignores_noop_integrator_after_planner_handoff(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.write_text(target, ".agentic/verification_commands.txt", "corepack pnpm test\n")
                    self.write_ticket_run(
                        target,
                        """
                        {
                          "run_id": "campaign-blocked",
                          "halt_when_complete": true,
                          "tickets": [
                            {"id": "T-1", "status": "blocked", "evidence": ["focused checks passed"], "blocker": "local database unavailable"}
                          ]
                        }
                        """,
                    )
                    self.write_text(
                        target,
                        "target/baseline_verification.json",
                        """
                        {
                          "schema_version": 1,
                          "head": "abc",
                          "verification_config_hash": "missing",
                          "status": "repairable_local_service",
                          "root_cause": "Local PostgreSQL is unavailable at 127.0.0.1:5432.",
                          "failure_signature": "verification_environment_failure:missing_local_database:abc"
                        }
                        """,
                    )
                    state = self.conveyor_state(
                        module,
                        accepted_by_role={"planner": 1, "builder": 0, "hardener": 0},
                    )
                    state["history"].append(
                        {
                            "role": "integrator",
                            "metadata": {
                                "accepted_by_role": {"planner": 0, "builder": 0, "hardener": 0},
                                "deferred_delta_by_role": {"planner": 0, "builder": 0, "hardener": 0},
                            },
                        }
                    )

                    role, reason, stop = module.choose_next(target, state, 2)

                    self.assertEqual("builder", role)
                    self.assertIn("local service harness", reason)
                    self.assertIn("verification_scope=baseline_repair", reason)
                    self.assertFalse(stop)

    def test_repairable_local_service_routes_from_accepted_builder_repair_to_hardener(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.write_text(target, ".agentic/verification_commands.txt", "corepack pnpm test\n")
                    self.write_text(
                        target,
                        "target/baseline_verification.json",
                        """
                        {
                          "schema_version": 1,
                          "head": "abc",
                          "verification_config_hash": "missing",
                          "status": "repairable_local_service",
                          "root_cause": "Local PostgreSQL is unavailable at 127.0.0.1:5432.",
                          "failure_signature": "verification_environment_failure:missing_local_database:abc"
                        }
                        """,
                    )
                    state = self.conveyor_state(
                        module,
                        accepted_by_role={"planner": 0, "builder": 1, "hardener": 0},
                    )

                    role, reason, stop = module.choose_next(target, state, 2)

                    self.assertEqual("hardener", role)
                    self.assertIn("baseline local-service repair", reason)
                    self.assertIn("verification_scope=baseline_repair", reason)
                    self.assertFalse(stop)

    def test_blocked_environment_baseline_idles_after_preflight(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.write_text(target, ".agentic/verification_commands.txt", "python3 -m pytest\n")
                    self.write_text(
                        target,
                        "target/baseline_verification.json",
                        """
                        {
                          "schema_version": 1,
                          "head": "abc",
                          "verification_config_hash": "missing",
                          "status": "blocked_environment",
                          "root_cause": "Missing required environment variable DATABASE_URL.",
                          "failure_signature": "verification_environment_failure:missing_env_var:abc"
                        }
                        """,
                    )

                    role, reason, stop = module.choose_next(target, self.conveyor_state(module), 2)

                    self.assertIsNone(role)
                    self.assertIn("blocked_environment", reason)
                    self.assertFalse(stop)

    def test_blocked_ticket_campaign_runs_baseline_preflight_before_halting(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.write_text(target, ".agentic/verification_commands.txt", "corepack pnpm test\n")
                    self.write_ticket_run(
                        target,
                        """
                        {
                          "run_id": "campaign-blocked",
                          "halt_when_complete": true,
                          "tickets": [
                            {"id": "T-1", "status": "blocked", "evidence": ["focused checks passed"], "blocker": "local database unavailable"}
                          ]
                        }
                        """,
                    )

                    role, reason, stop = module.choose_next(target, self.conveyor_state(module), 2)

                    self.assertEqual("integrator", role)
                    self.assertIn("baseline verification may be repairable", reason)
                    self.assertFalse(stop)

    def test_triaged_builder_deferral_gets_planner_handoff_once(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    manifest = target / "target" / "automation_queue" / "builder" / "run-new" / "manifest.json"
                    manifest.parent.mkdir(parents=True, exist_ok=True)
                    manifest.write_text(
                        textwrap.dedent(
                            """
                            {
                              "role": "builder",
                              "run_id": "run-new",
                              "status": "deferred",
                              "deferral_reason": "conflict",
                              "deferral_category": "apply_conflict",
                              "deferral_triage_status": "replace-from-current-HEAD",
                              "deferral_next_action": "Replace this work from current HEAD before retrying.",
                              "changed_files": ["src/query.ts"],
                              "created_at": "2026-05-04T00:00:00+00:00"
                            }
                            """
                        ).strip()
                        + "\n",
                        encoding="utf-8",
                    )

                    role, reason, stop = module.choose_next(target, self.conveyor_state(module), 2)

                    self.assertEqual("planner", role)
                    self.assertIn("replace-from-current-HEAD", reason)
                    self.assertFalse(stop)

    def test_planner_only_acceptance_with_unchanged_builder_deferral_is_no_progress(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.write_manifest(
                        target,
                        role="builder",
                        run_id="run-builder-deferred",
                        status="deferred",
                        changed_files=["src/query.ts"],
                        deferral_reason="verification_failure",
                        deferral_category="typescript_compiler_error",
                        deferral_root_cause="src/query.ts(12,9): error TS2345: type mismatch",
                    )
                    before = module.queue_snapshot(target)
                    planner_requested_at = "2026-05-04T00:10:00+00:00"
                    state = {
                        module.NO_PROGRESS_STATE_KEY: {
                            "active": False,
                            "streak": 1,
                            "threshold": 2,
                            "signature": before["deferred_signature"],
                            "planner_requested_at": planner_requested_at,
                        }
                    }
                    self.write_manifest(
                        target,
                        role="planner",
                        run_id="run-planner-docs",
                        status="applied",
                        changed_files=["docs/CODEX_AUTOMATION_TASKS.md"],
                    )
                    after = module.queue_snapshot(target)

                    metadata = module.update_integrator_no_progress(
                        state,
                        before=before,
                        after=after,
                        exit_code=0,
                        threshold=2,
                        finished_at="2026-05-04T00:20:00+00:00",
                    )

                    info = state[module.NO_PROGRESS_STATE_KEY]
                    self.assertFalse(metadata["progress_success"])
                    self.assertTrue(metadata["planner_only_acceptance"])
                    self.assertTrue(metadata["builder_deferred_unchanged"])
                    self.assertTrue(metadata["planner_acceptance_did_not_unstick_builder_deferral"])
                    self.assertEqual(2, info["streak"])
                    self.assertTrue(info["active"])
                    self.assertEqual(planner_requested_at, info["planner_requested_at"])
                    self.assertIn("planner-only", info["reason"])

    def test_active_no_progress_blocks_before_second_builder_deferral_planner_followup(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.write_manifest(
                        target,
                        role="builder",
                        run_id="run-builder-deferred",
                        status="deferred",
                        changed_files=["src/query.ts"],
                        deferral_reason="verification_failure",
                        deferral_category="typescript_compiler_error",
                        deferral_triage_status="replace-from-current-HEAD",
                        deferral_next_action="Planner already prepared a retry handoff.",
                    )
                    snapshot = module.queue_snapshot(target)
                    state = self.conveyor_state(module)
                    state[module.NO_PROGRESS_STATE_KEY] = {
                        "active": True,
                        "streak": 2,
                        "threshold": 2,
                        "signature": snapshot["deferred_signature"],
                        "builder_deferred_signature": snapshot["deferred_signature_by_role"]["builder"],
                        "planner_requested_at": "2026-05-04T00:10:00+00:00",
                        "reason": "integrator accepted planner-only patch, but builder deferred queue stayed blocked",
                    }

                    role, reason, stop = module.choose_next(target, state, 2)

                    self.assertIsNone(role)
                    self.assertIn("no-progress circuit breaker active after planner handoff", reason)
                    self.assertNotIn("builder deferred patch triaged", reason)
                    self.assertFalse(stop)

    def test_stale_active_role_run_with_missing_pid_is_cleared(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    state = {
                        "schema_version": 1,
                        "history": [],
                        "active_role_run": {
                            "role": "builder",
                            "run_id": "run-orphaned",
                            "pid": 99999999,
                            "started_at": "2026-05-04T00:00:00+00:00",
                            "status": "running",
                        },
                    }

                    recovery = module.recover_stale_active_role_run(
                        target,
                        state,
                        timeout_seconds=1,
                        grace_seconds=0,
                    )

                    self.assertIsNotNone(recovery)
                    self.assertEqual("orphaned", recovery["status"])
                    self.assertIsNone(state["active_role_run"])
                    self.assertEqual("orphaned", state["last_active_role_run"]["status"])
                    self.assertEqual(1, state["last_exit_code"])
                    self.assertEqual("orphaned", state["history"][-1]["metadata"]["active_role_recovery"])

    def test_over_age_active_role_run_is_killed_and_records_timeout_streak(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    proc = subprocess.Popen(
                        [
                            sys.executable,
                            "-c",
                            (
                                "import signal, time\n"
                                "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                                "time.sleep(60)\n"
                            ),
                        ],
                        start_new_session=True,
                    )
                    old_started = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat(timespec="seconds")
                    state = {
                        "schema_version": 1,
                        "history": [],
                        "active_role_run": {
                            "role": "hardener",
                            "run_id": "run-timeout",
                            "pid": proc.pid,
                            "started_at": old_started,
                            "status": "running",
                        },
                    }
                    try:
                        recovery = module.recover_stale_active_role_run(
                            target,
                            state,
                            timeout_seconds=1,
                            grace_seconds=0,
                        )
                        proc.wait(timeout=5)
                    finally:
                        if proc.poll() is None:
                            os.killpg(proc.pid, signal.SIGKILL)
                            proc.wait(timeout=5)

                    self.assertIsNotNone(recovery)
                    self.assertEqual("timed_out", recovery["status"])
                    self.assertIsNone(state["active_role_run"])
                    self.assertEqual("timed_out", state["last_active_role_run"]["status"])
                    self.assertEqual(module.ROLE_TIMEOUT_EXIT_CODE, state["last_exit_code"])
                    self.assertEqual(1, module.timeout_streak_count(state, "hardener"))
                    self.assertEqual("timed_out", state["history"][-1]["metadata"]["active_role_recovery"])

    def test_timeout_circuit_breaker_routes_repeated_role_timeout_to_planner(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                state = {
                    "role_timeout_streaks": {
                        "hardener": {"count": 2, "last_timed_out_at": "2026-05-04T00:00:00+00:00"}
                    }
                }

                role, reason, stop = module.apply_timeout_circuit_breaker(
                    state,
                    "hardener",
                    "candidate_done ticket needs hardener verification",
                    False,
                    threshold=2,
                )

                self.assertEqual("planner", role)
                self.assertIn("hardener lane timed out 2 consecutive time(s)", reason)
                self.assertFalse(stop)


class GitHeadPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.modules = [(path, load_conveyor(path)) for path in CONVEYOR_PATHS]

    def test_missing_directory_is_not_a_repo(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                status, detail = module.git_head_status(Path("/nonexistent/diffmogger/target/xyz"))
                self.assertEqual(status, "not_a_repo")
                self.assertIn("does not exist", detail)

    def test_non_git_directory(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    status, _ = module.git_head_status(Path(tmp))
                    self.assertEqual(status, "not_a_repo")

    def test_repo_without_commits(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
                    status, detail = module.git_head_status(Path(tmp))
                    self.assertEqual(status, "no_commits")
                    self.assertIn("no commits", detail)

    def test_repo_with_commit(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
                    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp, check=True)
                    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp, check=True)
                    subprocess.run(
                        ["git", "commit", "--allow-empty", "-m", "init", "-q"],
                        cwd=tmp,
                        check=True,
                    )
                    status, _ = module.git_head_status(Path(tmp))
                    self.assertEqual(status, "ok")


class ConveyorSignalCleanupTests(unittest.TestCase):
    def write_text(self, root: Path, relative: str, content: str) -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
        return path

    def seed_blocked_git_target(self, target: Path) -> None:
        subprocess.run(["git", "init", "-q"], cwd=target, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=target, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=target, check=True)
        self.write_text(
            target,
            "docs/CODEX_AUTOMATION_TASKS.md",
            """
            # Codex Automation Tasks

            AUTOMATION_STATUS: BLOCKED_ON_USER
            """,
        )
        subprocess.run(["git", "add", "."], cwd=target, check=True)
        subprocess.run(["git", "commit", "-m", "init", "-q"], cwd=target, check=True)

    def test_sigterm_during_idle_sleep_releases_conveyor_lock(self) -> None:
        for path in CONVEYOR_PATHS:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_blocked_git_target(target)
                    proc = subprocess.Popen(
                        [
                            sys.executable,
                            str(path),
                            "--target",
                            str(target),
                            "--idle-sleep-seconds",
                            "60",
                        ],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    lock_path = target / "target" / "automation_conveyor.lock"
                    try:
                        deadline = time.monotonic() + 5
                        while time.monotonic() < deadline and not lock_path.exists():
                            if proc.poll() is not None:
                                break
                            time.sleep(0.05)
                        self.assertTrue(lock_path.exists(), "conveyor did not acquire its lock")

                        proc.send_signal(signal.SIGTERM)
                        stdout, stderr = proc.communicate(timeout=5)
                    finally:
                        if proc.poll() is None:
                            proc.kill()
                            proc.communicate(timeout=5)

                    self.assertEqual(proc.returncode, 143, stderr)
                    self.assertFalse(lock_path.exists(), stdout + stderr)
                    self.assertIn("CONVEYOR_SIGNAL", stdout)
                    self.assertIn("CONVEYOR_LOCK_RELEASED", stdout)


class ConveyorSourceSafetyTests(unittest.TestCase):
    def test_cli_uses_runner_termination_flag(self) -> None:
        cli_text = (ROOT / "src" / "diffmogger" / "conveyor" / "cli.py").read_text(encoding="utf-8")

        self.assertIn("if conveyor_runner.TERMINATE_REQUESTED:", cli_text)
        self.assertNotIn("if TERMINATE_REQUESTED:", cli_text)


if __name__ == "__main__":
    unittest.main()
