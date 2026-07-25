# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""校验并保存网易世界 ``scriptData`` 顶层 JSON。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

from .config import (
    LEVEL_DAT_MAX_COLLECTION_ITEMS,
    LEVEL_DAT_MAX_DEPTH,
    LEVEL_DB_BACKUP_SUFFIX,
    LEVEL_DB_MAX_MESSAGEPACK_ITEMS,
    LEVEL_DB_MAX_SCRIPT_BYTES,
)
from .level_db import read_current_value
from .level_db_writer import LevelDbWriteError, write_current_value
from .netease_world_data import (
    SCRIPT_DATA_KEY,
    NeteaseWorldDataError,
    NeteaseWorldDataView,
    _MapPairs,
    _MessagePackBinary,
    _MessagePackReader,
    _MessagePackText,
    _extract_message_pack,
    _json_value,
    _map_get,
    _path_segment,
    load_netease_world_data,
)


class NeteaseWorldDataEditError(NeteaseWorldDataError):
    """用户 JSON、目标版本或编码结果无法安全保存。"""


def _reject_json_constant(value: str) -> object:
    raise NeteaseWorldDataEditError(f"JSON 不允许使用 {value}")


def _parse_json(value: str) -> object:
    if len(value.encode("utf-8")) > LEVEL_DB_MAX_SCRIPT_BYTES:
        raise NeteaseWorldDataEditError("单项 JSON 超过安全大小上限")
    try:
        return json.loads(value, parse_constant=_reject_json_constant)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise NeteaseWorldDataEditError(f"JSON 格式无效：{error}") from error


def _binary_from_json(value: object) -> bytes | None:
    if (
        not isinstance(value, dict)
        or "$binary" not in value
        or not set(value).issubset({"$binary", "$length"})
    ):
        return None
    encoded = value.get("$binary")
    if not isinstance(encoded, str):
        raise NeteaseWorldDataEditError("$binary 必须是十六进制字符串")
    try:
        decoded = bytes.fromhex(encoded)
    except ValueError as error:
        raise NeteaseWorldDataEditError("$binary 不是有效十六进制") from error
    expected = value.get("$length", len(decoded))
    if expected != len(decoded):
        raise NeteaseWorldDataEditError("$binary 长度与 $length 不一致")
    return decoded


def _ext_from_json(value: object) -> tuple[str, int, bytes] | None:
    if not isinstance(value, dict) or set(value) != {"$ext", "$data"}:
        return None
    ext_type = value.get("$ext")
    data = value.get("$data")
    if not isinstance(ext_type, int) or not -128 <= ext_type <= 127:
        raise NeteaseWorldDataEditError("$ext 类型必须是 -128 到 127 的整数")
    if not isinstance(data, str):
        raise NeteaseWorldDataEditError("$data 必须是十六进制字符串")
    try:
        return "$ext", ext_type, bytes.fromhex(data)
    except ValueError as error:
        raise NeteaseWorldDataEditError("$data 不是有效十六进制") from error


def _tuple_map_from_json(value: object, template: _MapPairs) -> _MapPairs | None:
    if _map_get(template, b"__type__") != b"tuple":
        return None
    original = _map_get(template, b"value")
    if not isinstance(value, list) or not isinstance(original, list):
        raise NeteaseWorldDataEditError("tuple 值必须保持为 JSON 数组")
    updated = _from_json(value, original)
    return _MapPairs(
        (key, updated if key == b"value" else item) for key, item in template
    )


def _map_pairs_from_json(value: object, template: _MapPairs) -> _MapPairs:
    tuple_value = _tuple_map_from_json(value, template)
    if tuple_value is not None:
        return tuple_value
    if isinstance(value, dict) and set(value) == {"$map"}:
        pairs = value["$map"]
        if not isinstance(pairs, list):
            raise NeteaseWorldDataEditError("$map 必须是键值对数组")
        result = _MapPairs()
        for index, pair in enumerate(pairs):
            if not isinstance(pair, list) or len(pair) != 2:
                raise NeteaseWorldDataEditError("$map 每项必须包含键和值")
            old_key, old_value = template[index] if index < len(template) else (None, None)
            result.append((_from_json(pair[0], old_key), _from_json(pair[1], old_value)))
        return result
    if not isinstance(value, dict):
        raise NeteaseWorldDataEditError("对象类型必须保持为 JSON 对象")
    return _object_from_json(value, template)


def _object_from_json(value: dict[str, object], template: _MapPairs) -> _MapPairs:
    result = _MapPairs()
    consumed: set[str] = set()
    for key, item in template:
        displayed_key = _json_value(key)
        if isinstance(displayed_key, str) and displayed_key in value:
            result.append((key, _from_json(value[displayed_key], item)))
            consumed.add(displayed_key)
    for key, item in value.items():
        if key not in consumed:
            result.append(
                (_MessagePackText(key.encode("utf-8")), _from_json(item, None))
            )
    return result


def _from_untyped_json(value: object) -> object:
    binary = _binary_from_json(value)
    if binary is not None:
        return _MessagePackBinary(binary)
    ext = _ext_from_json(value)
    if ext is not None:
        return ext
    if isinstance(value, str):
        return _MessagePackText(value.encode("utf-8"))
    if isinstance(value, list):
        return [_from_json(item, None) for item in value]
    if isinstance(value, dict):
        return _MapPairs(
            (_MessagePackText(key.encode("utf-8")), _from_json(item, None))
            for key, item in value.items()
        )
    return value


def _from_json(value: object, template: object) -> object:
    if isinstance(template, bytes):
        binary = _binary_from_json(value)
        if binary is not None:
            return type(template)(binary)
        if not isinstance(value, str):
            raise NeteaseWorldDataEditError("字符串值必须保持为 JSON 字符串")
        return type(template)(value.encode("utf-8"))
    if isinstance(template, _MapPairs):
        return _map_pairs_from_json(value, template)
    if isinstance(template, list):
        if not isinstance(value, list):
            raise NeteaseWorldDataEditError("数组值必须保持为 JSON 数组")
        return [
            _from_json(item, template[index] if index < len(template) else None)
            for index, item in enumerate(value)
        ]
    if isinstance(template, tuple) and len(template) == 3 and template[0] == "$ext":
        ext = _ext_from_json(value)
        if ext is None:
            raise NeteaseWorldDataEditError("扩展值必须保留 $ext/$data 结构")
        return ext
    return _from_untyped_json(value)


class _MessagePackWriter:
    def __init__(self) -> None:
        self._items = 0

    def write(self, value: object) -> bytes:
        encoded = self._value(value, 0)
        if len(encoded) > LEVEL_DB_MAX_SCRIPT_BYTES:
            raise NeteaseWorldDataEditError("编码后的 scriptData 超过安全大小上限")
        return encoded

    def _track(self, depth: int) -> None:
        if depth > LEVEL_DAT_MAX_DEPTH:
            raise NeteaseWorldDataEditError("MessagePack 嵌套深度超过安全上限")
        self._items += 1
        if self._items > LEVEL_DB_MAX_MESSAGEPACK_ITEMS:
            raise NeteaseWorldDataEditError("MessagePack 总元素数量超过安全上限")

    def _value(self, value: object, depth: int) -> bytes:  # noqa: PLR0911
        self._track(depth)
        if value is None:
            return b"\xc0"
        if value is False:
            return b"\xc2"
        if value is True:
            return b"\xc3"
        if isinstance(value, int):
            return self._integer(value)
        if isinstance(value, float):
            return b"\xcb" + struct.pack(">d", value)
        if isinstance(value, str):
            return self._bytes(value.encode("utf-8"))
        if isinstance(value, _MessagePackBinary):
            return self._binary(value)
        if isinstance(value, bytes):
            return self._bytes(value)
        if isinstance(value, _MapPairs):
            return self._map(value, depth)
        if isinstance(value, list):
            return self._array(value, depth)
        if isinstance(value, tuple) and len(value) == 3 and value[0] == "$ext":
            return self._extension(int(value[1]), bytes(value[2]))
        raise NeteaseWorldDataEditError(f"无法编码 MessagePack 类型 {type(value)!r}")

    @staticmethod
    def _integer(value: int) -> bytes:
        if 0 <= value <= 0x7F:
            return bytes([value])
        if -32 <= value < 0:
            return bytes([value + 256])
        for marker, size, signed, lower, upper in (
            (0xCC, 1, False, 0, 0xFF),
            (0xCD, 2, False, 0, 0xFFFF),
            (0xCE, 4, False, 0, 0xFFFFFFFF),
            (0xCF, 8, False, 0, 0xFFFFFFFFFFFFFFFF),
            (0xD0, 1, True, -0x80, 0x7F),
            (0xD1, 2, True, -0x8000, 0x7FFF),
            (0xD2, 4, True, -0x80000000, 0x7FFFFFFF),
            (0xD3, 8, True, -0x8000000000000000, 0x7FFFFFFFFFFFFFFF),
        ):
            if lower <= value <= upper:
                return bytes([marker]) + value.to_bytes(size, "big", signed=signed)
        raise NeteaseWorldDataEditError("整数超出 MessagePack 64 位范围")

    @staticmethod
    def _bytes(value: bytes) -> bytes:
        size = len(value)
        if size <= 31:
            return bytes([0xA0 | size]) + value
        if size <= 0xFF:
            return b"\xd9" + bytes([size]) + value
        if size <= 0xFFFF:
            return b"\xda" + struct.pack(">H", size) + value
        if size <= 0xFFFFFFFF:
            return b"\xdb" + struct.pack(">I", size) + value
        raise NeteaseWorldDataEditError("字符串超过 MessagePack 长度上限")

    @staticmethod
    def _binary(value: bytes) -> bytes:
        size = len(value)
        if size <= 0xFF:
            return b"\xc4" + bytes([size]) + value
        if size <= 0xFFFF:
            return b"\xc5" + struct.pack(">H", size) + value
        if size <= 0xFFFFFFFF:
            return b"\xc6" + struct.pack(">I", size) + value
        raise NeteaseWorldDataEditError("二进制值超过 MessagePack 长度上限")

    def _array(self, value: list[object], depth: int) -> bytes:
        size = len(value)
        if size > LEVEL_DAT_MAX_COLLECTION_ITEMS:
            raise NeteaseWorldDataEditError("数组数量超过安全上限")
        header = (
            bytes([0x90 | size])
            if size <= 15
            else b"\xdc" + struct.pack(">H", size)
            if size <= 0xFFFF
            else b"\xdd" + struct.pack(">I", size)
        )
        return header + b"".join(self._value(item, depth + 1) for item in value)

    def _map(self, value: _MapPairs, depth: int) -> bytes:
        size = len(value)
        if size > LEVEL_DAT_MAX_COLLECTION_ITEMS:
            raise NeteaseWorldDataEditError("对象数量超过安全上限")
        header = (
            bytes([0x80 | size])
            if size <= 15
            else b"\xde" + struct.pack(">H", size)
            if size <= 0xFFFF
            else b"\xdf" + struct.pack(">I", size)
        )
        return header + b"".join(
            self._value(key, depth + 1) + self._value(item, depth + 1)
            for key, item in value
        )

    @staticmethod
    def _extension(ext_type: int, value: bytes) -> bytes:
        size = len(value)
        fixed = {1: 0xD4, 2: 0xD5, 4: 0xD6, 8: 0xD7, 16: 0xD8}
        if size in fixed:
            return bytes([fixed[size], ext_type & 0xFF]) + value
        if size <= 0xFF:
            return b"\xc7" + bytes([size, ext_type & 0xFF]) + value
        if size <= 0xFFFF:
            return b"\xc8" + struct.pack(">H", size) + bytes([ext_type & 0xFF]) + value
        return b"\xc9" + struct.pack(">I", size) + bytes([ext_type & 0xFF]) + value


def _replace_message_pack(original: bytes, payload: bytes) -> bytes:
    offset = 1
    root_name_size = int.from_bytes(original[offset:offset + 2], "little")
    offset += 2 + root_name_size + 1
    name_size = int.from_bytes(original[offset:offset + 2], "little")
    size_offset = offset + 2 + name_size
    old_size = int.from_bytes(original[size_offset:size_offset + 4], "little")
    old_end = size_offset + 4 + old_size
    return original[:size_offset] + struct.pack("<I", len(payload)) + payload + original[old_end:]


def _change_map(changes: list[dict[str, object]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for change in changes:
        token = str(change.get("token", ""))
        if not token.startswith("extra:") or token in result:
            raise NeteaseWorldDataEditError("DB 修改项 token 无效或重复")
        result[token] = str(change.get("value", ""))
    if not result:
        raise NeteaseWorldDataEditError("没有需要保存的世界数据库修改")
    return result


def apply_extra_data_edits(
    original: bytes, changes: list[dict[str, object]]
) -> bytes:
    """在保留顶层键与原始值类型的前提下应用 JSON 修改。"""

    root = _MessagePackReader(_extract_message_pack(original)).read()
    if not isinstance(root, _MapPairs):
        raise NeteaseWorldDataEditError("scriptData MessagePack 根对象不是 Map")
    pending = _change_map(changes)
    updated = _MapPairs()
    for key, value in root:
        token = "extra:db.scriptData" + _path_segment(_json_value(key))
        edited = pending.pop(token, None)
        updated.append((key, value if edited is None else _from_json(_parse_json(edited), value)))
    if pending:
        raise NeteaseWorldDataEditError("DB 修改目标已变化，请重新读取后再编辑")
    payload = _MessagePackWriter().write(updated)
    encoded = _replace_message_pack(original, payload)
    _MessagePackReader(_extract_message_pack(encoded)).read()
    return encoded


def _checked_current_value(
    db_path: Path,
    expected_sequence: int,
    expected_fingerprint: str,
) -> bytes:
    current = read_current_value(db_path, SCRIPT_DATA_KEY)
    if current is None or current.deleted or current.value is None:
        raise NeteaseWorldDataEditError("DB 中当前没有可编辑的 scriptData")
    fingerprint = hashlib.sha256(current.value).hexdigest()
    if current.sequence != expected_sequence or fingerprint != expected_fingerprint:
        raise NeteaseWorldDataEditError("世界数据库已变化，请重新读取后再编辑")
    return current.value


def save_netease_world_data_edits(
    level_path: Path,
    expected_sequence: int,
    expected_fingerprint: str,
    changes: list[dict[str, object]],
) -> tuple[NeteaseWorldDataView, Path, int]:
    """修改 scriptData，整库备份后写入 WAL，并重读验证。"""

    db_path = level_path.parent / "db"
    original = _checked_current_value(
        db_path, expected_sequence, expected_fingerprint
    )
    updated = apply_extra_data_edits(original, changes)
    try:
        _saved, backup_path = write_current_value(
            db_path,
            SCRIPT_DATA_KEY,
            updated,
            expected_sequence=expected_sequence,
            expected_fingerprint=expected_fingerprint,
            backup_suffix=LEVEL_DB_BACKUP_SUFFIX,
        )
    except LevelDbWriteError as error:
        raise NeteaseWorldDataEditError(str(error)) from error
    view = load_netease_world_data(level_path)
    if view.summary.get("extraDataFingerprint") != hashlib.sha256(updated).hexdigest():
        raise NeteaseWorldDataEditError("保存后重新载入的 scriptData 指纹不一致")
    return view, backup_path, len(changes)


__all__ = [
    "NeteaseWorldDataEditError",
    "apply_extra_data_edits",
    "save_netease_world_data_edits",
]
