from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Iterator


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from diffmogger.runtime.state_store import (
    GRAPH_SNAPSHOT_RETENTION_LIMIT,
    acquire_resource_lease,
    connect,
    database_path_for_target,
    ensure_codebase_graph_conn,
    expire_stale_leases,
    list_conflicting_leases,
    prune_graph_snapshots_conn,
    refresh_codebase_graph,
    refresh_codebase_graph_changed_file,
    refresh_capability_manifest_conn,
    release_resource_lease,
    state_snapshot,
    write_canonical_state_brief,
    write_ticket_run_state,
)


def write_text(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@contextmanager
def connect_graph(target: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(database_path_for_target(target))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def ensure_codebase_graph(target: Path) -> dict[str, object]:
    with closing(connect(database_path_for_target(target))) as conn:
        capability = refresh_capability_manifest_conn(conn, target)
        return ensure_codebase_graph_conn(conn, target, capability=capability)


def graph_snapshot_count(target: Path) -> int:
    with connect_graph(target) as conn:
        return int(
            conn.execute(
                "SELECT COUNT(*) AS count FROM graph_snapshots WHERE graph_namespace = 'codebase'"
            ).fetchone()["count"]
        )


def execution_group_count(target: Path) -> int:
    with connect_graph(target) as conn:
        return int(conn.execute("SELECT COUNT(*) AS count FROM execution_groups").fetchone()["count"])


def file_node_paths(target: Path, snapshot_id: str) -> list[str]:
    with connect_graph(target) as conn:
        rows = conn.execute(
            """
            SELECT path
            FROM graph_nodes
            WHERE snapshot_id = ?
              AND graph_namespace = 'codebase'
              AND kind IN ('file', 'test_file', 'config_file', 'doc_file', 'lockfile')
            ORDER BY path
            """,
            (snapshot_id,),
        ).fetchall()
    return [str(row["path"]) for row in rows]


def command_values(target: Path, snapshot_id: str) -> list[str]:
    with connect_graph(target) as conn:
        rows = conn.execute(
            """
            SELECT fact_value
            FROM graph_node_facts
            WHERE snapshot_id = ?
              AND graph_namespace = 'codebase'
              AND fact_key = 'command'
            ORDER BY fact_value
            """,
            (snapshot_id,),
        ).fetchall()
    return [str(row["fact_value"]) for row in rows]


def import_edges(target: Path, snapshot_id: str) -> list[tuple[str, str, str]]:
    with connect_graph(target) as conn:
        rows = conn.execute(
            """
            SELECT source_node.path AS source_path, target_node.path AS target_path, edge.kind
            FROM graph_edges edge
            JOIN graph_nodes source_node
              ON source_node.snapshot_id = edge.snapshot_id
             AND source_node.node_id = edge.from_node_id
            JOIN graph_nodes target_node
              ON target_node.snapshot_id = edge.snapshot_id
             AND target_node.node_id = edge.to_node_id
            WHERE edge.snapshot_id = ? AND edge.kind = 'imports'
            ORDER BY source_node.path, target_node.path
            """,
            (snapshot_id,),
        ).fetchall()
    return [(row["source_path"], row["target_path"], row["kind"]) for row in rows]


def task_edges(target: Path, snapshot_id: str, edge_kind: str) -> list[tuple[str, str, str]]:
    with connect_graph(target) as conn:
        rows = conn.execute(
            """
            SELECT source_node.metadata_json AS source_metadata,
                   target_node.metadata_json AS target_metadata,
                   edge.kind
            FROM graph_edges edge
            JOIN graph_nodes source_node
              ON source_node.snapshot_id = edge.snapshot_id
             AND source_node.node_id = edge.from_node_id
            JOIN graph_nodes target_node
              ON target_node.snapshot_id = edge.snapshot_id
             AND target_node.node_id = edge.to_node_id
            WHERE edge.snapshot_id = ?
              AND edge.graph_namespace = 'task'
              AND edge.kind = ?
            ORDER BY source_node.name, target_node.name
            """,
            (snapshot_id, edge_kind),
        ).fetchall()
    edges: list[tuple[str, str, str]] = []
    for row in rows:
        source_metadata = json.loads(row["source_metadata"] or "{}")
        target_metadata = json.loads(row["target_metadata"] or "{}")
        source_id = source_metadata.get("ticket_id") or source_metadata.get("work_item_id") or source_metadata.get("run_id")
        target_id = target_metadata.get("ticket_id") or target_metadata.get("work_item_id") or target_metadata.get("run_id")
        edges.append((str(source_id or ""), str(target_id or ""), row["kind"]))
    return edges


def impact_edges(target: Path, snapshot_id: str, edge_kind: str) -> list[tuple[str, str, str, float, str]]:
    with connect_graph(target) as conn:
        rows = conn.execute(
            """
            SELECT source_node.metadata_json AS source_metadata,
                   target_node.path AS target_path,
                   target_node.name AS target_name,
                   edge.kind,
                   edge.metadata_json AS edge_metadata
            FROM graph_edges edge
            JOIN graph_nodes source_node
              ON source_node.snapshot_id = edge.snapshot_id
             AND source_node.node_id = edge.from_node_id
            JOIN graph_nodes target_node
              ON target_node.snapshot_id = edge.snapshot_id
             AND target_node.node_id = edge.to_node_id
            WHERE edge.snapshot_id = ?
              AND edge.graph_namespace = 'impact'
              AND edge.kind = ?
            ORDER BY source_node.name, target_node.path, target_node.name
            """,
            (snapshot_id, edge_kind),
        ).fetchall()
    edges: list[tuple[str, str, str, float, str]] = []
    for row in rows:
        source_metadata = json.loads(row["source_metadata"] or "{}")
        edge_metadata = json.loads(row["edge_metadata"] or "{}")
        source_id = source_metadata.get("ticket_id") or source_metadata.get("work_item_id") or source_metadata.get("run_id")
        target = row["target_path"] or row["target_name"]
        edges.append(
            (
                str(source_id or ""),
                str(target or ""),
                row["kind"],
                float(edge_metadata.get("confidence") or 0),
                str(edge_metadata.get("reason") or ""),
            )
        )
    return edges


def context_item_by_path(snapshot: dict[str, object], path: str) -> dict[str, object]:
    pack = snapshot.get("context_pack_preview") if isinstance(snapshot.get("context_pack_preview"), dict) else {}
    for item in pack.get("items", []) if isinstance(pack.get("items"), list) else []:
        if isinstance(item, dict) and item.get("path") == path:
            return item
    raise AssertionError(f"context item not found: {path}")


class CodebaseGraphTests(unittest.TestCase):
    def test_ensure_discovers_file_added_after_initial_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/app.py", "def main():\n    return 1\n")

            first = ensure_codebase_graph(target)
            write_text(target, "src/utils.py", "VALUE = 2\n")
            second = ensure_codebase_graph(target)

            self.assertNotEqual(first["latest_snapshot_id"], second["latest_snapshot_id"])
            self.assertEqual("full", second["graph_refresh_mode"])
            self.assertEqual(1, second["graph_inventory_added_count"])
            self.assertTrue(second["graph_inventory_changed"])
            self.assertEqual(2, second["indexed_file_count"])
            self.assertEqual(["src/app.py", "src/utils.py"], file_node_paths(target, str(second["latest_snapshot_id"])))

    def test_ensure_removes_deleted_file_from_active_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/app.py", "def main():\n    return 1\n")
            deleted = write_text(target, "src/obsolete.py", "OLD = True\n")

            first = ensure_codebase_graph(target)
            deleted.unlink()
            second = ensure_codebase_graph(target)

            self.assertNotEqual(first["latest_snapshot_id"], second["latest_snapshot_id"])
            self.assertEqual("full", second["graph_refresh_mode"])
            self.assertEqual(1, second["graph_inventory_deleted_count"])
            self.assertTrue(second["graph_inventory_changed"])
            self.assertEqual(1, second["indexed_file_count"])
            self.assertEqual(["src/app.py"], file_node_paths(target, str(second["latest_snapshot_id"])))

    def test_repeated_ensure_without_repo_changes_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/app.py", "def main():\n    return 1\n")
            write_text(target, "README.md", "# Demo\n")

            first = ensure_codebase_graph(target)
            second = ensure_codebase_graph(target)

            self.assertEqual(first["latest_snapshot_id"], second["latest_snapshot_id"])
            self.assertEqual(1, graph_snapshot_count(target))
            self.assertEqual(2, second["indexed_file_count"])
            self.assertEqual("staleness", second["graph_refresh_mode"])
            self.assertFalse(second["graph_inventory_changed"])

    def test_ensure_partially_reindexes_modified_known_file_without_rebuilding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/__init__.py", "")
            write_text(target, "src/one.py", "VALUE = 1\n")
            write_text(target, "src/two.py", "VALUE = 2\n")
            write_text(target, "src/app.py", "import src.one\n")

            first = ensure_codebase_graph(target)
            self.assertIn(("src/app.py", "src/one.py", "imports"), import_edges(target, str(first["latest_snapshot_id"])))

            write_text(target, "src/app.py", "import src.two\n")
            second = ensure_codebase_graph(target)

            self.assertEqual(first["latest_snapshot_id"], second["latest_snapshot_id"])
            self.assertEqual("partial", second["graph_refresh_mode"])
            self.assertEqual(0, second["stale_node_count"])
            self.assertEqual(1, graph_snapshot_count(target))
            edges = import_edges(target, str(second["latest_snapshot_id"]))
            self.assertNotIn(("src/app.py", "src/one.py", "imports"), edges)
            self.assertIn(("src/app.py", "src/two.py", "imports"), edges)
            with connect_graph(target) as conn:
                stale = conn.execute(
                    """
                    SELECT is_stale
                    FROM graph_nodes
                    WHERE snapshot_id = ? AND path = 'src/app.py'
                    """,
                    (second["latest_snapshot_id"],),
                ).fetchone()["is_stale"]
            self.assertEqual(0, stale)

    def test_simple_repo_indexes_file_and_directory_nodes_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/app.py", "def main():\n    return 1\n")
            write_text(target, "README.md", "# Demo\n")

            first = refresh_codebase_graph(target)
            second = refresh_codebase_graph(target)

            self.assertEqual(first["latest_snapshot_id"], second["latest_snapshot_id"])
            self.assertEqual(2, second["indexed_file_count"])
            self.assertEqual(1, second["node_counts"]["file"])
            self.assertEqual(1, second["node_counts"]["doc_file"])
            self.assertGreaterEqual(second["node_counts"]["directory"], 2)

            with connect_graph(target) as conn:
                snapshot_count = conn.execute("SELECT COUNT(*) AS count FROM graph_snapshots").fetchone()["count"]
                rows = conn.execute(
                    "SELECT kind, path FROM graph_nodes WHERE snapshot_id = ? ORDER BY kind, path",
                    (second["latest_snapshot_id"],),
                ).fetchall()

            self.assertEqual(1, snapshot_count)
            self.assertIn(("directory", "src"), [(row["kind"], row["path"]) for row in rows])
            self.assertIn(("file", "src/app.py"), [(row["kind"], row["path"]) for row in rows])

    def test_package_json_creates_command_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(
                target,
                "package.json",
                json.dumps({"scripts": {"test": "vitest run", "lint": "eslint .", "dev": "vite --host"}}),
            )

            summary = refresh_codebase_graph(target)

            self.assertEqual(3, summary["command_node_count"])
            with connect_graph(target) as conn:
                commands = [
                    row["fact_value"]
                    for row in conn.execute(
                        """
                        SELECT fact_value
                        FROM graph_node_facts
                        WHERE snapshot_id = ? AND fact_key = 'command'
                        ORDER BY fact_value
                        """,
                        (summary["latest_snapshot_id"],),
                    ).fetchall()
                ]

            self.assertEqual(["npm run dev", "npm run lint", "npm run test"], commands)

    def test_package_json_edit_triggers_full_refresh_and_updates_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "package.json", json.dumps({"scripts": {"test": "node --test"}}))

            first = ensure_codebase_graph(target)
            write_text(
                target,
                "package.json",
                json.dumps({"scripts": {"test": "node --test", "lint": "eslint ."}}),
            )
            second = ensure_codebase_graph(target)

            self.assertNotEqual(first["latest_snapshot_id"], second["latest_snapshot_id"])
            self.assertEqual("full", second["graph_refresh_mode"])
            self.assertEqual(2, second["command_node_count"])
            self.assertEqual(["npm run lint", "npm run test"], command_values(target, str(second["latest_snapshot_id"])))

    def test_repeated_state_snapshot_without_changes_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/app.py", "def main():\n    return 1\n")

            first = state_snapshot(target)
            second = state_snapshot(target)

            self.assertEqual(first["latest_graph_snapshot"]["snapshot_id"], second["latest_graph_snapshot"]["snapshot_id"])
            self.assertEqual(1, graph_snapshot_count(target))
            self.assertEqual("staleness", second["graph_refresh_mode"])
            self.assertFalse(second["graph_inventory_changed"])
            self.assertEqual(0, second["graph_inventory_added_count"])
            self.assertEqual(0, second["graph_inventory_deleted_count"])
            self.assertEqual(0, second["graph_inventory_structural_count"])

    def test_derived_graph_snapshot_pruning_keeps_recent_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            with closing(connect(database_path_for_target(target))) as conn:
                with conn:
                    for index in range(GRAPH_SNAPSHOT_RETENTION_LIMIT + 3):
                        snapshot_id = f"snapshot:{index:02d}"
                        conn.execute(
                            """
                            INSERT INTO graph_snapshots(
                                snapshot_id, graph_namespace, repo_root, generated_at, head_commit,
                                dirty_tracked_file_count, dirty_tracked_files_digest, indexed_file_count,
                                directory_node_count, command_node_count, test_node_count, stale_node_count,
                                digest, payload_json
                            )
                            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                snapshot_id,
                                "impact",
                                str(target),
                                f"2026-01-01T00:00:{index:02d}+00:00",
                                "",
                                0,
                                "",
                                0,
                                0,
                                0,
                                0,
                                0,
                                f"digest:{index:02d}",
                                "{}",
                            ),
                        )
                        conn.execute(
                            """
                            INSERT INTO graph_nodes(
                                snapshot_id, node_id, graph_namespace, kind, path, name, digest, is_stale, metadata_json
                            )
                            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (snapshot_id, f"node:{index:02d}", "impact", "ticket", "", f"Node {index}", "", 0, "{}"),
                        )

                    pruned = prune_graph_snapshots_conn(conn, "impact")

                snapshots = conn.execute(
                    "SELECT snapshot_id FROM graph_snapshots WHERE graph_namespace = 'impact' ORDER BY generated_at"
                ).fetchall()
                node_count = conn.execute(
                    "SELECT COUNT(*) AS count FROM graph_nodes WHERE graph_namespace = 'impact'"
                ).fetchone()["count"]

            self.assertEqual(3, pruned)
            self.assertEqual(GRAPH_SNAPSHOT_RETENTION_LIMIT, len(snapshots))
            self.assertEqual(GRAPH_SNAPSHOT_RETENTION_LIMIT, node_count)
            self.assertEqual("snapshot:03", snapshots[0]["snapshot_id"])

    def test_test_file_naming_creates_likely_tests_edge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/widget.py", "def render():\n    return 'ok'\n")
            write_text(target, "tests/test_widget.py", "from src.widget import render\n")

            summary = refresh_codebase_graph(target)

            with connect_graph(target) as conn:
                rows = conn.execute(
                    """
                    SELECT test_node.path AS test_path, source_node.path AS source_path
                    FROM graph_edges edge
                    JOIN graph_nodes test_node
                      ON test_node.snapshot_id = edge.snapshot_id
                     AND test_node.node_id = edge.from_node_id
                    JOIN graph_nodes source_node
                      ON source_node.snapshot_id = edge.snapshot_id
                     AND source_node.node_id = edge.to_node_id
                    WHERE edge.snapshot_id = ? AND edge.kind = 'likely_tests'
                    """,
                    (summary["latest_snapshot_id"],),
                ).fetchall()

            self.assertEqual([("tests/test_widget.py", "src/widget.py")], [(row["test_path"], row["source_path"]) for row in rows])

    def test_state_snapshot_partially_refreshes_changed_known_source_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/app.py", "VERSION = 1\n")
            refresh_codebase_graph(target)

            write_text(target, "src/app.py", "VERSION = 2\n")
            snapshot = state_snapshot(target)

            self.assertEqual("partial", snapshot["graph_refresh_mode"])
            self.assertEqual(0, snapshot["stale_node_count"])
            with connect_graph(target) as conn:
                stale = conn.execute(
                    """
                    SELECT path, is_stale
                    FROM graph_nodes
                    WHERE snapshot_id = ? AND path = 'src/app.py'
                    """,
                    (snapshot["latest_graph_snapshot"]["snapshot_id"],),
                ).fetchone()

            self.assertIsNotNone(stale)
            self.assertEqual(0, stale["is_stale"])

    def test_state_snapshot_exposes_compact_graph_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/app.py", "SECRET_SOURCE_BODY = 'not in snapshot summary'\n")
            write_text(target, "tests/test_app.py", "def test_app():\n    assert True\n")
            write_text(target, "package.json", json.dumps({"scripts": {"test": "node --test"}}))

            snapshot = state_snapshot(target)
            summary = snapshot["codebase_graph_summary"]

            self.assertEqual("codebase", summary["graph_namespace"])
            self.assertTrue(summary["exists"])
            self.assertEqual(summary["indexed_file_count"], snapshot["indexed_file_count"])
            self.assertEqual(summary["command_node_count"], snapshot["command_node_count"])
            self.assertEqual(1, snapshot["test_node_count"])
            self.assertIn("latest_graph_snapshot", snapshot)
            self.assertEqual("full", snapshot["graph_refresh_mode"])
            self.assertTrue(snapshot["graph_inventory_digest"])
            self.assertEqual(snapshot["graph_inventory_digest"], summary["graph_inventory_digest"])
            self.assertIsInstance(snapshot["graph_inventory_changed"], bool)
            self.assertGreaterEqual(summary["indexed_path_count"], summary["indexed_file_count"])
            self.assertLessEqual(len(summary["indexed_path_sample"]), 24)
            self.assertNotIn("SECRET_SOURCE_BODY", json.dumps(summary, sort_keys=True))
            self.assertNotIn("SECRET_SOURCE_BODY", json.dumps(snapshot["latest_graph_snapshot"], sort_keys=True))
            self.assertNotIn("SECRET_SOURCE_BODY", json.dumps(snapshot, sort_keys=True))

    def test_python_local_import_creates_imports_edge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/__init__.py", "")
            write_text(target, "src/utils.py", "VALUE = 1\n")
            write_text(target, "src/app.py", "import src.utils\n")

            summary = refresh_codebase_graph(target)

            self.assertIn(("src/app.py", "src/utils.py", "imports"), import_edges(target, summary["latest_snapshot_id"]))
            with connect_graph(target) as conn:
                facts = {
                    row["fact_key"]: row["fact_value"]
                    for row in conn.execute(
                        """
                        SELECT fact_key, fact_value
                        FROM graph_edge_facts
                        WHERE snapshot_id = ?
                          AND edge_id IN (
                              SELECT edge.edge_id
                              FROM graph_edges edge
                              JOIN graph_nodes source_node
                                ON source_node.snapshot_id = edge.snapshot_id
                               AND source_node.node_id = edge.from_node_id
                              JOIN graph_nodes target_node
                                ON target_node.snapshot_id = edge.snapshot_id
                               AND target_node.node_id = edge.to_node_id
                              WHERE edge.kind = 'imports'
                                AND source_node.path = 'src/app.py'
                                AND target_node.path = 'src/utils.py'
                          )
                        """,
                        (summary["latest_snapshot_id"],),
                    ).fetchall()
                }

            self.assertEqual("python_ast_import", facts["source"])
            self.assertEqual("true", facts["resolved"])
            self.assertEqual("src.utils", facts["raw_import"])

    def test_js_ts_relative_import_creates_imports_edge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/helper.ts", "export const value = 1;\n")
            write_text(target, "src/app.ts", "import { value } from './helper';\n")

            summary = refresh_codebase_graph(target)

            self.assertIn(("src/app.ts", "src/helper.ts", "imports"), import_edges(target, summary["latest_snapshot_id"]))
            with connect_graph(target) as conn:
                source = conn.execute(
                    """
                    SELECT fact.fact_value
                    FROM graph_edge_facts fact
                    JOIN graph_edges edge
                      ON edge.snapshot_id = fact.snapshot_id
                     AND edge.edge_id = fact.edge_id
                    JOIN graph_nodes source_node
                      ON source_node.snapshot_id = edge.snapshot_id
                     AND source_node.node_id = edge.from_node_id
                    JOIN graph_nodes target_node
                      ON target_node.snapshot_id = edge.snapshot_id
                     AND target_node.node_id = edge.to_node_id
                    WHERE edge.snapshot_id = ?
                      AND edge.kind = 'imports'
                      AND source_node.path = 'src/app.ts'
                      AND target_node.path = 'src/helper.ts'
                      AND fact.fact_key = 'source'
                    """,
                    (summary["latest_snapshot_id"],),
                ).fetchone()["fact_value"]

            self.assertEqual("js_ts_import_regex", source)

    def test_unresolved_external_package_import_is_low_confidence_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/app.ts", "import React from 'react';\nconst _ = require('lodash');\n")

            summary = refresh_codebase_graph(target)

            with connect_graph(target) as conn:
                imports = conn.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM graph_edges
                    WHERE snapshot_id = ? AND kind = 'imports'
                    """,
                    (summary["latest_snapshot_id"],),
                ).fetchone()["count"]
                references = conn.execute(
                    """
                    SELECT module_node.name AS module_name, resolved.fact_value AS resolved, confidence.fact_value AS confidence
                    FROM graph_edges edge
                    JOIN graph_nodes source_node
                      ON source_node.snapshot_id = edge.snapshot_id
                     AND source_node.node_id = edge.from_node_id
                    JOIN graph_nodes module_node
                      ON module_node.snapshot_id = edge.snapshot_id
                     AND module_node.node_id = edge.to_node_id
                    JOIN graph_edge_facts resolved
                      ON resolved.snapshot_id = edge.snapshot_id
                     AND resolved.edge_id = edge.edge_id
                     AND resolved.fact_key = 'resolved'
                    JOIN graph_edge_facts confidence
                      ON confidence.snapshot_id = edge.snapshot_id
                     AND confidence.edge_id = edge.edge_id
                     AND confidence.fact_key = 'confidence'
                    WHERE edge.snapshot_id = ?
                      AND edge.kind = 'references'
                      AND source_node.path = 'src/app.ts'
                    ORDER BY module_node.name
                    """,
                    (summary["latest_snapshot_id"],),
                ).fetchall()

            self.assertEqual(0, imports)
            self.assertEqual(["lodash", "react"], [row["module_name"] for row in references])
            self.assertEqual({"false"}, {row["resolved"] for row in references})
            self.assertTrue(all(float(row["confidence"]) <= 0.3 for row in references))

    def test_changed_file_partial_reindex_replaces_stale_import_edges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/__init__.py", "")
            write_text(target, "src/one.py", "VALUE = 1\n")
            write_text(target, "src/two.py", "VALUE = 2\n")
            write_text(target, "src/app.py", "import src.one\n")
            summary = refresh_codebase_graph(target)

            self.assertIn(("src/app.py", "src/one.py", "imports"), import_edges(target, summary["latest_snapshot_id"]))

            write_text(target, "src/app.py", "import src.two\n")
            updated = refresh_codebase_graph_changed_file(target, "src/app.py")

            edges = import_edges(target, updated["latest_snapshot_id"])
            self.assertNotIn(("src/app.py", "src/one.py", "imports"), edges)
            self.assertIn(("src/app.py", "src/two.py", "imports"), edges)
            with connect_graph(target) as conn:
                stale = conn.execute(
                    """
                    SELECT is_stale
                    FROM graph_nodes
                    WHERE snapshot_id = ? AND path = 'src/app.py'
                    """,
                    (updated["latest_snapshot_id"],),
                ).fetchone()["is_stale"]
                raw_imports = [
                    row["fact_value"]
                    for row in conn.execute(
                        """
                        SELECT fact.fact_value
                        FROM graph_edge_facts fact
                        JOIN graph_edges edge
                          ON edge.snapshot_id = fact.snapshot_id
                         AND edge.edge_id = fact.edge_id
                        JOIN graph_nodes source_node
                          ON source_node.snapshot_id = edge.snapshot_id
                         AND source_node.node_id = edge.from_node_id
                        WHERE edge.snapshot_id = ?
                          AND edge.kind = 'imports'
                          AND source_node.path = 'src/app.py'
                          AND fact.fact_key = 'raw_import'
                        ORDER BY fact.fact_value
                        """,
                        (updated["latest_snapshot_id"],),
                    ).fetchall()
                ]

            self.assertEqual(0, stale)
            self.assertEqual(["src.two"], raw_imports)


class TaskGraphTests(unittest.TestCase):
    def write_ticket_run(self, target: Path, tickets: list[dict[str, object]]) -> None:
        write_ticket_run_state(
            target,
            {
                "run_id": "ticket-run",
                "halt_when_complete": True,
                "notify_on_complete": False,
                "tickets": tickets,
            },
            actor_role="test",
            event_type="ticket.run_test",
        )

    def test_ticket_dependency_creates_task_edge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.write_ticket_run(
                target,
                [
                    {"id": "T1", "summary": "Foundation", "status": "done"},
                    {"id": "T2", "summary": "Feature", "status": "pending", "depends_on": ["T1"]},
                ],
            )

            snapshot = state_snapshot(target)
            task_summary = snapshot["task_graph_summary"]

            self.assertEqual("task", task_summary["graph_namespace"])
            self.assertIn(("T2", "T1", "depends_on"), task_edges(target, task_summary["latest_snapshot_id"], "depends_on"))

    def test_dependency_ready_ticket_is_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.write_ticket_run(
                target,
                [
                    {"id": "T1", "summary": "Foundation", "status": "done"},
                    {"id": "T2", "summary": "Feature", "status": "pending", "depends_on": ["T1"]},
                ],
            )

            snapshot = state_snapshot(target)

            ready_ids = {node["id"] for node in snapshot["ready_task_nodes"]}
            blocked_ids = {node["id"] for node in snapshot["blocked_task_nodes"]}
            self.assertIn("T2", ready_ids)
            self.assertNotIn("T2", blocked_ids)

    def test_blocked_dependency_prevents_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.write_ticket_run(
                target,
                [
                    {"id": "T1", "summary": "Foundation", "status": "pending"},
                    {"id": "T2", "summary": "Feature", "status": "pending", "depends_on": ["T1"]},
                ],
            )

            snapshot = state_snapshot(target)

            ready_ids = {node["id"] for node in snapshot["ready_task_nodes"]}
            blocked = {node["id"]: node for node in snapshot["blocked_task_nodes"]}
            self.assertNotIn("T2", ready_ids)
            self.assertIn("T2", blocked)
            self.assertEqual("dependency", blocked["T2"]["blocked_reasons"][0]["kind"])

    def test_task_dependency_cycle_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.write_ticket_run(
                target,
                [
                    {"id": "T1", "summary": "One", "status": "pending", "depends_on": ["T2"]},
                    {"id": "T2", "summary": "Two", "status": "pending", "depends_on": ["T1"]},
                ],
            )

            snapshot = state_snapshot(target)

            cycles = snapshot["dependency_cycles"]
            self.assertEqual(1, len(cycles))
            self.assertEqual({"T1", "T2"}, set(cycles[0]["labels"]))

    def test_state_snapshot_exposes_compact_task_graph_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.write_ticket_run(
                target,
                [
                    {"id": "T1", "summary": "Tiny reusable task", "status": "pending"},
                    {"id": "T2", "summary": "Done prerequisite", "status": "done"},
                ],
            )

            snapshot = state_snapshot(target)
            summary = snapshot["task_graph_summary"]

            self.assertEqual("task", summary["graph_namespace"])
            self.assertTrue(summary["exists"])
            self.assertGreaterEqual(summary["node_counts"]["ticket"], 2)
            self.assertIn("ready_task_nodes", snapshot)
            self.assertIn("blocked_task_nodes", snapshot)
            self.assertIn("dependency_cycles", snapshot)
            self.assertLess(len(json.dumps(summary, sort_keys=True)), 4000)


class ImpactGraphTests(unittest.TestCase):
    def write_ticket_run(self, target: Path, tickets: list[dict[str, object]]) -> None:
        write_ticket_run_state(
            target,
            {
                "run_id": "ticket-run",
                "halt_when_complete": True,
                "notify_on_complete": False,
                "tickets": tickets,
            },
            actor_role="test",
            event_type="ticket.run_test",
        )

    def test_ticket_mentioning_path_creates_likely_touches_edge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "def login():\n    return True\n")
            self.write_ticket_run(
                target,
                [{"id": "T1", "summary": "Update src/auth.py login behavior", "status": "pending"}],
            )

            snapshot = state_snapshot(target)
            impact_summary = snapshot["impact_graph_summary"]
            edges = impact_edges(target, impact_summary["latest_snapshot_id"], "likely_touches")

            self.assertEqual("impact", impact_summary["graph_namespace"])
            self.assertTrue(any(edge[0] == "T1" and edge[1] == "src/auth.py" for edge in edges))
            self.assertTrue(any("path mention" in edge[4] and edge[3] >= 0.9 for edge in edges))

    def test_ticket_mentioning_auth_ranks_auth_files_before_unrelated_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth/session.py", "def login():\n    return True\n")
            write_text(target, "src/billing/invoice.py", "def total():\n    return 1\n")
            self.write_ticket_run(
                target,
                [{"id": "T1", "summary": "Improve auth login session handling", "status": "pending"}],
            )

            snapshot = state_snapshot(target)
            items = snapshot["context_pack_preview"]["items"]
            paths = [item.get("path") for item in items]

            self.assertTrue(paths)
            self.assertIn("auth", str(paths[0]))
            self.assertNotIn("src/billing/invoice.py", paths[:1])

    def test_context_pack_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            for index in range(20):
                write_text(target, f"src/auth/part_{index}.py", f"VALUE = {index}\n")
            self.write_ticket_run(
                target,
                [{"id": "T1", "summary": "Review auth module coverage", "status": "pending"}],
            )

            snapshot = state_snapshot(target)
            pack = snapshot["context_pack_preview"]

            self.assertTrue(pack["bounded"])
            self.assertLessEqual(pack["item_count"], pack["max_items"])
            self.assertLessEqual(len(pack["items"]), 12)

    def test_context_pack_omits_raw_source_contents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "SECRET_SOURCE_BODY = 'do not include me'\n")
            self.write_ticket_run(
                target,
                [{"id": "T1", "summary": "Update auth module", "status": "pending"}],
            )

            snapshot = state_snapshot(target)

            self.assertNotIn("SECRET_SOURCE_BODY", json.dumps(snapshot["context_pack_preview"], sort_keys=True))
            self.assertTrue(all(not item.get("raw_contents_included") for item in snapshot["context_pack_preview"]["items"]))

    def test_relevant_known_file_change_refreshes_context_without_stale_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "VERSION = 1\n")
            self.write_ticket_run(
                target,
                [{"id": "T1", "summary": "Update src/auth.py", "status": "pending"}],
            )
            state_snapshot(target)

            write_text(target, "src/auth.py", "VERSION = 2\n")
            snapshot = state_snapshot(target)
            pack = snapshot["context_pack_preview"]

            self.assertEqual("partial", snapshot["graph_refresh_mode"])
            self.assertFalse(snapshot["stale_context_warning"])
            self.assertFalse(pack["stale_context_warning"])
            self.assertTrue(any(item.get("path") == "src/auth.py" and not item.get("is_stale") for item in pack["items"]))


class ResourceLeaseTests(unittest.TestCase):
    def write_ticket_run(self, target: Path, tickets: list[dict[str, object]]) -> None:
        write_ticket_run_state(
            target,
            {
                "run_id": "ticket-run",
                "halt_when_complete": True,
                "notify_on_complete": False,
                "tickets": tickets,
            },
            actor_role="test",
            event_type="ticket.run_test",
        )

    def test_file_lease_blocks_same_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "def login():\n    return True\n")
            self.write_ticket_run(target, [{"id": "T1", "summary": "Update src/auth.py", "status": "pending"}])
            snapshot = state_snapshot(target)
            auth_item = context_item_by_path(snapshot, "src/auth.py")

            acquired = acquire_resource_lease(
                target,
                task_id="T1",
                owner_role="builder",
                run_id="run-1",
                scope_kind="file",
                scope_node_id=str(auth_item["node_id"]),
            )
            conflicts = list_conflicting_leases(
                target,
                task_id="T2",
                owner_role="hardener",
                run_id="run-2",
                scope_kind="file",
                scope_node_id=str(auth_item["node_id"]),
            )

            self.assertTrue(acquired["acquired"])
            self.assertEqual(1, len(conflicts))
            self.assertEqual("same graph node", conflicts[0]["reason"])

    def test_directory_lease_blocks_child_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth/login.py", "LOGIN = True\n")
            write_text(target, "src/auth/session.py", "SESSION = True\n")
            write_text(target, "src/auth/tokens.py", "TOKEN = True\n")
            self.write_ticket_run(target, [{"id": "T1", "summary": "Update auth module", "status": "pending"}])
            snapshot = state_snapshot(target)
            suggestions = snapshot["lease_suggestions_for_next_action"]
            directory = next(item for item in suggestions if item["scope_kind"] == "directory" and item["path"] == "src/auth")
            child = context_item_by_path(snapshot, "src/auth/login.py")

            acquired = acquire_resource_lease(
                target,
                task_id="T1",
                owner_role="builder",
                run_id="run-1",
                scope_kind="directory",
                scope_node_id=str(directory["scope_node_id"]),
            )
            conflicts = list_conflicting_leases(
                target,
                task_id="T2",
                owner_role="hardener",
                run_id="run-2",
                scope_kind="file",
                scope_node_id=str(child["node_id"]),
            )

            self.assertTrue(acquired["acquired"])
            self.assertEqual(1, len(conflicts))
            self.assertEqual("directory contains leased file", conflicts[0]["reason"])

    def test_released_lease_no_longer_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "VALUE = 1\n")
            self.write_ticket_run(target, [{"id": "T1", "summary": "Update src/auth.py", "status": "pending"}])
            snapshot = state_snapshot(target)
            auth_item = context_item_by_path(snapshot, "src/auth.py")
            acquired = acquire_resource_lease(
                target,
                task_id="T1",
                owner_role="builder",
                scope_kind="file",
                scope_node_id=str(auth_item["node_id"]),
            )

            released = release_resource_lease(target, acquired["lease"]["lease_id"])
            conflicts = list_conflicting_leases(
                target,
                task_id="T2",
                owner_role="hardener",
                scope_kind="file",
                scope_node_id=str(auth_item["node_id"]),
            )

            self.assertTrue(released["released"])
            self.assertEqual([], conflicts)

    def test_expired_lease_no_longer_blocks_after_expiry_helper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "VALUE = 1\n")
            self.write_ticket_run(target, [{"id": "T1", "summary": "Update src/auth.py", "status": "pending"}])
            snapshot = state_snapshot(target)
            auth_item = context_item_by_path(snapshot, "src/auth.py")
            acquire_resource_lease(
                target,
                task_id="T1",
                owner_role="builder",
                scope_kind="file",
                scope_node_id=str(auth_item["node_id"]),
                expires_at="2000-01-01T00:00:00+00:00",
            )

            expired = expire_stale_leases(target, now="2000-01-01T00:00:01+00:00")
            conflicts = list_conflicting_leases(
                target,
                task_id="T2",
                owner_role="hardener",
                scope_kind="file",
                scope_node_id=str(auth_item["node_id"]),
            )

            self.assertEqual(1, expired)
            self.assertEqual([], conflicts)

    def test_unknown_impact_does_not_over_lock_repo_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "VALUE = 1\n")
            self.write_ticket_run(target, [{"id": "T1", "summary": "Clarify project roadmap", "status": "pending"}])

            snapshot = state_snapshot(target)
            repo_suggestions = [item for item in snapshot["lease_suggestions_for_next_action"] if item["scope_kind"] == "repo"]

            self.assertTrue(repo_suggestions)
            self.assertTrue(all(not item["recommended"] for item in repo_suggestions))
            self.assertEqual([], snapshot["active_leases"])


class ParallelExecutionPlannerTests(unittest.TestCase):
    def write_ticket_run(self, target: Path, tickets: list[dict[str, object]]) -> None:
        write_ticket_run_state(
            target,
            {
                "run_id": "ticket-run",
                "halt_when_complete": True,
                "notify_on_complete": False,
                "tickets": tickets,
            },
            actor_role="test",
            event_type="ticket.run_test",
        )

    def grouped_task_ids(self, snapshot: dict[str, object]) -> list[set[str]]:
        groups = snapshot.get("proposed_execution_groups") if isinstance(snapshot.get("proposed_execution_groups"), list) else []
        grouped: list[set[str]] = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            items = group.get("items") if isinstance(group.get("items"), list) else []
            grouped.append({str(item.get("task_id") or "") for item in items if isinstance(item, dict)})
        return grouped

    def blocked_by_task(self, snapshot: dict[str, object]) -> dict[str, dict[str, object]]:
        blocked = snapshot.get("blocked_parallel_candidates") if isinstance(snapshot.get("blocked_parallel_candidates"), list) else []
        return {
            str(item.get("task_id") or ""): item
            for item in blocked
            if isinstance(item, dict) and str(item.get("task_id") or "")
        }

    def test_disjoint_write_tasks_share_proposed_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "AUTH = True\n")
            write_text(target, "src/billing.py", "BILLING = True\n")
            self.write_ticket_run(
                target,
                [
                    {"id": "T1", "summary": "Update src/auth.py", "status": "pending"},
                    {"id": "T2", "summary": "Update src/billing.py", "status": "pending"},
                ],
            )

            snapshot = state_snapshot(target)

            self.assertIn({"T1", "T2"}, self.grouped_task_ids(snapshot))
            self.assertEqual(1, snapshot["parallelization_summary"]["group_count"])
            group = snapshot["proposed_execution_groups"][0]
            self.assertEqual("dry_run", group["mode"])
            self.assertEqual("write_workers", group["payload"]["execution_mode"])
            self.assertTrue(group["execution_group_id"].startswith("execution-group:"))
            self.assertTrue(all(item["item_id"].startswith("execution-group-item:") for item in group["items"]))

    def test_overlapping_file_impact_prevents_parallel_grouping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "AUTH = True\n")
            self.write_ticket_run(
                target,
                [
                    {"id": "T1", "summary": "Update src/auth.py login", "status": "pending"},
                    {"id": "T2", "summary": "Update src/auth.py session", "status": "pending"},
                ],
            )

            snapshot = state_snapshot(target)
            grouped = self.grouped_task_ids(snapshot)
            blocked = self.blocked_by_task(snapshot)

            self.assertFalse(any({"T1", "T2"}.issubset(group) for group in grouped))
            self.assertEqual(0, snapshot["parallelization_summary"]["group_count"])
            self.assertTrue(any(item.get("reason_kind") == "write_surface_overlap" for item in blocked.values()), blocked)

    def test_read_only_tasks_can_group_with_overlapping_read_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "AUTH = True\n")
            self.write_ticket_run(
                target,
                [
                    {
                        "id": "T1",
                        "summary": "Inspect src/auth.py for follow-up planning",
                        "status": "pending",
                        "action_kind": "read_only_analysis",
                        "execution_mode": "read_only",
                    },
                    {
                        "id": "T2",
                        "summary": "Review src/auth.py test context",
                        "status": "pending",
                        "action_kind": "read_only_context_review",
                        "execution_mode": "read_only",
                    },
                ],
            )

            snapshot = state_snapshot(target)

            self.assertIn({"T1", "T2"}, self.grouped_task_ids(snapshot))
            self.assertEqual("dry_run", snapshot["proposed_execution_groups"][0]["mode"])
            self.assertEqual("read_only", snapshot["proposed_execution_groups"][0]["payload"]["execution_mode"])

    def test_integration_task_is_not_grouped_with_write_workers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "AUTH = True\n")
            write_text(target, "src/billing.py", "BILLING = True\n")
            self.write_ticket_run(
                target,
                [
                    {
                        "id": "T1",
                        "summary": "Integrate src/auth.py queued patch",
                        "status": "pending",
                        "owner_role": "integrator",
                        "action_kind": "integrate_queued_patch",
                    },
                    {"id": "T2", "summary": "Update src/billing.py", "status": "pending"},
                ],
            )

            snapshot = state_snapshot(target)
            blocked = self.blocked_by_task(snapshot)

            self.assertNotIn({"T1", "T2"}, self.grouped_task_ids(snapshot))
            self.assertEqual("integration_serialized", blocked["T1"]["reason_kind"])

    def test_task_with_pending_approval_is_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "AUTH = True\n")
            write_text(target, "src/billing.py", "BILLING = True\n")
            self.write_ticket_run(
                target,
                [
                    {
                        "id": "T1",
                        "summary": "Update src/auth.py protected behavior",
                        "status": "pending",
                        "requires_approval": True,
                        "approval_status": "pending",
                    },
                    {"id": "T2", "summary": "Update src/billing.py", "status": "pending"},
                ],
            )

            snapshot = state_snapshot(target)
            blocked = self.blocked_by_task(snapshot)

            self.assertEqual("pending_approval", blocked["T1"]["reason_kind"])
            self.assertFalse(any("T1" in group for group in self.grouped_task_ids(snapshot)))

    def test_unknown_impact_write_task_is_excluded_from_write_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "AUTH = True\n")
            self.write_ticket_run(target, [{"id": "T1", "summary": "Implement safer defaults", "status": "pending"}])

            snapshot = state_snapshot(target)
            blocked = self.blocked_by_task(snapshot)

            self.assertEqual([], snapshot["proposed_execution_groups"])
            self.assertEqual("unknown_impact_write", blocked["T1"]["reason_kind"])

    def test_parallel_dry_run_snapshot_is_compact_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "SECRET_SOURCE_BODY = 'hidden'\n")
            write_text(target, "src/billing.py", "BILLING = True\n")
            self.write_ticket_run(
                target,
                [
                    {"id": "T1", "summary": "Update src/auth.py", "status": "pending"},
                    {"id": "T2", "summary": "Update src/billing.py", "status": "pending"},
                ],
            )

            first = state_snapshot(target)
            first_count = execution_group_count(target)
            second = state_snapshot(target)
            brief = write_canonical_state_brief(target)
            markdown = Path(brief["path"]).read_text(encoding="utf-8")

            self.assertEqual(
                [group["execution_group_id"] for group in first["proposed_execution_groups"]],
                [group["execution_group_id"] for group in second["proposed_execution_groups"]],
            )
            self.assertEqual(first_count, execution_group_count(target))
            self.assertIn("scheduler_parallel_dry_run", second)
            self.assertIn("proposed_execution_groups", second)
            self.assertIn("blocked_parallel_candidates", second)
            self.assertIn("## Parallel Execution Dry Run", markdown)
            self.assertIn("proposed_group", markdown)
            self.assertIn("context_preview", markdown)
            self.assertNotIn("SECRET_SOURCE_BODY", json.dumps(second["scheduler_parallel_dry_run"], sort_keys=True))


if __name__ == "__main__":
    unittest.main()
