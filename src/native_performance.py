# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""完全独立于 AirPerf 运行时的聚合性能采集会话。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Protocol

from .native_frame_metrics import NativeFrameError, NativeFrameMetrics
from .native_gpu_metrics import GpuMetricsError, NvidiaGpuMetrics
from .native_windows_metrics import NativeWindowsMetrics


LOGGER = logging.getLogger(__name__)


class _MetricSource(Protocol):
    def sample(self) -> dict[str, float]: ...

    def close(self) -> None: ...


class NativePerformanceSession:
    """合并 PDH 和 GPU 驱动指标，保持原统一报告的数据形状。"""

    def __init__(
        self,
        _mcstudio_root: Path,
        pid: int,
        process_name: str,
        windows_factory: Callable[[], NativeWindowsMetrics] = NativeWindowsMetrics,
        gpu_factory: Callable[[], NvidiaGpuMetrics] = NvidiaGpuMetrics,
        frame_factory: Callable[[], NativeFrameMetrics] = NativeFrameMetrics,
    ) -> None:
        self._pid = int(pid)
        self._process_name = process_name
        self._windows_factory = windows_factory
        self._gpu_factory = gpu_factory
        self._frame_factory = frame_factory
        self._sources: list[_MetricSource] = []
        self._warnings: list[str] = []

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(self._warnings)

    def open(self) -> None:
        self._warnings = []
        windows = self._windows_factory()
        windows.open(self._pid, self._process_name)
        self._sources = [windows]
        try:
            gpu = self._gpu_factory()
            gpu.open()
        except (GpuMetricsError, OSError) as error:
            LOGGER.info("原生 GPU 指标不可用，继续采集 Windows 指标：%s", error)
            self._warnings.append(f"GPU：{error}")
        else:
            self._sources.append(gpu)
        try:
            frames = self._frame_factory()
            frames.open(self._pid)
        except (NativeFrameError, OSError) as error:
            LOGGER.info("原生 DirectX 帧指标不可用，继续采集其他指标：%s", error)
            self._warnings.append(f"DirectX ETW：{error}")
        else:
            self._sources.append(frames)

    def sample(self) -> dict[str, float]:
        if not self._sources:
            raise OSError("原生性能采集会话尚未打开")
        result: dict[str, float] = {}
        for source in self._sources:
            try:
                result.update(source.sample())
            except (GpuMetricsError, NativeFrameError, OSError) as error:
                LOGGER.warning("原生性能指标源采样失败：%s", error)
        if not result:
            raise OSError("本次原生性能采样没有返回任何指标")
        return result

    def close(self) -> None:
        errors: list[OSError] = []
        for source in reversed(self._sources):
            try:
                source.close()
            except OSError as error:
                LOGGER.exception("关闭原生性能指标源失败")
                errors.append(error)
        self._sources = []
        if errors:
            raise errors[0]


__all__ = ["NativePerformanceSession"]
