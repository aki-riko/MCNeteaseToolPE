# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""只读解析 Bedrock/网易 LevelDB 中某个键的当前有效版本。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import struct
import zlib

from .config import (
    LEVEL_DB_MAX_BLOCK_BYTES,
    LEVEL_DB_MAX_LOG_BYTES,
    LEVEL_DB_MAX_MANIFEST_BYTES,
    LEVEL_DB_MAX_TABLE_BYTES,
    LEVEL_DB_MAX_TABLES,
)


_LOG_BLOCK_BYTES = 32_768
_LOG_HEADER_BYTES = 7
_TABLE_FOOTER_BYTES = 48
_TABLE_MAGIC = 0xDB4775248B80FB57
_TABLE_TRAILER_BYTES = 5
_FILE_NUMBER = re.compile(r"^(\d+)\.(?:ldb|sst|log)$", re.IGNORECASE)
_MANIFEST_NAME = re.compile(r"^MANIFEST-\d+$")
_CRC32C_POLYNOMIAL = 0x82F63B78


def _crc32c_table() -> tuple[int, ...]:
    values = []
    for index in range(256):
        checksum = index
        for _ in range(8):
            checksum = (
                (checksum >> 1) ^ _CRC32C_POLYNOMIAL
                if checksum & 1
                else checksum >> 1
            )
        values.append(checksum)
    return tuple(values)


_CRC32C_TABLE = _crc32c_table()
_FileStamp = tuple[int, int]


class LevelDbReadError(ValueError):
    """LevelDB 文件缺失、变化或使用了当前不支持的格式。"""


@dataclass(frozen=True, slots=True)
class LevelDbValue:
    sequence: int
    value: bytes | None
    source_file: str

    @property
    def deleted(self) -> bool:
        return self.value is None


@dataclass(slots=True)
class _ManifestState:
    log_number: int | None = None
    previous_log_number: int = 0
    last_sequence: int = 0
    live_files: set[tuple[int, int]] | None = None

    def __post_init__(self) -> None:
        if self.live_files is None:
            self.live_files = set()


def _varint(data: bytes, offset: int, *, bits: int = 64) -> tuple[int, int]:
    value = 0
    shift = 0
    maximum_bytes = (bits + 6) // 7
    for _ in range(maximum_bytes):
        if offset >= len(data):
            raise LevelDbReadError("LevelDB varint 意外结束")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
    raise LevelDbReadError("LevelDB varint 超过安全长度")


def _slice(data: bytes, offset: int) -> tuple[bytes, int]:
    size, offset = _varint(data, offset, bits=32)
    end = offset + size
    if end > len(data):
        raise LevelDbReadError("LevelDB 长度前缀超出文件范围")
    return data[offset:end], end


def _file_stamp(path: Path, label: str) -> _FileStamp:
    try:
        state = path.stat()
    except OSError as error:
        raise LevelDbReadError(f"无法读取 {label}：{error}") from error
    return state.st_size, state.st_mtime_ns


def _stable_read(
    path: Path,
    maximum: int,
    label: str,
    observed: dict[Path, _FileStamp] | None = None,
) -> bytes:
    try:
        before = path.stat()
        if before.st_size > maximum:
            raise LevelDbReadError(f"{label} 超过读取上限 {maximum} 字节")
        data = path.read_bytes()
        after = path.stat()
    except OSError as error:
        raise LevelDbReadError(f"无法读取 {label}：{error}") from error
    stamp = (after.st_size, after.st_mtime_ns)
    if (before.st_size, before.st_mtime_ns) != stamp:
        raise LevelDbReadError(f"读取期间 {label} 已变化，请关闭世界后重试")
    if observed is not None:
        observed[path] = stamp
    return data


def _crc32c(data: bytes, checksum: int = 0) -> int:
    current = checksum ^ 0xFFFFFFFF
    for byte in data:
        current = _CRC32C_TABLE[(current ^ byte) & 0xFF] ^ (current >> 8)
    return current ^ 0xFFFFFFFF


def _masked_crc32c(checksum: int) -> int:
    rotated = ((checksum >> 15) | (checksum << 17)) & 0xFFFFFFFF
    return (rotated + 0xA282EAD8) & 0xFFFFFFFF


def _verify_checksum(stored: bytes, chunks: tuple[bytes, ...], label: str) -> None:
    checksum = 0
    for chunk in chunks:
        checksum = _crc32c(chunk, checksum)
    if int.from_bytes(stored, "little") != _masked_crc32c(checksum):
        raise LevelDbReadError(f"{label} 校验和不匹配")


def _verify_snapshot(observed: dict[Path, _FileStamp]) -> None:
    for path, expected in observed.items():
        current = _file_stamp(path, path.name)
        if current != expected:
            raise LevelDbReadError(
                f"读取期间 {path.name} 已变化，请关闭世界后重试"
            )


def _logical_records(data: bytes) -> list[bytes]:
    records: list[bytes] = []
    fragment: bytearray | None = None
    for block_start in range(0, len(data), _LOG_BLOCK_BYTES):
        block = data[block_start:block_start + _LOG_BLOCK_BYTES]
        offset = 0
        while offset + _LOG_HEADER_BYTES <= len(block):
            length = int.from_bytes(block[offset + 4:offset + 6], "little")
            record_type = block[offset + 6]
            if length == 0 and record_type == 0:
                break
            end = offset + _LOG_HEADER_BYTES + length
            if record_type not in {1, 2, 3, 4} or end > len(block):
                raise LevelDbReadError("LevelDB 日志物理记录损坏")
            payload = block[offset + _LOG_HEADER_BYTES:end]
            _verify_checksum(
                block[offset:offset + 4],
                (bytes([record_type]), payload),
                "LevelDB 日志物理记录",
            )
            if record_type == 1:
                if fragment is not None:
                    raise LevelDbReadError("LevelDB 日志分片未正常结束")
                records.append(payload)
            elif record_type == 2:
                if fragment is not None:
                    raise LevelDbReadError("LevelDB 日志出现重复首分片")
                fragment = bytearray(payload)
            elif record_type == 3:
                if fragment is None:
                    raise LevelDbReadError("LevelDB 日志缺少首分片")
                fragment.extend(payload)
            else:
                if fragment is None:
                    raise LevelDbReadError("LevelDB 日志缺少首分片")
                fragment.extend(payload)
                records.append(bytes(fragment))
                fragment = None
            offset = end
    if fragment is not None:
        raise LevelDbReadError("LevelDB 日志尾部分片不完整")
    return records


def _parse_version_edit(record: bytes, state: _ManifestState) -> None:
    offset = 0
    assert state.live_files is not None
    while offset < len(record):
        tag, offset = _varint(record, offset, bits=32)
        if tag == 1:
            _comparator, offset = _slice(record, offset)
        elif tag in {2, 3, 4, 9}:
            value, offset = _varint(record, offset)
            if tag == 2:
                state.log_number = value
            elif tag == 4:
                state.last_sequence = value
            elif tag == 9:
                state.previous_log_number = value
        elif tag == 5:
            _level, offset = _varint(record, offset, bits=32)
            _key, offset = _slice(record, offset)
        elif tag == 6:
            level, offset = _varint(record, offset, bits=32)
            number, offset = _varint(record, offset)
            state.live_files.discard((level, number))
        elif tag == 7:
            level, offset = _varint(record, offset, bits=32)
            number, offset = _varint(record, offset)
            _size, offset = _varint(record, offset)
            _smallest, offset = _slice(record, offset)
            _largest, offset = _slice(record, offset)
            state.live_files.add((level, number))
        else:
            raise LevelDbReadError(f"MANIFEST 包含未知 VersionEdit 标签 {tag}")


def _load_manifest(
    db_path: Path,
    observed: dict[Path, _FileStamp] | None = None,
) -> _ManifestState:
    current = _stable_read(db_path / "CURRENT", 1024, "CURRENT", observed)
    try:
        manifest_name = current.decode("ascii").strip()
    except UnicodeDecodeError as error:
        raise LevelDbReadError("CURRENT 不是有效 ASCII") from error
    if not _MANIFEST_NAME.fullmatch(manifest_name):
        raise LevelDbReadError("CURRENT 指向了无效 MANIFEST 文件")
    manifest = _stable_read(
        db_path / manifest_name,
        LEVEL_DB_MAX_MANIFEST_BYTES,
        manifest_name,
        observed,
    )
    state = _ManifestState()
    for record in _logical_records(manifest):
        _parse_version_edit(record, state)
    if state.log_number is None:
        raise LevelDbReadError("MANIFEST 缺少当前日志编号")
    assert state.live_files is not None
    if len(state.live_files) > LEVEL_DB_MAX_TABLES:
        raise LevelDbReadError("LevelDB 活动 SSTable 数量超过安全上限")
    return state


def _write_batch_versions(record: bytes, key: bytes, source: str) -> list[LevelDbValue]:
    if len(record) < 12:
        raise LevelDbReadError("LevelDB WriteBatch 头部不完整")
    first_sequence = int.from_bytes(record[:8], "little")
    count = int.from_bytes(record[8:12], "little")
    offset = 12
    versions: list[LevelDbValue] = []
    for index in range(count):
        if offset >= len(record):
            raise LevelDbReadError("LevelDB WriteBatch 条目数量不匹配")
        value_type = record[offset]
        offset += 1
        entry_key, offset = _slice(record, offset)
        entry_value: bytes | None = None
        if value_type == 1:
            entry_value, offset = _slice(record, offset)
        elif value_type != 0:
            raise LevelDbReadError(f"LevelDB WriteBatch 包含未知操作 {value_type}")
        if entry_key == key:
            versions.append(LevelDbValue(first_sequence + index, entry_value, source))
    if offset != len(record):
        raise LevelDbReadError("LevelDB WriteBatch 尾部存在未解析数据")
    return versions


def _log_versions(path: Path, key: bytes) -> list[LevelDbValue]:
    data = _stable_read(path, LEVEL_DB_MAX_LOG_BYTES, path.name)
    versions: list[LevelDbValue] = []
    for record in _logical_records(data):
        versions.extend(_write_batch_versions(record, key, path.name))
    return versions


def _inflate_raw(data: bytes) -> bytes:
    decoder = zlib.decompressobj(-zlib.MAX_WBITS)
    output = decoder.decompress(data, LEVEL_DB_MAX_BLOCK_BYTES + 1)
    if decoder.unconsumed_tail or len(output) > LEVEL_DB_MAX_BLOCK_BYTES:
        raise LevelDbReadError("LevelDB 压缩块解压后超过安全上限")
    if decoder.unused_data:
        raise LevelDbReadError("LevelDB 原始 DEFLATE 压缩块尾部存在多余数据")
    remaining = LEVEL_DB_MAX_BLOCK_BYTES + 1 - len(output)
    if remaining > 0:
        output += decoder.flush(remaining)
    if len(output) > LEVEL_DB_MAX_BLOCK_BYTES or not decoder.eof:
        raise LevelDbReadError("LevelDB 原始 DEFLATE 压缩块不完整")
    return output


def _block_entries(block: bytes) -> list[tuple[bytes, bytes]]:
    if len(block) < 4:
        raise LevelDbReadError("LevelDB 数据块过短")
    restart_count = int.from_bytes(block[-4:], "little")
    restart_start = len(block) - 4 - restart_count * 4
    if restart_count < 1 or restart_start < 0:
        raise LevelDbReadError("LevelDB 数据块重启点损坏")
    if int.from_bytes(block[restart_start:restart_start + 4], "little") != 0:
        raise LevelDbReadError("LevelDB 数据块首重启点不是零")
    entries: list[tuple[bytes, bytes]] = []
    previous = b""
    offset = 0
    while offset < restart_start:
        shared, offset = _varint(block, offset, bits=32)
        unique, offset = _varint(block, offset, bits=32)
        value_size, offset = _varint(block, offset, bits=32)
        end_key = offset + unique
        end_value = end_key + value_size
        if shared > len(previous) or end_value > restart_start:
            raise LevelDbReadError("LevelDB 数据块条目越界")
        full_key = previous[:shared] + block[offset:end_key]
        entries.append((full_key, block[end_key:end_value]))
        previous = full_key
        offset = end_value
    return entries


def _read_block(handle_data: bytes, file_data: bytes) -> bytes:
    offset, cursor = _varint(handle_data, 0)
    size, cursor = _varint(handle_data, cursor)
    if cursor != len(handle_data):
        raise LevelDbReadError("LevelDB BlockHandle 尾部存在数据")
    trailer = offset + size
    if size > LEVEL_DB_MAX_BLOCK_BYTES or trailer + _TABLE_TRAILER_BYTES > len(file_data):
        raise LevelDbReadError("LevelDB BlockHandle 超出 SSTable 范围")
    compressed = file_data[offset:trailer]
    compression_type = file_data[trailer]
    _verify_checksum(
        file_data[trailer + 1:trailer + _TABLE_TRAILER_BYTES],
        (compressed, bytes([compression_type])),
        "LevelDB SSTable block",
    )
    if compression_type == 0:
        return compressed
    if compression_type == 4:
        return _inflate_raw(compressed)
    raise LevelDbReadError(f"暂不支持 LevelDB 压缩类型 {compression_type}")


def _table_versions(path: Path, key: bytes) -> list[LevelDbValue]:
    data = _stable_read(path, LEVEL_DB_MAX_TABLE_BYTES, f"SSTable {path.name}")
    if len(data) < _TABLE_FOOTER_BYTES:
        raise LevelDbReadError(f"SSTable {path.name} 缺少 Footer")
    footer = data[-_TABLE_FOOTER_BYTES:]
    if int.from_bytes(footer[-8:], "little") != _TABLE_MAGIC:
        raise LevelDbReadError(f"SSTable {path.name} Magic 不匹配")
    _meta_offset, cursor = _varint(footer, 0)
    _meta_size, cursor = _varint(footer, cursor)
    index_offset, cursor = _varint(footer, cursor)
    index_size, _cursor = _varint(footer, cursor)
    index_handle = _encode_handle(index_offset, index_size)
    index_entries = _block_entries(_read_block(index_handle, data))
    if not index_entries:
        return []
    target_index = len(index_entries) - 1
    for index, (internal_key, _handle) in enumerate(index_entries):
        user_key = internal_key[:-8] if len(internal_key) >= 8 else internal_key
        if user_key >= key:
            target_index = index
            break
    candidates = range(max(0, target_index - 1), min(len(index_entries), target_index + 2))
    versions: list[LevelDbValue] = []
    for index in candidates:
        _separator, handle = index_entries[index]
        for internal_key, value in _block_entries(_read_block(handle, data)):
            if len(internal_key) < 8 or internal_key[:-8] != key:
                continue
            trailer = int.from_bytes(internal_key[-8:], "little")
            value_type = trailer & 0xFF
            if value_type not in {0, 1}:
                raise LevelDbReadError(f"SSTable 包含未知值类型 {value_type}")
            versions.append(
                LevelDbValue(trailer >> 8, value if value_type == 1 else None, path.name)
            )
    return versions


def _encode_handle(offset: int, size: int) -> bytes:
    return _encode_varint(offset) + _encode_varint(size)


def _encode_varint(value: int) -> bytes:
    output = bytearray()
    while value >= 0x80:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def _numbered_files(db_path: Path, suffix: str) -> dict[int, Path]:
    result: dict[int, Path] = {}
    for path in db_path.glob(f"*.{suffix}"):
        matched = _FILE_NUMBER.fullmatch(path.name)
        if matched:
            result[int(matched.group(1))] = path
    return result


def read_current_value(db_path: Path, key: bytes) -> LevelDbValue | None:
    """依据 CURRENT/MANIFEST 合并活动 SSTable 与 WAL，返回最高序列版本。"""

    db_path = db_path.expanduser().resolve()
    if not db_path.is_dir():
        raise LevelDbReadError("世界目录中没有 db 文件夹")
    observed: dict[Path, _FileStamp] = {}
    state = _load_manifest(db_path, observed)
    versions: list[LevelDbValue] = []
    assert state.live_files is not None
    tables: list[Path] = []
    for _level, number in sorted(state.live_files):
        table = db_path / f"{number:06d}.ldb"
        if not table.is_file():
            table = db_path / f"{number:06d}.sst"
        if not table.is_file():
            raise LevelDbReadError(f"MANIFEST 引用的 SSTable {number} 不存在")
        observed[table] = _file_stamp(table, table.name)
        tables.append(table)
    for table in tables:
        versions.extend(_table_versions(table, key))
    log_files = _numbered_files(db_path, "log")
    active_logs = {
        number
        for number in log_files
        if number >= int(state.log_number or 0) or number == state.previous_log_number
    }
    for number in active_logs:
        path = log_files[number]
        observed[path] = _file_stamp(path, path.name)
    for number in sorted(active_logs):
        versions.extend(_log_versions(log_files[number], key))
    _verify_snapshot(observed)
    return max(versions, key=lambda item: item.sequence) if versions else None


__all__ = ["LevelDbReadError", "LevelDbValue", "read_current_value"]
