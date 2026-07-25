# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""在独立进程中实例化 level.dat 编辑页面及其输入组件。"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import time

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import (  # noqa: E402
    QObject,
    QPoint,
    QPointF,
    Property,
    Qt,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtQml import (  # noqa: E402
    QQmlApplicationEngine,
    QQmlComponent,
    QQmlExpression,
)
from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtQuick import QQuickWindow  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from prismqml import register_types  # noqa: E402
from prismqml.python.core.engine import EngineManager  # noqa: E402
from src.level_dat_backend import LevelDatBackend  # noqa: E402
from src.level_dat_model import LevelDatTagModel  # noqa: E402


def find_visual_item(root, object_name: str):
    """按 objectName 遍历可视树，覆盖 ListView 动态委托。"""
    if root.objectName() == object_name:
        return root
    for child in root.childItems():
        found = find_visual_item(child, object_name)
        if found is not None:
            return found
    return None


def find_visual_items_with_prefix(root, prefix: str):
    """收集可视树中指定 objectName 前缀的项目。"""
    found = []
    if root.objectName().startswith(prefix):
        found.append(root)
    for child in root.childItems():
        found.extend(find_visual_items_with_prefix(child, prefix))
    return found


class Backend(QObject):
    busyChanged = Signal()
    loaded = Signal(dict)
    saved = Signal(str, str)
    extraDataSaved = Signal(str, str)
    failed = Signal(str)
    extraDataCopied = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.saved_changes = None
        self.db_saved_changes = None
        self.copied_text = None
        self.loaded_sources = []
        self._tag_model = LevelDatTagModel(self)
        self._nbt_tag_model = LevelDatTagModel(self)
        self._extra_data_tag_model = LevelDatTagModel(self)

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return False

    @Property(str, constant=True)
    def recentNbtPath(self) -> str:
        return "file:///test/level.dat"

    @Property("QVariantList", constant=True)
    def savedNbtPaths(self):
        return ["file:///test/level.dat", "file:///second/level.dat"]

    @Property(QObject, constant=True)
    def tagModel(self):
        return self._tag_model

    @Property(QObject, constant=True)
    def nbtTagModel(self):
        return self._nbt_tag_model

    @Property(QObject, constant=True)
    def extraDataTagModel(self):
        return self._extra_data_tag_model

    @Slot(str)
    def load(self, source: str) -> None:
        self.loaded_sources.append(source)

    @Slot(str, str, list)
    def save(self, _source: str, _fingerprint: str, changes: list) -> None:
        self.saved_changes = changes

    @Slot(str, str, str, list)
    def saveExtraData(
        self, _source: str, _sequence: str, _fingerprint: str, changes: list,
    ) -> None:
        self.db_saved_changes = changes

    @Slot(str)
    def copyExtraDataText(self, value: str) -> None:
        self.copied_text = value
        self.extraDataCopied.emit(f"已复制当前 DB 值（{len(value)} 字符）")


app = QApplication.instance() or QApplication([])
engine = QQmlApplicationEngine()
EngineManager.set_engine(engine)
register_types(engine)

page_path = REPO_ROOT / "qml" / "LevelDatPage.qml"
component = QQmlComponent(engine, QUrl.fromLocalFile(str(page_path)))
assert not component.isError(), [error.toString() for error in component.errors()]
page = component.create()
assert page is not None, [error.toString() for error in component.errors()]
backend = Backend()
page.setProperty("backend", backend)
page.setWidth(1100)
page.setHeight(800)
window = QQuickWindow()
window.resize(1100, 800)
page.setParentItem(window.contentItem())
window.show()
app.processEvents()
assert page.property("sourceUrl") == "file:///test/level.dat"
assert backend.loaded_sources == ["file:///test/level.dat"]
path_button = page.findChild(QObject, "levelDatBrowseButton")
assert path_button is not None
assert int(path_button.property("feature")) == 7
select_saved_path = QQmlExpression(engine.rootContext(), page, "selectSavedNbtPath(1)")
select_saved_path.evaluate()
app.processEvents()
assert not select_saved_path.hasError(), select_saved_path.error().toString()
assert page.property("sourceUrl") == "file:///second/level.dat"
assert backend.loaded_sources == [
    "file:///test/level.dat",
    "file:///second/level.dat",
]
rows = [
    {
        "path": "integer",
        "value": "1",
        "token": '[["c",0]]',
        "depth": 0,
        "isNetease": False,
        "editable": True,
        "container": False,
        "sourceKind": "levelDat",
        "editorKind": "integer",
        "minimum": -128,
        "maximum": 127,
        "decimals": 0,
        "stepSize": 1,
    },
    {
        "path": "long",
        "value": "9223372036854775807",
        "token": '[["c",1]]',
        "depth": 0,
        "isNetease": False,
        "editable": True,
        "container": False,
        "sourceKind": "levelDat",
        "editorKind": "long",
        "minimum": 0,
        "maximum": 0,
        "decimals": 0,
        "stepSize": 1,
    },
    {
        "path": "double",
        "value": "1.25",
        "token": '[["c",2]]',
        "depth": 0,
        "isNetease": False,
        "editable": True,
        "container": False,
        "sourceKind": "levelDat",
        "editorKind": "decimal",
        "minimum": -1e100,
        "maximum": 1e100,
        "decimals": 17,
        "stepSize": 0.1,
    },
    {
        "path": "FlatWorldLayers",
        "value": "FlatWorldLayers:" + "x" * 120,
        "token": '[["c",3]]',
        "depth": 0,
        "isNetease": True,
        "editable": True,
        "container": False,
        "sourceKind": "levelDat",
        "editorKind": "text",
        "minimum": 0,
        "maximum": 0,
        "decimals": 0,
        "stepSize": 0,
    },
    {
        "path": "abilities",
        "value": "16 个标签",
        "token": '[["c",4]]',
        "depth": 0,
        "isNetease": False,
        "editable": False,
        "container": True,
        "sourceKind": "levelDat",
        "editorKind": "none",
        "minimum": 0,
        "maximum": 0,
        "decimals": 0,
        "stepSize": 0,
    },
]
for index in range(5, 2000):
    rows.append(
        {
            "path": f"stress[{index}]",
            "value": str(index),
            "token": f'[["c",{index}]]',
            "depth": 0,
            "isNetease": False,
            "editable": True,
            "container": False,
            "sourceKind": "levelDat",
            "editorKind": "integer",
            "minimum": -2147483648,
            "maximum": 2147483647,
            "decimals": 0,
            "stepSize": 1,
        }
    )
extra_data_rows = [
    {
        "path": "db.scriptData.dn_mj.exitPoints",
        "value": '{\n  "exitPoints": 5,\n  "enabled": true\n}',
        "token": "extra:db.scriptData.dn_mj.exitPoints",
        "depth": 1,
        "isNetease": True,
        "editable": False,
        "container": False,
        "sourceKind": "extraData",
        "editorKind": "none",
        "minimum": 0,
        "maximum": 0,
        "decimals": 0,
        "stepSize": 0,
        "valueTruncated": True,
        "fullValueLength": 2_207_564,
        "fullValue": '{\n  "exitPoints": 5,\n  "enabled": true\n}',
        "liveValidationLimit": 8192,
    }
]
for index in range(1, 60):
    extra_data_rows.append(
        {
            "path": f"db.scriptData.stress[{index}]",
            "value": f'{{\n  "index": {index}\n}}',
            "token": f"extra:db.scriptData.stress[{index}]",
            "depth": 1,
            "isNetease": True,
            "editable": False,
            "container": False,
            "sourceKind": "extraData",
            "editorKind": "none",
            "minimum": 0,
            "maximum": 0,
            "decimals": 0,
            "stepSize": 0,
            "valueTruncated": False,
            "fullValueLength": len(f'{{\n  "index": {index}\n}}'),
            "fullValue": f'{{\n  "index": {index}\n}}',
            "liveValidationLimit": 8192,
        }
    )
all_rows = rows + extra_data_rows
summary = {
    "filePath": "level.dat",
    "levelName": "测试",
    "formatVersion": 10,
    "fileSize": 100,
    "declaredPayloadSize": 92,
    "rootTagCount": len(rows),
    "nbtNodeCount": len(rows),
    "visibleNodeCount": len(all_rows),
    "neteaseNodeCount": 1,
    "levelDbPath": "db",
    "levelDbFound": True,
    "extraDataFound": True,
    "extraDataStatus": "已加载当前有效 scriptData",
    "extraDataSequence": 30,
    "extraDataFingerprint": "dbabc",
    "extraDataSourceFile": "000003.log",
    "extraDataEntryCount": 5,
    "extraDataViewRowCount": 1,
    "extraDataTruncated": False,
    "matchMapCount": 2,
    "exitPointCount": 5,
    "switchBlockCount": 1,
    "gateConsoleCount": 4,
    "fingerprint": "abc",
}
backend.tagModel.replace_rows(all_rows)
backend.nbtTagModel.replace_rows(rows)
backend.extraDataTagModel.replace_rows(extra_data_rows)
backend.loaded.emit(summary)
app.processEvents()
assert page.findChild(QObject, "levelDatSaveDialog") is not None
assert page.findChild(QObject, "levelDatDiscardDialog") is not None
assert page.property("summary")["visibleNodeCount"] == len(all_rows)
visible_tag_rows = find_visual_items_with_prefix(page, "levelDatTagRow_")
assert 0 < len(visible_tag_rows) < len(rows)
assert all(row.property("sourceKind") == "levelDat" for row in visible_tag_rows)
nbt_list = find_visual_item(page, "levelDatNbtList")
extra_data_list = find_visual_item(page, "levelDatExtraDataList")
assert nbt_list is not None
assert extra_data_list is not None
assert nbt_list.property("count") == len(rows)
assert extra_data_list.property("count") == 0
nbt_view = nbt_list.property("listView")
assert nbt_view is not None
assert float(visible_tag_rows[0].property("width")) <= float(nbt_view.property("width")) + 1
tag_layout = find_visual_item(page, "levelDatTagLayout_0")
path_label = find_visual_item(page, "levelDatTagPath_0")
value_editor = find_visual_item(page, "levelDatValueEditor_0")
assert tag_layout is not None
assert path_label is not None
assert value_editor is not None
layout_width = float(tag_layout.property("width"))
path_right = float(path_label.property("x")) + float(path_label.property("width"))
editor_x = float(value_editor.property("x"))
editor_width = float(value_editor.property("width"))
path_center_y = float(path_label.property("y")) + float(path_label.property("height")) / 2
editor_center_y = (
    float(value_editor.property("y")) + float(value_editor.property("height")) / 2
)
assert editor_x >= path_right
assert editor_x + editor_width <= layout_width + 1
assert abs(editor_center_y - path_center_y) <= 1
assert abs(editor_width - min(420, layout_width * 0.38)) <= 1
multiline_row = find_visual_item(page, "levelDatTagRow_3")
multiline_editor_in_row = find_visual_item(page, "levelDatValueEditor_3")
assert multiline_row is not None
assert multiline_editor_in_row is not None
multiline_text_area = find_visual_item(
    multiline_editor_in_row, "levelDatMultilineTextEditor"
)
assert multiline_text_area is not None
multiline_text_area.setProperty("text", "\n".join(f"line {index}" for index in range(100)))
app.processEvents()
assert float(multiline_text_area.property("maximumContentY")) > 0
assert float(multiline_text_area.property("height")) > 32
assert float(multiline_editor_in_row.property("height")) > 32, {
    "editorHeight": multiline_editor_in_row.property("height"),
    "editorImplicitHeight": multiline_editor_in_row.property("implicitHeight"),
    "textAreaHeight": multiline_text_area.property("height"),
    "textAreaImplicitHeight": multiline_text_area.property("implicitHeight"),
}
assert float(multiline_row.property("height")) > 40
container_row = find_visual_item(page, "levelDatContainerRow_4")
container_path = find_visual_item(page, "levelDatContainerPath_4")
container_summary = find_visual_item(page, "levelDatContainerSummary_4")
assert container_row is not None
assert container_path is not None
assert container_summary is not None
assert container_row.property("visible") is True
assert float(container_row.property("height")) >= 32
assert float(container_summary.property("x")) > float(container_path.property("x"))
update_value = QQmlExpression(
    engine.rootContext(),
    page,
    "updateValue('[[\"c\",0]]', '1', '2', true)",
)
save_changes = QQmlExpression(engine.rootContext(), page, "saveChanges()")
update_value.evaluate()
save_changes.evaluate()
app.processEvents()
assert not update_value.hasError(), update_value.error().toString()
assert not save_changes.hasError(), save_changes.error().toString()
assert backend.saved_changes == [{"token": '[["c",0]]', "value": "2"}]
assert nbt_list.property("scrollable") is True
wheel_position = multiline_text_area.mapToScene(QPointF(
    float(multiline_text_area.property("width")) / 2, float(multiline_text_area.property("height")) / 2,
))
QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                 QPoint(round(wheel_position.x()), round(wheel_position.y())))
app.processEvents()
assert multiline_text_area.property("focused") is True
QTest.wheelEvent(window, QPoint(round(wheel_position.x()), round(wheel_position.y())),
                 QPoint(0, -120))
for _index in range(20):
    app.processEvents()
    time.sleep(0.01)
assert abs(float(nbt_list.property("contentY"))) <= 1
assert float(multiline_text_area.property("contentY")) > 0
clear_focus = QQmlExpression(engine.rootContext(), multiline_text_area, "clearFocus()")
clear_focus.evaluate()
assert not clear_focus.hasError(), clear_focus.error().toString()
assert multiline_text_area.property("focused") is False
QTest.wheelEvent(window, QPoint(round(wheel_position.x()), round(wheel_position.y())),
                 QPoint(0, -120))
wheel_deadline = time.monotonic() + 2
while float(nbt_list.property("contentY")) <= 0 and time.monotonic() < wheel_deadline:
    app.processEvents()
    time.sleep(0.01)
assert float(nbt_list.property("contentY")) > 0
data_selector = find_visual_item(page, "levelDatDataSelector")
assert data_selector is not None
data_selector.setProperty("currentIndex", 1)
for _index in range(3):
    app.processEvents()
visible_db_rows = find_visual_items_with_prefix(page, "levelDatExtraDataRow_")
assert 0 < len(visible_db_rows) < len(extra_data_rows)
assert nbt_list.property("count") == 0 and extra_data_list.property("count") == len(extra_data_rows)
assert float(extra_data_list.property("width")) > 0 and float(extra_data_list.property("height")) > 0
extra_data_view = extra_data_list.property("listView")
assert extra_data_view is not None
assert float(visible_db_rows[0].property("width")) <= (
    float(extra_data_view.property("width")) + 1
)
data_card = find_visual_item(page, "levelDatExtraDataCard_0")
data_path = find_visual_item(page, "levelDatExtraDataPath_0")
preview_status = find_visual_item(page, "levelDatExtraDataPreviewStatus_0")
db_editor = find_visual_item(page, "levelDatExtraDataEditor_0")
assert all(item is not None for item in (data_card, data_path, preview_status, db_editor))
assert db_editor.property("visible") is True and db_editor.property("readOnly") is False
assert db_editor.property("textFormat") == Qt.TextFormat.PlainText.value
assert '\n  "exitPoints": 5,' in db_editor.property("text")
assert "完整值" in preview_status.property("text")
path_position = data_path.mapToScene(QPointF(0, 0))
value_position = db_editor.mapToScene(QPointF(0, 0))
assert value_position.y() >= path_position.y() + float(data_path.property("height"))
assert float(db_editor.property("width")) > float(data_card.property("width")) * 0.9
valid_db_json = '{"exitPoints": 6, "enabled": true}'
edit_db_value = QQmlExpression(
    engine.rootContext(), page,
    "updateDbValue('extra:db.scriptData.dn_mj.exitPoints', "
    "'{\\n  \"exitPoints\": 5,\\n  \"enabled\": true\\n}', "
    "'{\"exitPoints\": 6, \"enabled\": true}', true)",
)
edit_db_value.evaluate()
app.processEvents()
assert not edit_db_value.hasError(), edit_db_value.error().toString()
assert page.property("dbChangeCount") == 1 and page.property("dbInvalidCount") == 0
assert db_editor.property("text") == valid_db_json
copy_full_value = find_visual_item(page, "levelDatCopyFullValue_0")
assert copy_full_value is not None and copy_full_value.property("visible") is True
copy_position = copy_full_value.mapToScene(
    QPointF(float(copy_full_value.property("width")) / 2,
            float(copy_full_value.property("height")) / 2)
)
QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                 QPoint(round(copy_position.x()), round(copy_position.y())))
app.processEvents()
assert backend.copied_text == valid_db_json
assert page.property("noticeMessage") == f"已复制当前 DB 值（{len(valid_db_json)} 字符）"
save_db_changes = QQmlExpression(engine.rootContext(), page, "saveDbChanges()")
save_db_changes.evaluate()
app.processEvents()
assert not save_db_changes.hasError(), save_db_changes.error().toString()
assert backend.db_saved_changes == [{
    "token": "extra:db.scriptData.dn_mj.exitPoints", "value": valid_db_json,
}]
editor_path = REPO_ROOT / "qml" / "LevelDatValueEditor.qml"
editor_component = QQmlComponent(engine, QUrl.fromLocalFile(str(editor_path)))
assert not editor_component.isError(), [
    error.toString() for error in editor_component.errors()
]
editor = editor_component.create()
assert editor is not None, [error.toString() for error in editor_component.errors()]
editor.setProperty("editorKind", "long")
editor.setProperty("valueText", "9223372036854775807")
app.processEvents()
assert editor.objectName() == "levelDatValueEditor"
maximum_long = QQmlExpression(
    engine.rootContext(), editor, "longIsInRange('9223372036854775807')"
)
overflow_long = QQmlExpression(
    engine.rootContext(), editor, "longIsInRange('9223372036854775808')"
)
utf8_length = QQmlExpression(engine.rootContext(), editor, "utf8ByteLength('网易')")
maximum_result = maximum_long.evaluate()[0]
overflow_result = overflow_long.evaluate()[0]
utf8_result = utf8_length.evaluate()[0]
assert maximum_result is True and not maximum_long.hasError()
assert overflow_result is False and not overflow_long.hasError()
assert utf8_result == 6 and not utf8_length.hasError()
editor.setProperty("editorKind", "text")
editor.setProperty("valueText", "FlatWorldLayers:" + "x" * 120)
app.processEvents()
multiline_editor = find_visual_item(editor, "levelDatMultilineTextEditor")
assert multiline_editor is not None
assert float(multiline_editor.property("height")) > 32
threaded_backend = LevelDatBackend()
threaded_backend._on_loaded((summary, all_rows, []))
threaded_backend.setFilter("不会命中的旧请求", [])
threaded_backend.setFilter("stress[139]", [])
deadline = time.monotonic() + 5
while threaded_backend.tagModel.count != 1 and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(0.01)
assert threaded_backend.tagModel.count == 1
assert threaded_backend.nbtTagModel.count == 1
assert threaded_backend.extraDataTagModel.count == 0
window.close()
