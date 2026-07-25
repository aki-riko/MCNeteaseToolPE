# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
# 网易旧代码审核器的窄兼容规则。
# Narrow compatibility rules for the legacy Netease code reviewer.

"""Compatibility checks that current pylint cannot reproduce reliably.

These rules deliberately cover only patterns proven by historical rejected
projects.  They must stay narrow so missing Netease SDK modules do not turn
into hundreds of local-only import errors.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class CompatFinding:
    """One legacy-review finding before it is converted to an audit issue."""

    message_id: str
    symbol: str
    message: str
    line: int
    column: int


def _is_property_setter(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Attribute) or decorator.attr != "setter":
            continue
        if isinstance(decorator.value, ast.Name) and decorator.value.id == node.name:
            return True
    return False


def _self_stores(node: ast.AST) -> dict[str, list[int]]:
    stores: dict[str, list[int]] = {}
    for part in ast.walk(node):
        if not isinstance(part, ast.Attribute) or not isinstance(part.ctx, ast.Store):
            continue
        if isinstance(part.value, ast.Name) and part.value.id == "self":
            stores.setdefault(part.attr, []).append(part.lineno)
    return stores


def _getattr_accesses(node: ast.AST) -> list[tuple[str, int, int]]:
    accesses: list[tuple[str, int, int]] = []
    for part in ast.walk(node):
        if not isinstance(part, ast.Call) or len(part.args) < 2:
            continue
        if not isinstance(part.func, ast.Name) or part.func.id != "getattr":
            continue
        owner, member = part.args[:2]
        if not isinstance(owner, ast.Name) or owner.id != "self":
            continue
        if not isinstance(member, ast.Constant) or not isinstance(member.value, str):
            continue
        accesses.append((member.value, part.lineno, part.col_offset))
    return accesses


def find_legacy_property_accesses(source: str) -> list[CompatFinding]:
    """Reproduce the legacy E0203 property-setter rejection.

    The old reviewer rejected ``getattr(self, "_x", ...)`` followed by a
    direct ``self._x = ...`` in the same property setter when the class had no
    earlier direct initialization.  Modern pylint no longer reports it.
    """

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    findings: list[CompatFinding] = []
    for class_node in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
        class_stores: dict[str, list[int]] = {}
        methods = [
            node
            for node in class_node.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        for method in methods:
            for member, lines in _self_stores(method).items():
                class_stores.setdefault(member, []).extend(lines)

        for method in methods:
            if not _is_property_setter(method):
                continue
            method_stores = _self_stores(method)
            for member, line, column in _getattr_accesses(method):
                later_stores = [item for item in method_stores.get(member, []) if item > line]
                earlier_stores = [item for item in class_stores.get(member, []) if item < line]
                if not later_stores or earlier_stores:
                    continue
                definition_line = min(later_stores)
                findings.append(
                    CompatFinding(
                        "E0203",
                        "access-member-before-definition",
                        f"Access to member '{member}' before its definition line {definition_line}",
                        line,
                        column,
                    )
                )
    return findings


__all__ = [
    "CompatFinding",
    "find_legacy_property_accesses",
]
