from __future__ import annotations

import importlib
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "validation" / "starter_kit_manifest.json"
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def load_validator_module():
    return importlib.import_module("diffmogger.kit.validate_starter_kit_manifest")


class StarterKitManifestTests(unittest.TestCase):
    def test_manifest_shape_and_required_files_are_current(self) -> None:
        module = load_validator_module()
        manifest = module.load_manifest(MANIFEST)

        self.assertEqual([], module.validate_manifest_shape(manifest))
        self.assertEqual([], module.check_required_files(ROOT, manifest))
        self.assertIn("dashboard_native", manifest["required_file_groups"])
        self.assertIn(
            "services/agentic-dashboard/native/src/App.tsx",
            manifest["required_file_groups"]["dashboard_native"],
        )
        self.assertIn(
            "src/diffmogger/kit/scaffold_project_docs.py",
            manifest["required_file_groups"]["source_package"],
        )
        self.assertEqual([], manifest["script_wrapper_policy"]["allowed_non_wrapper_scripts"])
        self.assertIn("scripts/run_dashboard.py", manifest["forbidden_paths"])
        self.assertFalse(manifest["generated_smoke_target"]["allow_dashboard_backend_bundle"])

    def test_entrypoints_are_wrappers_over_package_sources(self) -> None:
        module = load_validator_module()
        manifest = module.load_manifest(MANIFEST)

        self.assertEqual([], module.check_runtime_entrypoints(ROOT, manifest))
        self.assertEqual([], module.check_script_wrapper_policy(ROOT, manifest))
        self.assertEqual([], module.check_runtime_source_ownership(ROOT, manifest))
        self.assertEqual([], module.check_wrapper_template_single_source(ROOT, manifest))
        self.assertEqual([], module.check_forbidden_paths(ROOT, manifest))

    def test_generated_runtime_wrappers_are_manifest_driven(self) -> None:
        module = load_validator_module()
        manifest = module.load_manifest(MANIFEST)

        self.assertEqual([], module.check_no_template_python_wrappers(ROOT, manifest))
        self.assertEqual([], module.check_generated_runtime_wrappers(ROOT, manifest))

    def test_active_docs_match_docs_map(self) -> None:
        module = load_validator_module()
        manifest = module.load_manifest(MANIFEST)

        self.assertEqual([], module.check_docs_policy(ROOT, manifest))

    def test_artifact_paths_are_ignored(self) -> None:
        module = load_validator_module()
        manifest = module.load_manifest(MANIFEST)

        self.assertEqual([], module.check_ignored_artifact_paths(ROOT, manifest))

    def test_runtime_entrypoint_reports_missing_package_import(self) -> None:
        module = load_validator_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "scripts").mkdir(parents=True)
            (root / "src/diffmogger/runtime").mkdir(parents=True)
            (root / "src/diffmogger/kit").mkdir(parents=True)
            (root / "scripts/example.py").write_text("print('not a wrapper')\n", encoding="utf-8")
            (root / "src/diffmogger/runtime/example.py").write_text("def main(): return 0\n", encoding="utf-8")
            (root / "src/diffmogger/kit/wrapper_template.py").write_text(
                "def render_wrapper(module):\n"
                "    return 'from ' + module + ' import *\\nrun_module(\"' + module + '\")\\n'\n",
                encoding="utf-8",
            )
            manifest = {
                "schema_version": 1,
                "canonical_wrapper_template": "src/diffmogger/kit/wrapper_template.py",
                "required_file_groups": {"smoke": ["scripts/example.py"]},
                "runtime_entrypoints": [
                    {
                        "script": "scripts/example.py",
                        "module": "diffmogger.runtime.example",
                        "source": "src/diffmogger/runtime/example.py",
                    }
                ],
                "ignored_artifact_paths": [],
            }

            errors = module.check_runtime_entrypoints(root, manifest)

        self.assertIn(
            "runtime entrypoint scripts/example.py does not re-export diffmogger.runtime.example",
            errors,
        )


if __name__ == "__main__":
    unittest.main()
