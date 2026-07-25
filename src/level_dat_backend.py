# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""Level.dat 阅读页面的 Qt 后端。"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import logging
import os
from pathlib import Path
import stat
import tempfile
from typing import Any

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot

from prismqml import get_clipboard_helper

from .config import (
    LEVEL_DAT_BACKUP_SUFFIX,
    LEVEL_DAT_MAX_BYTES,
    LEVEL_DAT_MAX_COLLECTION_ITEMS,
    LEVEL_DAT_MAX_DEPTH,
    LEVEL_DB_VALUE_PREVIEW_CHARS,
)
from .level_dat import (
    LevelDatDocument,
    LevelDatParseError,
    NbtTag,
    build_view_rows,
    parse_level_dat,
)
from .level_dat_editor import apply_text_edits, serialize_level_dat
from .level_dat_model import LevelDatTagModel, filter_level_dat_rows
from .netease_world_data import (
    NeteaseWorldDataError,
    empty_world_data_summary,
    load_netease_world_data,
)
from .netease_world_data_editor import save_netease_world_data_edits
from .settings_backend import ApplicationSettingsBackend


LOGGER = logging.getLogger(__name__)


def _extra_data_preview_row(row: dict[str, object]) -> dict[str, object]:
    value = str(row.get("value", ""))
    preview_row = row.copy()
    preview_row["fullValue"] = value
    preview_row["liveValidationLimit"] = LEVEL_DB_VALUE_PREVIEW_CHARS
    preview_row["fullValueLength"] = len(value)
    preview_row["valueTruncated"] = len(value) > LEVEL_DB_VALUE_PREVIEW_CHARS
    if preview_row["valueTruncated"]:
        preview_row["value"] = value[:LEVEL_DB_VALUE_PREVIEW_CHARS]
    return preview_row


@dataclass(slots=True)
class _FilterState:
    generation: int = 0
    query: str = ""
    changes: list[dict[str, object]] = field(default_factory=list)
    rows: list[dict[str, object]] = field(default_factory=list)
    handle: Any = None


class LevelDatReadError(ValueError):
    """level.dat 路径或文件内容不可读取。"""


def _local_path(source: str) -> Path:
    value = source.strip()
    if not value:
        raise LevelDatReadError("请选择 level.dat 文件")
    local_value = QUrl(value).toLocalFile() if value.casefold().startswith("file:") else value
    if not local_value:
        raise LevelDatReadError("所选文件不是本地文件")
    path = Path(local_value).expanduser().resolve()
    if path.name.casefold() != "level.dat":
        raise LevelDatReadError("请选择文件名为 level.dat 的存档数据")
    if not path.is_file():
        raise LevelDatReadError("所选 level.dat 不存在或不是文件")
    return path


def _read_bytes(path: Path) -> bytes:
    try:
        with path.open("rb") as handle:
            data = handle.read(LEVEL_DAT_MAX_BYTES + 1)
    except OSError as error:
        LOGGER.warning("读取 level.dat 失败：%s", path, exc_info=True)
        raise LevelDatReadError(f"无法读取 level.dat：{error}") from error
    if len(data) > LEVEL_DAT_MAX_BYTES:
        raise LevelDatReadError(f"level.dat 超过读取上限 {LEVEL_DAT_MAX_BYTES} 字节")
    return data


def _root_string(tags: tuple[NbtTag, ...], name: str) -> str:
    for tag in tags:
        if tag.name == name and tag.tag_type == 8:
            return str(tag.value)
    return ""


def _parse_document(data: bytes) -> LevelDatDocument:
    return parse_level_dat(
        data,
        max_depth=LEVEL_DAT_MAX_DEPTH,
        max_items=LEVEL_DAT_MAX_COLLECTION_ITEMS,
    )


def _view_from_data(
    path: Path,
    data: bytes,
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    document = _parse_document(data)
    rows = build_view_rows(document)
    root_tags = document.root.value
    assert isinstance(root_tags, tuple)
    netease_rows = [row for row in rows if row["isNetease"]]
    summary = {
        "filePath": str(path),
        "fileSize": len(data),
        "formatVersion": document.format_version,
        "declaredPayloadSize": document.declared_payload_size,
        "rootName": document.root.name,
        "rootTagCount": len(root_tags),
        "visibleNodeCount": len(rows),
        "neteaseNodeCount": len(netease_rows),
        "levelName": _root_string(root_tags, "LevelName"),
        "fingerprint": hashlib.sha256(data).hexdigest(),
    }
    return summary, rows, netease_rows


def _full_world_view(
    path: Path,
    data: bytes,
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    summary, rows, netease_rows = _view_from_data(path, data)
    summary["nbtNodeCount"] = len(rows)
    try:
        world_data = load_netease_world_data(path)
    except NeteaseWorldDataError as error:
        LOGGER.warning("读取同世界 LevelDB 失败：%s", path.parent / "db", exc_info=True)
        world_summary = empty_world_data_summary(path)
        world_summary["levelDbFound"] = (path.parent / "db").is_dir()
        world_summary["extraDataStatus"] = f"DB 读取失败：{error}"
    else:
        world_summary = world_data.summary
        rows.extend(world_data.rows)
    summary.update(world_summary)
    summary["visibleNodeCount"] = len(rows)
    return summary, rows, netease_rows


def load_level_dat_view(
    source: str,
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    """读取本地 level.dat 并生成页面摘要与完整节点列表。"""

    path = _local_path(source)
    return _full_world_view(path, _read_bytes(path))


def _atomic_write(path: Path, data: bytes) -> None:
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        os.replace(temporary, path)
    except OSError:
        LOGGER.exception("原子写入失败：%s", path)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            LOGGER.warning("清理 level.dat 临时文件失败：%s", temporary, exc_info=True)
        raise


def _verify_or_restore(path: Path, expected: bytes, original: bytes) -> bytes:
    try:
        saved = _read_bytes(path)
        if saved != expected:
            raise LevelDatReadError("保存后的文件字节与预期不一致")
        _parse_document(saved)
        return saved
    except (LevelDatReadError, LevelDatParseError) as error:
        LOGGER.error("保存后验证失败，开始恢复原文件：%s", path, exc_info=True)
        try:
            _atomic_write(path, original)
        except OSError:
            LOGGER.exception("恢复原始 level.dat 失败：%s", path)
        raise LevelDatReadError(f"保存后验证失败：{error}") from error


def _ensure_source_unchanged(path: Path, original: bytes) -> None:
    if _read_bytes(path) != original:
        raise LevelDatReadError("level.dat 已被其他程序修改，请重新读取后再编辑")


def _write_verified_backup(path: Path, original: bytes) -> None:
    _atomic_write(path, original)
    if _read_bytes(path) != original:
        raise LevelDatReadError("level.dat_old 备份验证失败，未写入主文件")


def save_level_dat_edits(
    source: str,
    fingerprint: str,
    changes: list[dict[str, object]],
) -> tuple[
    dict[str, object],
    list[dict[str, object]],
    list[dict[str, object]],
    str,
    int,
]:
    """校验版本指纹、创建官方备份并原子保存一组修改。"""

    path = _local_path(source)
    original = _read_bytes(path)
    if hashlib.sha256(original).hexdigest() != fingerprint:
        raise LevelDatReadError("level.dat 已被其他程序修改，请重新读取后再编辑")
    document = _parse_document(original)
    updated = serialize_level_dat(apply_text_edits(document, changes))
    _parse_document(updated)
    _ensure_source_unchanged(path, original)
    backup_path = path.with_name(path.name + LEVEL_DAT_BACKUP_SUFFIX)
    _write_verified_backup(backup_path, original)
    _atomic_write(path, updated)
    saved = _verify_or_restore(path, updated, original)
    summary, rows, netease_rows = _full_world_view(path, saved)
    return summary, rows, netease_rows, str(backup_path), len(changes)


def save_extra_data_edits(
    source: str,
    expected_sequence: str,
    expected_fingerprint: str,
    changes: list[dict[str, object]],
) -> tuple[
    dict[str, object],
    list[dict[str, object]],
    list[dict[str, object]],
    str,
    int,
]:
    """后台保存世界 scriptData，并重新载入完整页面模型。"""

    path = _local_path(source)
    try:
        sequence = int(expected_sequence)
    except ValueError as error:
        raise LevelDatReadError("世界数据库 sequence 无效，请重新读取") from error
    _view, backup_path, changed_count = save_netease_world_data_edits(
        path,
        sequence,
        expected_fingerprint,
        changes,
    )
    summary, rows, netease_rows = _full_world_view(path, _read_bytes(path))
    return summary, rows, netease_rows, str(backup_path), changed_count


class LevelDatBackend(QObject):
    """异步载入并安全保存一个本地 level.dat。"""

    busyChanged = Signal()
    loaded = Signal(dict)
    saved = Signal(str, str)
    extraDataSaved = Signal(str, str)
    failed = Signal(str)
    extraDataCopied = Signal(str)
    recentNbtPathChanged = Signal()

    def __init__(
        self,
        parent: QObject | None = None,
        settings_backend: ApplicationSettingsBackend | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings_backend = settings_backend
        if self._settings_backend is not None:
            self._settings_backend.recentNbtPathChanged.connect(
                self.recentNbtPathChanged
            )
        self._busy = False
        self._task_handle = None
        self._filter = _FilterState()
        self._tag_model = LevelDatTagModel(self)
        self._nbt_tag_model = LevelDatTagModel(self)
        self._extra_data_tag_model = LevelDatTagModel(self)
        self._extra_data_values: dict[str, str] = {}

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    @Property(str, notify=recentNbtPathChanged)
    def recentNbtPath(self) -> str:
        if self._settings_backend is None:
            return ""
        return self._settings_backend.recentNbtPath

    @Property("QVariantList", notify=recentNbtPathChanged)
    def savedNbtPaths(self) -> list[str]:
        if self._settings_backend is None:
            return []
        return self._settings_backend.savedNbtPaths

    @Property(QObject, constant=True)
    def tagModel(self) -> LevelDatTagModel:
        return self._tag_model

    @Property(QObject, constant=True)
    def nbtTagModel(self) -> LevelDatTagModel:
        return self._nbt_tag_model

    @Property(QObject, constant=True)
    def extraDataTagModel(self) -> LevelDatTagModel:
        return self._extra_data_tag_model

    @Slot(str)
    def copyExtraDataValue(self, token: str) -> None:
        value = self._extra_data_values.get(token)
        if value is None:
            LOGGER.warning("复制 DB 完整值失败，token 不存在：%s", token)
            self.failed.emit("无法复制完整 DB 值：当前数据已变化，请重新读取")
            return
        get_clipboard_helper().copy(value)
        self.extraDataCopied.emit(f"已复制完整 DB 值（{len(value)} 字符）")

    @Slot(str)
    def copyExtraDataText(self, value: str) -> None:
        get_clipboard_helper().copy(value)
        self.extraDataCopied.emit(f"已复制当前 DB 值（{len(value)} 字符）")

    def _set_busy(self, value: bool) -> None:
        if self._busy == value:
            return
        self._busy = value
        self.busyChanged.emit()

    @Slot(str)
    def load(self, source: str) -> None:
        if self._busy:
            self.failed.emit("正在读取 level.dat，请稍候")
            return
        from prismqml import run_in_pool

        self._reset_rows()
        self._set_busy(True)
        handle = run_in_pool(load_level_dat_view, source)
        self._task_handle = handle
        handle.succeeded.connect(self._on_loaded)
        handle.failed.connect(self._on_failed)

    @Slot(str, list)
    def setFilter(self, query: str, changes: list[dict[str, object]]) -> None:
        self._filter.query = query.strip()
        self._filter.changes = changes
        self._start_filter()

    @Slot(str, str, list)
    def save(self, source: str, fingerprint: str, changes: list[dict[str, object]]) -> None:
        if self._busy:
            self.failed.emit("正在处理 level.dat，请稍候")
            return
        from prismqml import run_in_pool

        self._set_busy(True)
        handle = run_in_pool(save_level_dat_edits, source, fingerprint, changes)
        self._task_handle = handle
        handle.succeeded.connect(self._on_saved)
        handle.failed.connect(self._on_failed)

    @Slot(str, str, str, list)
    def saveExtraData(
        self, source: str, expected_sequence: str, expected_fingerprint: str,
        changes: list[dict[str, object]],
    ) -> None:
        if self._busy:
            self.failed.emit("正在处理世界数据，请稍候")
            return
        from prismqml import run_in_pool

        self._set_busy(True)
        handle = run_in_pool(
            save_extra_data_edits, source, expected_sequence, expected_fingerprint, changes
        )
        self._task_handle = handle
        handle.succeeded.connect(self._on_extra_data_saved)
        handle.failed.connect(self._on_failed)

    @Slot(object)
    def _on_loaded(self, result: object) -> None:
        summary, rows, _netease_rows = result
        self._set_busy(False)
        self._install_rows(rows)
        self._remember_loaded_path(summary)
        self.loaded.emit(summary)

    @Slot(object)
    def _on_saved(self, result: object) -> None:
        summary, rows, _netease_rows, backup_path, changed_count = result
        self._set_busy(False)
        self._install_rows(rows)
        self._remember_loaded_path(summary)
        self.loaded.emit(summary)
        self.saved.emit(backup_path, f"已保存 {changed_count} 项修改")

    @Slot(object)
    def _on_extra_data_saved(self, result: object) -> None:
        summary, rows, _netease_rows, backup_path, changed_count = result
        self._set_busy(False)
        self._install_rows(rows)
        self._remember_loaded_path(summary)
        self.loaded.emit(summary)
        self.extraDataSaved.emit(backup_path, f"已保存 {changed_count} 项世界数据库修改")

    def _remember_loaded_path(self, summary: dict[str, object]) -> None:
        if self._settings_backend is None:
            return
        file_path = str(summary.get("filePath", ""))
        if file_path and not self._settings_backend.rememberNbtPath(file_path):
            LOGGER.warning("保存最近 NBT 路径失败：%s", file_path)

    def _reset_rows(self) -> None:
        self._cancel_filter()
        self._filter.query = ""
        self._filter.changes = []
        self._filter.rows = []
        self._extra_data_values = {}
        self._replace_visible_rows([])

    def _install_rows(self, rows: list[dict[str, object]]) -> None:
        self._filter.rows = rows
        self._extra_data_values = {
            str(row["token"]): str(row.get("value", ""))
            for row in rows
            if row.get("sourceKind") == "extraData"
        }
        self._start_filter()

    def _replace_visible_rows(self, rows: list[dict[str, object]]) -> None:
        self._tag_model.replace_rows(rows)
        self._nbt_tag_model.replace_rows(
            [row for row in rows if row.get("sourceKind") != "extraData"]
        )
        extra_data_rows = [
            _extra_data_preview_row(row)
            for row in rows
            if row.get("sourceKind") == "extraData"
        ]
        self._extra_data_tag_model.replace_rows(extra_data_rows)

    def _cancel_filter(self) -> None:
        self._filter.generation += 1
        if self._filter.handle is not None:
            self._filter.handle.cancel()
            self._filter.handle = None

    def _start_filter(self) -> None:
        self._cancel_filter()
        generation = self._filter.generation
        if not self._filter.query:
            self._replace_visible_rows(self._filter.rows)
            return
        if not self._filter.rows:
            self._replace_visible_rows([])
            return
        from prismqml import run_in_pool

        handle = run_in_pool(
            filter_level_dat_rows,
            self._filter.rows,
            self._filter.query,
            self._filter.changes,
            generation,
        )
        self._filter.handle = handle
        handle.succeeded.connect(self._on_filtered)
        handle.failed.connect(
            lambda failure, request=generation: self._on_filter_failed(request, failure)
        )

    @Slot(object)
    def _on_filtered(self, result: object) -> None:
        generation, rows = result
        if generation != self._filter.generation or rows is None:
            return
        self._filter.handle = None
        self._replace_visible_rows(rows)

    @Slot(int, object)
    def _on_filter_failed(self, generation: int, failure: object) -> None:
        exception = getattr(failure, "exception", failure)
        LOGGER.error("level.dat 后台筛选失败：%s", exception)
        if generation != self._filter.generation:
            return
        self._filter.handle = None
        self.failed.emit(f"筛选 level.dat 数据失败：{exception}")

    @Slot(object)
    def _on_failed(self, failure: object) -> None:
        exception = getattr(failure, "exception", failure)
        LOGGER.error("level.dat 后台处理失败：%s", exception)
        self._set_busy(False)
        self.failed.emit(str(exception))


__all__ = [
    "LevelDatBackend",
    "LevelDatReadError",
    "load_level_dat_view",
    "save_extra_data_edits",
    "save_level_dat_edits",
]
