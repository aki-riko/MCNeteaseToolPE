# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""完全独立的 Windows/GPU 性能指标测试。"""

from __future__ import annotations

from pathlib import Path

from src.native_gpu_metrics import GpuMetricsError
from src.native_performance import NativePerformanceSession
from src.native_windows_metrics import NativeWindowsMetrics, PDH_FMT_LONG


class _FakeQuery:
    def __init__(self, values: dict[str, float]) -> None:
        self.values = values
        self.closed = False
        self.collect_count = 0

    def add_counter(self, path: str) -> str:
        return path

    def collect(self) -> None:
        self.collect_count += 1

    def value(self, counter: object, format_flags: int = 0) -> float:
        path = str(counter)
        if format_flags & PDH_FMT_LONG:
            if "(ModPC#1)" in path:
                return 4242
            return 100
        return self.values.get(path, 1.0)

    def close(self) -> None:
        self.closed = True


def test_native_windows_metrics_resolves_pid_and_converts_values() -> None:
    values = {
        r"\Processor(_Total)\% Processor Time": 52.0,
        r"\Process(ModPC#1)\% Processor Time": 80.0,
        r"\Process(ModPC#1)\Working Set - Private": 20 * 1_048_576,
        r"\Process(ModPC#1)\IO Data Bytes/sec": 2 * 1_048_576,
    }
    queries: list[_FakeQuery] = []

    def query_factory() -> _FakeQuery:
        query = _FakeQuery(values)
        queries.append(query)
        return query

    metrics = NativeWindowsMetrics(query_factory=query_factory, processor_count=8)
    metrics.open(4242, "ModPC.exe")
    sample = metrics.sample()
    metrics.close()

    assert sample["systemCpuPercent"] == 52.0
    assert sample["processCpuPercent"] == 10.0
    assert sample["processPrivateWorkingSetMb"] == 20.0
    assert sample["ioTotalMbPerSec"] == 2.0
    assert queries[-1].closed is True


class _FakeWindows:
    def __init__(self) -> None:
        self.opened: tuple[int, str] | None = None
        self.closed = False

    def open(self, pid: int, name: str) -> None:
        self.opened = (pid, name)

    def sample(self) -> dict[str, float]:
        return {"systemCpuPercent": 25.0}

    def close(self) -> None:
        self.closed = True


class _FakeGpu:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.closed = False

    def open(self) -> None:
        if self.fail:
            raise GpuMetricsError("无 NVIDIA GPU")

    def sample(self) -> dict[str, float]:
        return {"gpuUsagePercent": 75.0, "gpuBusPercent": 12.0}

    def close(self) -> None:
        self.closed = True


def test_native_session_merges_windows_and_driver_metrics() -> None:
    windows = _FakeWindows()
    gpu = _FakeGpu()
    session = NativePerformanceSession(
        Path("ignored"),
        4242,
        "ModPC.exe",
        windows_factory=lambda: windows,  # type: ignore[arg-type]
        gpu_factory=lambda: gpu,  # type: ignore[arg-type]
    )
    session.open()

    assert session.sample() == {
        "systemCpuPercent": 25.0,
        "gpuUsagePercent": 75.0,
        "gpuBusPercent": 12.0,
    }
    session.close()
    assert windows.opened == (4242, "ModPC.exe")
    assert windows.closed is True
    assert gpu.closed is True


def test_native_session_keeps_windows_metrics_when_gpu_is_unavailable() -> None:
    windows = _FakeWindows()
    session = NativePerformanceSession(
        Path("ignored"),
        4242,
        "ModPC.exe",
        windows_factory=lambda: windows,  # type: ignore[arg-type]
        gpu_factory=lambda: _FakeGpu(fail=True),  # type: ignore[arg-type]
    )
    session.open()

    assert session.sample() == {"systemCpuPercent": 25.0}
    session.close()
