# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bedrock ``level.dat`` 与小端 NBT 的解析及编辑视图模型。"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import struct


LOGGER = logging.getLogger(__name__)
TAG_NAMES = (
    "TAG_End",
    "TAG_Byte",
    "TAG_Short",
    "TAG_Int",
    "TAG_Long",
    "TAG_Float",
    "TAG_Double",
    "TAG_Byte_Array",
    "TAG_String",
    "TAG_List",
    "TAG_Compound",
    "TAG_Int_Array",
    "TAG_Long_Array",
)

INTEGER_RANGES = {
    1: (-128, 127),
    2: (-32_768, 32_767),
    3: (-2_147_483_648, 2_147_483_647),
    4: (-9_223_372_036_854_775_808, 9_223_372_036_854_775_807),
}
DECIMAL_LIMITS = {
    5: 3.4028234663852886e38,
    6: 1.7976931348623157e308,
}
EDITABLE_TAG_TYPES = frozenset({1, 2, 3, 4, 5, 6, 8})


class LevelDatParseError(ValueError):
    """输入不是完整、受支持的 Bedrock level.dat。"""


@dataclass(frozen=True)
class NbtList:
    element_type: int
    items: tuple[object, ...]


@dataclass(frozen=True)
class NbtTag:
    tag_type: int
    name: str
    value: object


@dataclass(frozen=True)
class LevelDatDocument:
    format_version: int
    declared_payload_size: int
    root: NbtTag


class _LittleEndianNbtReader:
    def __init__(self, data: bytes, max_depth: int, max_items: int) -> None:
        self._data = data
        self._offset = 0
        self._max_depth = max_depth
        self._max_items = max_items

    @property
    def remaining(self) -> int:
        return len(self._data) - self._offset

    def _take(self, size: int) -> bytes:
        end = self._offset + size
        if size < 0 or end > len(self._data):
            raise LevelDatParseError(f"NBT 在偏移 {self._offset} 处意外结束")
        value = self._data[self._offset:end]
        self._offset = end
        return value

    def _unpack(self, format_code: str) -> object:
        size = struct.calcsize(f"<{format_code}")
        return struct.unpack(f"<{format_code}", self._take(size))[0]

    def _string(self) -> str:
        size = int(self._unpack("H"))
        raw = self._take(size)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as error:
            LOGGER.warning("NBT 字符串不是有效 UTF-8，偏移：%s", self._offset, exc_info=True)
            raise LevelDatParseError("NBT 字符串不是有效 UTF-8") from error

    def _count(self, label: str) -> int:
        count = int(self._unpack("i"))
        if count < 0:
            raise LevelDatParseError(f"{label} 的元素数量不能为负数")
        if count > self._max_items:
            raise LevelDatParseError(f"{label} 的元素数量 {count} 超过安全上限")
        return count

    def read_root(self) -> NbtTag:
        tag_type = int(self._unpack("B"))
        if tag_type != 10:
            raise LevelDatParseError("level.dat 根标签必须是 TAG_Compound")
        root = NbtTag(tag_type, self._string(), self._payload(tag_type, 0))
        if self.remaining:
            raise LevelDatParseError(f"NBT 根标签后仍有 {self.remaining} 字节未解析")
        return root

    def _payload(self, tag_type: int, depth: int) -> object:
        if depth > self._max_depth:
            raise LevelDatParseError("NBT 嵌套深度超过安全上限")
        if tag_type == 1:
            return self._unpack("b")
        if tag_type == 2:
            return self._unpack("h")
        if tag_type == 3:
            return self._unpack("i")
        if tag_type == 4:
            return self._unpack("q")
        if tag_type == 5:
            return self._unpack("f")
        if tag_type == 6:
            return self._unpack("d")
        return self._complex_payload(tag_type, depth)

    def _complex_payload(self, tag_type: int, depth: int) -> object:
        if tag_type == 7:
            return self._numeric_array("b", "TAG_Byte_Array")
        if tag_type == 8:
            return self._string()
        if tag_type == 9:
            return self._list(depth)
        if tag_type == 10:
            return self._compound(depth)
        if tag_type == 11:
            return self._numeric_array("i", "TAG_Int_Array")
        if tag_type == 12:
            return self._numeric_array("q", "TAG_Long_Array")
        raise LevelDatParseError(f"不支持的 NBT 标签类型：{tag_type}")

    def _list(self, depth: int) -> NbtList:
        element_type = int(self._unpack("B"))
        count = self._count("TAG_List")
        if element_type == 0 and count:
            raise LevelDatParseError("非空 TAG_List 不能使用 TAG_End 元素类型")
        if element_type >= len(TAG_NAMES):
            raise LevelDatParseError(f"TAG_List 使用了未知元素类型：{element_type}")
        items = tuple(self._payload(element_type, depth + 1) for _ in range(count))
        return NbtList(element_type, items)

    def _compound(self, depth: int) -> tuple[NbtTag, ...]:
        items: list[NbtTag] = []
        while True:
            tag_type = int(self._unpack("B"))
            if tag_type == 0:
                return tuple(items)
            if len(items) >= self._max_items:
                raise LevelDatParseError("TAG_Compound 的标签数量超过安全上限")
            if tag_type >= len(TAG_NAMES):
                raise LevelDatParseError(f"TAG_Compound 使用了未知标签类型：{tag_type}")
            name = self._string()
            items.append(NbtTag(tag_type, name, self._payload(tag_type, depth + 1)))

    def _numeric_array(self, format_code: str, label: str) -> tuple[object, ...]:
        count = self._count(label)
        item_size = struct.calcsize(f"<{format_code}")
        if count * item_size > self.remaining:
            raise LevelDatParseError(f"{label} 数据长度不足")
        return tuple(self._unpack(format_code) for _ in range(count))


def parse_level_dat(
    data: bytes,
    *,
    max_depth: int,
    max_items: int,
) -> LevelDatDocument:
    """解析完整的 Bedrock level.dat 字节，且不修改输入。"""

    if len(data) < 8:
        raise LevelDatParseError("文件不足 8 字节，缺少 Bedrock level.dat 头")
    version, declared_size = struct.unpack("<II", data[:8])
    payload = data[8:]
    if declared_size != len(payload):
        replacement_count = payload.count(b"\xef\xbf\xbd")
        if replacement_count >= 3:
            raise LevelDatParseError(
                "level.dat 疑似被按文本方式改写："
                f"头部声明 {declared_size} 字节，实际 {len(payload)} 字节，"
                f"并发现 {replacement_count} 处 UTF-8 替换字符；"
                "请从未损坏的 level.dat 或 level.dat_old 恢复"
            )
        raise LevelDatParseError(
            f"头部声明 NBT 为 {declared_size} 字节，实际为 {len(payload)} 字节"
        )
    reader = _LittleEndianNbtReader(payload, max_depth, max_items)
    return LevelDatDocument(version, declared_size, reader.read_root())


def _tag_value_text(tag: NbtTag) -> str:
    if tag.tag_type == 10:
        return f"{len(tag.value)} 个标签"
    if tag.tag_type == 9:
        value = tag.value
        assert isinstance(value, NbtList)
        return f"{len(value.items)} 项"
    if tag.tag_type in {7, 11, 12}:
        return f"{len(tag.value)} 项"
    return str(tag.value)


class _RowBuilder:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    def add(
        self,
        tag: NbtTag,
        path: str,
        depth: int,
        steps: tuple[tuple[str, int], ...],
        inherited_netease: bool = False,
    ) -> None:
        is_netease = inherited_netease or tag.name.casefold().startswith("netease")
        self.rows.append(self._row(tag, path, depth, steps, is_netease))
        if tag.tag_type == 10:
            self._add_compound(tag, path, depth, steps, is_netease)
        elif tag.tag_type == 9:
            self._add_list(tag, path, depth, steps, is_netease)
        elif tag.tag_type in {7, 11, 12}:
            self._add_array(tag, path, depth, steps, is_netease)

    def _row(
        self,
        tag: NbtTag,
        path: str,
        depth: int,
        steps: tuple[tuple[str, int], ...],
        is_netease: bool,
    ) -> dict[str, object]:
        row = {
            "path": path,
            "name": tag.name,
            "value": _tag_value_text(tag),
            "token": json.dumps(steps, separators=(",", ":")),
            "depth": depth,
            "isNetease": is_netease,
            "editable": tag.tag_type in EDITABLE_TAG_TYPES,
            "container": tag.tag_type in {7, 9, 10, 11, 12},
            "sourceKind": "levelDat",
        }
        row.update(_editor_metadata(tag.tag_type))
        return row

    def _add_compound(
        self,
        tag: NbtTag,
        path: str,
        depth: int,
        steps: tuple[tuple[str, int], ...],
        is_netease: bool,
    ) -> None:
        children = tag.value
        assert isinstance(children, tuple)
        for index, child in enumerate(children):
            assert isinstance(child, NbtTag)
            child_steps = steps + (("c", index),)
            self.add(child, f"{path}.{child.name}", depth + 1, child_steps, is_netease)

    def _add_list(
        self,
        tag: NbtTag,
        path: str,
        depth: int,
        steps: tuple[tuple[str, int], ...],
        is_netease: bool,
    ) -> None:
        value = tag.value
        assert isinstance(value, NbtList)
        for index, item in enumerate(value.items):
            child = NbtTag(value.element_type, f"[{index}]", item)
            child_steps = steps + (("l", index),)
            self.add(child, f"{path}[{index}]", depth + 1, child_steps, is_netease)

    def _add_array(
        self,
        tag: NbtTag,
        path: str,
        depth: int,
        steps: tuple[tuple[str, int], ...],
        is_netease: bool,
    ) -> None:
        element_types = {7: 1, 11: 3, 12: 4}
        values = tag.value
        assert isinstance(values, tuple)
        for index, item in enumerate(values):
            child = NbtTag(element_types[tag.tag_type], f"[{index}]", item)
            child_steps = steps + (("a", index),)
            self.add(child, f"{path}[{index}]", depth + 1, child_steps, is_netease)


def _editor_metadata(tag_type: int) -> dict[str, object]:
    if tag_type in {1, 2, 3}:
        minimum, maximum = INTEGER_RANGES[tag_type]
        return _control_metadata("integer", minimum, maximum, 0, 1)
    if tag_type == 4:
        return _control_metadata("long", 0, 0, 0, 1)
    if tag_type in DECIMAL_LIMITS:
        limit = DECIMAL_LIMITS[tag_type]
        decimals = 9 if tag_type == 5 else 17
        return _control_metadata("decimal", -limit, limit, decimals, 0.1)
    if tag_type == 8:
        return _control_metadata("text", 0, 0, 0, 0)
    return _control_metadata("none", 0, 0, 0, 0)


def _control_metadata(
    kind: str,
    minimum: int | float,
    maximum: int | float,
    decimals: int,
    step_size: int | float,
) -> dict[str, object]:
    return {
        "editorKind": kind,
        "minimum": minimum,
        "maximum": maximum,
        "decimals": decimals,
        "stepSize": step_size,
    }


def build_view_rows(
    document: LevelDatDocument,
) -> list[dict[str, object]]:
    """将嵌套 NBT 转为 QML 可直接消费的路径行。"""

    builder = _RowBuilder()
    root_items = document.root.value
    assert isinstance(root_items, tuple)
    for index, tag in enumerate(root_items):
        assert isinstance(tag, NbtTag)
        builder.add(tag, tag.name, 0, (("c", index),))
    return builder.rows


__all__ = [
    "LevelDatDocument",
    "LevelDatParseError",
    "NbtList",
    "NbtTag",
    "TAG_NAMES",
    "DECIMAL_LIMITS",
    "EDITABLE_TAG_TYPES",
    "INTEGER_RANGES",
    "build_view_rows",
    "parse_level_dat",
]
