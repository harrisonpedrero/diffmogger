from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
REPAIR_PATHS = [
    ROOT / "src" / "diffmogger" / "runtime" / "repair_environment.py",
]


def load_repair(path: Path):
    module_name = (
        "repair_environment_under_test_"
        + path.relative_to(ROOT).as_posix().replace("/", "_").replace(".", "_")
    )
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class RepairEnvironmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.modules = [(path, load_repair(path)) for path in REPAIR_PATHS]

    def test_ensure_info_exclude_uses_git_path_for_worktree_git_file(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    target = root / "worktree"
                    target.mkdir()
                    gitdir = root / "main.git" / "worktrees" / "role"
                    gitdir.mkdir(parents=True)
                    (target / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")

                    def fake_git(_target: Path, *args: str):
                        if args == ("rev-parse", "--is-inside-work-tree"):
                            return subprocess.CompletedProcess(["git", *args], 0, "true\n", "")
                        if args == ("rev-parse", "--git-path", "info/exclude"):
                            return subprocess.CompletedProcess(["git", *args], 0, str(gitdir / "info" / "exclude") + "\n", "")
                        return subprocess.CompletedProcess(["git", *args], 1, "", "unexpected git call")

                    original_git = module.git
                    try:
                        module.git = fake_git
                        module.ensure_info_exclude(target, ["/services/*/.venv/"])
                    finally:
                        module.git = original_git

                    exclude = gitdir / "info" / "exclude"
                    self.assertEqual(exclude.read_text(encoding="utf-8").strip(), "/services/*/.venv/")

    def test_successful_repair_rerun_clears_environment_failure(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)

                    def fake_repair_python_environment(_target, _command, _output, _diagnostics):
                        return "python -m pytest", ["using test venv"], ""

                    def fake_run_shell(_command, *, cwd, env=None):
                        return module.CommandRun(command=_command, exit_code=0, stdout="ok", stderr="")

                    original_repair = module.repair_python_environment
                    original_run_shell = module.run_shell
                    try:
                        module.repair_python_environment = fake_repair_python_environment
                        module.run_shell = fake_run_shell
                        outcome = module.diagnose_and_repair(
                            target,
                            "python3 -m pytest",
                            1,
                            "No module named pytest",
                            rerun=True,
                        )
                    finally:
                        module.repair_python_environment = original_repair
                        module.run_shell = original_run_shell

                    self.assertTrue(outcome.ok)
                    self.assertFalse(outcome.environment_failure)
                    self.assertEqual(outcome.final_exit_code, 0)

    def test_pyproject_test_extra_repairs_missing_pytest(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    (target / "pyproject.toml").write_text(
                        """
                        [project]
                        name = "demo"
                        version = "0.1.0"

                        [project.optional-dependencies]
                        test = ["pytest>=8"]
                        dev = ["ruff"]
                        """,
                        encoding="utf-8",
                    )
                    calls: list[list[str]] = []
                    installed = {"done": False}

                    def fake_run(args, *, cwd, env=None):
                        calls.append([str(item) for item in args])
                        if args[1:3] == ["-m", "venv"]:
                            python = Path(args[3]) / "bin" / "python"
                            python.parent.mkdir(parents=True, exist_ok=True)
                            python.write_text("#!/usr/bin/env sh\n", encoding="utf-8")
                            python.chmod(0o755)
                        if len(args) >= 5 and args[1:4] == ["-m", "pip", "install"]:
                            installed["done"] = True
                        return subprocess.CompletedProcess(args, 0, "", "")

                    def fake_python_can_import(_python_path, module_name):
                        return installed["done"] and module_name == "pytest"

                    def fake_run_shell(command, *, cwd, env=None):
                        return module.CommandRun(command=command, exit_code=0, stdout="pytest ok", stderr="")

                    original_run = module.run
                    original_python_can_import = module.python_can_import
                    original_run_shell = module.run_shell
                    try:
                        module.run = fake_run
                        module.python_can_import = fake_python_can_import
                        module.run_shell = fake_run_shell
                        outcome = module.diagnose_and_repair(
                            target,
                            "python3 -m pytest",
                            1,
                            "No module named pytest",
                            rerun=True,
                        )
                    finally:
                        module.run = original_run
                        module.python_can_import = original_python_can_import
                        module.run_shell = original_run_shell

                    self.assertTrue(outcome.ok)
                    self.assertTrue(outcome.repair_performed)
                    self.assertIn("target/automation_venvs/root/bin/python", outcome.final_command or "")
                    self.assertIn("-e", calls[-1])
                    self.assertIn(".[test]", calls[-1])

    def test_missing_pytest_without_declared_dependencies_blocks_repair(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    outcome = module.diagnose_and_repair(
                        target,
                        "python3 -m pytest",
                        1,
                        "No module named pytest",
                        rerun=True,
                    )

                    self.assertFalse(outcome.ok)
                    self.assertTrue(outcome.environment_failure)
                    self.assertFalse(outcome.repair_performed)
                    self.assertIn("No ignored local Python venv", outcome.blocked_reason)

    def test_existing_venv_with_pytest_is_reused(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    python = target / ".venv" / "bin" / "python"
                    python.parent.mkdir(parents=True)
                    python.write_text("#!/usr/bin/env sh\n", encoding="utf-8")
                    python.chmod(0o755)

                    def fake_python_can_import(_python_path, module_name):
                        return module_name == "pytest"

                    def fake_run_shell(command, *, cwd, env=None):
                        return module.CommandRun(command=command, exit_code=0, stdout="pytest ok", stderr="")

                    original_python_can_import = module.python_can_import
                    original_run_shell = module.run_shell
                    try:
                        module.python_can_import = fake_python_can_import
                        module.run_shell = fake_run_shell
                        outcome = module.diagnose_and_repair(
                            target,
                            "python3 -m pytest",
                            1,
                            "No module named pytest",
                            rerun=True,
                        )
                    finally:
                        module.python_can_import = original_python_can_import
                        module.run_shell = original_run_shell

                    self.assertTrue(outcome.ok)
                    self.assertIn(".venv/bin/python", outcome.final_command or "")
                    self.assertTrue(any("using existing local venv" in item for item in outcome.repairs))

    def test_existing_node_modules_cache_is_reused_without_reinstall(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    (target / "package.json").write_text('{"scripts":{"lint":"eslint ."}}\n', encoding="utf-8")
                    eslint = target / "node_modules" / ".bin" / "eslint"
                    eslint.parent.mkdir(parents=True)
                    eslint.write_text("#!/usr/bin/env sh\n", encoding="utf-8")
                    eslint.chmod(0o755)

                    def fail_install(_package_dir):
                        raise AssertionError("package manager install should not be called when cache is reusable")

                    def fake_run_shell(command, *, cwd, env=None):
                        return module.CommandRun(command=command, exit_code=0, stdout="lint ok", stderr="")

                    original_install = module.package_manager_install_command
                    original_run_shell = module.run_shell
                    try:
                        module.package_manager_install_command = fail_install
                        module.run_shell = fake_run_shell
                        outcome = module.diagnose_and_repair(
                            target,
                            "eslint .",
                            127,
                            "eslint: command not found",
                            rerun=True,
                        )
                    finally:
                        module.package_manager_install_command = original_install
                        module.run_shell = original_run_shell

                    self.assertTrue(outcome.ok)
                    self.assertTrue(outcome.repair_performed)
                    self.assertIn("node_modules/.bin", outcome.final_command or "")
                    self.assertTrue(any("using existing ignored Node dependency cache" in item for item in outcome.repairs))


if __name__ == "__main__":
    unittest.main()
