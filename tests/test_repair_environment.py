from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPAIR_PATHS = [
    ROOT / "scripts" / "repair_environment.py",
    ROOT / "templates" / "scripts" / "repair_environment.py",
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


if __name__ == "__main__":
    unittest.main()
