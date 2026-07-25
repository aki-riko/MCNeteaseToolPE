# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""在独立离屏窗口验证工程类型 Tag 的内容与几何位置。"""

from __future__ import annotations

import os
from pathlib import Path
import sys


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

page_path = Path(sys.argv[1]).resolve()
map_project = str(Path(sys.argv[2]).resolve())
addons_project = str(Path(sys.argv[3]).resolve())
archive_path = Path(sys.argv[4]).resolve()
sys.path.insert(0, str(page_path.parent.parent))

from PySide6.QtCore import QMetaObject, QObject, QUrl  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, QQmlExpression  # noqa: E402
from PySide6.QtQuick import QQuickItem, QQuickWindow  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from prismqml import register_types  # noqa: E402
from prismqml.python.core.engine import EngineManager  # noqa: E402

from src.backends import ProjectBackend  # noqa: E402
from src.settings_backend import ApplicationSettingsBackend  # noqa: E402


app = QApplication.instance() or QApplication([])
engine = QQmlApplicationEngine()
EngineManager.set_engine(engine)
register_types(engine)
component = QQmlComponent(engine, QUrl.fromLocalFile(str(page_path)))
assert not component.isError(), [error.toString() for error in component.errors()]
page = component.create()
assert isinstance(page, QQuickItem), [error.toString() for error in component.errors()]
window = QQuickWindow()
window.resize(1200, 800)
page.setParentItem(window.contentItem())
window.show()
revealed_archives: list[Path] = []
settings_backend = ApplicationSettingsBackend(
    settings_file=Path(map_project).parent / "project-page-probe-settings.json"
)
assert settings_backend.rememberProjectPath(addons_project) is True
assert settings_backend.rememberProjectPath(map_project) is True
backend = ProjectBackend(
    file_revealer=lambda path: revealed_archives.append(path) is None,
    settings_backend=settings_backend,
)
page.setProperty("backend", backend)
page.setWidth(1200)
page.setHeight(800)
app.processEvents()

title = page.findChild(QObject, "projectTitle")
tag = page.findChild(QObject, "projectTypeTag")
progress_text = page.findChild(QObject, "pipelineProgressText")
progress_bar = page.findChild(QObject, "pipelineProgress")
status_text = page.findChild(QObject, "pipelineStatusText")
run_button = page.findChild(QObject, "oneClickRunButton")
path_button = page.findChild(QObject, "projectPathBrowseButton")
assert title is not None
assert tag is not None
assert progress_text is not None
assert progress_bar is not None
assert status_text is not None
assert run_button is not None
assert path_button is not None
assert int(path_button.property("feature")) == 7
assert page.property("projectDir") == map_project
assert tag.property("visible") is True
assert tag.property("text") == "地图"
assert tag.property("_statusKey") == "info"
assert tag.parent() == title.parent()
title_right = float(title.property("x")) + float(title.property("width"))
tag_gap = float(tag.property("x")) - title_right
assert 0 < tag_gap <= 24

select_saved_path = QQmlExpression(
    engine.rootContext(), page, "selectSavedProjectPath(1)"
)
select_saved_path.evaluate()
app.processEvents()
assert not select_saved_path.hasError(), select_saved_path.error().toString()
assert page.property("projectDir") == addons_project
assert tag.property("text") == "Add-ons"
assert tag.property("_statusKey") == "success"

backend._set_state("audit", "第 2/4 步：Python 2.7 代码审核（1/347）", 51.234)
app.processEvents()
assert progress_text.property("text") == "51.23%"
assert abs(float(progress_bar.property("value")) - 51.234) < 0.001

page.setProperty("projectDir", "")
app.processEvents()
assert tag.property("visible") is False

page.setProperty("projectDir", addons_project)
app.processEvents()
backend._set_archive_path(str(archive_path))
status = f"全部完成：审核通过，ZIP 已输出到 {archive_path}"
backend._set_state("done", status, 100)
backend.finished.emit(True, 0, 2, [], status)
app.processEvents()
pipeline_link = page.findChild(QObject, "pipelineArchiveLink")
result_link = page.findChild(QObject, "resultArchiveLink")
assert pipeline_link is not None
assert result_link is not None
for link in (pipeline_link, result_link):
    assert link.property("visible") is True
    assert link.property("type") == 8
    assert link.property("text") == str(archive_path)
    assert QMetaObject.invokeMethod(link, "clicked")
app.processEvents()
assert revealed_archives == [archive_path, archive_path]
backend._set_archive_path("")
backend._set_busy(True)
long_status = (
    "第 2/4 步：Python 2.7 代码审核（335/347）："
    "behavior_dn_mj_zhubao/Script_NeteaseModousIY5rA/"
    + "System/Server/ModSetupServer/VeryLongDirectory/" * 8
    + "CurrentAuditFile.py"
)
backend._set_state("audit", long_status, 54.8)
app.processEvents()
button_parent = run_button.parent()
assert button_parent is not None
assert bool(run_button.property("loading")) is True
assert bool(run_button.property("clip")) is True
assert float(run_button.property("width")) <= float(button_parent.property("width")) + 0.5
button_loading_text = str(run_button.property("loadingText"))
assert button_loading_text != long_status
assert button_loading_text.endswith("…")
assert "\n" not in button_loading_text
assert int(status_text.property("lineCount")) == 1
assert bool(status_text.property("truncated")) is True
if len(sys.argv) > 5:
    assert window.grabWindow().save(sys.argv[5])
window.close()
print("project kind tag ok")
