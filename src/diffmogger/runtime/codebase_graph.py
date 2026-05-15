"""Reusable codebase graph indexing helpers.

This module owns pure repository scanning and conservative dependency
extraction. SQLite persistence stays in ``state_store``.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping


CODEBASE_GRAPH_NAMESPACE = "codebase"
CODEBASE_GRAPH_SCAN_LIMIT = 5000
GRAPH_INVENTORY_SAMPLE_LIMIT = 24
GRAPH_FILE_NODE_KINDS = {"file", "test_file", "config_file", "doc_file", "lockfile"}
DEPENDENCY_EDGE_KINDS = {"imports", "references", "defines_module", "resolved_to"}

CAPABILITY_SCAN_IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".diffmogger",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "dist-ssr",
    "build",
    "target",
    "coverage",
    ".next",
    ".turbo",
    "vendor",
}

LOCKFILE_NAMES = {
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lock",
    "bun.lockb",
    "Cargo.lock",
    "poetry.lock",
    "uv.lock",
    "requirements.txt",
    "go.sum",
    "Gemfile.lock",
    "composer.lock",
}

CONFIG_FILE_NAMES = {
    ".babelrc",
    ".env.example",
    ".eslintrc",
    ".eslintrc.cjs",
    ".eslintrc.js",
    ".eslintrc.json",
    ".gitignore",
    ".prettierrc",
    ".prettierrc.json",
    ".python-version",
    ".ruby-version",
    ".tool-versions",
    "Cargo.toml",
    "Dockerfile",
    "Gemfile",
    "Makefile",
    "Pipfile",
    "bunfig.toml",
    "compose.yaml",
    "docker-compose.yml",
    "go.mod",
    "jest.config.js",
    "jest.config.ts",
    "mypy.ini",
    "package.json",
    "playwright.config.js",
    "playwright.config.ts",
    "pyproject.toml",
    "pytest.ini",
    "ruff.toml",
    "setup.cfg",
    "setup.py",
    "tox.ini",
    "tsconfig.json",
    "vite.config.js",
    "vite.config.ts",
}

LANGUAGE_BY_EXTENSION = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".rs": "Rust",
    ".go": "Go",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".c": "C",
    ".h": "C/C++",
    ".cc": "C++",
    ".cpp": "C++",
    ".hpp": "C++",
    ".swift": "Swift",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".sql": "SQL",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "CSS",
    ".md": "Markdown",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".json": "JSON",
    ".toml": "TOML",
}

JS_TS_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json")
JS_TS_IMPORT_RE = re.compile(
    r"""
    (?:\bimport\s+(?:type\s+)?(?:[^;]*?\s+from\s+)?|\bexport\s+(?:type\s+)?[^;]*?\s+from\s+)
    ["'](?P<import>[^"']+)["']
    |\brequire\(\s*["'](?P<require>[^"']+)["']\s*\)
    """,
    re.VERBOSE,
)


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_optional_text(path: Path, *, limit: int = 200_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def file_digest(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    return hashlib.sha256(data).hexdigest()


def git_value(target: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=target,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def graph_node_id(kind: str, key: str) -> str:
    return f"graph-node:{CODEBASE_GRAPH_NAMESPACE}:{kind}:{sha256_text(key)[:24]}"


def graph_edge_id(kind: str, from_node_id: str, to_node_id: str) -> str:
    return f"graph-edge:{CODEBASE_GRAPH_NAMESPACE}:{kind}:{sha256_text(from_node_id + '>' + to_node_id)[:24]}"


def graph_fact(
    key: str,
    value: Any,
    *,
    value_type: str = "text",
    source: str = "indexer",
    confidence: float = 1.0,
) -> dict[str, Any]:
    return {
        "fact_key": key,
        "fact_value": str(value),
        "value_type": value_type,
        "source": source,
        "confidence": float(confidence),
    }


def dependency_facts(source: str, confidence: float, resolved: bool, raw_import: str) -> list[dict[str, Any]]:
    return [
        graph_fact("source", source, source=source, confidence=confidence),
        graph_fact("confidence", confidence, value_type="number", source=source, confidence=confidence),
        graph_fact("resolved", "true" if resolved else "false", value_type="boolean", source=source, confidence=confidence),
        graph_fact("raw_import", raw_import, source=source, confidence=confidence),
    ]


def graph_node(
    kind: str,
    key: str,
    *,
    path: str = "",
    name: str = "",
    digest: str = "",
    metadata: Mapping[str, Any] | None = None,
    facts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    node_id = graph_node_id(kind, key)
    return {
        "node_id": node_id,
        "graph_namespace": CODEBASE_GRAPH_NAMESPACE,
        "kind": kind,
        "path": path,
        "name": name,
        "digest": digest,
        "is_stale": 0,
        "metadata": dict(metadata or {}),
        "facts": list(facts or []),
    }


def graph_edge(
    kind: str,
    from_node_id: str,
    to_node_id: str,
    *,
    metadata: Mapping[str, Any] | None = None,
    facts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    edge_id = graph_edge_id(kind, from_node_id, to_node_id)
    return {
        "edge_id": edge_id,
        "graph_namespace": CODEBASE_GRAPH_NAMESPACE,
        "kind": kind,
        "from_node_id": from_node_id,
        "to_node_id": to_node_id,
        "metadata": dict(metadata or {}),
        "facts": list(facts or []),
    }


def module_node(module_name: str, *, language: str, source: str) -> dict[str, Any]:
    name = module_name.strip()
    return graph_node(
        "module",
        f"{language}:{name}",
        name=name,
        digest=sha256_text(f"{language}:{name}"),
        metadata={"module_name": name, "language": language, "source": source},
        facts=[
            graph_fact("module_name", name, source=source),
            graph_fact("language", language, source=source),
        ],
    )


def _gitignore_directory_patterns(target: Path) -> set[str]:
    patterns: set[str] = set()
    for raw in read_optional_text(target / ".gitignore", limit=80_000).splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        if any(token in line for token in ("*", "?", "[")):
            continue
        directory_pattern = line.endswith("/")
        pattern = line.strip("/").lstrip("/")
        if not pattern:
            continue
        if directory_pattern or "/" in pattern or "." not in Path(pattern).name:
            patterns.add(pattern)
    return patterns


def _ignored_repo_directory(rel: Path, ignored_patterns: set[str]) -> bool:
    name = rel.name
    if name in CAPABILITY_SCAN_IGNORED_DIRS or name.startswith(".cache"):
        return True
    rel_text = rel.as_posix().strip("/")
    for pattern in ignored_patterns:
        if "/" in pattern:
            if rel_text == pattern or rel_text.startswith(pattern.rstrip("/") + "/"):
                return True
        elif name == pattern:
            return True
    return False


def scan_repo_paths(target: Path, *, limit: int = CODEBASE_GRAPH_SCAN_LIMIT) -> tuple[list[Path], list[Path], bool]:
    directories: list[Path] = []
    files: list[Path] = []
    ignored_patterns = _gitignore_directory_patterns(target)
    truncated = False
    for root, dirnames, filenames in os.walk(target):
        root_path = Path(root)
        try:
            root_rel = root_path.relative_to(target)
        except ValueError:
            continue
        kept_dirnames: list[str] = []
        for name in sorted(dirnames):
            rel = (root_rel / name) if root_rel != Path(".") else Path(name)
            if _ignored_repo_directory(rel, ignored_patterns):
                continue
            kept_dirnames.append(name)
            directories.append(root_path / name)
        dirnames[:] = kept_dirnames
        for filename in sorted(filenames):
            path = root_path / filename
            try:
                rel = path.relative_to(target)
            except ValueError:
                continue
            if any(part in CAPABILITY_SCAN_IGNORED_DIRS for part in rel.parts):
                continue
            files.append(path)
            if len(files) >= limit:
                truncated = True
                return directories, files, truncated
    return directories, files, truncated


def scan_repo_files(target: Path, *, limit: int = CODEBASE_GRAPH_SCAN_LIMIT) -> list[Path]:
    _, files, _ = scan_repo_paths(target, limit=limit)
    return files


def _is_test_file(rel: Path) -> bool:
    parts = {part.lower() for part in rel.parts}
    name = rel.name.lower()
    if parts.intersection({"tests", "test", "__tests__"}):
        return True
    if name.startswith("test_"):
        return True
    return name.endswith(
        (
            "_test.py",
            "_test.go",
            ".test.js",
            ".test.jsx",
            ".test.ts",
            ".test.tsx",
            ".spec.js",
            ".spec.jsx",
            ".spec.ts",
            ".spec.tsx",
        )
    )


def _is_config_file(rel: Path) -> bool:
    lower_name = rel.name.lower()
    config_names = {item.lower() for item in CONFIG_FILE_NAMES}
    if lower_name in config_names:
        return True
    if lower_name.startswith("tsconfig") and lower_name.endswith(".json"):
        return True
    if lower_name.endswith(
        (".config.js", ".config.cjs", ".config.mjs", ".config.ts", ".config.json", ".config.yaml", ".config.yml")
    ):
        return True
    return lower_name.startswith(".") and lower_name.endswith((".json", ".toml", ".yaml", ".yml", "rc"))


def _is_doc_file(rel: Path) -> bool:
    return rel.suffix.lower() in {".md", ".mdx", ".rst", ".adoc"}


def codebase_file_kind(rel: Path) -> str:
    if rel.name in LOCKFILE_NAMES:
        return "lockfile"
    if _is_test_file(rel):
        return "test_file"
    if _is_config_file(rel):
        return "config_file"
    if _is_doc_file(rel):
        return "doc_file"
    return "file"


def _directory_inventory_record(rel: str) -> dict[str, str]:
    path = Path(rel)
    return {
        "path": rel,
        "path_kind": "directory",
        "kind": "directory",
        "extension": "",
        "parent": path.parent.as_posix() if rel != "." and path.parent.as_posix() != "." else "",
    }


def _file_inventory_record(rel: str) -> dict[str, str]:
    path = Path(rel)
    return {
        "path": rel,
        "path_kind": "file",
        "kind": codebase_file_kind(path),
        "extension": path.suffix.lower(),
        "parent": path.parent.as_posix() if path.parent.as_posix() != "." else ".",
    }


def graph_inventory_digest(records: list[Mapping[str, Any]]) -> str:
    return sha256_text(stable_json(records))


def graph_inventory_from_paths(
    target: Path,
    directories: list[Path],
    files: list[Path],
    *,
    truncated: bool,
) -> dict[str, Any]:
    target = target.expanduser().resolve()
    records: list[dict[str, str]] = [_directory_inventory_record(".")]
    for directory in sorted(directories, key=lambda item: item.relative_to(target).as_posix()):
        records.append(_directory_inventory_record(directory.relative_to(target).as_posix()))
    for path in sorted(files, key=lambda item: item.relative_to(target).as_posix()):
        records.append(_file_inventory_record(path.relative_to(target).as_posix()))
    records = sorted(records, key=lambda item: (item["path_kind"], item["path"], item["kind"]))
    return {
        "schema_version": 1,
        "graph_inventory_digest": graph_inventory_digest(records),
        "indexed_path_count": len(records),
        "indexed_file_path_count": len(files),
        "indexed_directory_path_count": len(records) - len(files),
        "indexed_paths_truncated": bool(truncated),
        "indexed_path_sample": records[:GRAPH_INVENTORY_SAMPLE_LIMIT],
        "records": records,
    }


def build_graph_inventory(target: Path, *, limit: int = CODEBASE_GRAPH_SCAN_LIMIT) -> dict[str, Any]:
    target = target.expanduser().resolve()
    directories, files, truncated = scan_repo_paths(target, limit=limit)
    return graph_inventory_from_paths(target, directories, files, truncated=truncated)


def file_node_for_path(target: Path, rel: str | Path) -> dict[str, Any]:
    rel_path = Path(str(rel).replace("\\", "/"))
    path = target / rel_path
    kind = codebase_file_kind(rel_path)
    digest = file_digest(path)
    language = LANGUAGE_BY_EXTENSION.get(path.suffix.lower(), "")
    metadata: dict[str, Any] = {
        "extension": path.suffix.lower(),
        "language": language,
        "parent": rel_path.parent.as_posix() if rel_path.parent.as_posix() != "." else ".",
    }
    try:
        metadata["size_bytes"] = path.stat().st_size
    except OSError:
        metadata["size_bytes"] = 0
    facts = [
        graph_fact("sha256", digest),
        graph_fact("path", rel_path.as_posix()),
        graph_fact("kind", kind),
    ]
    if language:
        facts.append(graph_fact("language", language))
    return graph_node(
        kind,
        f"{kind}:{rel_path.as_posix()}",
        path=rel_path.as_posix(),
        name=path.name,
        digest=digest,
        metadata=metadata,
        facts=facts,
    )


def _json_file(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _package_script_commands(target: Path) -> list[dict[str, str]]:
    package_json = _json_file(target / "package.json")
    scripts = package_json.get("scripts") if isinstance(package_json.get("scripts"), dict) else {}
    commands: list[dict[str, str]] = []
    for name, value in sorted(scripts.items()):
        script_name = str(name).strip()
        if not script_name:
            continue
        commands.append(
            {
                "kind": script_name,
                "command": f"npm run {script_name}",
                "source": "package.json",
                "script": script_name,
                "origin": "package_json_script",
                "script_digest": sha256_text(str(value or "")),
            }
        )
    return commands


def _codebase_command_candidates(target: Path, capability: Mapping[str, Any] | None = None) -> list[dict[str, str]]:
    commands_by_key: dict[tuple[str, str], dict[str, str]] = {}

    def add_command(item: Mapping[str, Any], *, origin: str) -> None:
        command_text = str(item.get("command") or "").strip()
        if not command_text:
            return
        command = {
            "kind": str(item.get("kind") or item.get("script") or "command"),
            "command": command_text,
            "source": str(item.get("source") or "detected"),
            "origin": str(item.get("origin") or origin),
        }
        if str(item.get("script") or "").strip():
            command["script"] = str(item.get("script") or "").strip()
        if str(item.get("script_digest") or "").strip():
            command["script_digest"] = str(item.get("script_digest") or "").strip()
        key = (command["source"], command["command"])
        existing = commands_by_key.get(key)
        if existing is None:
            commands_by_key[key] = command
            return
        kinds = {part for part in str(existing.get("kind") or "").split(",") if part}
        kinds.add(command["kind"])
        existing["kind"] = ",".join(sorted(kinds))
        origins = {part for part in str(existing.get("origin") or "").split(",") if part}
        origins.add(command["origin"])
        existing["origin"] = ",".join(sorted(origins))

    for item in _package_script_commands(target):
        add_command(item, origin="package_json_script")
    capability_commands = capability.get("commands") if isinstance(capability, Mapping) else []
    if isinstance(capability_commands, list):
        for item in capability_commands:
            if isinstance(item, Mapping):
                add_command(item, origin="capability_manifest")
    return [commands_by_key[key] for key in sorted(commands_by_key)]


def codebase_command_signature(target: Path, capability: Mapping[str, Any] | None = None) -> list[dict[str, str]]:
    """Return the command inputs that affect graph command nodes."""

    signature: list[dict[str, str]] = []
    for command in _codebase_command_candidates(target, capability):
        signature.append(
            {
                "command": str(command.get("command") or ""),
                "kind": str(command.get("kind") or ""),
                "source": str(command.get("source") or ""),
                "origin": str(command.get("origin") or ""),
                "script": str(command.get("script") or ""),
                "script_digest": str(command.get("script_digest") or ""),
            }
        )
    return sorted(signature, key=lambda item: (item["source"], item["command"], item["kind"], item["origin"]))


def codebase_command_signature_digest(target: Path, capability: Mapping[str, Any] | None = None) -> str:
    return sha256_text(stable_json(codebase_command_signature(target, capability)))


def _command_validates_repo(command: Mapping[str, Any]) -> bool:
    kind = str(command.get("kind") or "").lower()
    command_text = str(command.get("command") or "").lower()
    return any(
        token in kind or token in command_text
        for token in ("test", "verify", "verification", "smoke", "lint", "typecheck", "build", "check", "pytest", "unittest")
    )


def _source_basename_candidates(test_rel: str) -> set[str]:
    path = Path(test_rel)
    suffix = path.suffix
    stem = path.stem
    for token in (".test", ".spec"):
        if stem.endswith(token):
            stem = stem[: -len(token)]
    if stem.startswith("test_"):
        stem = stem[5:]
    if stem.endswith("_test"):
        stem = stem[:-5]
    if not stem:
        return set()
    if suffix.lower() == ".py":
        suffixes = [".py"]
    elif suffix.lower() in {".js", ".jsx"}:
        suffixes = [".js", ".jsx"]
    elif suffix.lower() in {".ts", ".tsx"}:
        suffixes = [".ts", ".tsx", ".js", ".jsx"]
    elif suffix.lower() == ".go":
        suffixes = [".go"]
    else:
        suffixes = [suffix]
    return {stem + item for item in suffixes if item}


def _likely_tested_sources(test_rel: str, source_rels: list[str]) -> list[str]:
    names = _source_basename_candidates(test_rel)
    if not names:
        return []
    matches = [rel for rel in source_rels if Path(rel).name in names and rel != test_rel]
    matches = [rel for rel in matches if not ({part.lower() for part in Path(rel).parts} & {"tests", "test", "__tests__"})]

    def score(rel: str) -> tuple[int, int, str]:
        path = Path(rel)
        same_parent = path.parent == Path(test_rel).parent
        under_src = rel.startswith("src/")
        mirrored = tuple(part for part in Path(test_rel).parts if part.lower() not in {"tests", "test", "__tests__"})
        mirror_hint = "/".join(mirrored[:-1])
        mirrored_parent = bool(mirror_hint and rel.startswith(mirror_hint))
        return (0 if same_parent or mirrored_parent else 1, 0 if under_src else 1, rel)

    return sorted(matches, key=score)[:3]


def python_module_name_for_rel(rel: str | Path) -> str:
    path = Path(str(rel).replace("\\", "/"))
    parts = list(path.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _python_import_records(target: Path, rel: str) -> list[dict[str, Any]]:
    path = target / rel
    text = read_optional_text(path, limit=300_000)
    if not text:
        return []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    records: list[dict[str, Any]] = []
    current_module = python_module_name_for_rel(rel)
    current_parts = current_module.split(".") if current_module else []
    current_package = current_parts[:-1] if Path(rel).name != "__init__.py" else current_parts
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module = str(alias.name or "").strip()
                if module:
                    records.append({"module": module, "raw_import": module, "lineno": getattr(node, "lineno", 0)})
        elif isinstance(node, ast.ImportFrom):
            module = str(node.module or "").strip()
            if node.level:
                keep_count = max(0, len(current_package) - (node.level - 1))
                base_parts = current_package[:keep_count]
                module = ".".join([*base_parts, *([module] if module else [])])
            imported_names = [str(alias.name or "").strip() for alias in node.names if str(alias.name or "").strip() and alias.name != "*"]
            candidates = [module] if module else []
            candidates.extend(f"{module}.{name}" if module else name for name in imported_names)
            for candidate in candidates:
                if candidate:
                    records.append({"module": candidate, "raw_import": candidate, "lineno": getattr(node, "lineno", 0)})
    unique: dict[str, dict[str, Any]] = {}
    for record in records:
        unique.setdefault(str(record["module"]), record)
    return list(unique.values())


def _resolve_python_module(module_name: str, file_node_by_rel: Mapping[str, str]) -> str:
    rel_base = module_name.replace(".", "/").strip("/")
    if not rel_base:
        return ""
    candidates = [f"{rel_base}.py", f"{rel_base}/__init__.py"]
    for candidate in candidates:
        if candidate in file_node_by_rel:
            return candidate
    return ""


def _strip_js_ts_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(^|[^:])//.*$", r"\1", text, flags=re.M)


def _js_ts_import_records(target: Path, rel: str) -> list[dict[str, Any]]:
    text = _strip_js_ts_comments(read_optional_text(target / rel, limit=300_000))
    records: list[dict[str, Any]] = []
    for match in JS_TS_IMPORT_RE.finditer(text):
        raw = (match.group("import") or match.group("require") or "").strip()
        if raw:
            records.append({"raw_import": raw, "module": raw, "lineno": text[: match.start()].count("\n") + 1})
    unique: dict[str, dict[str, Any]] = {}
    for record in records:
        unique.setdefault(str(record["raw_import"]), record)
    return list(unique.values())


def _resolve_js_ts_relative_import(import_text: str, importer_rel: str, file_node_by_rel: Mapping[str, str]) -> str:
    if not import_text.startswith(("./", "../")):
        return ""
    base = (Path(importer_rel).parent / import_text).as_posix()
    base = str(Path(base))
    raw_candidates = [base]
    if Path(base).suffix:
        raw_candidates.append(base)
    else:
        raw_candidates.extend(f"{base}{ext}" for ext in JS_TS_EXTENSIONS)
    raw_candidates.extend(f"{base}/index{ext}" for ext in JS_TS_EXTENSIONS)
    for candidate in raw_candidates:
        normalized = Path(candidate).as_posix()
        while normalized.startswith("./"):
            normalized = normalized[2:]
        if normalized in file_node_by_rel:
            return normalized
    return ""


def dependency_fragment_for_file(
    target: Path,
    rel: str,
    file_node_by_rel: Mapping[str, str],
    *,
    source_file_node_id: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    normalized_rel = Path(str(rel).replace("\\", "/")).as_posix()
    source_id = source_file_node_id or file_node_by_rel.get(normalized_rel, "")
    if not source_id:
        return {"nodes": [], "edges": []}
    suffix = Path(normalized_rel).suffix.lower()
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}

    def add_node(node: dict[str, Any]) -> str:
        nodes[node["node_id"]] = node
        return str(node["node_id"])

    def add_edge(edge: dict[str, Any]) -> None:
        edges[edge["edge_id"]] = edge

    if suffix == ".py":
        source = "python_ast_import"
        own_module = python_module_name_for_rel(normalized_rel)
        if own_module:
            own_module_id = add_node(module_node(own_module, language="Python", source=source))
            add_edge(
                graph_edge(
                    "defines_module",
                    source_id,
                    own_module_id,
                    metadata={"source_path": normalized_rel, "module": own_module, "source": source},
                    facts=dependency_facts(source, 1.0, True, own_module),
                )
            )
        for record in _python_import_records(target, normalized_rel):
            raw_import = str(record.get("raw_import") or record.get("module") or "")
            module_name = str(record.get("module") or raw_import)
            module_id = add_node(module_node(module_name, language="Python", source=source))
            resolved_rel = _resolve_python_module(module_name, file_node_by_rel)
            resolved = bool(resolved_rel)
            confidence = 0.95 if resolved else 0.2
            add_edge(
                graph_edge(
                    "references",
                    source_id,
                    module_id,
                    metadata={
                        "source_path": normalized_rel,
                        "module": module_name,
                        "raw_import": raw_import,
                        "resolved": resolved,
                        "source": source,
                    },
                    facts=dependency_facts(source, confidence, resolved, raw_import),
                )
            )
            if resolved:
                target_id = file_node_by_rel[resolved_rel]
                add_edge(
                    graph_edge(
                        "imports",
                        source_id,
                        target_id,
                        metadata={
                            "source_path": normalized_rel,
                            "target_path": resolved_rel,
                            "module": module_name,
                            "raw_import": raw_import,
                            "resolved": True,
                            "source": source,
                        },
                        facts=dependency_facts(source, 0.95, True, raw_import),
                    )
                )
                add_edge(
                    graph_edge(
                        "resolved_to",
                        module_id,
                        target_id,
                        metadata={
                            "source_path": normalized_rel,
                            "target_path": resolved_rel,
                            "module": module_name,
                            "raw_import": raw_import,
                            "resolved": True,
                            "source": source,
                        },
                        facts=dependency_facts(source, 0.95, True, raw_import),
                    )
                )
    elif suffix in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
        source = "js_ts_import_regex"
        for record in _js_ts_import_records(target, normalized_rel):
            raw_import = str(record.get("raw_import") or "")
            resolved_rel = _resolve_js_ts_relative_import(raw_import, normalized_rel, file_node_by_rel)
            resolved = bool(resolved_rel)
            module_id = add_node(module_node(raw_import, language="JavaScript", source=source))
            confidence = 0.9 if resolved else 0.2
            add_edge(
                graph_edge(
                    "references",
                    source_id,
                    module_id,
                    metadata={
                        "source_path": normalized_rel,
                        "module": raw_import,
                        "raw_import": raw_import,
                        "resolved": resolved,
                        "source": source,
                    },
                    facts=dependency_facts(source, confidence, resolved, raw_import),
                )
            )
            if resolved:
                target_id = file_node_by_rel[resolved_rel]
                add_edge(
                    graph_edge(
                        "imports",
                        source_id,
                        target_id,
                        metadata={
                            "source_path": normalized_rel,
                            "target_path": resolved_rel,
                            "module": raw_import,
                            "raw_import": raw_import,
                            "resolved": True,
                            "source": source,
                        },
                        facts=dependency_facts(source, 0.9, True, raw_import),
                    )
                )
                add_edge(
                    graph_edge(
                        "resolved_to",
                        module_id,
                        target_id,
                        metadata={
                            "source_path": normalized_rel,
                            "target_path": resolved_rel,
                            "module": raw_import,
                            "raw_import": raw_import,
                            "resolved": True,
                            "source": source,
                        },
                        facts=dependency_facts(source, 0.9, True, raw_import),
                    )
                )
    return {"nodes": list(nodes.values()), "edges": list(edges.values())}


def build_codebase_graph(target: Path, capability: Mapping[str, Any] | None = None) -> dict[str, Any]:
    target = target.expanduser().resolve()
    directories, files, truncated = scan_repo_paths(target, limit=CODEBASE_GRAPH_SCAN_LIMIT)
    inventory = graph_inventory_from_paths(target, directories, files, truncated=truncated)
    head_commit = git_value(target, "rev-parse", "--verify", "HEAD")
    status_porcelain = git_value(target, "status", "--porcelain=v1", "--untracked-files=no")
    dirty_lines = sorted(line for line in status_porcelain.splitlines() if line.strip())
    dirty_digest = sha256_text("\n".join(dirty_lines)) if dirty_lines else ""

    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}

    def add_node(node: dict[str, Any]) -> str:
        nodes[node["node_id"]] = node
        return str(node["node_id"])

    def add_edge(edge: dict[str, Any]) -> None:
        edges[edge["edge_id"]] = edge

    repo_id = add_node(
        graph_node(
            "repo",
            "repo",
            path=".",
            name=target.name or "repo",
            metadata={"vcs": "git" if head_commit else "unknown"},
            facts=[
                graph_fact("head_commit", head_commit),
                graph_fact("dirty_tracked_file_count", len(dirty_lines), value_type="integer"),
            ],
        )
    )
    command_signature_digest = codebase_command_signature_digest(target, capability)
    directory_ids: dict[str, str] = {
        ".": add_node(graph_node("directory", "directory:.", path=".", name=".", metadata={"depth": 0}))
    }
    add_edge(graph_edge("contains", repo_id, directory_ids["."], facts=[graph_fact("relation", "repo_root")]))

    for directory in sorted(directories, key=lambda item: item.relative_to(target).as_posix()):
        rel = directory.relative_to(target).as_posix()
        directory_ids[rel] = add_node(
            graph_node(
                "directory",
                f"directory:{rel}",
                path=rel,
                name=directory.name,
                metadata={"depth": len(Path(rel).parts)},
            )
        )
    for rel, node_id in sorted(directory_ids.items()):
        if rel == ".":
            continue
        parent_rel = Path(rel).parent.as_posix()
        if parent_rel == ".":
            parent_rel = "."
        parent_id = directory_ids.get(parent_rel, directory_ids["."])
        add_edge(graph_edge("contains", parent_id, node_id, facts=[graph_fact("relation", "directory_child")]))

    file_node_by_rel: dict[str, str] = {}
    source_file_rels: list[str] = []
    for path in sorted(files, key=lambda item: item.relative_to(target).as_posix()):
        rel = path.relative_to(target).as_posix()
        node = file_node_for_path(target, rel)
        node_id = add_node(node)
        file_node_by_rel[rel] = node_id
        if node["kind"] != "test_file":
            source_file_rels.append(rel)
        parent_rel = Path(rel).parent.as_posix()
        parent_id = directory_ids.get(parent_rel if parent_rel != "." else ".", directory_ids["."])
        add_edge(graph_edge("contains", parent_id, node_id, facts=[graph_fact("relation", "file_child")]))
        if node["kind"] == "config_file":
            add_edge(graph_edge("configures", node_id, repo_id, facts=[graph_fact("relation", "configures_repo")]))
        elif node["kind"] == "doc_file":
            add_edge(graph_edge("documents", node_id, repo_id, facts=[graph_fact("relation", "documents_repo")]))

    for command in _codebase_command_candidates(target, capability):
        command_text = str(command.get("command") or "")
        source = str(command.get("source") or "")
        kind = str(command.get("kind") or "command")
        node_id = add_node(
            graph_node(
                "command",
                f"command:{source}:{command_text}",
                name=command_text[:160],
                digest=sha256_text(stable_json(command)),
                metadata={
                    "command_kind": kind,
                    "source": source,
                    "origin": str(command.get("origin") or ""),
                    "script": str(command.get("script") or ""),
                    "script_digest": str(command.get("script_digest") or ""),
                },
                facts=[
                    graph_fact("command", command_text),
                    graph_fact("command_kind", kind),
                    graph_fact("source", source),
                ],
            )
        )
        if _command_validates_repo(command):
            add_edge(graph_edge("validates", node_id, repo_id, facts=[graph_fact("relation", "validates_repo")]))

    for rel, test_node_id in sorted(file_node_by_rel.items()):
        node = nodes[test_node_id]
        if node["kind"] != "test_file":
            continue
        for source_rel in _likely_tested_sources(rel, source_file_rels):
            source_node_id = file_node_by_rel.get(source_rel)
            if source_node_id:
                add_edge(
                    graph_edge(
                        "likely_tests",
                        test_node_id,
                        source_node_id,
                        metadata={"reason": "test_file_naming", "test_path": rel, "source_path": rel, "source_path_hint": source_rel},
                        facts=[
                            graph_fact("reason", "test_file_naming"),
                            graph_fact("confidence", "0.6", value_type="number", confidence=0.6),
                        ],
                    )
                )

    for rel in sorted(file_node_by_rel):
        fragment = dependency_fragment_for_file(target, rel, file_node_by_rel)
        for node in fragment["nodes"]:
            add_node(node)
        for edge in fragment["edges"]:
            add_edge(edge)

    node_counts: dict[str, int] = {}
    for node in nodes.values():
        node_counts[str(node["kind"])] = node_counts.get(str(node["kind"]), 0) + 1
    edge_counts: dict[str, int] = {}
    for edge in edges.values():
        edge_counts[str(edge["kind"])] = edge_counts.get(str(edge["kind"]), 0) + 1
    indexed_file_count = sum(node_counts.get(kind, 0) for kind in GRAPH_FILE_NODE_KINDS)
    digest_payload = {
        "schema_version": 1,
        "graph_namespace": CODEBASE_GRAPH_NAMESPACE,
        "repo": {"name": target.name or "repo", "head_commit": head_commit},
        "dirty_tracked_file_count": len(dirty_lines),
        "dirty_tracked_files_digest": dirty_digest,
        "nodes": [
            {
                "kind": node["kind"],
                "path": node["path"],
                "name": node["name"],
                "digest": node["digest"],
                "metadata": node["metadata"],
            }
            for node in sorted(nodes.values(), key=lambda item: (str(item["kind"]), str(item["path"]), str(item["name"])))
        ],
        "edges": [
            {
                "kind": edge["kind"],
                "from": edge["from_node_id"],
                "to": edge["to_node_id"],
                "metadata": edge["metadata"],
            }
            for edge in sorted(edges.values(), key=lambda item: (str(item["kind"]), str(item["from_node_id"]), str(item["to_node_id"])))
        ],
    }
    graph_digest = sha256_text(stable_json(digest_payload))
    return {
        "schema_version": 1,
        "snapshot_id": f"graph-snapshot:{CODEBASE_GRAPH_NAMESPACE}:{graph_digest[:24]}",
        "graph_namespace": CODEBASE_GRAPH_NAMESPACE,
        "repo_root": str(target),
        "generated_at": "",
        "head_commit": head_commit,
        "dirty_tracked_file_count": len(dirty_lines),
        "dirty_tracked_files_digest": dirty_digest,
        "indexed_file_count": indexed_file_count,
        "directory_node_count": node_counts.get("directory", 0),
        "command_node_count": node_counts.get("command", 0),
        "test_node_count": node_counts.get("test_file", 0),
        "stale_node_count": 0,
        "digest": graph_digest,
        "payload": {
            "schema_version": 1,
            "scan_limit": CODEBASE_GRAPH_SCAN_LIMIT,
            "truncated": truncated,
            "graph_inventory_digest": inventory["graph_inventory_digest"],
            "indexed_path_count": inventory["indexed_path_count"],
            "indexed_paths_truncated": inventory["indexed_paths_truncated"],
            "indexed_path_sample": inventory["indexed_path_sample"],
            "command_signature_digest": command_signature_digest,
            "node_counts": dict(sorted(node_counts.items())),
            "edge_counts": dict(sorted(edge_counts.items())),
        },
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
    }
