# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bedrock level.dat 解析与页面接线回归测试。"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import struct
import sys
import zipfile

import pytest

from src.level_dat import (
    DECIMAL_LIMITS,
    INTEGER_RANGES,
    LevelDatParseError,
    NbtList,
    build_view_rows,
    parse_level_dat,
)
from src.level_dat_backend import load_level_dat_view, save_level_dat_edits
from src.level_dat_editor import (
    LevelDatEditError,
    apply_text_edits,
    parse_scalar_value,
    serialize_level_dat,
)


ROOT = Path(__file__).resolve().parents[1]
QML_PROBE = ROOT / "test" / "_level_dat_qml_probe.py"
REAL_SAMPLE_ENV = "MCNETEASE_LEVEL_DAT_SAMPLE"
REAL_SAMPLE_ZIP_ENV = "MCNETEASE_LEVEL_DAT_SAMPLE_ZIP"


def _string(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return struct.pack("<H", len(encoded)) + encoded


def _named(tag_type: int, name: str, payload: bytes) -> bytes:
    return bytes([tag_type]) + _string(name) + payload


def _level_dat(*tags: bytes, version: int = 10) -> bytes:
    payload = _named(10, "", b"".join(tags) + b"\x00")
    return struct.pack("<II", version, len(payload)) + payload


def _tags_by_name(document) -> dict[str, object]:
    return {tag.name: tag for tag in document.root.value}


def _all_payload_tags() -> tuple[bytes, ...]:
    nested = _named(8, "child", _string("值")) + b"\x00"
    return (
        _named(1, "byte", struct.pack("<b", -7)),
        _named(2, "short", struct.pack("<h", -300)),
        _named(3, "int", struct.pack("<i", 123456)),
        _named(4, "long", struct.pack("<q", -9_000_000_000)),
        _named(5, "float", struct.pack("<f", 1.5)),
        _named(6, "double", struct.pack("<d", 2.25)),
        _named(7, "bytes", struct.pack("<i", 3) + b"\x00\x7f\xff"),
        _named(8, "text", _string("网易 NBT")),
        _named(9, "list", b"\x03" + struct.pack("<i", 2) + struct.pack("<ii", 4, 5)),
        _named(10, "compound", nested),
        _named(11, "ints", struct.pack("<i", 2) + struct.pack("<ii", -1, 2)),
        _named(12, "longs", struct.pack("<i", 2) + struct.pack("<qq", -3, 4)),
        _named(1, "neteaseEncryptFlag", struct.pack("<b", 0)),
    )


def _change(rows: list[dict[str, object]], path: str, value: str) -> dict[str, str]:
    row = next(candidate for candidate in rows if candidate["path"] == path)
    return {"token": str(row["token"]), "value": value}


def test_parser_reads_all_bedrock_nbt_tag_payload_types() -> None:
    document = parse_level_dat(
        _level_dat(*_all_payload_tags()),
        max_depth=64,
        max_items=1000,
    )
    parsed = _tags_by_name(document)

    assert document.format_version == 10
    assert parsed["byte"].value == -7
    assert parsed["text"].value == "网易 NBT"
    assert isinstance(parsed["list"].value, NbtList)
    assert parsed["list"].value.items == (4, 5)
    assert parsed["compound"].value[0].value == "值"
    assert parsed["ints"].value == (-1, 2)
    assert parsed["longs"].value == (-3, 4)

    rows = build_view_rows(document)
    by_path = {row["path"]: row for row in rows}
    assert by_path["compound.child"]["value"] == "值"
    assert by_path["list[1]"]["value"] == "5"
    assert by_path["bytes[2]"]["value"] == "-1"
    assert by_path["neteaseEncryptFlag"]["isNetease"] is True
    assert by_path["int"]["editorKind"] == "integer"
    assert by_path["long"]["editorKind"] == "long"
    assert by_path["double"]["editorKind"] == "decimal"
    assert by_path["text"]["editorKind"] == "text"
    assert by_path["compound"]["editable"] is False
    assert all("tagType" not in row for row in rows)


def test_serializer_round_trips_every_supported_payload_type() -> None:
    source = _level_dat(*_all_payload_tags())
    document = parse_level_dat(source, max_depth=64, max_items=1000)

    assert serialize_level_dat(document) == source


def test_editor_updates_scalars_nested_values_lists_and_arrays() -> None:
    source = _level_dat(*_all_payload_tags())
    document = parse_level_dat(source, max_depth=64, max_items=1000)
    rows = build_view_rows(document)
    changes = [
        _change(rows, "byte", "127"),
        _change(rows, "short", "-32768"),
        _change(rows, "int", "2147483647"),
        _change(rows, "long", "-9223372036854775808"),
        _change(rows, "float", "3.25"),
        _change(rows, "double", "-4.5e20"),
        _change(rows, "text", "原版与网易均可编辑"),
        _change(rows, "list[1]", "55"),
        _change(rows, "compound.child", "嵌套已修改"),
        _change(rows, "bytes[2]", "-128"),
        _change(rows, "ints[0]", "-2147483648"),
        _change(rows, "longs[1]", "9223372036854775807"),
    ]

    updated = apply_text_edits(document, changes)
    reparsed = parse_level_dat(
        serialize_level_dat(updated),
        max_depth=64,
        max_items=1000,
    )
    tags = _tags_by_name(reparsed)

    assert tags["byte"].value == 127
    assert tags["short"].value == -32_768
    assert tags["int"].value == 2_147_483_647
    assert tags["long"].value == -9_223_372_036_854_775_808
    assert tags["float"].value == pytest.approx(3.25)
    assert tags["double"].value == pytest.approx(-4.5e20)
    assert tags["text"].value == "原版与网易均可编辑"
    assert tags["list"].value.items == (4, 55)
    assert tags["compound"].value[0].value == "嵌套已修改"
    assert tags["bytes"].value == (0, 127, -128)
    assert tags["ints"].value == (-2_147_483_648, 2)
    assert tags["longs"].value == (-3, 9_223_372_036_854_775_807)


def test_editor_follows_lists_nested_inside_lists_and_compounds() -> None:
    compound_item = _named(3, "inside", struct.pack("<i", 1)) + b"\x00"
    compound_list = _named(9, "compoundList", b"\x0a" + struct.pack("<i", 1) + compound_item)
    string_list_item = b"\x08" + struct.pack("<i", 1) + _string("before")
    nested_list = _named(9, "nestedList", b"\x09" + struct.pack("<i", 1) + string_list_item)
    document = parse_level_dat(
        _level_dat(compound_list, nested_list),
        max_depth=64,
        max_items=1000,
    )
    rows = build_view_rows(document)
    updated = apply_text_edits(
        document,
        [
            _change(rows, "compoundList[0].inside", "2"),
            _change(rows, "nestedList[0][0]", "after"),
        ],
    )
    tags = _tags_by_name(
        parse_level_dat(
            serialize_level_dat(updated),
            max_depth=64,
            max_items=1000,
        )
    )

    assert tags["compoundList"].value.items[0][0].value == 2
    assert tags["nestedList"].value.items[0].items == ("after",)


def test_scalar_validation_covers_numeric_ranges_and_text_size() -> None:
    for tag_type, (minimum, maximum) in INTEGER_RANGES.items():
        assert parse_scalar_value(tag_type, str(minimum)) == minimum
        assert parse_scalar_value(tag_type, str(maximum)) == maximum
        with pytest.raises(LevelDatEditError, match="必须在"):
            parse_scalar_value(tag_type, str(minimum - 1))
        with pytest.raises(LevelDatEditError, match="必须在"):
            parse_scalar_value(tag_type, str(maximum + 1))

    for tag_type, limit in DECIMAL_LIMITS.items():
        assert parse_scalar_value(tag_type, str(limit)) == limit
        assert parse_scalar_value(tag_type, "+.5e-2") == pytest.approx(0.005)
        with pytest.raises(LevelDatEditError, match="有限数字"):
            parse_scalar_value(tag_type, "1e9999")
        with pytest.raises(LevelDatEditError, match="有效数字"):
            parse_scalar_value(tag_type, "nan")

    assert parse_scalar_value(8, "a" * 65_535) == "a" * 65_535
    with pytest.raises(LevelDatEditError, match="65535"):
        parse_scalar_value(8, "界" * 21_846)


def test_editor_rejects_duplicate_or_structurally_stale_tokens() -> None:
    document = parse_level_dat(
        _level_dat(_named(3, "value", struct.pack("<i", 1))),
        max_depth=64,
        max_items=1000,
    )
    row = build_view_rows(document)[0]
    change = {"token": row["token"], "value": "2"}

    with pytest.raises(LevelDatEditError, match="重复"):
        apply_text_edits(document, [change, change])
    with pytest.raises(LevelDatEditError, match="结构不一致"):
        apply_text_edits(document, [{"token": '[["l",0]]', "value": "2"}])


def test_parser_rejects_mismatched_header_length() -> None:
    data = bytearray(_level_dat())
    struct.pack_into("<I", data, 4, 999)

    with pytest.raises(LevelDatParseError, match="头部声明"):
        parse_level_dat(bytes(data), max_depth=64, max_items=1000)


def test_parser_identifies_probable_text_mode_binary_corruption() -> None:
    data = _level_dat() + b"\xef\xbf\xbd" * 3

    with pytest.raises(LevelDatParseError, match="按文本方式改写"):
        parse_level_dat(data, max_depth=64, max_items=1000)


def test_parser_rejects_negative_list_count() -> None:
    invalid_list = _named(9, "bad", b"\x03" + struct.pack("<i", -1))

    with pytest.raises(LevelDatParseError, match="不能为负数"):
        parse_level_dat(_level_dat(invalid_list), max_depth=64, max_items=1000)


def test_parser_applies_collection_safety_limit() -> None:
    two_items = _named(9, "tooMany", b"\x03" + struct.pack("<i", 2) + struct.pack("<ii", 1, 2))

    with pytest.raises(LevelDatParseError, match="超过安全上限"):
        parse_level_dat(_level_dat(two_items), max_depth=64, max_items=1)


def test_view_rows_do_not_truncate_string_values() -> None:
    full_value = "网易与原版数据" * 200
    document = parse_level_dat(
        _level_dat(_named(8, "complete", _string(full_value))),
        max_depth=64,
        max_items=1000,
    )

    assert build_view_rows(document)[0]["value"] == full_value


def test_view_loader_reads_level_dat_without_writing_it(tmp_path: Path) -> None:
    level_path = tmp_path / "level.dat"
    level_path.write_bytes(
        _level_dat(
            _named(8, "LevelName", _string("测试存档")),
            _named(1, "neteaseEncryptFlag", struct.pack("<b", 0)),
        )
    )
    before = level_path.read_bytes()

    summary, rows, netease_rows = load_level_dat_view(level_path.as_uri())

    assert summary["levelName"] == "测试存档"
    assert summary["formatVersion"] == 10
    assert summary["nbtNodeCount"] == len(rows)
    assert summary["levelDbFound"] is False
    assert summary["extraDataFound"] is False
    assert summary["extraDataStatus"] == "未发现同级 db 目录"
    assert [row["path"] for row in netease_rows] == ["neteaseEncryptFlag"]
    assert any(row["path"] == "LevelName" for row in rows)
    assert level_path.read_bytes() == before


def test_broken_db_does_not_block_level_dat_view(tmp_path: Path) -> None:
    level_path = tmp_path / "level.dat"
    level_path.write_bytes(_level_dat(_named(8, "LevelName", _string("仍可读取"))))
    db_path = tmp_path / "db"
    db_path.mkdir()
    (db_path / "CURRENT").write_text("not-a-manifest\n", encoding="ascii")

    summary, rows, _netease_rows = load_level_dat_view(level_path.as_uri())

    assert summary["levelName"] == "仍可读取"
    assert summary["levelDbFound"] is True
    assert summary["extraDataFound"] is False
    assert str(summary["extraDataStatus"]).startswith("DB 读取失败：")
    assert [row["path"] for row in rows] == ["LevelName"]


def test_save_creates_official_backup_and_reloads_written_data(tmp_path: Path) -> None:
    level_path = tmp_path / "level.dat"
    original = _level_dat(
        _named(8, "LevelName", _string("保存前")),
        _named(3, "NetworkVersion", struct.pack("<i", 818)),
    )
    level_path.write_bytes(original)
    summary, rows, _netease_rows = load_level_dat_view(level_path.as_uri())
    changes = [
        _change(rows, "LevelName", "保存后"),
        _change(rows, "NetworkVersion", "819"),
    ]

    saved_summary, saved_rows, _, backup_path, changed_count = save_level_dat_edits(
        level_path.as_uri(),
        str(summary["fingerprint"]),
        changes,
    )

    assert changed_count == 2
    assert backup_path == str(tmp_path / "level.dat_old")
    assert (tmp_path / "level.dat_old").read_bytes() == original
    assert saved_summary["levelName"] == "保存后"
    assert saved_summary["fingerprint"] != summary["fingerprint"]
    assert {row["path"]: row["value"] for row in saved_rows}["NetworkVersion"] == "819"
    assert not list(tmp_path.glob(".level.dat.*.tmp"))


def test_save_refuses_to_overwrite_an_external_change(tmp_path: Path) -> None:
    level_path = tmp_path / "level.dat"
    level_path.write_bytes(_level_dat(_named(3, "value", struct.pack("<i", 1))))
    summary, rows, _netease_rows = load_level_dat_view(level_path.as_uri())
    external = _level_dat(_named(3, "value", struct.pack("<i", 9)))
    level_path.write_bytes(external)

    with pytest.raises(ValueError, match="其他程序修改"):
        save_level_dat_edits(
            level_path.as_uri(),
            str(summary["fingerprint"]),
            [_change(rows, "value", "2")],
        )

    assert level_path.read_bytes() == external
    assert not (tmp_path / "level.dat_old").exists()


def test_real_level_dat_sample_when_configured() -> None:
    sample = os.getenv(REAL_SAMPLE_ENV)
    if not sample:
        pytest.skip(f"未设置 {REAL_SAMPLE_ENV}")

    summary, rows, netease_rows = load_level_dat_view(sample)
    by_path = {row["path"]: row["value"] for row in rows}

    assert summary["formatVersion"] == 10
    assert summary["declaredPayloadSize"] == 2941
    assert summary["fileSize"] == 2949
    assert summary["levelName"] == "监狱在建容器布置完毕"
    assert by_path["NetworkVersion"] == "818"
    assert by_path["neteaseEncryptFlag"] == "0"
    assert [row["path"] for row in netease_rows] == [
        "neteaseEncryptFlag",
        "neteaseStrongholdSelectedChunks",
    ]


def test_real_level_dat_from_zip_can_be_edited_and_backed_up(tmp_path: Path) -> None:
    sample_zip = os.getenv(REAL_SAMPLE_ZIP_ENV)
    if not sample_zip:
        pytest.skip(f"未设置 {REAL_SAMPLE_ZIP_ENV}")

    with zipfile.ZipFile(sample_zip) as archive:
        entries = [
            name
            for name in archive.namelist()
            if name.replace("\\", "/").casefold().endswith("/level.dat")
        ]
        assert len(entries) == 1
        original = archive.read(entries[0])

    level_path = tmp_path / "level.dat"
    level_path.write_bytes(original)
    document = parse_level_dat(original, max_depth=64, max_items=100_000)
    assert serialize_level_dat(document) == original
    summary, rows, _netease_rows = load_level_dat_view(level_path.as_uri())
    changes = [
        _change(rows, "LevelName", "临时副本编辑验证"),
        _change(rows, "NetworkVersion", "819"),
    ]

    saved_summary, saved_rows, _, backup_path, changed_count = save_level_dat_edits(
        level_path.as_uri(),
        str(summary["fingerprint"]),
        changes,
    )

    saved_by_path = {row["path"]: row["value"] for row in saved_rows}
    assert summary["fileSize"] == 2949
    assert summary["declaredPayloadSize"] == 2941
    assert summary["visibleNodeCount"] == 145
    assert changed_count == 2
    assert backup_path == str(tmp_path / "level.dat_old")
    assert (tmp_path / "level.dat_old").read_bytes() == original
    assert saved_summary["levelName"] == "临时副本编辑验证"
    assert saved_by_path["NetworkVersion"] == "819"


def test_level_dat_page_is_wired_to_a_dedicated_backend() -> None:
    main_source = (ROOT / "main.py").read_text(encoding="utf-8")
    qml_source = (ROOT / "qml" / "LevelDatPage.qml").read_text(encoding="utf-8")

    assert "from src.level_dat_backend import LevelDatBackend" in main_source
    assert (
        "level_dat_backend = LevelDatBackend(settings_backend=settings_backend)"
        in main_source
    )
    assert '_page_factory("LevelDatPage.qml", level_dat_backend)' in main_source
    assert '"DocumentData"' in main_source
    assert "selectedFile.toString()" in qml_source
    assert "backend.load(page.sourceUrl)" in qml_source
    assert "backend.save(page.sourceUrl" in qml_source
    assert "level.dat_old" in qml_source
    assert "ConfirmDialog" in qml_source
    assert "textFormat: Text.PlainText" in qml_source
    assert "TAG_" not in qml_source
    assert "ScrollArea {" not in qml_source
    assert "Repeater {" not in qml_source
    assert qml_source.count("LevelDatVirtualList {") == 1
    assert "LevelDatExtraDataPane {" in qml_source
    assert "StackedWidget {" in qml_source
    assert "SegmentedControl {" in qml_source
    assert "backend.nbtTagModel" in qml_source
    assert "backend.saveExtraData(" in qml_source
    assert "width: nbtList.width" not in qml_source
    assert "width: extraDataList.width" not in qml_source
    assert "backend.setFilter(filterInput.text" in qml_source
    assert 'qsTr("世界数据库")' in qml_source
    assert "DB 永不写入" not in qml_source
    assert "ListModel" not in qml_source
    assert "tagModel.append" not in qml_source

    editor_source = (ROOT / "qml" / "LevelDatValueEditor.qml").read_text(encoding="utf-8")
    assert "SpinBox {" in editor_source
    assert "LineEdit {" in editor_source
    assert "TextEdit {" in editor_source
    assert "type: Enums.input.spinbox_double" in editor_source
    assert "RegularExpressionValidator" in editor_source
    assert "TAG_" not in editor_source
    delegate_source = (ROOT / "qml" / "LevelDatTagDelegate.qml").read_text(
        encoding="utf-8"
    )
    assert "levelDatReadOnlyValue_" in delegate_source
    assert "readOnly: true" in delegate_source
    assert "Text.MarkdownText" not in delegate_source
    assert "width: QtQ.ListView.view ? QtQ.ListView.view.width : 0" in delegate_source
    extra_data_delegate_source = (
        ROOT / "qml" / "LevelDatExtraDataDelegate.qml"
    ).read_text(encoding="utf-8")
    assert "levelDatExtraDataCard_" in extra_data_delegate_source
    assert "levelDatExtraDataPath_" in extra_data_delegate_source
    assert "levelDatExtraDataPreviewStatus_" in extra_data_delegate_source
    assert "levelDatExtraDataEditor_" in extra_data_delegate_source
    assert "LevelDatFocusWheelTextEdit {" in extra_data_delegate_source
    assert "Text.MarkdownText" not in extra_data_delegate_source
    assert "textFormat: Text.PlainText" in extra_data_delegate_source
    assert "readOnly: false" in extra_data_delegate_source
    assert "onTextEdited:" in extra_data_delegate_source
    assert "Layout.fillWidth: true" in extra_data_delegate_source
    assert "复制当前 JSON" in extra_data_delegate_source
    assert (
        "width: QtQ.ListView.view ? QtQ.ListView.view.width : 0"
        in extra_data_delegate_source
    )
    extra_data_pane_source = (
        ROOT / "qml" / "LevelDatExtraDataPane.qml"
    ).read_text(encoding="utf-8")
    assert "LevelDatVirtualList {" in extra_data_pane_source
    assert "backend.extraDataTagModel" in extra_data_pane_source
    assert "delegate: LevelDatExtraDataDelegate" in extra_data_pane_source
    assert "保存 %1 项 DB 修改" in extra_data_pane_source
    assert "scrollTarget: dataList" in extra_data_pane_source
    focus_wheel_editor_source = (
        ROOT / "qml" / "LevelDatFocusWheelTextEdit.qml"
    ).read_text(encoding="utf-8")
    assert "control.hasFocus()" in focus_wheel_editor_source
    assert "control.scrollInner" in focus_wheel_editor_source
    assert "control.scrollTarget.scrollWheel" in focus_wheel_editor_source
    virtual_list_source = (ROOT / "qml" / "LevelDatVirtualList.qml").read_text(
        encoding="utf-8"
    )
    assert "ScrollArea {" in virtual_list_source
    assert "type: Enums.scroll.type_list" in virtual_list_source
    assert "reuseItems: true" in virtual_list_source
    assert "showScrollBar: true" in virtual_list_source
    assert "bounceEnabled: false" in virtual_list_source
    assert "property int cacheBuffer: 0" in virtual_list_source
    backend_source = (ROOT / "src" / "level_dat_backend.py").read_text(
        encoding="utf-8"
    )
    assert "load_netease_world_data" in backend_source
    assert "save_netease_world_data_edits" in backend_source
    assert 'LEVEL_DAT_BACKUP_SUFFIX = "_old"' in (
        ROOT / "src" / "config.py"
    ).read_text(encoding="utf-8")
    assert "LEVEL_DB_BACKUP_SUFFIX" in (
        ROOT / "src" / "config.py"
    ).read_text(encoding="utf-8")


def test_level_dat_page_instantiates_after_a_fresh_engine_start() -> None:
    result = subprocess.run(
        [sys.executable, str(QML_PROBE)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
