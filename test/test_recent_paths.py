# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""工程与 NBT 最近路径持久化回归测试。"""

from __future__ import annotations

import json
from pathlib import Path

from src.backends import ProjectBackend
from src.legacy_pylint_runner import WORKER_COUNT_ENV
from src.level_dat_backend import LevelDatBackend
from src import settings_backend as settings_module
from src.settings_backend import ApplicationSettingsBackend


ROOT = Path(__file__).resolve().parents[1]


def test_default_settings_file_is_under_appdata_application_directory(
    tmp_path: Path, monkeypatch
) -> None:
    app_data = tmp_path / "Roaming"
    monkeypatch.delenv(settings_module.SETTINGS_FILE_ENV, raising=False)
    monkeypatch.setenv(settings_module.APP_DATA_ENV, str(app_data))

    assert settings_module._settings_file() == (
        app_data / settings_module.APP_CONFIG_DIR_NAME / settings_module.SETTINGS_FILE_NAME
    )


def test_recent_project_and_nbt_paths_persist_and_reload(
    tmp_path: Path, monkeypatch
) -> None:
    settings_file = tmp_path / "settings.json"
    project_dirs = [tmp_path / "project-one", tmp_path / "project-two"]
    level_files = [
        tmp_path / "world-one" / "level.dat",
        tmp_path / "world-two" / "level.dat",
    ]
    for project_dir in project_dirs:
        project_dir.mkdir()
    for level_dat in level_files:
        level_dat.parent.mkdir()
        level_dat.write_bytes(b"level-data-placeholder")
    monkeypatch.delenv(WORKER_COUNT_ENV, raising=False)
    backend = ApplicationSettingsBackend(settings_file=settings_file)

    for project_dir in project_dirs:
        assert backend.rememberProjectPath(str(project_dir)) is True
    for level_dat in level_files:
        assert backend.rememberNbtPath(str(level_dat)) is True
    assert backend.rememberProjectPath(str(project_dirs[0])) is True
    assert backend.rememberNbtPath(str(level_files[0])) is True
    expected_projects = [str(path.resolve()) for path in project_dirs]
    expected_levels = [str(path.resolve()) for path in level_files]
    assert backend.savedProjectPaths == expected_projects
    assert backend.savedNbtPaths == expected_levels
    assert backend.recentProjectPath == expected_projects[0]
    assert backend.recentNbtPath == expected_levels[0]

    payload = json.loads(settings_file.read_text(encoding="utf-8"))
    assert payload["Paths"] == {
        "ProjectDirectory": "",
        "NbtFile": "",
        "ProjectDirectories": expected_projects,
        "NbtFiles": expected_levels,
    }

    reloaded = ApplicationSettingsBackend(settings_file=settings_file)
    assert reloaded.savedProjectPaths == expected_projects
    assert reloaded.savedNbtPaths == expected_levels
    assert reloaded.recentProjectPath == expected_projects[0]
    assert reloaded.recentNbtPath == expected_levels[0]


def test_recent_paths_reject_missing_or_non_nbt_targets(tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.json"
    other_file = tmp_path / "other.dat"
    other_file.write_bytes(b"not-level-dat")
    backend = ApplicationSettingsBackend(settings_file=settings_file)

    assert backend.rememberProjectPath(str(tmp_path / "missing")) is False
    assert backend.rememberNbtPath(str(other_file)) is False
    assert backend.recentProjectPath == ""
    assert backend.recentNbtPath == ""
    assert settings_file.exists() is False


def test_legacy_prismqml_settings_are_migrated_to_appdata_target(
    tmp_path: Path, monkeypatch
) -> None:
    legacy_file = tmp_path / "legacy" / "mcneteasetoolpe.json"
    target_file = tmp_path / "Roaming" / "MCNeteaseToolPE" / "settings.json"
    legacy_file.parent.mkdir()
    legacy_file.write_text(
        json.dumps({"Audit": {"Python27Workers": 1}}),
        encoding="utf-8",
    )
    monkeypatch.delenv(WORKER_COUNT_ENV, raising=False)
    monkeypatch.setattr(settings_module, "LEGACY_SETTINGS_FILE", legacy_file)
    monkeypatch.setattr(settings_module, "_settings_file", lambda: target_file)

    backend = ApplicationSettingsBackend()

    assert backend.python27Workers == 1
    assert target_file.is_file()
    assert json.loads(target_file.read_text(encoding="utf-8"))["Paths"] == {
        "ProjectDirectory": "",
        "NbtFile": "",
        "ProjectDirectories": [],
        "NbtFiles": [],
    }


def test_existing_single_path_keys_remain_available_as_history(
    tmp_path: Path,
) -> None:
    settings_file = tmp_path / "settings.json"
    project_dir = tmp_path / "legacy-project"
    level_dat = tmp_path / "legacy-world" / "level.dat"
    project_dir.mkdir()
    level_dat.parent.mkdir()
    level_dat.write_bytes(b"legacy-level-data")
    settings_file.write_text(
        json.dumps(
            {
                "Paths": {
                    "ProjectDirectory": str(project_dir),
                    "NbtFile": str(level_dat),
                }
            }
        ),
        encoding="utf-8",
    )

    backend = ApplicationSettingsBackend(settings_file=settings_file)

    assert backend.savedProjectPaths == [str(project_dir)]
    assert backend.savedNbtPaths == [str(level_dat)]
    assert backend.recentProjectPath == str(project_dir)
    assert backend.recentNbtPath == str(level_dat)


def test_page_backends_share_and_update_recent_paths(tmp_path: Path) -> None:
    settings = ApplicationSettingsBackend(settings_file=tmp_path / "settings.json")
    project_dir = tmp_path / "project"
    level_dat = tmp_path / "world" / "level.dat"
    project_dir.mkdir()
    level_dat.parent.mkdir()
    level_dat.write_bytes(b"level-data-placeholder")
    project_backend = ProjectBackend(settings_backend=settings)
    level_backend = LevelDatBackend(settings_backend=settings)

    assert project_backend.rememberProjectPath(str(project_dir)) is True
    assert project_backend.recentProjectPath == str(project_dir.resolve())
    assert project_backend.savedProjectPaths == [str(project_dir.resolve())]
    level_backend._on_loaded(({"filePath": str(level_dat)}, [], []))
    assert level_backend.recentNbtPath == str(level_dat.resolve())
    assert level_backend.savedNbtPaths == [str(level_dat.resolve())]


def test_pages_restore_recent_paths_and_navigation_uses_nbt_name() -> None:
    project_source = (ROOT / "qml" / "ProjectPage.qml").read_text(encoding="utf-8")
    nbt_source = (ROOT / "qml" / "LevelDatPage.qml").read_text(encoding="utf-8")
    main_source = (ROOT / "main.py").read_text(encoding="utf-8")

    assert "backend.recentProjectPath" in project_source
    assert "backend.savedProjectPaths" in project_source
    assert "backend.rememberProjectPath(projectDir)" in project_source
    assert "Component.onCompleted: restoreRecentProjectDir()" in project_source
    assert 'objectName: "projectPathBrowseButton"' in project_source
    assert "feature: Enums.button.feature_split" in project_source
    assert "page.projectPathMenuItems()" in project_source
    assert "page.selectSavedProjectPath(index)" in project_source
    assert "backend.recentNbtPath" in nbt_source
    assert "backend.savedNbtPaths" in nbt_source
    assert "page.loadSourceNow(recentPath)" in nbt_source
    assert "Component.onCompleted: restoreRecentSource()" in nbt_source
    assert 'objectName: "levelDatBrowseButton"' in nbt_source
    assert "page.nbtPathMenuItems()" in nbt_source
    assert "page.selectSavedNbtPath(index)" in nbt_source
    assert project_source.count("feature: Enums.button.feature_split") == 1
    assert nbt_source.count("feature: Enums.button.feature_split") == 1
    assert "ProjectBackend(settings_backend=settings_backend)" in main_source
    assert "LevelDatBackend(settings_backend=settings_backend)" in main_source
    assert '"NBT",' in main_source
