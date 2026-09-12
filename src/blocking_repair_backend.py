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
    canUndoChanged = Signal()
    projectPathChanged = Signal()
    auditResultAdopted = Signal(str)
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
        self._last_undo: dict[str, str] | None = None
        self._project_path = ""

    @Property("QVariantMap", notify=stateChanged)
    def state(self) -> dict[str, object]:
        return self._state

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    @Property(bool, notify=canUndoChanged)
    def canUndo(self) -> bool:
        return self._last_undo is not None

    @Property(str, notify=projectPathChanged)
    def projectPath(self) -> str:
        return self._project_path

    @Slot(str)
    def inspect(self, project_dir: str) -> None:
        self._start_task(
            lambda: (self._service.inspect(project_dir), None),
            "检查可自动优化项",
            project_path=project_dir,
        )

    @Slot(str, list)
    def adoptAuditResult(self, project_dir: str, issues: list[dict[str, object]]) -> None:
        self._start_task(
            lambda: (self._service.inspect_from_audit(project_dir, issues), None),
            "同步工程处理的审核阻塞项",
            project_path=project_dir,
            audit_adoption=True,
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
    def undoLastRemoval(self) -> None:
        root_path = self._state.get("rootPath")
        if not isinstance(root_path, str) or not root_path or self._last_undo is None:
            self._emit_failure("没有可撤销的隔离清理")
            return
        undo = dict(self._last_undo)
        self._start_task(
            lambda: self._service.restore_and_inspect(root_path, undo),
            "撤销清理",
        )

    @Slot()
    def reset(self) -> None:
        if self._busy:
            return
        self._state = empty_repair_state()
        self._set_last_undo(None)
        self._set_project_path("")
        self.stateChanged.emit()

    def _start_task(
        self,
        operation: Callable[[], object],
        label: str,
        *,
        project_path: str = "",
        audit_adoption: bool = False,
    ) -> None:
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
            lambda payload, task=handle: self._finish_task(
                task,
                payload,
                label,
                project_path,
                audit_adoption,
            )
        )
        handle.failed.connect(
            lambda failure, task=handle: self._fail_task(task, failure, label)
        )

    def _finish_task(
        self,
        handle: object,
        payload: object,
        label: str,
        project_path: str,
        audit_adoption: bool,
    ) -> None:
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
        if project_path:
            root_path = state.get("rootPath")
            if isinstance(root_path, str):
                self._set_project_path(root_path)
        self.stateChanged.emit()
        if audit_adoption and self._project_path:
            self.auditResultAdopted.emit(self._project_path)
        if outcome is not None:
            self._update_undo(outcome)
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

    def _update_undo(self, outcome: object) -> None:
        if not isinstance(outcome, dict):
            return
        undo = outcome.get("undo")
        if isinstance(undo, dict) and all(isinstance(value, str) for value in undo.values()):
            self._set_last_undo(dict(undo))
        elif outcome.get("clearUndo") is True:
            self._set_last_undo(None)

    def _set_last_undo(self, value: dict[str, str] | None) -> None:
        had_undo = self._last_undo is not None
        self._last_undo = value
        if had_undo != (value is not None):
            self.canUndoChanged.emit()

    def _set_project_path(self, value: str) -> None:
        if self._project_path == value:
            return
        self._project_path = value
        self.projectPathChanged.emit()

    def _set_busy(self, value: bool) -> None:
        if self._busy == value:
            return
        self._busy = value
        self.busyChanged.emit()


__all__ = ["BlockingRepairBackend"]
