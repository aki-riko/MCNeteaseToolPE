# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
from pathlib import Path
import stat
import struct
import zlib

import src.netease_content_audit as content_audit
import src.pack_scanner as pack_scanner
from src.netease_content_audit import run_content_checks
from src.pack_scanner import scan


def _manifest(module_type: str) -> dict[str, object]:
    return {
        "header": {"min_engine_version": [1, 20, 0]},
        "modules": [{"type": module_type}],
    }


def _write_manifest(pack: Path, module_type: str) -> None:
    pack.mkdir(parents=True, exist_ok=True)
    (pack / "manifest.json").write_text(json.dumps(_manifest(module_type)), encoding="utf-8")


def _codes(root: Path) -> set[int]:
    return {finding.code for finding in run_content_checks(str(root))}


def _png(width: int, height: int, pixel: bytes = b"\x00\x00\x00\x00") -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    row = b"\x00" + pixel * width
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(
        b"IDAT", zlib.compress(row * height)
    ) + chunk(b"IEND", b"")


def _level_dat(network_version: int) -> bytes:
    name = b"NetworkVersion"
    child = b"\x03" + struct.pack("<H", len(name)) + name + struct.pack("<i", network_version)
    payload = b"\x0a\x00\x00" + child + b"\x00"
    return struct.pack("<II", 10, len(payload)) + payload


def test_codes_6_and_10_cover_layout_and_resource_entities(tmp_path: Path) -> None:
    (tmp_path / "level.dat").write_bytes(_level_dat(818))
    _write_manifest(tmp_path / "wrong" / "nested", "data")
    resource = tmp_path / "resource_packs" / "resource_demo"
    _write_manifest(resource, "resources")
    (resource / "entities").mkdir()
    (tmp_path / "behavior_packs" / "missing_manifest").mkdir(parents=True)

    findings = run_content_checks(str(tmp_path))

    assert any(item.code == 6 and "层级" in item.title for item in findings)
    assert sum(item.code == 10 for item in findings) == 2


def test_codes_18_35_and_40_cover_metadata_identifiers_and_numeric_keys(tmp_path: Path) -> None:
    (tmp_path / ".mcs").mkdir()
    (tmp_path / "repeat.py").write_text("aaaaaa_value = 1\n", encoding="utf-8")
    (tmp_path / "keys.json").write_text('{"icon:2147483648": true}', encoding="utf-8")

    assert {18, 35, 40}.issubset(_codes(tmp_path))


def test_codes_12_13_23_30_and_31_cover_level_data(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "db").mkdir()
    assert 12 in _codes(tmp_path)

    level = tmp_path / "level.dat"
    level.write_bytes(b"broken")
    _write_manifest(tmp_path, "data")
    assert {13, 30}.issubset(_codes(tmp_path))

    level.write_bytes(_level_dat(900))
    level.chmod(stat.S_IREAD)
    monkeypatch.setattr(content_audit, "AUDIT_MAX_NETWORK_VERSION", 899)
    codes = _codes(tmp_path)
    assert 23 in codes
    assert 31 in codes


def test_codes_26_29_33_and_34_cover_media_and_player_rules(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(content_audit, "AUDIT_MAX_TEXTURE_DIMENSION", 2048)
    textures = tmp_path / "textures"
    textures.mkdir()
    (textures / "large.png").write_bytes(_png(2049, 1))

    entity = tmp_path / "entity"
    entity.mkdir()
    (entity / "player.entity.json").write_text(
        json.dumps(
            {
                "minecraft:client_entity": {
                    "description": {"render_controllers": []}
                }
            }
        ),
        encoding="utf-8",
    )

    sounds = tmp_path / "sounds"
    sounds.mkdir()
    (sounds / "bad.wav").write_bytes(b"RIFF")
    vorbis = b"\x01vorbis" + struct.pack("<IBIii", 0, 2, 48_000, 0, 129_000)
    (sounds / "high.ogg").write_bytes(vorbis)

    font = tmp_path / "font"
    font.mkdir()
    (font / "glyph_00.png").write_bytes(_png(256, 256, b"\x01\x00\x00\x00"))

    codes = _codes(tmp_path)
    assert {26, 29, 33, 34}.issubset(codes)


def test_codes_24_25_and_35_are_rejecting_errors(tmp_path: Path) -> None:
    (tmp_path / "level.dat").write_bytes(_level_dat(818))
    junk = tmp_path / ".git"
    junk.mkdir()
    (junk / "state").write_text("x", encoding="utf-8")
    (tmp_path / "bbbbbb_name.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")

    issues = scan(str(tmp_path))
    by_code = {issue.code: issue.severity for issue in issues}

    assert by_code[24] == "error"
    assert by_code[25] == "error"
    assert by_code[35] == "error"


def test_unknown_thresholds_are_disabled_and_repeated_name_requires_six(
    tmp_path: Path,
) -> None:
    pack = tmp_path / "behavior_pack"
    _write_manifest(pack, "data")
    textures = pack / "textures"
    textures.mkdir()
    (textures / "large.png").write_bytes(_png(4096, 1))
    (pack / ("abcde" * 24 + ".json")).write_text("{}", encoding="utf-8")
    (pack / "bbbbb_name.py").write_text("aaaaa_value = 1\n", encoding="utf-8")

    codes = _codes(tmp_path)
    issues = scan(str(tmp_path))

    assert 26 not in codes
    assert not any(issue.code == 27 for issue in issues)
    assert not any(issue.code == 35 for issue in issues)


def test_configured_unknown_thresholds_emit_codes_26_and_27(
    tmp_path: Path, monkeypatch
) -> None:
    pack = tmp_path / "resource_pack"
    _write_manifest(pack, "resources")
    textures = pack / "textures"
    textures.mkdir()
    (textures / "large.png").write_bytes(_png(65, 1))
    (pack / "long_name.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(content_audit, "AUDIT_MAX_TEXTURE_DIMENSION", 64)
    monkeypatch.setattr(pack_scanner, "AUDIT_MAX_FILE_NAME_CHARS", 8)

    issues = scan(str(tmp_path))

    assert any(issue.code == 26 for issue in issues)
    assert any(issue.code == 27 for issue in issues)


def test_player_controller_conditions_and_glyph_scope(tmp_path: Path) -> None:
    entity = tmp_path / "entity"
    entity.mkdir()
    valid_controllers = [
        {name: f"  {expression.replace(' ', '   ')}  "}
        for name, expression in content_audit.PLAYER_RENDER_CONTROLLERS.items()
    ]
    player = entity / "player.entity.json"
    player.write_text(
        json.dumps(
            {
                "minecraft:client_entity": {
                    "description": {"render_controllers": valid_controllers}
                }
            }
        ),
        encoding="utf-8",
    )
    unrelated = tmp_path / "textures"
    unrelated.mkdir()
    (unrelated / "glyph_icon.png").write_bytes(_png(1, 1))

    assert 29 not in _codes(tmp_path)
    assert 34 not in _codes(tmp_path)

    valid_controllers[0] = {
        "controller.render.player.first_person": "query.is_in_ui"
    }
    player.write_text(
        json.dumps(
            {
                "minecraft:client_entity": {
                    "description": {"render_controllers": valid_controllers}
                }
            }
        ),
        encoding="utf-8",
    )

    assert 29 in _codes(tmp_path)
