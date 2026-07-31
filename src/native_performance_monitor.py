# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""原生性能会话的后台持续采样与常量空间报告归约。"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import threading
from typing import Callable, Mapping, Protocol

from .config import NATIVE_PERFORMANCE_SAMPLE_INTERVAL_MS
from .native_performance import NativePerformanceSession


LOGGER = logging.getLogger(__name__)


class _SessionLike(Protocol):
    def open(self) -> None: ...

    def sample(self) -> dict[str, float]: ...

    def close(self) -> None: ...


@dataclass
class _MetricStats:
    count: int = 0
    total: float = 0.0
    minimum: float = float("inf")
    maximum: float = float("-inf")
    latest: float = 0.0

    def add(self, value: float) -> None:
        self.count += 1
        self.total += value
        self.minimum = min(self.minimum, value)
        self.maximum = max(self.maximum, value)
        self.latest = value

    def payload(self) -> dict[str, float | int]:
        average = self.total / self.count if self.count else 0.0
        return {
            "count": self.count,
            "average": round(average, 3),
            "minimum": round(self.minimum if self.count else 0.0, 3),
            "maximum": round(self.maximum if self.count else 0.0, 3),
            "latest": round(self.latest, 3),
        }


class NativePerformanceMonitor:
    """后台持续采样原生性能源，并保留常量空间统计。"""

    def __init__(
        self,
        changed: Callable[[], None],
        session_factory: Callable[[Path, int, str], _SessionLike] = NativePerformanceSession,
        interval_ms: int = NATIVE_PERFORMANCE_SAMPLE_INTERVAL_MS,
    ) -> None:
        self._changed = changed
        self._session_factory = session_factory
        self._interval_seconds = interval_ms / 1000.0
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._active = False
        self._status = "idle"
        self._message = ""
        self._sample_count = 0
        self._latest: dict[str, float] = {}
        self._stats: dict[str, _MetricStats] = {}
        self._warnings: list[str] = []

    @property
    def state(self) -> dict[str, object]:
        with self._lock:
            summary = {key: stat.payload() for key, stat in self._stats.items()}
            metrics = build_native_report_metrics(summary, self._sample_count)
            if self._status == "failed":
                metrics.append({"label": "原生采集状态", "value": "采集不可用"})
            if self._warnings:
                metrics.append({"label": "原生采集降级", "value": "；".join(self._warnings)})
            return {
                "active": self._active,
                "status": self._status,
                "message": self._message,
                "sampleCount": self._sample_count,
                "latest": dict(self._latest),
                "summary": summary,
                "metrics": metrics,
                "warnings": list(self._warnings),
            }

    def start(self, mcstudio_root: Path, pid: int, process_name: str) -> bool:
        with self._lock:
            if self._active:
                return False
            self._stop_event = threading.Event()
            self._active = True
            self._status = "starting"
            self._message = "正在启动原生 Windows 性能采集"
            self._sample_count = 0
            self._latest = {}
            self._stats = {}
            self._warnings = []
        arguments = (Path(mcstudio_root), int(pid), process_name, self._stop_event)
        self._thread = threading.Thread(
            target=self._run,
            args=arguments,
            name="native-performance-monitor",
            daemon=True,
        )
        self._thread.start()
        self._changed()
        return True

    def stop(self) -> None:
        with self._lock:
            if not self._active:
                return
            self._status = "stopping"
            self._message = "正在停止原生性能采集"
            self._stop_event.set()
        self._changed()

    def mark_unavailable(self, message: str) -> None:
        self._finish("failed", message)

    def _run(self, root: Path, pid: int, name: str, stop_event: threading.Event) -> None:
        session: _SessionLike | None = None
        try:
            session = self._session_factory(root, pid, name)
            session.open()
            self._set_running(session)
            while not stop_event.wait(self._interval_seconds):
                self._record(session.sample())
        except (OSError, ProcessLookupError, TimeoutError, ValueError) as error:
            LOGGER.warning("原生持续采集结束：%s", error)
            self._finish("failed", f"原生性能采集不可用：{error}")
        except Exception as error:
            LOGGER.exception("原生持续采集发生未预期错误")
            self._finish("failed", f"原生性能采集失败：{error}")
        else:
            self._finish("complete", "原生性能采集已完成")
        finally:
            if session is not None:
                try:
                    session.close()
                except OSError:
                    LOGGER.exception("关闭原生性能采集会话失败")

    def _set_running(self, session: _SessionLike) -> None:
        warnings = [str(item) for item in getattr(session, "warnings", ())]
        with self._lock:
            self._status = "monitoring"
            self._warnings = warnings
            if warnings:
                self._message = "其余原生指标采集中；" + "；".join(warnings)
            else:
                self._message = "Windows、GPU、磁盘、进程与 DirectX 帧指标采集中"
        self._changed()

    def _record(self, sample: dict[str, float]) -> None:
        with self._lock:
            self._latest = dict(sample)
            self._sample_count += 1
            for key, value in sample.items():
                self._stats.setdefault(key, _MetricStats()).add(float(value))
        self._changed()

    def _finish(self, status: str, message: str) -> None:
        with self._lock:
            if status == "complete" and self._warnings:
                message += "；" + "；".join(self._warnings)
            self._active = False
            self._status = status
            self._message = message
        self._changed()


def build_native_report_metrics(
    summary: Mapping[str, Mapping[str, object]],
    sample_count: int,
) -> list[dict[str, str]]:
    """把原生采集摘要整理进统一报告。"""

    if not sample_count:
        return []
    metrics = [{"label": "原生采样", "value": str(sample_count)}]
    definitions = (
        ("systemCpuPercent", "average", "系统 CPU 平均", "{:.1f}%"),
        ("systemCpuPercent", "maximum", "系统 CPU 峰值", "{:.1f}%"),
        ("systemAvailableMemoryMb", "minimum", "系统可用内存最低", "{:.1f} MB"),
        ("processPrivateWorkingSetMb", "maximum", "进程私有内存峰值", "{:.1f} MB"),
        ("gpuUsagePercent", "average", "GPU 平均", "{:.1f}%"),
        ("gpuUsagePercent", "maximum", "GPU 峰值", "{:.1f}%"),
        ("gpuTemperatureC", "maximum", "GPU 温度峰值", "{:.1f} °C"),
        ("gpuMemoryUsedMb", "maximum", "显存占用峰值", "{:.1f} MB"),
        ("diskTotalPercent", "maximum", "磁盘活动峰值", "{:.1f}%"),
        ("ioTotalMbPerSec", "maximum", "进程 IO 峰值", "{:.2f} MB/s"),
        ("frameCount", "maximum", "DirectX 帧数", "{:.0f}"),
        ("frameAverageFps", "average", "DirectX 平均 FPS", "{:.1f}"),
        ("frameP1LowFps", "minimum", "DirectX 1% Low", "{:.1f}"),
        ("frameTimeP99Ms", "maximum", "帧耗时 P99", "{:.2f} ms"),
        ("frameTimeMaxMs", "maximum", "帧耗时峰值", "{:.2f} ms"),
        ("frameJankCount", "maximum", "本地卡顿数", "{:.0f}"),
        ("frameBigJankCount", "maximum", "本地严重卡顿数", "{:.0f}"),
    )
    for key, field, label, template in definitions:
        payload = summary.get(key)
        if isinstance(payload, Mapping) and isinstance(payload.get(field), (int, float)):
            metrics.append({"label": f"原生 {label}", "value": template.format(payload[field])})
    return metrics


__all__ = ["NativePerformanceMonitor", "build_native_report_metrics"]
