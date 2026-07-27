# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
# 垃圾清理后端的 Python 实现。
# Python implementation of the cleanup backend.

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import shutil

from PySide6.QtCore import QObject, Property, Signal, Slot

from .pack_scanner import _absolute, _dir_size
from .project_structure import is_map_project


LOGGER = logging.getLogger(__name__)
JUNK_DIR_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
JUNK_FILE_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}
JUNK_FILE_SUFFIXES = (".pyc", ".pyo", ".mcp", ".log", ".tmp", ".bak", ".swp")
STUDIO_METADATA_NAMES = (".mcs", "studio.json", "work.mcscfg")
STUDIO_LINKED_PACK_PREFIXES = {
    "behavior_packs": "behavior_dn_",
    "resource_packs": "resource_dn_",
}


@dataclass(frozen=True)
class _ScanResult:
    items: list[str]
    total_bytes: int


def _is_inside(root: str, child: str) -> bool:
    try:
        return os.path.commonpath([root, child]).lower() == root.lower()
    except ValueError:
        return False


def _is_junk_file(name: str) -> bool:
    lower = name.lower()
    return lower in JUNK_FILE_NAMES or lower.endswith(JUNK_FILE_SUFFIXES)


def _scan_junk_directories(root: str, current: str, directories: list[str]) -> _ScanResult:
    items: list[str] = []
    total = 0
    kept: list[str] = []
    for name in directories:
        candidate = os.path.abspath(os.path.join(current, name))
        if os.path.islink(candidate):
            continue
        path = _absolute(candidate)
        if name.lower() in JUNK_DIR_NAMES:
            if _is_inside(root, path):
                items.append(path)
                total += _dir_size(path)
            continue
        kept.append(name)
    directories[:] = kept
    return _ScanResult(items, total)


def _scan_junk_files(root: str, current: str, files: list[str]) -> _ScanResult:
    items: list[str] = []
    total = 0
    for name in files:
        candidate = os.path.abspath(os.path.join(current, name))
        if os.path.islink(candidate):
            continue
        path = _absolute(candidate)
        if not _is_inside(root, path) or not _is_junk_file(name):
            continue
        try:
            size = os.path.getsize(path)
        except OSError as error:
            LOGGER.warning("无法统计垃圾文件 %s: %s", path, error)
            continue
        items.append(path)
        total += size
    return _ScanResult(items, total)


def _scan_studio_export_residue(root: str) -> _ScanResult:
    metadata = [
        _absolute(os.path.join(root, name))
        for name in STUDIO_METADATA_NAMES
        if os.path.lexists(os.path.join(root, name))
        and not os.path.islink(os.path.join(root, name))
    ]
    if not metadata:
        return _ScanResult([], 0)

    items = list(metadata)
    if is_map_project(root):
        for collection_name, prefix in STUDIO_LINKED_PACK_PREFIXES.items():
            collection = os.path.join(root, collection_name)
            if not os.path.isdir(collection) or os.path.islink(collection):
                continue
            for name in os.listdir(collection):
                candidate = os.path.join(collection, name)
                if (
                    not name.casefold().startswith(prefix)
                    or not os.path.isdir(candidate)
                    or os.path.islink(candidate)
                    or os.path.isfile(os.path.join(candidate, "manifest.json"))
                ):
                    continue
                items.append(_absolute(candidate))

    total = 0
    for path in items:
        try:
            total += _dir_size(path) if os.path.isdir(path) else os.path.getsize(path)
        except OSError as error:
            LOGGER.warning("无法统计 Studio 导出残留 %s: %s", path, error)
    return _ScanResult(items, total)


def _scan_junk(root: str) -> _ScanResult:
    studio_residue = _scan_studio_export_residue(root)
    residue_directories = [path for path in studio_residue.items if os.path.isdir(path)]
    items: list[str] = list(studio_residue.items)
    total = studio_residue.total_bytes
    map_database = _absolute(os.path.join(root, "db")) if is_map_project(root) else ""
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        if map_database and _is_inside(map_database, _absolute(current)):
            continue
        for result in (
            _scan_junk_directories(root, current, directories),
            _scan_junk_files(root, current, files),
        ):
            for path in result.items:
                if any(_is_inside(residue, path) for residue in residue_directories):
                    continue
                items.append(path)
                total += _dir_size(path) if os.path.isdir(path) else os.path.getsize(path)
    return _ScanResult(items, total)


def _scan(root_dir: str) -> tuple[_ScanResult, list[tuple[str, str]]]:
    root = _absolute(root_dir)
    if not os.path.isdir(root):
        return _ScanResult([], 0), [("error", f"目录无效:{root_dir}")]
    result = _scan_junk(root)
    return result, [("success", f"扫描完成:命中 {len(result.items)} 项,约 {result.total_bytes // 1024} KB")]


def _clean(root_dir: str) -> tuple[bool, int, int, str, list[tuple[str, str]]]:
    root = _absolute(root_dir)
    if not os.path.isdir(root):
        return False, 0, 0, "目录无效", []
    result = _scan_junk(root)
    removed = 0
    freed = 0
    failures: list[str] = []
    for path in sorted(result.items, key=lambda item: len(item), reverse=True):
        if not _is_inside(root, path) or os.path.islink(path):
            continue
        try:
            size = _dir_size(path) if os.path.isdir(path) else os.path.getsize(path)
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
        except OSError as error:
            LOGGER.warning("删除垃圾项失败 %s: %s", path, error)
            failures.append(path)
            continue
        removed += 1
        freed += size
    success = not failures
    message = f"清理完成,删除 {removed} 项,释放约 {freed // 1024} KB"
    if failures:
        message += f"；{len(failures)} 项删除失败"
    level = "success" if success else "error"
    return success, removed, freed, message, [(level, message)]


class CleanupBackend(QObject):
    """垃圾清理后端。"""

    logMessage = Signal(str, str)
    scanned = Signal(list, "qint64")
    progress = Signal(int, int)
    finished = Signal(bool, int, "qint64", str)
    busyChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._busy = False
        self._task_handle = None

    def _is_busy(self) -> bool:
        return self._busy

    busy = Property(bool, _is_busy, notify=busyChanged)

    def _set_busy(self, value: bool) -> None:
        if self._busy == value:
            return
        self._busy = value
        self.busyChanged.emit()

    @Slot(str)
    def scan(self, root_dir: str) -> None:
        if self._busy:
            self.logMessage.emit("正忙,请稍候", "warn")
            return
        from prismqml import run_in_pool

        self._set_busy(True)
        self.logMessage.emit(f"开始扫描:{_absolute(root_dir)}", "info")
        handle = run_in_pool(_scan, root_dir)
        self._task_handle = handle
        handle.succeeded.connect(self._on_scan_succeeded)
        handle.failed.connect(self._on_scan_failed)

    @Slot(str)
    def clean(self, root_dir: str) -> None:
        if self._busy:
            self.logMessage.emit("正忙,请稍候", "warn")
            return
        from prismqml import run_in_pool

        self._set_busy(True)
        self.logMessage.emit(f"开始清理:{_absolute(root_dir)}", "info")
        handle = run_in_pool(_clean, root_dir)
        self._task_handle = handle
        handle.succeeded.connect(self._on_clean_succeeded)
        handle.failed.connect(self._on_clean_failed)

    @Slot(object)
    def _on_scan_succeeded(self, result: tuple[_ScanResult, list[tuple[str, str]]]) -> None:
        scan_result, logs = result
        self._set_busy(False)
        for level, message in logs:
            self.logMessage.emit(message, level)
        self.scanned.emit(scan_result.items, scan_result.total_bytes)

    @Slot(object)
    def _on_clean_succeeded(self, result: tuple[bool, int, int, str, list[tuple[str, str]]]) -> None:
        success, removed, freed, message, logs = result
        self._set_busy(False)
        for level, text in logs:
            self.logMessage.emit(text, level)
        self.finished.emit(success, removed, freed, message)

    @Slot(object)
    def _on_scan_failed(self, failure: object) -> None:
        exception = getattr(failure, "exception", failure)
        LOGGER.error("扫描后台任务失败: %s", exception, exc_info=True)
        self._set_busy(False)
        self.scanned.emit([], 0)
        self.logMessage.emit(f"扫描失败:{exception}", "error")

    @Slot(object)
    def _on_clean_failed(self, failure: object) -> None:
        exception = getattr(failure, "exception", failure)
        LOGGER.error("清理后台任务失败: %s", exception, exc_info=True)
        self._set_busy(False)
        self.finished.emit(False, 0, 0, f"清理失败:{exception}")


__all__ = ["CleanupBackend"]
