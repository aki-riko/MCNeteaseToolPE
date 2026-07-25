# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""网易 Minecraft 全局清理的 Qt/QML 异步适配层。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Property, Signal, Slot

from .minecraft_cleanup_backend import MinecraftCleanupService, _empty_state
from .minecraft_cleanup_definitions import (
    MC_CLEANUP_MSG_FOLDER_MISSING,
    MC_CLEANUP_MSG_FOLDER_OPENED,
    MC_CLEANUP_MSG_FOLDER_OPEN_FAILED,
    MC_CLEANUP_MSG_TASK_FAILED,
)


LOGGER = logging.getLogger(__name__)


class MinecraftCleanupBackend(QObject):
    """向 QML 暴露异步扫描、清理与目录定位能力。"""

    stateChanged = Signal()
    result = Signal("QVariant")
    busyChanged = Signal()

    def __init__(
        self,
        parent: QObject | None = None,
        service: MinecraftCleanupService | None = None,
        folder_opener: Callable[[Path], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service or MinecraftCleanupService()
        self._folder_opener = folder_opener or self._open_local_folder
        self._state = _empty_state()
        self._busy = False
        self._task_handle = None

    @Property("QVariantMap", notify=stateChanged)
    def state(self) -> dict[str, object]:
        return self._state

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    @Slot()
    def refresh(self) -> None:
        self._start_task(self._service.scan, clean_task=False)

    @Slot(str)
    def clean(self, key: str) -> None:
        self._start_task(lambda: self._service.clean_and_scan(key), clean_task=True)

    @Slot()
    def cleanAll(self) -> None:
        self._start_task(lambda: self._service.clean_and_scan(), clean_task=True)

    @Slot(str)
    def openFolder(self, key: str) -> None:
        try:
            folder = self._service.folder_for(key)
        except (OSError, RuntimeError, ValueError) as error:
            LOGGER.warning("[Minecraft 清理] 无法解析清理目录：%s", error)
            self.result.emit(self._service._result(False, str(error)))
            return
        if not folder.is_dir():
            self._emit_folder_result(False, MC_CLEANUP_MSG_FOLDER_MISSING, folder)
            return
        self._open_folder(folder)

    def _open_folder(self, folder: Path) -> None:
        try:
            opened = self._folder_opener(folder)
        except Exception as error:  # noqa: BLE001 - 桌面打开器失败必须反馈而不能崩溃
            LOGGER.exception("[Minecraft 清理] 打开清理目录失败：%s", folder)
            message = f"{MC_CLEANUP_MSG_FOLDER_OPEN_FAILED.format(folder)}：{error}"
            self.result.emit(self._service._result(False, message))
            return
        template = MC_CLEANUP_MSG_FOLDER_OPENED if opened else MC_CLEANUP_MSG_FOLDER_OPEN_FAILED
        self._emit_folder_result(opened, template, folder)

    def _emit_folder_result(self, success: bool, template: str, folder: Path) -> None:
        self.result.emit(self._service._result(success, template.format(folder)))

    @staticmethod
    def _open_local_folder(folder: Path) -> bool:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _start_task(self, operation: Callable[[], object], clean_task: bool) -> None:
        if self._busy:
            return
        from prismqml import run_in_pool

        self._set_busy(True)
        try:
            handle = run_in_pool(operation)
        except Exception as error:
            LOGGER.exception("[Minecraft 清理] 启动后台任务失败")
            self._set_busy(False)
            self.result.emit(self._service._result(False, f"{MC_CLEANUP_MSG_TASK_FAILED} {error}"))
            return
        self._task_handle = handle
        handle.succeeded.connect(
            lambda payload, task=handle: self._finish_task(task, payload, clean_task)
        )
        handle.failed.connect(lambda failure, task=handle: self._fail_task(task, failure))

    def _finish_task(self, handle: object, payload: object, clean_task: bool) -> None:
        if handle is not self._task_handle:
            return
        self._task_handle = None
        self._set_busy(False)
        if clean_task:
            result, state = payload
            self._state = state
            self.stateChanged.emit()
            self.result.emit(result)
            return
        self._state = payload
        self.stateChanged.emit()

    def _fail_task(self, handle: object, failure: object) -> None:
        if handle is not self._task_handle:
            return
        self._task_handle = None
        self._set_busy(False)
        exception = getattr(failure, "exception", failure)
        LOGGER.error("[Minecraft 清理] 后台任务失败：%s", exception)
        self.result.emit(self._service._result(False, MC_CLEANUP_MSG_TASK_FAILED))

    def _set_busy(self, value: bool) -> None:
        if self._busy == value:
            return
        self._busy = value
        self.busyChanged.emit()


__all__ = ["MinecraftCleanupBackend"]
