from __future__ import annotations

import importlib.util
import tempfile
import textwrap
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


if __name__ == "__main__":
    unittest.main()
