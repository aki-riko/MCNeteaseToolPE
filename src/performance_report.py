# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""把进程与 AirPerf 指标按明确口径合并进持续监测报告。"""

from __future__ import annotations

from collections.abc import Mapping


def _sample_rate_text(sample_count: int, session_seconds: int) -> str:
    if session_seconds <= 0:
        return str(sample_count)
    return f"{sample_count}（{sample_count / session_seconds:.2f} Hz）"


def _process_metrics(
    sample_count: int,
    cpu_total: float,
    cpu_peak: float,
    memory_peak: float,
    session_seconds: int,
) -> list[dict[str, str]]:
    if not sample_count:
        return []
    return [
        {"label": "进程 CPU 平均", "value": f"{cpu_total / sample_count:.1f}%"},
        {"label": "进程 CPU 峰值", "value": f"{cpu_peak:.1f}%"},
        {"label": "进程工作集峰值", "value": f"{memory_peak:.1f} MB"},
        {
            "label": "进程采样",
            "value": _sample_rate_text(sample_count, session_seconds),
        },
    ]


def _airperf_metrics(
    state: Mapping[str, object], session_seconds: int
) -> list[dict[str, object]]:
    raw_metrics = state.get("metrics")
    if not isinstance(raw_metrics, list):
        return []
    result: list[dict[str, object]] = []
    for item in raw_metrics:
        if not isinstance(item, dict):
            continue
        payload = dict(item)
        if payload.get("label") == "AirPerf 采样":
            payload["value"] = _sample_rate_text(
                int(state.get("sampleCount", 0)), session_seconds
            )
        result.append(payload)
    return result


def combine_session_metrics(
    report: Mapping[str, object],
    *,
    session_seconds: int,
    process_sample_count: int,
    process_cpu_total: float,
    process_cpu_peak: float,
    process_memory_peak: float,
    airperf_state: Mapping[str, object],
) -> dict[str, object]:
    """返回不修改输入对象的统一会话报告。"""

    combined = dict(report)
    raw_metrics = combined.get("metrics")
    metrics = list(raw_metrics) if isinstance(raw_metrics, list) else []
    metrics.extend(
        _process_metrics(
            process_sample_count,
            process_cpu_total,
            process_cpu_peak,
            process_memory_peak,
            session_seconds,
        )
    )
    metrics.extend(_airperf_metrics(airperf_state, session_seconds))
    combined["metrics"] = metrics
    return combined


__all__ = ["combine_session_metrics"]
