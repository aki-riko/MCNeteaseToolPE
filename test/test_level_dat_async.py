# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""Level.dat 后台筛选和模型调度回归测试。"""

from __future__ import annotations

from src.config import LEVEL_DB_VALUE_PREVIEW_CHARS
from src.level_dat_backend import (
    LevelDatBackend,
    load_level_dat_view,
    save_extra_data_edits,
)
from src.level_dat_model import filter_level_dat_rows, matching_level_dat_rows


def _model_role(model, row: int, name: str):
    roles = {
        bytes(role_name).decode("utf-8"): role
        for role, role_name in model.roleNames().items()
    }
    return model.data(model.index(row, 0), roles[name])


def test_level_dat_filter_uses_paths_and_current_edited_values() -> None:
    rows = [
        {
            "path": "NetworkVersion",
            "value": "818",
            "token": '[["c",0]]',
        },
        {
            "path": "LevelName",
            "value": "原名称",
            "token": '[["c",1]]',
        },
    ]
    changes = [{"token": '[["c",1]]', "value": "修改后名称"}]

    assert matching_level_dat_rows(rows, "network", changes) == rows[:1]
    assert matching_level_dat_rows(rows, "修改后", changes) == rows[1:]
    assert matching_level_dat_rows(rows, "原名称", changes) == []


def test_level_dat_backend_routes_load_and_filter_through_pool(monkeypatch) -> None:
    import prismqml

    calls = []

    class _Connector:
        def connect(self, callback) -> None:
            self.callback = callback

    class _Handle:
        def __init__(self) -> None:
            self.succeeded = _Connector()
            self.failed = _Connector()
            self.cancelled = False

        def cancel(self) -> bool:
            self.cancelled = True
            return True

    def fake_run_in_pool(function, *args):
        handle = _Handle()
        calls.append((function, args, handle))
        return handle

    monkeypatch.setattr(prismqml, "run_in_pool", fake_run_in_pool)
    backend = LevelDatBackend()
    backend.load("file:///test/level.dat")

    assert calls[0][0] is load_level_dat_view

    rows = [
        {
            "path": "NetworkVersion",
            "value": "818",
            "token": '[["c",0]]',
            "depth": 0,
            "isNetease": False,
            "editable": True,
            "editorKind": "integer",
            "minimum": -2147483648,
            "maximum": 2147483647,
            "decimals": 0,
            "stepSize": 1,
        }
    ]
    backend._on_loaded(({"filePath": "level.dat"}, rows, []))
    backend.setFilter("network", [])

    assert calls[1][0] is filter_level_dat_rows
    assert calls[1][1][0] is rows

    backend.saveExtraData("level.dat", "30", "fingerprint", [])

    assert calls[2][0] is save_extra_data_edits
    assert calls[2][1] == ("level.dat", "30", "fingerprint", [])


def test_extra_data_model_previews_large_values_without_discarding_full_text() -> None:
    backend = LevelDatBackend()
    full_value = "x" * (LEVEL_DB_VALUE_PREVIEW_CHARS + 123)
    row = {
        "path": "db.scriptData.large",
        "value": full_value,
        "token": "extra:db.scriptData.large",
        "sourceKind": "extraData",
    }

    backend._on_loaded(({"filePath": "level.dat"}, [row], []))

    model = backend.extraDataTagModel
    assert _model_role(model, 0, "value") == full_value[:LEVEL_DB_VALUE_PREVIEW_CHARS]
    assert _model_role(model, 0, "valueTruncated") is True
    assert _model_role(model, 0, "fullValueLength") == len(full_value)
    assert _model_role(model, 0, "fullValue") == full_value
    assert _model_role(model, 0, "liveValidationLimit") == LEVEL_DB_VALUE_PREVIEW_CHARS
    assert backend._extra_data_values[row["token"]] == full_value


def test_copy_extra_data_value_uses_full_text_not_model_preview(monkeypatch) -> None:
    import src.level_dat_backend as backend_module

    class _ClipboardHelper:
        text = ""

        @classmethod
        def copy(cls, value: str) -> None:
            cls.text = value

    monkeypatch.setattr(
        backend_module,
        "get_clipboard_helper",
        lambda: _ClipboardHelper,
    )
    backend = LevelDatBackend()
    full_value = "x" * (LEVEL_DB_VALUE_PREVIEW_CHARS + 123)
    token = "extra:db.scriptData.large"
    row = {
        "path": "db.scriptData.large",
        "value": full_value,
        "token": token,
        "sourceKind": "extraData",
    }
    messages = []
    backend.extraDataCopied.connect(messages.append)

    backend._on_loaded(({"filePath": "level.dat"}, [row], []))
    backend.copyExtraDataValue(token)

    assert _ClipboardHelper.text == full_value
    assert messages == [f"已复制完整 DB 值（{len(full_value)} 字符）"]
