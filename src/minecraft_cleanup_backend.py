# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""网易 Minecraft 全局数据目录的安全分类清理后端。"""

from __future__ import annotations

from fnmatch import fnmatch
import logging
import os
from pathlib import Path
from typing import Callable, Iterable

from .minecraft_cleanup_definitions import (
    MC_CLEANUP_ENTRY_DEFINITIONS,
    MC_CLEANUP_MSG_CLEANED,
    MC_CLEANUP_MSG_EMPTY,
    MC_CLEANUP_MSG_PARTIAL,
    MC_CLEANUP_MSG_ROOT_MISSING,
    MC_CLEANUP_MSG_SKIPPED,
    MC_CLEANUP_MSG_UNKNOWN_TYPE,
    MC_CLEANUP_PROTECTED_COUNTDOWN_SECONDS,
    MC_CLEANUP_PROTECTED_DEFINITIONS,
    MC_CLEANUP_UI_TEXTS,
    MC_DATA_DIR_ENV,
    MC_DATA_DIR_NAME,
)


LOGGER = logging.getLogger(__name__)


def _format_size(size: int) -> str:
    value = float(max(0, size))
    units = ("B", "KB", "MB", "GB", "TB")
    unit_index = 0
    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1
    if unit_index == 0:
        return f"{int(value)}{units[unit_index]}"
    return f"{value:.2f}{units[unit_index]}"


class MinecraftCleanupService:
    """扫描并删除网易 Minecraft 固定白名单内的数据。"""

    def __init__(self, data_root_provider: Callable[[], Path] | None = None) -> None:
        self._data_root_provider = data_root_provider or self._default_data_root

    @staticmethod
    def _default_data_root() -> Path:
        configured = os.environ.get(MC_DATA_DIR_ENV, "").strip()
        if configured:
            return Path(configured)
        roaming = os.environ.get("APPDATA", "").strip()
        if not roaming:
            raise RuntimeError("APPDATA 环境变量未配置，无法定位 Minecraft 数据目录")
        return Path(roaming) / MC_DATA_DIR_NAME

    def scan(self) -> dict[str, object]:
        """扫描默认清理项与默认保留的数据分类。"""
        root = self._validated_root()
        cleanable_rows = [
            self._scan_cleanable(root, definition)
            for definition in MC_CLEANUP_ENTRY_DEFINITIONS
        ]
        protected_rows = [
            self._scan_protected(root, definition)
            for definition in MC_CLEANUP_PROTECTED_DEFINITIONS
        ]
        reclaimable_bytes = sum(int(row["bytes"]) for row in cleanable_rows)
        return {
            "rootPath": str(root),
            "rootExists": root.is_dir(),
            "reclaimableBytes": reclaimable_bytes,
            "reclaimableSize": _format_size(reclaimable_bytes),
            "cleanableRows": cleanable_rows,
            "protectedRows": protected_rows,
            "protectedCountdownSeconds": MC_CLEANUP_PROTECTED_COUNTDOWN_SECONDS,
            "texts": dict(MC_CLEANUP_UI_TEXTS),
        }

    def clean(self, key: str) -> dict[str, object]:
        """删除一个固定白名单清理分类。"""
        definition = self._definition_for(key)
        if definition is None:
            return self._result(False, MC_CLEANUP_MSG_UNKNOWN_TYPE.format(key))
        root, blocked = self._cleaning_root()
        if blocked is not None:
            return blocked
        if definition in MC_CLEANUP_PROTECTED_DEFINITIONS:
            return self._clean_protected_definition(root, definition)
        return self._clean_definition(root, definition)

    def clean_all(self) -> dict[str, object]:
        """只删除默认参与“清理全部”的推荐分类。"""
        root, blocked = self._cleaning_root()
        if blocked is not None:
            return blocked
        removed_files = removed_bytes = failed_files = 0
        for definition in MC_CLEANUP_ENTRY_DEFINITIONS:
            result = self._clean_definition(root, definition)
            removed_files += int(result["removedFiles"])
            removed_bytes += int(result["removedBytes"])
            failed_files += int(result["failedFiles"])
        return self._summary_result(removed_files, removed_bytes, failed_files)

    def clean_and_scan(self, key: str | None = None) -> tuple[dict[str, object], dict[str, object]]:
        result = self.clean_all() if key is None else self.clean(key)
        return result, self.scan()

    def folder_for(self, key: str = "") -> Path:
        """返回一个能准确代表该清理分类范围的目录。"""
        root = self._validated_root()
        if not key:
            return root
        definition = self._definition_for(key)
        if definition is None:
            raise ValueError(MC_CLEANUP_MSG_UNKNOWN_TYPE.format(key))
        return self._safe_target(root, definition["browsePath"])

    def _validated_root(self) -> Path:
        raw_root = Path(self._data_root_provider())
        if raw_root.name.casefold() != MC_DATA_DIR_NAME.casefold():
            raise ValueError(f"Minecraft 数据目录必须以 {MC_DATA_DIR_NAME} 结尾")
        if self._is_link_like(raw_root):
            raise ValueError("Minecraft 数据根目录不能是符号链接或目录联接")
        return raw_root.resolve(strict=False)

    def _scan_cleanable(self, root: Path, definition: dict) -> dict[str, object]:
        files = list(self._matching_files(root, definition)) if root.is_dir() else []
        nbytes = self._files_size(files)
        return {
            "key": definition["key"],
            "name": definition["name"],
            "description": definition["description"],
            "bytes": nbytes,
            "sizeText": _format_size(nbytes),
            "files": len(files),
            "filesText": f"{len(files)} 个文件",
            "exists": bool(files),
            "cleanable": True,
            "defaultSelected": True,
            "requiresCountdown": False,
        }

    def _scan_protected(self, root: Path, definition: dict) -> dict[str, object]:
        files = self._matching_protected_files(root, definition) if root.is_dir() else ()
        file_count, nbytes = self._files_summary(files)
        return {
            "key": definition["key"],
            "name": definition["name"],
            "description": definition["description"],
            "bytes": nbytes,
            "sizeText": _format_size(nbytes),
            "files": file_count,
            "filesText": f"{file_count} 个文件",
            "exists": file_count > 0,
            "cleanable": True,
            "defaultSelected": False,
            "requiresCountdown": True,
        }

    def _matching_files(self, root: Path, definition: dict) -> Iterable[Path]:
        raw_directory = root.joinpath(*definition["relativeDir"])
        if self._is_link_like(raw_directory):
            LOGGER.warning("[Minecraft 清理] 跳过链接目录：%s", raw_directory)
            return
        directory = self._safe_target(root, definition["relativeDir"])
        if not directory.is_dir():
            return
        candidates = directory.rglob("*") if definition["recursive"] else directory.iterdir()
        for candidate in candidates:
            if self._is_link_like(candidate) or not candidate.is_file():
                continue
            if any(fnmatch(candidate.name, pattern) for pattern in definition["patterns"]):
                yield candidate

    def _matching_protected_files(self, root: Path, definition: dict) -> Iterable[Path]:
        for relative in definition["paths"]:
            raw_target = root / relative
            if self._is_link_like(raw_target):
                yield raw_target
                continue
            target = self._protected_target(root, relative)
            if target is None:
                continue
            if target.is_file():
                yield target
                continue
            if not target.is_dir():
                continue
            for candidate, is_directory in self._walk_entries(root, target):
                if not is_directory:
                    yield candidate

    def _walk_entries(self, root: Path, directory: Path) -> Iterable[tuple[Path, bool]]:
        pending = [directory]
        while pending:
            current = pending.pop()
            try:
                with os.scandir(current) as iterator:
                    entries = list(iterator)
            except OSError as error:
                LOGGER.warning("[Minecraft 清理] 无法扫描目录 %s：%s", current, error)
                continue
            for entry in entries:
                path = Path(entry.path)
                if self._is_link_like(path):
                    yield path, False
                    continue
                try:
                    safe_path = self._safe_target(root, path.relative_to(root).parts)
                except ValueError as error:
                    LOGGER.warning("[Minecraft 清理] 跳过越界条目：%s", error)
                    continue
                if entry.is_dir(follow_symlinks=False):
                    pending.append(safe_path)
                    yield safe_path, True
                elif entry.is_file(follow_symlinks=False):
                    yield safe_path, False

    def _protected_target(self, root: Path, relative: str) -> Path | None:
        candidate = root / relative
        if self._is_link_like(candidate):
            LOGGER.warning("[Minecraft 清理] 跳过链接目标：%s", candidate)
            return None
        return self._safe_target(root, (relative,))

    @staticmethod
    def _is_link_like(path: Path) -> bool:
        is_junction = getattr(path, "is_junction", None)
        return path.is_symlink() or bool(is_junction and is_junction())

    def _files_size(self, files: Iterable[Path]) -> int:
        return self._files_summary(files)[1]

    def _files_summary(self, files: Iterable[Path]) -> tuple[int, int]:
        count = total = 0
        for path in files:
            count += 1
            try:
                linked = self._is_link_like(path)
                total += (path.lstat() if linked else path.stat()).st_size
            except OSError as error:
                LOGGER.warning("[Minecraft 清理] 无法读取文件大小 %s：%s", path, error)
        return count, total

    @staticmethod
    def _definition_for(key: str) -> dict | None:
        return next(
            (
                definition
                for definition in (
                    *MC_CLEANUP_ENTRY_DEFINITIONS,
                    *MC_CLEANUP_PROTECTED_DEFINITIONS,
                )
                if definition["key"] == key
            ),
            None,
        )

    def _cleaning_root(self) -> tuple[Path, dict[str, object] | None]:
        root = self._validated_root()
        if not root.is_dir():
            return root, self._result(False, MC_CLEANUP_MSG_ROOT_MISSING)
        return root, None

    def _clean_definition(self, root: Path, definition: dict) -> dict[str, object]:
        removed_files, removed_bytes, failed_files = self._delete_files(
            self._matching_files(root, definition)
        )
        if definition.get("removeEmptyDirs"):
            self._remove_empty_directories(root, definition)
        return self._summary_result(removed_files, removed_bytes, failed_files)

    def _clean_protected_definition(self, root: Path, definition: dict) -> dict[str, object]:
        removed_files, removed_bytes, failed_files = self._delete_files(
            self._matching_protected_files(root, definition)
        )
        self._remove_protected_empty_directories(root, definition)
        return self._summary_result(removed_files, removed_bytes, failed_files)

    def _delete_files(self, paths: Iterable[Path]) -> tuple[int, int, int]:
        removed_files = removed_bytes = failed_files = 0
        for path in list(paths):
            try:
                linked = self._is_link_like(path)
                size = path.lstat().st_size if linked else path.stat().st_size
                if getattr(path, "is_junction", lambda: False)():
                    path.rmdir()
                else:
                    path.unlink()
                removed_files += 1
                removed_bytes += size
            except OSError as error:
                failed_files += 1
                LOGGER.warning("[Minecraft 清理] 删除文件失败 %s：%s", path, error)
        return removed_files, removed_bytes, failed_files

    def _remove_protected_empty_directories(self, root: Path, definition: dict) -> None:
        for relative in definition["paths"]:
            directory = self._protected_target(root, relative)
            if directory is not None and directory.is_dir():
                self._remove_empty_descendants(root, directory, "有用数据")

    def _remove_empty_directories(self, root: Path, definition: dict) -> None:
        directory = self._safe_target(root, definition["relativeDir"])
        if directory.is_dir():
            self._remove_empty_descendants(root, directory, "缓存")

    def _remove_empty_descendants(self, root: Path, directory: Path, category: str) -> None:
        descendants = [path for path, is_directory in self._walk_entries(root, directory) if is_directory]
        descendants.sort(key=lambda path: len(path.parts), reverse=True)
        for path in descendants:
            try:
                if not any(path.iterdir()):
                    path.rmdir()
            except OSError as error:
                LOGGER.warning("[Minecraft 清理] 删除空%s目录失败 %s：%s", category, path, error)

    @staticmethod
    def _safe_target(root: Path, relative_parts: tuple[str, ...]) -> Path:
        target = root.joinpath(*relative_parts).resolve(strict=False)
        if target != root and root not in target.parents:
            raise ValueError(f"清理目标越界：{target}")
        return target

    def _summary_result(self, removed_files: int, removed_bytes: int, failed_files: int) -> dict[str, object]:
        if removed_files == 0 and failed_files == 0:
            return self._result(False, MC_CLEANUP_MSG_EMPTY)
        if failed_files:
            if removed_files == 0:
                return self._result(
                    False,
                    MC_CLEANUP_MSG_SKIPPED.format(failed_files),
                    removed_files,
                    removed_bytes,
                    failed_files,
                )
            return self._result(
                True,
                MC_CLEANUP_MSG_PARTIAL.format(removed_files, failed_files),
                removed_files,
                removed_bytes,
                failed_files,
            )
        return self._result(
            True,
            MC_CLEANUP_MSG_CLEANED.format(removed_files, _format_size(removed_bytes)),
            removed_files,
            removed_bytes,
            failed_files,
        )

    @staticmethod
    def _result(
        success: bool,
        message: str,
        removed_files: int = 0,
        removed_bytes: int = 0,
        failed_files: int = 0,
    ) -> dict[str, object]:
        return {
            "success": success,
            "message": message,
            "removedFiles": removed_files,
            "removedBytes": removed_bytes,
            "failedFiles": failed_files,
        }


def _empty_state() -> dict[str, object]:
    return {
        "rootPath": "",
        "rootExists": False,
        "reclaimableBytes": 0,
        "reclaimableSize": _format_size(0),
        "cleanableRows": [],
        "protectedRows": [],
        "protectedCountdownSeconds": MC_CLEANUP_PROTECTED_COUNTDOWN_SECONDS,
        "texts": dict(MC_CLEANUP_UI_TEXTS),
    }


__all__ = [
    "MC_DATA_DIR_ENV",
    "MC_DATA_DIR_NAME",
    "MinecraftCleanupService",
]
