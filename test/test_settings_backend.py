# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
# 应用设置后端回归测试。

from __future__ import annotations

import json

import pytest
from PySide6.QtCore import QCoreApplication

from prismqml.python.config import ConfigManager

from src.legacy_pylint_runner import WORKER_COUNT_ENV, _worker_count
from src.settings_backend import (
    ApplicationSettingsBackend,
    LOGICAL_PROCESSOR_COUNT,
    ensure_mica_default_enabled,
)


def test_python27_worker_setting_persists_and_applies_to_next_audit(
    tmp_path, monkeypatch
) -> None:
    if LOGICAL_PROCESSOR_COUNT <= 1:
        pytest.skip("单核环境没有可用于持久化测试的第二个并发值")
    settings_file = tmp_path / "settings.json"
    selected = LOGICAL_PROCESSOR_COUNT - 1
    monkeypatch.delenv(WORKER_COUNT_ENV, raising=False)
    backend = ApplicationSettingsBackend(settings_file=settings_file)

    assert backend.python27Workers == LOGICAL_PROCESSOR_COUNT
    assert backend.setPython27Workers(selected) is True
    assert backend.python27Workers == selected
    assert _worker_count(1000) == selected
    assert json.loads(settings_file.read_text(encoding="utf-8")) == {
        "Audit": {"Python27Workers": selected},
        "Paths": {
            "ProjectDirectory": "",
            "NbtFile": "",
            "ProjectDirectories": [],
            "NbtFiles": [],
        },
        "Window": {"CloseAction": "tray"},
    }

    monkeypatch.delenv(WORKER_COUNT_ENV, raising=False)
    reloaded = ApplicationSettingsBackend(settings_file=settings_file)

    assert reloaded.python27Workers == selected
    assert _worker_count(1000) == selected


def test_python27_worker_setting_is_clamped_to_available_processors(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv(WORKER_COUNT_ENV, raising=False)
    backend = ApplicationSettingsBackend(settings_file=tmp_path / "settings.json")

    assert backend.setPython27Workers(0) is True
    assert backend.python27Workers == 1
    assert backend.setPython27Workers(LOGICAL_PROCESSOR_COUNT + 100) is True
    assert backend.python27Workers == LOGICAL_PROCESSOR_COUNT


def test_environment_worker_override_disables_persisted_setting(
    tmp_path, monkeypatch
) -> None:
    settings_file = tmp_path / "settings.json"
    monkeypatch.delenv(WORKER_COUNT_ENV, raising=False)
    persisted = ApplicationSettingsBackend(settings_file=settings_file)
    assert persisted.setPython27Workers(1) is True

    monkeypatch.setenv(WORKER_COUNT_ENV, "7")
    overridden = ApplicationSettingsBackend(settings_file=settings_file)

    assert overridden.environmentOverrideActive is True
    assert overridden.environmentOverrideValue == "7"
    assert overridden.python27Workers == 1
    assert overridden.setPython27Workers(2) is False
    assert _worker_count(1000) == 7


def test_close_action_persists_and_rejects_unknown_values(tmp_path) -> None:
    settings_file = tmp_path / "settings.json"
    backend = ApplicationSettingsBackend(settings_file=settings_file)

    assert backend.closeAction == "tray"
    assert backend.setCloseAction("quit") is True
    assert backend.closeAction == "quit"
    assert backend.setCloseAction("minimize") is False
    assert backend.closeAction == "quit"

    reloaded = ApplicationSettingsBackend(settings_file=settings_file)

    assert reloaded.closeAction == "quit"


def test_close_action_falls_back_to_tray_for_corrupted_value(tmp_path) -> None:
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(
        json.dumps({"Window": {"CloseAction": 123}}), encoding="utf-8"
    )
    backend = ApplicationSettingsBackend(settings_file=settings_file)

    assert backend.closeAction == "tray"


def _with_fresh_config_manager(original):
    """复位引擎 ConfigManager 单例，测试结束后恢复原实例。"""

    def _restore():
        ConfigManager._instance = original

    return _restore


def _settle_config_persistence() -> None:
    """存在 Qt 应用时引擎异步落盘，等待写盘队列清空。"""

    if QCoreApplication.instance() is not None:
        ConfigManager._instance.waitForPersistence(5000)


def test_mica_defaults_enabled_for_missing_config(tmp_path) -> None:
    original = ConfigManager._instance
    ConfigManager._instance = None
    restore = _with_fresh_config_manager(original)
    try:
        config_file = tmp_path / "prismqml.json"

        assert ensure_mica_default_enabled(config_file) is True
        _settle_config_persistence()

        # 引擎默认已是开启时不产生写盘, 生效值必须为开。
        assert ConfigManager._instance.micaEnabled is True
    finally:
        restore()


def test_mica_user_choice_is_never_overridden(tmp_path) -> None:
    config_file = tmp_path / "prismqml.json"
    config_file.write_text(
        json.dumps({"Window": {"MicaEnabled": False, "DpiScale": 125}}),
        encoding="utf-8",
    )
    original = ConfigManager._instance
    ConfigManager._instance = None
    restore = _with_fresh_config_manager(original)
    try:
        assert ensure_mica_default_enabled(config_file) is False
    finally:
        restore()

    payload = json.loads(config_file.read_text(encoding="utf-8"))
    assert payload["Window"]["MicaEnabled"] is False
    assert payload["Window"]["DpiScale"] == 125


def test_mica_enabled_once_for_legacy_config_without_key(tmp_path) -> None:
    config_file = tmp_path / "prismqml.json"
    config_file.write_text(
        json.dumps({"Appearance": {"Theme": "dark"}}),
        encoding="utf-8",
    )
    original = ConfigManager._instance
    ConfigManager._instance = None
    restore = _with_fresh_config_manager(original)
    try:
        assert ensure_mica_default_enabled(config_file) is True
        _settle_config_persistence()
    finally:
        restore()

    # 引擎默认已是开启时不回写文件; 无论是否落盘, 生效值必须为开且旧键保留。
    payload = json.loads(config_file.read_text(encoding="utf-8"))
    assert payload.get("Window", {}).get("MicaEnabled", True) is True
    assert payload["Appearance"]["Theme"] == "dark"
