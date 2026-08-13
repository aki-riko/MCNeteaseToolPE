# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""网易周报形态的 Python UI 卡顿风险分析。

该模块只产生风险警告，不参与打包审核通过/拒审判定。它把周报中
“模块 + 函数”的归因方式映射到工程源码，识别高频回调中容易放大
帧耗时的 UI/玩家渲染调用，并明确静态调用链的可证明边界。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath
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
        "CreateUI",
        "GetBaseUIControl",
        "GetUI",
        "LoadForPlayer",
        "RebuildPlayerRender",
        "RegisterUI",
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
CALLBACK_NAMES = frozenset({"Notice", "OnUiInitFinished", "UiInitFinished", "Update"})
CALLBACK_SUFFIXES = ("Event", "Callback")
PYTHON_MODULE_SUFFIX = ".py"
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
        "CreateUI",
        "LoadForPlayer",
        "RebuildPlayerRender",
        "RegisterUI",
        "SetUiItem",
    }
)
EXTERNAL_BOUNDARY_CALLS = frozenset({"LoadForPlayer"})
PYTHON2_FIXERS = (
    "fix_except",
    "fix_exec",
    "fix_long",
    "fix_numliterals",
    "fix_print",
    "fix_raise",
    "fix_unicode",
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
class PerformanceAnalysis:
    """单文件静态分析结果，包括不可静默丢弃的诊断信息。"""

    risks: tuple[PerformanceRisk, ...]
    diagnostic: str = ""


@dataclass(frozen=True)
class _FunctionSummary:
    name: str
    line: int
    direct_calls: tuple[str, ...]
    loop_calls: tuple[str, ...]
    local_calls: tuple[str, ...]
    loop_local_calls: tuple[str, ...]


@dataclass(frozen=True)
class _ReachableCost:
    direct_calls: frozenset[str]
    loop_calls: frozenset[str]
    call_count: int


class _FunctionCallCollector(ast.NodeVisitor):
    """Collect calls in one function body without descending into nested defs."""

    def __init__(self, local_method_names: frozenset[str]) -> None:
        self._local_method_names = local_method_names
        self.direct_calls: list[str] = []
        self.loop_calls: list[str] = []
        self.local_calls: list[str] = []
        self.loop_local_calls: list[str] = []
        self._loop_depth = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return None

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return None

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return None

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return None

    def visit_For(self, node: ast.For) -> None:
        self._visit_loop(node)

    def visit_While(self, node: ast.While) -> None:
        self._visit_loop(node)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_loop(node)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_loop(node)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_loop(node)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_loop(node)

    def _visit_loop(self, node: ast.AST) -> None:
        self._loop_depth += 1
        self.generic_visit(node)
        self._loop_depth -= 1

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node)
        if name in HIGH_COST_CALLS:
            self.direct_calls.append(name)
            if self._loop_depth:
                self.loop_calls.append(name)
        local_name = _same_scope_call_name(node, self._local_method_names)
        if local_name:
            self.local_calls.append(local_name)
            if self._loop_depth:
                self.loop_local_calls.append(local_name)
        self.generic_visit(node)


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
    """把中文或英文周报字段转换为统一记录。"""

    return NeteasePerformanceRecord(
        component_id=_text(_first(payload, "组件ID", "componentId", "component_id")),
        component_name=_text(
            _first(payload, "组件名称", "componentName", "component_name")
        ),
        jank_count=_integer(_first(payload, "本周卡顿次数", "jankCount", "jank_count")),
        average_jank_seconds=_number(
            _first(
                payload,
                "平均卡顿时长(秒)",
                "平均卡顿时长（秒）",
                "averageJankSeconds",
                "average_jank_seconds",
            )
        ),
        module_name=_text(_first(payload, "模块名称", "moduleName", "module_name")),
        function_name=_text(
            _first(payload, "函数名称", "functionName", "function_name")
        ),
    )


def normalize_report_records(
    payload: Iterable[Mapping[str, object]],
) -> list[NeteasePerformanceRecord]:
    """归一化多行周报，并忽略非对象输入。"""

    return [normalize_report_record(item) for item in payload if isinstance(item, Mapping)]


def _call_name(node: ast.Call) -> str:
    function = node.func
    if isinstance(function, ast.Attribute):
        return function.attr
    if isinstance(function, ast.Name):
        return function.id
    return ""


def _same_scope_call_name(
    node: ast.Call,
    local_method_names: frozenset[str],
) -> str:
    function = node.func
    if isinstance(function, ast.Name) and function.id in local_method_names:
        return function.id
    if (
        isinstance(function, ast.Attribute)
        and function.attr in local_method_names
        and isinstance(function.value, ast.Name)
        and function.value.id in {"self", "cls"}
    ):
        return function.attr
    return ""


def _is_callback(name: str) -> bool:
    return name in CALLBACK_NAMES or name.endswith(CALLBACK_SUFFIXES)


@lru_cache(maxsize=1)
def _python2_refactoring_tool() -> object:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from lib2to3.refactor import RefactoringTool

    return RefactoringTool(["lib2to3.fixes." + name for name in PYTHON2_FIXERS])


def _parse_python_source(source: str) -> tuple[ast.AST | None, str]:
    try:
        return ast.parse(source), ""
    except SyntaxError as initial_error:
        try:
            tool = _python2_refactoring_tool()
            parse_source = source if source.endswith(("\n", "\r")) else source + "\n"
            converted = str(tool.refactor_string(parse_source, "<netease-python>"))
            return ast.parse(converted), ""
        except Exception as fallback_error:
            detail = str(fallback_error).strip() or fallback_error.__class__.__name__
            return None, (
                "性能风险分析无法解析 Python 源码："
                f"Python 3 解析失败（第 {initial_error.lineno or 0} 行）；"
                f"Python 2 兼容解析也失败（{detail}）"
            )


def _summarize_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    local_method_names: frozenset[str],
) -> _FunctionSummary:
    collector = _FunctionCallCollector(local_method_names)
    for statement in node.body:
        collector.visit(statement)
    return _FunctionSummary(
        name=node.name,
        line=int(getattr(node, "lineno", 0)),
        direct_calls=tuple(collector.direct_calls),
        loop_calls=tuple(collector.loop_calls),
        local_calls=tuple(collector.local_calls),
        loop_local_calls=tuple(collector.loop_local_calls),
    )


def _summaries(scope: ast.Module | ast.ClassDef) -> dict[str, _FunctionSummary]:
    methods = [
        node
        for node in scope.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    local_method_names = frozenset(node.name for node in methods)
    return {
        node.name: _summarize_function(node, local_method_names) for node in methods
    }


def _reachable_cost(
    name: str,
    summaries: Mapping[str, _FunctionSummary],
    seen: frozenset[str] = frozenset(),
) -> _ReachableCost:
    summary = summaries.get(name)
    if summary is None or name in seen:
        return _ReachableCost(frozenset(), frozenset(), 0)
    direct = set(summary.direct_calls)
    loops = set(summary.loop_calls)
    call_count = len(summary.direct_calls)
    for child in summary.local_calls:
        child_cost = _reachable_cost(child, summaries, seen | {name})
        direct.update(child_cost.direct_calls)
        loops.update(child_cost.loop_calls)
        call_count += child_cost.call_count
        if child in summary.loop_local_calls:
            loops.update(child_cost.direct_calls)
    return _ReachableCost(
        frozenset(direct),
        frozenset(loops),
        call_count,
    )


def _risk_for_callback(
    path: str,
    name: str,
    summary: _FunctionSummary,
    cost: _ReachableCost,
) -> PerformanceRisk | None:
    critical = cost.direct_calls.intersection(CRITICAL_CALLS)
    if not cost.loop_calls and cost.call_count < 3 and not critical:
        return None
    locations = ", ".join(sorted(cost.direct_calls))
    detail = f"{name}（第 {summary.line} 行）调用高成本操作：{locations or '间接调用'}"
    if cost.loop_calls:
        detail += f"；循环内重复操作：{', '.join(sorted(cost.loop_calls))}"
    external = cost.direct_calls.intersection(EXTERNAL_BOUNDARY_CALLS)
    if external:
        detail += (
            "；外部调用边界："
            f"{', '.join(sorted(external))}，已确认调用但未跨文件展开其内部实现"
        )
    detail += "。这是静态风险提示，需用 Tracy/AirPerf 在真实玩法中确认。"
    severity = "warning" if cost.loop_calls or cost.call_count >= 3 or critical else "info"
    return PerformanceRisk(
        path=path,
        function_name=name,
        severity=severity,
        title="Python UI 性能风险警告",
        detail=detail,
    )


def analyze_python_source_result(source: str, path: str = "") -> PerformanceAnalysis:
    """分析单个文件，同时返回不能静默忽略的解析诊断。"""

    tree, diagnostic = _parse_python_source(source)
    if tree is None:
        return PerformanceAnalysis((), diagnostic)
    risks: list[PerformanceRisk] = []
    scopes: list[ast.Module | ast.ClassDef] = [tree]
    scopes.extend(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef))
    for scope in scopes:
        summaries = _summaries(scope)
        for name, summary in summaries.items():
            if not _is_callback(name):
                continue
            risk = _risk_for_callback(
                path,
                name,
                summary,
                _reachable_cost(name, summaries),
            )
            if risk is not None:
                risks.append(risk)
    return PerformanceAnalysis(tuple(risks))


def analyze_python_source(source: str, path: str = "") -> list[PerformanceRisk]:
    """兼容原调用方，仅返回风险列表。"""

    return list(analyze_python_source_result(source, path).risks)


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


def _module_parts(module_name: str) -> tuple[str, ...]:
    normalized = module_name.strip().replace("\\", "/")
    if normalized.casefold().endswith(PYTHON_MODULE_SUFFIX):
        normalized = normalized[: -len(PYTHON_MODULE_SUFFIX)]
    if "/" not in normalized:
        normalized = normalized.replace(".", "/")
    path = PurePosixPath(normalized.casefold())
    return tuple(part for part in path.parts if part not in {"", "."})


def match_report_to_risks(
    record: NeteasePerformanceRecord,
    risks: Iterable[PerformanceRisk],
) -> list[PerformanceRisk]:
    """按模块路径后缀和函数名把周报记录匹配到源码风险。"""

    report_parts = _module_parts(record.module_name)
    function = record.function_name.casefold()
    matched: list[PerformanceRisk] = []
    for risk in risks:
        risk_parts = _module_parts(risk.path)
        module_matches = not report_parts or risk_parts[-len(report_parts) :] == report_parts
        if risk.function_name.casefold() == function and module_matches:
            matched.append(risk)
    return matched


__all__ = [
    "NeteasePerformanceRecord",
    "PerformanceAnalysis",
    "PerformanceRisk",
    "analyze_project",
    "analyze_python_source",
    "analyze_python_source_result",
    "match_report_to_risks",
    "normalize_report_record",
    "normalize_report_records",
]
