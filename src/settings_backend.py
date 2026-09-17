# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
# 应用设置持久化与 QML 门面。
# Persisted application settings and their QML-facing facade.

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import ClassVar

from PySide6.QtCore import QObject, Property, Signal, Slot
from prismqml.python.config import (
    DEFAULT_CONFIG_DIR,
    RangedEntry,
    SettingEntry,
    SettingsCore,
    Validator,
    getConfigManager,
)

from .legacy_pylint_runner import WORKER_COUNT_ENV


LOGGER = logging.getLogger(__name__)

SETTINGS_FILE_ENV = "MCNETEASE_SETTINGS_FILE"
CLOSE_ACTION_TRAY = "tray"
CLOSE_ACTION_QUIT = "quit"
CLOSE_ACTIONS = (CLOSE_ACTION_TRAY, CLOSE_ACTION_QUIT)
PRISMQML_CONFIG_FILE_ENV = "MCNETEASE_PRISMQML_CONFIG_FILE"
APP_DATA_ENV = "APPDATA"
XDG_CONFIG_HOME_ENV = "XDG_CONFIG_HOME"
APP_CONFIG_DIR_NAME = "MCNeteaseToolPE"
SETTINGS_FILE_NAME = "settings.json"
PRISMQML_CONFIG_FILE_NAME = "prismqml.json"
LOGICAL_PROCESSOR_COUNT = max(1, os.cpu_count() or 1)
LEGACY_SETTINGS_FILE = DEFAULT_CONFIG_DIR / "mcneteasetoolpe.json"


def _default_config_root() -> Path:
    app_data = os.environ.get(APP_DATA_ENV, "").strip()
    if app_data:
        return Path(app_data).expanduser()
    configured_root = os.environ.get(XDG_CONFIG_HOME_ENV, "").strip()
    return (
        Path(configured_root).expanduser()
        if configured_root
        else Path.home() / ".config"
    )


def _default_settings_file() -> Path:
    return _default_config_root() / APP_CONFIG_DIR_NAME / SETTINGS_FILE_NAME


DEFAULT_SETTINGS_FILE = _default_settings_file()


def _settings_file() -> Path:
    configured = os.environ.get(SETTINGS_FILE_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    return _default_settings_file()


def resolve_prismqml_config_path() -> Path:
    """返回 MCNeteaseToolPE 独占的 PrismQML 引擎配置路径。"""

    configured = os.environ.get(PRISMQML_CONFIG_FILE_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    return _default_config_root() / APP_CONFIG_DIR_NAME / PRISMQML_CONFIG_FILE_NAME


def ensure_mica_default_enabled(config_path: Path) -> bool:
    """云母效果默认开启；仅在配置从未写过该键时生效一次。

    引擎内置默认值为关闭。首次运行或旧配置缺少 Window/MicaEnabled 时写入
    True；用户显式选择后(包括关闭)不再覆盖。
    """

    payload = None
    try:
        if config_path.is_file():
            payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        LOGGER.warning("无法读取引擎配置：%s", config_path, exc_info=True)
        payload = None
    window_section = payload.get("Window") if isinstance(payload, dict) else None
    if isinstance(window_section, dict) and "MicaEnabled" in window_section:
        return False
    manager = getConfigManager(str(config_path), persist_appearance=True)
    manager.setMicaEnabled(True)
    return True


class _StringEntry(SettingEntry):
    """只接受 JSON 字符串的持久化条目。"""

    def prepare(self, incoming: object) -> str:
        if not isinstance(incoming, str):
            raise TypeError(f"{self.key} 必须是字符串")
        return incoming

    def decode(self, raw: object) -> str:
        if not isinstance(raw, str):
            raise ValueError(f"{self.key} 必须是字符串")
        return self.prepare(raw)


class _StringListEntry(SettingEntry):
    """只接受字符串列表，并保持去重后的原始顺序。"""

    def prepare(self, incoming: object) -> list[str]:
        if not isinstance(incoming, (list, tuple)):
            raise TypeError(f"{self.key} 必须是字符串列表")
        if not all(isinstance(value, str) for value in incoming):
            raise TypeError(f"{self.key} 只能包含字符串")
        return _unique_paths(list(incoming))

    def decode(self, raw: object) -> list[str]:
        if not isinstance(raw, list):
            raise ValueError(f"{self.key} 必须是 JSON 数组")
        return self.prepare(raw)


def _unique_paths(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value:
            continue
        key = os.path.normcase(os.path.normpath(value))
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _promote_path(paths: list[str], value: str) -> list[str]:
    key = os.path.normcase(os.path.normpath(value))
    remaining = [
        path
        for path in paths
        if os.path.normcase(os.path.normpath(path)) != key
    ]
    return [value, *remaining]


def _existing_path(value: str, *, directory: bool) -> str:
    try:
        path = Path(value).expanduser().resolve()
    except (OSError, RuntimeError):
        LOGGER.warning("无法解析最近路径：%s", value, exc_info=True)
        return ""
    exists = path.is_dir() if directory else path.is_file()
    if not exists:
        LOGGER.warning("拒绝保存不存在的最近路径：%s", path)
        return ""
    return os.path.normpath(str(path))


class ApplicationSettings(SettingsCore):
    """Persisted settings schema for this application."""

    python27_workers: ClassVar[RangedEntry] = RangedEntry(
        group="Audit",
        name="Python27Workers",
        default=LOGICAL_PROCESSOR_COUNT,
        validator=Validator.between(1, LOGICAL_PROCESSOR_COUNT),
    )
    recent_project_path: ClassVar[SettingEntry] = _StringEntry(
        group="Paths",
        name="ProjectDirectory",
        default="",
    )
    recent_nbt_path: ClassVar[SettingEntry] = _StringEntry(
        group="Paths",
        name="NbtFile",
        default="",
    )
    recent_project_paths: ClassVar[SettingEntry] = _StringListEntry(
        group="Paths",
        name="ProjectDirectories",
        default=[],
    )
    recent_nbt_paths: ClassVar[SettingEntry] = _StringListEntry(
        group="Paths",
        name="NbtFiles",
        default=[],
    )
    close_action: ClassVar[SettingEntry] = _StringEntry(
        group="Window",
        name="CloseAction",
        default=CLOSE_ACTION_TRAY,
    )


class ApplicationSettingsBackend(QObject):
    """Expose application settings to QML and apply them to future audits."""

    python27WorkersChanged = Signal()
    recentProjectPathChanged = Signal()
    recentNbtPathChanged = Signal()
    closeActionChanged = Signal()

    def __init__(
        self,
        parent: QObject | None = None,
        settings_file: str | os.PathLike[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self._environment_override_value = os.environ.get(WORKER_COUNT_ENV, "").strip()
        self._settings = ApplicationSettings(self)
        target_file = (
            Path(settings_file).expanduser() if settings_file else _settings_file()
        )
        self._load_settings(target_file, migrate_legacy=settings_file is None)
        self._settings.python27_workers.valueUpdated.connect(self._on_worker_count_changed)
        self._settings.recent_project_path.valueUpdated.connect(
            self._on_recent_project_path_changed
        )
        self._settings.recent_nbt_path.valueUpdated.connect(
            self._on_recent_nbt_path_changed
        )
        self._settings.recent_project_paths.valueUpdated.connect(
            self._on_recent_project_path_changed
        )
        self._settings.recent_nbt_paths.valueUpdated.connect(
            self._on_recent_nbt_path_changed
        )
        self._settings.close_action.valueUpdated.connect(
            self._on_close_action_changed
        )
        if not self._environment_override_value:
            self._apply_worker_count_to_environment()

    def _load_settings(self, target_file: Path, *, migrate_legacy: bool) -> None:
        should_migrate = (
            migrate_legacy
            and not target_file.exists()
            and LEGACY_SETTINGS_FILE.is_file()
        )
        if not should_migrate:
            self._settings.load(target_file)
            return
        loaded = self._settings.load(LEGACY_SETTINGS_FILE)
        self._settings.file = target_file
        if loaded and not self._settings.save():
            LOGGER.warning("迁移应用设置失败：%s", target_file)

    def _get_python27_workers(self) -> int:
        return int(self._settings.get(ApplicationSettings.python27_workers))

    python27Workers = Property(
        int,
        _get_python27_workers,
        notify=python27WorkersChanged,
    )

    @Property(str, notify=recentProjectPathChanged)
    def recentProjectPath(self) -> str:
        paths = self.savedProjectPaths
        return paths[0] if paths else ""

    @Property(str, notify=recentNbtPathChanged)
    def recentNbtPath(self) -> str:
        paths = self.savedNbtPaths
        return paths[0] if paths else ""

    @Property("QVariantList", notify=recentProjectPathChanged)
    def savedProjectPaths(self) -> list[str]:
        paths = self._settings.get(ApplicationSettings.recent_project_paths)
        legacy = self._settings.get(ApplicationSettings.recent_project_path)
        return _unique_paths([*paths, legacy])

    @Property("QVariantList", notify=recentNbtPathChanged)
    def savedNbtPaths(self) -> list[str]:
        paths = self._settings.get(ApplicationSettings.recent_nbt_paths)
        legacy = self._settings.get(ApplicationSettings.recent_nbt_path)
        return _unique_paths([*paths, legacy])

    def _get_close_action(self) -> str:
        value = str(self._settings.get(ApplicationSettings.close_action))
        return value if value in CLOSE_ACTIONS else CLOSE_ACTION_TRAY

    @Property(str, notify=closeActionChanged)
    def closeAction(self) -> str:
        return self._get_close_action()

    @Property(int, constant=True)
    def logicalProcessorCount(self) -> int:
        return LOGICAL_PROCESSOR_COUNT

    @Property(bool, constant=True)
    def environmentOverrideActive(self) -> bool:
        return bool(self._environment_override_value)

    @Property(str, constant=True)
    def environmentOverrideValue(self) -> str:
        return self._environment_override_value

    def _apply_worker_count_to_environment(self) -> None:
        os.environ[WORKER_COUNT_ENV] = str(self._get_python27_workers())

    @Slot(object)
    def _on_worker_count_changed(self, _value: object) -> None:
        if not self._environment_override_value:
            self._apply_worker_count_to_environment()
        self.python27WorkersChanged.emit()

    @Slot(object)
    def _on_recent_project_path_changed(self, _value: object) -> None:
        self.recentProjectPathChanged.emit()

    @Slot(object)
    def _on_recent_nbt_path_changed(self, _value: object) -> None:
        self.recentNbtPathChanged.emit()

    @Slot(object)
    def _on_close_action_changed(self, _value: object) -> None:
        self.closeActionChanged.emit()

    @Slot(int, result=bool)
    def setPython27Workers(self, value: int) -> bool:
        if self._environment_override_value:
            return False
        return self._settings.set(ApplicationSettings.python27_workers, int(value))

    @Slot(str, result=bool)
    def rememberProjectPath(self, value: str) -> bool:
        normalized = _existing_path(value, directory=True)
        if not normalized:
            return False
        paths = _promote_path(self.savedProjectPaths, normalized)
        return self._settings.set(ApplicationSettings.recent_project_paths, paths)

    @Slot(str, result=bool)
    def rememberNbtPath(self, value: str) -> bool:
        normalized = _existing_path(value, directory=False)
        if not normalized or Path(normalized).name.casefold() != "level.dat":
            LOGGER.warning("拒绝保存非 level.dat 的最近 NBT 路径：%s", value)
            return False
        paths = _promote_path(self.savedNbtPaths, normalized)
        return self._settings.set(ApplicationSettings.recent_nbt_paths, paths)

    @Slot(str, result=bool)
    def setCloseAction(self, value: str) -> bool:
        if value not in CLOSE_ACTIONS:
            LOGGER.warning("拒绝保存未知的关闭行为：%s", value)
            return False
        return self._settings.set(ApplicationSettings.close_action, value)


__all__ = [
    "ApplicationSettings",
    "ApplicationSettingsBackend",
    "APP_CONFIG_DIR_NAME",
    "CLOSE_ACTIONS",
    "CLOSE_ACTION_QUIT",
    "CLOSE_ACTION_TRAY",
    "DEFAULT_SETTINGS_FILE",
    "LEGACY_SETTINGS_FILE",
    "LOGICAL_PROCESSOR_COUNT",
    "SETTINGS_FILE_NAME",
    "SETTINGS_FILE_ENV",
]
