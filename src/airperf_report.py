# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""AirPerf 指标的统一报告标签与格式化。"""

from __future__ import annotations

from collections.abc import Mapping


REPORT_METRIC_DEFINITIONS = (
    ("systemCpuPercent", "average", "系统 CPU 平均", "{:.1f}%"),
    ("systemCpuPercent", "maximum", "系统 CPU 峰值", "{:.1f}%"),
    ("systemAvailableMemoryMb", "minimum", "系统可用内存最低", "{:.1f} MB"),
    ("processPrivateWorkingSetMb", "maximum", "进程私有内存峰值", "{:.1f} MB"),
    ("gpuUsagePercent", "average", "整机 GPU 平均", "{:.1f}%"),
    ("gpuUsagePercent", "maximum", "整机 GPU 峰值", "{:.1f}%"),
    ("gpuTemperatureC", "maximum", "整机 GPU 温度峰值", "{:.1f} °C"),
    ("gpuMemoryUsedMb", "maximum", "整机显存占用峰值", "{:.1f} MB"),
    ("diskTotalPercent", "maximum", "磁盘累计忙碌峰值", "{:.1f}%"),
    ("ioTotalMbPerSec", "maximum", "进程 IO 峰值", "{:.2f} MB/s"),
    ("frameAverageFps", "average", "平均 FPS", "{:.1f}"),
    ("frameDrawCalls", "average", "平均 DrawCall", "{:.1f}"),
    ("frameTriangleCount", "average", "平均三角面", "{:.0f}"),
    ("frameJankCount", "sum", "卡顿数", "{:.0f}"),
    ("frameBigJankCount", "sum", "严重卡顿数", "{:.0f}"),
    ("frameTimeMaxMs", "maximum", "帧耗时峰值", "{:.2f} ms"),
)


def build_airperf_report_metrics(
    summary: Mapping[str, Mapping[str, object]],
    sample_count: int,
) -> list[dict[str, str]]:
    """把常量空间统计摘要整理进统一报告。"""

    if not sample_count:
        return []
    metrics = [{"label": "AirPerf 采样", "value": str(sample_count)}]
    for key, field, label, template in REPORT_METRIC_DEFINITIONS:
        payload = summary.get(key)
        if isinstance(payload, Mapping) and isinstance(
            payload.get(field), (int, float)
        ):
            metrics.append(
                {"label": f"AirPerf {label}", "value": template.format(payload[field])}
            )
    stutter_count = _summary_number(summary, "frameStutterCount", "sum")
    stutter_duration_ms = _summary_number(
        summary, "frameStutterDurationSumMs", "sum"
    )
    if stutter_count:
        metrics.extend(
            [
                {
                    "label": "AirPerf 本地卡顿次数（含严重）",
                    "value": f"{stutter_count:.0f}",
                },
                {
                    "label": "AirPerf 本地平均卡顿时长",
                    "value": f"{stutter_duration_ms / stutter_count / 1000.0:.3f} 秒",
                },
            ]
        )
    return metrics


def _summary_number(
    summary: Mapping[str, Mapping[str, object]], key: str, field: str
) -> float:
    payload = summary.get(key)
    if not isinstance(payload, Mapping):
        return 0.0
    value = payload.get(field)
    return float(value) if isinstance(value, (int, float)) else 0.0


__all__ = ["REPORT_METRIC_DEFINITIONS", "build_airperf_report_metrics"]
