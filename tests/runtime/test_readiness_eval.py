from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from diffmogger.runtime.readiness_eval import (
    ReadinessThresholds,
    readiness_eval_scenarios,
    readiness_gate,
    run_readiness_eval,
)


class SymbolSchedulerReadinessEvalTests(unittest.TestCase):
    def test_fixture_scenarios_cover_required_quality_cases(self) -> None:
        tags = {
            tag
            for scenario in readiness_eval_scenarios()
            for tag in scenario.coverage_tags
        }

        self.assertTrue(
            {
                "direct_paths",
                "exact_symbols",
                "ambiguous_symbols",
                "stale_indexes",
                "imports",
                "cross_language_interfaces",
                "overlapping_ownership",
                "same_file_disjoint_symbols",
            }.issubset(tags)
        )

    def test_readiness_eval_reports_separate_direct_and_advisory_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = run_readiness_eval(fixture_root=Path(tmp))

        metrics = report["metrics"]
        self.assertIn("direct_write_precision", metrics)
        self.assertIn("advisory_impact_recall", metrics)
        self.assertGreaterEqual(metrics["direct_write_precision"], 0.95)
        self.assertGreaterEqual(metrics["advisory_impact_recall"], 0.75)
        self.assertGreaterEqual(metrics["scheduler_readiness"], 0.85)
        self.assertEqual("pass", report["gate"]["status"])
        self.assertTrue(report["coverage"]["complete"], report["coverage"])

    def test_eval_exposes_blocked_confidence_reasons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = run_readiness_eval(fixture_root=Path(tmp))

        by_name = {scenario["name"]: scenario for scenario in report["scenarios"]}
        ambiguous_blocked = by_name["ambiguous_symbol"]["blocked_parallel_candidates"]
        stale_blocked = by_name["stale_index"]["blocked_parallel_candidates"]
        overlap_blocked = by_name["overlapping_ownership"]["blocked_parallel_candidates"]

        self.assertTrue(
            any(
                item.get("missing_confidence_signal") == "direct_path_or_exact_symbol"
                and "ambiguous_symbol" in item.get("confidence_signals", [])
                for item in ambiguous_blocked
            ),
            ambiguous_blocked,
        )
        self.assertTrue(
            any(
                item.get("missing_confidence_signal") == "direct_path_or_exact_symbol"
                and "stale_symbol" in item.get("confidence_signals", [])
                for item in stale_blocked
            ),
            stale_blocked,
        )
        self.assertTrue(any(item.get("reason_kind") == "write_surface_overlap" for item in overlap_blocked), overlap_blocked)

    def test_first_24h_gate_warns_or_blocks_below_thresholds(self) -> None:
        report = {
            "metrics": {
                "direct_write_precision": 0.5,
                "advisory_impact_recall": 0.5,
                "scheduler_readiness": 0.5,
            },
            "coverage": {"complete": True},
        }
        thresholds = ReadinessThresholds(
            direct_write_precision_min=0.9,
            advisory_impact_recall_min=0.9,
            scheduler_readiness_min=0.9,
        )

        warned = readiness_gate(report, thresholds=thresholds, enforcement="warn")
        blocked = readiness_gate(report, thresholds=thresholds, enforcement="block")

        self.assertEqual("warn", warned["status"])
        self.assertEqual(0, warned["exit_code"])
        self.assertEqual("blocked", blocked["status"])
        self.assertNotEqual(0, blocked["exit_code"])

    def test_local_command_reports_json_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "evaluate_symbol_scheduler_readiness.py"),
                    "--json",
                    "--fixture-root",
                    tmp,
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual("symbol_scheduler_readiness_v1", report["harness"])
        self.assertIn("direct_write_precision", report["metrics"])
        self.assertIn("advisory_impact_recall", report["metrics"])

    def test_first_24h_command_blocks_below_configured_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "evaluate_symbol_scheduler_readiness.py"),
                    "--json",
                    "--first-24h",
                    "--strict",
                    "--scheduler-readiness-min",
                    "1.01",
                    "--fixture-root",
                    tmp,
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("READINESS_WARNING", result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual("blocked", report["gate"]["status"])


if __name__ == "__main__":
    unittest.main()
