# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""以可回滚 WAL 更新 Bedrock LevelDB 中单个键。"""

from __future__ import annotations

from contextlib import contextmanager
import ctypes
from dataclasses import dataclass
import hashlib
import logging
import os
from pathlib import Path
import shutil
import stat
import struct
import tempfile
from typing import BinaryIO, Iterator

from .config import LEVEL_DB_MAX_LOG_BYTES
from .level_db import (
    LevelDbReadError,
    LevelDbValue,
    _crc32c,
    _encode_varint,
    _load_manifest,
    _logical_records,
    _masked_crc32c,
    _numbered_files,
    _stable_read,
    read_current_value,
)


LOGGER = logging.getLogger(__name__)
_LOG_BLOCK_BYTES = 32_768
_LOG_HEADER_BYTES = 7


class LevelDbWriteError(LevelDbReadError):
    """LevelDB 已变化、正在使用或写后验证失败。"""


def _lock_windows(handle: BinaryIO) -> object:
    import msvcrt

    class _Overlapped(ctypes.Structure):
        _fields_ = [
            ("Internal", ctypes.c_void_p),
            ("InternalHigh", ctypes.c_void_p),
            ("Offset", ctypes.c_uint32),
            ("OffsetHigh", ctypes.c_uint32),
            ("hEvent", ctypes.c_void_p),
        ]

    overlapped = _Overlapped()
    lock_file = ctypes.WinDLL("kernel32", use_last_error=True).LockFileEx
    lock_file.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.POINTER(_Overlapped),
    ]
    lock_file.restype = ctypes.c_int
    os_handle = ctypes.c_void_p(msvcrt.get_osfhandle(handle.fileno()))
    if not lock_file(os_handle, 0x00000003, 0, 1, 0, ctypes.byref(overlapped)):
        raise OSError(ctypes.get_last_error(), "LevelDB LOCK 已被占用")
    return os_handle, overlapped


def _unlock_windows(handle: BinaryIO, state: object) -> None:
    os_handle, overlapped = state
    unlock_file = ctypes.WinDLL("kernel32", use_last_error=True).UnlockFileEx
    unlock_file.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.POINTER(type(overlapped)),
    ]
    unlock_file.restype = ctypes.c_int
    unlock_file(os_handle, 0, 1, 0, ctypes.byref(overlapped))


def _acquire_lock(handle: BinaryIO) -> object:
    if os.name == "nt":
        return _lock_windows(handle)
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    return True


def _release_lock(handle: BinaryIO, state: object) -> None:
    if os.name == "nt":
        _unlock_windows(handle, state)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _database_lock(db_path: Path) -> Iterator[None]:
    lock_path = db_path / "LOCK"
    created = not lock_path.exists()
    try:
        handle = lock_path.open("a+b")
    except OSError as error:
        raise LevelDbWriteError(f"无法创建 LevelDB 写入锁：{error}") from error
    try:
        state = _acquire_lock(handle)
    except OSError as error:
        handle.close()
        raise LevelDbWriteError("世界数据库正在使用，请关闭世界后重试") from error
    try:
        yield
    finally:
        try:
            _release_lock(handle, state)
        finally:
            handle.close()
            if created:
                try:
                    lock_path.unlink(missing_ok=True)
                except OSError:
                    LOGGER.warning(
                        "清理临时 LevelDB LOCK 失败：%s", lock_path, exc_info=True
                    )


def _file_snapshot(db_path: Path) -> dict[str, tuple[int, int]]:
    snapshot: dict[str, tuple[int, int]] = {}
    try:
        for path in db_path.iterdir():
            if path.is_file():
                state = path.stat()
                snapshot[path.name] = (state.st_size, state.st_mtime_ns)
    except OSError as error:
        raise LevelDbWriteError(f"无法检查世界数据库状态：{error}") from error
    return snapshot


def _next_backup_path(db_path: Path, suffix: str) -> Path:
    base = db_path.with_name(db_path.name + suffix)
    if not base.exists():
        return base
    index = 2
    while True:
        candidate = db_path.with_name(f"{db_path.name}{suffix}_{index}")
        if not candidate.exists():
            return candidate
        index += 1


def _copy_verified_backup(
    db_path: Path,
    suffix: str,
    key: bytes,
    expected: LevelDbValue,
) -> Path:
    backup_path = _next_backup_path(db_path, suffix)
    try:
        shutil.copytree(db_path, backup_path, symlinks=True)
        copied = read_current_value(backup_path, key)
    except (OSError, LevelDbReadError) as error:
        if backup_path.exists():
            try:
                shutil.rmtree(backup_path)
            except OSError:
                LOGGER.warning("清理不完整 DB 备份失败：%s", backup_path, exc_info=True)
        raise LevelDbWriteError(f"世界数据库备份验证失败：{error}") from error
    if copied is None or copied.sequence != expected.sequence or copied.value != expected.value:
        raise LevelDbWriteError("世界数据库备份内容与原始数据不一致")
    return backup_path


def _write_batch(sequence: int, key: bytes, value: bytes) -> bytes:
    return (
        struct.pack("<QI", sequence, 1)
        + b"\x01"
        + _encode_varint(len(key))
        + key
        + _encode_varint(len(value))
        + value
    )


def _append_logical_record(existing: bytes, record: bytes) -> bytes:
    output = bytearray(existing)
    cursor = 0
    first = True
    while cursor < len(record):
        remaining = _LOG_BLOCK_BYTES - (len(output) % _LOG_BLOCK_BYTES)
        if remaining < _LOG_HEADER_BYTES:
            output.extend(b"\x00" * remaining)
            remaining = _LOG_BLOCK_BYTES
        size = min(len(record) - cursor, remaining - _LOG_HEADER_BYTES)
        chunk = record[cursor:cursor + size]
        cursor += size
        last = cursor == len(record)
        record_type = 1 if first and last else 2 if first else 4 if last else 3
        checksum = _masked_crc32c(_crc32c(bytes([record_type]) + chunk))
        output.extend(checksum.to_bytes(4, "little"))
        output.extend(struct.pack("<HB", len(chunk), record_type))
        output.extend(chunk)
        first = False
    return bytes(output)


def _last_log_sequence(data: bytes) -> int:
    highest = 0
    for record in _logical_records(data):
        if len(record) < 12:
            raise LevelDbWriteError("LevelDB WriteBatch 头部不完整")
        first_sequence, count = struct.unpack("<QI", record[:12])
        if count:
            highest = max(highest, first_sequence + count - 1)
    return highest


def _active_log_sequence(db_path: Path, log_number: int, previous: int) -> int:
    highest = 0
    for number, path in _numbered_files(db_path, "log").items():
        if number >= log_number or number == previous:
            data = _stable_read(path, LEVEL_DB_MAX_LOG_BYTES, path.name)
            highest = max(highest, _last_log_sequence(data))
    return highest


def _atomic_write(path: Path, data: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


def _restore_log(path: Path, existed: bool, original: bytes) -> None:
    if existed:
        _atomic_write(path, original)
    else:
        path.unlink(missing_ok=True)


def _assert_expected(
    current: LevelDbValue | None,
    expected_sequence: int,
    expected_fingerprint: str,
) -> LevelDbValue:
    if current is None or current.deleted or current.value is None:
        raise LevelDbWriteError("DB 中当前没有可编辑的 scriptData")
    fingerprint = hashlib.sha256(current.value).hexdigest()
    if current.sequence != expected_sequence or fingerprint != expected_fingerprint:
        raise LevelDbWriteError("世界数据库已被其他程序修改，请重新读取后再编辑")
    return current


@dataclass(frozen=True, slots=True)
class _WritePlan:
    log_path: Path
    log_existed: bool
    original_log: bytes
    sequence: int


def _prepare_write(db_path: Path, current: LevelDbValue) -> _WritePlan:
    state = _load_manifest(db_path)
    if state.log_number is None:
        raise LevelDbWriteError("MANIFEST 缺少当前日志编号")
    log_path = db_path / f"{state.log_number:06d}.log"
    existed = log_path.is_file()
    original = (
        _stable_read(log_path, LEVEL_DB_MAX_LOG_BYTES, log_path.name)
        if existed
        else b""
    )
    highest = max(
        state.last_sequence,
        current.sequence,
        _active_log_sequence(
            db_path, int(state.log_number), state.previous_log_number
        ),
    )
    return _WritePlan(log_path, existed, original, highest + 1)


def _backup_unchanged_db(
    db_path: Path,
    suffix: str,
    key: bytes,
    current: LevelDbValue,
) -> Path:
    before = _file_snapshot(db_path)
    backup_path = _copy_verified_backup(db_path, suffix, key, current)
    if _file_snapshot(db_path) != before:
        raise LevelDbWriteError("备份期间世界数据库发生变化，请重新读取后再编辑")
    return backup_path


def _commit_wal(
    db_path: Path,
    key: bytes,
    value: bytes,
    plan: _WritePlan,
    backup_path: Path,
) -> LevelDbValue:
    updated_log = _append_logical_record(
        plan.original_log, _write_batch(plan.sequence, key, value)
    )
    if len(updated_log) > LEVEL_DB_MAX_LOG_BYTES:
        raise LevelDbWriteError("更新后的 LevelDB WAL 超过安全大小上限")
    try:
        _atomic_write(plan.log_path, updated_log)
        saved = read_current_value(db_path, key)
        if saved is None or saved.value != value or saved.sequence != plan.sequence:
            raise LevelDbWriteError("写入后重新读取的 scriptData 不一致")
        return saved
    except (OSError, LevelDbReadError) as error:
        LOGGER.error("世界数据库写入验证失败，开始回滚 WAL", exc_info=True)
        try:
            _restore_log(plan.log_path, plan.log_existed, plan.original_log)
        except OSError as restore_error:
            LOGGER.exception("世界数据库 WAL 回滚失败：%s", plan.log_path)
            raise LevelDbWriteError(
                f"DB 写入失败且自动回滚失败，请使用备份 {backup_path}：{restore_error}"
            ) from error
        raise LevelDbWriteError(f"DB 写入失败，已自动回滚：{error}") from error


def write_current_value(
    db_path: Path,
    key: bytes,
    value: bytes,
    *,
    expected_sequence: int,
    expected_fingerprint: str,
    backup_suffix: str,
) -> tuple[LevelDbValue, Path]:
    """在独占锁内备份 DB、追加 WAL，并重新读取验证当前值。"""

    db_path = db_path.expanduser().resolve()
    with _database_lock(db_path):
        current = _assert_expected(
            read_current_value(db_path, key), expected_sequence, expected_fingerprint
        )
        plan = _prepare_write(db_path, current)
        backup_path = _backup_unchanged_db(
            db_path, backup_suffix, key, current
        )
        _assert_expected(
            read_current_value(db_path, key), expected_sequence, expected_fingerprint
        )
        saved = _commit_wal(db_path, key, value, plan, backup_path)
        return saved, backup_path


__all__ = ["LevelDbWriteError", "write_current_value"]
