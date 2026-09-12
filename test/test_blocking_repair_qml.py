# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""阻塞项修复页的导航契约与离屏 QML 渲染回归测试。"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN = REPO_ROOT / "main.py"
PAGE = REPO_ROOT / "qml" / "BlockingRepairPage.qml"


def test_blocking_repair_is_a_separate_top_level_page() -> None:
    main_source = MAIN.read_text(encoding="utf-8")
    page_source = PAGE.read_text(encoding="utf-8")

    assert "from src.blocking_repair_backend import BlockingRepairBackend" in main_source
    assert 'blocking_repair_backend = BlockingRepairBackend()' in main_source
    assert '_page_factory("BlockingRepairPage.qml", blocking_repair_backend)' in main_source
    assert '"阻塞项修复"' in main_source
    for contract in (
        'objectName: "blockingRepairPage"',
        'objectName: "blockingRepairInspectButton"',
        'objectName: "blockingRepairItemsCard"',
        'objectName: "blockingRepairRemainingCard"',
        'objectName: "blockingRepairConfirmDialog"',
        'objectName: "blockingRepairApplyButton_" + modelData.id',
        'objectName: "blockingRepairActionBadge_" + modelData.id',
        'objectName: "blockingRepairGuidance_" + index',
        "repairDialog.repairDestructive = item.destructive === true",
        'objectName: "blockingRepairUndoButton"',
        'backend.undoLastRemoval()',
        'qsTr("隔离清理")',
        'qsTr("处理建议：%1")',
        "backend.applyRepair(repairId)",
        "完成后自动复审",
    ):
        assert contract in page_source


def test_blocking_repair_page_loads_and_renders_preview_rows_offscreen() -> None:
    script = f"""
import os
import sys
sys.path.insert(0, r'{REPO_ROOT}')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QMetaObject, QObject, QUrl
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, QQmlExpression
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtWidgets import QApplication
from prismqml import register_types
from prismqml.python.core.engine import EngineManager
from src.blocking_repair_backend import BlockingRepairBackend

app = QApplication.instance() or QApplication([])
engine = QQmlApplicationEngine()
EngineManager.set_engine(engine)
register_types(engine)
component = QQmlComponent(engine, QUrl.fromLocalFile(r'{PAGE}'))
assert not component.isError(), [error.toString() for error in component.errors()]
page = component.create()
assert isinstance(page, QQuickItem), [error.toString() for error in component.errors()]
backend = BlockingRepairBackend()
backend._state = {{
    'phase': 'ready',
    'rootPath': r'{REPO_ROOT}',
    'message': '已发现 2 项可自动优化项；执行后会自动复审。',
    'repairableCount': 2,
    'auditErrorCount': 1,
    'auditWarningCount': 0,
    'items': [{{
        'id': 'preview-repair',
        'kind': 'create_required_directory',
        'title': '补全行为包必需目录',
        'detail': '缺少 entities。',
        'change': '新增空目录 entities。',
        'path': 'behavior_pack/entities',
        'destructive': False,
    }}, {{
        'id': 'preview-cleanup',
        'kind': 'remove_generated_artifact',
        'title': '清理生成物',
        'detail': '发现不应提交的生成物。',
        'change': '移入工程外隔离区。',
        'path': 'behavior_pack/.cache',
        'destructive': True,
        'impact': '可在本页撤销。',
    }}],
    'blockingPreview': [{{
        'codeName': 'ManifestJsonError',
        'title': 'manifest 缺 min_engine_version',
        'detail': '需人工确认版本。',
        'path': 'behavior_pack/manifest.json',
        'guidance': '根据目标游戏版本补充该字段。',
    }}],
    'blockingPreviewTruncated': False,
}}
page.setProperty('backend', backend)
window = QQuickWindow()
window.resize(1180, 840)
page.setParentItem(window.contentItem())
page.setWidth(1180)
page.setHeight(840)
window.show()
backend.stateChanged.emit()
app.processEvents()

def find_quick_item(parent, name):
    if parent.objectName() == name:
        return parent
    for child in parent.childItems():
        found = find_quick_item(child, name)
        if found is not None:
            return found
    return None

for name in (
    'blockingRepairProjectCard',
    'blockingRepairInspectButton',
    'blockingRepairSummaryCard',
    'blockingRepairItemsCard',
    'blockingRepairRemainingCard',
    'blockingRepairConfirmDialog',
):
    assert page.findChild(QObject, name) is not None, name

repair_button = find_quick_item(page, 'blockingRepairApplyButton_preview-repair')
cleanup_button = find_quick_item(page, 'blockingRepairApplyButton_preview-cleanup')
repair_badge = find_quick_item(page, 'blockingRepairActionBadge_preview-repair')
cleanup_badge = find_quick_item(page, 'blockingRepairActionBadge_preview-cleanup')
guidance = find_quick_item(page, 'blockingRepairGuidance_0')
for name, item in (
    ('blockingRepairApplyButton_preview-repair', repair_button),
    ('blockingRepairApplyButton_preview-cleanup', cleanup_button),
    ('blockingRepairActionBadge_preview-repair', repair_badge),
    ('blockingRepairActionBadge_preview-cleanup', cleanup_badge),
    ('blockingRepairGuidance_0', guidance),
):
    assert item is not None, name
assert repair_button.property('text') == '修复'
assert cleanup_button.property('text') == '隔离清理'
assert repair_badge.property('text') == '可修复'
assert cleanup_badge.property('text') == '隔离清理'
assert guidance.property('visible') is True
assert guidance.property('text') == '处理建议：根据目标游戏版本补充该字段。'

dialog = page.findChild(QObject, 'blockingRepairConfirmDialog')
expression = QQmlExpression(
    engine.rootContext(), page,
    "confirmRepair({{id: 'preview-cleanup', title: '清理生成物', "
    "change: '移入工程外隔离区。', impact: '可在本页撤销。', destructive: true}})"
)
expression.evaluate()
assert not expression.hasError(), expression.error().toString()
app.processEvents()
assert dialog.property('repairDestructive') is True
assert dialog.property('title') == '确认隔离清理'
assert dialog.property('confirmText') == '隔离清理'
assert dialog.property('repairImpact') == '可在本页撤销。'
assert '工程外隔离区' in dialog.property('message')
assert '可在本页撤销' in dialog.property('message')
assert QMetaObject.invokeMethod(dialog, 'reject')

image = window.grabWindow()
assert not image.isNull()
assert image.width() == 1180 and image.height() == 840
window.close()
print('blocking repair page ok')
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
    assert "blocking repair page ok" in result.stdout
