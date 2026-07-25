# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""LevelDB 当前值读取与网易 scriptData 安全编辑回归测试。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import struct
import zlib

import pytest

import src.level_db as level_db
from src.level_dat_backend import load_level_dat_view
from src.level_db import LevelDbReadError, read_current_value
from src.netease_world_data import load_netease_world_data
from src.netease_world_data_editor import (
    NeteaseWorldDataEditError,
    save_netease_world_data_edits,
)


REAL_WORLD_ENV = "MCNETEASE_REAL_WORLD_LEVEL_DAT"
_TABLE_MAGIC = 0xDB4775248B80FB57
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


def _crc32c(value: bytes) -> int:
    checksum = 0xFFFFFFFF
    for byte in value:
        checksum = _CRC32C_TABLE[(checksum ^ byte) & 0xFF] ^ (checksum >> 8)
    return checksum ^ 0xFFFFFFFF


def _masked_crc32c(value: bytes) -> bytes:
    checksum = _crc32c(value)
    rotated = ((checksum >> 15) | (checksum << 17)) & 0xFFFFFFFF
    return ((rotated + 0xA282EAD8) & 0xFFFFFFFF).to_bytes(4, "little")


@dataclass(frozen=True)
class _PackedMap:
    pairs: tuple[tuple[object, object], ...]


def _varint(value: int) -> bytes:
    output = bytearray()
    while value >= 0x80:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def _slice(value: bytes) -> bytes:
    return _varint(len(value)) + value


def _physical_log(*records: bytes) -> bytes:
    """生成带跨 32 KiB block 分片的 LevelDB 日志。"""

    output = bytearray()
    for record in records:
        cursor = 0
        first = True
        while cursor < len(record):
            remaining_in_block = 32_768 - (len(output) % 32_768)
            if remaining_in_block < 7:
                output.extend(b"\x00" * remaining_in_block)
                remaining_in_block = 32_768
            chunk_size = min(len(record) - cursor, remaining_in_block - 7)
            chunk = record[cursor:cursor + chunk_size]
            cursor += chunk_size
            last = cursor == len(record)
            if first and last:
                record_type = 1
            elif first:
                record_type = 2
            elif last:
                record_type = 4
            else:
                record_type = 3
            output.extend(_masked_crc32c(bytes([record_type]) + chunk))
            output.extend(struct.pack("<HB", len(chunk), record_type))
            output.extend(chunk)
            first = False
    return bytes(output)


def _write_batch(sequence: int, *entries: tuple[bytes, bytes | None]) -> bytes:
    payload = bytearray(struct.pack("<QI", sequence, len(entries)))
    for key, value in entries:
        payload.append(0 if value is None else 1)
        payload.extend(_slice(key))
        if value is not None:
            payload.extend(_slice(value))
    return bytes(payload)


def _internal_key(key: bytes, sequence: int, value_type: int = 1) -> bytes:
    return key + ((sequence << 8) | value_type).to_bytes(8, "little")


def _block(*entries: tuple[bytes, bytes]) -> bytes:
    payload = bytearray()
    for key, value in entries:
        payload.extend(_varint(0))
        payload.extend(_varint(len(key)))
        payload.extend(_varint(len(value)))
        payload.extend(key)
        payload.extend(value)
    payload.extend(struct.pack("<II", 0, 1))
    return bytes(payload)


def _raw_deflate(value: bytes) -> bytes:
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    return compressor.compress(value) + compressor.flush()


def _block_region(value: bytes, compression_type: int) -> bytes:
    encoded_type = bytes([compression_type])
    return value + encoded_type + _masked_crc32c(value + encoded_type)


def _table(key: bytes, sequence: int, value: bytes) -> bytes:
    internal_key = _internal_key(key, sequence)
    data_block = _raw_deflate(_block((internal_key, value)))
    data_region = _block_region(data_block, 4)
    data_handle = _varint(0) + _varint(len(data_block))
    index_offset = len(data_region)
    index_block = _block((internal_key, data_handle))
    index_region = _block_region(index_block, 0)
    footer_handles = (
        _varint(0)
        + _varint(0)
        + _varint(index_offset)
        + _varint(len(index_block))
    )
    footer = footer_handles.ljust(40, b"\x00") + _TABLE_MAGIC.to_bytes(8, "little")
    return data_region + index_region + footer


def _manifest_edit(
    log_number: int,
    last_sequence: int,
    *,
    table_number: int | None = None,
    table_size: int = 0,
    smallest: bytes = b"",
    largest: bytes = b"",
) -> bytes:
    edit = bytearray()
    edit.extend(_varint(2) + _varint(log_number))
    edit.extend(_varint(4) + _varint(last_sequence))
    if table_number is not None:
        edit.extend(_varint(7) + _varint(0) + _varint(table_number))
        edit.extend(_varint(table_size) + _slice(smallest) + _slice(largest))
    return bytes(edit)


def _write_db(
    db_path: Path,
    wal: bytes,
    *,
    table: bytes | None = None,
    table_key: bytes = b"",
    table_sequence: int = 0,
) -> None:
    db_path.mkdir()
    table_number = 2 if table is not None else None
    manifest = _manifest_edit(
        3,
        max(0, table_sequence),
        table_number=table_number,
        table_size=len(table or b""),
        smallest=_internal_key(table_key, table_sequence) if table is not None else b"",
        largest=_internal_key(table_key, table_sequence) if table is not None else b"",
    )
    (db_path / "CURRENT").write_text("MANIFEST-000001\n", encoding="ascii")
    (db_path / "MANIFEST-000001").write_bytes(_physical_log(manifest))
    (db_path / "000003.log").write_bytes(_physical_log(wal))
    if table is not None:
        (db_path / "000002.ldb").write_bytes(table)


def _pack(value: object) -> bytes:
    if isinstance(value, _PackedMap):
        assert len(value.pairs) <= 15
        return bytes([0x80 | len(value.pairs)]) + b"".join(
            _pack(key) + _pack(item) for key, item in value.pairs
        )
    if isinstance(value, list):
        assert len(value) <= 15
        return bytes([0x90 | len(value)]) + b"".join(_pack(item) for item in value)
    if isinstance(value, bytes):
        assert len(value) <= 255
        return b"\xc4" + bytes([len(value)]) + value
    if isinstance(value, int):
        assert 0 <= value <= 127
        return bytes([value])
    raise TypeError(f"测试 MessagePack 不支持 {type(value)!r}")


def _script_data_nbt(payload: bytes) -> bytes:
    name = b"scriptData"
    return (
        b"\x0a\x00\x00"
        + b"\x08"
        + struct.pack("<H", len(name))
        + name
        + struct.pack("<I", len(payload))
        + payload
        + b"\x00"
    )


def test_current_value_prefers_fragmented_wal_over_raw_deflate_table(
    tmp_path: Path,
) -> None:
    key = b"scriptData"
    old_value = b"old"
    new_value = b"new:" + b"x" * 40_000
    table = _table(key, 7, old_value)
    wal = _write_batch(11, (b"other", b"ignored"), (key, new_value))
    _write_db(
        tmp_path / "db",
        wal,
        table=table,
        table_key=key,
        table_sequence=7,
    )

    current = read_current_value(tmp_path / "db", key)

    assert current is not None
    assert current.sequence == 12
    assert current.value == new_value
    assert current.source_file == "000003.log"


def test_crc32c_matches_standard_known_vector() -> None:
    assert level_db._crc32c(b"123456789") == 0xE3069283


def test_raw_deflate_trailing_bytes_are_rejected() -> None:
    compressed = _raw_deflate(b"payload") + b"trailing"

    with pytest.raises(LevelDbReadError, match="尾部"):
        level_db._inflate_raw(compressed)


def test_current_value_exposes_latest_deletion(tmp_path: Path) -> None:
    key = b"scriptData"
    _write_db(tmp_path / "db", _write_batch(20, (key, None)))

    current = read_current_value(tmp_path / "db", key)

    assert current is not None
    assert current.sequence == 20
    assert current.deleted is True
    assert current.value is None


def test_log_checksum_corruption_is_rejected(tmp_path: Path) -> None:
    key = b"scriptData"
    _write_db(tmp_path / "db", _write_batch(20, (key, b"value")))
    log_path = tmp_path / "db" / "000003.log"
    corrupted = bytearray(log_path.read_bytes())
    corrupted[-1] ^= 0x01
    log_path.write_bytes(corrupted)

    with pytest.raises(LevelDbReadError, match="校验和"):
        read_current_value(tmp_path / "db", key)


def test_sstable_checksum_corruption_is_rejected(tmp_path: Path) -> None:
    key = b"scriptData"
    table = _table(key, 7, b"old")
    _write_db(
        tmp_path / "db",
        _write_batch(8, (b"other", b"ignored")),
        table=table,
        table_key=key,
        table_sequence=7,
    )
    table_path = tmp_path / "db" / "000002.ldb"
    corrupted = bytearray(table_path.read_bytes())
    data_block_size = len(_raw_deflate(_block((_internal_key(key, 7), b"old"))))
    corrupted[data_block_size + 1] ^= 0x01
    table_path.write_bytes(corrupted)

    with pytest.raises(LevelDbReadError, match="校验和"):
        read_current_value(tmp_path / "db", key)


def test_snapshot_change_after_log_read_is_rejected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    key = b"scriptData"
    _write_db(tmp_path / "db", _write_batch(20, (key, b"old")))
    original_log_versions = level_db._log_versions

    def mutate_after_read(path: Path, target: bytes):
        versions = original_log_versions(path, target)
        with path.open("ab") as handle:
            handle.write(_physical_log(_write_batch(21, (key, b"new"))))
        return versions

    monkeypatch.setattr(level_db, "_log_versions", mutate_after_read)

    with pytest.raises(LevelDbReadError, match="读取期间.*变化"):
        read_current_value(tmp_path / "db", key)


def test_sstable_file_size_limit_is_enforced(tmp_path: Path, monkeypatch) -> None:
    key = b"scriptData"
    table = _table(key, 7, b"old")
    _write_db(
        tmp_path / "db",
        _write_batch(8, (b"other", b"ignored")),
        table=table,
        table_key=key,
        table_sequence=7,
    )
    monkeypatch.setattr(level_db, "LEVEL_DB_MAX_TABLE_BYTES", len(table) - 1)

    with pytest.raises(LevelDbReadError, match="超过读取上限"):
        read_current_value(tmp_path / "db", key)


def test_script_data_decodes_counts_tuple_key_and_read_only_rows(tmp_path: Path) -> None:
    encoded_tuple = _PackedMap(
        ((b"__type__", b"tuple"), (b"value", [1, 2]))
    )
    root = _PackedMap(
        (
            (
                b"dn_mj.maps",
                ["潮汐监狱".encode("utf-8"), "特勤处".encode("utf-8")],
            ),
            (b"dn_mj.exitPoints", [1, 2, 3, 4, 5]),
            (b"dn_mj.exitPoint.switches", [1]),
            (b"dn_mj.exitPoint.es", [1, 2, 3, 4]),
            (encoded_tuple, b"complex-key"),
        )
    )
    value = _script_data_nbt(_pack(root))
    _write_db(tmp_path / "db", _write_batch(30, (b"scriptData", value)))
    level_path = tmp_path / "level.dat"
    level_path.write_bytes(b"unused by direct world-data loader")

    view = load_netease_world_data(level_path)
    rows = {row["path"]: row for row in view.rows}

    assert view.summary["extraDataSequence"] == 30
    assert view.summary["extraDataEntryCount"] == 5
    assert view.summary["matchMapCount"] == 2
    assert view.summary["exitPointCount"] == 5
    assert view.summary["switchBlockCount"] == 1
    assert view.summary["gateConsoleCount"] == 4
    maps_row = rows["db.scriptData.dn_mj.maps"]
    assert maps_row["value"] == '[\n  "潮汐监狱",\n  "特勤处"\n]'
    complex_row = rows["db.scriptData[[1,2]]"]
    assert complex_row["value"] == '"complex-key"'
    assert complex_row["editable"] is True
    assert complex_row["sourceKind"] == "extraData"


def test_script_data_save_backs_up_writes_wal_and_reloads(tmp_path: Path) -> None:
    root = _PackedMap(
        (
            (
                b"dn_mj.map.test",
                _PackedMap(((b"maxPlayer", 21), (b"labels", [b"old"]))),
            ),
            (b"untouched", b"keep"),
        )
    )
    original = _script_data_nbt(_pack(root))
    _write_db(tmp_path / "db", _write_batch(30, (b"scriptData", original)))
    level_path = tmp_path / "level.dat"
    level_path.write_bytes(b"unused by direct world-data loader")

    view, backup_path, changed_count = save_netease_world_data_edits(
        level_path,
        30,
        hashlib.sha256(original).hexdigest(),
        [
            {
                "token": "extra:db.scriptData.dn_mj.map.test",
                "value": '{"maxPlayer": 30, "labels": ["new", "added"]}',
            }
        ],
    )

    assert backup_path == tmp_path / "db_old"
    assert changed_count == 1
    assert view.summary["extraDataSequence"] == 31
    rows = {row["path"]: row["value"] for row in view.rows}
    assert rows["db.scriptData.dn_mj.map.test"] == (
        '{\n  "maxPlayer": 30,\n  "labels": [\n    "new",\n    "added"\n  ]\n}'
    )
    assert rows["db.scriptData.untouched"] == '"keep"'
    saved = read_current_value(tmp_path / "db", b"scriptData")
    assert saved is not None and saved.value is not None
    assert b"\xc4\x09untouched\xc4\x04keep" in saved.value
    backup = read_current_value(backup_path, b"scriptData")
    assert backup is not None and backup.sequence == 30 and backup.value == original
    assert not (tmp_path / "db" / "LOCK").exists()


def test_script_data_save_rejects_stale_sequence_without_backup(tmp_path: Path) -> None:
    original = _script_data_nbt(_pack(_PackedMap(((b"key", b"value"),))))
    _write_db(tmp_path / "db", _write_batch(30, (b"scriptData", original)))
    level_path = tmp_path / "level.dat"
    level_path.write_bytes(b"unused")

    with pytest.raises(NeteaseWorldDataEditError, match="已变化"):
        save_netease_world_data_edits(
            level_path,
            29,
            hashlib.sha256(original).hexdigest(),
            [{"token": "extra:db.scriptData.key", "value": '"changed"'}],
        )

    assert not (tmp_path / "db_old").exists()
    assert not (tmp_path / "db" / "LOCK").exists()


def test_script_data_save_rejects_invalid_json_without_backup(tmp_path: Path) -> None:
    original = _script_data_nbt(_pack(_PackedMap(((b"key", b"value"),))))
    _write_db(tmp_path / "db", _write_batch(30, (b"scriptData", original)))
    level_path = tmp_path / "level.dat"
    level_path.write_bytes(b"unused")

    with pytest.raises(NeteaseWorldDataEditError, match="JSON 格式无效"):
        save_netease_world_data_edits(
            level_path,
            30,
            hashlib.sha256(original).hexdigest(),
            [{"token": "extra:db.scriptData.key", "value": "{"}],
        )

    assert not (tmp_path / "db_old").exists()


def test_real_world_extra_data_when_configured() -> None:
    sample = os.getenv(REAL_WORLD_ENV)
    if not sample:
        pytest.skip(f"未设置 {REAL_WORLD_ENV}")

    summary, rows, _netease_rows = load_level_dat_view(sample)

    assert summary["extraDataSequence"] == 5_957_285
    assert summary["extraDataSourceFile"] == "025399.log"
    assert summary["extraDataEntryCount"] == 146
    assert summary["matchMapCount"] == 2
    assert summary["exitPointCount"] == 5
    assert summary["switchBlockCount"] == 1
    assert summary["gateConsoleCount"] == 4
    assert any(row["path"] == "db.scriptData.dn_mj.exitPoints" for row in rows)
