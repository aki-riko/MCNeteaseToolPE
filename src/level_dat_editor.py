# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""NBT 值的类型安全编辑与 Bedrock level.dat 序列化。"""

from __future__ import annotations

from dataclasses import replace
import json
import logging
import math
import re
import struct

from .level_dat import (
    DECIMAL_LIMITS,
    EDITABLE_TAG_TYPES,
    INTEGER_RANGES,
    LevelDatDocument,
    NbtList,
    NbtTag,
)


LOGGER = logging.getLogger(__name__)
DECIMAL_PATTERN = re.compile(
    r"[+-]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:[eE][+-]?\d+)?"
)


class LevelDatEditError(ValueError):
    """用户编辑无法按原 NBT 类型安全保存。"""


def _parse_integer(tag_type: int, text: str) -> int:
    value_text = text.strip()
    if not re.fullmatch(r"[+-]?\d+", value_text):
        raise LevelDatEditError("请输入十进制整数")
    value = int(value_text, 10)
    minimum, maximum = INTEGER_RANGES[tag_type]
    if not minimum <= value <= maximum:
        raise LevelDatEditError(f"整数必须在 {minimum} 到 {maximum} 之间")
    return value


def _parse_decimal(tag_type: int, text: str) -> float:
    value_text = text.strip()
    if not DECIMAL_PATTERN.fullmatch(value_text):
        raise LevelDatEditError("请输入有效数字")
    value = float(value_text)
    if not math.isfinite(value):
        raise LevelDatEditError("请输入有限数字")
    limit = DECIMAL_LIMITS[tag_type]
    if abs(value) > limit:
        raise LevelDatEditError(f"数字绝对值不能超过 {limit}")
    return value


def parse_scalar_value(tag_type: int, text: str) -> object:
    """按原 NBT 标量类型解析并校验用户文本。"""

    if tag_type in INTEGER_RANGES:
        return _parse_integer(tag_type, text)
    if tag_type in DECIMAL_LIMITS:
        return _parse_decimal(tag_type, text)
    if tag_type == 8:
        encoded = text.encode("utf-8")
        if len(encoded) > 65_535:
            raise LevelDatEditError("字符串的 UTF-8 数据不能超过 65535 字节")
        return text
    raise LevelDatEditError("该结构节点不能直接编辑")


def _decode_token(token: str) -> tuple[tuple[str, int], ...]:
    try:
        document = json.loads(token)
    except json.JSONDecodeError as error:
        LOGGER.warning("解析 level.dat 编辑节点标识失败：%s", token, exc_info=True)
        raise LevelDatEditError("编辑节点标识无效") from error
    if not isinstance(document, list) or not document:
        raise LevelDatEditError("编辑节点标识不能为空")
    steps: list[tuple[str, int]] = []
    for step in document:
        if not _valid_step(step):
            raise LevelDatEditError("编辑节点标识包含无效路径")
        steps.append((step[0], step[1]))
    return tuple(steps)


def _valid_step(step: object) -> bool:
    return (
        isinstance(step, list)
        and len(step) == 2
        and step[0] in {"c", "l", "a"}
        and isinstance(step[1], int)
        and not isinstance(step[1], bool)
        and step[1] >= 0
    )


def _checked_index(index: int, length: int) -> None:
    if index >= length:
        raise LevelDatEditError("编辑节点已不存在，请重新读取文件")


def _replace_tag(
    tag: NbtTag,
    steps: tuple[tuple[str, int], ...],
    text: str,
) -> NbtTag:
    if not steps:
        if tag.tag_type not in EDITABLE_TAG_TYPES:
            raise LevelDatEditError("该结构节点不能直接编辑")
        return replace(tag, value=parse_scalar_value(tag.tag_type, text))
    kind, index = steps[0]
    if tag.tag_type == 10 and kind == "c":
        return _replace_compound_child(tag, index, steps[1:], text)
    if tag.tag_type == 9 and kind == "l":
        return _replace_list_item(tag, index, steps[1:], text)
    if tag.tag_type in {7, 11, 12} and kind == "a":
        return _replace_array_item(tag, index, steps[1:], text)
    raise LevelDatEditError("编辑节点路径与当前文件结构不一致")


def _replace_compound_child(tag, index, remaining, text) -> NbtTag:
    children = tag.value
    assert isinstance(children, tuple)
    _checked_index(index, len(children))
    updated = list(children)
    updated[index] = _replace_tag(children[index], remaining, text)
    return replace(tag, value=tuple(updated))


def _replace_list_item(tag, index, remaining, text) -> NbtTag:
    value = tag.value
    assert isinstance(value, NbtList)
    _checked_index(index, len(value.items))
    items = list(value.items)
    wrapped = NbtTag(value.element_type, "", items[index])
    items[index] = _replace_tag(wrapped, remaining, text).value
    return replace(tag, value=replace(value, items=tuple(items)))


def _replace_array_item(tag, index, remaining, text) -> NbtTag:
    values = tag.value
    assert isinstance(values, tuple)
    _checked_index(index, len(values))
    element_types = {7: 1, 11: 3, 12: 4}
    wrapped = NbtTag(element_types[tag.tag_type], "", values[index])
    updated = list(values)
    updated[index] = _replace_tag(wrapped, remaining, text).value
    return replace(tag, value=tuple(updated))


def apply_text_edits(
    document: LevelDatDocument,
    changes: list[dict[str, object]],
) -> LevelDatDocument:
    """按稳定节点标识在不可变 NBT 文档上应用一组文本修改。"""

    if not changes:
        raise LevelDatEditError("没有需要保存的修改")
    root = document.root
    seen: set[str] = set()
    for change in changes:
        token, value = _change_fields(change)
        if token in seen:
            raise LevelDatEditError("同一节点不能重复提交修改")
        seen.add(token)
        root = _replace_tag(root, _decode_token(token), value)
    return replace(document, root=root)


def _change_fields(change: object) -> tuple[str, str]:
    if not isinstance(change, dict):
        raise LevelDatEditError("修改数据格式无效")
    token = change.get("token")
    value = change.get("value")
    if not isinstance(token, str) or not isinstance(value, str):
        raise LevelDatEditError("修改数据缺少节点或文本值")
    return token, value


class _LittleEndianNbtWriter:
    def __init__(self) -> None:
        self._data = bytearray()

    def _pack(self, format_code: str, value: object) -> None:
        self._data.extend(struct.pack(f"<{format_code}", value))

    def _string(self, value: str) -> None:
        encoded = value.encode("utf-8")
        if len(encoded) > 65_535:
            raise LevelDatEditError("NBT 字符串的 UTF-8 数据超过 65535 字节")
        self._pack("H", len(encoded))
        self._data.extend(encoded)

    def _count(self, value: int) -> None:
        if not 0 <= value <= 2_147_483_647:
            raise LevelDatEditError("NBT 集合元素数量超出 32 位范围")
        self._pack("i", value)

    def named_tag(self, tag: NbtTag) -> None:
        if not 1 <= tag.tag_type <= 12:
            raise LevelDatEditError("命名标签类型无效")
        self._pack("B", tag.tag_type)
        self._string(tag.name)
        self._payload(tag.tag_type, tag.value)

    def _payload(self, tag_type: int, value: object) -> None:
        primitive_formats = {1: "b", 2: "h", 3: "i", 4: "q", 5: "f", 6: "d"}
        if tag_type in primitive_formats:
            self._pack(primitive_formats[tag_type], value)
            return
        if tag_type == 8:
            self._string(str(value))
            return
        self._complex_payload(tag_type, value)

    def _complex_payload(self, tag_type: int, value: object) -> None:
        if tag_type == 7:
            self._numeric_array("b", value)
        elif tag_type == 9:
            self._list(value)
        elif tag_type == 10:
            self._compound(value)
        elif tag_type == 11:
            self._numeric_array("i", value)
        elif tag_type == 12:
            self._numeric_array("q", value)
        else:
            raise LevelDatEditError(f"无法序列化 NBT 标签类型 {tag_type}")

    def _numeric_array(self, format_code: str, value: object) -> None:
        assert isinstance(value, tuple)
        self._count(len(value))
        for item in value:
            self._pack(format_code, item)

    def _list(self, value: object) -> None:
        assert isinstance(value, NbtList)
        self._pack("B", value.element_type)
        self._count(len(value.items))
        for item in value.items:
            self._payload(value.element_type, item)

    def _compound(self, value: object) -> None:
        assert isinstance(value, tuple)
        for child in value:
            assert isinstance(child, NbtTag)
            self.named_tag(child)
        self._pack("B", 0)

    def bytes(self) -> bytes:
        return bytes(self._data)


def serialize_level_dat(document: LevelDatDocument) -> bytes:
    """把完整文档序列化为 Bedrock 小端 level.dat 字节。"""

    if document.root.tag_type != 10:
        raise LevelDatEditError("level.dat 根标签必须是 Compound")
    writer = _LittleEndianNbtWriter()
    writer.named_tag(document.root)
    payload = writer.bytes()
    if len(payload) > 4_294_967_295:
        raise LevelDatEditError("NBT 数据超过 level.dat 头部可表示范围")
    return struct.pack("<II", document.format_version, len(payload)) + payload


__all__ = [
    "LevelDatEditError",
    "apply_text_edits",
    "parse_scalar_value",
    "serialize_level_dat",
]
