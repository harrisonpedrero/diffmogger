#!/usr/bin/env python3
"""Diagnose and safely repair local automation environment failures.

The helper is intentionally local-first:

- never installs globally
- never reads .env files
- only creates dependency state under ignored local paths
- records diagnostics and repair attempts as structured JSON
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ENV_FAILURE_KINDS = {
    "missing_command",
    "missing_python_module",
    "missing_pytest",
    "missing_node_module",
    "missing_node_dependencies",
}


@dataclass
class CommandRun:
    command: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""

    @property
    def output(self) -> str:
        return (self.stdout + "\n" + self.stderr).strip()


@dataclass
class EnvironmentRepairOutcome:
    command: str
    initial_exit_code: int
    initial_output: str
    diagnostics: list[dict[str, str]] = field(default_factory=list)
    repairs: list[str] = field(default_factory=list)
    repair_performed: bool = False
    final_command: str | None = None
    final_exit_code: int | None = None
    final_output: str = ""
    path_prepend: list[str] = field(default_factory=list)
    environment_failure: bool = False
    blocked_reason: str = ""

    @property
    def ok(self) -> bool:
        return self.final_exit_code == 0 if self.final_exit_code is not None else self.initial_exit_code == 0

    @property
    def final_or_initial_exit_code(self) -> int:
        return self.final_exit_code if self.final_exit_code is not None else self.initial_exit_code

    def checks_run(self) -> list[str]:
        checks = [self.command]
        if self.diagnostics:
            checks.append("environment diagnosis: " + summarize_diagnostics(self.diagnostics))
        checks.extend(f"environment repair: {item}" for item in self.repairs)
        if self.final_command:
            checks.append(self.final_command)
        return checks

    def detail(self) -> str:
        parts = [
            f"$ {self.command}",
            f"exit={self.initial_exit_code}",
            self.initial_output,
        ]
        if self.diagnostics:
            parts.extend(["", "environment diagnosis: " + summarize_diagnostics(self.diagnostics)])
        if self.repairs:
            parts.extend(["", *[f"environment repair: {item}" for item in self.repairs]])
        if self.blocked_reason:
            parts.extend(["", f"environment repair blocked: {self.blocked_reason}"])
        if self.final_command:
            parts.extend(["", f"$ {self.final_command}", f"exit={self.final_exit_code}", self.final_output])
        return "\n".join(part for part in parts if part is not None).strip()

    def to_json(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "initial_exit_code": self.initial_exit_code,
            "diagnostics": self.diagnostics,
            "repairs": self.repairs,
            "repair_performed": self.repair_performed,
            "final_command": self.final_command,
            "final_exit_code": self.final_exit_code,
            "path_prepend": self.path_prepend,
            "environment_failure": self.environment_failure,
            "blocked_reason": self.blocked_reason,
            "ok": self.ok,
        }


def run(args: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True)


def run_shell(command: str, *, cwd: Path, env: dict[str, str] | None = None) -> CommandRun:
    result = run(["/bin/bash", "-lc", command], cwd=cwd, env=env)
    return CommandRun(command=command, exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr)


def git(target: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd=target)


def inside_git_repo(target: Path) -> bool:
    result = git(target, "rev-parse", "--is-inside-work-tree")
    return result.returncode == 0 and result.stdout.strip() == "true"


def ensure_info_exclude(target: Path, patterns: list[str]) -> None:
    if not inside_git_repo(target):
        return
    exclude = target / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    lines = existing.splitlines()
    changed = False
    for pattern in patterns:
        if pattern not in lines:
            lines.append(pattern)
            changed = True
    if changed:
        exclude.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def git_ignores_path(target: Path, path: Path) -> bool:
    if not inside_git_repo(target):
        return True
    try:
        rel = path.relative_to(target)
    except ValueError:
        return False
    candidates = [rel.as_posix()]
    if path.is_dir() or not path.suffix:
        candidates.append(rel.as_posix().rstrip("/") + "/")
    for candidate in candidates:
        result = git(target, "check-ignore", "-q", "--", candidate)
        if result.returncode == 0:
            return True
    return False


def quote_command(args: list[str]) -> str:
    return " ".join(shlex.quote(arg) for arg in args)


def split_command(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return []


def command_basename(command: str) -> str:
    tokens = split_command(command)
    return Path(tokens[0]).name if tokens else ""


def parse_missing_command(command: str, exit_code: int, output: str) -> str:
    patterns = [
        r"(?:^|\n)/bin/bash: line \d+: ([A-Za-z0-9_.-]+): command not found",
        r"(?:^|\n)([A-Za-z0-9_.-]+): command not found",
        r"(?:^|\n)([A-Za-z0-9_.-]+): not found",
        r"(?:^|\n)sh: ([A-Za-z0-9_.-]+): command not found",
    ]
    for pattern in patterns:
        match = re.search(pattern, output)
        if match:
            return match.group(1)
    return command_basename(command) if exit_code == 127 else ""


def parse_missing_python_module(output: str) -> str:
    patterns = [
        r"No module named ['\"]?([A-Za-z0-9_.-]+)['\"]?",
        r"ModuleNotFoundError:\s+No module named ['\"]([^'\"]+)['\"]",
        r"ImportError:\s+No module named ['\"]?([A-Za-z0-9_.-]+)['\"]?",
    ]
    for pattern in patterns:
        match = re.search(pattern, output)
        if match:
            return match.group(1).strip()
    return ""


def parse_missing_node_module(output: str) -> str:
    patterns = [
        r"Cannot find module ['\"]([^'\"]+)['\"]",
        r"Error \[ERR_MODULE_NOT_FOUND\]: Cannot find package ['\"]([^'\"]+)['\"]",
        r"Cannot find package ['\"]([^'\"]+)['\"]",
    ]
    for pattern in patterns:
        match = re.search(pattern, output)
        if match:
            module = match.group(1).strip()
            if module.startswith(".") or module.startswith("/"):
                continue
            return module
    return ""


def command_uses_pytest(command: str) -> bool:
    tokens = split_command(command)
    return "pytest" in command or any(token == "pytest" for token in tokens)


def diagnose_failure(command: str, exit_code: int, output: str) -> list[dict[str, str]]:
    diagnostics: list[dict[str, str]] = []
    missing_command = parse_missing_command(command, exit_code, output)
    missing_module = parse_missing_python_module(output)
    missing_node_module = parse_missing_node_module(output)

    if missing_command:
        diagnostics.append({"kind": "missing_command", "name": missing_command})
    if missing_module:
        kind = "missing_pytest" if missing_module == "pytest" or command_uses_pytest(command) else "missing_python_module"
        diagnostics.append({"kind": kind, "name": missing_module})
    if "pytest: command not found" in output.lower() or "pytest: not found" in output.lower():
        diagnostics.append({"kind": "missing_pytest", "name": "pytest"})
    if missing_node_module:
        diagnostics.append({"kind": "missing_node_module", "name": missing_node_module})
    if missing_command and (Path("node_modules") / ".bin" / missing_command).as_posix():
        if missing_command not in {"python", "python3", "pytest", "pip", "pip3", "codex", "git"}:
            diagnostics.append({"kind": "missing_node_dependencies", "name": missing_command})

    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in diagnostics:
        key = (item.get("kind", ""), item.get("name", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def summarize_diagnostics(diagnostics: list[dict[str, str]]) -> str:
    if not diagnostics:
        return "no repairable environment failure detected"
    return "; ".join(f"{item.get('kind')}:{item.get('name')}" for item in diagnostics)


def python_can_import(python_path: Path, module: str) -> bool:
    module = module.replace("-", "_")
    result = run([str(python_path), "-c", f"import {module}"], cwd=python_path.parent)
    return result.returncode == 0


def candidate_service_dirs(target: Path, command: str, output: str) -> list[Path]:
    services = target / "services"
    candidates: list[Path] = []
    if not services.exists():
        return candidates
    haystack = command + "\n" + output
    for service in sorted(path for path in services.iterdir() if path.is_dir()):
        rel = service.relative_to(target).as_posix()
        if rel in haystack or service.name in haystack:
            candidates.append(service)
    return candidates


def existing_venv_pythons(target: Path, command: str, output: str) -> list[Path]:
    candidates: list[Path] = []
    for service in candidate_service_dirs(target, command, output):
        candidates.append(service / ".venv" / "bin" / "python")
    candidates.extend(
        [
            target / "services" / "agentic-notifier" / ".venv" / "bin" / "python",
            target / ".venv" / "bin" / "python",
        ]
    )
    services = target / "services"
    if services.exists():
        candidates.extend(sorted(services.glob("*/.venv/bin/python")))
    seen: set[Path] = set()
    unique: list[Path] = []
    for candidate in candidates:
        key = candidate.resolve() if candidate.exists() else candidate
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def python_requirement_candidates(target: Path, command: str, output: str) -> list[tuple[Path, Path]]:
    candidates: list[tuple[Path, Path]] = []
    for service in candidate_service_dirs(target, command, output):
        requirements = service / "requirements.txt"
        if requirements.exists():
            candidates.append((requirements, service / ".venv"))
    notifier_requirements = target / "services" / "agentic-notifier" / "requirements.txt"
    if notifier_requirements.exists():
        candidates.append((notifier_requirements, notifier_requirements.parent / ".venv"))
    root_requirements = target / "requirements.txt"
    if root_requirements.exists():
        candidates.append((root_requirements, target / "target" / "automation_venvs" / "root"))
    services = target / "services"
    if services.exists():
        for requirements in sorted(services.glob("*/requirements.txt")):
            candidates.append((requirements, requirements.parent / ".venv"))
    seen: set[tuple[Path, Path]] = set()
    unique: list[tuple[Path, Path]] = []
    for item in candidates:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique


def python_command_for_venv(target: Path, python_path: Path, original_command: str) -> str:
    tokens = split_command(original_command)
    if tokens:
        first = Path(tokens[0]).name
        if first in {"python", "python3"}:
            return quote_command([str(python_path), *tokens[1:]])
        if first == "pytest":
            args = tokens[1:]
            if not args and (target / "services" / "agentic-notifier").exists() and "agentic-notifier" in python_path.as_posix():
                args = ["services/agentic-notifier"]
            return quote_command([str(python_path), "-m", "pytest", *args])
        for index, token in enumerate(tokens[:-1]):
            if token == "-m" and tokens[index + 1] == "pytest":
                args = tokens[index + 2 :]
                if not args and (target / "services" / "agentic-notifier").exists() and "agentic-notifier" in python_path.as_posix():
                    args = ["services/agentic-notifier"]
                return quote_command([str(python_path), "-m", "pytest", *args])
    if (target / "services" / "agentic-notifier").exists() and "agentic-notifier" in python_path.as_posix():
        return quote_command([str(python_path), "-m", "pytest", "services/agentic-notifier"])
    return quote_command([str(python_path), "-m", "pytest"])


def repair_python_environment(
    target: Path,
    command: str,
    output: str,
    diagnostics: list[dict[str, str]],
) -> tuple[str | None, list[str], str]:
    needed_modules = [
        item.get("name", "")
        for item in diagnostics
        if item.get("kind") in {"missing_python_module", "missing_pytest"}
    ]
    if not needed_modules:
        return None, [], ""
    notes: list[str] = []
    primary_module = needed_modules[0] or "pytest"
    for python_path in existing_venv_pythons(target, command, output):
        if not python_path.exists() or not os.access(python_path, os.X_OK):
            continue
        if python_can_import(python_path, primary_module):
            notes.append(f"using existing local venv {python_path.relative_to(target)}")
            return python_command_for_venv(target, python_path, command), notes, ""
        notes.append(f"{python_path.relative_to(target)} exists but cannot import {primary_module}")

    ensure_info_exclude(target, ["/target/automation_venvs/", "/.venv/", "/services/*/.venv/"])
    for requirements, venv_dir in python_requirement_candidates(target, command, output):
        if not git_ignores_path(target, venv_dir):
            notes.append(f"skipped {venv_dir.relative_to(target)} because it is not ignored by repo policy")
            continue
        python_path = venv_dir / "bin" / "python"
        if python_path.exists() and python_can_import(python_path, primary_module):
            notes.append(f"using existing local ignored venv {venv_dir.relative_to(target)}")
            return python_command_for_venv(target, python_path, command), notes, ""
        if not python_path.exists():
            created = run([sys.executable, "-m", "venv", str(venv_dir)], cwd=target)
            if created.returncode != 0:
                notes.append(f"venv creation failed for {venv_dir.relative_to(target)}: {created.stderr.strip()}")
                continue
        installed = run([str(python_path), "-m", "pip", "install", "-r", str(requirements)], cwd=target)
        if installed.returncode != 0:
            notes.append(f"dependency install failed for {requirements.relative_to(target)}: {installed.stderr.strip()}")
            continue
        if python_can_import(python_path, primary_module):
            notes.append(f"installed Python dependencies from {requirements.relative_to(target)} into {venv_dir.relative_to(target)}")
            return python_command_for_venv(target, python_path, command), notes, ""
        notes.append(f"installed {requirements.relative_to(target)} but {primary_module} is still unavailable")
    return None, notes, "No ignored local Python venv with declared requirements could satisfy the missing module."


def find_package_dirs(target: Path, command: str, output: str) -> list[Path]:
    candidates: list[Path] = []
    haystack = command + "\n" + output
    for path in sorted(target.rglob("package.json")):
        if "node_modules" in path.parts or "target" in path.parts or ".git" in path.parts:
            continue
        package_dir = path.parent
        rel = package_dir.relative_to(target).as_posix()
        if rel == "." or rel in haystack or package_dir.name in haystack:
            candidates.append(package_dir)
    return candidates


def package_manager_install_command(package_dir: Path) -> list[str] | None:
    if (package_dir / "pnpm-lock.yaml").exists() and shutil.which("pnpm"):
        return ["pnpm", "install", "--frozen-lockfile"]
    if (package_dir / "yarn.lock").exists() and shutil.which("yarn"):
        return ["yarn", "install", "--frozen-lockfile"]
    if (package_dir / "package-lock.json").exists() and shutil.which("npm"):
        return ["npm", "ci"]
    if (package_dir / "npm-shrinkwrap.json").exists() and shutil.which("npm"):
        return ["npm", "ci"]
    return None


def command_with_node_bin(package_dir: Path, command: str) -> str:
    node_bin = package_dir / "node_modules" / ".bin"
    return f"PATH={shlex.quote(str(node_bin))}:$PATH {command}"


def path_prepend_from_command(command: str) -> list[str]:
    prepends: list[str] = []
    path_match = re.match(r"PATH=([^:]+):\$PATH\s+", command)
    if path_match:
        prepends.append(shlex.split(path_match.group(1))[0] if path_match.group(1).startswith("'") else path_match.group(1))
    tokens = split_command(command)
    if tokens:
        first = Path(tokens[0])
        if first.name in {"python", "pytest"} and first.parent.name == "bin":
            prepends.append(str(first.parent))
    seen: set[str] = set()
    unique: list[str] = []
    for item in prepends:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique


def repair_node_environment(
    target: Path,
    command: str,
    output: str,
    diagnostics: list[dict[str, str]],
) -> tuple[str | None, list[str], str]:
    if not any(item.get("kind") in {"missing_node_module", "missing_node_dependencies"} for item in diagnostics):
        return None, [], ""
    notes: list[str] = []
    package_dirs = find_package_dirs(target, command, output)
    if not package_dirs:
        return None, notes, "No package.json was found for the failing command."
    for package_dir in package_dirs:
        try:
            rel = package_dir.relative_to(target)
        except ValueError:
            rel = package_dir
        node_modules = package_dir / "node_modules"
        pattern = f"/{rel.as_posix()}/node_modules/" if rel.as_posix() != "." else "/node_modules/"
        ensure_info_exclude(target, [pattern])
        if not git_ignores_path(target, node_modules):
            notes.append(f"skipped {rel}/node_modules because it is not ignored by repo policy")
            continue
        install_command = package_manager_install_command(package_dir)
        if install_command is None:
            notes.append(f"skipped {rel}: no supported lockfile/package manager pair found")
            continue
        installed = run(install_command, cwd=package_dir)
        if installed.returncode != 0:
            notes.append(f"{' '.join(install_command)} failed in {rel}: {installed.stderr.strip()}")
            continue
        notes.append(f"installed Node dependencies in {rel} with {' '.join(install_command)}")
        return command_with_node_bin(package_dir, command), notes, ""
    return None, notes, "No ignored project-local Node dependency install could be completed."


def repair_missing_python_command(command: str, diagnostics: list[dict[str, str]]) -> tuple[str | None, list[str], str]:
    if not any(item.get("kind") == "missing_command" and item.get("name") == "python" for item in diagnostics):
        return None, [], ""
    if not shutil.which("python3"):
        return None, [], "python command is missing and python3 is not available on PATH."
    tokens = split_command(command)
    if not tokens or Path(tokens[0]).name != "python":
        return None, [], ""
    return quote_command(["python3", *tokens[1:]]), ["substituted python3 for missing python command"], ""


def diagnose_and_repair(
    target: Path,
    command: str,
    exit_code: int,
    output: str,
    *,
    rerun: bool,
) -> EnvironmentRepairOutcome:
    diagnostics = diagnose_failure(command, exit_code, output)
    outcome = EnvironmentRepairOutcome(
        command=command,
        initial_exit_code=exit_code,
        initial_output=output,
        diagnostics=diagnostics,
        environment_failure=any(item.get("kind") in ENV_FAILURE_KINDS for item in diagnostics),
    )
    if exit_code == 0 or not diagnostics:
        return outcome

    final_command = None
    blocked_reasons: list[str] = []
    for repairer in [
        repair_missing_python_command,
        lambda _command, _diagnostics: repair_python_environment(target, _command, output, _diagnostics),
        lambda _command, _diagnostics: repair_node_environment(target, _command, output, _diagnostics),
    ]:
        repaired_command, notes, blocked = repairer(command, diagnostics)
        outcome.repairs.extend(note for note in notes if note)
        if repaired_command:
            final_command = repaired_command
            break
        if blocked:
            blocked_reasons.append(blocked)

    if final_command is None:
        outcome.blocked_reason = " ".join(blocked_reasons).strip() or "No safe local repair recipe matched this environment failure."
        return outcome

    outcome.repair_performed = True
    outcome.final_command = final_command
    outcome.path_prepend = path_prepend_from_command(final_command)
    if rerun:
        rerun_result = run_shell(final_command, cwd=target)
        outcome.final_exit_code = rerun_result.exit_code
        outcome.final_output = rerun_result.output
        final_diagnostics = diagnose_failure(final_command, rerun_result.exit_code, rerun_result.output)
        if rerun_result.exit_code != 0 and final_diagnostics:
            outcome.environment_failure = True
            outcome.blocked_reason = "Repair ran but the command still has an environment failure: " + summarize_diagnostics(final_diagnostics)
        elif rerun_result.exit_code != 0:
            outcome.environment_failure = False
    return outcome


def run_command_with_repair(target: Path, command: str) -> EnvironmentRepairOutcome:
    initial = run_shell(command, cwd=target)
    return diagnose_and_repair(target, command, initial.exit_code, initial.output, rerun=True)


def read_log(path: str) -> str:
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", default=".", help="Target project directory")
    parser.add_argument("--command", required=True, help="Command that failed")
    parser.add_argument("--exit-code", type=int, help="Exit code from an already-run command")
    parser.add_argument("--stdout-file", default="", help="Stdout log from an already-run command")
    parser.add_argument("--stderr-file", default="", help="Stderr log from an already-run command")
    parser.add_argument("--rerun", action="store_true", help="Rerun the command once after a repair")
    parser.add_argument("--status-file", default="", help="Write JSON status to this file")
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    if args.exit_code is None:
        outcome = run_command_with_repair(target, args.command)
    else:
        output = (read_log(args.stdout_file) + "\n" + read_log(args.stderr_file)).strip()
        outcome = diagnose_and_repair(target, args.command, args.exit_code, output, rerun=args.rerun)
    payload = outcome.to_json()
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.status_file:
        status_path = Path(args.status_file)
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    if outcome.ok:
        return 0
    if outcome.environment_failure:
        return 75
    return outcome.final_or_initial_exit_code


if __name__ == "__main__":
    raise SystemExit(main())
