# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
# 审核通过后的 ZIP 打包后端。

"""Create a distributable ZIP beside the selected Minecraft project."""

from __future__ import annotations

from collections.abc import Callable
import logging
import os
from pathlib import Path
import tempfile
from typing import NamedTuple
import zipfile

from PySide6.QtCore import QObject, Property, Signal, Slot

from prismqml import current_task, run_in_thread

from .config import ZIP_COMPRESSION_LEVEL
from .pack_scanner import _collect_pack_dirs
from .project_structure import is_map_project


LOGGER = logging.getLogger(__name__)


class ArchiveResult(NamedTuple):
    """Details of a successfully created archive."""

    archive_path: str
    file_count: int
    size_bytes: int


ProgressCallback = Callable[[int, int], None]


def _walk_entries(
    root: Path,
    source_dir: Path,
    excluded_files: frozenset[Path] = frozenset(),
) -> tuple[list[tuple[Path, str]], int]:
    entries: list[tuple[Path, str]] = []
    file_count = 0
    for current, directories, names in os.walk(source_dir, topdown=True, followlinks=False):
        current_path = Path(current)
        directories[:] = sorted(
            name for name in directories if not (current_path / name).is_symlink()
        )
        if current_path != root:
            entries.append((current_path, current_path.relative_to(root).as_posix() + "/"))
        for name in sorted(names):
            path = current_path / name
            if path.is_symlink() or not path.is_file() or path.resolve() in excluded_files:
                continue
            entries.append((path, path.relative_to(root).as_posix()))
            file_count += 1
    return entries, file_count


def _pack_entries(
    root: Path,
    excluded_files: frozenset[Path] = frozenset(),
) -> tuple[list[tuple[Path, str]], int, list[Path]]:
    """Return a complete map or manifest-bearing Add-on archive entry list."""

    if is_map_project(root):
        entries, file_count = _walk_entries(root, root, excluded_files)
        return entries, file_count, []

    entries: list[tuple[Path, str]] = []
    file_count = 0
    discovered = [
        Path(path).resolve()
        for path in sorted(_collect_pack_dirs(str(root)), key=str.casefold)
    ]
    if not discovered:
        raise ValueError("工程内未找到含 manifest.json 的组件包")
    pack_dirs: list[Path] = []
    for candidate in sorted(discovered, key=lambda path: (len(path.parts), str(path).casefold())):
        if any(parent == candidate or parent in candidate.parents for parent in pack_dirs):
            continue
        pack_dirs.append(candidate)

    for pack_dir in pack_dirs:
        pack_entries, pack_file_count = _walk_entries(root, pack_dir, excluded_files)
        entries.extend(pack_entries)
        file_count += pack_file_count
    return entries, file_count, pack_dirs


def _temporary_archive_path(archive: Path) -> str:
    with tempfile.NamedTemporaryFile(
        mode="wb",
        prefix=f".{archive.stem}.",
        suffix=".tmp",
        dir=archive.parent,
        delete=False,
    ) as temporary:
        return temporary.name


def _remove_temporary_archive(path: str) -> None:
    if not path:
        return
    try:
        os.unlink(path)
    except FileNotFoundError:
        LOGGER.debug("ZIP 临时文件已不存在:%s", path)


def _write_archive(
    archive: Path,
    entries: list[tuple[Path, str]],
    progress: ProgressCallback | None,
) -> int:
    temporary_path = _temporary_archive_path(archive)
    try:
        with zipfile.ZipFile(
            temporary_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=ZIP_COMPRESSION_LEVEL,
        ) as bundle:
            for index, (path, member_name) in enumerate(entries, start=1):
                bundle.write(path, member_name)
                if progress is not None:
                    progress(index, len(entries))
        os.replace(temporary_path, archive)
        temporary_path = ""
        return archive.stat().st_size
    finally:
        _remove_temporary_archive(temporary_path)


def create_zip_archive(
    project_dir: str,
    output_path: str | None = None,
    progress: ProgressCallback | None = None,
) -> ArchiveResult:
    """Create an atomic ZIP; maps retain all world data, Add-ons retain only packs."""

    root = Path(project_dir).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"工程目录无效:{project_dir}")

    archive = (
        Path(output_path).expanduser().resolve()
        if output_path
        else root / f"{root.name}.zip"
    )
    archive.parent.mkdir(parents=True, exist_ok=True)

    entries, file_count, pack_dirs = _pack_entries(root, frozenset({archive}))
    if any(archive == pack or pack in archive.parents for pack in pack_dirs):
        raise ValueError("ZIP 输出路径不能位于组件包目录内")
    total = max(1, len(entries))
    if progress is not None:
        progress(0, total)

    size_bytes = _write_archive(archive, entries, progress)
    return ArchiveResult(str(archive), file_count, size_bytes)


def _create_zip_task(project_dir: str) -> ArchiveResult:
    """Create one archive through PrismQML's managed task context."""

    task = current_task()

    def report_progress(current: int, total: int) -> None:
        task.raise_if_cancelled()
        task.report_progress((current, total))

    return create_zip_archive(project_dir, progress=report_progress)


class PackageBackend(QObject):
    """Run ZIP compression off the UI thread after a passed audit."""

    logMessage = Signal(str, str)
    progress = Signal(int, int)
    taskFailed = Signal(str)
    busyChanged = Signal()
    finished = Signal(bool, str, int, "qint64")

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._busy = False
        self._task_handle = None

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    def _set_busy(self, value: bool) -> None:
        if self._busy == value:
            return
        self._busy = value
        self.busyChanged.emit()

    @Slot(str)
    def package(self, project_dir: str) -> None:
        if self._busy or self._task_handle is not None:
            self.logMessage.emit("ZIP 打包正在执行，请稍候", "warn")
            return
        self._set_busy(True)
        self.logMessage.emit("审核通过，开始自动输出 ZIP 压缩包", "info")
        try:
            handle = run_in_thread(_create_zip_task, project_dir)
        except Exception as error:  # noqa: BLE001 - task startup failure must settle the UI
            LOGGER.exception("ZIP 后台任务启动失败:%s", project_dir)
            self._finish_failed(f"ZIP 打包失败:{error}")
            return
        self._task_handle = handle
        handle.progress.connect(
            lambda value, task=handle: self._on_progress(task, value)
        )
        handle.succeeded.connect(
            lambda result, task=handle: self._on_succeeded(task, result)
        )
        handle.failed.connect(
            lambda failure, task=handle: self._on_task_failed(task, failure)
        )
        handle.cancelled.connect(lambda task=handle: self._on_cancelled(task))

    def _on_progress(self, handle: object, value: object) -> None:
        if handle is not self._task_handle:
            return
        if (
            not isinstance(value, tuple)
            or len(value) != 2
            or not all(isinstance(item, int) for item in value)
        ):
            LOGGER.error("ZIP 后台任务返回无效进度:%r", value)
            return
        self.progress.emit(value[0], value[1])

    def _on_succeeded(self, handle: object, result: object) -> None:
        if handle is not self._task_handle:
            return
        self._task_handle = None
        if not isinstance(result, ArchiveResult):
            self._finish_failed("ZIP 打包失败:后台任务返回无效结果")
            return
        self._on_completed(result.archive_path, result.file_count, result.size_bytes)

    def _on_task_failed(self, handle: object, failure: object) -> None:
        if handle is not self._task_handle:
            return
        self._task_handle = None
        error = getattr(failure, "exception", failure)
        LOGGER.error("ZIP 打包失败:%s", error)
        self._finish_failed(f"ZIP 打包失败:{error}")

    def _on_cancelled(self, handle: object) -> None:
        if handle is not self._task_handle:
            return
        self._task_handle = None
        self._finish_failed("ZIP 打包已取消")

    @Slot(str, int, "qint64")
    def _on_completed(self, archive_path: str, file_count: int, size_bytes: int) -> None:
        self._set_busy(False)
        self.logMessage.emit(
            f"ZIP 打包完成：{archive_path}（{file_count} 个文件，{size_bytes} 字节）",
            "success",
        )
        self.finished.emit(True, archive_path, file_count, size_bytes)

    def _finish_failed(self, message: str) -> None:
        self._set_busy(False)
        self.logMessage.emit(message, "error")
        self.taskFailed.emit(message)
        self.finished.emit(False, "", 0, 0)


__all__ = ["ArchiveResult", "PackageBackend", "create_zip_archive"]
