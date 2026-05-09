#!/usr/bin/env python3
"""Validate the Diffmogger starter-kit source manifest."""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def find_kit_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "templates").is_dir() and (parent / "validation" / "starter_kit_manifest.json").is_file():
            return parent
    return Path(__file__).resolve().parents[3]


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError(f"{path}: manifest must be a JSON object")
    return manifest


def validate_manifest_shape(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if not isinstance(manifest.get("canonical_wrapper_template"), str) or not manifest.get("canonical_wrapper_template"):
        errors.append("canonical_wrapper_template must be a non-empty string")

    groups = manifest.get("required_file_groups")
    if not isinstance(groups, dict) or not groups:
        errors.append("required_file_groups must be a non-empty object")
    else:
        seen: dict[str, str] = {}
        for group, files in groups.items():
            if not isinstance(group, str) or not group:
                errors.append("required_file_groups keys must be non-empty strings")
                continue
            if not isinstance(files, list) or not files:
                errors.append(f"required_file_groups.{group} must be a non-empty list")
                continue
            for item in files:
                if not isinstance(item, str) or not item:
                    errors.append(f"required_file_groups.{group} contains a non-string path")
                    continue
                if item.startswith("/") or ".." in Path(item).parts:
                    errors.append(f"required file path must be repo-relative and safe: {item}")
                previous = seen.get(item)
                if previous is not None:
                    errors.append(f"required file listed twice: {item} in {previous} and {group}")
                seen[item] = group

    for section in ("runtime_entrypoints", "source_entrypoints"):
        entrypoints = manifest.get(section, [])
        if section == "runtime_entrypoints" and (not isinstance(entrypoints, list) or not entrypoints):
            errors.append("runtime_entrypoints must be a non-empty list")
            continue
        if not isinstance(entrypoints, list):
            errors.append(f"{section} must be a list")
            continue
        for entry in entrypoints:
            if not isinstance(entry, dict):
                errors.append(f"{section} entries must be objects")
                continue
            for entry_key in ("script", "module", "source"):
                if not isinstance(entry.get(entry_key), str) or not entry.get(entry_key):
                    errors.append(f"entrypoint entries require {entry_key} strings")
            if "source_script" in entry and (
                not isinstance(entry.get("source_script"), str) or not entry.get("source_script")
            ):
                errors.append("entrypoint source_script must be a non-empty string when provided")
            if "template" in entry:
                errors.append("runtime entrypoints must use canonical_wrapper_template, not per-script templates")

    ignored = manifest.get("ignored_artifact_paths", [])
    if not isinstance(ignored, list):
        errors.append("ignored_artifact_paths must be a list")
    else:
        for item in ignored:
            if not isinstance(item, str) or not item:
                errors.append("ignored_artifact_paths entries must be non-empty strings")

    for section in ("script_wrapper_policy", "generated_smoke_target", "docs_policy"):
        if section in manifest and not isinstance(manifest[section], dict):
            errors.append(f"{section} must be an object")

    wrapper_policy = manifest.get("script_wrapper_policy", {})
    if isinstance(wrapper_policy, dict):
        allowed = wrapper_policy.get("allowed_non_wrapper_scripts", [])
        if not isinstance(allowed, list):
            errors.append("script_wrapper_policy.allowed_non_wrapper_scripts must be a list")
        else:
            for item in allowed:
                if not isinstance(item, str) or not item.startswith("scripts/") or not item.endswith(".py"):
                    errors.append("allowed non-wrapper scripts must be repo-relative scripts/*.py paths")

    forbidden_paths = manifest.get("forbidden_paths", [])
    if not isinstance(forbidden_paths, list):
        errors.append("forbidden_paths must be a list")
    else:
        for item in forbidden_paths:
            if not isinstance(item, str) or not item:
                errors.append("forbidden_paths entries must be non-empty strings")

    docs_policy = manifest.get("docs_policy", {})
    if isinstance(docs_policy, dict) and docs_policy:
        for key in ("ownership_map",):
            if not isinstance(docs_policy.get(key), str) or not docs_policy.get(key):
                errors.append(f"docs_policy.{key} must be a non-empty string")
        for key in ("mapped_docs", "active_doc_globs", "forbidden_active_doc_patterns"):
            value = docs_policy.get(key, [])
            if not isinstance(value, list):
                errors.append(f"docs_policy.{key} must be a list")
            elif any(not isinstance(item, str) or not item for item in value):
                errors.append(f"docs_policy.{key} entries must be non-empty strings")
        line_limits = docs_policy.get("line_limits", {})
        if not isinstance(line_limits, dict):
            errors.append("docs_policy.line_limits must be an object")
        else:
            for path, limit in line_limits.items():
                if not isinstance(path, str) or not isinstance(limit, int) or limit <= 0:
                    errors.append("docs_policy.line_limits must map paths to positive integers")

    return errors


def iter_required_files(manifest: dict[str, Any]) -> list[tuple[str, str]]:
    groups = manifest.get("required_file_groups", {})
    return [(group, path) for group, paths in groups.items() for path in paths]


def check_required_files(root: Path, manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for group, rel_path in iter_required_files(manifest):
        path = root / rel_path
        if not path.exists():
            errors.append(f"{group}: missing required file: {rel_path}")
        elif not path.is_file():
            errors.append(f"{group}: required path is not a file: {rel_path}")
        elif path.stat().st_size == 0:
            errors.append(f"{group}: required file is empty: {rel_path}")
    return errors


def manifest_entrypoints(manifest: dict[str, Any], section: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for raw in manifest.get(section, []):
        if isinstance(raw, dict):
            entries.append(
                {
                    "script": str(raw.get("script") or ""),
                    "source_script": str(raw.get("source_script") or raw.get("script") or ""),
                    "module": str(raw.get("module") or ""),
                    "source": str(raw.get("source") or ""),
                }
            )
    return entries


def all_manifest_entrypoints(manifest: dict[str, Any]) -> list[dict[str, str]]:
    return [
        *manifest_entrypoints(manifest, "runtime_entrypoints"),
        *manifest_entrypoints(manifest, "source_entrypoints"),
    ]


def repo_rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def target_wrapper_rel(script_rel: str) -> str:
    if not script_rel.startswith("scripts/"):
        raise ValueError(f"runtime entrypoint script must live under scripts/: {script_rel}")
    return f".diffmogger/{script_rel}"


def looks_like_compatibility_wrapper(text: str) -> bool:
    return (
        text.startswith("#!/usr/bin/env python3\n\"\"\"Compatibility wrapper for ")
        and "runpy.run_module(" in text
        and "from pathlib import Path" in text
    )


def load_wrapper_renderer(root: Path, manifest: dict[str, Any]) -> tuple[Any | None, list[str]]:
    rel_path = str(manifest.get("canonical_wrapper_template") or "")
    path = root / rel_path
    if not path.exists():
        return None, [f"canonical wrapper template missing: {rel_path}"]
    spec = importlib.util.spec_from_file_location("diffmogger_wrapper_template_validator", path)
    if spec is None or spec.loader is None:
        return None, [f"canonical wrapper template is not importable: {rel_path}"]
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - defensive diagnostics.
        return None, [f"canonical wrapper template failed to import: {rel_path}: {exc}"]
    render = getattr(module, "render_wrapper", None)
    if not callable(render):
        return None, [f"canonical wrapper template must expose render_wrapper(): {rel_path}"]
    return render, []


def check_runtime_entrypoints(root: Path, manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    render_wrapper, render_errors = load_wrapper_renderer(root, manifest)
    if render_errors:
        return render_errors
    assert render_wrapper is not None

    for entry in all_manifest_entrypoints(manifest):
        script_rel = entry["source_script"]
        source_rel = entry["source"]
        module = entry["module"]

        script = root / script_rel
        source = root / source_rel
        if not script.exists():
            errors.append(f"runtime entrypoint missing: {script_rel}")
            continue
        if not source.exists():
            errors.append(f"runtime source missing: {source_rel}")
            continue
        script_text = script.read_text(encoding="utf-8")
        try:
            expected = render_wrapper(module)
        except Exception as exc:
            errors.append(f"runtime entrypoint {script_rel} could not render canonical wrapper: {exc}")
            continue
        if script_text != expected:
            errors.append(f"runtime entrypoint {script_rel} does not match canonical wrapper template for {module}")
        if f"from {module} import *" not in script_text:
            errors.append(f"runtime entrypoint {script_rel} does not re-export {module}")
        if f'run_module("{module}"' not in script_text:
            errors.append(f"runtime entrypoint {script_rel} does not execute {module}")
        if "\"src\"" not in script_text or "\"lib\"" not in script_text:
            errors.append(f"runtime entrypoint {script_rel} does not support source and bundled library imports")

        source_text = source.read_text(encoding="utf-8")
        if looks_like_compatibility_wrapper(source_text):
            errors.append(f"runtime source must not be a compatibility wrapper: {source_rel}")
    return errors


def check_script_wrapper_policy(root: Path, manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    render_wrapper, render_errors = load_wrapper_renderer(root, manifest)
    if render_errors:
        return render_errors
    assert render_wrapper is not None

    policy = manifest.get("script_wrapper_policy", {})
    allowed = set(policy.get("allowed_non_wrapper_scripts", [])) if isinstance(policy, dict) else set()
    entrypoint_modules = {
        entry["source_script"]: entry["module"]
        for entry in all_manifest_entrypoints(manifest)
    }

    for script in sorted((root / "scripts").rglob("*.py")):
        rel_path = repo_rel(script, root)
        if rel_path in allowed:
            continue
        module = entrypoint_modules.get(rel_path)
        if not module:
            errors.append(f"root Python script must be declared as a package wrapper or explicitly allowed: {rel_path}")
            continue
        expected = render_wrapper(module)
        if script.read_text(encoding="utf-8") != expected:
            errors.append(f"root Python script is not the canonical thin package wrapper for {module}: {rel_path}")

    for rel_path in sorted(allowed):
        path = root / rel_path
        if path.exists() and rel_path in entrypoint_modules:
            errors.append(f"script cannot be both an entrypoint wrapper and an allowed non-wrapper: {rel_path}")
    return errors


def check_runtime_source_ownership(root: Path, manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for entry in all_manifest_entrypoints(manifest):
        script_rel = entry["script"]
        source_script_rel = entry["source_script"]
        source_rel = entry["source"]
        module = entry["module"]
        if not script_rel.startswith("scripts/") or not script_rel.endswith(".py"):
            errors.append(f"generated Python entrypoint must live under scripts/: {script_rel}")
        if not source_script_rel.startswith("scripts/") or not source_script_rel.endswith(".py"):
            errors.append(f"source Python wrapper must live under scripts/: {source_script_rel}")
        if not module.startswith("diffmogger."):
            errors.append(f"entrypoint module must live in the diffmogger package: {script_rel} -> {module}")
        if not source_rel.startswith("src/diffmogger/") or not source_rel.endswith(".py"):
            errors.append(f"entrypoint implementation must live under src/diffmogger/: {script_rel} -> {source_rel}")

    wrapper_template = str(manifest.get("canonical_wrapper_template") or "")
    if wrapper_template and not wrapper_template.startswith("src/diffmogger/"):
        errors.append(f"canonical wrapper template must live under src/diffmogger/: {wrapper_template}")
    return errors


def check_forbidden_paths(root: Path, manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for rel_path in manifest.get("forbidden_paths", []):
        path = root / rel_path
        if path.exists():
            errors.append(f"forbidden legacy path exists: {rel_path}")
    required_paths = {rel_path for _group, rel_path in iter_required_files(manifest)}
    for rel_path in manifest.get("forbidden_paths", []):
        if rel_path in required_paths:
            errors.append(f"forbidden path is still listed as required: {rel_path}")
    return errors


def import_scaffolder(root: Path) -> tuple[Any | None, list[str]]:
    src_dir = root / "src"
    import_path_text = str(src_dir)
    if import_path_text not in sys.path:
        sys.path.insert(0, import_path_text)
    try:
        module = importlib.import_module("diffmogger.kit.scaffold_project_docs")
    except Exception as exc:  # pragma: no cover - defensive diagnostics.
        return None, [f"diffmogger.kit.scaffold_project_docs failed to import: {exc}"]
    return module, []


def check_generated_runtime_wrappers(root: Path, manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    render_wrapper, render_errors = load_wrapper_renderer(root, manifest)
    if render_errors:
        return render_errors
    assert render_wrapper is not None
    scaffolder, scaffold_errors = import_scaffolder(root)
    if scaffold_errors:
        return scaffold_errors
    assert scaffolder is not None

    try:
        values = scaffolder.placeholders(
            {
                "project_name": "Runtime Wrapper Smoke",
                "human_bridge_enabled": False,
                "human_bridge_mode": "disabled",
            }
        )
    except Exception as exc:
        return [f"could not build scaffold placeholder values: {exc}"]

    with tempfile.TemporaryDirectory() as temp_dir:
        target = Path(temp_dir)
        try:
            scaffolder.scaffold(target, values, force=True)
        except Exception as exc:
            return [f"scaffold smoke failed while validating generated runtime wrappers: {exc}"]
        expected_wrappers = {
            target_wrapper_rel(entry["script"])
            for entry in manifest_entrypoints(manifest, "runtime_entrypoints")
        }
        generated_wrappers = {
            repo_rel(path, target)
            for path in (target / ".diffmogger" / "scripts").glob("*.py")
        }
        if generated_wrappers != expected_wrappers:
            missing = sorted(expected_wrappers - generated_wrappers)
            extra = sorted(generated_wrappers - expected_wrappers)
            if missing:
                errors.append(f"generated smoke target missing Python wrappers: {missing}")
            if extra:
                errors.append(f"generated smoke target has unexpected Python wrappers: {extra}")

        for entry in manifest_entrypoints(manifest, "runtime_entrypoints"):
            script_rel = entry["script"]
            module = entry["module"]
            try:
                generated_rel = target_wrapper_rel(script_rel)
            except ValueError as exc:
                errors.append(str(exc))
                continue
            generated = target / generated_rel
            if not generated.exists():
                errors.append(f"generated runtime wrapper missing: {generated_rel}")
                continue
            text = generated.read_text(encoding="utf-8")
            expected = render_wrapper(module)
            if text != expected:
                errors.append(f"generated runtime wrapper {generated_rel} does not match canonical wrapper template")
            if f"from {module} import *" not in text:
                errors.append(f"generated runtime wrapper {generated_rel} does not re-export {module}")
            if f'run_module("{module}"' not in text:
                errors.append(f"generated runtime wrapper {generated_rel} does not execute {module}")
            if '_HERE.parents[1] / "lib"' not in text:
                errors.append(f"generated runtime wrapper {generated_rel} does not import from .diffmogger/lib")

        smoke_policy = manifest.get("generated_smoke_target", {})
        required_packages = smoke_policy.get("required_bundle_packages", []) if isinstance(smoke_policy, dict) else []
        for package in required_packages:
            source_package = root / "src" / "diffmogger" / package
            generated_package = target / ".diffmogger" / "lib" / "diffmogger" / package
            if not source_package.exists():
                errors.append(f"generated smoke policy references missing source package: src/diffmogger/{package}")
                continue
            if not generated_package.exists():
                errors.append(f"generated smoke target missing runtime bundle package: .diffmogger/lib/diffmogger/{package}")
                continue
            for source in sorted(source_package.rglob("*.py")):
                if "__pycache__" in source.parts:
                    continue
                rel = source.relative_to(root / "src")
                generated = target / ".diffmogger" / "lib" / rel
                if not generated.exists():
                    errors.append(f"generated smoke target missing runtime bundle source: {generated.relative_to(target).as_posix()}")

        if not (target / ".diffmogger" / "lib" / "diffmogger" / "runtime").exists():
            errors.append("generated smoke target missing .diffmogger/lib/diffmogger/runtime runtime bundle")

        forbidden_packages = set(smoke_policy.get("forbidden_bundle_packages", [])) if isinstance(smoke_policy, dict) else set()
        if isinstance(smoke_policy, dict) and not bool(smoke_policy.get("allow_dashboard_backend_bundle", False)):
            forbidden_packages.add("dashboard")
        for package in sorted(forbidden_packages):
            bundled = target / ".diffmogger" / "lib" / "diffmogger" / package
            if bundled.exists():
                errors.append(f"generated smoke target must not bundle dashboard/source-kit package: {bundled.relative_to(target).as_posix()}")
    return errors


def check_no_template_python_wrappers(root: Path, manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for group, rel_path in iter_required_files(manifest):
        if rel_path.startswith("templates/scripts/") and rel_path.endswith(".py"):
            errors.append(f"{group}: Python wrappers must not be tracked as templates: {rel_path}")
    for rel_path in sorted(path.relative_to(root).as_posix() for path in (root / "templates" / "scripts").glob("*.py")):
        errors.append(f"Python wrapper template must be generated, not stored under templates/scripts: {rel_path}")
    tracked = subprocess.run(
        ["git", "ls-files", "--", "templates/scripts/*.py"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if tracked.returncode == 0:
        for rel_path in sorted(path for path in tracked.stdout.splitlines() if path.strip()):
            if (root / rel_path).exists():
                errors.append(f"tracked Python wrapper template exists under templates/scripts: {rel_path}")
    return errors


def check_wrapper_template_single_source(root: Path, manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    canonical = str(manifest.get("canonical_wrapper_template") or "")
    canonical_path = root / canonical
    if canonical not in {rel_path for _group, rel_path in iter_required_files(manifest)}:
        errors.append(f"canonical wrapper template must be listed in required files: {canonical}")
    for scan_root in [root / "src" / "diffmogger", root / "scripts", root / "templates"]:
        if not scan_root.exists():
            continue
        for path in sorted(scan_root.rglob("*.py")):
            if path == canonical_path or "__pycache__" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if re.search(r"^WRAPPER_TEMPLATE\s*=", text, re.MULTILINE) or re.search(r"^def\s+render_wrapper\s*\(", text, re.MULTILINE):
                errors.append(f"wrapper rendering logic must live only in {canonical}: {repo_rel(path, root)}")
    return errors


MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def markdown_links(root: Path, markdown_path: Path) -> set[str]:
    text = markdown_path.read_text(encoding="utf-8")
    links: set[str] = set()
    for raw_link in MARKDOWN_LINK_RE.findall(text):
        link = raw_link.strip().strip("<>")
        if not link or re.match(r"^[a-z][a-z0-9+.-]*:", link, re.IGNORECASE):
            continue
        link = link.split("#", 1)[0]
        if not link:
            continue
        try:
            resolved = (markdown_path.parent / link).resolve().relative_to(root.resolve())
        except ValueError:
            continue
        links.add(resolved.as_posix())
    return links


def expand_doc_globs(root: Path, globs: list[str]) -> set[str]:
    paths: set[str] = set()
    for pattern in globs:
        for path in root.glob(pattern):
            if path.is_file():
                paths.add(repo_rel(path, root))
    return paths


def check_docs_policy(root: Path, manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    policy = manifest.get("docs_policy", {})
    if not isinstance(policy, dict) or not policy:
        return errors

    ownership_map = str(policy.get("ownership_map") or "")
    ownership_path = root / ownership_map
    if not ownership_path.exists():
        return [f"docs ownership map missing: {ownership_map}"]

    mapped_docs = set(policy.get("mapped_docs", []))
    active_docs = expand_doc_globs(root, list(policy.get("active_doc_globs", [])))
    expected_active_docs = mapped_docs | {ownership_map}
    missing_from_scan = sorted(expected_active_docs - active_docs)
    unmapped_active_docs = sorted(active_docs - expected_active_docs)
    if missing_from_scan:
        errors.append(f"docs policy references missing active docs: {missing_from_scan}")
    if unmapped_active_docs:
        errors.append(f"active docs are not listed in docs/README.md ownership policy: {unmapped_active_docs}")

    links = markdown_links(root, ownership_path)
    for rel_path in sorted(mapped_docs):
        if rel_path not in links:
            errors.append(f"docs ownership map does not link active doc: {rel_path}")

    for rel_path, max_lines in sorted(policy.get("line_limits", {}).items()):
        path = root / rel_path
        if not path.exists():
            errors.append(f"line-count policy references missing doc: {rel_path}")
            continue
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count > int(max_lines):
            errors.append(f"{rel_path} has {line_count} lines; limit is {max_lines}")

    forbidden_patterns = list(policy.get("forbidden_active_doc_patterns", []))
    for rel_path in sorted(active_docs):
        path = root / rel_path
        text = path.read_text(encoding="utf-8")
        for pattern in forbidden_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                errors.append(f"active doc {rel_path} contains forbidden stale-doc pattern: {pattern}")
    return errors


def git_check_ignored(root: Path, rel_path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--", rel_path],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def check_ignored_artifact_paths(root: Path, manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for rel_path in manifest.get("ignored_artifact_paths", []):
        if not git_check_ignored(root, rel_path):
            errors.append(f"artifact path is not ignored: {rel_path}")
    return errors


def validate(root: Path, manifest_path: Path) -> list[str]:
    manifest = load_manifest(manifest_path)
    errors = validate_manifest_shape(manifest)
    if errors:
        return errors
    errors.extend(check_required_files(root, manifest))
    errors.extend(check_no_template_python_wrappers(root, manifest))
    errors.extend(check_wrapper_template_single_source(root, manifest))
    errors.extend(check_script_wrapper_policy(root, manifest))
    errors.extend(check_runtime_source_ownership(root, manifest))
    errors.extend(check_forbidden_paths(root, manifest))
    errors.extend(check_docs_policy(root, manifest))
    errors.extend(check_runtime_entrypoints(root, manifest))
    errors.extend(check_generated_runtime_wrappers(root, manifest))
    errors.extend(check_ignored_artifact_paths(root, manifest))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "manifest",
        nargs="?",
        default="validation/starter_kit_manifest.json",
        help="Path to the starter-kit validation manifest.",
    )
    args = parser.parse_args(argv)

    root = find_kit_root()
    manifest_path = (root / args.manifest).resolve()
    errors = validate(root, manifest_path)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"OK: starter-kit manifest validated: {manifest_path.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
