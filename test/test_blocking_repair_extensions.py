# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""扩展非代码阻塞项修复的真实文件回归测试。"""

from __future__ import annotations

import json
from pathlib import Path
import stat
import struct
import zlib

import pytest

from src.blocking_repair import (
    BlockingRepairService,
    REPAIR_CLEAR_LEVEL_READONLY,
    REPAIR_FIX_PLAYER_CONTROLLERS,
    REPAIR_MOVE_PACK_LAYOUT,
    REPAIR_NORMALIZE_GLYPH_TRANSPARENCY,
    REPAIR_NORMALIZE_JSON_BOM,
    REPAIR_REMOVE_SAFE_RESIDUE,
    REPAIR_SET_MIN_ENGINE_VERSION,
)
from src.netease_content_audit import PLAYER_RENDER_CONTROLLERS
from src.image_audit_utils import png_transparent_pixel_status
from src.pack_scanner import scan


def _manifest(module_type: str, minimum: list[int] | None = None) -> dict[str, object]:
    header: dict[str, object] = {
        "uuid": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "version": [1, 0, 0],
    }
    if minimum is not None:
        header["min_engine_version"] = minimum
    return {
        "header": header,
        "modules": [
            {
                "type": module_type,
                "uuid": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            }
        ],
    }


def _write_manifest(directory: Path, module_type: str, minimum: list[int] | None = None) -> Path:
    directory.mkdir(parents=True)
    path = directory / "manifest.json"
    path.write_text(json.dumps(_manifest(module_type, minimum)), encoding="utf-8")
    return path


def _png(width: int, height: int, pixel: bytes) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    scanline = b"\0" + pixel * width
    raw = scanline * height
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def _repair_id(state: dict[str, object], kind: str) -> str:
    for item in state["items"]:
        if item["kind"] == kind:
            return str(item["id"])
    raise AssertionError(f"未发现修复类型:{kind}")


def test_json_bom_repair_removes_the_same_code_40_from_rescan(tmp_path: Path) -> None:
    source = tmp_path / "config.json"
    source.write_bytes(b"\xef\xbb\xbf{\"enabled\":true}")
    service = BlockingRepairService()

    before = scan(str(tmp_path))
    repair_id = _repair_id(service.inspect(str(tmp_path)), REPAIR_NORMALIZE_JSON_BOM)
    _state, outcome = service.apply_and_inspect(str(tmp_path), repair_id)
    after = scan(str(tmp_path))

    assert any(issue.code == 40 for issue in before)
    assert outcome["success"] is True
    assert not source.read_bytes().startswith(b"\xef\xbb\xbf")
    assert not any(issue.code == 40 for issue in after)


def test_safe_residue_repair_deletes_the_scanned_cache_item(tmp_path: Path) -> None:
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "module.pyc").write_bytes(b"cache")
    service = BlockingRepairService()

    repair_id = _repair_id(service.inspect(str(tmp_path)), REPAIR_REMOVE_SAFE_RESIDUE)
    _state, outcome = service.apply_and_inspect(str(tmp_path), repair_id)

    assert outcome["success"] is True
    assert not cache.exists()
    assert outcome["changedPaths"] == ["__pycache__"]
    assert isinstance(outcome["undo"], dict)


def test_safe_residue_can_be_restored_from_its_isolation_record(tmp_path: Path) -> None:
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    cached_file = cache / "module.pyc"
    cached_file.write_bytes(b"cache")
    service = BlockingRepairService()

    repair_id = _repair_id(service.inspect(str(tmp_path)), REPAIR_REMOVE_SAFE_RESIDUE)
    _state, outcome = service.apply_and_inspect(str(tmp_path), repair_id)
    restored_state, restore_outcome = service.restore_and_inspect(
        str(tmp_path), outcome["undo"]
    )

    assert restore_outcome["success"] is True
    assert cached_file.read_bytes() == b"cache"
    assert restored_state["repairableCount"] == 1


def test_safe_residue_plan_rejects_changed_descendant_before_isolation(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    cached_file = cache / "module.pyc"
    cached_file.write_bytes(b"before")
    service = BlockingRepairService()

    repair_id = _repair_id(service.inspect(str(tmp_path)), REPAIR_REMOVE_SAFE_RESIDUE)
    cached_file.write_bytes(b"after")

    with pytest.raises(ValueError, match="已过期"):
        service.apply_and_inspect(str(tmp_path), repair_id)

    assert cached_file.read_bytes() == b"after"


def test_minimum_engine_repair_removes_code_37_for_same_manifest(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path / "resource_pack", "resources", [1, 17, 0])
    service = BlockingRepairService()

    before = scan(str(tmp_path))
    repair_id = _repair_id(service.inspect(str(tmp_path)), REPAIR_SET_MIN_ENGINE_VERSION)
    _state, outcome = service.apply_and_inspect(str(tmp_path), repair_id)
    after = scan(str(tmp_path))

    assert any(issue.code == 37 for issue in before)
    assert outcome["success"] is True
    assert json.loads(manifest.read_text(encoding="utf-8"))["header"]["min_engine_version"] == [1, 18, 0]
    assert not any(issue.code == 37 for issue in after)


def test_player_controller_repair_writes_the_audited_conditions(tmp_path: Path) -> None:
    player = tmp_path / "entity" / "player.entity.json"
    player.parent.mkdir()
    player.write_text(
        json.dumps({"minecraft:client_entity": {"description": {}}}),
        encoding="utf-8",
    )
    service = BlockingRepairService()

    before = scan(str(tmp_path))
    repair_id = _repair_id(service.inspect(str(tmp_path)), REPAIR_FIX_PLAYER_CONTROLLERS)
    _state, outcome = service.apply_and_inspect(str(tmp_path), repair_id)
    after = scan(str(tmp_path))
    controllers = json.loads(player.read_text(encoding="utf-8"))["minecraft:client_entity"]["description"]["render_controllers"]
    present = {key: value for entry in controllers for key, value in entry.items()}

    assert any(issue.code == 29 for issue in before)
    assert outcome["success"] is True
    assert present == PLAYER_RENDER_CONTROLLERS
    assert not any(issue.code == 29 for issue in after)


def test_pack_layout_repair_moves_the_same_map_pack_to_required_collection(tmp_path: Path) -> None:
    (tmp_path / "level.dat").write_bytes(b"not-a-valid-level")
    source = tmp_path / "nested" / "misplaced_pack"
    _write_manifest(source, "data", [1, 20, 0])
    service = BlockingRepairService()

    before = scan(str(tmp_path))
    repair_id = _repair_id(service.inspect(str(tmp_path)), REPAIR_MOVE_PACK_LAYOUT)
    _state, outcome = service.apply_and_inspect(str(tmp_path), repair_id)
    after = scan(str(tmp_path))
    target = tmp_path / "behavior_packs" / "misplaced_pack"

    assert any(issue.code == 6 and "目录层级" in issue.title for issue in before)
    assert outcome["success"] is True
    assert not source.exists()
    assert (target / "manifest.json").is_file()
    assert not any(issue.code == 6 and "目录层级" in issue.title for issue in after)


def test_pack_layout_refuses_to_move_a_partial_wrapper_directory(tmp_path: Path) -> None:
    (tmp_path / "level.dat").write_bytes(b"not-a-valid-level")
    wrapper = tmp_path / "wrapper"
    source = wrapper / "misplaced_pack"
    _write_manifest(source, "data", [1, 20, 0])
    textures = wrapper / "textures"
    textures.mkdir()
    (textures / "needed.png").write_bytes(b"resource")
    service = BlockingRepairService()

    state = service.inspect(str(tmp_path))

    assert all(item["kind"] != REPAIR_MOVE_PACK_LAYOUT for item in state["items"])
    assert (source / "manifest.json").is_file()
    assert (textures / "needed.png").is_file()


def test_level_readonly_repair_changes_only_file_writability(tmp_path: Path) -> None:
    level = tmp_path / "level.dat"
    original = b"not-a-valid-level"
    level.write_bytes(original)
    level.chmod(stat.S_IREAD)
    service = BlockingRepairService()

    before = scan(str(tmp_path))
    repair_id = _repair_id(service.inspect(str(tmp_path)), REPAIR_CLEAR_LEVEL_READONLY)
    _state, outcome = service.apply_and_inspect(str(tmp_path), repair_id)
    after = scan(str(tmp_path))

    assert any(issue.code == 23 for issue in before)
    assert outcome["success"] is True
    assert level.read_bytes() == original
    assert level.stat().st_mode & stat.S_IWRITE
    assert not any(issue.code == 23 for issue in after)


def test_glyph_transparency_repair_preserves_visible_pixels_and_removes_code_34(
    tmp_path: Path,
) -> None:
    glyph = tmp_path / "font" / "glyph_00.png"
    glyph.parent.mkdir()
    glyph.write_bytes(_png(256, 256, b"\x01\x02\x03\x00"))
    service = BlockingRepairService()

    before = scan(str(tmp_path))
    repair_id = _repair_id(service.inspect(str(tmp_path)), REPAIR_NORMALIZE_GLYPH_TRANSPARENCY)
    _state, outcome = service.apply_and_inspect(str(tmp_path), repair_id)
    after = scan(str(tmp_path))

    assert any(issue.code == 34 and "RGB 未归零" in issue.title for issue in before)
    assert outcome["success"] is True
    assert png_transparent_pixel_status(glyph) == "valid"
    assert not any(issue.code == 34 for issue in after)
