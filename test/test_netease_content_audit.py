# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
from pathlib import Path
import stat
import struct
import zlib

import src.netease_content_audit as content_audit
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
    (tmp_path / "repeat.py").write_text("aaaaa_value = 1\n", encoding="utf-8")
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


def test_codes_26_29_33_and_34_cover_media_and_player_rules(tmp_path: Path) -> None:
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


def test_codes_24_25_27_and_35_are_rejecting_errors(tmp_path: Path) -> None:
    (tmp_path / "level.dat").write_bytes(_level_dat(818))
    junk = tmp_path / ".git"
    junk.mkdir()
    (junk / "state").write_text("x", encoding="utf-8")
    (tmp_path / ("a" * 81 + ".json")).write_text("{", encoding="utf-8")
    (tmp_path / "bbbbb_name.py").write_text("value = 1\n", encoding="utf-8")

    issues = scan(str(tmp_path))
    by_code = {issue.code: issue.severity for issue in issues}

    assert by_code[24] == "error"
    assert by_code[25] == "error"
    assert by_code[27] == "error"
    assert by_code[35] == "error"
