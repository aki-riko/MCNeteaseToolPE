# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from pathlib import Path

import pytest

from src.mcp_project_service import ProjectToolService
from src.minecraft_cleanup_backend import MinecraftCleanupService
from src.minecraft_cleanup_definitions import MC_DATA_DIR_NAME


def _service_for(root: Path) -> ProjectToolService:
    cleanup = MinecraftCleanupService(data_root_provider=lambda: root)
    return ProjectToolService(global_cleanup_service=cleanup)


def _assert_cleanup_categories(state: dict[str, object]) -> None:
    assert {row["key"] for row in state["cleanableRows"]} == {
        "game_logs",
        "mcp_logs",
        "pack_cache",
    }
    assert {row["key"] for row in state["protectedRows"]} == {
        "worlds_and_packs",
        "settings_and_user_state",
        "resource_indexes",
    }


def test_global_cleanup_requires_scan_token_and_preserves_protected_data(
    tmp_path: Path,
) -> None:
    root = tmp_path / MC_DATA_DIR_NAME
    log = root / "logs" / "Debug_Log.txt"
    world = root / "minecraftWorlds" / "demo" / "level.dat"
    log.parent.mkdir(parents=True)
    world.parent.mkdir(parents=True)
    log.write_text("log", encoding="utf-8")
    world.write_text("world", encoding="utf-8")
    service = _service_for(root)

    state = service.scan_global_minecraft_data()
    _assert_cleanup_categories(state)
    assert state["recommended_category"] == "recommended"
    scan_token = str(state["scan_token"])
    service.clean_global_minecraft_data("recommended", scan_token, confirm=True)
    assert not log.exists()
    assert world.exists()
    with pytest.raises(PermissionError, match="先调用 scan_global_minecraft_data"):
        service.clean_global_minecraft_data("recommended", scan_token, confirm=True)


def test_global_cleanup_double_confirms_protected_data(tmp_path: Path) -> None:
    root = tmp_path / MC_DATA_DIR_NAME
    world = root / "minecraftWorlds" / "demo" / "level.dat"
    world.parent.mkdir(parents=True)
    world.write_text("world", encoding="utf-8")
    service = _service_for(root)
    scan_token = str(service.scan_global_minecraft_data()["scan_token"])

    with pytest.raises(PermissionError, match="confirm_protected"):
        service.clean_global_minecraft_data("worlds_and_packs", scan_token, confirm=True)
    service.clean_global_minecraft_data(
        "worlds_and_packs",
        scan_token,
        confirm=True,
        confirm_protected=True,
    )
    assert not world.exists()


def test_global_cleanup_rejects_missing_or_stale_scan_token(tmp_path: Path) -> None:
    root = tmp_path / MC_DATA_DIR_NAME
    first_log = root / "logs" / "first.txt"
    first_log.parent.mkdir(parents=True)
    first_log.write_text("first", encoding="utf-8")
    service = _service_for(root)

    with pytest.raises(PermissionError, match="先调用 scan_global_minecraft_data"):
        service.clean_global_minecraft_data("game_logs", "guessed", confirm=True)
    state = service.scan_global_minecraft_data()
    with pytest.raises(ValueError, match="必须来自"):
        service.clean_global_minecraft_data(
            "guessed_category", str(state["scan_token"]), confirm=True
        )
    second_log = root / "logs" / "second.txt"
    second_log.write_text("changed after scan", encoding="utf-8")

    with pytest.raises(RuntimeError, match="扫描后发生变化"):
        service.clean_global_minecraft_data(
            "game_logs", str(state["scan_token"]), confirm=True
        )
    assert first_log.exists()
    assert second_log.exists()
