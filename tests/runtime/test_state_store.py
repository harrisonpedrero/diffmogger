from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from diffmogger.conveyor.state import load_state, write_state
from diffmogger.runtime.state_store import (
    CONVEYOR_PROJECTION_NAME,
    RUNNER_PROJECTION_NAME,
    canonical_state_brief_path_for_target,
    load_conveyor_state,
    load_runner_state,
    render_canonical_state_brief,
    state_snapshot,
    validate_state_database,
    write_canonical_state_brief,
    write_runner_state,
)


class StateStoreTests(unittest.TestCase):
    def test_initializes_sqlite_and_generated_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            projection_path = target / "target" / "automation_conveyor_state.json"

            state = load_conveyor_state(projection_path)
            snapshot = state_snapshot(target)

            self.assertEqual(1, state["schema_version"])
            self.assertEqual("sqlite", snapshot["authority"])
            self.assertEqual("ok", snapshot["status"])
            self.assertGreaterEqual(snapshot["counts"]["events"], 1)
            self.assertTrue(Path(snapshot["database"]["path"]).exists())
            self.assertTrue(projection_path.exists())
            projected = json.loads(projection_path.read_text(encoding="utf-8"))
            self.assertEqual("sqlite", projected["canonical_state"]["authority"])
            self.assertEqual(CONVEYOR_PROJECTION_NAME, projected["canonical_state"]["projection"])

    def test_legacy_json_is_imported_once_as_compatibility_migration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            projection_path = target / "target" / "automation_conveyor_state.json"
            projection_path.parent.mkdir(parents=True, exist_ok=True)
            projection_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "cycles": 7,
                        "role_counts": {"builder": 3},
                        "history": [{"role": "builder", "exit_code": 0}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            imported = load_conveyor_state(projection_path)
            first_snapshot = state_snapshot(target)
            loaded_again = load_conveyor_state(projection_path)
            second_snapshot = state_snapshot(target)

            self.assertEqual(7, imported["cycles"])
            self.assertEqual(7, loaded_again["cycles"])
            self.assertEqual(first_snapshot["counts"]["events"], second_snapshot["counts"]["events"])
            self.assertEqual("compatibility.legacy_conveyor_json_imported", first_snapshot["last_event"]["event_type"])

    def test_conveyor_write_state_materializes_typed_next_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            projection_path = Path(tmp) / "target" / "automation_conveyor_state.json"
            state = load_state(projection_path)
            state["decision_queue"] = [
                {"role": "builder", "state": "next", "reason": "builder lane is next runnable work"},
                {"role": "hardener", "state": "standby", "reason": "verify recently changed work"},
            ]

            write_state(
                projection_path,
                state,
                event_type="test.decision_recorded",
                actor_role="test",
                phase="decision",
            )
            snapshot = state_snapshot(Path(tmp))
            validation = validate_state_database(Path(tmp))

            self.assertEqual("pass", validation["status"])
            self.assertEqual(2, len(snapshot["next_actions"]))
            self.assertEqual("builder", snapshot["next_actions"][0]["owner_role"])
            self.assertEqual("test.decision_recorded", snapshot["last_event"]["event_type"])

            db = sqlite3.connect(snapshot["database"]["path"])
            try:
                event_count = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                projection_count = db.execute("SELECT COUNT(*) FROM projections").fetchone()[0]
            finally:
                db.close()
            self.assertGreaterEqual(event_count, 2)
            self.assertEqual(1, projection_count)

    def test_runner_state_is_sqlite_backed_with_json_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            projection_path = target / "target" / "automation_runner.json"

            write_runner_state(
                projection_path,
                {"schema_version": 1, "state": "running", "pid": 1234, "started_at": "2026-05-03T22:30:00+00:00"},
            )
            loaded = load_runner_state(projection_path)
            projected = json.loads(projection_path.read_text(encoding="utf-8"))
            snapshot = state_snapshot(target)

            self.assertEqual("running", loaded["state"])
            self.assertEqual("sqlite", projected["canonical_state"]["authority"])
            self.assertEqual(RUNNER_PROJECTION_NAME, projected["canonical_state"]["projection"])
            self.assertGreaterEqual(snapshot["counts"]["events"], 2)

    def test_canonical_state_brief_is_bounded_markdown_view(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            projection_path = target / "target" / "automation_conveyor_state.json"
            state = load_state(projection_path)
            state["decision_queue"] = [
                {"role": "builder", "state": "next", "reason": "build the next small reusable increment"}
            ]
            write_state(projection_path, state, event_type="test.brief_decision")

            result = write_canonical_state_brief(target)
            brief_path = canonical_state_brief_path_for_target(target)
            markdown = brief_path.read_text(encoding="utf-8")

            self.assertEqual(str(brief_path), result["path"])
            self.assertIn("# Canonical State Brief", markdown)
            self.assertIn("authority: SQLite orchestration state is canonical", markdown)
            self.assertIn("target/orchestration.sqlite3", markdown)
            self.assertIn("builder: next", markdown)
            self.assertNotIn(str(target), markdown)

            rendered = render_canonical_state_brief(state_snapshot(target), target=target)
            self.assertIn("## Projection Freshness", rendered)


if __name__ == "__main__":
    unittest.main()
