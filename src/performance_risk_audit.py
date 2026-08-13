# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""网易周报形态的 Python UI 卡顿风险分析。

该模块只产生风险警告，不参与打包审核通过/拒审判定。它把周报中
“模块 + 函数”的归因方式映射到工程源码，识别 Update/事件回调中容易
放大帧耗时的 UI 引擎调用，并保留调用链上下文供 Tracy 复核。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping
import warnings


HIGH_COST_CALLS = frozenset(
    {
        "Clone",
        "AddPlayerAnimation",
        "AddPlayerAnimationController",
        "AddPlayerGeometry",
        "AddPlayerRenderController",
        "AddPlayerRenderMaterial",
        "AddPlayerSoundEffect",
        "AddPlayerTexture",
        "CreateActorRender",
        "GetBaseUIControl",
        "LoadForPlayer",
        "RebuildPlayerRender",
        "SetAlpha",
        "SetPosition",
        "SetScrollViewPos",
        "SetSize",
        "SetSprite",
        "SetText",
        "SetUiItem",
        "SetVisible",
    }
)
CALLBACK_NAMES = frozenset({"Update"})
CALLBACK_SUFFIXES = ("Event", "Callback")
MAX_CALL_GRAPH_DEPTH = 3
PYTHON_MODULE_SUFFIX = ".py"
LOOP_NODES = (ast.For, ast.While, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
CRITICAL_CALLS = frozenset(
    {
        "Clone",
        "AddPlayerAnimation",
        "AddPlayerAnimationController",
        "AddPlayerGeometry",
        "AddPlayerRenderController",
        "AddPlayerRenderMaterial",
        "AddPlayerSoundEffect",
        "AddPlayerTexture",
        "CreateActorRender",
        "LoadForPlayer",
        "RebuildPlayerRender",
        "SetUiItem",
    }
)


@dataclass(frozen=True)
class NeteasePerformanceRecord:
    """一行网易卡顿周报的归一化表示。"""

    component_id: str
    component_name: str
    jank_count: int
    average_jank_seconds: float
    module_name: str
    function_name: str

    @property
    def average_jank_ms(self) -> float:
        return self.average_jank_seconds * 1000.0


@dataclass(frozen=True)
class PerformanceRisk:
    """源码风险警告；不等于运行时已证实的卡顿。"""

    path: str
    function_name: str
    severity: str
    title: str
    detail: str


@dataclass(frozen=True)
class _FunctionSummary:
    name: str
    line: int
    direct_calls: tuple[str, ...]
    loop_calls: tuple[str, ...]
    local_calls: tuple[str, ...]
    loop_local_calls: tuple[str, ...]


def _text(value: object) -> str:
    return str(value or "").strip()


def _integer(value: object) -> int:
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def _number(value: object) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _first(mapping: Mapping[str, object], *keys: str) -> object:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return ""


def normalize_report_record(payload: Mapping[str, object]) -> NeteasePerformanceRecord:
    """把中文或英文周报字段转换为统一记录。

    支持网易截图中对应的字段名，也支持导出 JSON/CSV 时常见的英文别名。
    """

    return NeteasePerformanceRecord(
        component_id=_text(_first(payload, "组件ID", "componentId", "component_id")),
        component_name=_text(_first(payload, "组件名称", "componentName", "component_name")),
        jank_count=_integer(_first(payload, "本周卡顿次数", "jankCount", "jank_count")),
        average_jank_seconds=_number(
            _first(payload, "平均卡顿时长(秒)", "平均卡顿时长（秒）", "averageJankSeconds", "average_jank_seconds")
        ),
        module_name=_text(_first(payload, "模块名称", "moduleName", "module_name")),
        function_name=_text(_first(payload, "函数名称", "functionName", "function_name")),
    )


def normalize_report_records(
    payload: Iterable[Mapping[str, object]],
) -> list[NeteasePerformanceRecord]:
    """归一化多行周报，并忽略非对象输入。"""

    return [normalize_report_record(item) for item in payload if isinstance(item, Mapping)]


def _function_name(node: ast.AST) -> str:
    return str(getattr(node, "name", ""))


def _call_name(node: ast.Call) -> str:
    function = node.func
    if isinstance(function, ast.Attribute):
        return function.attr
    if isinstance(function, ast.Name):
        return function.id
    return ""


def _is_callback(name: str) -> bool:
    return name in CALLBACK_NAMES or name.endswith(CALLBACK_SUFFIXES)


def _parse_python2_source(source: str) -> ast.AST | None:
    try:
        return ast.parse(source)
    except SyntaxError:
        # 网易行为包仍常见 Python 2 print/except 语法；lib2to3 是标准库，
        # 只用于只读解析，不会改写工程文件。
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                from lib2to3.refactor import RefactoringTool

            tool = RefactoringTool(
                ["lib2to3.fixes." + name for name in (
                    "fix_except", "fix_exec", "fix_print", "fix_raise", "fix_unicode"
                )]
            )
            converted = str(tool.refactor_string(source, "<netease-python>"))
            return ast.parse(converted)
        except (Exception, SyntaxError):  # pragma: no cover - parser fallback
            return None


def _summarize_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> _FunctionSummary:
    direct: list[str] = []
    loop: list[str] = []
    local: list[str] = []
    loop_local: list[str] = []
    for part in ast.walk(node):
        if not isinstance(part, ast.Call):
            continue
        name = _call_name(part)
        if name in HIGH_COST_CALLS:
            direct.append(name)
        elif isinstance(part.func, ast.Name) and part.func.id.startswith("_"):
            local.append(part.func.id)
        elif (
            isinstance(part.func, ast.Attribute)
            and part.func.attr.startswith("_")
            and isinstance(part.func.value, ast.Name)
            and part.func.value.id in {"self", "cls"}
        ):
            local.append(part.func.attr)
    # ast 不保留 parent；通过独立遍历循环体精确记录循环内的高成本调用。
    for loop_node in ast.walk(node):
        if not isinstance(loop_node, LOOP_NODES):
            continue
        for part in ast.walk(loop_node):
            if isinstance(part, ast.Call):
                name = _call_name(part)
                if name in HIGH_COST_CALLS:
                    loop.append(name)
                elif isinstance(part.func, ast.Name) and part.func.id.startswith("_"):
                    loop_local.append(part.func.id)
                elif (
                    isinstance(part.func, ast.Attribute)
                    and part.func.attr.startswith("_")
                    and isinstance(part.func.value, ast.Name)
                    and part.func.value.id in {"self", "cls"}
                ):
                    loop_local.append(part.func.attr)
    return _FunctionSummary(
        name=_function_name(node),
        line=int(getattr(node, "lineno", 0)),
        direct_calls=tuple(sorted(set(direct))),
        loop_calls=tuple(sorted(set(loop))),
        local_calls=tuple(sorted(set(local))),
        loop_local_calls=tuple(sorted(set(loop_local))),
    )


def _summaries(scope: ast.Module | ast.ClassDef) -> dict[str, _FunctionSummary]:
    return {
        node.name: _summarize_function(node)
        for node in scope.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _reachable_cost(
    name: str,
    summaries: Mapping[str, _FunctionSummary],
    depth: int = 0,
    seen: frozenset[str] = frozenset(),
) -> tuple[set[str], set[str]]:
    summary = summaries.get(name)
    if summary is None:
        return set(), set()
    direct = set(summary.direct_calls)
    loops = set(summary.loop_calls)
    if depth >= MAX_CALL_GRAPH_DEPTH or name in seen:
        return direct, loops
    for child in summary.local_calls:
        child_direct, child_loops = _reachable_cost(
            child, summaries, depth + 1, seen | {name}
        )
        direct.update(child_direct)
        loops.update(child_loops)
        if child in summary.loop_local_calls:
            loops.update(child_direct)
            loops.update(child_loops)
    return direct, loops


def analyze_python_source(source: str, path: str = "") -> list[PerformanceRisk]:
    """分析单个 Python 行为包文件，返回保守的性能风险警告。"""

    tree = _parse_python2_source(source)
    if tree is None:
        return []
    risks: list[PerformanceRisk] = []
    scopes: list[ast.Module | ast.ClassDef] = [tree]
    scopes.extend(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef))
    for scope in scopes:
        summaries = _summaries(scope)
        for name, summary in summaries.items():
            if not _is_callback(name):
                continue
            direct, loops = _reachable_cost(name, summaries)
            if not loops and len(direct) < 3 and not direct.intersection(CRITICAL_CALLS):
                continue
            severity = (
                "warning"
                if loops or name == "Update" or direct.intersection(CRITICAL_CALLS)
                else "info"
            )
            locations = ", ".join(sorted(direct))
            loop_text = ", ".join(sorted(loops))
            detail = f"{name}（第 {summary.line} 行）调用 UI 引擎操作：{locations or '间接调用'}"
            if loop_text:
                detail += f"；循环内重复操作：{loop_text}"
            detail += "。这是静态风险提示，需用 Tracy/AirPerf 在真实玩法中确认。"
            risks.append(
                PerformanceRisk(
                    path=path,
                    function_name=name,
                    severity=severity,
                    title="Python UI 性能风险警告",
                    detail=detail,
                )
            )
    return risks


def analyze_project(project_dir: str) -> list[PerformanceRisk]:
    """只读扫描行为包 Python 文件，返回性能风险警告。"""

    root = Path(project_dir).resolve()
    if not root.is_dir():
        return []
    risks: list[PerformanceRisk] = []
    for path in root.rglob("*" + PYTHON_MODULE_SUFFIX):
        if any(part in {".git", "__pycache__", ".pytest_cache"} for part in path.parts):
            continue
        try:
            source = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue
        risks.extend(analyze_python_source(source, str(path)))
    return risks


def match_report_to_risks(
    record: NeteasePerformanceRecord,
    risks: Iterable[PerformanceRisk],
) -> list[PerformanceRisk]:
    """按模块末段和函数名把周报记录匹配到源码风险。"""

    module_tail = record.module_name.rsplit(".", 1)[-1].casefold()
    function = record.function_name.casefold()
    return [
        risk
        for risk in risks
        if risk.function_name.casefold() == function
        and (
            not module_tail
            or module_tail in Path(risk.path).stem.casefold()
            or module_tail in risk.path.casefold()
        )
    ]


__all__ = [
    "NeteasePerformanceRecord",
    "PerformanceRisk",
    "analyze_project",
    "analyze_python_source",
    "match_report_to_risks",
    "normalize_report_record",
    "normalize_report_records",
]
