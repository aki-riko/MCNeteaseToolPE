# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""PrismQML release and high-level integration contracts."""

from __future__ import annotations

import re
from importlib.metadata import version
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PRISMQML_VERSION = "0.3.3.1"
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

    assert f"prismqml=={EXPECTED_PRISMQML_VERSION}" in requirements.splitlines()
    assert version("prismqml") == EXPECTED_PRISMQML_VERSION


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
