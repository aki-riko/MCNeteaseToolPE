# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""独立 Minecraft 缓存页与分离按钮的 QML 运行时契约。"""

from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN = REPO_ROOT / "main.py"
PROJECT_PAGE = REPO_ROOT / "qml" / "ProjectPage.qml"
PROJECT_PAGE_PROBE = REPO_ROOT / "test" / "_project_page_qml_probe.py"
CLEANUP_PAGE = REPO_ROOT / "qml" / "MinecraftCleanupPage.qml"


def test_cleanup_is_a_separate_top_level_page_with_uniform_split_actions() -> None:
    main_source = MAIN.read_text(encoding="utf-8")
    project_source = PROJECT_PAGE.read_text(encoding="utf-8")
    cleanup_source = CLEANUP_PAGE.read_text(encoding="utf-8")

    assert 'minecraft_cleanup_backend = MinecraftCleanupBackend()' in main_source
    assert '_page_factory("MinecraftCleanupPage.qml", minecraft_cleanup_backend)' in main_source
    assert '"缓存清理"' in main_source
    assert "MinecraftCleanupPage" not in project_source
    assert "minecraftCleanupBackend" not in project_source

    assert cleanup_source.count("feature: Enums.button.feature_split") == 3
    assert cleanup_source.count("menuItems: root._folderMenuItems()") == 3
    for contract in (
        'objectName: "minecraftCleanupPage"',
        'objectName: "minecraftCleanupCleanableCard"',
        'objectName: "minecraftCleanupProtectedCard"',
        'objectName: "minecraftCleanupConfirmDialog"',
        'objectName: "minecraftCleanupButton_" + modelData.key',
        'objectName: "minecraftCleanupAllButton"',
        'style: Enums.button.style_filled',
        'style: Enums.button.style_primary',
        'backend.openFolder(key || "")',
        "onMenuItemClicked: (_index, _text) => root._openFolder(modelData.key)",
        'onMenuItemClicked: (_index, _text) => root._openFolder("")',
    ):
        assert contract in cleanup_source


def test_project_page_uses_prismqml_tag_for_project_kind() -> None:
    source = PROJECT_PAGE.read_text(encoding="utf-8")

    assert 'objectName: "projectTitle"' in source
    assert 'objectName: "projectTypeTag"' in source
    assert "Tag {" in source
    assert 'qsTr("地图")' in source
    assert 'qsTr("Add-ons")' in source
    assert "backend.classifyProject(projectDir)" in source


def test_project_page_renders_archive_paths_as_reveal_links() -> None:
    source = PROJECT_PAGE.read_text(encoding="utf-8")

    assert 'objectName: "pipelineStatusText"' in source
    assert 'objectName: "pipelineProgressText"' in source
    assert "page.formatProgress(backend ? backend.progress : 0)" in source
    assert 'objectName: "resultMessageText"' in source
    assert 'objectName: "pipelineArchiveLink"' in source
    assert 'objectName: "resultArchiveLink"' in source
    assert source.count("type: Enums.label.type_hyperlink") == 2
    assert source.count("onClicked: backend.revealArchive()") == 2
    for forbidden in (
        "Text.StyledText",
        "messageWithArchiveLink",
        "activateMessageLink",
        "archiveLinkAction",
    ):
        assert forbidden not in source


def test_project_page_caps_long_loading_status_to_card_width() -> None:
    source = PROJECT_PAGE.read_text(encoding="utf-8")

    assert 'objectName: "oneClickRunButton"' in source
    assert "width: page.busy && parent ? parent.width : implicitWidth" in source
    assert "clip: true" in source
    assert "contentAlignment: Enums.button.align_left" in source
    assert "progressStatusFontMetrics.elidedText(" in source
    assert "elide: Text.ElideRight" in source
    assert "maximumLineCount: 1" in source


def test_project_kind_tag_updates_and_stays_right_of_title(tmp_path: Path) -> None:
    map_project = tmp_path / "map"
    addons_project = tmp_path / "addons"
    map_project.mkdir()
    addons_project.mkdir()
    (map_project / "level.dat").write_bytes(b"bedrock-level")
    archive = tmp_path / "project & archive.zip"
    archive.write_bytes(b"zip")
    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT_PAGE_PROBE),
            str(PROJECT_PAGE),
            str(map_project),
            str(addons_project),
            str(archive),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    output = result.stdout + result.stderr
    assert "Detected anchors on an item that is managed by a layout" not in output


def test_cleanup_split_buttons_route_open_folder_after_fresh_engine_start() -> None:
    script = f"""
import os
import sys
from pathlib import Path
sys.path.insert(0, r'{REPO_ROOT}')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QObject, Property, QMetaObject, QUrl, Signal, Slot
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, QQmlExpression
from PySide6.QtWidgets import QApplication
from prismqml import register_types
from prismqml.python.core.engine import EngineManager

app = QApplication.instance() or QApplication([])
engine = QQmlApplicationEngine()
EngineManager.set_engine(engine)
register_types(engine)
sample_root = str(Path(os.environ.get('TEMP', '.')) / 'MinecraftPE_Netease')

class CacheBackend(QObject):
    stateChanged = Signal()
    result = Signal('QVariant')
    busyChanged = Signal()

    def __init__(self):
        super().__init__()
        self.refresh_count = 0
        self.opened_keys = []

    @Property('QVariantMap', notify=stateChanged)
    def state(self):
        return {{
            'rootPath': sample_root,
            'rootExists': True,
            'reclaimableSize': '12.34MB',
            'cleanableRows': [{{
                'key': 'pack_cache',
                'name': '资源包缓存',
                'description': '缓存',
                'sizeText': '12.34MB',
                'filesText': '2 个文件',
                'exists': True,
            }}],
            'protectedRows': [{{
                'key': 'worlds_and_packs',
                'name': '世界、组件与皮肤',
                'description': '默认保留',
                'sizeText': '1.00MB',
                'filesText': '1 个文件',
                'exists': True,
            }}],
            'protectedCountdownSeconds': 3,
            'texts': {{
                'recommendedTitle': '推荐清理',
                'protectedTitle': '有用数据（默认不清理）',
                'refresh': '重新扫描',
                'scanning': '正在扫描…',
                'clean': '清理',
                'cleanAll': '清理全部',
                'openFolder': '打开文件夹',
                'cleanableBadge': '可清理',
                'protectedBadge': '默认保留',
                'missingRoot': '未找到',
                'safeSummary': '安全说明',
                'confirmTitle': '确认清理',
                'confirmAll': '全部确认',
                'confirmSingle': '单项确认',
                'confirmProtected': '删除{{name}}',
                'confirm': '确认清理',
                'cancel': '取消',
                'empty': '暂无可清理内容',
            }},
        }}

    @Property(bool, notify=busyChanged)
    def busy(self):
        return False

    @Slot()
    def refresh(self):
        self.refresh_count += 1

    @Slot(str)
    def clean(self, _key):
        pass

    @Slot()
    def cleanAll(self):
        pass

    @Slot(str)
    def openFolder(self, key):
        self.opened_keys.append(key)

backend = CacheBackend()
component = QQmlComponent(engine, QUrl.fromLocalFile(r'{CLEANUP_PAGE}'))
assert not component.isError(), [error.toString() for error in component.errors()]
page = component.create()
assert page is not None, [error.toString() for error in component.errors()]
page.setProperty('backend', backend)
page.setWidth(1100)
page.setHeight(800)
app.processEvents()

assert page.findChild(QObject, 'minecraftCleanupSummaryCard') is not None
dialog = page.findChild(QObject, 'minecraftCleanupConfirmDialog')
assert dialog is not None
dialog.setProperty('requiresCountdown', True)
app.processEvents()
assert dialog.property('countdown') == 3
assert QMetaObject.invokeMethod(dialog, 'open')
app.processEvents()
assert dialog.property('_confirmEnabled') is False
assert QMetaObject.invokeMethod(dialog, 'reject')

for key in ('pack_cache', '', 'worlds_and_packs'):
    expression = QQmlExpression(engine.rootContext(), page, "_openFolder('" + key + "')")
    expression.evaluate()
    assert not expression.hasError(), expression.error().toString()
app.processEvents()
assert backend.opened_keys == ['pack_cache', '', 'worlds_and_packs']
assert backend.refresh_count >= 1
print('minecraft cleanup split buttons ok')
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    output = result.stdout + result.stderr
    assert "Detected anchors on an item that is managed by a layout" not in output
