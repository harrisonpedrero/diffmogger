from __future__ import annotations

import hashlib
import importlib.util
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SUMMARIZER_PATHS = [
    ROOT / "scripts" / "summarize_worker_outputs.py",
    ROOT / "templates" / "scripts" / "summarize_worker_outputs.py",
]


def load_summarizer(path: Path):
    module_name = (
        "summarizer_under_test_"
        + path.relative_to(ROOT).as_posix().replace("/", "_").replace(".", "_")
    )
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class WorkerSummarizerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.modules = [(path, load_summarizer(path)) for path in SUMMARIZER_PATHS]

    def test_source_and_template_summarizers_stay_identical(self) -> None:
        source_path, template_path = SUMMARIZER_PATHS
        source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
        template_hash = hashlib.sha256(template_path.read_bytes()).hexdigest()

        self.assertEqual(
            source_hash,
            template_hash,
            (
                "scripts/summarize_worker_outputs.py and templates/scripts/"
                "summarize_worker_outputs.py must stay byte-identical."
            ),
        )

    def test_build_summary_extracts_highlights_in_stable_heading_order(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    run_dir = target / "target" / "agent_runs" / "run-001"
                    run_dir.mkdir(parents=True)
                    (run_dir / "worker_review.md").write_text(
                        textwrap.dedent(
                            """
                            # Worker Review

                            - status: PASS

                            ## Recommendations

                            - Add a broader dashboard smoke.

                            ## Findings

                            - Worker summaries should be deterministic.

                            ## Risks

                            - Unstable ordering makes review diffs noisy.
                            """
                        ).lstrip(),
                        encoding="utf-8",
                    )

                    output_path, summary = module.build_summary(target, "run-001")

                    self.assertEqual(run_dir / "summary.md", output_path)
                    self.assertIn("- `worker_review.md`: PASS", summary)
                    findings_index = summary.index("- Worker summaries should be deterministic.")
                    risks_index = summary.index("- Unstable ordering makes review diffs noisy.")
                    recommendations_index = summary.index("- Add a broader dashboard smoke.")
                    self.assertLess(findings_index, risks_index)
                    self.assertLess(risks_index, recommendations_index)

    def test_build_summary_ignores_legacy_worker_summary_report(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    run_dir = target / "target" / "agent_runs" / "run-legacy"
                    run_dir.mkdir(parents=True)
                    (run_dir / "worker_summary.md").write_text(
                        "- status: STALE\n\n## Findings\n\n- Old summary file.\n",
                        encoding="utf-8",
                    )

                    _, summary = module.build_summary(target, "run-legacy")

                    self.assertIn("- worker_reports: 0", summary)
                    self.assertIn("No worker reports were found for this run.", summary)
                    self.assertNotIn("Old summary file.", summary)


if __name__ == "__main__":
    unittest.main()
