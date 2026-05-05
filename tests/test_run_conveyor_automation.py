from __future__ import annotations

import importlib.util
import json
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONVEYOR_PATHS = [
    ROOT / "scripts" / "run_conveyor_automation.py",
    ROOT / "templates" / "scripts" / "run_conveyor_automation.py",
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
    ) -> Path:
        path = root / "target" / "automation_queue" / role / run_id / "manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "role": role,
                    "run_id": run_id,
                    "status": status,
                    "summary": summary,
                    "changed_files": changed_files or [],
                    "runtime_state_changed_files": runtime_state_changed_files or [],
                    "created_at": "2026-05-04T00:00:00+00:00",
                    "integrated_at": "2026-05-04T00:00:00+00:00",
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
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

    def test_planner_deferral_changes_fast_follow_before_interval(self) -> None:
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
                        3600,
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
                        3600,
                        2,
                    )
                    self.assertEqual(role, "planner")
                    self.assertIn("planner deferred patch resolved", reason)
                    self.assertIn("fast-follow replanning", reason)
                    self.assertFalse(stop)

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
                        3600,
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

                    role, reason, stop = module.choose_next(target, state, 3600, 2)

                    self.assertEqual("hardener", role)
                    self.assertIn("post-builder verification pass", reason)
                    self.assertFalse(stop)

    def test_hardener_attempt_after_builder_integration_clears_pending_pass(self) -> None:
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

                    role, reason, stop = module.choose_next(target, state, 3600, 2)

                    self.assertEqual("builder", role)
                    self.assertIn("builder lane is next", reason)
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

                    role, reason, stop = module.choose_next(target, state, 3600, 2)

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

                    role, reason, stop = module.choose_next(target, state, 3600, 2)

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

                    role, reason, stop = module.choose_next(target, state, 3600, 2)

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
                    role, reason, _stop = module.choose_next(target, state, 3600, 2)

                    queue = module.conveyor_decision_queue(target, state, role, reason, 3600, 2)

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
                    role, reason, _stop = module.choose_next(target, state, 3600, 2)

                    queue = module.conveyor_decision_queue(target, state, role, reason, 3600, 2)

                    self.assertEqual(queue[0]["role"], "planner")
                    self.assertEqual(queue[0]["state"], "next")
                    self.assertIn("planner deferred patch resolved", queue[0]["reason"])

    def write_ticket_run(self, root: Path, payload: str) -> None:
        self.write_text(
            root,
            "docs/TICKET_RUN.md",
            f"""
            # Ticket Run

            ```json ticket-run
            {payload}
            ```
            """,
        )

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

                    role, reason, stop = module.choose_next(target, self.conveyor_state(module), 3600, 2)

                    self.assertIsNone(role)
                    self.assertEqual(reason, "ticket campaign complete")
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

                    role, reason, stop = module.choose_next(target, self.conveyor_state(module), 3600, 2)

                    self.assertIsNone(role)
                    self.assertEqual(reason, "ticket campaign blocked")
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

                    role, reason, stop = module.choose_next(target, self.conveyor_state(module), 3600, 2)

                    self.assertEqual(role, "builder")
                    self.assertIn("builder-first policy", reason)
                    self.assertFalse(stop)

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

                    role, reason, stop = module.choose_next(target, self.conveyor_state(module), 3600, 2)

                    self.assertEqual("integrator", role)
                    self.assertIn("duplicate builder deferred patches need triage", reason)
                    self.assertFalse(stop)

    def test_missing_baseline_ledger_routes_to_integrator_preflight(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.write_text(target, ".agentic/verification_commands.txt", "python3 -m pytest\n")

                    role, reason, stop = module.choose_next(target, self.conveyor_state(module), 3600, 2)

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

                    role, reason, stop = module.choose_next(target, self.conveyor_state(module), 3600, 2)

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

                    role, reason, stop = module.choose_next(target, state, 3600, 2)

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

                    role, reason, stop = module.choose_next(target, state, 3600, 2)

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

                    role, reason, stop = module.choose_next(target, state, 3600, 2)

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

                    role, reason, stop = module.choose_next(target, state, 3600, 2)

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

                    role, reason, stop = module.choose_next(target, self.conveyor_state(module), 3600, 2)

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

                    role, reason, stop = module.choose_next(target, self.conveyor_state(module), 3600, 2)

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

                    role, reason, stop = module.choose_next(target, self.conveyor_state(module), 3600, 2)

                    self.assertEqual("planner", role)
                    self.assertIn("replace-from-current-HEAD", reason)
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

    def test_sigterm_during_idle_sleep_releases_scheduler_lock(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
