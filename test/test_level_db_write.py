# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""世界数据库写入失败回滚门禁。"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import src.level_db_writer as writer
from src.level_db import LevelDbReadError, read_current_value
from src.netease_world_data_editor import (
    NeteaseWorldDataEditError,
    save_netease_world_data_edits,
)
from test.test_level_db import (
    _PackedMap,
    _pack,
    _script_data_nbt,
    _write_batch,
    _write_db,
)


def test_failed_post_write_validation_restores_original_wal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    original_value = _script_data_nbt(
        _pack(_PackedMap(((b"key", b"original"),)))
    )
    db_path = tmp_path / "db"
    _write_db(db_path, _write_batch(30, (b"scriptData", original_value)))
    level_path = tmp_path / "level.dat"
    level_path.write_bytes(b"unused")
    log_path = db_path / "000003.log"
    original_log = log_path.read_bytes()
    original_reader = writer.read_current_value

    def fail_after_log_replace(path: Path, key: bytes):
        if path.resolve() == db_path.resolve() and log_path.stat().st_size > len(original_log):
            raise LevelDbReadError("强制写后验证失败")
        return original_reader(path, key)

    monkeypatch.setattr(writer, "read_current_value", fail_after_log_replace)

    with pytest.raises(NeteaseWorldDataEditError, match="已自动回滚"):
        save_netease_world_data_edits(
            level_path,
            30,
            hashlib.sha256(original_value).hexdigest(),
            [{"token": "extra:db.scriptData.key", "value": '"changed"'}],
        )

    assert log_path.read_bytes() == original_log
    current = read_current_value(db_path, b"scriptData")
    assert current is not None and current.sequence == 30
    assert current.value == original_value
    assert (tmp_path / "db_old").is_dir()
