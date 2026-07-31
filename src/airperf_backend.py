# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""AirPerf Win 指标采集与持续汇总。"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
from typing import Callable, Mapping, Protocol

from .airperf_protocol import AirPerfProtocol, AirPerfProtocolError
from .airperf_runtime import (
    AIRPERF_SERVICE_NAME,
    APHOST_PORTS,
    extract_aphost_runtime,
    find_airperf_libzmq,
    process_architecture,
)
from .config import (
    AIRPERF_GRAPHICS_ENABLED,
    AIRPERF_HOST,
    AIRPERF_RPC_TIMEOUT_MS,
    AIRPERF_SAMPLE_INTERVAL_MS,
    AIRPERF_START_TIMEOUT_MS,
)
from .airperf_graphics import AirPerfGraphicsAccumulator


LOGGER = logging.getLogger(__name__)


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
            "sum": round(self.total, 3),
            "average": round(average, 3),
            "minimum": round(self.minimum if self.count else 0.0, 3),
            "maximum": round(self.maximum if self.count else 0.0, 3),
            "latest": round(self.latest, 3),
        }


@dataclass(frozen=True)
class _CounterSpec:
    key: str
    category: str
    counter: str
    instance: str
    divisor: float = 1.0


SYSTEM_COUNTERS = (
    _CounterSpec("systemCpuPercent", "Processor", "% Processor Time", "_Total"),
    _CounterSpec("systemAvailableMemoryMb", "Memory", "Available MBytes", ""),
    _CounterSpec("gpuTemperatureC", "GPU_Counters", "Temperature-GPU_Core", "GPU_Instance"),
    _CounterSpec("gpuFrequencyMhz", "GPU_Counters", "Clock-GPU_Core", "GPU_Instance"),
    _CounterSpec("gpuUsagePercent", "GPU_Counters", "Load-GPU_Core", "GPU_Instance"),
    _CounterSpec("gpuFrameBufferPercent", "GPU_Counters", "Load-GPU_Frame_Buffer", "GPU_Instance"),
    _CounterSpec("gpuVideoEnginePercent", "GPU_Counters", "Load-GPU_Video_Engine", "GPU_Instance"),
    _CounterSpec("gpuBusPercent", "GPU_Counters", "Load-GPU_Bus_Interface", "GPU_Instance"),
    _CounterSpec("gpuMemoryUsedMb", "GPU_Counters", "SmallData-GPU_Memory_Used", "GPU_Instance"),
    _CounterSpec("diskReadPercent", "PhysicalDisk", "% Disk Read Time", "_Total"),
    _CounterSpec("diskWritePercent", "PhysicalDisk", "% Disk Write Time", "_Total"),
    _CounterSpec("diskTotalPercent", "PhysicalDisk", "% Disk Time", "_Total"),
)
PROCESS_COUNTERS = (
    _CounterSpec("processCpuPercent", "Process", "% Processor Time", "{process}"),
    _CounterSpec("processPrivateWorkingSetMb", "Process", "Working Set - Private", "{process}", 1_048_576),
    _CounterSpec("processWorkingSetMb", "Process", "Working Set", "{process}", 1_048_576),
    _CounterSpec("ioReadOperationsPerSec", "Process", "IO Read Operations/sec", "{process}"),
    _CounterSpec("ioWriteOperationsPerSec", "Process", "IO Write Operations/sec", "{process}"),
    _CounterSpec("ioTotalOperationsPerSec", "Process", "IO Data Operations/sec", "{process}"),
    _CounterSpec("ioReadMbPerSec", "Process", "IO Read Bytes/sec", "{process}", 1_048_576),
    _CounterSpec("ioWriteMbPerSec", "Process", "IO Write Bytes/sec", "{process}", 1_048_576),
    _CounterSpec("ioTotalMbPerSec", "Process", "IO Data Bytes/sec", "{process}", 1_048_576),
)


def _port_is_open(host: str, port: int) -> bool:
    try:
        connection = socket.create_connection((host, port), timeout=0.2)
    except OSError:
        return False
    connection.close()
    return True


class _ProtocolLike(Protocol):
    def check_init_done(self) -> bool: ...

    def get_counter(self, category: str) -> dict[str, object]: ...

    def get_data(self, category: str, counter: str, instance: str, host: str = "") -> object: ...

    def hook_process(self, pid: int) -> bool: ...

    def get_directx_data(self, pid: int) -> list[dict[str, object]]: ...

    def remove_counter(self, key: str) -> object: ...

    def close(self) -> None: ...


class AirPerfSession:
    """一个目标进程对应的 aphost 会话。"""

    def __init__(
        self,
        mcstudio_root: Path,
        pid: int,
        process_name: str,
        environment: Mapping[str, str] | None = None,
        architecture_provider: Callable[[int], str] = process_architecture,
        protocol_factory: Callable[..., _ProtocolLike] = AirPerfProtocol,
    ) -> None:
        self._root = Path(mcstudio_root)
        self._pid = int(pid)
        self._process_name = Path(process_name).stem
        self._environment = environment if environment is not None else os.environ
        self._architecture_provider = architecture_provider
        self._protocol_factory = protocol_factory
        self._protocol: _ProtocolLike | None = None
        self._host_process: subprocess.Popen[bytes] | None = None
        self._owns_host = False
        self._host_port = 0
        self._process_instance = ""
        self._active_specs: list[_CounterSpec] = []
        self._graphics = AirPerfGraphicsAccumulator()
        self._graphics_active = False
        self._graphics_samples: tuple[dict[str, float], ...] = ()
        self._warnings: list[str] = []

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(self._warnings)

    @property
    def graphics_samples(self) -> tuple[dict[str, float], ...]:
        return self._graphics_samples

    def open(self) -> None:
        architecture = self._architecture_provider(self._pid)
        service = self._root / "airperf" / AIRPERF_SERVICE_NAME
        executable = extract_aphost_runtime(service, architecture, self._environment)
        dll_path = find_airperf_libzmq(self._root / "airperf")
        if AIRPERF_HOST.casefold() not in {"localhost", "127.0.0.1"}:
            raise AirPerfProtocolError("AirPerf aphost 只允许连接本机回环地址")
        port = APHOST_PORTS[architecture]
        self._host_port = port
        endpoint = f"tcp://{AIRPERF_HOST}:{port}"
        self._protocol = self._protocol_factory(
            dll_path=dll_path,
            endpoint=endpoint,
            timeout_ms=AIRPERF_RPC_TIMEOUT_MS,
        )
        if not _port_is_open(AIRPERF_HOST, port):
            self._start_host(executable)
        self._wait_until_ready()
        self._process_instance = self._resolve_process_instance()
        self._active_specs = self._resolved_specs()
        self._prime_counters()
        self._start_graphics_capture()

    def _start_graphics_capture(self) -> None:
        if not AIRPERF_GRAPHICS_ENABLED or self._protocol is None:
            return
        try:
            if not self._protocol.hook_process(self._pid):
                raise AirPerfProtocolError("aphost 未能挂接目标进程")
            self._protocol.get_directx_data(self._pid)
        except (AirPerfProtocolError, OSError, TimeoutError) as error:
            message = f"DirectX：{error}"
            LOGGER.info("AirPerf %s", message)
            self._warnings.append(message)
            return
        self._graphics_active = True

    def _host_ready(self) -> bool:
        try:
            return bool(self._protocol and self._protocol.check_init_done())
        except (AirPerfProtocolError, TimeoutError, OSError):
            return False

    def _start_host(self, executable: Path) -> None:
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._host_process = subprocess.Popen(
            [str(executable)],
            cwd=str(executable.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
        self._owns_host = True

    def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + AIRPERF_START_TIMEOUT_MS / 1000.0
        while time.monotonic() < deadline:
            if self._host_process and self._host_process.poll() is not None:
                raise AirPerfProtocolError("aphost 在初始化完成前退出")
            if self._host_ready():
                return
            time.sleep(0.15)
        raise TimeoutError("等待 aphost 初始化超时")

    def _resolve_process_instance(self) -> str:
        if self._protocol is None:
            raise AirPerfProtocolError("aphost 会话尚未建立")
        process_data = self._protocol.get_counter("Process").get("Process", {})
        instances = process_data.get("Instances", []) if isinstance(process_data, dict) else []
        prefix = self._process_name.casefold()
        candidates = [str(item) for item in instances if str(item).casefold().startswith(prefix)]
        for instance in candidates:
            value = self._protocol.get_data("Process", "ID Process", instance)
            if int(float(value)) == self._pid:
                return instance
        raise ProcessLookupError(f"aphost 未找到 PID {self._pid} 对应的 {self._process_name} 计数器实例")

    def _resolved_specs(self) -> list[_CounterSpec]:
        processors = max(1, os.cpu_count() or 1)
        specs = list(SYSTEM_COUNTERS)
        for spec in PROCESS_COUNTERS:
            divisor = float(processors) if spec.key == "processCpuPercent" else spec.divisor
            specs.append(_CounterSpec(spec.key, spec.category, spec.counter, self._process_instance, divisor))
        return specs

    def _prime_counters(self) -> None:
        enabled: list[_CounterSpec] = []
        if self._protocol is None:
            return
        for spec in self._active_specs:
            try:
                self._protocol.get_data(spec.category, spec.counter, spec.instance)
            except (AirPerfProtocolError, TimeoutError, OSError) as error:
                LOGGER.info("AirPerf 指标不可用 %s：%s", spec.key, error)
            else:
                enabled.append(spec)
        self._active_specs = enabled

    def sample(self) -> dict[str, float]:
        if self._protocol is None:
            raise AirPerfProtocolError("aphost 会话尚未建立")
        self._graphics_samples = ()
        sample: dict[str, float] = {}
        for spec in self._active_specs:
            value = self._protocol.get_data(spec.category, spec.counter, spec.instance)
            if isinstance(value, (int, float)):
                sample[spec.key] = round(float(value) / spec.divisor, 4)
        if self._graphics_active:
            try:
                frame_samples = self._graphics.feed_all(
                    self._protocol.get_directx_data(self._pid)
                )
                self._graphics_samples = tuple(frame_samples)
                if frame_samples:
                    sample.update(frame_samples[-1])
            except (AirPerfProtocolError, OSError, TimeoutError) as error:
                self._graphics_active = False
                message = f"DirectX：{error}"
                LOGGER.warning("AirPerf 帧采集降级：%s", error)
                self._warnings.append(message)
        return sample

    def close(self) -> None:
        if not self._owns_host and _port_is_open(AIRPERF_HOST, self._host_port):
            self._remove_active_counters()
        if self._protocol is not None:
            self._protocol.close()
            self._protocol = None
        if self._owns_host and self._host_process and self._host_process.poll() is None:
            self._host_process.terminate()
            try:
                self._host_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._host_process.kill()
        self._host_process = None
        self._owns_host = False

    def _remove_active_counters(self) -> None:
        if self._protocol is None:
            return
        for spec in self._active_specs:
            key = f"::{spec.category}::{spec.counter}::{spec.instance}"
            try:
                self._protocol.remove_counter(key)
            except (AirPerfProtocolError, TimeoutError, OSError) as error:
                LOGGER.debug("移除 AirPerf 计数器失败 %s：%s", key, error)


class AirPerfMonitor:
    """后台持续采样逆向还原的 AirPerf 指标并保留常量空间摘要。"""

    def __init__(
        self,
        changed: Callable[[], None],
        session_factory: Callable[[Path, int, str], object] | None = None,
        interval_ms: int = AIRPERF_SAMPLE_INTERVAL_MS,
    ) -> None:
        self._changed = changed
        if session_factory is None:
            session_factory = AirPerfSession
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
            metrics = build_airperf_report_metrics(summary, self._sample_count)
            if self._status == "failed":
                metrics.append({"label": "AirPerf 状态", "value": "采集不可用"})
            if self._warnings:
                metrics.append({"label": "AirPerf 降级", "value": "；".join(self._warnings)})
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
            if self._active or (self._thread is not None and self._thread.is_alive()):
                return False
            self._stop_event = threading.Event()
            self._active = True
            self._status = "starting"
            self._message = "正在启动 AirPerf 兼容采集"
            self._sample_count = 0
            self._latest = {}
            self._stats = {}
            self._warnings = []
        arguments = (Path(mcstudio_root), int(pid), process_name, self._stop_event)
        self._thread = threading.Thread(target=self._run, args=arguments, name="airperf-monitor", daemon=True)
        self._thread.start()
        self._changed()
        return True

    def stop(self) -> None:
        with self._lock:
            if not self._active:
                return
            self._active = False
            self._status = "stopping"
            self._message = "正在停止 AirPerf 兼容采集"
            self._stop_event.set()
        self._changed()

    def mark_unavailable(self, message: str) -> None:
        self._finish("failed", message)

    def _run(self, root: Path, pid: int, name: str, stop_event: threading.Event) -> None:
        session: object | None = None
        try:
            session = self._session_factory(root, pid, name)
            session.open()  # type: ignore[attr-defined]
            self._set_running(session)
            while not stop_event.wait(self._interval_seconds):
                sample = session.sample()  # type: ignore[attr-defined]
                self._sync_session_warnings(session)
                raw_frame_samples = getattr(session, "graphics_samples", ())
                frame_samples = [
                    item for item in raw_frame_samples if isinstance(item, Mapping)
                ]
                self._record(sample, frame_samples)
        except (AirPerfProtocolError, OSError, ProcessLookupError, TimeoutError, ValueError) as error:
            LOGGER.warning("AirPerf 持续采集结束：%s", error)
            self._finish("failed", f"AirPerf 兼容采集不可用：{error}")
        except Exception as error:
            LOGGER.exception("AirPerf 持续采集发生未预期错误")
            self._finish("failed", f"AirPerf 兼容采集失败：{error}")
        else:
            self._finish("complete", "AirPerf 兼容采集已完成")
        finally:
            if session is not None:
                try:
                    session.close()  # type: ignore[attr-defined]
                except (AirPerfProtocolError, OSError, TimeoutError):
                    LOGGER.exception("关闭 AirPerf 采集会话失败")

    def _set_running(self, session: object | None = None) -> None:
        warnings = [str(item) for item in getattr(session, "warnings", ())]
        with self._lock:
            self._status = "monitoring"
            self._warnings = warnings
            self._message = "AirPerf 系统、GPU、磁盘、进程与 DirectX 指标采集中"
            if warnings:
                self._message = "AirPerf 其余指标采集中；" + "；".join(warnings)
        self._changed()

    def _record(
        self,
        sample: dict[str, float],
        frame_samples: list[Mapping[str, object]] | None = None,
    ) -> None:
        completed_frames = frame_samples or []
        with self._lock:
            self._latest = dict(sample)
            self._sample_count += 1
            for key, value in sample.items():
                if completed_frames and key.startswith("frame"):
                    continue
                self._stats.setdefault(key, _MetricStats()).add(float(value))
            for frame_sample in completed_frames:
                for key, value in frame_sample.items():
                    if isinstance(value, (int, float)):
                        self._stats.setdefault(key, _MetricStats()).add(float(value))
        self._changed()

    def _sync_session_warnings(self, session: object) -> None:
        warnings = [str(item) for item in getattr(session, "warnings", ())]
        with self._lock:
            if warnings == self._warnings:
                return
            self._warnings = warnings
            self._message = "AirPerf 其余指标采集中；" + "；".join(warnings)

    def _finish(self, status: str, message: str) -> None:
        with self._lock:
            self._active = False
            self._status = status
            self._message = message
        self._changed()


REPORT_METRIC_DEFINITIONS = (
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
    return metrics


__all__ = [
    "AIRPERF_SERVICE_NAME",
    "APHOST_PORTS",
    "AirPerfGraphicsAccumulator",
    "AirPerfMonitor",
    "AirPerfSession",
    "build_airperf_report_metrics",
    "extract_aphost_runtime",
    "find_airperf_libzmq",
    "process_architecture",
]
