# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
# 应用设置后端回归测试。

from __future__ import annotations

import json

import pytest

from src.legacy_pylint_runner import WORKER_COUNT_ENV, _worker_count
from src.settings_backend import (
    ApplicationSettingsBackend,
    LOGICAL_PROCESSOR_COUNT,
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
