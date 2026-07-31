# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""性能诊断页的 Tracy 采集状态控制器。"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import datetime

from .config import TRACY_CAPTURE_SECONDS, TRACY_PROBE_INTERVAL_MS
from .tracy_analysis import (
    DEFAULT_TOP_ROWS,
    MAX_CAPTURE_SECONDS,
    TracyAnalysisError,
    capture_tracy,
    diff_tracy_captures,
    probe_tracy,
)
from .tracy_report import (
    add_capture_to_session,
    build_capture_report,
    build_comparison_report,
    build_session_report,
    new_session_summary,
)


LOGGER = logging.getLogger(__name__)
MAX_TRACY_CAPTURES = 20
SESSION_CAPTURE_LABEL = "session"


class TracyPerformanceController:
    """管理原生 Tracy 探测、后台采集和基线对比。"""

    def __init__(
        self,
        state_changed: Callable[[], None],
        emit_result: Callable[[bool, str], None],
        probe: Callable[[], dict[str, object]] | None = None,
        capture_runner: Callable[[int, str, int], dict[str, object]] | None = None,
        capture_seconds: int = TRACY_CAPTURE_SECONDS,
        probe_interval_ms: int = TRACY_PROBE_INTERVAL_MS,
    ) -> None:
        self._state_changed = state_changed
        self._emit_result = emit_result
        self._probe = probe or probe_tracy
        self._capture_runner = capture_runner or capture_tracy
        self._capture_seconds = int(capture_seconds)
        self._probe_interval_ms = int(probe_interval_ms)
        self._status = self._empty_status()
        self._status_checked = False
        self._busy = False
        self._task_handle: object | None = None
        self._sequence = 0
        self._captures: dict[str, dict[str, object]] = {}
        self._capture_order: list[str] = []
        self._selected_capture_id = ""
        self._baseline_capture_id = ""
        self._comparison_capture_id = ""
        self._diff: dict[str, object] = {}
        self._report: dict[str, object] = {}
        self._continuous_active = False
        self._stop_requested = False
        self._session_summary = new_session_summary()

    @staticmethod
    def _empty_status() -> dict[str, object]:
        return {
            "address": "",
            "port": 0,
            "reachable": False,
            "binAvailable": False,
            "binDir": "",
            "tools": {},
        }

    @property
    def state(self) -> dict[str, object]:
        return {
            **self._status,
            "statusChecked": self._status_checked,
            "captureSeconds": self._capture_seconds,
            "probeIntervalMs": self._probe_interval_ms,
            "busy": self._busy,
            "continuousActive": self._continuous_active,
            "stopRequested": self._stop_requested,
            "windowsCompleted": int(self._session_summary.get("windows", 0)),
            "captures": self._capture_summaries(),
            "selectedCaptureId": self._selected_capture_id,
            "baselineCaptureId": self._baseline_capture_id,
            "comparisonCaptureId": self._comparison_capture_id,
            "hotspots": self._selected_hotspots(),
            "diff": dict(self._diff),
            "report": dict(self._report),
        }

    @property
    def continuous_active(self) -> bool:
        return self._continuous_active

    def refresh_status(self) -> None:
        try:
            self._status = dict(self._probe())
        except (OSError, TracyAnalysisError, TypeError, ValueError) as error:
            LOGGER.warning("探测原生 Tracy 失败：%s", error)
            self._status = self._empty_status()
            self._status["error"] = str(error)
        self._status_checked = True

    def quick_capture(self) -> None:
        """使用默认参数采集热点；已有首次结果时自动生成前后对比。"""
        label = "after" if self._baseline_capture_id else "before"
        self.capture(self._capture_seconds, "", label)

    def start_continuous(self) -> bool:
        """启动连续 Tracy 窗口，直到显式请求停止。"""
        if self._busy:
            self._emit_result(False, "Tracy 正在采样，请先结束当前任务")
            return False
        self.refresh_status()
        if not self._capture_is_ready():
            return False
        self._session_summary = new_session_summary()
        self._continuous_active = True
        self._stop_requested = False
        self._diff = {}
        self._report = build_session_report(self._session_summary, active=True)
        self._state_changed()
        return self._start_capture_task(
            self._capture_seconds,
            "",
            SESSION_CAPTURE_LABEL,
        )

    def stop_continuous(self) -> bool:
        """在当前窗口完成后停止，避免强杀 Tracy 导致损坏采样。"""
        if not self._continuous_active:
            return False
        if not self._stop_requested:
            self._stop_requested = True
            self._state_changed()
        return True

    def capture(self, seconds: int, name_contains: str, label: str) -> None:
        capture_label = self._validate_capture_request(label)
        if capture_label is None:
            return
        try:
            duration = int(seconds)
        except (TypeError, ValueError) as error:
            LOGGER.warning("Tracy 采样时长无效：%r", seconds)
            self._emit_result(False, f"Tracy 采样时长无效：{error}")
            return
        if duration < 1 or duration > MAX_CAPTURE_SECONDS:
            self._emit_result(
                False,
                f"Tracy 采样时长必须在 1-{MAX_CAPTURE_SECONDS} 秒之间",
            )
            return
        if not self._comparison_window_is_valid(duration, capture_label):
            return
        self.refresh_status()
        if not self._capture_is_ready():
            return
        self._start_capture_task(duration, name_contains.strip(), capture_label)

    def _comparison_window_is_valid(self, duration: int, label: str) -> bool:
        if label != "after":
            return True
        baseline = self._captures.get(self._baseline_capture_id)
        if baseline is None:
            self._emit_result(False, "请先采集基线，再进行复测")
            return False
        if int(baseline.get("seconds", 0)) != duration:
            self._emit_result(False, "复测时长必须与 Tracy 基线相同")
            return False
        return True

    def _validate_capture_request(self, label: str) -> str | None:
        if self._busy:
            self._emit_result(False, "Tracy 正在采样，请等待当前任务结束")
            return None
        normalized = label.strip().casefold()
        if normalized not in {"before", "after"}:
            self._emit_result(False, "Tracy 采样标签必须是 before 或 after")
            return None
        return normalized

    def _capture_is_ready(self) -> bool:
        if not self._status.get("binAvailable"):
            self._state_changed()
            self._emit_result(False, "缺少随包 Tracy CLI，请重新安装或配置 CLI 目录")
            return False
        if not self._status.get("reachable"):
            self._state_changed()
            self._emit_result(False, "未连接到 ModPC 原生 Tracy，请先启动游戏")
            return False
        return True

    def _start_capture_task(
        self, duration: int, name_contains: str, label: str
    ) -> bool:
        from prismqml import run_in_pool

        self._set_busy(True)
        try:
            handle = run_in_pool(
                self._capture_runner,
                duration,
                name_contains,
                DEFAULT_TOP_ROWS,
            )
        except Exception as error:  # noqa: BLE001 - 调度失败必须恢复 UI 状态
            LOGGER.exception("启动 Tracy 后台采样失败")
            message = f"启动 Tracy 采样失败：{error}"
            if label == SESSION_CAPTURE_LABEL:
                self._finish_continuous(False, message)
            else:
                self._set_busy(False)
                self._emit_result(False, message)
            return False
        self._task_handle = handle
        handle.succeeded.connect(
            lambda payload, task=handle, capture_label=label: (
                self._finish_capture(task, payload, capture_label)
            )
        )
        handle.failed.connect(
            lambda failure, task=handle, capture_label=label: self._fail_capture(
                task, failure, capture_label
            )
        )
        return True

    def _set_busy(self, value: bool) -> None:
        if self._busy == value:
            return
        self._busy = value
        self._state_changed()

    def _finish_capture(self, handle: object, payload: object, label: str) -> None:
        if handle is not self._task_handle:
            return
        self._task_handle = None
        capture = self._validated_capture(payload)
        if capture is None:
            LOGGER.error("Tracy 后台采样返回了无效数据：%r", type(payload).__name__)
            message = "Tracy 采样失败：后台返回值不是有效采样数据"
            if label == SESSION_CAPTURE_LABEL:
                self._finish_continuous(False, message)
            else:
                self._set_busy(False)
                self._emit_result(False, message)
            return
        capture = self._store_capture(capture, label)
        if label == SESSION_CAPTURE_LABEL:
            self._finish_continuous_window(capture)
            return
        self._set_busy(False)
        self._emit_capture_result(capture, label)

    def _finish_continuous_window(self, capture: dict[str, object]) -> None:
        add_capture_to_session(self._session_summary, capture)
        if self._stop_requested:
            windows = int(self._session_summary.get("windows", 0))
            self._finish_continuous(True, f"持续监测完成：共 {windows} 个窗口")
            return
        self._report = build_session_report(self._session_summary, active=True)
        self._state_changed()
        self._start_capture_task(
            self._capture_seconds,
            "",
            SESSION_CAPTURE_LABEL,
        )

    def _finish_continuous(self, success: bool, message: str) -> None:
        self._continuous_active = False
        self._stop_requested = False
        self._report = build_session_report(self._session_summary, active=False)
        self._set_busy(False)
        self._emit_result(success, message)

    @staticmethod
    def _validated_capture(payload: object) -> dict[str, object] | None:
        if not isinstance(payload, Mapping):
            return None
        capture = dict(payload)
        try:
            seconds = int(capture.get("seconds", 0))
        except (TypeError, ValueError):
            return None
        if seconds < 1:
            return None
        capture["seconds"] = seconds
        for key in ("rows", "top"):
            rows = capture.get(key)
            if not isinstance(rows, list) or any(
                not isinstance(row, Mapping) for row in rows
            ):
                return None
            capture[key] = [dict(row) for row in rows]
        return capture

    def _store_capture(self, capture: dict[str, object], label: str) -> dict[str, object]:
        self._sequence += 1
        capture_id = f"capture-{self._sequence}"
        capture.update(
            {
                "captureId": capture_id,
                "label": label,
                "capturedAt": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
        self._captures[capture_id] = capture
        self._capture_order.append(capture_id)
        self._trim_captures()
        self._selected_capture_id = capture_id
        if label == "before":
            self._baseline_capture_id = capture_id
            self._diff = {}
            self._report = build_capture_report(capture)
        elif label == "after":
            self._comparison_capture_id = capture_id
            if not self._calculate_diff(
                str(capture.get("filter", "")), emit_error=False
            ):
                self._report = build_capture_report(capture)
        return capture

    def _emit_capture_result(self, capture: dict[str, object], label: str) -> None:
        frames = capture.get("frames")
        zones = capture.get("zones")
        self._emit_result(
            True,
            f"{('首次检测' if label == 'before' else '对比检测')}完成："
            f"{frames if frames is not None else '?'} 帧，"
            f"{zones if zones is not None else '?'} 个区间",
        )

    def _trim_captures(self) -> None:
        removed_reference = False
        while len(self._capture_order) > MAX_TRACY_CAPTURES:
            removed = self._capture_order.pop(0)
            self._captures.pop(removed, None)
            if self._selected_capture_id == removed:
                self._selected_capture_id = ""
            if self._baseline_capture_id == removed:
                self._baseline_capture_id = ""
                removed_reference = True
            if self._comparison_capture_id == removed:
                self._comparison_capture_id = ""
                removed_reference = True
        if removed_reference:
            self._diff = {}

    def _fail_capture(self, handle: object, failure: object, label: str = "") -> None:
        if handle is not self._task_handle:
            return
        self._task_handle = None
        exception = getattr(failure, "exception", failure)
        LOGGER.error("Tracy 后台采样失败：%s", exception)
        message = f"Tracy 采样失败：{exception}"
        if label == SESSION_CAPTURE_LABEL:
            self._finish_continuous(False, message)
        else:
            self._set_busy(False)
            self._emit_result(False, message)

    def select_capture(self, capture_id: str) -> None:
        if not self._capture_exists(capture_id, "Tracy 采样记录已不存在"):
            return
        self._selected_capture_id = capture_id
        self._state_changed()

    def select_baseline(self, capture_id: str) -> None:
        if not self._capture_exists(capture_id, "Tracy 基线记录已不存在"):
            return
        self._baseline_capture_id = capture_id
        self._diff = {}
        self._state_changed()

    def select_comparison(self, capture_id: str) -> None:
        if not self._capture_exists(capture_id, "Tracy 复测记录已不存在"):
            return
        self._comparison_capture_id = capture_id
        self._diff = {}
        self._state_changed()

    def _capture_exists(self, capture_id: str, message: str) -> bool:
        if capture_id in self._captures:
            return True
        self._emit_result(False, message)
        return False

    def compare(self, name_contains: str) -> None:
        if self._calculate_diff(name_contains.strip(), emit_error=True):
            self._state_changed()
            self._emit_result(True, "Tracy 基线与复测对比已更新")

    def _calculate_diff(self, name_contains: str, *, emit_error: bool) -> bool:
        base = self._captures.get(self._baseline_capture_id)
        new = self._captures.get(self._comparison_capture_id)
        if base is None or new is None:
            self._diff = {}
            if emit_error:
                self._emit_result(False, "请先选择 Tracy 基线与复测记录")
            return False
        try:
            self._diff = diff_tracy_captures(
                base,
                new,
                name_contains=name_contains,
                top_n=DEFAULT_TOP_ROWS,
            )
        except TracyAnalysisError as error:
            LOGGER.warning("Tracy 采样对比失败：%s", error)
            self._diff = {}
            if emit_error:
                self._emit_result(False, str(error))
            return False
        self._report = build_comparison_report(new, self._diff)
        return True

    def clear(self) -> None:
        if self._busy:
            self._emit_result(False, "Tracy 正在采样，暂不能清空记录")
            return
        self._captures = {}
        self._capture_order = []
        self._selected_capture_id = ""
        self._baseline_capture_id = ""
        self._comparison_capture_id = ""
        self._diff = {}
        self._report = {}
        self._session_summary = new_session_summary()
        self._state_changed()

    def _capture_summaries(self) -> list[dict[str, object]]:
        return [
            self._capture_summary(self._captures[capture_id])
            for capture_id in reversed(self._capture_order)
            if capture_id in self._captures
        ]

    @staticmethod
    def _capture_summary(capture: dict[str, object]) -> dict[str, object]:
        capture_id = str(capture.get("captureId", ""))
        label = {
            "before": "基线",
            "after": "复测",
            SESSION_CAPTURE_LABEL: "持续",
        }.get(str(capture.get("label", "")), "采样")
        fps = capture.get("averageFps")
        fps_text = f" · {float(fps):.1f} FPS" if isinstance(fps, (int, float)) else ""
        return {
            "id": capture_id,
            "text": f"{label} {capture_id} · {capture.get('seconds', 0)}s{fps_text}",
            "label": capture.get("label", ""),
            "seconds": capture.get("seconds", 0),
            "frames": capture.get("frames"),
            "zones": capture.get("zones"),
            "averageFps": fps,
            "uniqueFunctions": capture.get("uniqueFunctions", 0),
            "matchedFunctions": capture.get("matchedFunctions", 0),
            "filter": capture.get("filter", ""),
        }

    def _selected_hotspots(self) -> list[dict[str, object]]:
        capture = self._captures.get(self._selected_capture_id)
        return list(capture.get("top", [])) if capture else []
