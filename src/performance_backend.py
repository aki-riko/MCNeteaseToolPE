# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""性能诊断页面的 Qt/QML 后端。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Property, QProcess, QTimer, Signal, Slot

from .performance_monitor import (
    MCSTUDIO_ROOT_ENV,
    PerformanceToolLocator,
    ProcessDescriptor,
    ProcessSample,
    WindowsProcessSampler,
)
from .tracy_backend import MAX_TRACY_CAPTURES, TracyPerformanceController


LOGGER = logging.getLogger(__name__)
SAMPLE_INTERVAL_MS = 1000
MAX_HISTORY_SAMPLES = 120

CPU_PROFILE_SNIPPET = """import time
import mod.server.extraServerApi as serverApi

def StartCpuProfile(seconds):
    if not serverApi.StartProfile():
        return False
    fileName = "profile_%d.svg" % int(time.time())
    gameComp = serverApi.GetEngineCompFactory().CreateGame(serverApi.GetLevelId())
    gameComp.AddTimer(seconds, lambda: serverApi.StopProfile(fileName))
    return True
"""

MEMORY_PROFILE_SNIPPET = """import time
import mod.server.extraServerApi as serverApi

def StartMemoryProfile(seconds):
    if not serverApi.StartMemProfile():
        return False
    fileName = "memory_profile_%d.svg" % int(time.time())
    gameComp = serverApi.GetEngineCompFactory().CreateGame(serverApi.GetLevelId())
    gameComp.AddTimer(seconds, lambda: serverApi.StopMemProfile(fileName))
    return True
"""

PROFILE_SNIPPETS = {
    "cpu": CPU_PROFILE_SNIPPET,
    "memory": MEMORY_PROFILE_SNIPPET,
}


def _default_launcher(executable: Path) -> bool:
    launched, _pid = QProcess.startDetached(
        str(executable),
        [],
        str(executable.parent),
    )
    return bool(launched)


def _default_clipboard_setter(text: str) -> None:
    from PySide6.QtGui import QGuiApplication

    clipboard = QGuiApplication.clipboard()
    if clipboard is None:
        raise RuntimeError("系统剪贴板不可用")
    clipboard.setText(text)


def _create_default_sampler() -> WindowsProcessSampler | None:
    try:
        return WindowsProcessSampler()
    except OSError:
        LOGGER.warning("当前系统不支持 Windows 进程性能采样", exc_info=True)
        return None


class PerformanceBackend(QObject):
    """桥接官方工具，并采样本机 ModPC 进程的 CPU 与工作集。"""

    stateChanged = Signal()
    result = Signal("QVariant")

    def __init__(
        self,
        parent: QObject | None = None,
        locator: PerformanceToolLocator | None = None,
        sampler: object | None = None,
        launcher: Callable[[Path], bool] | None = None,
        clipboard_setter: Callable[[str], None] | None = None,
        tracy_probe: Callable[[], dict[str, object]] | None = None,
        tracy_capture_runner: (
            Callable[[int, str, int], dict[str, object]] | None
        ) = None,
    ) -> None:
        super().__init__(parent)
        self._locator = locator or PerformanceToolLocator()
        self._sampler = sampler if sampler is not None else _create_default_sampler()
        self._launcher = launcher or _default_launcher
        self._clipboard_setter = clipboard_setter or _default_clipboard_setter
        self._discovery = self._empty_discovery()
        self._processes: list[ProcessDescriptor] = []
        self._selected_pid = 0
        self._monitoring = False
        self._last_sample: ProcessSample | None = None
        self._cpu_history: list[dict[str, object]] = []
        self._memory_history: list[dict[str, object]] = []
        self._sample_number = 0
        self._tracy = TracyPerformanceController(
            self.stateChanged.emit,
            self._emit_result,
            probe=tracy_probe,
            capture_runner=tracy_capture_runner,
        )
        self._timer = QTimer(self)
        self._timer.setInterval(SAMPLE_INTERVAL_MS)
        self._timer.timeout.connect(self._sample_selected_process)

    @staticmethod
    def _empty_discovery() -> dict[str, object]:
        return {
            "root": "",
            "configured": False,
            "tools": {
                "tracy": {"available": False, "path": ""},
                "airperf": {"available": False, "path": ""},
            },
        }

    @Property("QVariantMap", notify=stateChanged)
    def state(self) -> dict[str, object]:
        sample = self._last_sample
        return {
            "mcStudioRoot": self._discovery.get("root", ""),
            "rootConfigured": bool(self._discovery.get("configured", False)),
            "rootEnvironment": MCSTUDIO_ROOT_ENV,
            "tools": self._discovery.get("tools", {}),
            "samplerAvailable": self._sampler is not None,
            "processes": [self._process_payload(item) for item in self._processes],
            "selectedPid": self._selected_pid,
            "monitoring": self._monitoring,
            "cpuPercent": round(sample.cpu_percent, 1) if sample else 0.0,
            "workingSetMb": round(sample.working_set_mb, 1) if sample else 0.0,
            "peakWorkingSetMb": round(sample.peak_working_set_mb, 1) if sample else 0.0,
            "cpuHistory": list(self._cpu_history),
            "memoryHistory": list(self._memory_history),
            "tracy": self._tracy.state,
        }

    @staticmethod
    def _process_payload(process: ProcessDescriptor) -> dict[str, object]:
        return {"pid": process.pid, "name": process.name, "text": process.label}

    @Slot()
    def refresh(self) -> None:
        self._discovery = self._locator.discover()
        self._refresh_processes()
        self._tracy.refresh_status()
        self.stateChanged.emit()

    def _refresh_processes(self, *, report_errors: bool = True) -> None:
        if self._sampler is None:
            self._processes = []
            self._selected_pid = 0
            return
        try:
            processes = self._sampler.list_candidates()
        except OSError as error:
            LOGGER.exception("枚举 Minecraft 进程失败")
            if report_errors:
                self._emit_result(False, f"枚举 Minecraft 进程失败：{error}")
            return
        self._processes = list(processes)
        available_pids = {item.pid for item in self._processes}
        self._reconcile_selected_process(available_pids)

    def _reconcile_selected_process(self, available_pids: set[int]) -> None:
        if self._selected_pid in available_pids:
            return
        if self._monitoring:
            self._stop_monitoring("目标进程已退出，监测已停止", success=False)
        self._selected_pid = self._processes[0].pid if self._processes else 0
        self._last_sample = None

    @Slot(int)
    def selectProcess(self, pid: int) -> None:
        target = int(pid)
        if target == self._selected_pid:
            return
        available_pids = {item.pid for item in self._processes}
        if target not in available_pids:
            self._emit_result(False, f"进程 PID {target} 已不存在")
            return
        if self._monitoring:
            self._stop_monitoring("")
        self._selected_pid = target
        self._last_sample = None
        self.clearHistory()

    @Slot()
    def startMonitoring(self) -> None:
        if self._sampler is None:
            self._emit_result(False, "当前系统不支持 Windows 进程性能采样")
            return
        if not self._selected_pid:
            self._emit_result(False, "请先启动并选择一个 ModPC/Minecraft 进程")
            return
        self._sampler.reset(self._selected_pid)
        self._monitoring = True
        self._timer.start()
        self.stateChanged.emit()
        self._sample_selected_process()

    @Slot()
    def stopMonitoring(self) -> None:
        self._stop_monitoring("监测已停止")

    def _stop_monitoring(self, message: str, *, success: bool = True) -> None:
        self._timer.stop()
        changed = self._monitoring
        self._monitoring = False
        if changed:
            self.stateChanged.emit()
        if message:
            self._emit_result(success, message)

    @Slot()
    def clearHistory(self) -> None:
        self._cpu_history = []
        self._memory_history = []
        self._sample_number = 0
        self.stateChanged.emit()

    def _sample_selected_process(self) -> None:
        if not self._monitoring or self._sampler is None or not self._selected_pid:
            return
        try:
            sample = self._sampler.sample(self._selected_pid)
        except (OSError, ProcessLookupError) as error:
            LOGGER.warning("采样进程 PID %s 失败：%s", self._selected_pid, error)
            self._stop_monitoring(f"目标进程不可用：{error}", success=False)
            self._refresh_processes()
            self.stateChanged.emit()
            return
        self._last_sample = sample
        self._append_sample(sample)
        self.stateChanged.emit()

    def _append_sample(self, sample: ProcessSample) -> None:
        self._sample_number += 1
        label = str(self._sample_number)
        self._cpu_history.append({"label": label, "value": round(sample.cpu_percent, 2)})
        self._memory_history.append({"label": label, "value": round(sample.working_set_mb, 2)})
        self._cpu_history = self._cpu_history[-MAX_HISTORY_SAMPLES:]
        self._memory_history = self._memory_history[-MAX_HISTORY_SAMPLES:]

    @Slot()
    def refreshTracyStatus(self) -> None:
        self._tracy.refresh_status()
        self.stateChanged.emit()

    @Slot()
    def refreshPerformanceTarget(self) -> None:
        """持续刷新 ModPC 进程和 Tracy 状态，自动跟随晚启动或重启。"""
        if not self._monitoring:
            self._refresh_processes(report_errors=False)
        self._tracy.refresh_status()
        self.stateChanged.emit()

    @Slot(int, str, str)
    def captureTracy(self, seconds: int, name_contains: str, label: str) -> None:
        self._tracy.capture(seconds, name_contains, label)

    @Slot()
    def captureTracyQuick(self) -> None:
        self._tracy.quick_capture()

    @Slot(str)
    def selectTracyCapture(self, capture_id: str) -> None:
        self._tracy.select_capture(capture_id)

    @Slot(str)
    def selectTracyBaseline(self, capture_id: str) -> None:
        self._tracy.select_baseline(capture_id)

    @Slot(str)
    def selectTracyComparison(self, capture_id: str) -> None:
        self._tracy.select_comparison(capture_id)

    @Slot(str)
    def compareTracyCaptures(self, name_contains: str) -> None:
        self._tracy.compare(name_contains)

    @Slot()
    def clearTracyCaptures(self) -> None:
        self._tracy.clear()

    @Slot()
    def launchTracy(self) -> None:
        self._launch_tool("tracy", "方块探针（Tracy）")

    @Slot()
    def launchAirPerf(self) -> None:
        self._launch_tool("airperf", "方块易测（AirPerf）")

    def _launch_tool(self, key: str, display_name: str) -> None:
        tool = self._discovery.get("tools", {}).get(key, {})
        path = Path(str(tool.get("path", ""))) if tool.get("path") else None
        if not path or not tool.get("available") or not path.is_file():
            self._emit_result(False, f"未找到 {display_name}，请安装 MCStudio 或配置 {MCSTUDIO_ROOT_ENV}")
            return
        try:
            launched = self._launcher(path)
        except OSError as error:
            LOGGER.exception("启动官方性能工具失败：%s", path)
            self._emit_result(False, f"启动 {display_name} 失败：{error}")
            return
        self._emit_result(launched, f"已启动 {display_name}" if launched else f"启动 {display_name} 失败")

    @Slot(str)
    def copyProfileSnippet(self, kind: str) -> None:
        snippet = PROFILE_SNIPPETS.get(kind)
        if snippet is None:
            self._emit_result(False, "未知的性能分析脚本类型")
            return
        try:
            self._clipboard_setter(snippet)
        except (OSError, RuntimeError) as error:
            LOGGER.exception("复制性能分析脚本失败")
            self._emit_result(False, f"复制失败：{error}")
            return
        label = "CPU" if kind == "cpu" else "内存"
        self._emit_result(True, f"已复制服务端 {label} 分析脚本")

    def _emit_result(self, success: bool, message: str) -> None:
        self.result.emit({"success": success, "message": message})


__all__ = [
    "CPU_PROFILE_SNIPPET",
    "MAX_HISTORY_SAMPLES",
    "MAX_TRACY_CAPTURES",
    "MEMORY_PROFILE_SNIPPET",
    "PROFILE_SNIPPETS",
    "PerformanceBackend",
    "SAMPLE_INTERVAL_MS",
]
