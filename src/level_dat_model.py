# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""Level.dat 页面使用的虚拟化只读模型与后台筛选任务。"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import (
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    Property,
    QThread,
    Qt,
    Signal,
)


LevelDatRow = dict[str, object]
LevelDatChange = dict[str, object]

_ROLE_KEYS = (
    "path",
    "value",
    "token",
    "depth",
    "isNetease",
    "editable",
    "container",
    "sourceKind",
    "editorKind",
    "minimum",
    "maximum",
    "decimals",
    "stepSize",
    "valueTruncated",
    "fullValueLength",
    "fullValue",
    "liveValidationLimit",
)
_FIRST_ROLE = int(Qt.ItemDataRole.UserRole) + 1
_ROLE_NAMES = {
    _FIRST_ROLE + offset: QByteArray(key.encode("utf-8"))
    for offset, key in enumerate(_ROLE_KEYS)
}
_ROLE_LOOKUP = {
    _FIRST_ROLE + offset: key for offset, key in enumerate(_ROLE_KEYS)
}


def matching_level_dat_rows(
    rows: list[LevelDatRow],
    query: str,
    changes: Sequence[LevelDatChange],
    *,
    cancel_requested: Callable[[], bool] | None = None,
) -> list[LevelDatRow] | None:
    """筛选路径或当前显示值；返回 None 表示任务已取消。"""

    normalized = query.strip().casefold()
    if not normalized:
        return rows
    changed_values = {
        str(change["token"]): str(change["value"])
        for change in changes
    }
    matched: list[LevelDatRow] = []
    for index, row in enumerate(rows):
        if index % 256 == 0 and cancel_requested and cancel_requested():
            return None
        token = str(row["token"])
        value = changed_values.get(token, str(row["value"]))
        searchable = f"{row['path']} {value}".casefold()
        if normalized in searchable:
            matched.append(row)
    return matched


def filter_level_dat_rows(
    rows: list[LevelDatRow],
    query: str,
    changes: Sequence[LevelDatChange],
    generation: int,
) -> tuple[int, list[LevelDatRow] | None]:
    """在线程池内执行筛选，并携带请求代次防止旧结果覆盖新结果。"""

    from prismqml import current_task

    task = current_task()
    return generation, matching_level_dat_rows(
        rows,
        query,
        changes,
        cancel_requested=lambda: task.cancel_requested,
    )


class LevelDatTagModel(QAbstractListModel):
    """向 QML 暴露筛选结果；模型变更只能发生在其所属线程。"""

    countChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[LevelDatRow] = []

    @Property(int, notify=countChanged)
    def count(self) -> int:
        return len(self._rows)

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def roleNames(self) -> dict[int, QByteArray]:  # noqa: N802
        return _ROLE_NAMES

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        key = _ROLE_LOOKUP.get(int(role))
        if key is None:
            return None
        row = self._rows[index.row()]
        if key == "valueTruncated":
            return bool(row.get(key, False))
        if key == "fullValueLength":
            return int(row.get(key, len(str(row.get("value", "")))))
        if key == "fullValue":
            return str(row.get(key, row.get("value", "")))
        if key == "liveValidationLimit":
            return int(row.get(key, 0))
        return row.get(key)

    def replace_rows(self, rows: list[LevelDatRow]) -> None:
        if QThread.currentThread() != self.thread():
            raise RuntimeError("Level.dat 模型只能在所属 Qt 线程更新")
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()
        self.countChanged.emit()

    def clear(self) -> None:
        if self._rows:
            self.replace_rows([])


__all__ = [
    "LevelDatChange",
    "LevelDatRow",
    "LevelDatTagModel",
    "filter_level_dat_rows",
    "matching_level_dat_rows",
]
