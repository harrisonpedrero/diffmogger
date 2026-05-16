"""Optional code-intelligence provider interfaces for scheduler verification.

The runtime treats language servers as opportunistic evidence providers. A
target repo can run perfectly well with no LSP tools installed; extractor facts
remain the fallback signal.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol


CODE_INTELLIGENCE_SCHEMA_VERSION = 1
DEFAULT_QUERY_TIMEOUT_MS = 750

LANGUAGE_SERVER_CANDIDATES: dict[str, list[dict[str, Any]]] = {
    "Python": [
        {"server_id": "pyright", "command": "pyright-langserver", "version_args": ["--version"]},
        {"server_id": "pylsp", "command": "pylsp", "version_args": ["--version"]},
    ],
    "JavaScript": [
        {"server_id": "typescript-language-server", "command": "typescript-language-server", "version_args": ["--version"]},
        {"server_id": "tsserver", "command": "tsserver", "version_args": ["--version"]},
    ],
    "TypeScript": [
        {"server_id": "typescript-language-server", "command": "typescript-language-server", "version_args": ["--version"]},
        {"server_id": "tsserver", "command": "tsserver", "version_args": ["--version"]},
    ],
    "Rust": [
        {"server_id": "rust-analyzer", "command": "rust-analyzer", "version_args": ["--version"]},
    ],
    "Go": [
        {"server_id": "gopls", "command": "gopls", "version_args": ["version"]},
    ],
    "Java": [
        {"server_id": "jdtls", "command": "jdtls", "version_args": ["--version"]},
    ],
}


@dataclass(frozen=True)
class CodePosition:
    file_path: str
    line: int
    character: int


@dataclass(frozen=True)
class CodeRange:
    file_path: str
    start_line: int
    start_character: int
    end_line: int
    end_character: int


@dataclass
class CodeIntelligenceResult:
    query_kind: str
    status: str = "ok"
    items: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""
    elapsed_ms: int = 0
    provider: dict[str, Any] = field(default_factory=dict)


class CodeIntelligenceProvider(Protocol):
    def provider_info(self, language: str = "") -> dict[str, Any]:
        ...

    def document_symbols(self, file: str) -> CodeIntelligenceResult:
        ...

    def definitions(self, file: str, position: CodePosition | None = None, symbol: str = "") -> CodeIntelligenceResult:
        ...

    def references(self, file: str, position: CodePosition | None = None, symbol: str = "") -> CodeIntelligenceResult:
        ...

    def workspace_symbols(self, query: str) -> CodeIntelligenceResult:
        ...

    def diagnostics(self, files: list[str] | None = None) -> CodeIntelligenceResult:
        ...

    def hover_type_info(self, file: str, position: CodePosition | None = None, symbol: str = "") -> CodeIntelligenceResult:
        ...


def _version_for_command(command: str, args: list[str], *, cwd: Path, timeout: float = 1.0) -> str:
    try:
        result = subprocess.run(
            [command, *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    output = (result.stdout or result.stderr or "").strip().splitlines()
    return output[0][:160] if output else ""


def repo_languages_from_paths(target: Path) -> set[str]:
    from diffmogger.runtime import codebase_graph

    languages: set[str] = set()
    for path in codebase_graph.scan_repo_files(target):
        language = codebase_graph.LANGUAGE_BY_EXTENSION.get(path.suffix.lower())
        if language in LANGUAGE_SERVER_CANDIDATES:
            languages.add(language)
    if (target / "pyproject.toml").exists() or (target / "setup.py").exists():
        languages.add("Python")
    if (target / "package.json").exists() or (target / "tsconfig.json").exists():
        languages.update({"JavaScript", "TypeScript"})
    if (target / "Cargo.toml").exists():
        languages.add("Rust")
    if (target / "go.mod").exists():
        languages.add("Go")
    return languages


def detect_code_intelligence_providers(target: Path) -> dict[str, Any]:
    target = target.expanduser().resolve()
    languages = sorted(repo_languages_from_paths(target))
    providers: list[dict[str, Any]] = []
    selected_by_language: dict[str, dict[str, Any]] = {}
    for language in languages:
        candidates = LANGUAGE_SERVER_CANDIDATES.get(language, [])
        selected: dict[str, Any] = {}
        for candidate in candidates:
            command = str(candidate.get("command") or "")
            executable = shutil.which(command)
            available = bool(executable)
            item = {
                "language": language,
                "server_id": str(candidate.get("server_id") or command),
                "command": command,
                "available": available,
                "path": executable or "",
                "version": _version_for_command(command, list(candidate.get("version_args") or []), cwd=target) if available else "",
                "capabilities": [
                    "document_symbols",
                    "definitions",
                    "references",
                    "workspace_symbols",
                    "diagnostics",
                    "hover_type_info",
                ],
                "status": "available" if available else "missing",
                "source": "language_server_detection",
            }
            providers.append(item)
            if available and not selected:
                selected = item
        if selected:
            selected_by_language[language] = selected
    available_count = sum(1 for item in providers if item.get("available"))
    return {
        "schema_version": CODE_INTELLIGENCE_SCHEMA_VERSION,
        "generated_at": "",
        "languages": languages,
        "providers": providers,
        "selected_by_language": selected_by_language,
        "available_count": available_count,
        "missing_count": max(0, len(providers) - available_count),
        "policy": {
            "required": False,
            "fallback": "extractor_only",
            "scheduler_grade_when_confirmed": True,
        },
    }


class UnavailableCodeIntelligenceProvider:
    def __init__(self, *, language: str = "", reason: str = "missing_language_server") -> None:
        self.language = language
        self.reason = reason

    def provider_info(self, language: str = "") -> dict[str, Any]:
        return {
            "language": language or self.language,
            "server_id": "none",
            "server_version": "",
            "available": False,
            "status": "unavailable",
            "source": "code_intelligence_provider",
            "reason": self.reason,
        }

    def _result(self, query_kind: str, language: str = "") -> CodeIntelligenceResult:
        return CodeIntelligenceResult(
            query_kind=query_kind,
            status="unavailable",
            error=self.reason,
            provider=self.provider_info(language),
        )

    def document_symbols(self, file: str) -> CodeIntelligenceResult:
        return self._result("document_symbols")

    def definitions(self, file: str, position: CodePosition | None = None, symbol: str = "") -> CodeIntelligenceResult:
        return self._result("definitions")

    def references(self, file: str, position: CodePosition | None = None, symbol: str = "") -> CodeIntelligenceResult:
        return self._result("references")

    def workspace_symbols(self, query: str) -> CodeIntelligenceResult:
        return self._result("workspace_symbols")

    def diagnostics(self, files: list[str] | None = None) -> CodeIntelligenceResult:
        return self._result("diagnostics")

    def hover_type_info(self, file: str, position: CodePosition | None = None, symbol: str = "") -> CodeIntelligenceResult:
        return self._result("hover_type_info")


class StaticCodeIntelligenceProvider:
    """Deterministic provider for tests and local fixtures."""

    def __init__(
        self,
        *,
        language: str = "Python",
        server_id: str = "static-lsp",
        server_version: str = "test",
        workspace_symbol_results: Mapping[str, list[Mapping[str, Any]]] | None = None,
        diagnostics_by_file: Mapping[str, list[Mapping[str, Any]]] | None = None,
        timeout_queries: set[str] | None = None,
    ) -> None:
        self.language = language
        self.server_id = server_id
        self.server_version = server_version
        self.workspace_symbol_results = {
            str(key): [dict(item) for item in value]
            for key, value in dict(workspace_symbol_results or {}).items()
        }
        self.diagnostics_by_file = {
            str(key): [dict(item) for item in value]
            for key, value in dict(diagnostics_by_file or {}).items()
        }
        self.timeout_queries = set(timeout_queries or set())

    def provider_info(self, language: str = "") -> dict[str, Any]:
        return {
            "language": language or self.language,
            "server_id": self.server_id,
            "server_version": self.server_version,
            "available": True,
            "status": "available",
            "source": "static_code_intelligence_provider",
        }

    def _timed_result(self, query_kind: str, *, query: str = "", items: list[dict[str, Any]] | None = None) -> CodeIntelligenceResult:
        started = time.monotonic()
        if query in self.timeout_queries:
            return CodeIntelligenceResult(
                query_kind=query_kind,
                status="timeout",
                error="query timed out",
                elapsed_ms=max(1, int((time.monotonic() - started) * 1000)),
                provider=self.provider_info(),
            )
        return CodeIntelligenceResult(
            query_kind=query_kind,
            status="ok",
            items=list(items or []),
            elapsed_ms=max(1, int((time.monotonic() - started) * 1000)),
            provider=self.provider_info(),
        )

    def document_symbols(self, file: str) -> CodeIntelligenceResult:
        items = [
            item
            for values in self.workspace_symbol_results.values()
            for item in values
            if str(item.get("file_path") or item.get("path") or "") == file
        ]
        return self._timed_result("document_symbols", query=file, items=items)

    def definitions(self, file: str, position: CodePosition | None = None, symbol: str = "") -> CodeIntelligenceResult:
        return self.workspace_symbols(symbol)

    def references(self, file: str, position: CodePosition | None = None, symbol: str = "") -> CodeIntelligenceResult:
        return self.workspace_symbols(symbol)

    def workspace_symbols(self, query: str) -> CodeIntelligenceResult:
        return self._timed_result("workspace_symbols", query=query, items=self.workspace_symbol_results.get(str(query), []))

    def diagnostics(self, files: list[str] | None = None) -> CodeIntelligenceResult:
        selected_files = files or sorted(self.diagnostics_by_file)
        diagnostics = [
            {**dict(item), "file_path": file}
            for file in selected_files
            for item in self.diagnostics_by_file.get(file, [])
        ]
        result = self._timed_result("diagnostics", query="diagnostics", items=[])
        result.diagnostics = diagnostics
        return result

    def hover_type_info(self, file: str, position: CodePosition | None = None, symbol: str = "") -> CodeIntelligenceResult:
        return self.workspace_symbols(symbol)


class DetectedCodeIntelligenceProvider(UnavailableCodeIntelligenceProvider):
    """Availability wrapper for real language servers.

    Full JSON-RPC sessions are intentionally outside this lightweight runtime
    path. The wrapper records that a server is present and returns typed
    ``unsupported`` query results until a caller supplies a concrete provider.
    """

    def __init__(self, provider_info: Mapping[str, Any]) -> None:
        self.info = dict(provider_info)

    def provider_info(self, language: str = "") -> dict[str, Any]:
        return {
            "language": language or str(self.info.get("language") or ""),
            "server_id": str(self.info.get("server_id") or ""),
            "server_version": str(self.info.get("version") or ""),
            "command": str(self.info.get("command") or ""),
            "available": bool(self.info.get("available")),
            "status": "available" if self.info.get("available") else "unavailable",
            "source": "language_server_detection",
        }

    def _result(self, query_kind: str, language: str = "") -> CodeIntelligenceResult:
        return CodeIntelligenceResult(
            query_kind=query_kind,
            status="unsupported",
            error="language server detected but no JSON-RPC session provider is configured",
            provider=self.provider_info(language),
        )


def provider_from_manifest(manifest: Mapping[str, Any], *, language: str = "") -> CodeIntelligenceProvider:
    code_intelligence = manifest.get("code_intelligence") if isinstance(manifest.get("code_intelligence"), Mapping) else {}
    selected = code_intelligence.get("selected_by_language") if isinstance(code_intelligence.get("selected_by_language"), Mapping) else {}
    info = selected.get(language) if language and isinstance(selected.get(language), Mapping) else None
    if info:
        return DetectedCodeIntelligenceProvider(info)
    return UnavailableCodeIntelligenceProvider(language=language)
