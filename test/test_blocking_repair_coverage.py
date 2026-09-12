# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""非代码审核阻塞项的程序内处置说明覆盖测试。"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.blocking_repair import (
    KNOWN_AUDIT_ERROR_CODES,
    NON_CODE_ERROR_CODES,
    is_non_code_issue,
    issue_guidance,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT_SOURCES = (REPO_ROOT / "src" / "pack_scanner.py", REPO_ROOT / "src" / "netease_content_audit.py")
GENERIC_GUIDANCE = issue_guidance(-1, "未知审核问题")
ACTION_OR_BOUNDARY_TERMS = (
    "人工",
    "不会",
    "不能",
    "检查",
    "修复",
    "处理",
    "显示",
    "选择",
    "定位",
    "转换",
)


def _error_codes_from_source(path: Path) -> set[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    codes: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id == "_issue" and len(node.args) >= 2:
            code, severity = node.args[:2]
        elif node.func.id == "_finding" and len(node.args) >= 4:
            code, severity = node.args[2:4]
        else:
            continue
        if isinstance(code, ast.Constant) and isinstance(code.value, int):
            if isinstance(severity, ast.Constant) and severity.value == "error":
                codes.add(code.value)
    return codes


def test_error_code_inventory_tracks_the_actual_audit_sources() -> None:
    source_codes = set().union(*(_error_codes_from_source(path) for path in AUDIT_SOURCES))

    assert source_codes == KNOWN_AUDIT_ERROR_CODES
    assert NON_CODE_ERROR_CODES < KNOWN_AUDIT_ERROR_CODES


@pytest.mark.parametrize("code", sorted(NON_CODE_ERROR_CODES))
def test_every_non_code_error_has_specific_in_app_guidance(code: int) -> None:
    guidance = issue_guidance(code, f"审核错误码 {code}").strip()

    assert guidance
    assert guidance != GENERIC_GUIDANCE
    assert len(guidance) >= 15
    assert any(term in guidance for term in ACTION_OR_BOUNDARY_TERMS), guidance


def test_code_18_project_editor_metadata_uses_cleanup_guidance() -> None:
    guidance = issue_guidance(18, "工程包含编辑信息")

    assert "编辑信息" in guidance
    assert "确认清理项" in guidance
    assert "修改源码" not in guidance


def test_other_code_18_issues_keep_source_review_guidance() -> None:
    guidance = issue_guidance(18, "历史已确认的网易拒审规则")

    assert "代码或 API 审核问题" in guidance
    assert "修改源码" in guidance
    assert "确认清理项" not in guidance


def test_mixed_code_35_distinguishes_filename_and_python_identifier() -> None:
    assert is_non_code_issue(35, "命名含 5 个以上连续相同字符") is True
    assert is_non_code_issue(35, "标识符含5个以上连续相同字符") is False
    assert "修改源码" in issue_guidance(35, "标识符含5个以上连续相同字符")
