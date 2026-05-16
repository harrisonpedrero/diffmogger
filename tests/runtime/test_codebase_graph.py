from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Iterator
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from diffmogger.runtime import state_store as state_store_module
from diffmogger.runtime.state_store import (
    GRAPH_SNAPSHOT_RETENTION_LIMIT,
    acquire_resource_lease,
    codebase_graph_summary,
    code_intelligence_summary,
    connect,
    database_path_for_target,
    ensure_codebase_graph_conn,
    expire_stale_leases,
    list_conflicting_leases,
    prune_graph_snapshots_conn,
    refresh_impact_graph_conn,
    refresh_codebase_graph,
    refresh_codebase_graph_changed_file,
    refresh_codebase_graph_staleness_conn,
    refresh_capability_manifest_conn,
    refresh_task_graph_conn,
    record_scope_evidence_from_report_text_conn,
    refresh_code_intelligence_facts_conn,
    render_canonical_state_brief,
    scope_evidence_records_conn,
    release_resource_lease,
    state_snapshot,
    upsert_execution_dag_node,
    write_canonical_state_brief,
    write_ticket_run_state,
)
from diffmogger.runtime.code_intelligence import StaticCodeIntelligenceProvider


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


def codebase_reference_metadata(target: Path, snapshot_id: str) -> list[dict[str, object]]:
    with connect_graph(target) as conn:
        rows = conn.execute(
            """
            SELECT source_node.path AS source_path,
                   target_node.path AS target_path,
                   edge.metadata_json AS edge_metadata
            FROM graph_edges edge
            JOIN graph_nodes source_node
              ON source_node.snapshot_id = edge.snapshot_id
             AND source_node.node_id = edge.from_node_id
            JOIN graph_nodes target_node
              ON target_node.snapshot_id = edge.snapshot_id
             AND target_node.node_id = edge.to_node_id
            WHERE edge.snapshot_id = ?
              AND edge.graph_namespace = 'codebase'
              AND edge.kind = 'references'
              AND source_node.kind IN ('file', 'test_file', 'config_file', 'doc_file', 'lockfile')
              AND target_node.kind IN ('file', 'test_file', 'config_file', 'doc_file', 'lockfile')
            ORDER BY source_node.path, target_node.path
            """,
            (snapshot_id,),
        ).fetchall()
    items: list[dict[str, object]] = []
    for row in rows:
        metadata = json.loads(row["edge_metadata"] or "{}")
        items.append(
            {
                "source_path": row["source_path"],
                "target_path": row["target_path"],
                **metadata,
            }
        )
    return items


def symbol_nodes(target: Path, snapshot_id: str) -> list[dict[str, object]]:
    with connect_graph(target) as conn:
        rows = conn.execute(
            """
            SELECT node_id, path, name, metadata_json
            FROM graph_nodes
            WHERE snapshot_id = ?
              AND graph_namespace = 'codebase'
              AND kind = 'symbol'
            ORDER BY path, name
            """,
            (snapshot_id,),
        ).fetchall()
    symbols: list[dict[str, object]] = []
    for row in rows:
        metadata = json.loads(row["metadata_json"] or "{}")
        symbols.append({"node_id": row["node_id"], "path": row["path"], "name": row["name"], **metadata})
    return symbols


def module_nodes(target: Path, snapshot_id: str) -> list[dict[str, object]]:
    with connect_graph(target) as conn:
        rows = conn.execute(
            """
            SELECT name, metadata_json
            FROM graph_nodes
            WHERE snapshot_id = ?
              AND graph_namespace = 'codebase'
              AND kind = 'module'
            ORDER BY name
            """,
            (snapshot_id,),
        ).fetchall()
    modules: list[dict[str, object]] = []
    for row in rows:
        metadata = json.loads(row["metadata_json"] or "{}")
        modules.append({"name": row["name"], **metadata})
    return modules


def file_index_rows(target: Path, snapshot_id: str) -> list[dict[str, object]]:
    with connect_graph(target) as conn:
        rows = conn.execute(
            """
            SELECT path, node_id, content_hash, extractor_version, indexed_at,
                   language, parse_status, symbol_count, failure_reason, is_stale,
                   metadata_json
            FROM codebase_file_index
            WHERE snapshot_id = ?
            ORDER BY path
            """,
            (snapshot_id,),
        ).fetchall()
    records: list[dict[str, object]] = []
    for row in rows:
        metadata = json.loads(row["metadata_json"] or "{}")
        records.append(
            {
                "path": row["path"],
                "node_id": row["node_id"],
                "content_hash": row["content_hash"],
                "extractor_version": row["extractor_version"],
                "indexed_at": row["indexed_at"],
                "language": row["language"],
                "parse_status": row["parse_status"],
                "symbol_count": int(row["symbol_count"] or 0),
                "failure_reason": row["failure_reason"],
                "is_stale": int(row["is_stale"] or 0),
                "metadata": metadata,
            }
        )
    return records


def code_intelligence_facts(target: Path, snapshot_id: str) -> list[dict[str, object]]:
    with connect_graph(target) as conn:
        rows = conn.execute(
            """
            SELECT fact_id, snapshot_id, file_path, symbol_node_id, symbol_name,
                   query_kind, language, status, source, language_server_id,
                   language_server_version, collected_at, confidence, is_stale,
                   payload_json
            FROM code_intelligence_facts
            WHERE snapshot_id = ?
            ORDER BY file_path, symbol_name, query_kind, status
            """,
            (snapshot_id,),
        ).fetchall()
    facts: list[dict[str, object]] = []
    for row in rows:
        payload = json.loads(row["payload_json"] or "{}")
        facts.append(
            {
                "fact_id": row["fact_id"],
                "snapshot_id": row["snapshot_id"],
                "file_path": row["file_path"],
                "symbol_node_id": row["symbol_node_id"],
                "symbol_name": row["symbol_name"],
                "query_kind": row["query_kind"],
                "language": row["language"],
                "status": row["status"],
                "source": row["source"],
                "language_server_id": row["language_server_id"],
                "language_server_version": row["language_server_version"],
                "collected_at": row["collected_at"],
                "confidence": float(row["confidence"] or 0),
                "is_stale": int(row["is_stale"] or 0),
                "payload": payload,
            }
        )
    return facts


def ownership_edges(target: Path, snapshot_id: str) -> list[tuple[str, str, str, float]]:
    with connect_graph(target) as conn:
        rows = conn.execute(
            """
            SELECT source_node.path AS source_path,
                   target_node.name AS symbol_name,
                   edge.metadata_json AS edge_metadata
            FROM graph_edges edge
            JOIN graph_nodes source_node
              ON source_node.snapshot_id = edge.snapshot_id
             AND source_node.node_id = edge.from_node_id
            JOIN graph_nodes target_node
              ON target_node.snapshot_id = edge.snapshot_id
             AND target_node.node_id = edge.to_node_id
            WHERE edge.snapshot_id = ?
              AND edge.graph_namespace = 'codebase'
              AND edge.kind = 'owns_symbol'
            ORDER BY source_node.path, target_node.name
            """,
            (snapshot_id,),
        ).fetchall()
    edges: list[tuple[str, str, str, float]] = []
    for row in rows:
        metadata = json.loads(row["edge_metadata"] or "{}")
        edges.append(
            (
                row["source_path"],
                row["symbol_name"],
                str(metadata.get("symbol_kind") or ""),
                float(metadata.get("confidence") or 0),
            )
        )
    return edges


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


def impact_edge_metadata(target: Path, snapshot_id: str, edge_kind: str) -> list[dict[str, object]]:
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
    items: list[dict[str, object]] = []
    for row in rows:
        source_metadata = json.loads(row["source_metadata"] or "{}")
        edge_metadata = json.loads(row["edge_metadata"] or "{}")
        items.append(
            {
                "task_id": source_metadata.get("ticket_id") or source_metadata.get("work_item_id") or source_metadata.get("run_id"),
                "target": row["target_path"] or row["target_name"],
                **edge_metadata,
            }
        )
    return items


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
            self.assertEqual(["src/app.py"], [str(item["path"]) for item in file_index_rows(target, str(second["latest_snapshot_id"]))])

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

    def test_full_refresh_tracks_per_file_symbol_index_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/service.py", "def build():\n    return 1\n\nclass Worker:\n    pass\n")
            write_text(target, "README.md", "# Demo\n")

            summary = refresh_codebase_graph(target)
            rows = {str(item["path"]): item for item in file_index_rows(target, str(summary["latest_snapshot_id"]))}

            self.assertEqual({"README.md", "src/service.py"}, set(rows))
            service = rows["src/service.py"]
            self.assertEqual(64, len(str(service["content_hash"])))
            self.assertEqual("symbol-index-v1", service["extractor_version"])
            self.assertTrue(service["indexed_at"])
            self.assertEqual("Python", service["language"])
            self.assertEqual("ok", service["parse_status"])
            self.assertEqual(2, service["symbol_count"])
            self.assertEqual("", service["failure_reason"])
            self.assertEqual(0, service["is_stale"])
            self.assertEqual("not_applicable", rows["README.md"]["parse_status"])
            self.assertEqual(0, rows["README.md"]["symbol_count"])
            self.assertEqual(2, summary["file_index_count"])
            self.assertEqual(0, summary["failed_file_count"])

    def test_incremental_reindex_updates_file_index_and_symbol_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/app.py", "def one():\n    return 1\n")
            first = refresh_codebase_graph(target)
            before = {str(item["path"]): item for item in file_index_rows(target, str(first["latest_snapshot_id"]))}

            write_text(target, "src/app.py", "def one():\n    return 1\n\nclass Two:\n    pass\n")
            second = refresh_codebase_graph_changed_file(target, "src/app.py")
            after = {str(item["path"]): item for item in file_index_rows(target, str(second["latest_snapshot_id"]))}

            self.assertEqual(first["latest_snapshot_id"], second["latest_snapshot_id"])
            self.assertNotEqual(before["src/app.py"]["content_hash"], after["src/app.py"]["content_hash"])
            self.assertEqual("ok", after["src/app.py"]["parse_status"])
            self.assertEqual(2, after["src/app.py"]["symbol_count"])
            self.assertEqual(0, after["src/app.py"]["is_stale"])
            self.assertIn("src.app.Two", {str(item["qualified_name"]) for item in symbol_nodes(target, str(second["latest_snapshot_id"]))})

    def test_incremental_delete_removes_file_index_and_symbol_facts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            deleted = write_text(target, "src/app.py", "class App:\n    pass\n")
            summary = refresh_codebase_graph(target)
            self.assertIn("src/app.py", {str(item["path"]) for item in file_index_rows(target, str(summary["latest_snapshot_id"]))})

            deleted.unlink()
            updated = refresh_codebase_graph_changed_file(target, "src/app.py")
            snapshot_id = str(updated["latest_snapshot_id"])

            self.assertNotIn("src/app.py", file_node_paths(target, snapshot_id))
            self.assertNotIn("src/app.py", {str(item["path"]) for item in file_index_rows(target, snapshot_id)})
            self.assertFalse(symbol_nodes(target, snapshot_id))
            self.assertEqual(0, updated["file_index_count"])

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
            self.assertGreaterEqual(summary["file_index_count"], summary["indexed_file_count"])
            self.assertTrue(snapshot["file_index"])
            self.assertNotIn("SECRET_SOURCE_BODY", json.dumps(summary, sort_keys=True))
            self.assertNotIn("SECRET_SOURCE_BODY", json.dumps(snapshot["latest_graph_snapshot"], sort_keys=True))
            self.assertNotIn("SECRET_SOURCE_BODY", json.dumps(snapshot, sort_keys=True))

    def test_large_symbol_graph_snapshot_is_storage_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            for index in range(8):
                write_text(
                    target,
                    f"src/module_{index}.py",
                    "\n".join(
                        [
                            f"class Service{index}:",
                            "    def run(self):",
                            "        return 1",
                            "",
                            f"def helper_{index}():",
                            "    return Service0",
                            "",
                        ]
                    ),
                )

            with mock.patch.object(state_store_module, "GRAPH_SNAPSHOT_FILE_NODE_LIMIT", 3), mock.patch.object(
                state_store_module,
                "GRAPH_SNAPSHOT_SYMBOL_NODE_LIMIT",
                5,
            ), mock.patch.object(state_store_module, "GRAPH_SNAPSHOT_OTHER_NODE_LIMIT", 4), mock.patch.object(
                state_store_module,
                "GRAPH_SNAPSHOT_EDGE_LIMIT",
                7,
            ):
                summary = ensure_codebase_graph(target)

            storage = summary["snapshot_storage"]
            self.assertTrue(summary["storage_truncated"])
            self.assertTrue(summary["latest_graph_snapshot"]["storage_truncated"])
            self.assertLessEqual(summary["node_counts"].get("file", 0), 3)
            self.assertLessEqual(summary["node_counts"].get("symbol", 0), 5)
            self.assertLessEqual(sum(summary["edge_counts"].values()), 7)
            self.assertEqual(8, summary["indexed_file_count"])
            self.assertLess(storage["stored_node_count"], storage["original_node_count"])
            self.assertGreater(storage["dropped_node_counts"].get("symbol", 0), 0)

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

    def test_python_ast_extracts_symbols_and_ownership_edges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(
                target,
                "src/service.py",
                "\n".join(
                    [
                        "def build_value():",
                        "    return 1",
                        "",
                        "class Worker:",
                        "    def run(self):",
                        "        return build_value()",
                        "    async def refresh(self):",
                        "        return None",
                        "",
                    ]
                ),
            )

            summary = refresh_codebase_graph(target)
            snapshot_id = str(summary["latest_snapshot_id"])
            symbols = symbol_nodes(target, snapshot_id)
            ownership = ownership_edges(target, snapshot_id)

            by_name = {str(item["qualified_name"]): item for item in symbols}
            self.assertEqual("function", by_name["src.service.build_value"]["symbol_kind"])
            self.assertEqual("class", by_name["src.service.Worker"]["symbol_kind"])
            self.assertEqual("method", by_name["src.service.Worker.run"]["symbol_kind"])
            self.assertEqual("async_method", by_name["src.service.Worker.refresh"]["symbol_kind"])
            self.assertIn(("src/service.py", "build_value", "function", 1.0), ownership)
            self.assertIn(("src/service.py", "Worker", "class", 1.0), ownership)
            self.assertEqual(4, summary["node_counts"]["symbol"])
            self.assertEqual(4, summary["edge_counts"]["owns_symbol"])
            self.assertTrue(summary["symbol_nodes"])
            self.assertTrue(summary["ownership_edges"])
            self.assertGreaterEqual(summary["ownership_edges"][0]["confidence"], 0.8)

    def test_ts_js_extracts_imports_exports_functions_classes_methods_and_components(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(
                target,
                "src/helper.ts",
                "\n".join(
                    [
                        "export function formatValue(value: string) {",
                        "  return value;",
                        "}",
                        "export class Service {",
                        "  run() { return formatValue('ok'); }",
                        "}",
                        "export const HelperCard = () => <section />;",
                        "",
                    ]
                ),
            )
            write_text(
                target,
                "src/app.tsx",
                "import { formatValue, HelperCard } from './helper';\nexport function App() { return <HelperCard />; }\n",
            )

            summary = refresh_codebase_graph(target)
            snapshot_id = str(summary["latest_snapshot_id"])
            symbols = symbol_nodes(target, snapshot_id)
            ownership = ownership_edges(target, snapshot_id)

            helper_symbols = {
                (str(item["name"]), str(item["symbol_kind"]), bool(item["exported"]))
                for item in symbols
                if item["path"] == "src/helper.ts"
            }
            app_symbols = {
                (str(item["name"]), str(item["symbol_kind"]), bool(item["exported"]))
                for item in symbols
                if item["path"] == "src/app.tsx"
            }
            self.assertIn(("formatValue", "function", True), helper_symbols)
            self.assertIn(("Service", "class", True), helper_symbols)
            self.assertIn(("run", "method", False), helper_symbols)
            self.assertIn(("HelperCard", "component", True), helper_symbols)
            self.assertIn(("App", "component", True), app_symbols)
            self.assertIn(("src/app.tsx", "src/helper.ts", "imports"), import_edges(target, snapshot_id))
            self.assertIn(("src/helper.ts", "HelperCard", "component", 0.8), ownership)
            self.assertGreaterEqual(summary["node_counts"]["symbol"], 5)
            self.assertGreaterEqual(summary["edge_counts"]["owns_symbol"], 5)
            self.assertTrue(summary["latest_graph_snapshot"]["symbol_nodes"])
            self.assertTrue(summary["latest_graph_snapshot"]["import_edges"])

    def test_rust_extracts_modules_imports_structs_functions_and_impl_methods(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "Cargo.toml", "[package]\nname = \"demo-rust\"\nversion = \"0.1.0\"\n")
            write_text(
                target,
                "src/lib.rs",
                "\n".join(
                    [
                        "pub mod worker;",
                        "use crate::worker::Worker;",
                        "use std::fmt;",
                        "",
                        "pub struct Config {",
                        "    pub name: String,",
                        "    retries: usize,",
                        "}",
                        "",
                        "pub enum Mode { Fast, Slow }",
                        "pub trait Runnable { fn run(&self); }",
                        "pub fn build_worker() -> Worker { Worker::new() }",
                        "impl Config {",
                        "    pub fn retry_count(&self) -> usize { self.retries }",
                        "}",
                        "",
                    ]
                ),
            )
            write_text(
                target,
                "src/worker.rs",
                "pub struct Worker;\nimpl Worker {\n    pub fn new() -> Self { Worker }\n}\n",
            )

            summary = refresh_codebase_graph(target)
            snapshot_id = str(summary["latest_snapshot_id"])
            symbols = symbol_nodes(target, snapshot_id)
            lib_symbols = {
                (str(item["name"]), str(item["symbol_kind"]), bool(item["exported"]), str(item.get("parent_symbol") or ""))
                for item in symbols
                if item["path"] == "src/lib.rs"
            }

            self.assertIn(("worker", "module", True, ""), lib_symbols)
            self.assertIn(("Config", "struct", True, ""), lib_symbols)
            self.assertIn(("Mode", "enum", True, ""), lib_symbols)
            self.assertIn(("Runnable", "trait", True, ""), lib_symbols)
            self.assertIn(("build_worker", "function", True, ""), lib_symbols)
            self.assertIn(("retry_count", "method", True, "Config"), lib_symbols)
            self.assertIn(("name", "field", True, "Config"), lib_symbols)
            self.assertIn(("src/lib.rs", "src/worker.rs", "imports"), import_edges(target, snapshot_id))
            self.assertTrue(any(item["name"] == "src::worker" for item in module_nodes(target, snapshot_id)))
            self.assertTrue(all(int((item.get("owning_range") or {}).get("start_line", 0)) >= 1 for item in symbols))
            self.assertGreaterEqual(summary["edge_counts"]["owns_symbol"], 8)

    def test_go_extracts_packages_imports_types_functions_methods_and_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "go.mod", "module example.com/demo\n")
            write_text(
                target,
                "internal/model/model.go",
                "\n".join(
                    [
                        "package model",
                        "",
                        "type User struct {",
                        "    ID string",
                        "    name string",
                        "}",
                        "",
                        "func NewUser() User { return User{} }",
                        "",
                    ]
                ),
            )
            write_text(
                target,
                "service/service.go",
                "\n".join(
                    [
                        "package service",
                        "",
                        "import (",
                        "    \"fmt\"",
                        "    \"example.com/demo/internal/model\"",
                        ")",
                        "",
                        "type Runner interface {",
                        "    Run() error",
                        "}",
                        "",
                        "type Service struct {",
                        "    User model.User",
                        "    name string",
                        "}",
                        "",
                        "func NewService() *Service { return &Service{} }",
                        "func (s *Service) Run() error { return nil }",
                        "func (s *Service) format() string { return fmt.Sprint(s.name) }",
                        "",
                    ]
                ),
            )

            summary = refresh_codebase_graph(target)
            snapshot_id = str(summary["latest_snapshot_id"])
            symbols = symbol_nodes(target, snapshot_id)
            service_symbols = {
                (str(item["name"]), str(item["symbol_kind"]), bool(item["exported"]), str(item.get("parent_symbol") or ""))
                for item in symbols
                if item["path"] == "service/service.go"
            }

            self.assertIn(("Runner", "interface", True, ""), service_symbols)
            self.assertIn(("Service", "struct", True, ""), service_symbols)
            self.assertIn(("NewService", "function", True, ""), service_symbols)
            self.assertIn(("Run", "method", True, "Service"), service_symbols)
            self.assertIn(("format", "method", False, "Service"), service_symbols)
            self.assertIn(("User", "field", True, "Service"), service_symbols)
            self.assertIn(("service/service.go", "internal/model/model.go", "imports"), import_edges(target, snapshot_id))
            self.assertTrue(any(item["name"] == "service" and item["language"] == "Go" for item in module_nodes(target, snapshot_id)))
            self.assertTrue(any(item["package_name"] == "example.com/demo" for item in symbols if item["language"] == "Go"))
            self.assertGreaterEqual(summary["edge_counts"]["owns_symbol"], 8)

    def test_java_extracts_packages_imports_classes_interfaces_enums_methods_and_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(
                target,
                "src/main/java/com/example/model/User.java",
                "\n".join(
                    [
                        "package com.example.model;",
                        "",
                        "public class User {",
                        "  public String id;",
                        "  private String secret;",
                        "  public String id() { return id; }",
                        "}",
                        "",
                    ]
                ),
            )
            write_text(
                target,
                "src/main/java/com/example/service/Service.java",
                "\n".join(
                    [
                        "package com.example.service;",
                        "",
                        "import com.example.model.User;",
                        "import java.util.List;",
                        "",
                        "public class Service {",
                        "  private User user;",
                        "  public Service(User user) { this.user = user; }",
                        "  public User current() { return user; }",
                        "}",
                        "",
                        "interface Runner {",
                        "  void run();",
                        "}",
                        "",
                        "enum Mode { FAST, SLOW; }",
                        "",
                    ]
                ),
            )

            summary = refresh_codebase_graph(target)
            snapshot_id = str(summary["latest_snapshot_id"])
            symbols = symbol_nodes(target, snapshot_id)
            service_symbols = {
                (str(item["name"]), str(item["symbol_kind"]), str(item["visibility"]), str(item.get("parent_symbol") or ""))
                for item in symbols
                if item["path"] == "src/main/java/com/example/service/Service.java"
            }

            self.assertIn(("Service", "class", "public", ""), service_symbols)
            self.assertIn(("Runner", "interface", "package", ""), service_symbols)
            self.assertIn(("Mode", "enum", "package", ""), service_symbols)
            self.assertIn(("current", "method", "public", "Service"), service_symbols)
            self.assertIn(("run", "method", "package", "Runner"), service_symbols)
            self.assertIn(("user", "field", "private", "Service"), service_symbols)
            self.assertIn(("src/main/java/com/example/service/Service.java", "src/main/java/com/example/model/User.java", "imports"), import_edges(target, snapshot_id))
            self.assertTrue(any(item["name"] == "com.example.service" and item["language"] == "Java" for item in module_nodes(target, snapshot_id)))
            self.assertTrue(any(item["package_name"] == "com.example.service" for item in symbols if item["language"] == "Java"))
            self.assertGreaterEqual(summary["edge_counts"]["owns_symbol"], 8)

    def test_normalized_symbol_identity_contract_across_supported_extractors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "pkg/service.py", "class PyService:\n    def run(self):\n        return True\n")
            write_text(target, "package.json", json.dumps({"name": "@example/demo"}))
            write_text(target, "src/widget.tsx", "export function Widget() { return <section />; }\n")
            write_text(target, "Cargo.toml", "[package]\nname = \"demo-rust\"\nversion = \"0.1.0\"\n")
            write_text(
                target,
                "src/lib.rs",
                "pub struct RustService;\nimpl RustService {\n    pub fn run(&self) {}\n}\n",
            )
            write_text(target, "go.mod", "module example.com/demo\n")
            write_text(
                target,
                "pkg/service.go",
                "package service\ntype GoService struct {}\nfunc (s GoService) Run() {}\n",
            )
            write_text(
                target,
                "src/main/java/com/example/JavaService.java",
                "package com.example;\npublic class JavaService {\n  public void run() {}\n}\n",
            )

            summary = refresh_codebase_graph(target)
            snapshot_id = str(summary["latest_snapshot_id"])
            symbols = symbol_nodes(target, snapshot_id)
            languages = {str(item["language"]) for item in symbols}

            self.assertTrue({"Python", "TypeScript", "Rust", "Go", "Java"}.issubset(languages))
            for item in symbols:
                self.assertEqual(1, item["symbol_identity_schema_version"])
                self.assertTrue(str(item["symbol_id"]).startswith("symbol:"))
                self.assertTrue(item["qualified_name"])
                self.assertTrue(item["symbol_kind"])
                self.assertIn(item["visibility"], {"public", "private", "protected", "internal", "package", "unknown"})
                self.assertEqual("exact", item["resolution_kind"])
                self.assertGreater(float(item["extractor_confidence"]), 0)
                owning_range = item["owning_range"]
                self.assertIsInstance(owning_range, dict)
                self.assertGreaterEqual(int(owning_range.get("start_line", 0)), 1)

    def test_parser_failure_keeps_file_graph_as_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/broken.py", "def broken(:\n    return 1\n")
            write_text(target, "README.md", "# Still indexable\n")

            summary = refresh_codebase_graph(target)
            snapshot_id = str(summary["latest_snapshot_id"])

            self.assertEqual(["README.md", "src/broken.py"], file_node_paths(target, snapshot_id))
            self.assertEqual([], symbol_nodes(target, snapshot_id))
            with connect_graph(target) as conn:
                parser_status = conn.execute(
                    """
                    SELECT fact.fact_value
                    FROM graph_node_facts fact
                    JOIN graph_nodes node
                      ON node.snapshot_id = fact.snapshot_id
                     AND node.node_id = fact.node_id
                    WHERE fact.snapshot_id = ?
                      AND node.path = 'src/broken.py'
                      AND fact.fact_key = 'parser_status'
                    """,
                    (snapshot_id,),
                ).fetchone()["fact_value"]

            self.assertEqual("syntax_error", parser_status)
            self.assertEqual(2, summary["indexed_file_count"])
            self.assertEqual(1, summary["node_counts"]["file"])
            self.assertEqual(1, summary["node_counts"]["doc_file"])
            indexed = {str(item["path"]): item for item in file_index_rows(target, snapshot_id)}
            self.assertEqual("syntax_error", indexed["src/broken.py"]["parse_status"])
            self.assertEqual("syntax_error", indexed["src/broken.py"]["failure_reason"])
            self.assertEqual(0, indexed["src/broken.py"]["symbol_count"])
            self.assertEqual(1, summary["failed_file_count"])
            self.assertEqual("syntax_error", summary["latest_graph_snapshot"]["file_index"][0]["parse_status"])

    def test_rust_go_java_parse_failures_keep_advisory_file_facts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/broken.rs", "pub struct Broken {\n    pub id: usize\n")
            write_text(target, "service/broken.go", "package service\nfunc Broken(\n")
            write_text(target, "src/main/java/Broken.java", "class Broken {\n  public void run() {\n")

            summary = refresh_codebase_graph(target)
            snapshot_id = str(summary["latest_snapshot_id"])
            indexed = {str(item["path"]): item for item in file_index_rows(target, snapshot_id)}
            broken_paths = {"src/broken.rs", "service/broken.go", "src/main/java/Broken.java"}

            self.assertTrue(broken_paths.issubset(set(file_node_paths(target, snapshot_id))))
            self.assertEqual(broken_paths, {path for path, item in indexed.items() if item["parse_status"] == "syntax_error"})
            self.assertEqual(broken_paths, {path for path, item in indexed.items() if item["failure_reason"] == "syntax_error"})
            self.assertEqual(3, summary["failed_file_count"])
            self.assertFalse([item for item in symbol_nodes(target, snapshot_id) if item["path"] in broken_paths])

    def test_mixed_language_repo_exposes_file_symbol_ownership_and_import_previews(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "pkg/__init__.py", "")
            write_text(target, "pkg/model.py", "class Model:\n    pass\n")
            write_text(target, "src/view.tsx", "export const View = () => <main />;\n")
            write_text(target, "src/app.tsx", "import { View } from './view';\nexport function App() { return <View />; }\n")

            snapshot = state_snapshot(target)
            summary = snapshot["codebase_graph_summary"]
            latest = snapshot["latest_graph_snapshot"]
            snapshot_id = str(latest["snapshot_id"])

            self.assertIn("pkg/model.py", file_node_paths(target, snapshot_id))
            self.assertIn("src/app.tsx", file_node_paths(target, snapshot_id))
            self.assertIn(("src/app.tsx", "src/view.tsx", "imports"), import_edges(target, snapshot_id))
            self.assertIn(("pkg/model.py", "Model", "class", 1.0), ownership_edges(target, snapshot_id))
            self.assertTrue(any(item["language"] == "Python" for item in latest["symbol_nodes"]))
            self.assertTrue(any(item["language"] == "TypeScript" for item in latest["symbol_nodes"]))
            self.assertTrue(latest["file_nodes"])
            self.assertTrue(latest["symbol_nodes"])
            self.assertTrue(latest["ownership_edges"])
            self.assertTrue(latest["import_edges"])
            self.assertGreater(summary["node_counts"]["symbol"], 0)
            self.assertGreater(summary["edge_counts"]["owns_symbol"], 0)
            self.assertGreaterEqual(latest["import_edges"][0]["confidence"], 0.8)

    def test_semantic_references_resolve_exact_symbol_owners_across_languages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(
                target,
                "services/payment.py",
                "class PaymentService:\n    def refresh(self):\n        return True\n",
            )
            write_text(target, "web/payment.ts", "export const usePayment = () => PaymentService.refresh();\n")
            write_text(target, "src/main.rs", "fn main() { PaymentService::refresh(); }\n")
            write_text(target, "cmd/main.go", "package main\nfunc main() { var _ PaymentService }\n")
            write_text(target, "src/main/java/App.java", "class App { void run() { PaymentService.refresh(); } }\n")

            summary = refresh_codebase_graph(target)
            snapshot_id = str(summary["latest_snapshot_id"])
            references = [
                item
                for item in codebase_reference_metadata(target, snapshot_id)
                if item["target_path"] == "services/payment.py"
            ]

            self.assertTrue(references)
            self.assertTrue({"web/payment.ts", "src/main.rs", "cmd/main.go", "src/main/java/App.java"}.issubset({str(item["source_path"]) for item in references}))
            self.assertEqual({"exact_symbol_reference"}, {str(item["signal_kind"]) for item in references})
            self.assertEqual({"exact"}, {str(item["resolution_kind"]) for item in references})
            self.assertTrue(all(str(item.get("symbol_node_id") or "").startswith("graph-node:codebase:symbol:") for item in references))
            self.assertTrue(all(not item["write_candidate"] for item in references))
            self.assertTrue(summary["latest_graph_snapshot"]["semantic_edges"])

    def test_cross_language_interface_bridge_edges_are_advisory_with_reasons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(
                target,
                "api/openapi.yaml",
                "\n".join(
                    [
                        "openapi: 3.1.0",
                        "paths:",
                        "  /api/users/{id}:",
                        "    get:",
                        "      operationId: getUser",
                        "components:",
                        "  schemas:",
                        "    User:",
                        "      type: object",
                        "",
                    ]
                ),
            )
            write_text(
                target,
                "src/users.ts",
                "export class UsersApi { getUser() { return fetch('/api/users/:id'); } }\n",
            )

            summary = refresh_codebase_graph(target)
            bridge = next(
                item
                for item in codebase_reference_metadata(target, str(summary["latest_snapshot_id"]))
                if item["source_path"] == "src/users.ts" and item["target_path"] == "api/openapi.yaml"
            )

            self.assertEqual("interface_bridge", bridge["signal_kind"])
            self.assertIn("openapi", str(bridge["interface_kind"]))
            self.assertIn("cross-language", str(bridge["reason"]))
            self.assertGreaterEqual(float(bridge["confidence"]), 0.6)
            self.assertFalse(bridge["write_candidate"])
            self.assertEqual("advisory", bridge["dependency_mode"])

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
            unresolved = [
                item
                for item in symbol_nodes(target, str(summary["latest_snapshot_id"]))
                if item.get("resolution_kind") == "unresolved"
            ]
            self.assertEqual({"React", "lodash"}, {str(item["name"]) for item in unresolved})
            self.assertTrue(all(item["symbol_kind"] == "import" for item in unresolved))
            self.assertTrue(all(item["owner_file_path"] == "" for item in unresolved))
            self.assertTrue(all(item["reference_file_path"] == "src/app.ts" for item in unresolved))
            self.assertTrue(all(float(item["extractor_confidence"]) <= 0.3 for item in unresolved))

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

    def scope_report(self, records: list[dict[str, object]]) -> str:
        return "\n".join(
            [
                "# Read-only Scope Report",
                "",
                "Structured ownership evidence follows. The runtime must normalize and threshold it before use.",
                "",
                "```json",
                json.dumps({"scope_evidence_records": records}, sort_keys=True),
                "```",
                "",
            ]
        )

    def record_scope_report(self, target: Path, task_id: str, records: list[dict[str, object]]) -> list[dict[str, object]]:
        with closing(connect(database_path_for_target(target))) as conn:
            result = record_scope_evidence_from_report_text_conn(
                conn,
                target,
                report_text=self.scope_report(records),
                task_id=task_id,
                worker_id=f"worker:test:{task_id}",
                worker_run_id="run:test-scope-evidence",
                report_artifact_id=f"artifact:test:{task_id}",
            )
            self.assertEqual("recorded", result["status"])
            return scope_evidence_records_conn(conn, task_id=task_id)

    def write_execution_groups(self, snapshot: dict[str, object]) -> list[dict[str, object]]:
        groups = snapshot.get("proposed_execution_groups") if isinstance(snapshot.get("proposed_execution_groups"), list) else []
        return [
            group
            for group in groups
            if isinstance(group, dict)
            and isinstance(group.get("payload"), dict)
            and group["payload"].get("execution_mode") == "write_workers"
        ]

    def read_only_scope_groups(self, snapshot: dict[str, object]) -> list[dict[str, object]]:
        groups = snapshot.get("proposed_execution_groups") if isinstance(snapshot.get("proposed_execution_groups"), list) else []
        return [
            group
            for group in groups
            if isinstance(group, dict)
            and isinstance(group.get("payload"), dict)
            and group["payload"].get("execution_mode") == "read_only"
            and group["payload"].get("scope_evidence_required")
        ]

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
            direct = next(item for item in impact_edge_metadata(target, impact_summary["latest_snapshot_id"], "likely_touches") if item["target"] == "src/auth.py")
            self.assertEqual("direct_path", direct["signal_kind"])
            self.assertTrue(direct["write_candidate"])

    def test_authored_path_metadata_creates_direct_write_candidate_without_summary_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "AUTH = True\n")
            self.write_ticket_run(
                target,
                [{"id": "T1", "summary": "Implement the queued auth hardening change", "status": "pending", "paths": ["src/auth.py"]}],
            )

            snapshot = state_snapshot(target)
            item = context_item_by_path(snapshot, "src/auth.py")

            self.assertEqual("direct_path", item["signal_kind"])
            self.assertTrue(item["write_candidate"])
            self.assertGreaterEqual(item["confidence"], 0.9)

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

    def test_symbol_owner_match_creates_direct_write_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "class AuthService:\n    def refresh(self):\n        return True\n")
            self.write_ticket_run(
                target,
                [{"id": "T1", "summary": "Update AuthService refresh behavior", "status": "pending"}],
            )

            snapshot = state_snapshot(target)
            impact_summary = snapshot["impact_graph_summary"]
            direct = next(
                item
                for item in impact_edge_metadata(target, impact_summary["latest_snapshot_id"], "likely_touches")
                if item["target"] == "src/auth.py"
            )

            self.assertEqual("exact_symbol", direct["signal_kind"])
            self.assertEqual("symbol_owner_match", direct["source"])
            self.assertTrue(direct["write_candidate"])
            self.assertGreaterEqual(direct["confidence"], 0.9)

    def test_ambiguous_symbol_owner_match_is_advisory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/alpha.py", "class Shared:\n    pass\n")
            write_text(target, "src/beta.py", "class Shared:\n    pass\n")
            self.write_ticket_run(
                target,
                [{"id": "T1", "summary": "Update Shared behavior", "status": "pending"}],
            )

            snapshot = state_snapshot(target)
            impact_summary = snapshot["impact_graph_summary"]
            shared_edges = [
                item
                for item in impact_edge_metadata(target, impact_summary["latest_snapshot_id"], "likely_touches")
                if item["target"] in {"src/alpha.py", "src/beta.py"}
            ]

            self.assertEqual({"ambiguous_symbol"}, {item["signal_kind"] for item in shared_edges})
            self.assertEqual({"ambiguous"}, {item["symbol_resolution"] for item in shared_edges})
            self.assertTrue(all(not item["write_candidate"] for item in shared_edges))
            groups = snapshot.get("proposed_execution_groups") if isinstance(snapshot.get("proposed_execution_groups"), list) else []
            scope_items = [
                item
                for group in groups
                if isinstance(group, dict)
                and isinstance(group.get("payload"), dict)
                and group["payload"].get("execution_mode") == "read_only"
                and group["payload"].get("scope_evidence_required")
                for item in group.get("items", [])
                if isinstance(item, dict) and item.get("task_id") == "T1"
            ]

            self.assertEqual(1, len(scope_items), groups)
            payload = scope_items[0]["payload"]
            self.assertEqual("scope", payload["canonical_action_type"])
            self.assertTrue(payload["scope_evidence_required"])
            self.assertEqual("scoping_read_confidence", payload["missing_confidence_signal"])
            self.assertTrue(
                any(
                    evidence.get("signal_kind") == "ambiguous_symbol"
                    for evidence in payload["scope_evidence"]["ownership_evidence"]
                ),
                payload["scope_evidence"],
            )

    def test_inferred_symbol_owner_match_is_advisory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "class AuthService:\n    pass\n")
            self.write_ticket_run(
                target,
                [{"id": "T1", "summary": "Update authservice behavior", "status": "pending"}],
            )

            snapshot = state_snapshot(target)
            impact_summary = snapshot["impact_graph_summary"]
            auth = next(
                item
                for item in impact_edge_metadata(target, impact_summary["latest_snapshot_id"], "likely_touches")
                if item["target"] == "src/auth.py"
            )

            self.assertEqual("inferred_symbol", auth["signal_kind"])
            self.assertEqual("inferred", auth["symbol_resolution"])
            self.assertFalse(auth["write_candidate"])

    def test_stale_symbol_owner_match_is_advisory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "class AuthService:\n    pass\n")
            summary = refresh_codebase_graph(target)
            with connect_graph(target) as conn:
                conn.execute(
                    """
                    UPDATE graph_nodes
                    SET is_stale = 1
                    WHERE snapshot_id = ?
                      AND graph_namespace = 'codebase'
                      AND kind = 'symbol'
                      AND name = 'AuthService'
                    """,
                    (summary["latest_snapshot_id"],),
                )
                conn.commit()
            self.write_ticket_run(
                target,
                [{"id": "T1", "summary": "Update AuthService behavior", "status": "pending"}],
            )

            snapshot = state_snapshot(target)
            impact_summary = snapshot["impact_graph_summary"]
            auth = next(
                item
                for item in impact_edge_metadata(target, impact_summary["latest_snapshot_id"], "likely_touches")
                if item["target"] == "src/auth.py"
            )

            self.assertEqual("stale_symbol", auth["signal_kind"])
            self.assertEqual("stale", auth["symbol_resolution"])
            self.assertFalse(auth["write_candidate"])

    def test_exact_scope_evidence_promotes_ticket_to_write_worker_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "class AuthService:\n    def refresh(self):\n        return True\n")
            write_text(target, "tests/test_auth.py", "from src.auth import AuthService\n\ndef test_refresh():\n    assert AuthService().refresh()\n")
            self.write_ticket_run(target, [{"id": "T1", "summary": "Implement safer defaults", "status": "pending"}])

            before = state_snapshot(target)
            self.assertEqual(1, len(self.read_only_scope_groups(before)))

            records = self.record_scope_report(
                target,
                "T1",
                [
                    {
                        "candidate_path": "src/auth.py",
                        "candidate_symbol": "AuthService",
                        "confidence": 0.93,
                        "likely_tests": ["tests/test_auth.py"],
                        "reasons": ["read-only inspection found AuthService owns the requested refresh behavior"],
                    }
                ],
            )
            accepted = [record for record in records if record["status"] == "accepted"]
            self.assertEqual(1, len(accepted), records)

            after = state_snapshot(target)
            write_groups = self.write_execution_groups(after)
            self.assertEqual(1, len(write_groups), after.get("proposed_execution_groups"))
            item_payload = write_groups[0]["items"][0]["payload"]
            touches = item_payload["likely_touches"]

            self.assertEqual("build", item_payload["canonical_action_type"])
            self.assertTrue(any(touch["path"] == "src/auth.py" and touch["source"] == "scope_evidence" for touch in touches))
            self.assertTrue(any(touch["signal_kind"] == "exact_symbol" for touch in touches))
            self.assertTrue(write_groups[0]["items"][0]["required_leases"])
            self.assertEqual([], self.read_only_scope_groups(after))
            self.assertTrue(after["accepted_scope_evidence_records"])

    def test_ambiguous_scope_evidence_does_not_promote_write_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/alpha.py", "class Shared:\n    pass\n")
            write_text(target, "src/beta.py", "class Shared:\n    pass\n")
            self.write_ticket_run(target, [{"id": "T1", "summary": "Update Shared behavior", "status": "pending"}])
            state_snapshot(target)

            records = self.record_scope_report(
                target,
                "T1",
                [
                    {
                        "candidate_symbol": "Shared",
                        "confidence": 0.96,
                        "reasons": ["two owners exist, so this report cannot identify a single write owner"],
                    }
                ],
            )
            rejected = [record for record in records if record["status"] == "rejected"]
            self.assertEqual("ambiguous_symbol", rejected[0]["rejection_reason"])

            after = state_snapshot(target)
            self.assertEqual([], self.write_execution_groups(after))
            scope_groups = self.read_only_scope_groups(after)
            self.assertEqual(1, len(scope_groups), after.get("proposed_execution_groups"))

    def test_stale_scope_evidence_does_not_promote_write_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "class AuthService:\n    pass\n")
            self.write_ticket_run(target, [{"id": "T1", "summary": "Implement safer defaults", "status": "pending"}])
            state_snapshot(target)

            records = self.record_scope_report(
                target,
                "T1",
                [
                    {
                        "candidate_path": "src/auth.py",
                        "candidate_symbol": "AuthService",
                        "confidence": 0.95,
                        "stale_context_warning": "worker inspected stale context and could not verify current ownership",
                        "reasons": ["ownership may have changed since the context pack was generated"],
                    }
                ],
            )
            rejected = [record for record in records if record["status"] == "rejected"]
            self.assertEqual("stale_context", rejected[0]["rejection_reason"])

            after = state_snapshot(target)
            self.assertEqual([], self.write_execution_groups(after))
            scope_groups = self.read_only_scope_groups(after)
            self.assertEqual(1, len(scope_groups), after.get("proposed_execution_groups"))

    def test_creation_path_scope_evidence_promotes_path_level_write_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.write_ticket_run(target, [{"id": "T1", "summary": "Create backend API service", "status": "pending"}])
            state_snapshot(target)

            records = self.record_scope_report(
                target,
                "T1",
                [
                    {
                        "candidate_path": "backend/api.py",
                        "evidence_kind": "creation_path",
                        "confidence": 0.93,
                        "likely_tests": ["tests/test_backend_api.py"],
                        "reasons": ["read-only scoping found this new file should own the backend API service"],
                    }
                ],
            )

            accepted = [record for record in records if record["status"] == "accepted"]
            self.assertEqual(1, len(accepted), records)
            self.assertEqual("creation_path", accepted[0]["payload"]["signal_kind"])
            self.assertEqual("", accepted[0]["symbol_node_id"])

            after = state_snapshot(target)
            write_groups = self.write_execution_groups(after)
            self.assertEqual(1, len(write_groups), after.get("proposed_execution_groups"))
            item_payload = write_groups[0]["items"][0]["payload"]
            touches = item_payload["likely_touches"]
            leases = write_groups[0]["items"][0]["required_leases"]

            self.assertTrue(any(touch["path"] == "backend/api.py" and touch["signal_kind"] == "creation_path" for touch in touches))
            self.assertTrue(any(lease["scope_kind"] == "file" and lease["path"] == "backend/api.py" for lease in leases))
            self.assertFalse(any(lease["scope_kind"] == "symbol" for lease in leases))

    def test_unsafe_creation_path_scope_evidence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.write_ticket_run(target, [{"id": "T1", "summary": "Create runtime helper", "status": "pending"}])
            state_snapshot(target)

            records = self.record_scope_report(
                target,
                "T1",
                [
                    {
                        "candidate_path": ".diffmogger/runtime/helper.py",
                        "evidence_kind": "creation_path",
                        "confidence": 0.97,
                        "reasons": ["worker suggested creating a target-internal runtime helper"],
                    }
                ],
            )

            rejected = [record for record in records if record["status"] == "rejected"]
            self.assertEqual(1, len(rejected), records)
            self.assertEqual("unsafe_candidate_path", rejected[0]["rejection_reason"])

            after = state_snapshot(target)
            self.assertEqual([], self.write_execution_groups(after))

    def test_stale_file_index_downgrades_symbol_evidence_without_reindex(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "class AuthService:\n    pass\n")
            self.write_ticket_run(
                target,
                [{"id": "T1", "summary": "Update AuthService behavior", "status": "pending"}],
            )
            graph = refresh_codebase_graph(target)
            write_text(target, "src/auth.py", "class AuthService:\n    pass\n\nSTALE = True\n")

            with closing(connect(database_path_for_target(target))) as conn:
                refresh_codebase_graph_staleness_conn(conn, target, snapshot_id=str(graph["latest_snapshot_id"]))
                graph_summary = codebase_graph_summary(conn)
                refresh_task_graph_conn(conn, target)
                impact = refresh_impact_graph_conn(conn, target)

            auth = next(
                item
                for item in impact_edge_metadata(target, impact["latest_snapshot_id"], "likely_touches")
                if item["target"] == "src/auth.py"
            )

            self.assertEqual(1, graph_summary["stale_file_count"])
            self.assertTrue(graph_summary["latest_graph_snapshot"]["file_index"][0]["is_stale"])
            self.assertEqual("stale_symbol", auth["signal_kind"])
            self.assertEqual("stale", auth["symbol_resolution"])
            self.assertFalse(auth["write_candidate"])

    def test_missing_lsp_provider_degrades_to_extractor_only_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "class AuthService:\n    pass\n")

            with mock.patch("diffmogger.runtime.code_intelligence.shutil.which", return_value=None):
                snapshot = state_snapshot(target)
                with closing(connect(database_path_for_target(target))) as conn:
                    summary = refresh_code_intelligence_facts_conn(conn, target)

            availability = snapshot["code_intelligence"]["provider_availability"]
            self.assertEqual(0, availability["available_count"])
            self.assertIn("Python", availability["languages"])
            self.assertEqual("extractor_only", summary["fallback"])
            self.assertIn("unavailable", summary["fact_counts"])

    def test_available_lsp_provider_confirms_symbol_owner_for_scheduler(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "class AuthService:\n    def refresh(self):\n        return True\n")
            graph = refresh_codebase_graph(target)
            provider = StaticCodeIntelligenceProvider(
                language="Python",
                server_id="pyright",
                server_version="pyright 1.2.3",
                workspace_symbol_results={
                    "AuthService": [
                        {
                            "name": "AuthService",
                            "qualified_name": "src.auth.AuthService",
                            "kind": "class",
                            "file_path": "src/auth.py",
                            "confidence": 0.99,
                        }
                    ],
                    "refresh": [
                        {
                            "name": "refresh",
                            "qualified_name": "src.auth.AuthService.refresh",
                            "kind": "method",
                            "file_path": "src/auth.py",
                            "confidence": 0.98,
                        }
                    ],
                },
                diagnostics_by_file={"src/auth.py": []},
            )
            with closing(connect(database_path_for_target(target))) as conn:
                summary = refresh_code_intelligence_facts_conn(conn, target, provider=provider)
                receipt = conn.execute(
                    """
                    SELECT kind, status, payload_json
                    FROM validation_receipts
                    WHERE kind = 'code_intelligence_diagnostics'
                    """
                ).fetchone()
            self.write_ticket_run(
                target,
                [{"id": "T1", "summary": "Update AuthService refresh behavior", "status": "pending"}],
            )

            snapshot = state_snapshot(target)
            impact_summary = snapshot["impact_graph_summary"]
            direct = next(
                item
                for item in impact_edge_metadata(target, impact_summary["latest_snapshot_id"], "likely_touches")
                if item["target"] == "src/auth.py"
            )
            facts = code_intelligence_facts(target, str(graph["latest_snapshot_id"]))
            confirmed = [item for item in facts if item["status"] == "confirmed"]

            self.assertGreaterEqual(summary["fact_counts"]["confirmed"], 1)
            self.assertTrue(confirmed)
            self.assertTrue(all(item["source"] == "lsp_workspace_symbols" for item in confirmed))
            self.assertTrue(all(item["collected_at"] for item in confirmed))
            self.assertEqual({"pyright"}, {str(item["language_server_id"]) for item in confirmed})
            self.assertEqual("symbol_owner_match_lsp_confirmed", direct["source"])
            self.assertEqual("confirmed", direct["lsp_status"])
            self.assertTrue(direct["write_candidate"])
            self.assertGreaterEqual(direct["confidence"], 0.96)
            self.assertIsNotNone(receipt)
            self.assertEqual("passed", receipt["status"])

    def test_lsp_timeout_is_explained_without_blocking_extractor_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "class AuthService:\n    pass\n")
            provider = StaticCodeIntelligenceProvider(
                language="Python",
                server_id="pyright",
                server_version="pyright timeout",
                timeout_queries={"AuthService"},
            )
            refresh_codebase_graph(target)
            with closing(connect(database_path_for_target(target))) as conn:
                summary = refresh_code_intelligence_facts_conn(conn, target, provider=provider)
            self.write_ticket_run(
                target,
                [{"id": "T1", "summary": "Update AuthService behavior", "status": "pending"}],
            )

            snapshot = state_snapshot(target)
            impact_summary = snapshot["impact_graph_summary"]
            auth = next(
                item
                for item in impact_edge_metadata(target, impact_summary["latest_snapshot_id"], "likely_touches")
                if item["target"] == "src/auth.py"
            )

            self.assertIn("timeout", summary["fact_counts"])
            self.assertEqual("timeout", auth["lsp_status"])
            self.assertEqual("symbol_owner_match_lsp_timeout", auth["source"])
            self.assertTrue(auth["write_candidate"])

    def test_stale_file_with_lsp_provider_keeps_symbol_evidence_advisory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "class AuthService:\n    pass\n")
            graph = refresh_codebase_graph(target)
            write_text(target, "src/auth.py", "class AuthService:\n    pass\n\nSTALE = True\n")
            provider = StaticCodeIntelligenceProvider(
                language="Python",
                workspace_symbol_results={
                    "AuthService": [
                        {
                            "name": "AuthService",
                            "qualified_name": "src.auth.AuthService",
                            "file_path": "src/auth.py",
                            "confidence": 0.99,
                        }
                    ]
                },
            )
            with closing(connect(database_path_for_target(target))) as conn:
                refresh_codebase_graph_staleness_conn(conn, target, snapshot_id=str(graph["latest_snapshot_id"]))
                summary = refresh_code_intelligence_facts_conn(conn, target, provider=provider, refresh_graph=False)
                refresh_task_graph_conn(conn, target)
            self.write_ticket_run(
                target,
                [{"id": "T1", "summary": "Update AuthService behavior", "status": "pending"}],
            )
            with closing(connect(database_path_for_target(target))) as conn:
                refresh_task_graph_conn(conn, target)
                impact = refresh_impact_graph_conn(conn, target)

            auth = next(
                item
                for item in impact_edge_metadata(target, impact["latest_snapshot_id"], "likely_touches")
                if item["target"] == "src/auth.py"
            )

            self.assertIn("stale_file", summary["fact_counts"])
            self.assertEqual("stale_file", auth["lsp_status"])
            self.assertEqual("stale_symbol", auth["signal_kind"])
            self.assertFalse(auth["write_candidate"])

    def test_lsp_disambiguates_same_name_symbols_for_write_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/alpha.py", "class Shared:\n    pass\n")
            write_text(target, "src/beta.py", "class Shared:\n    pass\n")
            refresh_codebase_graph(target)
            provider = StaticCodeIntelligenceProvider(
                language="Python",
                server_id="pyright",
                server_version="pyright disambiguation",
                workspace_symbol_results={
                    "Shared": [
                        {
                            "name": "Shared",
                            "qualified_name": "src.beta.Shared",
                            "kind": "class",
                            "file_path": "src/beta.py",
                            "confidence": 0.99,
                        }
                    ]
                },
            )
            with closing(connect(database_path_for_target(target))) as conn:
                refresh_code_intelligence_facts_conn(conn, target, provider=provider)
            self.write_ticket_run(
                target,
                [{"id": "T1", "summary": "Update Shared behavior", "status": "pending"}],
            )

            snapshot = state_snapshot(target)
            impact_summary = snapshot["impact_graph_summary"]
            shared = {
                item["target"]: item
                for item in impact_edge_metadata(target, impact_summary["latest_snapshot_id"], "likely_touches")
                if item["target"] in {"src/alpha.py", "src/beta.py"}
            }

            self.assertEqual("symbol_owner_match_lsp_disambiguated", shared["src/beta.py"]["source"])
            self.assertEqual("confirmed", shared["src/beta.py"]["lsp_status"])
            self.assertTrue(shared["src/beta.py"]["write_candidate"])
            self.assertEqual("symbol_owner_match_lsp_downgraded", shared["src/alpha.py"]["source"])
            self.assertEqual("downgraded", shared["src/alpha.py"]["lsp_status"])
            self.assertFalse(shared["src/alpha.py"]["write_candidate"])

    def test_import_adjacency_is_reduced_confidence_context_not_direct_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/helper.ts", "export const value = 1;\n")
            write_text(target, "src/app.ts", "import { value } from './helper';\nexport const app = value;\n")
            self.write_ticket_run(
                target,
                [{"id": "T1", "summary": "Update src/app.ts behavior", "status": "pending"}],
            )

            snapshot = state_snapshot(target)
            helper = context_item_by_path(snapshot, "src/helper.ts")

            self.assertEqual("import_adjacency", helper["signal_kind"])
            self.assertFalse(helper["write_candidate"])
            self.assertLess(helper["confidence"], context_item_by_path(snapshot, "src/app.ts")["confidence"])

    def test_cross_language_interface_bridge_is_scoping_context_not_write_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(
                target,
                "api/openapi.yaml",
                "openapi: 3.1.0\npaths:\n  /api/users/{id}:\n    get:\n      operationId: getUser\ncomponents:\n  schemas:\n    User:\n      type: object\n",
            )
            write_text(target, "src/users.ts", "export class UsersApi { getUser() { return fetch('/api/users/:id'); } }\n")
            self.write_ticket_run(
                target,
                [{"id": "T1", "summary": "Update api/openapi.yaml user contract", "status": "pending"}],
            )

            snapshot = state_snapshot(target)
            openapi = context_item_by_path(snapshot, "api/openapi.yaml")
            users = context_item_by_path(snapshot, "src/users.ts")

            self.assertEqual("direct_path", openapi["signal_kind"])
            self.assertTrue(openapi["write_candidate"])
            self.assertEqual("interface_bridge", users["signal_kind"])
            self.assertFalse(users["write_candidate"])
            self.assertLess(users["confidence"], openapi["confidence"])

    def test_symbol_context_pack_explains_symbols_tests_neighbors_and_reasons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/__init__.py", "")
            write_text(target, "src/auth.py", "class AuthService:\n    def refresh(self):\n        return True\n")
            write_text(target, "src/app.py", "from src.auth import AuthService\nservice = AuthService()\n")
            write_text(target, "tests/test_auth.py", "from src.auth import AuthService\ndef test_auth():\n    assert AuthService()\n")
            self.write_ticket_run(
                target,
                [{"id": "T1", "summary": "Update AuthService refresh behavior", "status": "pending"}],
            )

            snapshot = state_snapshot(target)
            symbol_context = snapshot["context_pack_preview"]["symbol_context"]

            self.assertTrue(symbol_context["bounded"])
            self.assertTrue(any(item.get("qualified_name") == "src.auth.AuthService" for item in symbol_context["direct_symbols"]))
            self.assertTrue(any(item.get("path") == "src/auth.py" for item in symbol_context["owning_files"]))
            self.assertTrue(any(item.get("path") == "tests/test_auth.py" for item in symbol_context["likely_tests"]))
            self.assertTrue(any(item.get("path") == "src/app.py" for item in symbol_context["dependency_neighbors"]))
            self.assertTrue(all(item.get("reason") for item in symbol_context["confidence_reasons"]))

    def test_symbol_context_pack_exposes_interface_edges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(
                target,
                "api/openapi.yaml",
                "openapi: 3.1.0\npaths:\n  /api/users/{id}:\n    get:\n      operationId: getUser\ncomponents:\n  schemas:\n    User:\n      type: object\n",
            )
            write_text(target, "src/users.ts", "export class UsersApi { getUser() { return fetch('/api/users/:id'); } }\n")
            self.write_ticket_run(
                target,
                [{"id": "T1", "summary": "Update api/openapi.yaml user contract", "status": "pending"}],
            )

            snapshot = state_snapshot(target)
            interface_edges = snapshot["context_pack_preview"]["symbol_context"]["interface_edges"]

            self.assertTrue(interface_edges)
            self.assertTrue(all(item.get("signal_kind") == "interface_bridge" for item in interface_edges))
            self.assertTrue(any(item.get("path") == "src/users.ts" for item in interface_edges))
            self.assertTrue(all(item.get("reason") for item in interface_edges))

    def test_ambiguous_semantic_reference_never_becomes_direct_write_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/alpha.ts", "export class Shared {}\n")
            write_text(target, "src/beta.ts", "export class Shared {}\n")
            write_text(target, "src/consumer.ts", "export const useShared = (value: Shared) => value;\n")
            self.write_ticket_run(
                target,
                [{"id": "T1", "summary": "Update src/consumer.ts handling", "status": "pending"}],
            )

            snapshot = state_snapshot(target)
            alpha = context_item_by_path(snapshot, "src/alpha.ts")
            beta = context_item_by_path(snapshot, "src/beta.ts")

            self.assertEqual("ambiguous_semantic_reference", alpha["signal_kind"])
            self.assertEqual("ambiguous_semantic_reference", beta["signal_kind"])
            self.assertFalse(alpha["write_candidate"])
            self.assertFalse(beta["write_candidate"])

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

    def test_symbol_context_pack_is_deterministic_and_size_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            for index in range(20):
                write_text(target, f"src/auth/part_{index:02d}.py", f"AUTH_{index} = True\n")
            self.write_ticket_run(
                target,
                [
                    {
                        "id": "T1",
                        "summary": "Review auth module coverage",
                        "status": "pending",
                        "execution_mode": "read_only",
                        "action_kind": "read_only_analysis",
                    }
                ],
            )

            first = state_snapshot(target)["context_pack_preview"]["symbol_context"]
            second = state_snapshot(target)["context_pack_preview"]["symbol_context"]
            excluded = first["excluded_low_confidence_candidates"]

            self.assertEqual(first, second)
            self.assertLessEqual(len(first["direct_symbols"]), first["limits"]["direct_symbols"])
            self.assertLessEqual(len(first["owning_files"]), first["limits"]["owning_files"])
            self.assertLessEqual(len(excluded), first["limits"]["excluded_low_confidence_candidates"])
            self.assertTrue(excluded)
            self.assertTrue(all(item.get("exclusion_reason") for item in excluded))

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

    def test_disjoint_symbol_leases_share_file_without_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "class AuthLogin:\n    pass\n\nclass AuthTokens:\n    pass\n")
            graph = refresh_codebase_graph(target)
            symbols = {str(item["name"]): item for item in symbol_nodes(target, str(graph["latest_snapshot_id"]))}

            acquired = acquire_resource_lease(
                target,
                task_id="T1",
                owner_role="builder",
                run_id="run-1",
                scope_kind="symbol",
                scope_node_id=str(symbols["AuthLogin"]["node_id"]),
            )
            disjoint_conflicts = list_conflicting_leases(
                target,
                task_id="T2",
                owner_role="builder",
                run_id="run-2",
                scope_kind="symbol",
                scope_node_id=str(symbols["AuthTokens"]["node_id"]),
            )
            same_conflicts = list_conflicting_leases(
                target,
                task_id="T3",
                owner_role="builder",
                run_id="run-3",
                scope_kind="symbol",
                scope_node_id=str(symbols["AuthLogin"]["node_id"]),
            )

            self.assertTrue(acquired["acquired"])
            self.assertEqual([], disjoint_conflicts)
            self.assertEqual(1, len(same_conflicts))
            self.assertEqual("same symbol node", same_conflicts[0]["reason"])

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

    def read_only_scope_groups(self, snapshot: dict[str, object]) -> list[dict[str, object]]:
        groups = snapshot.get("proposed_execution_groups") if isinstance(snapshot.get("proposed_execution_groups"), list) else []
        return [
            group
            for group in groups
            if isinstance(group, dict)
            and isinstance(group.get("payload"), dict)
            and group["payload"].get("execution_mode") == "read_only"
            and group["payload"].get("scope_evidence_required")
        ]

    def upsert_ready_dag_node(
        self,
        target: Path,
        *,
        node_id: str,
        task_id: str,
        summary: str,
        paths: list[str] | None = None,
        symbols: list[str] | None = None,
    ) -> None:
        metadata: dict[str, object] = {"source": "test.parallel_planner", "summary": summary}
        if paths is not None:
            metadata["paths"] = paths
        if symbols is not None:
            metadata["symbols"] = symbols
        with closing(connect(database_path_for_target(target))) as conn:
            with conn:
                upsert_execution_dag_node(
                    conn,
                    node_id=node_id,
                    task_id=task_id,
                    action_type="build",
                    status="ready",
                    owner_role="builder",
                    confidence=0.9,
                    metadata=metadata,
                )

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
            self.assertEqual("execution_dag", snapshot["parallelization_summary"]["planner_source"])
            self.assertEqual(0.75, snapshot["parallelization_summary"]["policy"]["direct_write_confidence_threshold"])
            self.assertEqual("dag_action_capabilities", snapshot["parallelization_summary"]["scheduler_basis"])
            self.assertGreaterEqual(snapshot["parallelization_summary"]["fast_path_build_count"], 2)
            group = snapshot["proposed_execution_groups"][0]
            self.assertEqual("dry_run", group["mode"])
            self.assertEqual("write_workers", group["payload"]["execution_mode"])
            self.assertEqual("ready_execution_wave", group["payload"]["wave_kind"])
            self.assertEqual("dag_action_capabilities", group["payload"]["scheduler_basis"])
            self.assertTrue(group["execution_group_id"].startswith("execution-group:"))
            self.assertTrue(all(item["item_id"].startswith("execution-group-item:") for item in group["items"]))
            self.assertEqual({"build"}, {item["payload"]["canonical_action_type"] for item in group["items"]})

    def test_independent_docs_and_test_write_shapes_share_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "docs/auth.md", "# Auth\n")
            write_text(target, "tests/test_auth.py", "def test_auth():\n    assert True\n")
            self.write_ticket_run(
                target,
                [
                    {"id": "T1", "summary": "Update docs/auth.md", "status": "pending"},
                    {"id": "T2", "summary": "Update tests/test_auth.py", "status": "pending"},
                ],
            )

            snapshot = state_snapshot(target)
            group = snapshot["proposed_execution_groups"][0]
            leases = [
                lease
                for item in group["items"]
                for lease in item["required_leases"]
                if isinstance(lease, dict)
            ]

            self.assertIn({"T1", "T2"}, self.grouped_task_ids(snapshot))
            self.assertEqual({"docs", "tests"}, {lease["scope_kind"] for lease in leases})
            self.assertTrue(all(lease["ownership_kind"] in {"docs_only", "tests_only"} for lease in leases))
            self.assertEqual(1, snapshot["parallelization_summary"]["group_count"])

    def test_independent_module_write_shapes_share_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "def login():\n    return True\n")
            write_text(target, "src/billing.py", "def invoice():\n    return True\n")
            self.write_ticket_run(
                target,
                [
                    {"id": "T1", "summary": "Update src/auth.py", "status": "pending"},
                    {"id": "T2", "summary": "Update src/billing.py", "status": "pending"},
                ],
            )

            snapshot = state_snapshot(target)
            group = snapshot["proposed_execution_groups"][0]
            leases = [
                lease
                for item in group["items"]
                for lease in item["required_leases"]
                if isinstance(lease, dict)
            ]

            self.assertIn({"T1", "T2"}, self.grouped_task_ids(snapshot))
            self.assertEqual({"module"}, {lease["scope_kind"] for lease in leases})
            self.assertEqual({"src.auth", "src.billing"}, {lease["module_name"] for lease in leases})
            self.assertEqual(1, snapshot["parallelization_summary"]["group_count"])

    def test_multi_file_package_write_uses_package_lease(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "go.mod", "module example.com/demo\n")
            write_text(target, "service/auth.go", "package service\nfunc Login() bool { return true }\n")
            write_text(target, "service/session.go", "package service\nfunc Session() bool { return true }\n")
            self.write_ticket_run(target, [{"id": "T1", "summary": "Completed ticket shell", "status": "done"}])
            self.upsert_ready_dag_node(
                target,
                node_id="dag-node:test:T1:service-package",
                task_id="T1",
                summary="Update service package ownership",
                paths=["service/auth.go", "service/session.go"],
            )

            snapshot = state_snapshot(target)
            group = snapshot["proposed_execution_groups"][0]
            leases = [
                lease
                for item in group["items"]
                for lease in item["required_leases"]
                if isinstance(lease, dict)
            ]

            self.assertEqual({"package"}, {lease["scope_kind"] for lease in leases})
            self.assertEqual({"example.com/demo"}, {lease["package_name"] for lease in leases})
            self.assertTrue(all("service/auth.go" in lease["owned_paths"] for lease in leases))

    def test_ticket_depends_on_blocks_cross_ticket_parallel_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "AUTH = True\n")
            write_text(target, "src/billing.py", "BILLING = True\n")
            self.write_ticket_run(
                target,
                [
                    {"id": "T1", "summary": "Update src/auth.py", "status": "pending"},
                    {"id": "T2", "summary": "Update src/billing.py", "status": "pending", "depends_on": ["T1"]},
                ],
            )

            snapshot = state_snapshot(target)
            blocked = snapshot["execution_dag"]["blocked_nodes"]

            self.assertNotIn({"T1", "T2"}, self.grouped_task_ids(snapshot))
            self.assertTrue(all("T2" not in group for group in self.grouped_task_ids(snapshot)))
            self.assertTrue(
                any(
                    item["task_id"] == "T2"
                    and item["action_type"] == "ticket"
                    and any(reason["kind"] == "dependency" for reason in item.get("blocked_reasons", []))
                    for item in blocked
                ),
                blocked,
            )

    def test_done_dependency_without_evidence_still_blocks_dependent_ticket(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "AUTH = True\n")
            write_text(target, "src/billing.py", "BILLING = True\n")
            self.write_ticket_run(
                target,
                [
                    {"id": "T1", "summary": "Update src/auth.py", "status": "done", "evidence": []},
                    {"id": "T2", "summary": "Update src/billing.py", "status": "pending", "depends_on": ["T1"]},
                ],
            )

            snapshot = state_snapshot(target)
            blocked = snapshot["execution_dag"]["blocked_nodes"]

            self.assertTrue(all("T2" not in group for group in self.grouped_task_ids(snapshot)))
            self.assertTrue(
                any(item["task_id"] == "T1" and item["action_type"] == "completion" for item in blocked),
                blocked,
            )
            self.assertTrue(
                any(
                    item["task_id"] == "T2"
                    and item["action_type"] == "ticket"
                    and any(reason["kind"] == "dependency" for reason in item.get("blocked_reasons", []))
                    for item in blocked
                ),
                blocked,
            )

    def test_done_dependency_with_evidence_unblocks_dependent_ticket(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "AUTH = True\n")
            write_text(target, "src/billing.py", "BILLING = True\n")
            self.write_ticket_run(
                target,
                [
                    {"id": "T1", "summary": "Update src/auth.py", "status": "done", "evidence": ["pytest passed"]},
                    {"id": "T2", "summary": "Update src/billing.py", "status": "pending", "depends_on": ["T1"]},
                ],
            )

            snapshot = state_snapshot(target)

            self.assertTrue(any("T2" in group for group in self.grouped_task_ids(snapshot)), snapshot["proposed_execution_groups"])

    def test_low_confidence_ticket_gets_scope_before_build(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "AUTH = True\n")
            self.write_ticket_run(target, [{"id": "T1", "summary": "Improve login flow", "status": "pending"}])

            snapshot = state_snapshot(target)
            ready = snapshot["execution_dag"]["ready_nodes"]
            blocked = snapshot["execution_dag"]["blocked_nodes"]
            telemetry = snapshot["parallelization_summary"]["role_specialization_telemetry"]

            self.assertTrue(any(item["task_id"] == "T1" and item["action_type"] == "scope" for item in ready))
            self.assertTrue(any(item["task_id"] == "T1" and item["action_type"] == "build" for item in blocked))
            self.assertGreaterEqual(telemetry["specialization_added_count"], 1)
            self.assertEqual("expected_reduced_failures", telemetry["failure_effect"])

    def test_optional_review_does_not_block_ready_build_fast_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/app.py", "APP = True\n")
            with closing(connect(database_path_for_target(target))) as conn:
                with conn:
                    upsert_execution_dag_node(
                        conn,
                        node_id="dag-node:test:build-fast",
                        task_id="T1",
                        action_type="build",
                        status="ready",
                        owner_role="builder",
                        confidence=0.92,
                        metadata={"source": "test.parallel_planner", "summary": "Update src/app.py", "paths": ["src/app.py"]},
                    )
                    upsert_execution_dag_node(
                        conn,
                        node_id="dag-node:test:review-optional",
                        task_id="T1",
                        action_type="review",
                        status="ready",
                        owner_role="hardener",
                        confidence=0.7,
                        metadata={"source": "test.parallel_planner", "summary": "Review src/app.py", "paths": ["src/app.py"]},
                    )

            snapshot = state_snapshot(target)
            groups = snapshot["proposed_execution_groups"]
            write_group = next(group for group in groups if group["payload"]["execution_mode"] == "write_workers")

            self.assertEqual({"dag-node:test:build-fast"}, {item["payload"]["dag_node_id"] for item in write_group["items"]})
            self.assertEqual("build", write_group["items"][0]["payload"]["canonical_action_type"])

    def test_same_ticket_write_fanout_groups_only_disjoint_dag_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth_login.py", "LOGIN = True\n")
            write_text(target, "src/auth_tokens.py", "TOKENS = True\n")
            self.write_ticket_run(target, [{"id": "T1", "summary": "Completed ticket shell", "status": "done"}])
            self.upsert_ready_dag_node(
                target,
                node_id="dag-node:test:T1:login",
                task_id="T1",
                summary="Update login ownership",
                paths=["src/auth_login.py"],
            )
            self.upsert_ready_dag_node(
                target,
                node_id="dag-node:test:T1:tokens",
                task_id="T1",
                summary="Update token ownership",
                paths=["src/auth_tokens.py"],
            )

            snapshot = state_snapshot(target)
            group = snapshot["proposed_execution_groups"][0]
            items = group["items"]
            touch_paths = {
                touch["path"]
                for item in items
                for touch in item["payload"]["likely_touches"]
                if isinstance(touch, dict)
            }

            self.assertEqual(2, len(items))
            self.assertEqual({"T1"}, {item["task_id"] for item in items})
            self.assertEqual({"src/auth_login.py", "src/auth_tokens.py"}, touch_paths)
            self.assertEqual({"dag-node:test:T1:login", "dag-node:test:T1:tokens"}, {item["payload"]["dag_node_id"] for item in items})

    def test_same_ticket_write_fanout_blocks_overlapping_dag_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "AUTH = True\n")
            self.write_ticket_run(target, [{"id": "T1", "summary": "Completed ticket shell", "status": "done"}])
            self.upsert_ready_dag_node(
                target,
                node_id="dag-node:test:T1:first",
                task_id="T1",
                summary="Update first auth surface",
                paths=["src/auth.py"],
            )
            self.upsert_ready_dag_node(
                target,
                node_id="dag-node:test:T1:second",
                task_id="T1",
                summary="Update second auth surface",
                paths=["src/auth.py"],
            )

            snapshot = state_snapshot(target)
            blocked = snapshot.get("blocked_parallel_candidates") if isinstance(snapshot.get("blocked_parallel_candidates"), list) else []

            self.assertEqual([], snapshot["proposed_execution_groups"])
            self.assertTrue(any(isinstance(item, dict) and item.get("reason_kind") == "write_surface_overlap" for item in blocked), blocked)

    def test_overlapping_module_write_ownership_blocks_same_wave(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "def login():\n    return True\n")
            self.write_ticket_run(target, [{"id": "T1", "summary": "Completed ticket shell", "status": "done"}])
            self.upsert_ready_dag_node(
                target,
                node_id="dag-node:test:T1:auth-login",
                task_id="T1",
                summary="Update auth login",
                paths=["src/auth.py"],
            )
            self.upsert_ready_dag_node(
                target,
                node_id="dag-node:test:T1:auth-session",
                task_id="T1",
                summary="Update auth session",
                paths=["src/auth.py"],
            )

            snapshot = state_snapshot(target)
            blocked = snapshot.get("blocked_parallel_candidates") if isinstance(snapshot.get("blocked_parallel_candidates"), list) else []
            leases = [
                lease
                for item in blocked
                if isinstance(item, dict)
                for lease in (item.get("required_leases") if isinstance(item.get("required_leases"), list) else [])
                if isinstance(lease, dict)
            ]

            self.assertEqual([], snapshot["proposed_execution_groups"])
            self.assertEqual({"module"}, {lease["scope_kind"] for lease in leases})
            self.assertTrue(any("module" in str(item.get("reason") or "") for item in blocked if isinstance(item, dict)), blocked)

    def test_same_file_disjoint_symbol_write_fanout_uses_symbol_leases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "class AuthLogin:\n    pass\n\nclass AuthTokens:\n    pass\n")
            self.write_ticket_run(target, [{"id": "T1", "summary": "Completed ticket shell", "status": "done"}])
            self.upsert_ready_dag_node(
                target,
                node_id="dag-node:test:T1:login-symbol",
                task_id="T1",
                summary="Update AuthLogin behavior",
                symbols=["AuthLogin"],
            )
            self.upsert_ready_dag_node(
                target,
                node_id="dag-node:test:T1:token-symbol",
                task_id="T1",
                summary="Update AuthTokens behavior",
                symbols=["AuthTokens"],
            )

            snapshot = state_snapshot(target)
            group = snapshot["proposed_execution_groups"][0]
            items = group["items"]
            leases = [
                lease
                for item in items
                for lease in item["required_leases"]
                if isinstance(lease, dict)
            ]
            touch_paths = {
                touch["path"]
                for item in items
                for touch in item["payload"]["likely_touches"]
                if isinstance(touch, dict)
            }

            self.assertEqual(2, len(items))
            self.assertEqual({"src/auth.py"}, touch_paths)
            self.assertEqual({"symbol"}, {lease["scope_kind"] for lease in leases})
            self.assertEqual({"AuthLogin", "AuthTokens"}, {lease["symbol_name"] for lease in leases})
            self.assertTrue(all(lease["confidence"] >= 0.75 for lease in leases))
            self.assertEqual(1, snapshot["parallelization_summary"]["group_count"])

    def test_same_file_same_symbol_write_fanout_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "class AuthLogin:\n    pass\n")
            self.write_ticket_run(target, [{"id": "T1", "summary": "Completed ticket shell", "status": "done"}])
            self.upsert_ready_dag_node(
                target,
                node_id="dag-node:test:T1:login-first",
                task_id="T1",
                summary="Update AuthLogin validation",
                symbols=["AuthLogin"],
            )
            self.upsert_ready_dag_node(
                target,
                node_id="dag-node:test:T1:login-second",
                task_id="T1",
                summary="Update AuthLogin persistence",
                symbols=["AuthLogin"],
            )

            snapshot = state_snapshot(target)
            blocked = snapshot.get("blocked_parallel_candidates") if isinstance(snapshot.get("blocked_parallel_candidates"), list) else []

            self.assertEqual([], snapshot["proposed_execution_groups"])
            self.assertTrue(
                any(
                    isinstance(item, dict)
                    and item.get("reason_kind") == "write_surface_overlap"
                    and "symbol ownership overlaps" in str(item.get("reason") or "")
                    for item in blocked
                ),
                blocked,
            )

    def test_weak_extractor_same_file_symbols_fall_back_to_file_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.ts", "export class LoginPanel {}\n\nexport class TokenPanel {}\n")
            self.write_ticket_run(target, [{"id": "T1", "summary": "Completed ticket shell", "status": "done"}])
            self.upsert_ready_dag_node(
                target,
                node_id="dag-node:test:T1:login-panel",
                task_id="T1",
                summary="Update LoginPanel behavior",
                symbols=["LoginPanel"],
            )
            self.upsert_ready_dag_node(
                target,
                node_id="dag-node:test:T1:token-panel",
                task_id="T1",
                summary="Update TokenPanel behavior",
                symbols=["TokenPanel"],
            )

            snapshot = state_snapshot(target)
            blocked = snapshot.get("blocked_parallel_candidates") if isinstance(snapshot.get("blocked_parallel_candidates"), list) else []
            fallback = [
                lease
                for item in blocked
                if isinstance(item, dict)
                for lease in (item.get("required_leases") if isinstance(item.get("required_leases"), list) else [])
                if isinstance(lease, dict) and lease.get("symbol_lease_fallback_reason")
            ]

            self.assertEqual([], snapshot["proposed_execution_groups"])
            self.assertTrue(fallback, blocked)
            self.assertEqual({"file"}, {lease["scope_kind"] for lease in fallback})
            self.assertTrue(any("parser confidence" in str(lease.get("symbol_lease_fallback_reason") or "") for lease in fallback))
            self.assertTrue(any("symbol-level lease unavailable" in str(item.get("reason") or "") for item in blocked if isinstance(item, dict)), blocked)

    def test_stale_symbol_ownership_blocks_same_wave_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "class AuthLogin:\n    pass\n\nclass AuthTokens:\n    pass\n")
            graph = refresh_codebase_graph(target)
            with connect_graph(target) as conn:
                conn.execute(
                    """
                    UPDATE graph_nodes
                    SET is_stale = 1
                    WHERE snapshot_id = ?
                      AND graph_namespace = 'codebase'
                      AND kind = 'symbol'
                    """,
                    (graph["latest_snapshot_id"],),
                )
                conn.commit()
            self.write_ticket_run(target, [{"id": "T1", "summary": "Completed ticket shell", "status": "done"}])
            self.upsert_ready_dag_node(
                target,
                node_id="dag-node:test:T1:stale-login",
                task_id="T1",
                summary="Update AuthLogin behavior",
                symbols=["AuthLogin"],
            )
            self.upsert_ready_dag_node(
                target,
                node_id="dag-node:test:T1:stale-token",
                task_id="T1",
                summary="Update AuthTokens behavior",
                symbols=["AuthTokens"],
            )

            snapshot = state_snapshot(target)
            blocked = snapshot.get("blocked_parallel_candidates") if isinstance(snapshot.get("blocked_parallel_candidates"), list) else []

            self.assertEqual([], snapshot["proposed_execution_groups"])
            self.assertTrue(
                any(
                    isinstance(item, dict)
                    and item.get("reason_kind") == "missing_direct_write_signal"
                    and "stale_symbol" in item.get("confidence_signals", [])
                    for item in blocked
                ),
                blocked,
            )
            why_groups = {
                item["reason_kind"]: item
                for item in snapshot["why_not_parallel"]["reason_groups"]
                if isinstance(item, dict)
            }
            self.assertIn("stale_symbol", why_groups)
            self.assertIn("Refresh the codebase index", why_groups["stale_symbol"]["next_action"])

    def test_ambiguous_symbol_ownership_blocks_same_wave_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/alpha.py", "class Shared:\n    pass\n")
            write_text(target, "src/beta.py", "class Shared:\n    pass\n")
            self.write_ticket_run(target, [{"id": "T1", "summary": "Completed ticket shell", "status": "done"}])
            self.upsert_ready_dag_node(
                target,
                node_id="dag-node:test:T1:shared-first",
                task_id="T1",
                summary="Update Shared validation",
                symbols=["Shared"],
            )
            self.upsert_ready_dag_node(
                target,
                node_id="dag-node:test:T1:shared-second",
                task_id="T1",
                summary="Update Shared persistence",
                symbols=["Shared"],
            )

            snapshot = state_snapshot(target)
            blocked = snapshot.get("blocked_parallel_candidates") if isinstance(snapshot.get("blocked_parallel_candidates"), list) else []

            self.assertEqual([], snapshot["proposed_execution_groups"])
            self.assertTrue(
                any(
                    isinstance(item, dict)
                    and item.get("reason_kind") == "missing_direct_write_signal"
                    and "ambiguous_symbol" in item.get("confidence_signals", [])
                    for item in blocked
                ),
                blocked,
            )

    def test_symbol_matches_unlock_parallel_write_group_without_path_mentions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "class AuthService:\n    pass\n")
            write_text(target, "src/billing.py", "class BillingService:\n    pass\n")
            self.write_ticket_run(
                target,
                [
                    {"id": "T1", "summary": "Update AuthService behavior", "status": "pending"},
                    {"id": "T2", "summary": "Update BillingService behavior", "status": "pending"},
                ],
            )

            snapshot = state_snapshot(target)

            self.assertIn({"T1", "T2"}, self.grouped_task_ids(snapshot))
            group = snapshot["proposed_execution_groups"][0]
            touches = [
                touch
                for item in group["items"]
                for touch in item["payload"]["likely_touches"]
                if isinstance(touch, dict)
            ]
            self.assertEqual({"exact_symbol"}, {touch["signal_kind"] for touch in touches})
            self.assertEqual(1, snapshot["parallelization_summary"]["group_count"])

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
            why = snapshot["why_not_parallel"]
            why_groups = {item["reason_kind"]: item for item in why["reason_groups"] if isinstance(item, dict)}
            rendered = render_canonical_state_brief(snapshot, target=target)

            self.assertIn("write_surface_overlap", why["reason_counts"])
            self.assertIn("write_surface_overlap", snapshot["parallelization_summary"]["blocked_reason_counts"])
            self.assertIn("Split ownership", why_groups["write_surface_overlap"]["next_action"])
            self.assertIn("## Why Not Parallel?", rendered)
            self.assertIn("kind=write_surface_overlap", rendered)

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

    def test_unknown_impact_write_task_uses_scope_evidence_group_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth.py", "AUTH = True\n")
            self.write_ticket_run(target, [{"id": "T1", "summary": "Implement safer defaults", "status": "pending"}])

            snapshot = state_snapshot(target)
            scope_groups = self.read_only_scope_groups(snapshot)
            group = scope_groups[0]
            item = group["items"][0]
            payload = item["payload"]

            self.assertEqual(1, len(scope_groups))
            self.assertEqual({"T1"}, self.grouped_task_ids(snapshot)[0])
            self.assertEqual("scope", payload["canonical_action_type"])
            self.assertEqual([], item["required_leases"])
            self.assertTrue(payload["scope_evidence_required"])
            self.assertEqual("unknown_scoping_context", payload["scope_fanout_reason_kind"])
            self.assertIn("risk_notes", payload["scope_evidence"])
            self.assertTrue(any(note["kind"] == "no_likely_paths" for note in payload["scope_evidence"]["risk_notes"]))

    def test_generated_ticket_id_does_not_create_direct_write_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.write_ticket_run(
                target,
                [
                    {
                        "id": "TICKET-001",
                        "summary": "Create local project directory layout",
                        "status": "pending",
                    }
                ],
            )

            snapshot = state_snapshot(target)
            nodes = [
                item
                for item in snapshot["execution_dag"]["nodes"]
                if isinstance(item, dict) and item.get("task_id") == "TICKET-001"
            ]
            build = next(item for item in nodes if item["action_type"] == "build")
            metadata = build["metadata"]
            scope_groups = self.read_only_scope_groups(snapshot)
            scope_items = [
                item
                for group in scope_groups
                for item in group.get("items", [])
                if isinstance(item, dict) and item.get("task_id") == "TICKET-001"
            ]

            self.assertEqual("waiting", build["status"])
            self.assertFalse(metadata["direct_write_signal"])
            self.assertTrue(metadata["requires_scope"])
            self.assertNotIn("TICKET", metadata["symbols"])
            self.assertEqual(1, len(scope_items))
            self.assertEqual("scope", scope_items[0]["payload"]["canonical_action_type"])
            self.assertEqual("unknown_scoping_context", scope_items[0]["payload"]["scope_fanout_reason_kind"])
            self.assertEqual([], scope_items[0]["required_leases"])

    def test_vague_keyword_only_impact_uses_read_only_scope_fanout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_text(target, "src/auth/session.py", "SESSION = True\n")
            write_text(target, "src/billing/invoice.py", "INVOICE = True\n")
            self.write_ticket_run(
                target,
                [
                    {"id": "T1", "summary": "Improve auth defaults", "status": "pending"},
                    {"id": "T2", "summary": "Improve billing defaults", "status": "pending"},
                ],
            )

            snapshot = state_snapshot(target)
            scope_groups = self.read_only_scope_groups(snapshot)
            item_payloads = {
                str(item.get("task_id") or ""): item["payload"]
                for group in scope_groups
                for item in group.get("items", [])
                if isinstance(item, dict)
            }

            self.assertEqual(1, len(scope_groups))
            self.assertEqual({"T1", "T2"}, set(item_payloads))
            self.assertEqual("insufficient_scoping_confidence", item_payloads["T1"]["scope_fanout_reason_kind"])
            self.assertEqual("scoping_read_confidence", item_payloads["T1"]["missing_confidence_signal"])
            self.assertEqual("scope", item_payloads["T1"]["canonical_action_type"])
            self.assertEqual("insufficient_scoping_confidence", item_payloads["T2"]["scope_fanout_reason_kind"])
            self.assertTrue(item_payloads["T1"]["scope_evidence"]["ownership_evidence"])

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
            item_payloads = [
                item["payload"]
                for group in second["proposed_execution_groups"]
                for item in group.get("items", [])
                if isinstance(item, dict) and isinstance(item.get("payload"), dict)
            ]
            self.assertTrue(item_payloads)
            for payload in item_payloads:
                preview = payload.get("context_pack_preview")
                self.assertIsInstance(preview, dict)
                self.assertTrue(preview.get("deduplicated"))
                self.assertTrue(preview.get("context_pack_digest"))
                self.assertLessEqual(len(preview.get("items") or []), state_store_module.CONTEXT_PACK_INLINE_ITEM_LIMIT)
            with connect_graph(target) as conn:
                rows = conn.execute(
                    "SELECT payload_json FROM execution_group_items ORDER BY item_id"
                ).fetchall()
            self.assertTrue(rows)
            self.assertTrue(all(len(row["payload_json"].encode("utf-8")) < 6000 for row in rows))


if __name__ == "__main__":
    unittest.main()
