# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""将 Tracy 采样与前后差异整理为面向开发者的事实型总结报告。"""

from __future__ import annotations

from collections.abc import Mapping

from .tracy_semantics import is_wait_zone_name


def new_session_summary() -> dict[str, object]:
    """创建常量内存增长的持续监测归约状态。"""
    return {
        "windows": 0,
        "seconds": 0,
        "captureSpanSeconds": 0.0,
        "frames": 0,
        "framesKnown": True,
        "zones": 0,
        "capturedAt": "",
        "functions": {},
    }


def _number(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _integer(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _rows(payload: Mapping[str, object], key: str) -> list[Mapping[str, object]]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _metric(label: str, value: str) -> dict[str, str]:
    return {"label": label, "value": value}


def _report_rows(capture: Mapping[str, object]) -> list[Mapping[str, object]]:
    rows = _rows(capture, "rows") or _rows(capture, "top")
    return sorted(
        rows,
        key=lambda row: (-_number(row.get("selfMs")), str(row.get("name", ""))),
    )


def _is_wait_zone(row: Mapping[str, object]) -> bool:
    return is_wait_zone_name(row.get("name", ""))


def _wait_self_ms(capture: Mapping[str, object]) -> float:
    return sum(
        _number(row.get("selfMs"))
        for row in _report_rows(capture)
        if _is_wait_zone(row)
    )


def _capture_metrics(capture: Mapping[str, object]) -> list[dict[str, str]]:
    metrics = [
        _metric("采样时长", f"{_integer(capture.get('seconds'))} 秒"),
        _metric("函数", str(_integer(capture.get("matchedFunctions")))),
    ]
    frames = capture.get("frames")
    if frames is not None:
        metrics.insert(1, _metric("Tracy FrameMark 数", str(_integer(frames))))
    fps = capture.get("averageFps")
    if fps is not None:
        metrics.append(_metric("Tracy FrameMark 频率", f"{_number(fps):.1f} 次/秒"))
    wait_self_ms = _wait_self_ms(capture)
    if wait_self_ms:
        metrics.append(_metric("等待函数自身耗时", f"{wait_self_ms:.3f} ms"))
    captured_at = str(capture.get("capturedAt", "")).strip()
    if captured_at:
        metrics.append(_metric("检测时间", captured_at))
    return metrics


def _hotspot_item(row: Mapping[str, object]) -> dict[str, str]:
    return {
        "kind": "hotspot",
        "name": str(row.get("name", "未知函数")),
        "detail": (
            f"自身 {_number(row.get('selfMs')):.3f} ms · "
            f"总计 {_number(row.get('totalMs')):.3f} ms · "
            f"调用 {_integer(row.get('calls'))} 次"
        ),
    }


def _capture_recommendations(
    capture: Mapping[str, object], top: Mapping[str, object]
) -> list[str]:
    name = str(top.get("name", "首个热点"))
    recommendations = [f"优先检查 {name}，它是本次自身耗时最高的函数。"]
    calls = _integer(top.get("calls"))
    frames = _integer(capture.get("frames"))
    if frames and calls > frames:
        recommendations.append(
            f"该函数平均每个 FrameMark 调用 {calls / frames:.2f} 次，检查是否存在重复执行。"
        )
    self_ms = _number(top.get("selfMs"))
    if self_ms and _number(top.get("totalMs")) >= self_ms * 1.5:
        recommendations.append("它的总耗时明显高于自身耗时，继续检查下游调用链。")
    return recommendations


def _wait_recommendation(capture: Mapping[str, object]) -> str | None:
    wait_names = [
        str(row.get("name", ""))
        for row in _report_rows(capture)
        if _is_wait_zone(row)
    ]
    if not wait_names:
        return None
    return f"{', '.join(wait_names)} 属于等待函数，等待函数不作为优化热点。"


def build_capture_report(capture: Mapping[str, object]) -> dict[str, object]:
    """生成单次采样报告，不使用未公开的通过阈值。"""
    hotspots = [row for row in _report_rows(capture) if not _is_wait_zone(row)]
    if not hotspots:
        wait_note = _wait_recommendation(capture)
        return {
            "kind": "capture",
            "title": "本次检测总结",
            "verdict": "未发现热点",
            "tone": "info",
            "conclusion": (
                "本次只采集到等待函数，没有可归因的执行热点。"
                if wait_note
                else "本次没有可汇总的函数热点，请确认检测期间触发了目标玩法。"
            ),
            "metrics": _capture_metrics(capture),
            "highlights": [],
            "recommendations": [
                wait_note or "重新检测时，在游戏中持续操作需要分析的玩法。"
            ],
        }
    top = hotspots[0]
    top_self = _number(top.get("selfMs"))
    actionable_self = sum(_number(row.get("selfMs")) for row in hotspots)
    share = (
        f"，占非等待函数自身耗时 {top_self / actionable_self * 100:.1f}%"
        if actionable_self
        else ""
    )
    recommendations = _capture_recommendations(capture, top)
    wait_note = _wait_recommendation(capture)
    if wait_note:
        recommendations.insert(0, wait_note)
    return {
        "kind": "capture",
        "title": "本次检测总结",
        "verdict": "检测完成",
        "tone": "info",
        "conclusion": f"主要热点是 {top.get('name', '未知函数')}，自身耗时 {top_self:.3f} ms{share}。",
        "metrics": _capture_metrics(capture),
        "highlights": [_hotspot_item(row) for row in hotspots[:3]],
        "recommendations": recommendations,
    }


def add_capture_to_session(
    session: dict[str, object], capture: Mapping[str, object]
) -> None:
    """把一个窗口累加到持续会话，不保留每个窗口的完整明细。"""
    session["windows"] = _integer(session.get("windows")) + 1
    session["seconds"] = _integer(session.get("seconds")) + _integer(
        capture.get("seconds")
    )
    session["captureSpanSeconds"] = _number(
        session.get("captureSpanSeconds")
    ) + _number(capture.get("captureSpanSeconds") or capture.get("seconds"))
    frames = capture.get("frames")
    if frames is None:
        session["framesKnown"] = False
    else:
        session["frames"] = _integer(session.get("frames")) + _integer(frames)
    session["zones"] = _integer(session.get("zones")) + _integer(capture.get("zones"))
    session["capturedAt"] = str(capture.get("capturedAt", ""))
    functions = session.setdefault("functions", {})
    if isinstance(functions, dict):
        _merge_session_rows(functions, _rows(capture, "rows"))


def _merge_session_rows(
    functions: dict[str, object], rows: list[Mapping[str, object]]
) -> None:
    for row in rows:
        name = str(row.get("name", "")).strip()
        if not name:
            continue
        current = functions.setdefault(
            name, {"name": name, "selfMs": 0.0, "totalMs": 0.0, "calls": 0}
        )
        if not isinstance(current, dict):
            continue
        current["selfMs"] = _number(current.get("selfMs")) + _number(row.get("selfMs"))
        current["totalMs"] = _number(current.get("totalMs")) + _number(row.get("totalMs"))
        current["calls"] = _integer(current.get("calls")) + _integer(row.get("calls"))


def _session_capture(session: Mapping[str, object]) -> dict[str, object]:
    functions = session.get("functions")
    values = list(functions.values()) if isinstance(functions, Mapping) else []
    rows = [dict(row) for row in values if isinstance(row, Mapping)]
    rows.sort(key=lambda row: (-_number(row.get("selfMs")), str(row.get("name", ""))))
    seconds = _integer(session.get("seconds"))
    capture_span_seconds = _number(session.get("captureSpanSeconds")) or float(seconds)
    frames = _integer(session.get("frames"))
    frames_known = session.get("framesKnown") is True
    return {
        "seconds": seconds,
        "captureSpanSeconds": capture_span_seconds,
        "frames": frames if frames_known else None,
        "zones": _integer(session.get("zones")),
        "averageFps": (
            frames / capture_span_seconds
            if frames_known and capture_span_seconds
            else None
        ),
        "matchedFunctions": len(rows),
        "totalSelfMs": sum(_number(row.get("selfMs")) for row in rows),
        "capturedAt": session.get("capturedAt", ""),
        "top": rows[:3],
        "rows": rows,
    }


def build_session_report(
    session: Mapping[str, object], *, active: bool
) -> dict[str, object]:
    """生成持续会话当前累计或停止后的总结。"""
    windows = _integer(session.get("windows"))
    report = build_capture_report(_session_capture(session))
    if not windows:
        conclusion = (
            "正在采集第一个监测窗口，请继续操作需要分析的玩法。"
            if active
            else "监测在首个完整窗口结束前停止，没有可汇总的函数热点。"
        )
    else:
        conclusion = f"已完成 {windows} 个连续窗口；{report['conclusion']}"
    report.update(
        {
            "kind": "session",
            "title": "持续性能监测报告",
            "verdict": "持续监测中" if active else "监测完成",
            "tone": "processing" if active else "info",
            "conclusion": conclusion,
            "metrics": [_metric("监测窗口", str(windows))] + report["metrics"],
        }
    )
    return report


def _comparison_conclusion(summary: Mapping[str, object]) -> tuple[str, str, str]:
    delta = _number(summary.get("deltaMs"))
    percent = summary.get("percent")
    change = f"{abs(delta):.3f} ms"
    if percent is not None:
        change += f"（{abs(_number(percent)):.2f}%）"
    if delta < 0:
        return "已有改善", "success", f"已匹配函数自身总耗时下降 {change}。"
    if delta > 0:
        return "需要关注", "warning", f"已匹配函数自身总耗时上升 {change}。"
    return "基本持平", "info", "两次检测的已匹配函数自身总耗时没有变化。"


def _change_items(diff: Mapping[str, object]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for key, kind in (
        ("regressed", "regressed"),
        ("improved", "improved"),
        ("added", "added"),
        ("removed", "removed"),
    ):
        for row in _rows(diff, key)[:2]:
            result.append(
                {
                    "kind": kind,
                    "name": str(row.get("name", "未知函数")),
                    "detail": (
                        f"{_number(row.get('baseMs')):.3f} → "
                        f"{_number(row.get('newMs')):.3f} ms · "
                        f"变化 {_number(row.get('deltaMs')):+.3f} ms"
                    ),
                }
            )
    return result


def _comparison_metrics(
    new: Mapping[str, object], summary: Mapping[str, object]
) -> list[dict[str, str]]:
    return [
        _metric("优化前", f"{_number(summary.get('baseSelfMs')):.3f} ms"),
        _metric("优化后", f"{_number(summary.get('newSelfMs')):.3f} ms"),
        _metric("变化", f"{_number(summary.get('deltaMs')):+.3f} ms"),
    ] + _capture_metrics(new)


def _comparison_recommendations(diff: Mapping[str, object]) -> list[str]:
    regressed = _rows(diff, "regressed")
    improved = _rows(diff, "improved")
    recommendations: list[str] = []
    if regressed:
        recommendations.append(f"优先检查回退最大的 {regressed[0].get('name', '函数')}。")
    if improved:
        recommendations.append(f"改善最大的是 {improved[0].get('name', '函数')}，建议保留改动并复测。")
    if _rows(diff, "added"):
        recommendations.append("本次出现了新热点，确认它是否由当前改动或场景差异引入。")
    return recommendations or ["函数级耗时未出现明显变化；请保持相同场景继续复测。"]


def build_comparison_report(
    new: Mapping[str, object], diff: Mapping[str, object]
) -> dict[str, object]:
    """生成两次等长采样的自动对比报告。"""
    summary = diff.get("summary")
    summary_map = summary if isinstance(summary, Mapping) else {}
    verdict, tone, conclusion = _comparison_conclusion(summary_map)
    return {
        "kind": "comparison",
        "title": "优化前后对比报告",
        "verdict": verdict,
        "tone": tone,
        "conclusion": conclusion,
        "metrics": _comparison_metrics(new, summary_map),
        "highlights": _change_items(diff),
        "recommendations": _comparison_recommendations(diff),
    }


__all__ = [
    "add_capture_to_session",
    "build_capture_report",
    "build_comparison_report",
    "build_session_report",
    "new_session_summary",
]
