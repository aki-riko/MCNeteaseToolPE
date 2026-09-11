# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""PrismQML release and high-level integration contracts."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PRISMQML_VERSION = "0.4.2.24"
EXPECTED_MCP_TOOL_NAMES = {
    "process_project",
    "inspect_world_data",
    "update_level_dat",
    "update_world_database",
    "scan_global_minecraft_data",
    "clean_global_minecraft_data",
}


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_prismqml_release_is_pinned_and_installed() -> None:
    requirements = _read("requirements.txt")
    readme = _read("README.md")

    assert f"prismqml=={EXPECTED_PRISMQML_VERSION}" in requirements.splitlines()
    assert f"`prismqml=={EXPECTED_PRISMQML_VERSION}`" in readme
    assert version("prismqml") == EXPECTED_PRISMQML_VERSION


def test_main_uses_prismqml_startup_splash_contract() -> None:
    source = _read("main.py")

    assert "App.setApplicationDisplayName(APP_TITLE)" in source
    assert "splash_subtitle=SPLASH_SUBTITLE" in source
    assert "window_width=WINDOW_W" in source
    assert "window_height=WINDOW_H" in source
    assert "win.resize(WINDOW_W, WINDOW_H)" not in source
    assert "_disable_broken_splash_icon_shadow" not in source


def test_prismqml_config_is_owned_by_mcneteasetoolpe() -> None:
    main_source = _read("main.py")
    settings_source = _read("src/settings_backend.py")

    assert "config_path=resolve_prismqml_config_path()" in main_source
    assert "persist_appearance=True" in main_source
    assert 'APP_CONFIG_DIR_NAME = "MCNeteaseToolPE"' in settings_source
    assert 'PRISMQML_CONFIG_FILE_NAME = "prismqml.json"' in settings_source


def test_application_config_wins_when_gallery_config_exists() -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        temporary_root = Path(temporary_directory)
        gallery_path = temporary_root / "gallery.json"
        application_path = (
            temporary_root / "roaming" / "MCNeteaseToolPE" / "prismqml.json"
        )
        application_path.parent.mkdir(parents=True)
        gallery_path.write_text(
            json.dumps(
                {
                    "Appearance": {
                        "Theme": "dark",
                        "Skin": "vintage_ticket",
                        "Language": "zh_CN",
                        "AccentColor": "#123456",
                    }
                }
            ),
            encoding="utf-8",
        )
        application_path.write_text(
            json.dumps(
                {
                    "Appearance": {
                        "Theme": "light",
                        "Skin": "fluent",
                        "Language": "en",
                        "AccentColor": "#654321",
                    }
                }
            ),
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment.update(
            {
                "APPDATA": str(temporary_root / "roaming"),
                "MCNETEASE_PRISMQML_CONFIG_FILE": str(application_path),
                "PRISMQML_CONFIG_FILE": str(gallery_path),
                "PYTHONIOENCODING": "utf-8",
                "QT_QPA_PLATFORM": "offscreen",
            }
        )
        script = """
from pathlib import Path
from PySide6.QtCore import QTimer
from prismqml import App
from prismqml.python.config import getConfigManager
from src.settings_backend import resolve_prismqml_config_path

config_path = resolve_prismqml_config_path()
app = App(
    [],
    config_path=config_path,
    persist_appearance=True,
    auto_update_slot_redirect=False,
)
manager = getConfigManager(config_path, persist_appearance=True)
assert Path(manager.getConfigPath()).resolve() == config_path.resolve()
assert manager.theme == "light"
assert manager.skin == "fluent"
assert manager.language == "en"
assert manager.accentColor == "#654321"
QTimer.singleShot(0, app.quit)
raise SystemExit(app.exec())
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )

    assert result.returncode == 0, result.stdout + result.stderr


def test_settings_uses_prismqml_default_update_toast() -> None:
    source = _read("qml/SettingsPage.qml")

    assert "AutoUpdater {" in source
    assert "AutoUpdaterProgressDialogPresenter" not in source
    assert "feedbackPresenter:" not in source
    assert "notifyWhenUpToDate: true" in source
    assert "onClicked: autoUpdater.check()" in source
    assert "statusText" not in source
    assert "onUpToDateNotified" not in source
    assert "onErrorOccurred" not in source


def test_settings_uses_prismqml_spinbox_for_python27_workers() -> None:
    source = _read("qml/SettingsPage.qml")

    assert "SettingsCardGroup {" in source
    assert "SettingsCardCore {" in source
    assert re.search(r"(?m)^\s*Card\s*\{", source) is None
    assert 'objectName: "python27WorkersSpinBox"' in source
    assert "SpinBox {" in source
    assert "maximum: backend ? backend.logicalProcessorCount : 1" in source
    assert "backend.setPython27Workers(Math.round(newValue))" in source


def test_about_card_uses_native_homepage_links() -> None:
    source = _read("qml/SettingsPage.qml")

    assert 'objectName: "aboutSettingsCard"' in source
    assert 'objectName: "aboutTitleLabel"' in source
    assert 'objectName: "aboutVersionPrefix"' in source
    assert 'objectName: "prismQmlHomepageLink"' in source
    assert 'objectName: "aboutDescriptionSuffix"' in source
    assert "type: Enums.label.type_hyperlink" in source
    assert "url: prismQmlHomepage" in source
    assert 'objectName: "projectHomepageButton"' in source
    assert "anchors.right: projectHomepageButton.left" in source
    assert "anchors.right: parent.right" in source
    assert "property url destinationUrl: appProjectHomepage" in source
    assert "style: Enums.button.style_hyperlink" in source
    assert "Qt.openUrlExternally(destinationUrl)" in source


def test_nuitka_script_uses_installed_prismqml_release() -> None:
    source = _read("build_nuitka.ps1")

    assert "[string]$PrismQmlRoot" not in source
    assert "$env:PYTHONPATH" not in source
    assert "importlib.metadata" in source
    assert "m.version('prismqml')" in source
    assert "pathlib.Path(prismqml.__file__).resolve().parent" in source


def test_nuitka_script_builds_a_gui_executable_without_a_new_console() -> None:
    source = _read("build_nuitka.ps1")

    assert '"--windows-console-mode=attach"' in source
    assert '"--windows-console-mode=hide"' not in source
    assert "[int]$NuitkaJobs = 0" in source
    assert '"--jobs=$NuitkaJobs"' in source
    assert "Get-WindowsPeSubsystem" in source
    assert "$windowsGuiSubsystem = 2" in source


def test_python_updater_context_contract() -> None:
    python_source = _read("main.py")

    assert "app.enable_auto_update(" in python_source
    assert 'setContextProperty("appInstallerSilentArgs"' in python_source
    assert 'setContextProperty("appProjectHomepage"' in python_source
    assert 'setContextProperty("prismQmlHomepage"' in python_source


def test_project_qml_reuses_prismqml_text_and_feedback_primitives() -> None:
    sources = {
        path.relative_to(ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in (ROOT / "qml").rglob("*.qml")
    }

    for relative_path, source in sources.items():
        assert re.search(r"(?m)^\s*Text\s*\{", source) is None, relative_path
        assert re.search(r"delegate\s*:\s*Text\s*\{", source) is None, relative_path
        assert "Text.StyledText" not in source, relative_path
        assert re.search(r"<a(?:\s|>)", source, re.IGNORECASE) is None, relative_path
        assert "toastTimer" not in source, relative_path
        assert source.count("elide: Text.") == len(
            re.findall(r"wrapMode:\s*Text\.NoWrap\s+elide:\s*Text\.", source)
        ), relative_path


def test_python_ui_helpers_are_delegated_to_prismqml() -> None:
    level_dat_source = _read("src/level_dat_backend.py")
    package_source = _read("src/package_backend.py")

    assert "get_clipboard_helper().copy(" in level_dat_source
    assert "QGuiApplication.clipboard" not in level_dat_source
    assert "run_in_thread(_create_zip_task, project_dir)" in package_source
    assert "QThread" not in package_source
    assert "_PackageWorker" not in package_source


def test_level_dat_reuses_prismqml_surface_primitives() -> None:
    tag_delegate = _read("qml/LevelDatTagDelegate.qml")
    extra_data_delegate = _read("qml/LevelDatExtraDataDelegate.qml")

    assert tag_delegate.count("Card {") == 1
    assert tag_delegate.count("Badge {") == 1
    assert tag_delegate.count("Separator {") == 1
    assert len(re.findall(r"(?m)^\s*Rectangle\s*\{", tag_delegate)) == 1
    assert "contentPadding: 0" in tag_delegate

    assert extra_data_delegate.count("Card {") == 2
    assert extra_data_delegate.count("Badge {") == 1
    assert len(re.findall(r"(?m)^\s*Rectangle\s*\{", extra_data_delegate)) == 1
    assert extra_data_delegate.count("contentPadding: 0") == 2


def _assert_mcp_page_contract(page_source: str) -> None:
    assert "property string projectDir" not in page_source
    assert "FolderDialog" not in page_source
    assert "mcpPortSpinBox" not in page_source
    assert 'qsTr("连接信息")' not in page_source
    assert "mcpEndpointField" not in page_source
    assert "backend.copyEndpoint()" not in page_source
    assert 'qsTr("接入 %1 个端点")' in page_source
    assert "backend.accessPrompt" in page_source
    assert "backend.copyAccessPrompt()" in page_source
    assert "height: contentHeight" in page_source
    assert "showScrollIndicator" not in page_source


def _assert_mcp_page_tool_list(page_source: str) -> None:
    tool_names = set(re.findall(r'\{ "name": "([^"]+)"', page_source))
    assert tool_names == EXPECTED_MCP_TOOL_NAMES


def _assert_mcp_readme_tool_list(readme: str) -> None:
    mcp_section = readme.split("## 🔌 MCP 服务器", 1)[1].split("## 🛠️", 1)[0]
    tool_names = set(re.findall(r"(?m)^- `([^`]+)`：", mcp_section))
    assert tool_names == EXPECTED_MCP_TOOL_NAMES
    assert "工程识别、只读审核、清理预览" not in readme


def test_documentation_page_is_replaced_by_python_mcp_server() -> None:
    python_source = _read("main.py")
    page_source = _read("qml/McpServerPage.qml")
    backend_source = _read("src/mcp_server_backend.py")
    readme = _read("README.md")

    assert not (ROOT / "qml" / "DocsPage.qml").exists()
    assert "DocsPage.qml" not in python_source
    assert '_page_factory("McpServerPage.qml", mcp_server_backend)' in python_source
    assert '"MCP"' in python_source
    _assert_mcp_page_contract(page_source)
    _assert_mcp_page_tool_list(page_source)
    _assert_mcp_readme_tool_list(readme)
    assert "McpServerBackend()" in python_source
    assert "QTimer.singleShot(0, self.start)" in backend_source
