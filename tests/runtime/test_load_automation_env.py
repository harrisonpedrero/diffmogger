from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
LOAD_ENV_PATHS = [
    ROOT / "src" / "diffmogger" / "runtime" / "load_automation_env.py",
]
LOAD_ENV_WRAPPER_PATHS = [
    ROOT / "scripts" / "runtime" / "load_automation_env.py",
]


def load_env_module(path: Path):
    module_name = "load_env_under_test_" + path.relative_to(ROOT).as_posix().replace("/", "_").replace(".", "_")
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class LoadAutomationEnvTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.modules = [(path, load_env_module(path)) for path in LOAD_ENV_PATHS]

    def write_text(self, root: Path, relative: str, content: str) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_source_helper_is_runtime_wrapper(self) -> None:
        for path in LOAD_ENV_WRAPPER_PATHS:
            text = path.read_text(encoding="utf-8")
            self.assertIn("diffmogger.runtime.load_automation_env", text)
            self.assertIn('"lib"', text)

    def test_default_root_and_monorepo_env_files_are_loaded_without_overriding_shell(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.write_text(
                        target,
                        ".env",
                        "AUTH_SECRET=file-secret\nROOT_ONLY=root\nSHARED=from-root\n",
                    )
                    self.write_text(
                        target,
                        "apps/web/.env.local",
                        "APP_LOCAL_ONLY=from-app\nSHARED=from-app\nAUTH_SECRET=app-file-secret\n",
                    )

                    env = module.build_environment(
                        target,
                        {
                            "AUTH_SECRET": "shell-secret",
                            "PATH": "/usr/bin",
                        },
                    )

                    self.assertEqual("shell-secret", env["AUTH_SECRET"])
                    self.assertEqual("root", env["ROOT_ONLY"])
                    self.assertEqual("from-app", env["APP_LOCAL_ONLY"])
                    self.assertEqual("from-app", env["SHARED"])
                    self.assertEqual("1", env[module.SENTINEL])

    def test_explicit_env_files_and_denylist_are_honored(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.write_text(target, ".env", "DEFAULT_ONLY=not-loaded\n")
                    self.write_text(target, "config/local.env", "CUSTOM_ONLY=yes\nBLOCKED_SECRET=hide-me\n")

                    env = module.build_environment(
                        target,
                        {
                            "CODEX_AUTOMATION_ENV_FILES": "config/local.env",
                            "CODEX_AUTOMATION_ENV_DENYLIST": "BLOCKED_SECRET",
                            "BLOCKED_SECRET": "shell-hide-me",
                        },
                    )

                    self.assertEqual("yes", env["CUSTOM_ONLY"])
                    self.assertNotIn("DEFAULT_ONLY", env)
                    self.assertNotIn("BLOCKED_SECRET", env)
                    self.assertEqual("1", env[module.SENTINEL])


if __name__ == "__main__":
    unittest.main()
