"""Tree-sitter backed code facts with a parser-unavailable fallback."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Iterable

from diffmogger.contracts import CodeFact


LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
}


def _fact_id(path: Path, kind: str, name: str, line: int, target: str = "") -> str:
    raw = f"{path.as_posix()}:{kind}:{name}:{line}:{target}"
    return "fact:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _language_for(path: Path):
    suffix = path.suffix.lower()
    language_name = LANGUAGE_BY_SUFFIX.get(suffix)
    if not language_name:
        return "", None
    try:
        from tree_sitter import Language
        if language_name == "python":
            import tree_sitter_python

            return language_name, Language(tree_sitter_python.language())
        if language_name == "typescript":
            return language_name, None
        import tree_sitter_javascript

        return language_name, Language(tree_sitter_javascript.language())
    except Exception:
        return language_name, None


def _node_text(source: bytes, node) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _children(node, *types: str):
    return [child for child in node.children if child.type in types]


def _walk(node) -> Iterable:
    yield node
    for child in node.children:
        yield from _walk(child)


def _python_facts(path: Path, source: bytes, root) -> list[CodeFact]:
    facts: list[CodeFact] = []
    for node in _walk(root):
        if node.type in {"function_definition", "class_definition"}:
            name_node = node.child_by_field_name("name")
            if name_node is None:
                continue
            name = _node_text(source, name_node)
            kind = "class" if node.type == "class_definition" else "function"
            facts.append(
                CodeFact(
                    fact_id=_fact_id(path, "symbol", name, node.start_point[0] + 1),
                    file_path=path.as_posix(),
                    language="python",
                    kind="symbol",
                    name=name,
                    line=node.start_point[0] + 1,
                    column=node.start_point[1],
                    payload={"symbol_kind": kind},
                )
            )
        elif node.type in {"import_statement", "import_from_statement"}:
            text = _node_text(source, node).strip()
            target = text.replace("import", "", 1).replace("from", "", 1).strip().split()[0].strip(",")
            facts.append(
                CodeFact(
                    fact_id=_fact_id(path, "import", text, node.start_point[0] + 1, target),
                    file_path=path.as_posix(),
                    language="python",
                    kind="import",
                    name=text,
                    target=target,
                    line=node.start_point[0] + 1,
                    column=node.start_point[1],
                )
            )
    return facts


def _javascript_facts(path: Path, source: bytes, root) -> list[CodeFact]:
    facts: list[CodeFact] = []
    for node in _walk(root):
        if node.type in {"function_declaration", "class_declaration"}:
            name_node = node.child_by_field_name("name")
            if name_node is None:
                continue
            name = _node_text(source, name_node)
            kind = "class" if node.type == "class_declaration" else "function"
            facts.append(
                CodeFact(
                    fact_id=_fact_id(path, "symbol", name, node.start_point[0] + 1),
                    file_path=path.as_posix(),
                    language="javascript",
                    kind="symbol",
                    name=name,
                    line=node.start_point[0] + 1,
                    column=node.start_point[1],
                    payload={"symbol_kind": kind},
                )
            )
        elif node.type == "import_statement":
            text = _node_text(source, node).strip()
            match = re.search(r"from\s+['\"]([^'\"]+)['\"]|import\s+['\"]([^'\"]+)['\"]", text)
            target = (match.group(1) or match.group(2)) if match else ""
            facts.append(
                CodeFact(
                    fact_id=_fact_id(path, "import", text, node.start_point[0] + 1, target),
                    file_path=path.as_posix(),
                    language="javascript",
                    kind="import",
                    name=text,
                    target=target,
                    line=node.start_point[0] + 1,
                    column=node.start_point[1],
                )
            )
    return facts


def fallback_facts(path: Path, reason: str) -> list[CodeFact]:
    return [
        CodeFact(
            fact_id=_fact_id(path, "parser_unavailable", reason, 0),
            file_path=path.as_posix(),
            language=LANGUAGE_BY_SUFFIX.get(path.suffix.lower(), "unknown"),
            kind="parser_unavailable",
            name=reason,
            source="fallback",
            payload={"reason": reason},
        )
    ]


def facts_for_file(path: Path) -> list[CodeFact]:
    path = path.expanduser().resolve()
    language, tree_sitter_language = _language_for(path)
    if not language:
        return []
    if tree_sitter_language is None:
        return fallback_facts(path, "tree_sitter_parser_unavailable")
    try:
        from tree_sitter import Parser

        source = path.read_bytes()
        parser = Parser()
        parser.language = tree_sitter_language
        tree = parser.parse(source)
    except Exception:
        return fallback_facts(path, "tree_sitter_parse_failed")
    if language == "python":
        return _python_facts(path, source, tree.root_node)
    return _javascript_facts(path, source, tree.root_node)


def facts_for_tree(root: Path, *, limit: int = 5000) -> list[CodeFact]:
    facts: list[CodeFact] = []
    ignored = {".git", ".diffmogger", "node_modules", "__pycache__", ".venv", "dist", "build"}
    for path in sorted(root.rglob("*")):
        if len(facts) >= limit:
            break
        if not path.is_file() or any(part in ignored for part in path.parts):
            continue
        facts.extend(facts_for_file(path))
    return facts[:limit]
