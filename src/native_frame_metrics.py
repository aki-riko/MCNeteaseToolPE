# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""进程内加载自研 ETW 采集器并归约 DirectX Present 帧数据。"""

from __future__ import annotations

import ctypes
import math
import os
from pathlib import Path
from statistics import median
from typing import Mapping, Sequence


NATIVE_METRICS_DIR_ENV = "MCNETEASE_NATIVE_METRICS_DIR"
NATIVE_FRAME_DLL = "native_frame_capture.dll"
DEFAULT_FRAME_CAPACITY = 120_000
MAX_FRAME_INTERVAL_MS = 1_000.0


class NativeFrameError(OSError):
    """原生 ETW 帧采集器返回错误。"""


def bundled_native_metrics_dir(environment: Mapping[str, str] | None = None) -> Path:
    values = environment if environment is not None else os.environ
    configured = str(values.get(NATIVE_METRICS_DIR_ENV, "")).strip()
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[1] / "native_bin"


def _percentile(sorted_values: Sequence[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    position = (len(sorted_values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(sorted_values[lower])
    weight = position - lower
    return float(sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight)


def summarize_frame_intervals(
    intervals_ms: Sequence[float],
    present_calls_ms: Sequence[float],
) -> dict[str, float]:
    """把一批 Present 间隔归约为 FPS、尾延迟和本地卡顿指标。"""

    intervals = sorted(
        float(value)
        for value in intervals_ms
        if 0.0 < float(value) <= MAX_FRAME_INTERVAL_MS
    )
    if not intervals:
        return {}
    average_ms = sum(intervals) / len(intervals)
    middle = median(intervals)
    jank_threshold = max(1000.0 / 30.0, middle * 2.0)
    big_jank_threshold = max(100.0, middle * 3.0)
    calls = [float(value) for value in present_calls_ms if float(value) >= 0.0]
    return {
        "frameWindowCount": float(len(intervals)),
        "frameAverageFps": round(1000.0 / average_ms, 4),
        "frameP1LowFps": round(1000.0 / _percentile(intervals, 0.99), 4),
        "frameTimeAverageMs": round(average_ms, 4),
        "frameTimeP95Ms": round(_percentile(intervals, 0.95), 4),
        "frameTimeP99Ms": round(_percentile(intervals, 0.99), 4),
        "frameTimeMaxMs": round(intervals[-1], 4),
        "frameJankWindowCount": float(sum(value > jank_threshold for value in intervals)),
        "frameBigJankWindowCount": float(sum(value > big_jank_threshold for value in intervals)),
        "presentCallAverageMs": round(sum(calls) / len(calls), 4) if calls else 0.0,
    }


class NativeFrameMetrics:
    """通过同进程 DLL 直接消费 DXGI/D3D9 ETW Present 事件。"""

    def __init__(
        self,
        environment: Mapping[str, str] | None = None,
        capacity: int = DEFAULT_FRAME_CAPACITY,
    ) -> None:
        self._directory = bundled_native_metrics_dir(environment)
        self._capacity = max(1, int(capacity))
        self._library: object | None = None
        self._last_timestamp = -1.0
        self._total_frames = 0
        self._total_janks = 0
        self._total_big_janks = 0

    def open(self, pid: int) -> None:
        path = self._directory / NATIVE_FRAME_DLL
        if not path.is_file():
            raise NativeFrameError(f"缺少原生帧采集器：{path}")
        library = ctypes.CDLL(str(path))
        self._configure(library)
        status = library.StartNativeFrameCapture(int(pid), self._capacity)
        if status:
            raise NativeFrameError(f"启动 DirectX ETW 帧采集失败（Windows {status}）")
        self._library = library

    @staticmethod
    def _configure(library: object) -> None:
        library.StartNativeFrameCapture.argtypes = [ctypes.c_ulong, ctypes.c_ulong]
        library.StartNativeFrameCapture.restype = ctypes.c_ulong
        library.StopNativeFrameCapture.argtypes = []
        library.StopNativeFrameCapture.restype = ctypes.c_ulong
        library.GetNativeFrameCount.argtypes = [ctypes.POINTER(ctypes.c_ulong)]
        library.GetNativeFrameCount.restype = ctypes.c_ulong
        library.GetNativeFrameData.argtypes = [
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_ulong),
        ]
        library.GetNativeFrameData.restype = ctypes.c_ulong

    def sample(self) -> dict[str, float]:
        if self._library is None:
            raise NativeFrameError("原生帧采集会话尚未打开")
        count = ctypes.c_ulong()
        status = self._library.GetNativeFrameCount(ctypes.byref(count))
        if status:
            raise NativeFrameError(f"读取 ETW 帧数量失败（Windows {status}）")
        if count.value == 0:
            return self._cumulative_payload()
        size = min(count.value, self._capacity)
        timestamps = (ctypes.c_double * size)()
        intervals = (ctypes.c_double * size)()
        calls = (ctypes.c_double * size)()
        returned = ctypes.c_ulong()
        status = self._library.GetNativeFrameData(
            size,
            timestamps,
            intervals,
            calls,
            ctypes.byref(returned),
        )
        if status:
            raise NativeFrameError(f"读取 ETW 帧数据失败（Windows {status}）")
        new_indices = [
            index
            for index in range(returned.value)
            if timestamps[index] > self._last_timestamp
        ]
        if not new_indices:
            return self._cumulative_payload()
        self._last_timestamp = timestamps[new_indices[-1]]
        summary = summarize_frame_intervals(
            [intervals[index] for index in new_indices],
            [calls[index] for index in new_indices],
        )
        self._total_frames += int(summary.get("frameWindowCount", 0.0))
        self._total_janks += int(summary.pop("frameJankWindowCount", 0.0))
        self._total_big_janks += int(summary.pop("frameBigJankWindowCount", 0.0))
        summary.update(self._cumulative_payload())
        return summary

    def _cumulative_payload(self) -> dict[str, float]:
        return {
            "frameCount": float(self._total_frames),
            "frameJankCount": float(self._total_janks),
            "frameBigJankCount": float(self._total_big_janks),
        }

    def close(self) -> None:
        if self._library is not None:
            status = self._library.StopNativeFrameCapture()
            self._library = None
            if status:
                raise NativeFrameError(f"停止 DirectX ETW 帧采集失败（Windows {status}）")


__all__ = [
    "NativeFrameError",
    "NativeFrameMetrics",
    "bundled_native_metrics_dir",
    "summarize_frame_intervals",
]
