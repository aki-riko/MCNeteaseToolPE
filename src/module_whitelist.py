# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
# 网易 Python 模块白名单加载与导入提取。
# Netease Python module whitelist loading and import extraction.

"""Document-backed import checks that remain valid for Python 2.7 source."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import io
from pathlib import Path
import re
import token
import tokenize
from typing import Iterable


WHITELIST_FILENAME = "netease_python_module_whitelist.txt"
MODULE_NAME_RE = re.compile(r"^\.*[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$")
FROM_IMPORT_RE = re.compile(r"(?m)^[ \t]*from[ \t]+([.\w]+)[ \t]+import\b")
PLAIN_IMPORT_RE = re.compile(r"(?m)^[ \t]*import[ \t]+([^#;\r\n]+)")


@dataclass(frozen=True)
class ImportReference:
    """One imported module and its source line."""

    module: str
    line: int


@lru_cache(maxsize=8)
def load_module_whitelist(path: str | None = None) -> frozenset[str]:
    """Load the bundled current Netease module whitelist."""

    source = Path(path) if path else Path(__file__).with_name(WHITELIST_FILENAME)
    entries = frozenset(
        line.strip()
        for line in source.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    if not entries:
        raise ValueError(f"网易模块白名单为空: {source}")
    return entries


def _logical_statements(source: str) -> list[list[tokenize.TokenInfo]]:
    statements: list[list[tokenize.TokenInfo]] = []
    current: list[tokenize.TokenInfo] = []
    ignored = {tokenize.ENCODING, tokenize.NL, tokenize.INDENT, tokenize.DEDENT, tokenize.COMMENT}
    try:
        parts = tokenize.generate_tokens(io.StringIO(source).readline)
        for part in parts:
            if part.type == tokenize.NEWLINE or (part.type == token.OP and part.string == ";"):
                if current:
                    statements.append(current)
                    current = []
                continue
            if part.type not in ignored and part.type != tokenize.ENDMARKER:
                current.append(part)
    except (IndentationError, tokenize.TokenError):
        pass
    if current:
        statements.append(current)
    return statements


def _from_import(statement: list[tokenize.TokenInfo]) -> tuple[ImportReference | None, int | None]:
    for index, part in enumerate(statement):
        if part.type != token.NAME or part.string != "from":
            continue
        for import_index in range(index + 1, len(statement)):
            candidate = statement[import_index]
            if candidate.type == token.NAME and candidate.string == "import":
                module = "".join(item.string for item in statement[index + 1:import_index])
                if MODULE_NAME_RE.fullmatch(module):
                    return ImportReference(module, part.start[0]), import_index
                return None, import_index
    return None, None


def _plain_imports(statement: list[tokenize.TokenInfo], handled: int | None) -> list[ImportReference]:
    output: list[ImportReference] = []
    for index, part in enumerate(statement):
        if index == handled or part.type != token.NAME or part.string != "import":
            continue
        current: list[str] = []
        skip_alias = False
        for item in statement[index + 1:]:
            if item.type == token.OP and item.string == ",":
                _append_module(output, current, part.start[0])
                current, skip_alias = [], False
            elif item.type == token.NAME and item.string == "as":
                skip_alias = True
            elif skip_alias and item.type == token.NAME:
                skip_alias = False
            elif not skip_alias and (item.type == token.NAME or item.string == "."):
                current.append(item.string)
        _append_module(output, current, part.start[0])
    return output


def _append_module(output: list[ImportReference], parts: list[str], line: int) -> None:
    module = "".join(parts)
    if MODULE_NAME_RE.fullmatch(module):
        output.append(ImportReference(module, line))


def _regex_imports(source: str) -> list[ImportReference]:
    output = [ImportReference(match.group(1), source.count("\n", 0, match.start()) + 1)
              for match in FROM_IMPORT_RE.finditer(source)]
    for match in PLAIN_IMPORT_RE.finditer(source):
        line = source.count("\n", 0, match.start()) + 1
        for item in match.group(1).split(","):
            module = re.split(r"\s+as\s+", item.strip(), maxsplit=1)[0]
            if MODULE_NAME_RE.fullmatch(module):
                output.append(ImportReference(module, line))
    return output


def find_import_references(source: str) -> list[ImportReference]:
    """Extract imports without requiring Python 3-compatible syntax."""

    output: list[ImportReference] = []
    for statement in _logical_statements(source):
        from_reference, handled = _from_import(statement)
        if from_reference is not None:
            output.append(from_reference)
        output.extend(_plain_imports(statement, handled))
    output.extend(_regex_imports(source))
    return list({(item.module, item.line): item for item in output}.values())


def collect_local_modules(pack_dir: str, files: Iterable[str]) -> frozenset[str]:
    """Collect importable developer-owned module paths in one behavior pack."""

    pack = Path(pack_dir).resolve()
    modules: set[str] = set()
    for path_value in files:
        try:
            relative = Path(path_value).resolve().relative_to(pack)
        except ValueError:
            continue
        parts = [*relative.parts[:-1], relative.stem]
        if parts[-1] == "__init__":
            modules.add("__init__")
            parts.pop()
        if not parts or not all(re.fullmatch(r"[A-Za-z_]\w*", part) for part in parts):
            continue
        for start in range(len(parts)):
            for end in range(start + 1, len(parts) + 1):
                modules.add(".".join(parts[start:end]))
    return frozenset(modules)


def find_disallowed_imports(
    source: str,
    whitelist: frozenset[str],
    local_modules: frozenset[str],
) -> list[ImportReference]:
    """Return imports outside the official list and local-module exemption."""

    reserved_roots = {item.split(".", 1)[0] for item in whitelist}
    output: list[ImportReference] = []
    for reference in find_import_references(source):
        if reference.module.startswith(".") or reference.module in whitelist:
            continue
        root = reference.module.split(".", 1)[0]
        if reference.module in local_modules and root not in reserved_roots:
            continue
        output.append(reference)
    return output


__all__ = [
    "ImportReference",
    "collect_local_modules",
    "find_disallowed_imports",
    "find_import_references",
    "load_module_whitelist",
]
