from __future__ import annotations

import unittest
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
from diffmogger.runtime.blocker_review import adjudicate_baseline_blocker


class BlockerReviewTests(unittest.TestCase):
    def test_all_zero_ebadengine_baseline_is_false_positive_not_human(self) -> None:
        review = adjudicate_baseline_blocker(
            {
                "status": "blocked_environment",
                "category": "missing_env_var",
                "root_cause": "Missing required environment variable `EBADENGINE`.",
                "failure_signature": "verification_environment_failure:missing_env_var:abc",
                "checks_run": ["npm ci"],
                "detail": "\n".join(
                    [
                        "$ npm ci",
                        "exit=0",
                        "npm warn EBADENGINE Unsupported engine {",
                        "npm warn EBADENGINE   required: { node: '^20.19.0 || ^22.13.0 || >=24' }",
                        "npm warn EBADENGINE }",
                    ]
                ),
            }
        )

        self.assertEqual("false_positive", review["verdict"])
        self.assertFalse(review["is_blocker"])
        self.assertNotEqual("needs_human", review["verdict"])

    def test_warning_only_package_manager_output_downgrades_without_human(self) -> None:
        review = adjudicate_baseline_blocker(
            {
                "status": "blocked_environment",
                "category": "other",
                "root_cause": "npm warn EBADENGINE Unsupported engine",
                "failure_signature": "verification_environment_failure:other:abc",
                "checks_run": ["npm install"],
                "detail": "\n".join(
                    [
                        "$ npm install",
                        "npm warn EBADENGINE Unsupported engine",
                        "npm warn deprecated example@1.0.0: use a maintained package",
                    ]
                ),
            }
        )

        self.assertEqual("downgrade_to_warning", review["verdict"])
        self.assertFalse(review["is_blocker"])
        self.assertTrue(review["rerun_recommended"])

    def test_source_failure_misclassified_as_environment_gets_rerun_not_human(self) -> None:
        review = adjudicate_baseline_blocker(
            {
                "status": "blocked_environment",
                "category": "other",
                "root_cause": "Verification environment failed.",
                "failure_signature": "verification_environment_failure:other:abc",
                "checks_run": ["npm test"],
                "detail": "\n".join(
                    [
                        "$ npm test",
                        "exit=1",
                        "AssertionError: expected 1 received 2",
                    ]
                ),
            }
        )

        self.assertEqual("source_failure_not_environment", review["verdict"])
        self.assertFalse(review["is_blocker"])
        self.assertNotEqual("needs_human", review["verdict"])


if __name__ == "__main__":
    unittest.main()
