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
from PySide6.QtCore import QObject, QUrl
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
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
    'message': '已发现 1 项可自动优化项；执行后会自动复审。',
    'repairableCount': 1,
    'auditErrorCount': 1,
    'auditWarningCount': 0,
    'items': [{{
        'id': 'preview-repair',
        'kind': 'create_required_directory',
        'title': '补全行为包必需目录',
        'detail': '缺少 entities。',
        'change': '新增空目录 entities。',
        'path': 'behavior_pack/entities',
    }}],
    'blockingPreview': [{{
        'codeName': 'ManifestJsonError',
        'title': 'manifest 缺 min_engine_version',
        'detail': '需人工确认版本。',
        'path': 'behavior_pack/manifest.json',
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

for name in (
    'blockingRepairProjectCard',
    'blockingRepairInspectButton',
    'blockingRepairSummaryCard',
    'blockingRepairItemsCard',
    'blockingRepairRemainingCard',
    'blockingRepairConfirmDialog',
):
    assert page.findChild(QObject, name) is not None, name
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
