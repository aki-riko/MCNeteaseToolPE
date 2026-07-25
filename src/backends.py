# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
# 工程处理后端兼容导出与一键流程编排。
# Compatibility exports and the one-click project workflow coordinator.

"""Compatibility exports plus the one-click project workflow coordinator."""

import logging
import os
from pathlib import Path
import sys
from typing import Callable

from PySide6.QtCore import QObject, Property, QProcess, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

from .audit_backend import AuditBackend
from .cleanup_backend import CleanupBackend
from .package_backend import PackageBackend
from .project_structure import classify_project
from .settings_backend import ApplicationSettingsBackend
from .uuid_backend import UuidBackend


LOGGER = logging.getLogger(__name__)

# 快速且无子进度的清理、UUID 阶段只占小区间；逐文件审核占主区间。
CLEANUP_PROGRESS_END = 5
AUDIT_PROGRESS_END = 70
UUID_PROGRESS_END = 75
PIPELINE_PROGRESS_END = 100


class ProjectBackend(QObject):
    """Run cleanup, audit, UUID rewrite, and automatic ZIP packaging."""

    logMessage = Signal(str, str)
    busyChanged = Signal()
    phaseChanged = Signal()
    statusChanged = Signal()
    progressChanged = Signal()
    archivePathChanged = Signal()
    recentProjectPathChanged = Signal()
    finished = Signal(bool, int, int, list, str)

    def __init__(
        self,
        parent: QObject | None = None,
        uuid_backend: UuidBackend | None = None,
        cleanup_backend: CleanupBackend | None = None,
        audit_backend: AuditBackend | None = None,
        package_backend: PackageBackend | None = None,
        file_revealer: Callable[[Path], bool] | None = None,
        settings_backend: ApplicationSettingsBackend | None = None,
    ) -> None:
        super().__init__(parent)
        self._uuid_backend = uuid_backend or UuidBackend(self)
        self._cleanup_backend = cleanup_backend or CleanupBackend(self)
        self._audit_backend = audit_backend or AuditBackend(self)
        self._package_backend = package_backend or PackageBackend(self)
        for child in (
            self._uuid_backend,
            self._cleanup_backend,
            self._audit_backend,
            self._package_backend,
        ):
            if child.parent() is None:
                child.setParent(self)
        self._busy = False
        self._phase = "idle"
        self._status = "选择工程目录后即可开始"
        self._progress = 0
        self._project_dir = ""
        self._archive_path = ""
        self._file_revealer = file_revealer or self._reveal_local_file
        self._settings_backend = settings_backend
        if self._settings_backend is not None:
            self._settings_backend.recentProjectPathChanged.connect(
                self.recentProjectPathChanged
            )
        self._audit_errors = 0
        self._audit_warnings = 0
        self._audit_issues: list[dict[str, object]] = []
        self._connect_backends()

    def _connect_backends(self) -> None:
        self._uuid_backend.logMessage.connect(self._relay_log)
        self._cleanup_backend.logMessage.connect(self._relay_log)
        self._audit_backend.logMessage.connect(self._relay_log)
        self._uuid_backend.finished.connect(self._on_uuid_finished)
        self._cleanup_backend.finished.connect(self._on_cleanup_finished)
        self._audit_backend.progress.connect(self._on_audit_progress)
        self._audit_backend.taskFailed.connect(self._on_audit_task_failed)
        self._audit_backend.finished.connect(self._on_audit_finished)
        self._package_backend.logMessage.connect(self._relay_log)
        self._package_backend.progress.connect(self._on_package_progress)
        self._package_backend.taskFailed.connect(self._on_package_task_failed)
        self._package_backend.finished.connect(self._on_package_finished)

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    @Property(str, notify=phaseChanged)
    def phase(self) -> str:
        return self._phase

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        return self._status

    @Property(float, notify=progressChanged)
    def progress(self) -> float:
        return self._progress

    @Property(str, notify=archivePathChanged)
    def archivePath(self) -> str:
        return self._archive_path

    @Property(str, notify=recentProjectPathChanged)
    def recentProjectPath(self) -> str:
        if self._settings_backend is None:
            return ""
        return self._settings_backend.recentProjectPath

    @Property("QVariantList", notify=recentProjectPathChanged)
    def savedProjectPaths(self) -> list[str]:
        if self._settings_backend is None:
            return []
        return self._settings_backend.savedProjectPaths

    @Property(QObject, constant=True)
    def uuidBackend(self) -> QObject:
        return self._uuid_backend

    @Property(QObject, constant=True)
    def cleanupBackend(self) -> QObject:
        return self._cleanup_backend

    @Property(QObject, constant=True)
    def auditBackend(self) -> QObject:
        return self._audit_backend

    @Property(QObject, constant=True)
    def packageBackend(self) -> QObject:
        return self._package_backend

    @Slot(str, result=str)
    def classifyProject(self, project_dir: str) -> str:
        return classify_project(project_dir)

    @Slot(str, result=bool)
    def rememberProjectPath(self, project_dir: str) -> bool:
        if self._settings_backend is None:
            return False
        return self._settings_backend.rememberProjectPath(project_dir)

    @Slot(result=bool)
    def revealArchive(self) -> bool:
        """Open the archive folder and select the generated ZIP file."""

        archive = Path(self._archive_path)
        if not self._archive_path or not archive.is_file():
            message = "ZIP 文件不存在，无法在文件夹中定位"
            LOGGER.warning("%s：%s", message, self._archive_path or "<empty>")
            self.logMessage.emit(message, "error")
            return False
        try:
            opened = self._file_revealer(archive)
        except Exception as error:  # noqa: BLE001 - 桌面启动失败必须反馈而不能崩溃
            LOGGER.exception("打开 ZIP 所在文件夹失败：%s", archive)
            self.logMessage.emit(f"无法打开 ZIP 所在文件夹：{error}", "error")
            return False
        if not opened:
            message = f"无法在文件夹中定位 ZIP：{archive}"
            LOGGER.error(message)
            self.logMessage.emit(message, "error")
        return opened

    @staticmethod
    def _reveal_local_file(archive: Path) -> bool:
        if sys.platform == "win32":
            opened, _process_id = QProcess.startDetached(
                "explorer.exe",
                ["/select,", os.path.normpath(str(archive))],
            )
            return opened
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(archive.parent)))

    def _set_busy(self, value: bool) -> None:
        if self._busy == value:
            return
        self._busy = value
        self.busyChanged.emit()

    def _set_archive_path(self, archive_path: str) -> None:
        if self._archive_path == archive_path:
            return
        self._archive_path = archive_path
        self.archivePathChanged.emit()

    def _set_state(self, phase: str, status: str, progress: float) -> None:
        progress = max(0, min(progress, PIPELINE_PROGRESS_END))
        if self._phase != phase:
            self._phase = phase
            self.phaseChanged.emit()
        if self._status != status:
            self._status = status
            self.statusChanged.emit()
        if self._progress != progress:
            self._progress = progress
            self.progressChanged.emit()

    @Slot(str)
    def run(self, project_dir: str) -> None:
        if self._busy:
            self.logMessage.emit("一键处理正在执行，请勿重复启动", "warn")
            return
        self._set_archive_path("")
        root = os.path.abspath(os.path.realpath(project_dir)) if project_dir else ""
        if not root or not os.path.isdir(root):
            self._set_state("failed", "请选择有效的工程目录", 0)
            self.logMessage.emit(self._status, "error")
            self.finished.emit(False, 0, 0, [], self._status)
            return
        self._project_dir = root
        self._audit_errors = 0
        self._audit_warnings = 0
        self._audit_issues = []
        self._set_busy(True)
        self._set_state("cleanup", "第 1/4 步：正在清理垃圾", 0)
        self.logMessage.emit("开始一键处理：垃圾清理 → 打包审核 → UUID 重写 → 自动 ZIP", "info")
        self._cleanup_backend.clean(root)

    @Slot()
    def reset(self) -> None:
        if self._busy:
            self.logMessage.emit("任务执行期间不能重置状态", "warn")
            return
        self._project_dir = ""
        self._set_archive_path("")
        self._audit_errors = 0
        self._audit_warnings = 0
        self._audit_issues = []
        self._set_state("idle", "选择工程目录后即可开始", 0)

    @Slot(str, str)
    def _relay_log(self, text: str, level: str) -> None:
        self.logMessage.emit(text, level)

    @Slot(bool, int, str)
    def _on_uuid_finished(self, success: bool, changed: int, message: str) -> None:
        if not self._busy or self._phase != "uuid":
            LOGGER.warning("忽略非当前流程的 UUID 完成信号:%s", message)
            return
        if not success:
            self._fail(message)
            return
        self.logMessage.emit(f"UUID 重写完成：更新 {changed} 个 manifest", "success")
        self._set_state(
            "package",
            "第 4/4 步：正在自动输出 ZIP 压缩包",
            UUID_PROGRESS_END,
        )
        self._package_backend.package(self._project_dir)

    @Slot(bool, int, "qint64", str)
    def _on_cleanup_finished(self, success: bool, removed: int, freed: int, message: str) -> None:
        if not self._busy or self._phase != "cleanup":
            LOGGER.warning("忽略非当前流程的清理完成信号:%s", message)
            return
        if not success:
            self._fail(message)
            return
        self.logMessage.emit(f"垃圾清理完成：移除 {removed} 项，释放 {freed} 字节", "success")
        self._set_state(
            "audit",
            "第 2/4 步：正在准备打包审核",
            CLEANUP_PROGRESS_END,
        )
        self._audit_backend.audit(self._project_dir)

    @Slot(int, int, str)
    def _on_audit_progress(self, current: int, total: int, status: str) -> None:
        if not self._busy or self._phase != "audit":
            return
        audit_range = AUDIT_PROGRESS_END - CLEANUP_PROGRESS_END
        audit_progress = (current / total) * audit_range if total > 0 else 0
        self._set_state(
            "audit",
            f"第 2/4 步：{status}",
            CLEANUP_PROGRESS_END + audit_progress,
        )

    @Slot(str)
    def _on_audit_task_failed(self, message: str) -> None:
        if self._busy and self._phase == "audit":
            self._fail(message)

    @Slot(bool, int, int, list)
    def _on_audit_finished(
        self,
        passed: bool,
        errors: int,
        warnings: int,
        issues: list[dict[str, object]],
    ) -> None:
        if not self._busy or self._phase != "audit":
            return
        self._audit_errors = errors
        self._audit_warnings = warnings
        self._audit_issues = list(issues)
        if passed:
            self.logMessage.emit(
                f"审核通过：{warnings} 条警告，开始重写 UUID",
                "success",
            )
            self._set_state(
                "uuid",
                "第 3/4 步：正在重写 UUID",
                AUDIT_PROGRESS_END,
            )
            self._uuid_backend.generate(self._project_dir)
            return
        status = (
            f"处理完成：审核未通过，{errors} 个错误、{warnings} 个警告"
        )
        self._set_state("done", status, PIPELINE_PROGRESS_END)
        self._set_busy(False)
        self.logMessage.emit(status, "error")
        self.finished.emit(passed, errors, warnings, issues, status)

    @Slot(int, int)
    def _on_package_progress(self, current: int, total: int) -> None:
        if not self._busy or self._phase != "package":
            return
        package_range = PIPELINE_PROGRESS_END - UUID_PROGRESS_END
        package_progress = (current / total) * package_range if total > 0 else 0
        self._set_state(
            "package",
            "第 4/4 步：正在自动输出 ZIP 压缩包",
            UUID_PROGRESS_END + package_progress,
        )

    @Slot(str)
    def _on_package_task_failed(self, message: str) -> None:
        if self._busy and self._phase == "package":
            self._fail(message)

    @Slot(bool, str, int, "qint64")
    def _on_package_finished(
        self,
        success: bool,
        archive_path: str,
        file_count: int,
        size_bytes: int,
    ) -> None:
        if not self._busy or self._phase != "package":
            return
        if not success:
            self._fail("ZIP 打包失败，请查看处理记录")
            return
        self._set_archive_path(os.path.abspath(os.path.realpath(archive_path)))
        status = f"全部完成：审核通过，ZIP 已输出到 {self._archive_path}"
        self._set_state("done", status, PIPELINE_PROGRESS_END)
        self._set_busy(False)
        self.logMessage.emit(status, "success")
        self.finished.emit(
            True,
            self._audit_errors,
            self._audit_warnings,
            self._audit_issues,
            status,
        )

    def _fail(self, message: str) -> None:
        self._set_state("failed", message, self._progress)
        self._set_busy(False)
        self.logMessage.emit(message, "error")
        self.finished.emit(False, 0, 0, [], message)


__all__ = [
    "ProjectBackend",
    "UuidBackend",
    "CleanupBackend",
    "AuditBackend",
    "PackageBackend",
]
