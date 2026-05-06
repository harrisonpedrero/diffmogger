from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
RUN_DASHBOARD_PATH = ROOT / "scripts" / "run_dashboard.py"


def load_run_dashboard_module():
    spec = importlib.util.spec_from_file_location("run_dashboard_under_test", RUN_DASHBOARD_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RunDashboardEnvTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_run_dashboard_module()

    def test_missing_dotenv_is_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env: dict[str, str] = {}

            loaded = self.module.load_repo_dotenv(Path(tmp), env)

            self.assertEqual(0, loaded)
            self.assertEqual({}, env)

    def test_dotenv_does_not_override_existing_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text(
                "CONTEXT7_API_KEY=from-dotenv\nNEW_OPTION=from-file\n",
                encoding="utf-8",
            )
            env = {"CONTEXT7_API_KEY": "from-shell"}

            loaded = self.module.load_repo_dotenv(root, env)

            self.assertEqual(1, loaded)
            self.assertEqual("from-shell", env["CONTEXT7_API_KEY"])
            self.assertEqual("from-file", env["NEW_OPTION"])

    def test_export_syntax_and_quoted_values_are_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text(
                "\n".join(
                    [
                        "# dashboard-local optional runtime values",
                        "export CONTEXT7_API_KEY='quoted-test-key'",
                        'DOUBLE_QUOTED="two words"',
                        "PLAIN=value # inline comment",
                        "HASH_VALUE='keep # hash'",
                        "ESCAPED=\"line\\nnext\"",
                        "MALFORMED",
                        "1INVALID=ignored",
                        "BAD-NAME=ignored",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            env: dict[str, str] = {}

            loaded = self.module.load_repo_dotenv(root, env)

            self.assertEqual(5, loaded)
            self.assertEqual("quoted-test-key", env["CONTEXT7_API_KEY"])
            self.assertEqual("two words", env["DOUBLE_QUOTED"])
            self.assertEqual("value", env["PLAIN"])
            self.assertEqual("keep # hash", env["HASH_VALUE"])
            self.assertEqual("line\nnext", env["ESCAPED"])
            self.assertNotIn("1INVALID", env)
            self.assertNotIn("BAD-NAME", env)

    def test_main_loads_repo_dotenv_before_importing_dashboard_app(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dashboard_root = root / "services" / "agentic-dashboard"
            package_dir = dashboard_root / "agentic_dashboard"
            package_dir.mkdir(parents=True)
            (package_dir / "__init__.py").write_text("", encoding="utf-8")
            (package_dir / "app.py").write_text(
                "\n".join(
                    [
                        "from pathlib import Path",
                        "import os",
                        "",
                        "def main():",
                        "    visible = 'yes' if os.environ.get('CONTEXT7_API_KEY') else 'no'",
                        "    Path(os.environ['DASHBOARD_TEST_RECORD']).write_text(visible + '\\n', encoding='utf-8')",
                        "    return 0",
                    ]
                ),
                encoding="utf-8",
            )
            (root / ".env").write_text("CONTEXT7_API_KEY=placeholder-context7-key\n", encoding="utf-8")
            record = root / "record.txt"
            old_root = self.module.KIT_ROOT
            old_dashboard_root = self.module.DASHBOARD_ROOT
            self.module.KIT_ROOT = root
            self.module.DASHBOARD_ROOT = dashboard_root
            sys.modules.pop("agentic_dashboard", None)
            sys.modules.pop("agentic_dashboard.app", None)
            stdout = io.StringIO()
            stderr = io.StringIO()

            try:
                with patch.dict(os.environ, {"DASHBOARD_TEST_RECORD": str(record)}, clear=True):
                    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                        code = self.module.main()
            finally:
                self.module.KIT_ROOT = old_root
                self.module.DASHBOARD_ROOT = old_dashboard_root
                sys.modules.pop("agentic_dashboard", None)
                sys.modules.pop("agentic_dashboard.app", None)
                try:
                    sys.path.remove(str(dashboard_root))
                except ValueError:
                    pass

            self.assertEqual(0, code)
            self.assertEqual("yes\n", record.read_text(encoding="utf-8"))
            self.assertNotIn("placeholder-context7-key", stdout.getvalue())
            self.assertNotIn("placeholder-context7-key", stderr.getvalue())

    def test_loaded_dotenv_values_are_visible_to_child_processes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("CONTEXT7_API_KEY=placeholder-context7-key\n", encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                self.module.load_repo_dotenv(root)
                result = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        "import os; raise SystemExit(0 if os.environ.get('CONTEXT7_API_KEY') else 1)",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )

            self.assertEqual(0, result.returncode)
            self.assertNotIn("placeholder-context7-key", result.stdout)
            self.assertNotIn("placeholder-context7-key", result.stderr)


if __name__ == "__main__":
    unittest.main()
