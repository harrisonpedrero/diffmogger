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
DEPENDENCY_EDGE_KINDS = {"imports", "references", "defines_module", "resolved_to", "owns_symbol"}

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
    ".graphql": "GraphQL",
    ".gql": "GraphQL",
    ".proto": "Protocol Buffers",
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
JS_TS_SOURCE_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
JS_TS_IMPORT_RE = re.compile(
    r"""
    (?:\bimport\s+(?:type\s+)?(?:[^;]*?\s+from\s+)?|\bexport\s+(?:type\s+)?[^;]*?\s+from\s+)
    ["'](?P<import>[^"']+)["']
    |\brequire\(\s*["'](?P<require>[^"']+)["']\s*\)
    """,
    re.VERBOSE,
)
JS_TS_IMPORT_STATEMENT_RE = re.compile(
    r"""
    \bimport\s+(?:type\s+)?
    (?P<clause>[\s\S]*?)
    \s+from\s+["'](?P<module>[^"']+)["']
    |\bimport\s*["'](?P<side_effect>[^"']+)["']
    |\bexport\s+(?:type\s+)?(?P<export_clause>[\s\S]*?)\s+from\s+["'](?P<export_module>[^"']+)["']
    |\brequire\(\s*["'](?P<require>[^"']+)["']\s*\)
    """,
    re.VERBOSE,
)
PYTHON_SYMBOL_KINDS = {"function", "async_function", "class", "method", "async_method"}
JS_TS_SYMBOL_KINDS = {"function", "class", "method", "component"}
SYMBOL_IDENTITY_SCHEMA_VERSION = 1
SYMBOL_RESOLUTION_KINDS = {"exact", "inferred", "ambiguous", "unresolved", "stale"}
SYMBOL_EXTRACTOR_VERSION = "symbol-index-v1"
RUST_SYMBOL_KINDS = {"module", "function", "method", "struct", "enum", "trait", "field"}
GO_SYMBOL_KINDS = {"function", "method", "struct", "interface", "type", "field"}
JAVA_SYMBOL_KINDS = {"class", "interface", "enum", "record", "method", "field"}
SEMANTIC_REFERENCE_SOURCE = "semantic_resolution"
CROSS_LANGUAGE_INTERFACE_SOURCE = "cross_language_interface"
SEMANTIC_REFERENCE_SIGNAL_KINDS = {
    "exact_symbol_reference",
    "ambiguous_symbol_reference",
    "interface_bridge",
}
INTERFACE_FILE_EXTENSIONS = {".graphql", ".gql", ".proto", ".sql", ".yaml", ".yml", ".json"}
SEMANTIC_SOURCE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".rs", ".go", ".java"}
SEMANTIC_SYMBOL_STOP_WORDS = {
    "api",
    "app",
    "class",
    "const",
    "data",
    "default",
    "enum",
    "error",
    "event",
    "field",
    "func",
    "function",
    "handler",
    "impl",
    "index",
    "input",
    "interface",
    "main",
    "model",
    "props",
    "request",
    "response",
    "result",
    "route",
    "self",
    "service",
    "state",
    "string",
    "struct",
    "type",
    "value",
    "void",
}
GENERATED_CLIENT_SUFFIX_WORDS = {
    "api",
    "client",
    "controller",
    "grpc",
    "handler",
    "model",
    "mutation",
    "query",
    "repository",
    "request",
    "resolver",
    "response",
    "route",
    "service",
}


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


def _normalized_rel_path(value: str | Path) -> str:
    raw = str(value or "").replace("\\", "/").strip()
    return Path(raw).as_posix() if raw else ""


def _line_col_for_offset(text: str, offset: int) -> tuple[int, int]:
    offset = max(0, min(len(text), int(offset or 0)))
    prefix = text[:offset]
    line = prefix.count("\n") + 1
    previous_newline = prefix.rfind("\n")
    col = offset + 1 if previous_newline < 0 else offset - previous_newline
    return line, col


def _owning_range(
    *,
    start_line: int = 0,
    start_col: int = 0,
    end_line: int = 0,
    end_col: int = 0,
) -> dict[str, int]:
    start_line = max(0, int(start_line or 0))
    start_col = max(0, int(start_col or 0))
    end_line = max(start_line, int(end_line or start_line or 0))
    end_col = max(0, int(end_col or 0))
    return {
        "start_line": start_line,
        "start_col": start_col,
        "end_line": end_line,
        "end_col": end_col,
    }


def _symbol_visibility(name: str, *, exported: bool = False, explicit: str = "") -> str:
    explicit_value = str(explicit or "").strip().lower()
    if explicit_value in {"public", "private", "protected", "internal", "package", "unknown"}:
        return explicit_value
    clean_name = str(name or "")
    if clean_name.startswith("_"):
        return "private"
    return "public" if exported else "private"


def _symbol_identity_id(identity: Mapping[str, Any]) -> str:
    stable_identity = {
        key: value
        for key, value in identity.items()
        if key not in {"extractor_confidence", "resolution_kind"}
    }
    return f"symbol:{sha256_text(stable_json(stable_identity))[:24]}"


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


def symbol_node(
    *,
    rel: str,
    language: str,
    symbol_kind: str,
    name: str,
    qualified_name: str,
    source: str,
    confidence: float = 0.9,
    exported: bool = False,
    lineno: int = 0,
    parent_symbol: str = "",
    package_name: str = "",
    module_name: str = "",
    visibility: str = "",
    range_start_line: int = 0,
    range_start_col: int = 0,
    range_end_line: int = 0,
    range_end_col: int = 0,
    extractor_confidence: float | None = None,
    resolution_kind: str = "exact",
    owner_file_path: str | None = None,
    reference_file_path: str = "",
) -> dict[str, Any]:
    normalized_rel = _normalized_rel_path(rel)
    owner_path = _normalized_rel_path(owner_file_path) if owner_file_path is not None else normalized_rel
    reference_path = _normalized_rel_path(reference_file_path) if reference_file_path else ""
    clean_resolution = str(resolution_kind or "exact").strip().lower()
    if clean_resolution not in SYMBOL_RESOLUTION_KINDS:
        clean_resolution = "inferred"
    clean_name = str(name or "").strip()
    clean_qualified = str(qualified_name or clean_name).strip()
    clean_package = str(package_name or "").strip()
    clean_module = str(module_name or "").strip()
    clean_visibility = _symbol_visibility(clean_name, exported=exported, explicit=visibility)
    confidence = float(confidence)
    extractor_confidence_value = float(confidence if extractor_confidence is None else extractor_confidence)
    owning_range = _owning_range(
        start_line=range_start_line or lineno,
        start_col=range_start_col,
        end_line=range_end_line or range_start_line or lineno,
        end_col=range_end_col,
    )
    identity = {
        "schema_version": SYMBOL_IDENTITY_SCHEMA_VERSION,
        "language": language,
        "package_name": clean_package,
        "module_name": clean_module,
        "file_path": owner_path or normalized_rel,
        "qualified_name": clean_qualified,
        "symbol_kind": symbol_kind,
        "visibility": clean_visibility,
        "exported": bool(exported),
        "owning_range": owning_range,
        "extractor_confidence": extractor_confidence_value,
        "resolution_kind": clean_resolution,
    }
    symbol_id = _symbol_identity_id(identity)
    metadata = {
        "symbol_identity_schema_version": SYMBOL_IDENTITY_SCHEMA_VERSION,
        "symbol_id": symbol_id,
        "file_path": owner_path or normalized_rel,
        "owner_file_path": owner_path,
        "reference_file_path": reference_path,
        "language": language,
        "symbol_kind": symbol_kind,
        "qualified_name": clean_qualified,
        "package_name": clean_package,
        "module_name": clean_module,
        "visibility": clean_visibility,
        "exported": bool(exported),
        "lineno": int(lineno or 0),
        "owning_range": owning_range,
        "range_start_line": owning_range["start_line"],
        "range_start_col": owning_range["start_col"],
        "range_end_line": owning_range["end_line"],
        "range_end_col": owning_range["end_col"],
        "extractor_confidence": extractor_confidence_value,
        "confidence": confidence,
        "resolution_kind": clean_resolution,
        "resolved": clean_resolution not in {"unresolved", "ambiguous"},
        "ambiguous": clean_resolution == "ambiguous",
        "unresolved": clean_resolution == "unresolved",
        "symbol_identity": identity,
        "source": source,
    }
    if parent_symbol:
        metadata["parent_symbol"] = parent_symbol
    return graph_node(
        "symbol",
        symbol_id,
        path=normalized_rel,
        name=clean_name,
        digest=sha256_text(stable_json(metadata)),
        metadata=metadata,
        facts=[
            graph_fact("symbol_id", symbol_id, source=source, confidence=confidence),
            graph_fact("symbol_identity_schema_version", SYMBOL_IDENTITY_SCHEMA_VERSION, value_type="integer", source=source, confidence=confidence),
            graph_fact("symbol_name", clean_name, source=source, confidence=confidence),
            graph_fact("qualified_name", clean_qualified, source=source, confidence=confidence),
            graph_fact("symbol_kind", symbol_kind, source=source, confidence=confidence),
            graph_fact("owner_file_path", owner_path, source=source, confidence=confidence),
            graph_fact("file_path", owner_path or normalized_rel, source=source, confidence=confidence),
            graph_fact("reference_file_path", reference_path, source=source, confidence=confidence),
            graph_fact("language", language, source=source, confidence=confidence),
            graph_fact("package_name", clean_package, source=source, confidence=confidence),
            graph_fact("module_name", clean_module, source=source, confidence=confidence),
            graph_fact("visibility", clean_visibility, source=source, confidence=confidence),
            graph_fact("exported", "true" if exported else "false", value_type="boolean", source=source, confidence=confidence),
            graph_fact("owning_range", stable_json(owning_range), value_type="json", source=source, confidence=confidence),
            graph_fact("extractor_confidence", extractor_confidence_value, value_type="number", source=source, confidence=confidence),
            graph_fact("resolution_kind", clean_resolution, source=source, confidence=confidence),
            graph_fact("resolved", "true" if clean_resolution not in {"unresolved", "ambiguous"} else "false", value_type="boolean", source=source, confidence=confidence),
            graph_fact("confidence", confidence, value_type="number", source=source, confidence=confidence),
        ],
    )


def ownership_edge(
    file_node_id: str,
    symbol_node_id: str,
    *,
    rel: str,
    symbol_name: str,
    symbol_kind: str,
    source: str,
    confidence: float,
) -> dict[str, Any]:
    return graph_edge(
        "owns_symbol",
        file_node_id,
        symbol_node_id,
        metadata={
            "source_path": rel,
            "symbol_name": symbol_name,
            "symbol_kind": symbol_kind,
            "source": source,
            "confidence": float(confidence),
        },
        facts=[
            graph_fact("relation", "owns_symbol", source=source, confidence=confidence),
            graph_fact("symbol_name", symbol_name, source=source, confidence=confidence),
            graph_fact("symbol_kind", symbol_kind, source=source, confidence=confidence),
            graph_fact("confidence", confidence, value_type="number", source=source, confidence=confidence),
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


def _python_package_name_for_rel(rel: str | Path) -> str:
    module_name = python_module_name_for_rel(rel)
    return module_name.split(".", 1)[0] if module_name else ""


def _path_module_name_for_rel(rel: str | Path, *, separator: str = ".") -> str:
    path = Path(str(rel).replace("\\", "/"))
    parts = list(path.with_suffix("").parts)
    if parts and parts[-1] in {"index", "mod", "lib", "main"}:
        parts = parts[:-1] or parts
    return separator.join(parts)


def _nearest_package_json_name(target: Path, rel: str) -> str:
    path = (target / rel).parent
    root = target.resolve()
    for current in [path, *path.parents]:
        try:
            current.resolve().relative_to(root)
        except ValueError:
            break
        package_path = current / "package.json"
        try:
            data = json.loads(package_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            name = str(data.get("name") or "").strip()
            if name:
                return name
    return ""


def _go_module_name(target: Path) -> str:
    text = read_optional_text(target / "go.mod", limit=80_000)
    match = re.search(r"(?m)^\s*module\s+(\S+)", text)
    return match.group(1).strip() if match else ""


def _cargo_package_name(target: Path) -> str:
    text = read_optional_text(target / "Cargo.toml", limit=120_000)
    in_package = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        section = re.match(r"\[(?P<section>[^\]]+)\]", line)
        if section:
            in_package = section.group("section").strip() == "package"
            continue
        if in_package:
            match = re.match(r"name\s*=\s*[\"']([^\"']+)[\"']", line)
            if match:
                return match.group(1).strip()
    return ""


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


def _python_symbol_records(target: Path, rel: str) -> tuple[list[dict[str, Any]], str]:
    text = read_optional_text(target / rel, limit=300_000)
    if not text:
        return [], "empty"
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return [], "syntax_error"
    module_name = python_module_name_for_rel(rel)
    package_name = _python_package_name_for_rel(rel)
    records: list[dict[str, Any]] = []

    def add_record(
        *,
        name: str,
        symbol_kind: str,
        lineno: int,
        end_lineno: int = 0,
        col_offset: int = 0,
        end_col_offset: int = 0,
        parent_symbol: str = "",
    ) -> None:
        clean_name = str(name or "").strip()
        if not clean_name:
            return
        qualified = ".".join(part for part in (module_name, parent_symbol, clean_name) if part)
        records.append(
            {
                "name": clean_name,
                "qualified_name": qualified or clean_name,
                "symbol_kind": symbol_kind,
                "lineno": int(lineno or 0),
                "range_start_line": int(lineno or 0),
                "range_start_col": int(col_offset or 0) + 1 if lineno else 0,
                "range_end_line": int(end_lineno or lineno or 0),
                "range_end_col": int(end_col_offset or 0) + 1 if end_col_offset else 0,
                "package_name": package_name,
                "module_name": module_name,
                "visibility": _symbol_visibility(clean_name, exported=not clean_name.startswith("_")),
                "parent_symbol": parent_symbol,
                "exported": not clean_name.startswith("_"),
                "confidence": 1.0,
                "extractor_confidence": 1.0,
                "resolution_kind": "exact",
            }
        )

    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            add_record(
                name=node.name,
                symbol_kind="async_function" if isinstance(node, ast.AsyncFunctionDef) else "function",
                lineno=getattr(node, "lineno", 0),
                end_lineno=getattr(node, "end_lineno", 0),
                col_offset=getattr(node, "col_offset", 0),
                end_col_offset=getattr(node, "end_col_offset", 0),
            )
        elif isinstance(node, ast.ClassDef):
            add_record(
                name=node.name,
                symbol_kind="class",
                lineno=getattr(node, "lineno", 0),
                end_lineno=getattr(node, "end_lineno", 0),
                col_offset=getattr(node, "col_offset", 0),
                end_col_offset=getattr(node, "end_col_offset", 0),
            )
            for child in getattr(node, "body", []):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    add_record(
                        name=child.name,
                        symbol_kind="async_method" if isinstance(child, ast.AsyncFunctionDef) else "method",
                        lineno=getattr(child, "lineno", 0),
                        end_lineno=getattr(child, "end_lineno", 0),
                        col_offset=getattr(child, "col_offset", 0),
                        end_col_offset=getattr(child, "end_col_offset", 0),
                        parent_symbol=node.name,
                    )

    return records, "ok"


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


def _parse_js_ts_import_clause(clause: str) -> list[str]:
    clause = re.sub(r"\btype\b", "", str(clause or "")).strip()
    if not clause:
        return []
    symbols: list[str] = []
    namespace = re.search(r"\*\s+as\s+([A-Za-z_$][\w$]*)", clause)
    if namespace:
        symbols.append(namespace.group(1))
    named = re.search(r"\{(?P<body>[^}]*)\}", clause, flags=re.S)
    if named:
        for part in named.group("body").split(","):
            item = part.strip()
            if not item:
                continue
            item = re.sub(r"^\s*type\s+", "", item)
            alias_match = re.search(r"\bas\s+([A-Za-z_$][\w$]*)$", item)
            if alias_match:
                symbols.append(alias_match.group(1))
            else:
                name_match = re.match(r"([A-Za-z_$][\w$]*)", item)
                if name_match:
                    symbols.append(name_match.group(1))
    prefix = clause.split("{", 1)[0].strip().rstrip(",").strip()
    if prefix and not prefix.startswith("*"):
        default_name = prefix.split(",", 1)[0].strip()
        if re.match(r"^[A-Za-z_$][\w$]*$", default_name):
            symbols.append(default_name)
    return sorted(set(symbols))


def _js_ts_import_records(target: Path, rel: str) -> list[dict[str, Any]]:
    text = _strip_js_ts_comments(read_optional_text(target / rel, limit=300_000))
    records: list[dict[str, Any]] = []
    for match in JS_TS_IMPORT_STATEMENT_RE.finditer(text):
        raw = (
            match.group("module")
            or match.group("side_effect")
            or match.group("export_module")
            or match.group("require")
            or ""
        ).strip()
        if raw:
            clause = match.group("clause") or match.group("export_clause") or ""
            records.append(
                {
                    "raw_import": raw,
                    "module": raw,
                    "lineno": text[: match.start()].count("\n") + 1,
                    "imported_symbols": _parse_js_ts_import_clause(clause),
                }
            )
    unique: dict[str, dict[str, Any]] = {}
    for record in records:
        unique.setdefault(str(record["raw_import"]), record)
    return list(unique.values())


def _is_component_like(name: str, suffix: str, snippet: str = "") -> bool:
    if not name or not name[0].isupper():
        return False
    if suffix in {".jsx", ".tsx"}:
        return True
    return bool(re.search(r"<[A-ZA-Za-z][\w.:-]*[\s/>]", snippet) or "React.createElement" in snippet)


def _js_ts_exported_names(text: str) -> set[str]:
    exported: set[str] = set()
    for match in re.finditer(r"\bexport\s+\{(?P<body>[^}]*)\}", text, flags=re.S):
        for part in match.group("body").split(","):
            item = part.strip()
            if not item:
                continue
            alias = re.search(r"\bas\s+([A-Za-z_$][\w$]*)$", item)
            if alias:
                exported.add(alias.group(1))
                continue
            name = re.match(r"(?:type\s+)?([A-Za-z_$][\w$]*)", item)
            if name:
                exported.add(name.group(1))
    return exported


def _matching_brace_end(text: str, open_brace_index: int) -> int:
    depth = 0
    quote = ""
    escape = False
    for index in range(open_brace_index, len(text)):
        char = text[index]
        if quote:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                quote = ""
            continue
        if char in {"'", '"', "`"}:
            quote = char
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return len(text)


def _delimiter_balance_status(text: str) -> str:
    stack: list[str] = []
    pairs = {"}": "{", ")": "(", "]": "["}
    quote = ""
    escape = False
    for char in text:
        if quote:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                quote = ""
            continue
        if char in {"'", '"', "`"}:
            quote = char
            continue
        if char in "{([":
            stack.append(char)
        elif char in pairs:
            if not stack or stack.pop() != pairs[char]:
                return "syntax_error"
    return "syntax_error" if quote or stack else "ok"


def _declaration_end_offset(text: str, start_offset: int) -> int:
    open_brace = text.find("{", start_offset)
    semicolon = text.find(";", start_offset)
    if open_brace >= 0 and (semicolon < 0 or open_brace < semicolon):
        return _matching_brace_end(text, open_brace)
    if semicolon >= 0:
        return semicolon
    newline = text.find("\n", start_offset)
    return newline if newline >= 0 else max(0, len(text) - 1)


def _member_lines_at_body_depth(body: str, *, base_offset: int = 0) -> list[tuple[str, int]]:
    members: list[tuple[str, int]] = []
    depth = 0
    offset = 0
    quote = ""
    escape = False
    for line in body.splitlines(keepends=True):
        if depth == 0 and line.strip():
            members.append((line, base_offset + offset))
        for char in line:
            if quote:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == quote:
                    quote = ""
                continue
            if char in {"'", '"', "`"}:
                quote = char
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth = max(0, depth - 1)
        offset += len(line)
    return members


def _js_ts_symbol_records(target: Path, rel: str) -> tuple[list[dict[str, Any]], str]:
    text = _strip_js_ts_comments(read_optional_text(target / rel, limit=300_000))
    if not text:
        return [], "empty"
    suffix = Path(rel).suffix.lower()
    module_name = _path_module_name_for_rel(rel)
    package_name = _nearest_package_json_name(target, rel)
    exported_names = _js_ts_exported_names(text)
    records_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}

    def add_record(
        *,
        name: str,
        symbol_kind: str,
        lineno: int,
        exported: bool = False,
        parent_symbol: str = "",
        confidence: float = 0.85,
        visibility: str = "",
        end_lineno: int = 0,
        col_offset: int = 0,
        end_col_offset: int = 0,
    ) -> None:
        clean_name = str(name or "").strip()
        if not clean_name:
            return
        resolved_kind = "component" if symbol_kind == "function" and _is_component_like(clean_name, suffix) else symbol_kind
        resolved_exported = bool(exported or clean_name in exported_names)
        qualified = ".".join(part for part in (module_name, parent_symbol, clean_name) if part) or clean_name
        key = (qualified, resolved_kind, parent_symbol)
        records_by_key[key] = {
            "name": clean_name,
            "qualified_name": qualified,
            "symbol_kind": resolved_kind,
            "lineno": int(lineno or 0),
            "range_start_line": int(lineno or 0),
            "range_start_col": int(col_offset or 0) + 1 if lineno else 0,
            "range_end_line": int(end_lineno or lineno or 0),
            "range_end_col": int(end_col_offset or 0) + 1 if end_col_offset else 0,
            "package_name": package_name,
            "module_name": module_name,
            "visibility": _symbol_visibility(clean_name, exported=resolved_exported, explicit=visibility),
            "parent_symbol": parent_symbol,
            "exported": resolved_exported,
            "confidence": float(confidence),
            "extractor_confidence": float(confidence),
            "resolution_kind": "exact",
        }

    for match in re.finditer(
        r"(?P<export>\bexport\s+(?:default\s+)?)?(?P<async>\basync\s+)?\bfunction\s+(?P<name>[A-Za-z_$][\w$]*)\s*(?:<[^>{}]*>)?\s*\(",
        text,
    ):
        add_record(
            name=match.group("name"),
            symbol_kind="function",
            lineno=text[: match.start()].count("\n") + 1,
            exported=bool(match.group("export")),
            confidence=0.9,
            col_offset=match.start() - text.rfind("\n", 0, match.start()) - 1,
        )

    class_ranges: list[tuple[str, int, int]] = []
    for match in re.finditer(
        r"(?P<export>\bexport\s+(?:default\s+)?)?\bclass\s+(?P<name>[A-Za-z_$][\w$]*)[^{]*\{",
        text,
    ):
        class_name = match.group("name")
        open_brace = text.find("{", match.start())
        close_brace = _matching_brace_end(text, open_brace) if open_brace >= 0 else match.end()
        class_ranges.append((class_name, open_brace, close_brace))
        start_line, start_col = _line_col_for_offset(text, match.start())
        end_line, end_col = _line_col_for_offset(text, close_brace)
        add_record(
            name=class_name,
            symbol_kind="class",
            lineno=start_line,
            exported=bool(match.group("export")),
            confidence=0.9,
            end_lineno=end_line,
            col_offset=start_col - 1,
            end_col_offset=end_col - 1,
        )
        body = text[open_brace + 1 : close_brace] if open_brace >= 0 else ""
        for method in re.finditer(
            r"(?m)^\s*(?P<mods>(?:public|private|protected|static|readonly|async|get|set|\s)*)"
            r"(?P<name>[A-Za-z_$][\w$]*)\s*(?:<[^>{}]*>)?\([^;\n{}]*\)\s*(?::[^{;\n]+)?\{",
            body,
        ):
            method_name = method.group("name")
            if method_name in {"if", "for", "while", "switch", "catch", "function"}:
                continue
            method_offset = open_brace + 1 + method.start()
            method_line, method_col = _line_col_for_offset(text, method_offset)
            mods = str(method.group("mods") or "")
            explicit_visibility = ""
            visibility_match = re.search(r"\b(public|private|protected)\b", mods)
            if visibility_match:
                explicit_visibility = visibility_match.group(1)
            add_record(
                name=method_name,
                symbol_kind="method",
                lineno=method_line,
                parent_symbol=class_name,
                confidence=0.8,
                visibility=explicit_visibility or "public",
                col_offset=method_col - 1,
            )

    for match in re.finditer(
        r"(?P<export>\bexport\s+)?\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*"
        r"(?P<initializer>(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>|(?:React\.)?(?:memo|forwardRef)\s*\()",
        text,
    ):
        snippet = text[match.start() : min(len(text), match.end() + 240)]
        add_record(
            name=match.group("name"),
            symbol_kind="component" if _is_component_like(match.group("name"), suffix, snippet) else "function",
            lineno=text[: match.start()].count("\n") + 1,
            exported=bool(match.group("export")),
            confidence=0.8,
            col_offset=match.start() - text.rfind("\n", 0, match.start()) - 1,
        )

    return [records_by_key[key] for key in sorted(records_by_key)], "ok"


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


def _rust_visibility(raw: str) -> str:
    value = str(raw or "").strip()
    if not value:
        return "private"
    if value.startswith("pub("):
        return "internal"
    return "public"


def _rust_expand_use_path(raw_path: str) -> list[str]:
    path = re.sub(r"\s+as\s+[A-Za-z_]\w*$", "", str(raw_path or "").strip())
    path = path.strip(":")
    if not path:
        return []
    if "{" not in path or "}" not in path:
        return [path]
    prefix, rest = path.split("{", 1)
    body = rest.rsplit("}", 1)[0]
    prefix = prefix.rstrip(":")
    expanded: list[str] = []
    for part in body.split(","):
        item = re.sub(r"\s+as\s+[A-Za-z_]\w*$", "", part.strip()).strip(":")
        if not item or item == "self":
            continue
        expanded.append("::".join(value for value in (prefix, item) if value))
    return expanded


def _rust_import_records(target: Path, rel: str) -> list[dict[str, Any]]:
    text = _strip_js_ts_comments(read_optional_text(target / rel, limit=300_000))
    records: list[dict[str, Any]] = []
    for match in re.finditer(r"(?m)^\s*(?:pub\s+)?use\s+(?P<path>[^;]+);", text):
        for raw_path in _rust_expand_use_path(match.group("path")):
            leaf = raw_path.rsplit("::", 1)[-1]
            records.append(
                {
                    "raw_import": raw_path,
                    "module": raw_path,
                    "lineno": text[: match.start()].count("\n") + 1,
                    "imported_symbols": [leaf] if leaf else [],
                    "import_kind": "use",
                }
            )
    for match in re.finditer(r"(?m)^\s*(?:pub(?:\([^)]*\))?\s+)?mod\s+(?P<name>[A-Za-z_]\w*)\s*;", text):
        module_name = match.group("name")
        records.append(
            {
                "raw_import": module_name,
                "module": module_name,
                "lineno": text[: match.start()].count("\n") + 1,
                "imported_symbols": [module_name],
                "import_kind": "mod",
            }
        )
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        unique.setdefault((str(record["raw_import"]), str(record.get("import_kind") or "")), record)
    return list(unique.values())


def _rust_crate_root_for_rel(importer_rel: str) -> str:
    parts = list(Path(importer_rel).parts)
    if "src" in parts:
        return Path(*parts[: parts.index("src") + 1]).as_posix()
    return "."


def _rust_candidate_for_segments(base: str, segments: list[str], file_node_by_rel: Mapping[str, str]) -> str:
    clean_segments = [segment for segment in segments if segment and re.match(r"^[A-Za-z_]\w*$", segment)]
    base_path = Path(base) if base and base != "." else Path(".")
    for end in range(len(clean_segments), 0, -1):
        prefix = Path(*clean_segments[:end]).as_posix()
        raw_candidates = [
            (base_path / f"{prefix}.rs").as_posix(),
            (base_path / prefix / "mod.rs").as_posix(),
        ]
        for candidate in raw_candidates:
            normalized = candidate[2:] if candidate.startswith("./") else candidate
            if normalized in file_node_by_rel:
                return normalized
    return ""


def _resolve_rust_import(import_text: str, importer_rel: str, file_node_by_rel: Mapping[str, str]) -> str:
    raw_parts = [part for part in str(import_text or "").split("::") if part and part != "self"]
    if not raw_parts:
        return ""
    crate_root = _rust_crate_root_for_rel(importer_rel)
    first = raw_parts[0]
    if first == "crate":
        return _rust_candidate_for_segments(crate_root, raw_parts[1:], file_node_by_rel)
    if first == "super":
        parent = Path(importer_rel).parent.parent
        return _rust_candidate_for_segments(parent.as_posix(), raw_parts[1:], file_node_by_rel)
    if first in {"std", "core", "alloc"}:
        return ""
    parent = Path(importer_rel).parent
    resolved = _rust_candidate_for_segments(parent.as_posix(), raw_parts, file_node_by_rel)
    if resolved:
        return resolved
    return _rust_candidate_for_segments(crate_root, raw_parts, file_node_by_rel)


def _rust_symbol_records(target: Path, rel: str) -> tuple[list[dict[str, Any]], str]:
    text = _strip_js_ts_comments(read_optional_text(target / rel, limit=300_000))
    if not text:
        return [], "empty"
    if _delimiter_balance_status(text) != "ok":
        return [], "syntax_error"
    module_name = _path_module_name_for_rel(rel, separator="::")
    package_name = _cargo_package_name(target)
    records_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}

    def add_record(
        *,
        name: str,
        symbol_kind: str,
        start_offset: int,
        end_offset: int | None = None,
        visibility: str = "private",
        parent_symbol: str = "",
        confidence: float = 0.78,
    ) -> None:
        clean_name = str(name or "").strip()
        if not clean_name:
            return
        start_line, start_col = _line_col_for_offset(text, start_offset)
        end_line, end_col = _line_col_for_offset(text, end_offset if end_offset is not None else start_offset)
        qualified = "::".join(part for part in (module_name, parent_symbol, clean_name) if part) or clean_name
        key = (qualified, symbol_kind, parent_symbol)
        records_by_key[key] = {
            "name": clean_name,
            "qualified_name": qualified,
            "symbol_kind": symbol_kind,
            "lineno": start_line,
            "range_start_line": start_line,
            "range_start_col": start_col,
            "range_end_line": end_line,
            "range_end_col": end_col,
            "package_name": package_name,
            "module_name": module_name,
            "visibility": visibility,
            "parent_symbol": parent_symbol,
            "exported": visibility == "public",
            "confidence": confidence,
            "extractor_confidence": confidence,
            "resolution_kind": "exact",
        }

    for match in re.finditer(
        r"(?m)^(?P<indent>\s*)(?P<vis>pub(?:\([^)]*\))?\s+)?mod\s+(?P<name>[A-Za-z_]\w*)\b(?P<tail>\s*[;{])",
        text,
    ):
        if match.group("indent").strip():
            continue
        add_record(
            name=match.group("name"),
            symbol_kind="module",
            start_offset=match.start(),
            end_offset=_declaration_end_offset(text, match.start()),
            visibility=_rust_visibility(match.group("vis") or ""),
            confidence=0.74,
        )

    for match in re.finditer(
        r"(?m)^(?P<indent>\s*)(?P<vis>pub(?:\([^)]*\))?\s+)?(?P<kind>struct|enum|trait)\s+(?P<name>[A-Za-z_]\w*)\b",
        text,
    ):
        if match.group("indent").strip():
            continue
        declaration_end = _declaration_end_offset(text, match.start())
        add_record(
            name=match.group("name"),
            symbol_kind=match.group("kind"),
            start_offset=match.start(),
            end_offset=declaration_end,
            visibility=_rust_visibility(match.group("vis") or ""),
        )
        if match.group("kind") == "struct":
            open_brace = text.find("{", match.end(), declaration_end + 1)
            if open_brace >= 0 and open_brace <= declaration_end:
                body = text[open_brace + 1 : declaration_end]
                for field in re.finditer(
                    r"(?m)^\s*(?P<vis>pub(?:\([^)]*\))?\s+)?(?P<name>[A-Za-z_]\w*)\s*:",
                    body,
                ):
                    add_record(
                        name=field.group("name"),
                        symbol_kind="field",
                        start_offset=open_brace + 1 + field.start(),
                        visibility=_rust_visibility(field.group("vis") or ""),
                        parent_symbol=match.group("name"),
                        confidence=0.66,
                    )

    for match in re.finditer(
        r"(?m)^(?P<indent>\s*)(?P<vis>pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+(?P<name>[A-Za-z_]\w*)\s*(?:<[^>{}]*>)?\(",
        text,
    ):
        if match.group("indent").strip():
            continue
        add_record(
            name=match.group("name"),
            symbol_kind="function",
            start_offset=match.start(),
            end_offset=_declaration_end_offset(text, match.start()),
            visibility=_rust_visibility(match.group("vis") or ""),
        )

    for impl in re.finditer(r"(?m)^\s*impl(?:<[^>{}]*>)?\s+(?:[A-Za-z_]\w+\s+for\s+)?(?P<name>[A-Za-z_]\w*)[^{]*\{", text):
        parent = impl.group("name")
        open_brace = text.find("{", impl.start())
        close_brace = _matching_brace_end(text, open_brace) if open_brace >= 0 else impl.end()
        body = text[open_brace + 1 : close_brace] if open_brace >= 0 else ""
        for method in re.finditer(
            r"(?m)^\s*(?P<vis>pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+(?P<name>[A-Za-z_]\w*)\s*(?:<[^>{}]*>)?\(",
            body,
        ):
            add_record(
                name=method.group("name"),
                symbol_kind="method",
                start_offset=open_brace + 1 + method.start(),
                end_offset=_declaration_end_offset(text, open_brace + 1 + method.start()),
                visibility=_rust_visibility(method.group("vis") or ""),
                parent_symbol=parent,
                confidence=0.74,
            )

    return [records_by_key[key] for key in sorted(records_by_key)], "ok"


def _go_import_records(target: Path, rel: str) -> list[dict[str, Any]]:
    text = _strip_js_ts_comments(read_optional_text(target / rel, limit=300_000))
    records: list[dict[str, Any]] = []

    def add_import(raw: str, *, lineno: int, alias: str = "") -> None:
        path = str(raw or "").strip()
        if not path:
            return
        imported_symbol = alias if alias and alias not in {"_", "."} else path.rsplit("/", 1)[-1]
        records.append(
            {
                "raw_import": path,
                "module": path,
                "lineno": lineno,
                "imported_symbols": [imported_symbol] if imported_symbol else [],
            }
        )

    block_spans: list[tuple[int, int]] = []
    for block in re.finditer(r"(?ms)^\s*import\s*\((?P<body>.*?)\)", text):
        block_spans.append((block.start(), block.end()))
        base_lineno = text[: block.start()].count("\n") + 1
        for line_index, raw_line in enumerate(block.group("body").splitlines(), start=1):
            line = raw_line.strip().rstrip(",")
            if not line:
                continue
            match = re.match(r"(?:(?P<alias>[A-Za-z_]\w*|[_.])\s+)?[\"`](?P<path>[^\"`]+)[\"`]", line)
            if match:
                add_import(match.group("path"), lineno=base_lineno + line_index, alias=match.group("alias") or "")
    for match in re.finditer(r"(?m)^\s*import\s+(?:(?P<alias>[A-Za-z_]\w*|[_.])\s+)?[\"`](?P<path>[^\"`]+)[\"`]", text):
        if any(start <= match.start() < end for start, end in block_spans):
            continue
        add_import(match.group("path"), lineno=text[: match.start()].count("\n") + 1, alias=match.group("alias") or "")
    unique: dict[str, dict[str, Any]] = {}
    for record in records:
        unique.setdefault(str(record["raw_import"]), record)
    return list(unique.values())


def _resolve_go_import(import_text: str, importer_rel: str, file_node_by_rel: Mapping[str, str], target: Path) -> str:
    module_name = _go_module_name(target)
    raw = str(import_text or "").strip()
    if not raw or not module_name:
        return ""
    if raw == module_name:
        package_dir = "."
    elif raw.startswith(module_name + "/"):
        package_dir = raw[len(module_name) + 1 :]
    else:
        return ""
    candidates = [
        rel
        for rel in file_node_by_rel
        if Path(rel).suffix == ".go"
        and rel != importer_rel
        and (Path(rel).parent.as_posix() if Path(rel).parent.as_posix() != "." else ".") == package_dir
    ]
    candidates = sorted(candidates, key=lambda item: (item.endswith("_test.go"), item))
    return candidates[0] if candidates else ""


def _go_symbol_records(target: Path, rel: str) -> tuple[list[dict[str, Any]], str]:
    text = _strip_js_ts_comments(read_optional_text(target / rel, limit=300_000))
    if not text:
        return [], "empty"
    if _delimiter_balance_status(text) != "ok":
        return [], "syntax_error"
    package_decl = re.search(r"(?m)^\s*package\s+(?P<name>[A-Za-z_]\w*)\b", text)
    if not package_decl:
        return [], "syntax_error"
    module_name = package_decl.group("name") if package_decl else _path_module_name_for_rel(rel)
    package_name = _go_module_name(target)
    records_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}

    def go_visibility(name: str) -> str:
        return "public" if name[:1].isupper() else "private"

    def add_record(
        *,
        name: str,
        symbol_kind: str,
        start_offset: int,
        end_offset: int | None = None,
        parent_symbol: str = "",
        confidence: float = 0.84,
    ) -> None:
        clean_name = str(name or "").strip()
        if not clean_name:
            return
        start_line, start_col = _line_col_for_offset(text, start_offset)
        end_line, end_col = _line_col_for_offset(text, end_offset if end_offset is not None else start_offset)
        visibility = go_visibility(clean_name)
        qualified = ".".join(part for part in (module_name, parent_symbol, clean_name) if part) or clean_name
        key = (qualified, symbol_kind, parent_symbol)
        records_by_key[key] = {
            "name": clean_name,
            "qualified_name": qualified,
            "symbol_kind": symbol_kind,
            "lineno": start_line,
            "range_start_line": start_line,
            "range_start_col": start_col,
            "range_end_line": end_line,
            "range_end_col": end_col,
            "package_name": package_name,
            "module_name": module_name,
            "visibility": visibility,
            "parent_symbol": parent_symbol,
            "exported": visibility == "public",
            "confidence": confidence,
            "extractor_confidence": confidence,
            "resolution_kind": "exact",
        }

    for match in re.finditer(r"(?m)^\s*func\s+(?P<name>[A-Za-z_]\w*)\s*\(", text):
        add_record(
            name=match.group("name"),
            symbol_kind="function",
            start_offset=match.start(),
            end_offset=_declaration_end_offset(text, match.start()),
        )
    for match in re.finditer(r"(?m)^\s*func\s*\((?P<receiver>[^)]*)\)\s*(?P<name>[A-Za-z_]\w*)\s*\(", text):
        receiver = re.sub(r"[*\s]+", " ", match.group("receiver") or "").strip().split(" ")
        parent = receiver[-1] if receiver else ""
        add_record(
            name=match.group("name"),
            symbol_kind="method",
            start_offset=match.start(),
            end_offset=_declaration_end_offset(text, match.start()),
            parent_symbol=parent,
            confidence=0.82,
        )

    type_matches: list[dict[str, Any]] = []
    for match in re.finditer(
        r"(?m)^\s*type\s+(?P<name>[A-Za-z_]\w*)\s+(?P<kind>struct|interface)\b|^\s*type\s+(?P<alias>[A-Za-z_]\w*)\b",
        text,
    ):
        type_matches.append(
            {
                "name": match.group("name") or match.group("alias") or "",
                "kind": match.group("kind") or "type",
                "start_offset": match.start(),
            }
        )
    for block in re.finditer(r"(?ms)^\s*type\s*\((?P<body>.*?)\)", text):
        for entry in re.finditer(r"(?m)^\s*(?P<name>[A-Za-z_]\w*)\s+(?P<kind>struct|interface)\b", block.group("body")):
            type_matches.append(
                {
                    "name": entry.group("name") or "",
                    "kind": entry.group("kind") or "type",
                    "start_offset": block.start("body") + entry.start(),
                }
            )
    for match in type_matches:
        name = str(match.get("name") or "")
        kind = str(match.get("kind") or "type")
        start_offset = int(match.get("start_offset") or 0)
        declaration_end = _declaration_end_offset(text, start_offset)
        add_record(name=name, symbol_kind=kind, start_offset=start_offset, end_offset=declaration_end, confidence=0.84)
        open_brace = text.find("{", start_offset, declaration_end + 1)
        if open_brace < 0 or open_brace > declaration_end:
            continue
        body = text[open_brace + 1 : declaration_end]
        if kind == "struct":
            for field_line, offset in _member_lines_at_body_depth(body, base_offset=open_brace + 1):
                field = re.match(r"\s*(?P<name>[A-Za-z_]\w*)\s+(?P<type>[^`\"/{}()]+)", field_line)
                if field:
                    add_record(
                        name=field.group("name"),
                        symbol_kind="field",
                        start_offset=offset + field_line.find(field.group("name")),
                        parent_symbol=name,
                        confidence=0.7,
                    )
        elif kind == "interface":
            for method_line, offset in _member_lines_at_body_depth(body, base_offset=open_brace + 1):
                method = re.match(r"\s*(?P<name>[A-Za-z_]\w*)\s*\(", method_line)
                if method:
                    add_record(
                        name=method.group("name"),
                        symbol_kind="method",
                        start_offset=offset + method_line.find(method.group("name")),
                        parent_symbol=name,
                        confidence=0.72,
                    )

    return [records_by_key[key] for key in sorted(records_by_key)], "ok"


def _java_import_records(target: Path, rel: str) -> list[dict[str, Any]]:
    text = _strip_js_ts_comments(read_optional_text(target / rel, limit=300_000))
    records: list[dict[str, Any]] = []
    for match in re.finditer(
        r"(?m)^\s*import\s+(?:static\s+)?(?P<module>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*(?:\.\*)?)\s*;",
        text,
    ):
        module_name = match.group("module")
        leaf = "" if module_name.endswith(".*") else module_name.rsplit(".", 1)[-1]
        records.append(
            {
                "raw_import": module_name,
                "module": module_name,
                "lineno": text[: match.start()].count("\n") + 1,
                "imported_symbols": [leaf] if leaf else [],
            }
        )
    return records


def _resolve_java_import(import_text: str, importer_rel: str, file_node_by_rel: Mapping[str, str]) -> str:
    raw = str(import_text or "").strip()
    if not raw:
        return ""
    wildcard = raw.endswith(".*")
    module_path = raw[:-2].replace(".", "/") if wildcard else raw.replace(".", "/")
    if not wildcard:
        direct_candidates = [
            f"{module_path}.java",
            f"src/main/java/{module_path}.java",
            f"src/test/java/{module_path}.java",
        ]
        for candidate in direct_candidates:
            if candidate in file_node_by_rel and candidate != importer_rel:
                return candidate
        suffix = f"/{module_path}.java"
        matches = sorted(rel for rel in file_node_by_rel if rel.endswith(suffix) and rel != importer_rel)
        if matches:
            return matches[0]
    package_dir = module_path
    direct_dirs = {package_dir, f"src/main/java/{package_dir}", f"src/test/java/{package_dir}"}
    matches = sorted(
        rel
        for rel in file_node_by_rel
        if Path(rel).suffix == ".java"
        and rel != importer_rel
        and (Path(rel).parent.as_posix() in direct_dirs or Path(rel).parent.as_posix().endswith("/" + package_dir))
    )
    return matches[0] if matches else ""


def _java_symbol_records(target: Path, rel: str) -> tuple[list[dict[str, Any]], str]:
    text = _strip_js_ts_comments(read_optional_text(target / rel, limit=300_000))
    if not text:
        return [], "empty"
    if _delimiter_balance_status(text) != "ok":
        return [], "syntax_error"
    package_match = re.search(r"(?m)^\s*package\s+(?P<name>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*;", text)
    package_name = package_match.group("name") if package_match else ""
    module_name = package_name or _path_module_name_for_rel(rel)
    records_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}

    def java_visibility(mods: str) -> str:
        match = re.search(r"\b(public|protected|private)\b", str(mods or ""))
        return match.group(1) if match else "package"

    def add_record(
        *,
        name: str,
        symbol_kind: str,
        start_offset: int,
        end_offset: int | None = None,
        visibility: str = "package",
        parent_symbol: str = "",
        confidence: float = 0.78,
    ) -> None:
        clean_name = str(name or "").strip()
        if not clean_name:
            return
        start_line, start_col = _line_col_for_offset(text, start_offset)
        end_line, end_col = _line_col_for_offset(text, end_offset if end_offset is not None else start_offset)
        qualified = ".".join(part for part in (module_name, parent_symbol, clean_name) if part) or clean_name
        key = (qualified, symbol_kind, parent_symbol)
        records_by_key[key] = {
            "name": clean_name,
            "qualified_name": qualified,
            "symbol_kind": symbol_kind,
            "lineno": start_line,
            "range_start_line": start_line,
            "range_start_col": start_col,
            "range_end_line": end_line,
            "range_end_col": end_col,
            "package_name": package_name,
            "module_name": module_name,
            "visibility": visibility,
            "parent_symbol": parent_symbol,
            "exported": visibility == "public",
            "confidence": confidence,
            "extractor_confidence": confidence,
            "resolution_kind": "exact",
        }

    class_ranges: list[tuple[str, int, int]] = []
    for match in re.finditer(
        r"(?m)^\s*(?P<mods>(?:public|protected|private|abstract|final|static|\s)*)"
        r"(?P<kind>class|interface|enum|record)\s+(?P<name>[A-Za-z_]\w*)\b[^{]*\{",
        text,
    ):
        class_name = match.group("name")
        open_brace = text.find("{", match.start())
        close_brace = _matching_brace_end(text, open_brace) if open_brace >= 0 else match.end()
        class_ranges.append((class_name, open_brace, close_brace))
        add_record(
            name=class_name,
            symbol_kind=match.group("kind"),
            start_offset=match.start(),
            end_offset=close_brace,
            visibility=java_visibility(match.group("mods") or ""),
            confidence=0.82,
        )
    for class_name, open_brace, close_brace in class_ranges:
        body = text[open_brace + 1 : close_brace] if open_brace >= 0 else ""
        for method in re.finditer(
            r"(?m)^\s*(?P<mods>(?:public|protected|private|static|final|abstract|synchronized|native|\s)*)"
            r"(?:[A-Za-z_]\w*(?:<[^>{}]*>)?(?:\[\])?\s+)+(?P<name>[A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:throws\s+[^{]+)?\{",
            body,
        ):
            method_name = method.group("name")
            if method_name in {"if", "for", "while", "switch", "catch"}:
                continue
            add_record(
                name=method_name,
                symbol_kind="method",
                start_offset=open_brace + 1 + method.start(),
                visibility=java_visibility(method.group("mods") or ""),
                parent_symbol=class_name,
                confidence=0.76,
            )
        for member_line, offset in _member_lines_at_body_depth(body, base_offset=open_brace + 1):
            stripped = member_line.strip()
            if not stripped or stripped.startswith("@"):
                continue
            constructor = re.match(
                rf"(?P<mods>(?:public|protected|private|\s)*){re.escape(class_name)}\s*\([^;{{}}]*\)\s*(?:throws\s+[^\{{]+)?\{{",
                stripped,
            )
            if constructor:
                add_record(
                    name=class_name,
                    symbol_kind="method",
                    start_offset=offset + member_line.find(class_name),
                    visibility=java_visibility(constructor.group("mods") or ""),
                    parent_symbol=class_name,
                    confidence=0.72,
                )
                continue
            abstract_method = re.match(
                r"(?P<mods>(?:public|protected|private|static|final|abstract|default|\s)*)"
                r"(?:[A-Za-z_]\w*(?:<[^>{}]*>)?(?:\[\])?\s+)+(?P<name>[A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:throws\s+[^;]+)?;",
                stripped,
            )
            if abstract_method:
                add_record(
                    name=abstract_method.group("name"),
                    symbol_kind="method",
                    start_offset=offset + member_line.find(abstract_method.group("name")),
                    visibility=java_visibility(abstract_method.group("mods") or ""),
                    parent_symbol=class_name,
                    confidence=0.72,
                )
                continue
            field = re.match(
                r"(?P<mods>(?:public|protected|private|static|final|volatile|transient|\s)*)"
                r"(?:[A-Za-z_]\w*(?:<[^>{}]*>)?(?:\[\])?\s+)+(?P<name>[A-Za-z_]\w*)\s*(?:=[^;]*)?;",
                stripped,
            )
            if field and "(" not in stripped:
                add_record(
                    name=field.group("name"),
                    symbol_kind="field",
                    start_offset=offset + member_line.find(field.group("name")),
                    visibility=java_visibility(field.group("mods") or ""),
                    parent_symbol=class_name,
                    confidence=0.7,
                )

    return [records_by_key[key] for key in sorted(records_by_key)], "ok"


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

    def add_parser_status(source: str, status: str, confidence: float) -> None:
        file_node = file_node_for_path(target, normalized_rel)
        file_node.setdefault("facts", []).append(
            graph_fact("parser_status", status, source=source, confidence=confidence)
        )
        file_node.setdefault("facts", []).append(
            graph_fact("parser_confidence", confidence, value_type="number", source=source, confidence=confidence)
        )
        metadata = file_node.setdefault("metadata", {})
        if isinstance(metadata, dict):
            metadata["parser_status"] = status
            metadata["parser_confidence"] = float(confidence)
            metadata["parser_source"] = source
        add_node(file_node)

    def add_symbol_records(records: list[dict[str, Any]], *, language: str, source: str) -> None:
        for record in records:
            symbol_name = str(record.get("name") or "")
            symbol_kind = str(record.get("symbol_kind") or "symbol")
            confidence = float(record.get("confidence") if record.get("confidence") is not None else 0.85)
            symbol = symbol_node(
                rel=normalized_rel,
                language=language,
                symbol_kind=symbol_kind,
                name=symbol_name,
                qualified_name=str(record.get("qualified_name") or symbol_name),
                source=source,
                confidence=confidence,
                exported=bool(record.get("exported")),
                lineno=int(record.get("lineno") or 0),
                parent_symbol=str(record.get("parent_symbol") or ""),
                package_name=str(record.get("package_name") or ""),
                module_name=str(record.get("module_name") or ""),
                visibility=str(record.get("visibility") or ""),
                range_start_line=int(record.get("range_start_line") or record.get("lineno") or 0),
                range_start_col=int(record.get("range_start_col") or 0),
                range_end_line=int(record.get("range_end_line") or record.get("lineno") or 0),
                range_end_col=int(record.get("range_end_col") or 0),
                extractor_confidence=float(record.get("extractor_confidence") if record.get("extractor_confidence") is not None else confidence),
                resolution_kind=str(record.get("resolution_kind") or "exact"),
            )
            symbol_id = add_node(symbol)
            add_edge(
                ownership_edge(
                    source_id,
                    symbol_id,
                    rel=normalized_rel,
                    symbol_name=symbol_name,
                    symbol_kind=symbol_kind,
                    source=source,
                    confidence=confidence,
                )
            )

    def add_unresolved_import_symbol(
        *,
        raw_import: str,
        language: str,
        source: str,
        lineno: int = 0,
        imported_symbol: str = "",
    ) -> None:
        raw_import = str(raw_import or "").strip()
        imported_symbol = str(imported_symbol or "").strip()
        if not raw_import and not imported_symbol:
            return
        symbol_name = imported_symbol or raw_import.rsplit("/", 1)[-1].rsplit(".", 1)[-1] or raw_import
        qualified_name = ".".join(part for part in (raw_import, imported_symbol) if part)
        package_name = raw_import.split("/", 1)[0].split(".", 1)[0] if raw_import else ""
        add_node(
            symbol_node(
                rel=normalized_rel,
                owner_file_path="",
                reference_file_path=normalized_rel,
                language=language,
                symbol_kind="import",
                name=symbol_name,
                qualified_name=qualified_name or symbol_name,
                source=source,
                confidence=0.2,
                exported=False,
                lineno=int(lineno or 0),
                package_name=package_name,
                module_name=raw_import,
                visibility="unknown",
                range_start_line=int(lineno or 0),
                range_end_line=int(lineno or 0),
                extractor_confidence=0.2,
                resolution_kind="unresolved",
            )
        )

    def add_import_edges(
        records: list[dict[str, Any]],
        *,
        language: str,
        source: str,
        resolve_import: Any,
        resolved_confidence: float,
        unresolved_confidence: float = 0.2,
    ) -> None:
        for record in records:
            raw_import = str(record.get("raw_import") or record.get("module") or "")
            module_name = str(record.get("module") or raw_import)
            if not raw_import and not module_name:
                continue
            module_id = add_node(module_node(module_name or raw_import, language=language, source=source))
            resolved_rel = str(resolve_import(raw_import, normalized_rel, file_node_by_rel) or "")
            resolved = bool(resolved_rel)
            confidence = resolved_confidence if resolved else unresolved_confidence
            imported_symbols = [str(item) for item in (record.get("imported_symbols") or []) if str(item).strip()]
            if not resolved:
                if not imported_symbols:
                    imported_symbols = [""]
                for imported_symbol in imported_symbols:
                    add_unresolved_import_symbol(
                        raw_import=raw_import,
                        imported_symbol=imported_symbol,
                        language=language,
                        source=source,
                        lineno=int(record.get("lineno") or 0),
                    )
            add_edge(
                graph_edge(
                    "references",
                    source_id,
                    module_id,
                    metadata={
                        "source_path": normalized_rel,
                        "module": module_name,
                        "raw_import": raw_import,
                        "imported_symbols": imported_symbols,
                        "resolved": resolved,
                        "confidence": confidence,
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
                            "imported_symbols": imported_symbols,
                            "resolved": True,
                            "confidence": resolved_confidence,
                            "source": source,
                        },
                        facts=dependency_facts(source, resolved_confidence, True, raw_import),
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
                            "imported_symbols": imported_symbols,
                            "resolved": True,
                            "confidence": resolved_confidence,
                            "source": source,
                        },
                        facts=dependency_facts(source, resolved_confidence, True, raw_import),
                    )
                )

    if suffix == ".py":
        source = "python_ast_import"
        symbol_records, parser_status = _python_symbol_records(target, normalized_rel)
        add_parser_status(source, parser_status, 1.0 if parser_status == "ok" else 0.35)
        add_symbol_records(symbol_records, language="Python", source=source)
        own_module = python_module_name_for_rel(normalized_rel)
        if own_module:
            own_module_id = add_node(module_node(own_module, language="Python", source=source))
            add_edge(
                graph_edge(
                    "defines_module",
                    source_id,
                    own_module_id,
                    metadata={"source_path": normalized_rel, "module": own_module, "source": source, "confidence": 1.0},
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
            if not resolved:
                add_unresolved_import_symbol(
                    raw_import=raw_import,
                    language="Python",
                    source=source,
                    lineno=int(record.get("lineno") or 0),
                )
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
                        "confidence": confidence,
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
                            "confidence": 0.95,
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
                            "confidence": 0.95,
                            "source": source,
                        },
                        facts=dependency_facts(source, 0.95, True, raw_import),
                    )
                )
    elif suffix in JS_TS_SOURCE_EXTENSIONS:
        source = "js_ts_import_regex"
        symbol_records, parser_status = _js_ts_symbol_records(target, normalized_rel)
        add_parser_status(source, parser_status, 0.8 if parser_status == "ok" else 0.25)
        add_symbol_records(
            symbol_records,
            language="TypeScript" if suffix in {".ts", ".tsx"} else "JavaScript",
            source=source,
        )
        for record in _js_ts_import_records(target, normalized_rel):
            raw_import = str(record.get("raw_import") or "")
            resolved_rel = _resolve_js_ts_relative_import(raw_import, normalized_rel, file_node_by_rel)
            resolved = bool(resolved_rel)
            language = "TypeScript" if suffix in {".ts", ".tsx"} else "JavaScript"
            module_id = add_node(module_node(raw_import, language=language, source=source))
            confidence = 0.9 if resolved else 0.2
            if not resolved:
                imported_symbols = [str(item) for item in (record.get("imported_symbols") or []) if str(item).strip()]
                if not imported_symbols:
                    imported_symbols = [""]
                for imported_symbol in imported_symbols:
                    add_unresolved_import_symbol(
                        raw_import=raw_import,
                        imported_symbol=imported_symbol,
                        language=language,
                        source=source,
                        lineno=int(record.get("lineno") or 0),
                    )
            add_edge(
                graph_edge(
                    "references",
                    source_id,
                    module_id,
                    metadata={
                        "source_path": normalized_rel,
                        "module": raw_import,
                        "raw_import": raw_import,
                        "imported_symbols": list(record.get("imported_symbols") or []),
                        "resolved": resolved,
                        "confidence": confidence,
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
                            "imported_symbols": list(record.get("imported_symbols") or []),
                            "resolved": True,
                            "confidence": 0.9,
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
                            "imported_symbols": list(record.get("imported_symbols") or []),
                            "resolved": True,
                            "confidence": 0.9,
                            "source": source,
                        },
                        facts=dependency_facts(source, 0.9, True, raw_import),
                    )
                )
    elif suffix == ".rs":
        source = "rust_regex_symbol"
        symbol_records, parser_status = _rust_symbol_records(target, normalized_rel)
        add_parser_status(source, parser_status, 0.78 if parser_status == "ok" else 0.25)
        add_symbol_records(symbol_records, language="Rust", source=source)
        own_module = _path_module_name_for_rel(normalized_rel, separator="::")
        if own_module:
            own_module_id = add_node(module_node(own_module, language="Rust", source=source))
            add_edge(
                graph_edge(
                    "defines_module",
                    source_id,
                    own_module_id,
                    metadata={"source_path": normalized_rel, "module": own_module, "source": source, "confidence": 0.78},
                    facts=dependency_facts(source, 0.78, True, own_module),
                )
            )
        if parser_status == "ok":
            add_import_edges(
                _rust_import_records(target, normalized_rel),
                language="Rust",
                source=source,
                resolve_import=_resolve_rust_import,
                resolved_confidence=0.78,
            )
    elif suffix == ".go":
        source = "go_regex_symbol"
        symbol_records, parser_status = _go_symbol_records(target, normalized_rel)
        add_parser_status(source, parser_status, 0.84 if parser_status == "ok" else 0.25)
        add_symbol_records(symbol_records, language="Go", source=source)
        package_decl = re.search(
            r"(?m)^\s*package\s+(?P<name>[A-Za-z_]\w*)\b",
            _strip_js_ts_comments(read_optional_text(target / normalized_rel, limit=300_000)),
        )
        own_module = package_decl.group("name") if package_decl else _path_module_name_for_rel(normalized_rel)
        if own_module:
            own_module_id = add_node(module_node(own_module, language="Go", source=source))
            add_edge(
                graph_edge(
                    "defines_module",
                    source_id,
                    own_module_id,
                    metadata={"source_path": normalized_rel, "module": own_module, "source": source, "confidence": 0.84},
                    facts=dependency_facts(source, 0.84, True, own_module),
                )
            )
        if parser_status == "ok":
            add_import_edges(
                _go_import_records(target, normalized_rel),
                language="Go",
                source=source,
                resolve_import=lambda raw, importer, files: _resolve_go_import(raw, importer, files, target),
                resolved_confidence=0.84,
            )
    elif suffix == ".java":
        source = "java_regex_symbol"
        symbol_records, parser_status = _java_symbol_records(target, normalized_rel)
        add_parser_status(source, parser_status, 0.78 if parser_status == "ok" else 0.25)
        add_symbol_records(symbol_records, language="Java", source=source)
        package_match = re.search(
            r"(?m)^\s*package\s+(?P<name>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*;",
            _strip_js_ts_comments(read_optional_text(target / normalized_rel, limit=300_000)),
        )
        own_module = package_match.group("name") if package_match else _path_module_name_for_rel(normalized_rel)
        if own_module:
            own_module_id = add_node(module_node(own_module, language="Java", source=source))
            add_edge(
                graph_edge(
                    "defines_module",
                    source_id,
                    own_module_id,
                    metadata={"source_path": normalized_rel, "module": own_module, "source": source, "confidence": 0.78},
                    facts=dependency_facts(source, 0.78, True, own_module),
                )
            )
        if parser_status == "ok":
            add_import_edges(
                _java_import_records(target, normalized_rel),
                language="Java",
                source=source,
                resolve_import=_resolve_java_import,
                resolved_confidence=0.78,
            )
    return {"nodes": list(nodes.values()), "edges": list(edges.values())}


def _semantic_reference_facts(
    *,
    source: str,
    confidence: float,
    reference: str,
    signal_kind: str,
    resolution_kind: str,
) -> list[dict[str, Any]]:
    return [
        graph_fact("source", source, source=source, confidence=confidence),
        graph_fact("confidence", confidence, value_type="number", source=source, confidence=confidence),
        graph_fact("resolved", "true" if resolution_kind == "exact" else "false", value_type="boolean", source=source, confidence=confidence),
        graph_fact("raw_import", reference, source=source, confidence=confidence),
        graph_fact("signal_kind", signal_kind, source=source, confidence=confidence),
        graph_fact("resolution_kind", resolution_kind, source=source, confidence=confidence),
    ]


def _semantic_reference_detail(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "signal_kind": str(metadata.get("signal_kind") or ""),
        "resolution_kind": str(metadata.get("resolution_kind") or ""),
        "reference": str(metadata.get("reference") or metadata.get("matched_reference") or ""),
        "symbol_name": str(metadata.get("symbol_name") or ""),
        "qualified_name": str(metadata.get("qualified_name") or ""),
        "symbol_node_id": str(metadata.get("symbol_node_id") or ""),
        "interface_kind": str(metadata.get("interface_kind") or ""),
        "matched_terms": list(metadata.get("matched_terms") or []) if isinstance(metadata.get("matched_terms"), list) else [],
        "confidence": float(metadata.get("confidence") or 0.0),
        "reason": str(metadata.get("reason") or ""),
    }


def _merge_semantic_reference_edge(edges: dict[str, dict[str, Any]], edge: dict[str, Any]) -> None:
    edge_id = str(edge.get("edge_id") or "")
    if not edge_id or edge_id not in edges:
        metadata = edge.get("metadata") if isinstance(edge.get("metadata"), Mapping) else {}
        edge["metadata"] = {
            **dict(metadata),
            "dependency_mode": str(metadata.get("dependency_mode") or "advisory"),
            "write_candidate": False,
            "reference_details": [_semantic_reference_detail(metadata)],
        }
        edges[edge_id] = edge
        return
    current = edges[edge_id]
    current_metadata = current.get("metadata") if isinstance(current.get("metadata"), dict) else {}
    incoming_metadata = edge.get("metadata") if isinstance(edge.get("metadata"), Mapping) else {}
    current_confidence = float(current_metadata.get("confidence") or 0.0)
    incoming_confidence = float(incoming_metadata.get("confidence") or 0.0)
    details = [
        item
        for item in (current_metadata.get("reference_details") if isinstance(current_metadata.get("reference_details"), list) else [])
        if isinstance(item, dict)
    ]
    incoming_detail = _semantic_reference_detail(incoming_metadata)
    detail_keys = {stable_json(item) for item in details}
    if stable_json(incoming_detail) not in detail_keys:
        details.append(incoming_detail)
    signals = {
        str(current_metadata.get("signal_kind") or ""),
        *(str(item.get("signal_kind") or "") for item in details),
    }
    signals.discard("")
    if incoming_confidence > current_confidence:
        for key in (
            "signal_kind",
            "resolution_kind",
            "reference",
            "matched_reference",
            "symbol_name",
            "qualified_name",
            "symbol_node_id",
            "interface_kind",
            "matched_terms",
            "reason",
            "source",
        ):
            if key in incoming_metadata:
                current_metadata[key] = incoming_metadata.get(key)
        current_metadata["confidence"] = incoming_confidence
    else:
        current_metadata["confidence"] = current_confidence
    current_metadata["signals"] = sorted(signals)
    current_metadata["dependency_mode"] = "advisory"
    current_metadata["write_candidate"] = False
    current_metadata["reference_details"] = sorted(details, key=stable_json)[:12]
    current["metadata"] = current_metadata
    current["facts"] = _semantic_reference_facts(
        source=str(current_metadata.get("source") or SEMANTIC_REFERENCE_SOURCE),
        confidence=float(current_metadata.get("confidence") or 0.0),
        reference=str(current_metadata.get("reference") or current_metadata.get("matched_reference") or ""),
        signal_kind=str(current_metadata.get("signal_kind") or "semantic_reference"),
        resolution_kind=str(current_metadata.get("resolution_kind") or "inferred"),
    )


def _add_semantic_file_reference_edge(
    edges: dict[str, dict[str, Any]],
    *,
    from_node_id: str,
    to_node_id: str,
    source_path: str,
    target_path: str,
    signal_kind: str,
    resolution_kind: str,
    confidence: float,
    reason: str,
    reference: str,
    source: str = SEMANTIC_REFERENCE_SOURCE,
    extra_metadata: Mapping[str, Any] | None = None,
) -> None:
    metadata = {
        "source_path": source_path,
        "target_path": target_path,
        "source": source,
        "signal_kind": signal_kind,
        "resolution_kind": resolution_kind,
        "confidence": float(confidence),
        "reason": reason,
        "reference": reference,
        "matched_reference": reference,
        "resolved": resolution_kind == "exact",
        "dependency_mode": "advisory",
        "write_candidate": False,
    }
    if isinstance(extra_metadata, Mapping):
        metadata.update({str(key): value for key, value in extra_metadata.items()})
    _merge_semantic_reference_edge(
        edges,
        graph_edge(
            "references",
            from_node_id,
            to_node_id,
            metadata=metadata,
            facts=_semantic_reference_facts(
                source=source,
                confidence=float(confidence),
                reference=reference,
                signal_kind=signal_kind,
                resolution_kind=resolution_kind,
            ),
        ),
    )


def _semantic_identifier_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"(?<![A-Za-z0-9_$])([A-Za-z_$][\w$]{2,})(?![A-Za-z0-9_$])", text)
        if token.lower() not in SEMANTIC_SYMBOL_STOP_WORDS
    }


def _semantic_alias_regex(alias: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![A-Za-z0-9_$]){re.escape(alias)}(?![A-Za-z0-9_$])")


def _semantic_symbol_aliases(symbol: Mapping[str, Any]) -> set[str]:
    metadata = symbol.get("metadata") if isinstance(symbol.get("metadata"), Mapping) else {}
    aliases: set[str] = set()
    name = str(symbol.get("name") or "").strip()
    qualified = str(metadata.get("qualified_name") or "").strip()
    parent = str(metadata.get("parent_symbol") or "").strip()
    for value in (name, qualified):
        if value:
            aliases.add(value)
    if parent and name:
        aliases.add(f"{parent}.{name}")
        aliases.add(f"{parent}::{name}")
    for separator in (".", "::"):
        if separator in qualified:
            parts = [part for part in qualified.split(separator) if part]
            if len(parts) >= 2:
                aliases.add(separator.join(parts[-2:]))
    clean_aliases: set[str] = set()
    for alias in aliases:
        if not alias:
            continue
        simple = re.match(r"^[A-Za-z_$][\w$]*$", alias)
        if simple and (len(alias) < 3 or alias.lower() in SEMANTIC_SYMBOL_STOP_WORDS):
            continue
        clean_aliases.add(alias)
    return clean_aliases


def _semantic_symbol_reference_edges(
    target: Path,
    *,
    nodes: Mapping[str, dict[str, Any]],
    file_node_by_rel: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    source_files = {
        rel: node_id
        for rel, node_id in file_node_by_rel.items()
        if Path(rel).suffix.lower() in SEMANTIC_SOURCE_EXTENSIONS
    }
    if not source_files:
        return {}
    symbols = [
        node
        for node in nodes.values()
        if str(node.get("kind") or "") == "symbol"
        and isinstance(node.get("metadata"), Mapping)
        and str((node.get("metadata") or {}).get("owner_file_path") or "")
        and str((node.get("metadata") or {}).get("resolution_kind") or "exact") == "exact"
    ]
    alias_index: dict[str, list[dict[str, Any]]] = {}
    owned_aliases_by_rel: dict[str, set[str]] = {}
    for symbol in symbols:
        metadata = symbol.get("metadata") if isinstance(symbol.get("metadata"), Mapping) else {}
        owner_rel = _normalized_rel_path(str(metadata.get("owner_file_path") or symbol.get("path") or ""))
        if not owner_rel or owner_rel not in file_node_by_rel:
            continue
        aliases = _semantic_symbol_aliases(symbol)
        owned_aliases_by_rel.setdefault(owner_rel, set()).update(aliases)
        for alias in aliases:
            alias_index.setdefault(alias, []).append(symbol)
    if not alias_index:
        return {}

    simple_aliases = {alias for alias in alias_index if re.match(r"^[A-Za-z_$][\w$]*$", alias)}
    compound_aliases = sorted(alias for alias in alias_index if alias not in simple_aliases)
    edges: dict[str, dict[str, Any]] = {}
    for source_rel, source_id in sorted(source_files.items()):
        text = read_optional_text(target / source_rel, limit=300_000)
        if not text:
            continue
        candidate_aliases = sorted(_semantic_identifier_tokens(text).intersection(simple_aliases))
        for alias in compound_aliases:
            if alias in text:
                candidate_aliases.append(alias)
        seen_aliases: set[str] = set()
        for alias in candidate_aliases:
            if alias in seen_aliases or alias in owned_aliases_by_rel.get(source_rel, set()):
                continue
            seen_aliases.add(alias)
            if not _semantic_alias_regex(alias).search(text):
                continue
            candidates = alias_index.get(alias) or []
            owner_rels = {
                _normalized_rel_path(str((candidate.get("metadata") or {}).get("owner_file_path") or candidate.get("path") or ""))
                for candidate in candidates
                if isinstance(candidate.get("metadata"), Mapping)
            }
            owner_rels.discard("")
            owner_rels.discard(source_rel)
            if not owner_rels:
                continue
            resolution_kind = "exact" if len(owner_rels) == 1 else "ambiguous"
            signal_kind = "exact_symbol_reference" if resolution_kind == "exact" else "ambiguous_symbol_reference"
            for candidate in candidates:
                metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), Mapping) else {}
                owner_rel = _normalized_rel_path(str(metadata.get("owner_file_path") or candidate.get("path") or ""))
                if owner_rel == source_rel or owner_rel not in owner_rels:
                    continue
                target_id = file_node_by_rel.get(owner_rel)
                if not target_id:
                    continue
                qualified_name = str(metadata.get("qualified_name") or candidate.get("name") or alias)
                confidence = 0.82 if resolution_kind == "exact" else 0.44
                confidence = min(confidence, max(0.35, float(metadata.get("confidence") or confidence)))
                reason = (
                    f"exact symbol reference `{alias}` resolves to `{qualified_name}`"
                    if resolution_kind == "exact"
                    else f"ambiguous symbol reference `{alias}` has {len(owner_rels)} possible owners"
                )
                _add_semantic_file_reference_edge(
                    edges,
                    from_node_id=source_id,
                    to_node_id=target_id,
                    source_path=source_rel,
                    target_path=owner_rel,
                    signal_kind=signal_kind,
                    resolution_kind=resolution_kind,
                    confidence=confidence,
                    reason=reason,
                    reference=alias,
                    extra_metadata={
                        "symbol_name": str(candidate.get("name") or alias),
                        "qualified_name": qualified_name,
                        "symbol_node_id": str(candidate.get("node_id") or ""),
                        "symbol_kind": str(metadata.get("symbol_kind") or ""),
                        "language": str(metadata.get("language") or ""),
                    },
                )
                if resolution_kind == "exact":
                    break
    return edges


def _semantic_split_words(value: str) -> list[str]:
    raw = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(value or ""))
    raw = re.sub(r"[^A-Za-z0-9]+", " ", raw)
    return [part.lower() for part in raw.split() if part and part.lower() not in SEMANTIC_SYMBOL_STOP_WORDS]


def _semantic_term_variants(value: str) -> set[str]:
    words = _semantic_split_words(value)
    terms: set[str] = set()
    if words:
        terms.add("_".join(words))
        terms.update(words)
    for word in list(terms):
        if word.endswith("ies") and len(word) > 4:
            terms.add(f"{word[:-3]}y")
        elif word.endswith("s") and len(word) > 3:
            terms.add(word[:-1])
    return {term for term in terms if len(term) >= 3 and term not in SEMANTIC_SYMBOL_STOP_WORDS}


def _semantic_route_key(value: str) -> str:
    route = str(value or "").strip().strip("'\"`")
    if not route.startswith("/"):
        return ""
    route = re.sub(r":([A-Za-z_]\w*)", "{param}", route)
    route = re.sub(r"\{[^}/]+\}", "{param}", route)
    route = re.sub(r"/+", "/", route).rstrip("/") or "/"
    return route.lower()


def _semantic_route_terms(text: str) -> set[str]:
    terms: set[str] = set()
    for match in re.finditer(r"['\"`](/[^'\"`\s,;)]+)['\"`]", text):
        route = _semantic_route_key(match.group(1))
        if route:
            terms.add(f"route:{route}")
    return terms


def _semantic_openapi_terms(text: str) -> tuple[set[str], set[str], list[str]]:
    if not re.search(r"(?im)^\s*(openapi|swagger)\s*[:=]", text) and "components:" not in text and '"openapi"' not in text:
        return set(), set(), []
    route_terms = {
        f"route:{_semantic_route_key(match.group(1))}"
        for match in re.finditer(r"(?m)['\"]?(/[^:'\"\s][^:'\"]*)['\"]?\s*:", text)
        if _semantic_route_key(match.group(1))
    }
    name_terms: set[str] = set()
    details: list[str] = []
    for match in re.finditer(r"(?m)^\s{2,}([A-Z][A-Za-z0-9_]+)\s*:\s*(?:$|[#'{\"])", text):
        name = match.group(1)
        name_terms.update(_semantic_term_variants(name))
        details.append(name)
    for match in re.finditer(r'"([A-Z][A-Za-z0-9_]+)"\s*:\s*\{', text):
        name = match.group(1)
        name_terms.update(_semantic_term_variants(name))
        details.append(name)
    return route_terms, name_terms, sorted(set(details))


def _semantic_graphql_terms(text: str) -> tuple[set[str], list[str]]:
    name_terms: set[str] = set()
    details: list[str] = []
    for match in re.finditer(r"\b(?:type|interface|input|enum|scalar|union)\s+([A-Za-z_]\w*)", text):
        name = match.group(1)
        name_terms.update(_semantic_term_variants(name))
        details.append(name)
    return name_terms, sorted(set(details))


def _semantic_proto_terms(text: str) -> tuple[set[str], list[str]]:
    name_terms: set[str] = set()
    details: list[str] = []
    for match in re.finditer(r"\b(?:message|service|enum)\s+([A-Za-z_]\w*)", text):
        name = match.group(1)
        name_terms.update(_semantic_term_variants(name))
        details.append(name)
    for match in re.finditer(r"\brpc\s+([A-Za-z_]\w*)\s*\(", text):
        name = match.group(1)
        name_terms.update(_semantic_term_variants(name))
        details.append(name)
    return name_terms, sorted(set(details))


def _semantic_sql_terms(text: str) -> tuple[set[str], list[str]]:
    name_terms: set[str] = set()
    details: list[str] = []
    for match in re.finditer(r"(?i)\bCREATE\s+(?:TABLE|VIEW)\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][\w.]*)(?:\s|\()", text):
        name = match.group(1).rsplit(".", 1)[-1]
        name_terms.update(_semantic_term_variants(name))
        details.append(name)
    return name_terms, sorted(set(details))


def _semantic_interface_terms_for_file(target: Path, rel: str) -> dict[str, Any]:
    suffix = Path(rel).suffix.lower()
    if suffix not in INTERFACE_FILE_EXTENSIONS:
        return {}
    text = read_optional_text(target / rel, limit=300_000)
    if not text:
        return {}
    route_terms: set[str] = set()
    name_terms: set[str] = set()
    kinds: set[str] = set()
    details: list[str] = []
    if suffix in {".yaml", ".yml", ".json"}:
        openapi_routes, openapi_names, openapi_details = _semantic_openapi_terms(text)
        if openapi_routes or openapi_names:
            kinds.add("openapi")
            route_terms.update(openapi_routes)
            name_terms.update(openapi_names)
            details.extend(openapi_details)
    elif suffix in {".graphql", ".gql"}:
        graphql_names, graphql_details = _semantic_graphql_terms(text)
        if graphql_names:
            kinds.add("graphql")
            name_terms.update(graphql_names)
            details.extend(graphql_details)
    elif suffix == ".proto":
        proto_names, proto_details = _semantic_proto_terms(text)
        if proto_names:
            kinds.add("protobuf")
            name_terms.update(proto_names)
            details.extend(proto_details)
    elif suffix == ".sql":
        sql_names, sql_details = _semantic_sql_terms(text)
        if sql_names:
            kinds.add("sql_schema")
            name_terms.update(sql_names)
            details.extend(sql_details)
    if not kinds:
        return {}
    return {
        "route_terms": route_terms,
        "name_terms": name_terms,
        "interface_kinds": kinds,
        "details": sorted(set(details)),
    }


def _semantic_generated_symbol_terms(symbols: list[dict[str, Any]]) -> set[str]:
    terms: set[str] = set()
    for symbol in symbols:
        name = str(symbol.get("name") or "")
        words = _semantic_split_words(name)
        if not words:
            continue
        if words[-1] in GENERATED_CLIENT_SUFFIX_WORDS:
            terms.update(_semantic_term_variants(" ".join(words[:-1] or words)))
            terms.update(_semantic_term_variants(" ".join(words)))
        elif len(words) >= 2 and words[-2] in GENERATED_CLIENT_SUFFIX_WORDS:
            terms.update(_semantic_term_variants(" ".join(words[:-2] + words[-1:])))
    return terms


def _semantic_code_interface_terms_for_file(
    target: Path,
    rel: str,
    *,
    symbols_by_file: Mapping[str, list[dict[str, Any]]],
) -> dict[str, set[str]]:
    suffix = Path(rel).suffix.lower()
    if suffix not in SEMANTIC_SOURCE_EXTENSIONS:
        return {"route_terms": set(), "generated_terms": set()}
    text = read_optional_text(target / rel, limit=300_000)
    route_terms = _semantic_route_terms(text)
    generated_terms = _semantic_generated_symbol_terms(list(symbols_by_file.get(rel) or []))
    file_words = _semantic_split_words(Path(rel).stem)
    if file_words and any(word in GENERATED_CLIENT_SUFFIX_WORDS for word in file_words):
        generated_terms.update(_semantic_term_variants(" ".join(file_words)))
    return {"route_terms": route_terms, "generated_terms": generated_terms}


def _semantic_interface_bridge_edges(
    target: Path,
    *,
    nodes: Mapping[str, dict[str, Any]],
    file_node_by_rel: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    symbols_by_file: dict[str, list[dict[str, Any]]] = {}
    for node in nodes.values():
        if str(node.get("kind") or "") != "symbol":
            continue
        metadata = node.get("metadata") if isinstance(node.get("metadata"), Mapping) else {}
        owner_rel = _normalized_rel_path(str(metadata.get("owner_file_path") or node.get("path") or ""))
        if owner_rel:
            symbols_by_file.setdefault(owner_rel, []).append(node)

    interface_terms_by_rel = {
        rel: terms
        for rel in file_node_by_rel
        for terms in [_semantic_interface_terms_for_file(target, rel)]
        if terms
    }
    if not interface_terms_by_rel:
        return {}
    code_terms_by_rel = {
        rel: _semantic_code_interface_terms_for_file(target, rel, symbols_by_file=symbols_by_file)
        for rel in file_node_by_rel
        if Path(rel).suffix.lower() in SEMANTIC_SOURCE_EXTENSIONS
    }
    edges: dict[str, dict[str, Any]] = {}
    for interface_rel, interface_terms in sorted(interface_terms_by_rel.items()):
        interface_id = file_node_by_rel.get(interface_rel)
        if not interface_id:
            continue
        interface_route_terms = set(interface_terms.get("route_terms") or set())
        interface_name_terms = set(interface_terms.get("name_terms") or set())
        interface_kinds = sorted(str(item) for item in (interface_terms.get("interface_kinds") or set()))
        interface_kind = ",".join(interface_kinds)
        for code_rel, code_terms in sorted(code_terms_by_rel.items()):
            if code_rel == interface_rel:
                continue
            code_id = file_node_by_rel.get(code_rel)
            if not code_id:
                continue
            route_matches = sorted(interface_route_terms.intersection(code_terms.get("route_terms") or set()))
            generated_matches = sorted(interface_name_terms.intersection(code_terms.get("generated_terms") or set()))
            matched_terms = route_matches or generated_matches
            if not matched_terms:
                continue
            confidence = 0.68 if route_matches else 0.62
            if "sql_schema" in interface_kinds and not route_matches:
                confidence = 0.58
            reason = (
                f"cross-language interface route match between `{code_rel}` and `{interface_rel}`"
                if route_matches
                else f"cross-language generated-client/schema match between `{code_rel}` and `{interface_rel}`"
            )
            _add_semantic_file_reference_edge(
                edges,
                from_node_id=code_id,
                to_node_id=interface_id,
                source_path=code_rel,
                target_path=interface_rel,
                signal_kind="interface_bridge",
                resolution_kind="inferred",
                confidence=confidence,
                reason=reason,
                reference=", ".join(matched_terms[:4]),
                source=CROSS_LANGUAGE_INTERFACE_SOURCE,
                extra_metadata={
                    "interface_kind": interface_kind,
                    "matched_terms": matched_terms[:8],
                    "interface_details": list(interface_terms.get("details") or [])[:8],
                },
            )
    return edges


def semantic_resolution_edges(
    target: Path,
    *,
    nodes: Mapping[str, dict[str, Any]],
    file_node_by_rel: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Build scheduler-grade semantic file reference edges from indexed symbols."""

    edges: dict[str, dict[str, Any]] = {}
    for edge in _semantic_symbol_reference_edges(target, nodes=nodes, file_node_by_rel=file_node_by_rel).values():
        _merge_semantic_reference_edge(edges, edge)
    for edge in _semantic_interface_bridge_edges(target, nodes=nodes, file_node_by_rel=file_node_by_rel).values():
        _merge_semantic_reference_edge(edges, edge)
    return list(edges.values())


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

    for edge in semantic_resolution_edges(target, nodes=nodes, file_node_by_rel=file_node_by_rel):
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
        "symbol_extractor_version": SYMBOL_EXTRACTOR_VERSION,
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
            "symbol_extractor_version": SYMBOL_EXTRACTOR_VERSION,
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
