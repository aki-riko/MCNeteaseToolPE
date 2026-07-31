# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""网易 ModPC 进程发现、Windows 性能采样与官方工具定位。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import time
from typing import Callable, Iterable


MCSTUDIO_ROOT_ENV = "MCNETEASE_MCSTUDIO_ROOT"
TOOL_RELATIVE_PATHS = {
    "tracy": Path("tracy") / "tracy-profiler.exe",
    "airperf": Path("airperf") / "airperf.exe",
}
_MINECRAFT_PROCESS_NAMES = {
    "minecraft.windows.exe",
    "minecraft.windows_beta.exe",
    "minecraftclient.exe",
    "modpc.exe",
}
_MINECRAFT_PROCESS_PARTS = ("minecraft.windows", "minecraftclient", "modpc")
_EXCLUDED_PROCESS_NAMES = {"mcstudio.exe", "mcneteasetoolpe.exe"}


@dataclass(frozen=True)
class ProcessDescriptor:
    """可供用户选择的 Minecraft 进程。"""

    pid: int
    name: str

    @property
    def label(self) -> str:
        return f"{self.name}（PID {self.pid}）"


@dataclass(frozen=True)
class ProcessSample:
    """单次进程性能采样结果。"""

    pid: int
    cpu_percent: float
    working_set_mb: float
    peak_working_set_mb: float


def is_minecraft_process(name: str) -> bool:
    """只收录 ModPC/Minecraft 客户端，不把 MCStudio 自身混入列表。"""

    normalized = name.strip().casefold()
    if not normalized or normalized in _EXCLUDED_PROCESS_NAMES:
        return False
    if normalized in _MINECRAFT_PROCESS_NAMES:
        return True
    return any(part in normalized for part in _MINECRAFT_PROCESS_PARTS)


def mcstudio_root_candidates(
    environment: dict[str, str] | None = None,
) -> list[Path]:
    """按显式配置、PATH、系统程序目录的顺序给出候选安装目录。"""

    env = environment if environment is not None else os.environ
    candidates: list[Path] = []
    configured = env.get(MCSTUDIO_ROOT_ENV, "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())

    executable = shutil.which("MCStudio.exe")
    if executable:
        candidates.append(Path(executable).resolve().parent)

    for variable in ("PROGRAMFILES(X86)", "PROGRAMFILES"):
        root = env.get(variable, "").strip()
        if root:
            candidates.append(Path(root) / "Netease" / "MCStudio")
    return _unique_paths(candidates)


def _unique_paths(paths: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = os.path.normcase(os.path.normpath(str(path)))
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


class PerformanceToolLocator:
    """定位 MCStudio 自带工具，但不复制或修改其安装文件。"""

    def __init__(
        self,
        candidate_provider: Callable[[], list[Path]] | None = None,
    ) -> None:
        self._candidate_provider = candidate_provider or mcstudio_root_candidates

    def discover(self) -> dict[str, object]:
        candidates = self._candidate_provider()
        root = next((path for path in candidates if path.is_dir()), None)
        tools = self._tool_paths(root)
        return {
            "root": str(root) if root else "",
            "configured": bool(os.environ.get(MCSTUDIO_ROOT_ENV, "").strip()),
            "tools": tools,
        }

    @staticmethod
    def _tool_paths(root: Path | None) -> dict[str, dict[str, object]]:
        result: dict[str, dict[str, object]] = {}
        for key, relative_path in TOOL_RELATIVE_PATHS.items():
            path = root / relative_path if root else None
            result[key] = {
                "available": bool(path and path.is_file()),
                "path": str(path) if path else "",
            }
        return result


if os.name == "nt":
    _ULONG_PTR = wintypes.WPARAM
    _SIZE_T = ctypes.c_size_t

    class _PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", _ULONG_PTR),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", _SIZE_T),
            ("WorkingSetSize", _SIZE_T),
            ("QuotaPeakPagedPoolUsage", _SIZE_T),
            ("QuotaPagedPoolUsage", _SIZE_T),
            ("QuotaPeakNonPagedPoolUsage", _SIZE_T),
            ("QuotaNonPagedPoolUsage", _SIZE_T),
            ("PagefileUsage", _SIZE_T),
            ("PeakPagefileUsage", _SIZE_T),
        ]


class WindowsProcessSampler:
    """使用 Win32 API 采样，不引入额外运行时依赖。"""

    _TH32CS_SNAPPROCESS = 0x00000002
    _PROCESS_QUERY_INFORMATION = 0x0400
    _PROCESS_VM_READ = 0x0010
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    _BYTES_PER_MB = 1024 * 1024
    _FILETIME_TICKS_PER_SECOND = 10_000_000

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        logical_processors: int | None = None,
    ) -> None:
        if os.name != "nt":
            raise OSError("进程性能监测仅支持 Windows")
        self._clock = clock
        self._logical_processors = max(1, logical_processors or os.cpu_count() or 1)
        self._previous_cpu: dict[int, tuple[float, float]] = {}
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._psapi = ctypes.WinDLL("psapi", use_last_error=True)
        self._configure_api()

    def _configure_api(self) -> None:
        self._kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        self._kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        self._kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
        self._kernel32.Process32FirstW.restype = wintypes.BOOL
        self._kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
        self._kernel32.Process32NextW.restype = wintypes.BOOL
        self._kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self._kernel32.OpenProcess.restype = wintypes.HANDLE
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._kernel32.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        self._kernel32.GetProcessTimes.restype = wintypes.BOOL
        self._psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_PROCESS_MEMORY_COUNTERS),
            wintypes.DWORD,
        ]
        self._psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

    def list_candidates(self) -> list[ProcessDescriptor]:
        snapshot = self._kernel32.CreateToolhelp32Snapshot(self._TH32CS_SNAPPROCESS, 0)
        if snapshot == self._INVALID_HANDLE_VALUE:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return self._read_snapshot(snapshot)
        finally:
            self._kernel32.CloseHandle(snapshot)

    def _read_snapshot(self, snapshot: int) -> list[ProcessDescriptor]:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        processes: list[ProcessDescriptor] = []
        available = self._kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while available:
            name = entry.szExeFile
            if is_minecraft_process(name):
                processes.append(ProcessDescriptor(int(entry.th32ProcessID), name))
            available = self._kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        return sorted(processes, key=lambda item: (item.name.casefold(), item.pid))

    def reset(self, pid: int | None = None) -> None:
        if pid is None:
            self._previous_cpu.clear()
            return
        self._previous_cpu.pop(pid, None)

    def sample(self, pid: int) -> ProcessSample:
        access = self._PROCESS_QUERY_INFORMATION | self._PROCESS_VM_READ
        handle = self._kernel32.OpenProcess(access, False, pid)
        if not handle:
            raise ProcessLookupError(f"无法打开进程 PID {pid}")
        try:
            cpu_seconds = self._read_cpu_seconds(handle)
            memory = self._read_memory(handle)
        finally:
            self._kernel32.CloseHandle(handle)
        cpu_percent = self._calculate_cpu_percent(pid, cpu_seconds)
        return ProcessSample(pid, cpu_percent, *memory)

    def _read_cpu_seconds(self, handle: int) -> float:
        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        success = self._kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel),
            ctypes.byref(user),
        )
        if not success:
            raise ctypes.WinError(ctypes.get_last_error())
        ticks = _filetime_to_int(kernel) + _filetime_to_int(user)
        return ticks / self._FILETIME_TICKS_PER_SECOND

    def _read_memory(self, handle: int) -> tuple[float, float]:
        counters = _PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        success = self._psapi.GetProcessMemoryInfo(
            handle,
            ctypes.byref(counters),
            counters.cb,
        )
        if not success:
            raise ctypes.WinError(ctypes.get_last_error())
        working_set = counters.WorkingSetSize / self._BYTES_PER_MB
        peak_working_set = counters.PeakWorkingSetSize / self._BYTES_PER_MB
        return working_set, peak_working_set

    def _calculate_cpu_percent(self, pid: int, cpu_seconds: float) -> float:
        now = self._clock()
        previous = self._previous_cpu.get(pid)
        self._previous_cpu[pid] = (now, cpu_seconds)
        if previous is None:
            return 0.0
        elapsed = now - previous[0]
        if elapsed <= 0:
            return 0.0
        used = max(0.0, cpu_seconds - previous[1])
        percent = used / elapsed * 100.0 / self._logical_processors
        return min(100.0, max(0.0, percent))


def _filetime_to_int(value: wintypes.FILETIME) -> int:
    return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)


__all__ = [
    "MCSTUDIO_ROOT_ENV",
    "PerformanceToolLocator",
    "ProcessDescriptor",
    "ProcessSample",
    "TOOL_RELATIVE_PATHS",
    "WindowsProcessSampler",
    "is_minecraft_process",
    "mcstudio_root_candidates",
]
