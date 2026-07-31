# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""基于 Windows PDH 的系统、磁盘与目标进程指标采集。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import logging
import os
from pathlib import Path
from typing import Callable, Protocol


LOGGER = logging.getLogger(__name__)

PDH_FMT_LONG = 0x00000100
PDH_FMT_DOUBLE = 0x00000200
PDH_CSTATUS_VALID_DATA = 0x00000000
PDH_CSTATUS_NEW_DATA = 0x00000001


class PdhError(OSError):
    """PDH 返回非成功状态。"""

    def __init__(self, operation: str, status: int) -> None:
        self.status = int(status) & 0xFFFFFFFF
        super().__init__(f"{operation} 失败（PDH 0x{self.status:08X}）")


class _PdhFormattedValueUnion(ctypes.Union):
    _fields_ = [
        ("longValue", wintypes.LONG),
        ("doubleValue", ctypes.c_double),
        ("largeValue", ctypes.c_longlong),
        ("ansiStringValue", ctypes.c_char_p),
        ("wideStringValue", wintypes.LPWSTR),
    ]


class _PdhFormattedValue(ctypes.Structure):
    _anonymous_ = ("value",)
    _fields_ = [("CStatus", wintypes.DWORD), ("value", _PdhFormattedValueUnion)]


class QueryLike(Protocol):
    def add_counter(self, path: str) -> object: ...

    def collect(self) -> None: ...

    def value(self, counter: object, format_flags: int = PDH_FMT_DOUBLE) -> float: ...

    def close(self) -> None: ...


class PdhQuery:
    """一个只使用英文计数器路径的 PDH 查询。"""

    def __init__(self, library: object | None = None) -> None:
        if os.name != "nt":
            raise OSError("Windows PDH 仅支持 Windows")
        self._pdh = library or ctypes.WinDLL("pdh.dll", use_last_error=True)
        self._configure_functions()
        self._query = wintypes.HANDLE()
        self._check("PdhOpenQueryW", self._pdh.PdhOpenQueryW(None, 0, ctypes.byref(self._query)))

    def _configure_functions(self) -> None:
        self._pdh.PdhOpenQueryW.argtypes = [wintypes.LPCWSTR, ctypes.c_size_t, ctypes.POINTER(wintypes.HANDLE)]
        self._pdh.PdhOpenQueryW.restype = wintypes.LONG
        self._pdh.PdhAddEnglishCounterW.argtypes = [
            wintypes.HANDLE,
            wintypes.LPCWSTR,
            ctypes.c_size_t,
            ctypes.POINTER(wintypes.HANDLE),
        ]
        self._pdh.PdhAddEnglishCounterW.restype = wintypes.LONG
        self._pdh.PdhCollectQueryData.argtypes = [wintypes.HANDLE]
        self._pdh.PdhCollectQueryData.restype = wintypes.LONG
        self._pdh.PdhGetFormattedCounterValue.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(_PdhFormattedValue),
        ]
        self._pdh.PdhGetFormattedCounterValue.restype = wintypes.LONG
        self._pdh.PdhCloseQuery.argtypes = [wintypes.HANDLE]
        self._pdh.PdhCloseQuery.restype = wintypes.LONG

    @staticmethod
    def _check(operation: str, status: int) -> None:
        if int(status) & 0xFFFFFFFF:
            raise PdhError(operation, status)

    def add_counter(self, path: str) -> wintypes.HANDLE:
        counter = wintypes.HANDLE()
        status = self._pdh.PdhAddEnglishCounterW(self._query, path, 0, ctypes.byref(counter))
        self._check(f"PdhAddEnglishCounterW({path})", status)
        return counter

    def collect(self) -> None:
        self._check("PdhCollectQueryData", self._pdh.PdhCollectQueryData(self._query))

    def value(self, counter: object, format_flags: int = PDH_FMT_DOUBLE) -> float:
        counter_type = wintypes.DWORD()
        formatted = _PdhFormattedValue()
        status = self._pdh.PdhGetFormattedCounterValue(
            counter,
            format_flags,
            ctypes.byref(counter_type),
            ctypes.byref(formatted),
        )
        self._check("PdhGetFormattedCounterValue", status)
        if formatted.CStatus not in (PDH_CSTATUS_VALID_DATA, PDH_CSTATUS_NEW_DATA):
            raise PdhError("PDH 计数器数据状态", formatted.CStatus)
        if format_flags & PDH_FMT_LONG:
            return float(formatted.longValue)
        return float(formatted.doubleValue)

    def close(self) -> None:
        if self._query:
            status = self._pdh.PdhCloseQuery(self._query)
            self._query = wintypes.HANDLE()
            self._check("PdhCloseQuery", status)


@dataclass(frozen=True)
class _MetricDefinition:
    key: str
    path: str
    divisor: float = 1.0


SYSTEM_METRICS = (
    _MetricDefinition("systemCpuPercent", r"\Processor(_Total)\% Processor Time"),
    _MetricDefinition("systemAvailableMemoryMb", r"\Memory\Available MBytes"),
    _MetricDefinition("diskReadPercent", r"\PhysicalDisk(_Total)\% Disk Read Time"),
    _MetricDefinition("diskWritePercent", r"\PhysicalDisk(_Total)\% Disk Write Time"),
    _MetricDefinition("diskTotalPercent", r"\PhysicalDisk(_Total)\% Disk Time"),
)

PROCESS_METRICS = (
    _MetricDefinition("processCpuPercent", r"\Process({instance})\% Processor Time"),
    _MetricDefinition("processPrivateWorkingSetMb", r"\Process({instance})\Working Set - Private", 1_048_576),
    _MetricDefinition("processWorkingSetMb", r"\Process({instance})\Working Set", 1_048_576),
    _MetricDefinition("ioReadOperationsPerSec", r"\Process({instance})\IO Read Operations/sec"),
    _MetricDefinition("ioWriteOperationsPerSec", r"\Process({instance})\IO Write Operations/sec"),
    _MetricDefinition("ioTotalOperationsPerSec", r"\Process({instance})\IO Data Operations/sec"),
    _MetricDefinition("ioReadMbPerSec", r"\Process({instance})\IO Read Bytes/sec", 1_048_576),
    _MetricDefinition("ioWriteMbPerSec", r"\Process({instance})\IO Write Bytes/sec", 1_048_576),
    _MetricDefinition("ioTotalMbPerSec", r"\Process({instance})\IO Data Bytes/sec", 1_048_576),
)


class NativeWindowsMetrics:
    """AirPerf 等价的 Windows 系统、磁盘和进程计数器集合。"""

    def __init__(
        self,
        query_factory: Callable[[], QueryLike] = PdhQuery,
        processor_count: int | None = None,
    ) -> None:
        self._query_factory = query_factory
        self._processor_count = max(1, processor_count or os.cpu_count() or 1)
        self._query: QueryLike | None = None
        self._counters: dict[str, tuple[object, float]] = {}

    def open(self, pid: int, process_name: str) -> None:
        instance = self._resolve_process_instance(int(pid), Path(process_name).stem)
        query = self._query_factory()
        counters: dict[str, tuple[object, float]] = {}
        for definition in (*SYSTEM_METRICS, *PROCESS_METRICS):
            path = definition.path.format(instance=instance)
            divisor = self._processor_count if definition.key == "processCpuPercent" else definition.divisor
            try:
                counters[definition.key] = (query.add_counter(path), float(divisor))
            except PdhError as error:
                LOGGER.info("原生 Windows 指标不可用 %s：%s", definition.key, error)
        if not counters:
            query.close()
            raise OSError("Windows PDH 没有可用性能计数器")
        query.collect()
        self._query = query
        self._counters = counters

    def _resolve_process_instance(self, pid: int, process_name: str) -> str:
        for index in range(128):
            instance = process_name if index == 0 else f"{process_name}#{index}"
            query = self._query_factory()
            try:
                counter = query.add_counter(rf"\Process({instance})\ID Process")
                query.collect()
                if int(query.value(counter, PDH_FMT_LONG)) == pid:
                    return instance
            except PdhError:
                pass
            finally:
                query.close()
        raise ProcessLookupError(f"Windows PDH 未找到 PID {pid} 对应的 {process_name} 实例")

    def sample(self) -> dict[str, float]:
        if self._query is None:
            raise OSError("原生 Windows 指标会话尚未打开")
        self._query.collect()
        result: dict[str, float] = {}
        for key, (counter, divisor) in self._counters.items():
            try:
                result[key] = round(self._query.value(counter) / divisor, 4)
            except PdhError as error:
                LOGGER.debug("读取原生 Windows 指标失败 %s：%s", key, error)
        return result

    def close(self) -> None:
        if self._query is not None:
            self._query.close()
            self._query = None
        self._counters = {}


__all__ = [
    "NativeWindowsMetrics",
    "PdhError",
    "PdhQuery",
    "PROCESS_METRICS",
    "SYSTEM_METRICS",
]
