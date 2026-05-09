from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def load_guardrail_module():
    return importlib.import_module("diffmogger.kit.check_native_rebuild_guardrails")


class NativeRebuildGuardrailTests(unittest.TestCase):
    def test_inventory_commands_are_preserved_in_backend_and_native_allowlist(self) -> None:
        module = load_guardrail_module()

        failures = module.check_guardrails()

        self.assertEqual([], failures)


if __name__ == "__main__":
    unittest.main()
