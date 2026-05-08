from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUARDRAILS = ROOT / "scripts" / "check_native_rebuild_guardrails.py"


def load_guardrail_module():
    spec = importlib.util.spec_from_file_location("native_rebuild_guardrails", GUARDRAILS)
    if spec is None or spec.loader is None:  # pragma: no cover - assertion helper.
        raise AssertionError(f"Could not load {GUARDRAILS}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NativeRebuildGuardrailTests(unittest.TestCase):
    def test_inventory_commands_are_preserved_in_backend_and_native_allowlist(self) -> None:
        module = load_guardrail_module()

        failures = module.check_guardrails()

        self.assertEqual([], failures)


if __name__ == "__main__":
    unittest.main()
