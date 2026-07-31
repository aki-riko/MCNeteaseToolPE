# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""将 Tracy 采样与前后差异整理为面向开发者的事实型总结报告。"""

from __future__ import annotations

from collections.abc import Mapping


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


def _capture_metrics(capture: Mapping[str, object]) -> list[dict[str, str]]:
    metrics = [
        _metric("采样时长", f"{_integer(capture.get('seconds'))} 秒"),
        _metric("函数", str(_integer(capture.get("matchedFunctions")))),
    ]
    frames = capture.get("frames")
    if frames is not None:
        metrics.insert(1, _metric("帧数", str(_integer(frames))))
    fps = capture.get("averageFps")
    if fps is not None:
        metrics.append(_metric("窗口平均 FPS", f"{_number(fps):.1f}"))
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
            f"该函数平均每帧调用 {calls / frames:.2f} 次，检查是否存在重复执行。"
        )
    self_ms = _number(top.get("selfMs"))
    if self_ms and _number(top.get("totalMs")) >= self_ms * 1.5:
        recommendations.append("它的总耗时明显高于自身耗时，继续检查下游调用链。")
    return recommendations


def build_capture_report(capture: Mapping[str, object]) -> dict[str, object]:
    """生成单次采样报告，不使用未公开的通过阈值。"""
    hotspots = _rows(capture, "top")
    if not hotspots:
        return {
            "kind": "capture",
            "title": "本次检测总结",
            "verdict": "未发现热点",
            "tone": "info",
            "conclusion": "本次没有可汇总的函数热点，请确认检测期间触发了目标玩法。",
            "metrics": _capture_metrics(capture),
            "highlights": [],
            "recommendations": ["重新检测时，在游戏中持续操作需要分析的玩法。"],
        }
    top = hotspots[0]
    top_self = _number(top.get("selfMs"))
    total_self = _number(capture.get("totalSelfMs"))
    share = f"，占全部函数自身耗时 {top_self / total_self * 100:.1f}%" if total_self else ""
    return {
        "kind": "capture",
        "title": "本次检测总结",
        "verdict": "检测完成",
        "tone": "info",
        "conclusion": f"主要热点是 {top.get('name', '未知函数')}，自身耗时 {top_self:.3f} ms{share}。",
        "metrics": _capture_metrics(capture),
        "highlights": [_hotspot_item(row) for row in hotspots[:3]],
        "recommendations": _capture_recommendations(capture, top),
    }


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


__all__ = ["build_capture_report", "build_comparison_report"]
