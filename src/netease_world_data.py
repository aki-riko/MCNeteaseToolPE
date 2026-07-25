# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""读取世界 LevelDB 的网易 ``scriptData`` 并生成编辑视图。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import struct

from .config import (
    LEVEL_DAT_MAX_COLLECTION_ITEMS,
    LEVEL_DAT_MAX_DEPTH,
    LEVEL_DB_MAX_MESSAGEPACK_ITEMS,
    LEVEL_DB_MAX_SCRIPT_BYTES,
    LEVEL_DB_MAX_VIEW_ROWS,
)
from .level_db import LevelDbReadError, read_current_value


SCRIPT_DATA_KEY = b"scriptData"
MATCH_DATA_KEYS = {
    "matchMapCount": b"dn_mj.maps",
    "exitPointCount": b"dn_mj.exitPoints",
    "switchBlockCount": b"dn_mj.exitPoint.switches",
    "gateConsoleCount": b"dn_mj.exitPoint.es",
}


class NeteaseWorldDataError(ValueError):
    """网易 scriptData 的 NBT 包装或 MessagePack 内容无效。"""


class _MapPairs(list[tuple[object, object]]):
    pass


class _MessagePackText(bytes):
    pass


class _MessagePackBinary(bytes):
    pass


@dataclass(frozen=True, slots=True)
class NeteaseWorldDataView:
    summary: dict[str, object]
    rows: list[dict[str, object]]


class _MessagePackReader:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._offset = 0
        self._items = 0

    def read(self) -> object:
        value = self._value(0)
        if self._offset != len(self._data):
            raise NeteaseWorldDataError("MessagePack 根对象后仍有未解析数据")
        return value

    def _take(self, size: int) -> bytes:
        end = self._offset + size
        if size < 0 or end > len(self._data):
            raise NeteaseWorldDataError("MessagePack 在数据尾部意外结束")
        value = self._data[self._offset:end]
        self._offset = end
        return value

    def _integer(self, size: int, *, signed: bool = False) -> int:
        return int.from_bytes(self._take(size), "big", signed=signed)

    def _count(self, size: int) -> int:
        count = self._integer(size)
        if count > LEVEL_DAT_MAX_COLLECTION_ITEMS:
            raise NeteaseWorldDataError("MessagePack 集合数量超过安全上限")
        return count

    def _track(self, count: int = 1) -> None:
        self._items += count
        if self._items > LEVEL_DB_MAX_MESSAGEPACK_ITEMS:
            raise NeteaseWorldDataError("MessagePack 总元素数量超过安全上限")

    def _value(self, depth: int) -> object:  # noqa: C901, PLR0911, PLR0912
        if depth > LEVEL_DAT_MAX_DEPTH:
            raise NeteaseWorldDataError("MessagePack 嵌套深度超过安全上限")
        self._track()
        marker = self._integer(1)
        if marker <= 0x7F:
            return marker
        if marker >= 0xE0:
            return marker - 256
        if 0x80 <= marker <= 0x8F:
            return self._map(marker & 0x0F, depth)
        if 0x90 <= marker <= 0x9F:
            return self._array(marker & 0x0F, depth)
        if 0xA0 <= marker <= 0xBF:
            return _MessagePackText(self._take(marker & 0x1F))
        if marker == 0xC0:
            return None
        if marker == 0xC2:
            return False
        if marker == 0xC3:
            return True
        if marker in {0xC4, 0xC5, 0xC6}:
            size_bytes = {0xC4: 1, 0xC5: 2, 0xC6: 4}[marker]
            return _MessagePackBinary(self._take(self._count(size_bytes)))
        if marker in {0xD9, 0xDA, 0xDB}:
            size_bytes = {0xD9: 1, 0xDA: 2, 0xDB: 4}[marker]
            return _MessagePackText(self._take(self._count(size_bytes)))
        if marker == 0xCA:
            return struct.unpack(">f", self._take(4))[0]
        if marker == 0xCB:
            return struct.unpack(">d", self._take(8))[0]
        if marker in {0xCC, 0xCD, 0xCE, 0xCF}:
            return self._integer({0xCC: 1, 0xCD: 2, 0xCE: 4, 0xCF: 8}[marker])
        if marker in {0xD0, 0xD1, 0xD2, 0xD3}:
            return self._integer(
                {0xD0: 1, 0xD1: 2, 0xD2: 4, 0xD3: 8}[marker],
                signed=True,
            )
        if marker in {0xDC, 0xDD}:
            return self._array(self._count(2 if marker == 0xDC else 4), depth)
        if marker in {0xDE, 0xDF}:
            return self._map(self._count(2 if marker == 0xDE else 4), depth)
        if marker in {0xD4, 0xD5, 0xD6, 0xD7, 0xD8}:
            size = {0xD4: 1, 0xD5: 2, 0xD6: 4, 0xD7: 8, 0xD8: 16}[marker]
            return ("$ext", self._integer(1, signed=True), self._take(size))
        if marker in {0xC7, 0xC8, 0xC9}:
            size = self._count({0xC7: 1, 0xC8: 2, 0xC9: 4}[marker])
            return ("$ext", self._integer(1, signed=True), self._take(size))
        raise NeteaseWorldDataError(f"不支持的 MessagePack 标记 0x{marker:02x}")

    def _array(self, count: int, depth: int) -> list[object]:
        return [self._value(depth + 1) for _ in range(count)]

    def _map(self, count: int, depth: int) -> _MapPairs:
        return _MapPairs(
            (self._value(depth + 1), self._value(depth + 1)) for _ in range(count)
        )


def _extract_message_pack(value: bytes) -> bytes:
    if len(value) > LEVEL_DB_MAX_SCRIPT_BYTES:
        raise NeteaseWorldDataError("scriptData 超过读取上限")
    offset = 0
    if len(value) < 8 or value[offset] != 10:
        raise NeteaseWorldDataError("scriptData 不是 NBT TAG_Compound")
    offset += 1
    root_name_size = int.from_bytes(value[offset:offset + 2], "little")
    offset += 2 + root_name_size
    if offset + 3 > len(value) or value[offset] != 8:
        raise NeteaseWorldDataError("scriptData NBT 缺少长字符串标签")
    offset += 1
    name_size = int.from_bytes(value[offset:offset + 2], "little")
    offset += 2
    name_end = offset + name_size
    if name_end + 4 > len(value):
        raise NeteaseWorldDataError("scriptData NBT 标签名越界")
    try:
        name = value[offset:name_end].decode("utf-8")
    except UnicodeDecodeError as error:
        raise NeteaseWorldDataError("scriptData NBT 标签名不是 UTF-8") from error
    if name != "scriptData":
        raise NeteaseWorldDataError("scriptData NBT 长字符串名称不匹配")
    payload_size = int.from_bytes(value[name_end:name_end + 4], "little")
    payload_start = name_end + 4
    payload_end = payload_start + payload_size
    if payload_size > LEVEL_DB_MAX_SCRIPT_BYTES or payload_end + 1 != len(value):
        raise NeteaseWorldDataError("scriptData NBT 长字符串长度不匹配")
    if value[payload_end] != 0:
        raise NeteaseWorldDataError("scriptData NBT Compound 未正常结束")
    return value[payload_start:payload_end]


def _map_get(mapping: _MapPairs, key: object, default: object = None) -> object:
    for item_key, value in mapping:
        if item_key == key:
            return value
    return default


def _decode_bytes(value: bytes) -> object:
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return {"$binary": value.hex(), "$length": len(value)}


def _json_value(value: object) -> object:
    if isinstance(value, bytes):
        return _decode_bytes(value)
    if isinstance(value, _MapPairs):
        encoded_type = _map_get(value, b"__type__")
        encoded_value = _map_get(value, b"value")
        if encoded_type == b"tuple" and isinstance(encoded_value, list):
            return [_json_value(item) for item in encoded_value]
        pairs = [(_json_value(key), _json_value(item)) for key, item in value]
        keys = [key for key, _item in pairs]
        if all(isinstance(key, str) for key in keys) and len(set(keys)) == len(keys):
            return {str(key): item for key, item in pairs}
        return {"$map": [[key, item] for key, item in pairs]}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, tuple) and len(value) == 3 and value[0] == "$ext":
        return {"$ext": value[1], "$data": value[2].hex()}
    return value


def _path_segment(key: object) -> str:
    if isinstance(key, str):
        return "." + key
    return "[" + json.dumps(key, ensure_ascii=False, separators=(",", ":")) + "]"


def _display_value(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


class _ViewRows:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []
        self.truncated = False

    def add(
        self,
        path: str,
        value: object,
        depth: int,
        *,
        container: bool | None = None,
    ) -> None:
        if len(self.rows) >= LEVEL_DB_MAX_VIEW_ROWS:
            self.truncated = True
            return
        is_container = isinstance(value, (dict, list)) if container is None else container
        count = len(value) if is_container else 0
        row_value = f"{count} 项" if is_container else _display_value(value)
        self.rows.append(
            {
                "path": path,
                "value": row_value,
                "token": "extra:" + path,
                "depth": depth,
                "isNetease": True,
                "editable": not is_container,
                "container": is_container,
                "sourceKind": "extraData",
                "editorKind": "none",
                "minimum": 0,
                "maximum": 0,
                "decimals": 0,
                "stepSize": 0,
            }
        )


def _count(value: object) -> int:
    return len(value) if isinstance(value, (list, _MapPairs)) else 0


def empty_world_data_summary(level_path: Path) -> dict[str, object]:
    return {
        "levelDbPath": str(level_path.parent / "db"),
        "levelDbFound": False,
        "extraDataFound": False,
        "extraDataStatus": "未发现同级 db 目录",
        "extraDataSequence": 0,
        "extraDataFingerprint": "",
        "extraDataSourceFile": "",
        "extraDataEntryCount": 0,
        "extraDataViewRowCount": 0,
        "extraDataTruncated": False,
        **{name: 0 for name in MATCH_DATA_KEYS},
    }


def load_netease_world_data(level_path: Path) -> NeteaseWorldDataView:
    """只读载入与 ``level.dat`` 同级的世界 DB。"""

    summary = empty_world_data_summary(level_path)
    db_path = level_path.parent / "db"
    if not db_path.is_dir():
        return NeteaseWorldDataView(summary, [])
    summary["levelDbFound"] = True
    try:
        current = read_current_value(db_path, SCRIPT_DATA_KEY)
    except LevelDbReadError as error:
        raise NeteaseWorldDataError(str(error)) from error
    if current is None or current.deleted or current.value is None:
        summary["extraDataStatus"] = "DB 中未找到当前 scriptData"
        return NeteaseWorldDataView(summary, [])
    root = _MessagePackReader(_extract_message_pack(current.value)).read()
    if not isinstance(root, _MapPairs):
        raise NeteaseWorldDataError("scriptData MessagePack 根对象不是 Map")
    rows = _ViewRows()
    rows.add("db.scriptData", [None] * len(root), 0, container=True)
    for key, value in root:
        rows.add(
            "db.scriptData" + _path_segment(_json_value(key)),
            _json_value(value),
            1,
            container=False,
        )
    summary.update(
        {
            "extraDataFound": True,
            "extraDataStatus": "已加载当前有效 scriptData",
            "extraDataSequence": current.sequence,
            "extraDataFingerprint": hashlib.sha256(current.value).hexdigest(),
            "extraDataSourceFile": current.source_file,
            "extraDataEntryCount": len(root),
            "extraDataViewRowCount": len(rows.rows),
            "extraDataTruncated": rows.truncated,
        }
    )
    for summary_name, key in MATCH_DATA_KEYS.items():
        summary[summary_name] = _count(_map_get(root, key))
    return NeteaseWorldDataView(summary, rows.rows)


__all__ = [
    "MATCH_DATA_KEYS",
    "NeteaseWorldDataError",
    "NeteaseWorldDataView",
    "SCRIPT_DATA_KEY",
    "empty_world_data_summary",
    "load_netease_world_data",
]
