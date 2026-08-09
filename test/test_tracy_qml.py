# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""一键 Tracy 卡片的无窗口 QML 回归测试。"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
PAGE = REPO_ROOT / "qml" / "PerformancePage.qml"


def test_performance_page_quick_capture_states_load_offscreen() -> None:
    script = f"""
import copy
import os
import sys
sys.path.insert(0, r'{REPO_ROOT}')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QObject, QUrl
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from prismqml import register_types
from prismqml.python.core.engine import EngineManager
from src.performance_backend import PerformanceBackend
from src.performance_monitor import ProcessDescriptor, ProcessSample

class Locator:
    def discover(self):
        return {{
            'root': r'C:\\MCStudio',
            'configured': True,
            'tools': {{
                'tracy': {{'available': True, 'path': r'C:\\MCStudio\\tracy\\tracy-profiler.exe'}},
                'airperf': {{'available': True, 'path': r'C:\\MCStudio\\airperf\\airperf.exe'}},
            }},
        }}

class Sampler:
    def list_candidates(self):
        return [ProcessDescriptor(42, 'Minecraft.Windows.exe')]
    def reset(self, _pid):
        pass
    def sample(self, pid):
        return ProcessSample(pid, 10.0, 500.0, 550.0)

def tracy_probe():
    return {{
        'address': '127.0.0.1', 'port': 8086,
        'binAvailable': True, 'binDir': 'tracy_bin',
        'reachable': False, 'tools': {{}},
    }}

app = QApplication.instance() or QApplication([])
engine = QQmlApplicationEngine()
EngineManager.set_engine(engine)
register_types(engine)
backend = PerformanceBackend(
    locator=Locator(), sampler=Sampler(), launcher=lambda _path: True,
    tracy_probe=tracy_probe,
)
component = QQmlComponent(engine, QUrl.fromLocalFile(r'{PAGE}'))
assert not component.isError(), [error.toString() for error in component.errors()]
page = component.create()
assert page is not None, [error.toString() for error in component.errors()]
window = QQuickWindow()
page.setParentItem(window.contentItem())
page.setProperty('backend', backend)
window.setWidth(1100)
window.setHeight(800)
page.setWidth(1100)
page.setHeight(800)
window.show()
app.processEvents()
for name in (
    'performanceProcessCard', 'performanceThresholdCard',
    'performanceProcessSelector', 'performanceCpuChart', 'performanceMemoryChart',
    'performanceMainScrollArea', 'performanceDetailsButton',
    'performanceDetailsDrawer', 'performanceDetailsPanel',
    'performanceDetailsScrollArea', 'performanceHotspotList',
    'performanceReportMetricsList',
    'tracyAnalysisCard', 'performanceUnifiedMonitorButton',
    'performanceAutoMonitoringButton', 'tracyGuideText',
    'tracyReportSection', 'tracyReportTitle', 'tracyReportConclusion',
    'tracyHotspotScopeTitle', 'tracySelectedFrameRateTag',
    'tracyOpenDetailsButton',
):
    assert page.findChild(QObject, name) is not None, name
assert page.findChild(QObject, 'tracyDurationSpinBox') is None
assert page.findChild(QObject, 'tracyFilterInput') is None
assert page.findChild(QObject, 'performanceOfficialToolsCard') is None
assert page.findChild(QObject, 'performanceMonitorButton') is None

cpu_chart = page.findChild(QObject, 'performanceCpuChart')
memory_chart = page.findChild(QObject, 'performanceMemoryChart')
assert memory_chart.property('y') > cpu_chart.property('y'), (
    cpu_chart.property('y'), memory_chart.property('y'), page.property('width')
)
page.setWidth(1600)
window.setWidth(1600)
app.processEvents()
assert memory_chart.property('y') > cpu_chart.property('y'), (
    cpu_chart.property('y'), memory_chart.property('y'), page.property('width')
)

tracy_card = page.findChild(QObject, 'tracyAnalysisCard')
details_panel = page.findChild(QObject, 'performanceDetailsPanel')
details_button = page.findChild(QObject, 'performanceDetailsButton')
details_drawer = page.findChild(QObject, 'performanceDetailsDrawer')
main_scroll = page.findChild(QObject, 'performanceMainScrollArea')
details_scroll = page.findChild(QObject, 'performanceDetailsScrollArea')
hotspot_list = page.findChild(QObject, 'performanceHotspotList')
report_metrics_list = page.findChild(QObject, 'performanceReportMetricsList')
capture_button = page.findChild(QObject, 'performanceUnifiedMonitorButton')
auto_button = page.findChild(QObject, 'performanceAutoMonitoringButton')
guide_text = page.findChild(QObject, 'tracyGuideText')
report_section = page.findChild(QObject, 'tracyReportSection')
report_title = page.findChild(QObject, 'tracyReportTitle')
report_conclusion = page.findChild(QObject, 'tracyReportConclusion')
assert capture_button.property('text') == '等待 ModPC 启动…'
assert capture_button.property('enabled') is False
assert capture_button.property('level') == 0
assert auto_button.property('text') == '自动监测：开'
assert auto_button.property('level') == 1
assert '已自动识别 Minecraft.Windows.exe' in guide_text.property('text')
ready_state = {{
    'statusChecked': True, 'binAvailable': True, 'reachable': True,
    'busy': False, 'captureSeconds': 10, 'probeIntervalMs': 1500,
    'continuousActive': False, 'stopRequested': False, 'windowsCompleted': 0,
    'captures': [], 'selectedCaptureId': '', 'baselineCaptureId': '',
    'comparisonCaptureId': '', 'hotspots': [], 'diff': {{}},
}}
tracy_card.setProperty('state', ready_state)
details_panel.setProperty('state', ready_state)
QTest.qWait(100)
assert capture_button.property('text') == '开始持续监测'
assert capture_button.property('enabled') is True
assert capture_button.property('level') == 1
assert '已自动识别 Minecraft.Windows.exe' in guide_text.property('text')
baseline = {{
    'id': 'capture-1', 'text': '首次检测', 'label': 'before',
    'seconds': 10, 'averageFps': 60.0, 'matchedFunctions': 1,
}}
ready_state['captures'] = [baseline]
ready_state['selectedCaptureId'] = 'capture-1'
ready_state['baselineCaptureId'] = 'capture-1'
ready_state['hotspots'] = [{{
    'name': 'update @ Demo', 'selfMs': 20.0,
    'totalMs': 24.0, 'calls': 10,
}}]
ready_state['report'] = {{
    'kind': 'capture', 'title': '本次检测总结',
    'verdict': '检测完成', 'tone': 'info',
    'conclusion': '主要热点是 update @ Demo。',
    'metrics': [
        {{'label': '采样时长', 'value': '10 秒'}},
        {{'label': '函数', 'value': '1'}},
        {{'label': 'FrameMark 频率', 'value': '60.0 次/秒'}},
    ],
    'highlights': [
        {{'kind': 'hotspot', 'name': 'update @ Demo', 'detail': '自身 20.000 ms · 调用 10 次'}},
        {{'kind': 'hotspot', 'name': 'render @ Demo', 'detail': '自身 12.000 ms · 调用 10 次'}},
        {{'kind': 'hotspot', 'name': 'tick @ Demo', 'detail': '自身 8.000 ms · 调用 10 次'}},
    ],
    'recommendations': [
        '优先检查 update @ Demo。',
        '确认 render @ Demo 是否重复执行。',
        '对比优化前后的同场景窗口。',
    ],
}}
tracy_card.setProperty('state', ready_state)
details_panel.setProperty('state', ready_state)
QTest.qWait(100)
assert capture_button.property('text') == '开始持续监测'
assert report_section.property('visible') is True
assert report_title.property('text') == '本次检测总结'
assert report_conclusion.property('text') == '主要热点是 update @ Demo。'
assert page.findChild(QObject, 'tracyHotspotScopeTitle').property('text') == (
    '当前选中窗口最耗时函数（10 秒）'
)
assert page.findChild(QObject, 'tracySelectedFrameRateTag').property('text') == (
    '60.0 FrameMark/s'
)
assert hotspot_list.property('count') == 1, hotspot_list.property('count')
assert hotspot_list.property('bounceEnabled') is False
assert report_metrics_list.property('count') == 3
assert report_metrics_list.property('bounceEnabled') is False

page.setHeight(420)
window.setHeight(420)
QTest.qWait(100)
main_flickable = main_scroll.property('flickableItem')
main_max_y = main_flickable.property('contentHeight') - main_flickable.property('height')
assert main_max_y > 0, (main_flickable.property('contentHeight'), main_flickable.property('height'))
main_scroll.smoothScrollTo(main_max_y)
QTest.qWait(600)
position_before_refresh = main_flickable.property('contentY')
refreshed_state = copy.deepcopy(ready_state)
refreshed_state['report']['metrics'][2]['value'] = '60.1 次/秒'
refreshed_state['report']['highlights'][0]['detail'] = '自身 20.100 ms · 调用 10 次'
refreshed_state['hotspots'][0]['selfMs'] = 20.1
tracy_card.setProperty('state', refreshed_state)
details_panel.setProperty('state', refreshed_state)
QTest.qWait(120)
position_after_refresh = main_flickable.property('contentY')
assert abs(position_after_refresh - position_before_refresh) < 2.0, (
    position_before_refresh, position_after_refresh,
    main_flickable.property('contentHeight')
)

details_button.clicked.emit()
QTest.qWait(350)
assert details_drawer.property('opened') is True, details_drawer.property('opened')
details_flickable = details_scroll.property('flickableItem')
details_max_y = details_flickable.property('contentHeight') - details_flickable.property('height')
assert details_max_y > 0, (
    details_flickable.property('contentHeight'), details_flickable.property('height')
)
details_scroll.smoothScrollTo(details_max_y)
QTest.qWait(600)
details_position_before = details_flickable.property('contentY')
drawer_refresh = copy.deepcopy(refreshed_state)
drawer_refresh['report']['metrics'][0]['value'] = '11 秒'
drawer_refresh['report']['recommendations'][0] = '优先检查 update @ Demo 的重复调用。'
drawer_refresh['hotspots'][0]['totalMs'] = 24.1
details_panel.setProperty('state', drawer_refresh)
QTest.qWait(120)
details_position_after = details_flickable.property('contentY')
assert abs(details_position_after - details_position_before) < 2.0, (
    details_position_before, details_position_after,
    details_flickable.property('contentHeight')
)
page.findChild(QObject, 'performanceDetailsCloseButton').clicked.emit()
QTest.qWait(350)
assert details_drawer.property('opened') is False, details_drawer.property('opened')

screen_area = window.screen().availableGeometry()
window.setX(screen_area.x())
window.setWidth(300)
page.setWidth(300)
QTest.qWait(100)
if screen_area.width() - window.width() >= details_drawer.property('drawerWidth'):
    details_button.clicked.emit()
    QTest.qWait(350)
    assert details_drawer.property('mode') == 1, details_drawer.property('mode')
    assert details_drawer.property('opened') is True
    page.findChild(QObject, 'performanceDetailsCloseButton').clicked.emit()
    QTest.qWait(350)
    assert details_drawer.property('opened') is False

ready_state['busy'] = True
ready_state['continuousActive'] = True
ready_state['windowsCompleted'] = 2
tracy_card.setProperty('state', ready_state)
app.processEvents()
assert capture_button.property('text') == '停止并生成报告'
assert capture_button.property('enabled') is True
assert capture_button.property('level') == 2
assert '已完成 2 个窗口' in guide_text.property('text')
ready_state['stopRequested'] = True
tracy_card.setProperty('state', ready_state)
app.processEvents()
assert capture_button.property('text') == '正在停止并生成报告…'
assert capture_button.property('enabled') is False
assert capture_button.property('level') == 0
backend.setAutoMonitoring(False)
app.processEvents()
assert auto_button.property('text') == '自动监测：关'
assert auto_button.property('level') == 0
backend.startMonitoring()
app.processEvents()
assert page.findChild(QObject, 'performanceCpuValue').property('text') == '10.0%'
backend.stopMonitoring()
print('performance page quick capture ok')
"""
    environment = dict(os.environ)
    environment["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    output = result.stdout + result.stderr
    assert "Detected anchors on an item that is managed by a layout" not in output
