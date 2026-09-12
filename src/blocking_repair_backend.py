# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""阻塞项修复中心的 Qt/QML 异步适配层。"""

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QObject, Property, Signal, Slot

from .blocking_repair import BlockingRepairService, empty_repair_state


LOGGER = logging.getLogger(__name__)


class BlockingRepairBackend(QObject):
    """仅把状态更新留在主线程，扫描与文件写入全部交给后台任务。"""

    stateChanged = Signal()
    busyChanged = Signal()
    result = Signal("QVariant")

    def __init__(
        self,
        parent: QObject | None = None,
        service: BlockingRepairService | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service or BlockingRepairService()
        self._state = empty_repair_state()
        self._busy = False
        self._task_handle = None

    @Property("QVariantMap", notify=stateChanged)
    def state(self) -> dict[str, object]:
        return self._state

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    @Slot(str)
    def inspect(self, project_dir: str) -> None:
        self._start_task(
            lambda: (self._service.inspect(project_dir), None),
            "检查可自动优化项",
        )

    @Slot(str)
    def applyRepair(self, repair_id: str) -> None:
        root_path = self._state.get("rootPath")
        if not isinstance(root_path, str) or not root_path:
            self._emit_failure("请先完成一次工程检查")
            return
        self._start_task(
            lambda: self._service.apply_and_inspect(root_path, repair_id),
            "执行修复",
        )

    @Slot()
    def reset(self) -> None:
        if self._busy:
            return
        self._state = empty_repair_state()
        self.stateChanged.emit()

    def _start_task(self, operation: Callable[[], object], label: str) -> None:
        if self._busy:
            return
        from prismqml import run_in_pool

        self._set_busy(True)
        try:
            handle = run_in_pool(operation)
        except Exception as error:  # noqa: BLE001 - 调度失败必须反馈至界面
            LOGGER.exception("阻塞项修复后台任务启动失败")
            self._set_busy(False)
            self._emit_failure(f"{label}无法启动:{error}")
            return
        self._task_handle = handle
        handle.succeeded.connect(
            lambda payload, task=handle: self._finish_task(task, payload, label)
        )
        handle.failed.connect(
            lambda failure, task=handle: self._fail_task(task, failure, label)
        )

    def _finish_task(self, handle: object, payload: object, label: str) -> None:
        if handle is not self._task_handle:
            return
        self._task_handle = None
        self._set_busy(False)
        try:
            state, outcome = payload
            if not isinstance(state, dict):
                raise ValueError("后台任务返回了无效状态")
            self._state = state
        except (TypeError, ValueError) as error:
            LOGGER.error("阻塞项修复后台任务结果无效: %s", error)
            self._emit_failure(f"{label}失败:{error}")
            return
        self.stateChanged.emit()
        if outcome is not None:
            self.result.emit(outcome)

    def _fail_task(self, handle: object, failure: object, label: str) -> None:
        if handle is not self._task_handle:
            return
        self._task_handle = None
        self._set_busy(False)
        exception = getattr(failure, "exception", failure)
        LOGGER.error("阻塞项修复后台任务失败: %s", exception, exc_info=True)
        self._emit_failure(f"{label}失败:{exception}")

    def _emit_failure(self, message: str) -> None:
        self._state = {**self._state, "phase": "failed", "message": message}
        self.stateChanged.emit()
        self.result.emit({"success": False, "message": message, "changedPaths": []})

    def _set_busy(self, value: bool) -> None:
        if self._busy == value:
            return
        self._busy = value
        self.busyChanged.emit()


__all__ = ["BlockingRepairBackend"]
