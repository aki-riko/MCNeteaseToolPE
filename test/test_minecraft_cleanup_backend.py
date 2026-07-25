# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""网易 Minecraft 全局缓存清理后端回归测试。"""

from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from src.minecraft_cleanup_backend import (
    MC_DATA_DIR_ENV,
    MC_DATA_DIR_NAME,
    MinecraftCleanupService,
)
from src.minecraft_cleanup_qt_backend import MinecraftCleanupBackend


def _data_root(tmp_path: Path) -> Path:
    root = tmp_path / MC_DATA_DIR_NAME
    root.mkdir()
    return root


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _sample_data(root: Path) -> dict[str, Path]:
    return {
        "game_log": _write(root / "logs" / "Debug_Log.txt", "debug"),
        "nested_log": _write(root / "logs" / "Purtle" / "ContentLog.txt", "content"),
        "log_metadata": _write(root / "logs" / "session.json", "{}"),
        "mcp_log": _write(root / "mcp.log", "mcp"),
        "rotated_mcp_log": _write(root / "mcp.log.2026-07-21", "old"),
        "pack_cache": _write(root / "packcache" / "encoded-a" / "payload.bin", "cache"),
        "nested_pack_cache": _write(
            root / "packcache" / "encoded-b" / "nested" / "index",
            "index",
        ),
        "world": _write(root / "minecraftWorlds" / "world-a" / "level.dat", "world"),
        "options": _write(root / "minecraftpe" / "options.txt", "settings"),
        "user_state": _write(root / "storge" / "stream" / "users" / "user.data", "state"),
        "resource_index": _write(root / "sound_definitions.json", "resource"),
    }


def _service(root: Path) -> MinecraftCleanupService:
    return MinecraftCleanupService(data_root_provider=lambda: root)


def test_scan_matches_kaleidos_categories_and_default_protection(tmp_path: Path) -> None:
    root = _data_root(tmp_path)
    paths = _sample_data(root)

    state = _service(root).scan()
    rows = {row["key"]: row for row in state["cleanableRows"]}
    protected = {row["key"]: row for row in state["protectedRows"]}

    assert state["rootPath"] == str(root.resolve())
    assert state["rootExists"] is True
    assert rows["game_logs"]["files"] == 2
    assert rows["mcp_logs"]["files"] == 2
    assert rows["pack_cache"]["files"] == 2
    assert state["reclaimableBytes"] == sum(
        paths[key].stat().st_size
        for key in (
            "game_log",
            "nested_log",
            "mcp_log",
            "rotated_mcp_log",
            "pack_cache",
            "nested_pack_cache",
        )
    )
    assert state["protectedCountdownSeconds"] == 3
    assert all(row["defaultSelected"] is False for row in protected.values())
    assert protected["worlds_and_packs"]["files"] == 1
    assert protected["settings_and_user_state"]["files"] == 2
    assert protected["resource_indexes"]["files"] == 1


def test_clean_all_removes_only_recommended_data(tmp_path: Path) -> None:
    root = _data_root(tmp_path)
    paths = _sample_data(root)

    result = _service(root).clean_all()

    assert result["success"] is True
    assert result["removedFiles"] == 6
    for key in (
        "game_log",
        "nested_log",
        "mcp_log",
        "rotated_mcp_log",
        "pack_cache",
        "nested_pack_cache",
    ):
        assert paths[key].exists() is False
    for key in ("log_metadata", "world", "options", "user_state", "resource_index"):
        assert paths[key].exists() is True
    assert (root / "packcache").is_dir()


@pytest.mark.parametrize(
    ("category", "removed", "preserved"),
    (
        ("worlds_and_packs", ("world",), ("game_log", "options", "resource_index")),
        ("settings_and_user_state", ("options", "user_state"), ("game_log", "world")),
        ("resource_indexes", ("resource_index",), ("game_log", "world", "options")),
    ),
)
def test_protected_categories_require_explicit_single_category_cleanup(
    tmp_path: Path,
    category: str,
    removed: tuple[str, ...],
    preserved: tuple[str, ...],
) -> None:
    root = _data_root(tmp_path)
    paths = _sample_data(root)

    result = _service(root).clean(category)

    assert result["success"] is True
    for key in removed:
        assert paths[key].exists() is False
    for key in preserved:
        assert paths[key].exists() is True


def test_locked_file_is_reported_and_skipped(tmp_path: Path, monkeypatch) -> None:
    root = _data_root(tmp_path)
    locked = _write(root / "logs" / "locked.txt", "locked")
    removable = _write(root / "logs" / "removable.txt", "remove")
    original_unlink = Path.unlink

    def _unlink(path: Path, *args, **kwargs):
        if path == locked:
            raise PermissionError("locked")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", _unlink)

    result = _service(root).clean("game_logs")

    assert result["success"] is True
    assert result["removedFiles"] == 1
    assert result["failedFiles"] == 1
    assert "跳过" in result["message"]
    assert locked.exists() is True
    assert removable.exists() is False


def test_root_path_uses_environment_override_and_fails_closed(tmp_path: Path, monkeypatch) -> None:
    root = _data_root(tmp_path)
    monkeypatch.setenv(MC_DATA_DIR_ENV, str(root))

    assert MinecraftCleanupService().scan()["rootPath"] == str(root.resolve())

    with pytest.raises(ValueError, match=MC_DATA_DIR_NAME):
        MinecraftCleanupService(data_root_provider=lambda: tmp_path).scan()

    service = _service(root)
    monkeypatch.setattr(service, "_is_link_like", lambda path: path == root)
    with pytest.raises(ValueError, match="符号链接"):
        service.scan()


def test_recommended_cleanup_skips_linked_cache_directory(tmp_path: Path, monkeypatch) -> None:
    root = _data_root(tmp_path)
    cached = _write(root / "packcache" / "payload.bin", "cache")
    service = _service(root)
    pack_cache = root / "packcache"
    original_is_link_like = service._is_link_like
    monkeypatch.setattr(
        service,
        "_is_link_like",
        lambda path: path == pack_cache or original_is_link_like(path),
    )

    state = service.scan()
    row = next(item for item in state["cleanableRows"] if item["key"] == "pack_cache")
    result = service.clean("pack_cache")

    assert row["files"] == 0
    assert result["success"] is False
    assert cached.exists() is True


def test_folder_mapping_matches_each_cleanup_scope(tmp_path: Path) -> None:
    root = _data_root(tmp_path)
    _sample_data(root)
    service = _service(root)

    assert service.folder_for("game_logs") == (root / "logs").resolve()
    assert service.folder_for("pack_cache") == (root / "packcache").resolve()
    assert service.folder_for("mcp_logs") == root.resolve()
    assert service.folder_for("worlds_and_packs") == (root / "minecraftWorlds").resolve()
    assert service.folder_for("settings_and_user_state") == (root / "minecraftpe").resolve()
    assert service.folder_for("resource_indexes") == (root / "ClientCache").resolve()
    assert service.folder_for() == root.resolve()


def test_qml_backend_open_folder_uses_injected_desktop_opener(tmp_path: Path) -> None:
    root = _data_root(tmp_path)
    _sample_data(root)
    opened: list[Path] = []
    results: list[dict[str, object]] = []
    backend = MinecraftCleanupBackend(
        service=_service(root),
        folder_opener=lambda folder: not opened.append(folder),
    )
    backend.result.connect(results.append)

    backend.openFolder("pack_cache")

    assert opened == [(root / "packcache").resolve()]
    assert results and results[0]["success"] is True
    assert str(opened[0]) in results[0]["message"]


def test_qml_backend_refreshes_on_worker_and_publishes_state(tmp_path: Path) -> None:
    application = QCoreApplication.instance() or QCoreApplication([])
    assert application is not None
    root = _data_root(tmp_path)
    _sample_data(root)
    backend = MinecraftCleanupBackend(service=_service(root))
    states: list[dict[str, object]] = []
    loop = QEventLoop()
    backend.stateChanged.connect(lambda: (states.append(backend.state), loop.quit()))
    QTimer.singleShot(5_000, loop.quit)

    backend.refresh()
    assert backend.busy is True
    loop.exec()

    assert backend.busy is False
    assert len(states) == 1
    assert states[0]["rootPath"] == str(root.resolve())
    assert states[0]["reclaimableBytes"] > 0
