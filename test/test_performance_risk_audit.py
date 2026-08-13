# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""网易周报驱动的 Python UI 性能风险分析测试。"""

from __future__ import annotations

from pathlib import Path

from src.pack_scanner import scan
from src.performance_risk_audit import (
    analyze_python_source,
    match_report_to_risks,
    normalize_report_record,
)


def test_normalizes_fields_from_real_netease_weekly_report_shape() -> None:
    record = normalize_report_record(
        {
            "组件ID": "4687438332819910536",
            "组件名称": "破译大红行动3.0 完全版",
            "本周卡顿次数": 1586,
            "平均卡顿时长(秒)": 0.601,
            "模块名称": "MarketMod.client.ui.marketScreen",
            "函数名称": "Update",
        }
    )

    assert record.jank_count == 1586
    assert record.average_jank_seconds == 0.601
    assert record.average_jank_ms == 601.0
    assert record.module_name == "MarketMod.client.ui.marketScreen"
    assert record.function_name == "Update"


def test_flags_update_call_chain_with_looped_ui_engine_work() -> None:
    source = """
class MarketScreen(object):
    def Update(self):
        self._UpdateVirtualItems()

    def _UpdateVirtualItems(self):
        for path in self.paths:
            self.GetBaseUIControl(path).SetVisible(True)
            self.GetBaseUIControl(path).asItemRenderer().SetUiItem('a', 0)
"""

    risks = analyze_python_source(source, "MarketMod/client/ui/marketScreen.py")

    assert len(risks) == 1
    risk = risks[0]
    assert risk.function_name == "Update"
    assert risk.severity == "warning"
    assert "GetBaseUIControl" in risk.detail
    assert "SetUiItem" in risk.detail
    assert "循环内重复操作" in risk.detail
    assert "真实玩法中确认" in risk.detail


def test_flags_event_callback_but_does_not_call_it_a_rejection_error() -> None:
    source = """
class Client(object):
    def AddPlayerCreatedClientEvent(self, args):
        for player in args['players']:
            self.Clone('/template', '/root', player)
"""

    risks = analyze_python_source(source, "Script/System/Client/ModItemsClient.py")

    assert len(risks) == 1
    assert risks[0].severity == "warning"
    assert risks[0].title == "Python UI 性能风险警告"


def test_flags_reported_player_created_callback_through_render_loader() -> None:
    source = """
class Client(object):
    def AddPlayerCreatedClientEvent(self, args):
        self._LoadPlayerRenderManagers(args['playerId'])

    def _LoadPlayerRenderManagers(self, player_id):
        self._EnsurePlayerRenderManager(player_id)

    def _EnsurePlayerRenderManager(self, player_id):
        self.manager.LoadForPlayer(player_id)
"""

    risks = analyze_python_source(source, "System/Client/ModItemsClient.py")

    assert len(risks) == 1
    assert "LoadForPlayer" in risks[0].detail


def test_marks_indirect_high_cost_call_as_looped_when_helper_runs_in_loop() -> None:
    source = """
class Screen(object):
    def Update(self):
        self._Refresh()

    def _Refresh(self):
        for path in self.paths:
            self._Fill(path)

    def _Fill(self, path):
        self.GetBaseUIControl(path).asItemRenderer().SetUiItem('a', 0)
"""

    risks = analyze_python_source(source, "screen.py")

    assert "循环内重复操作：GetBaseUIControl, SetUiItem" in risks[0].detail


def test_marks_render_loader_inside_comprehension_as_looped() -> None:
    source = """
class Client(object):
    def AddPlayerCreatedClientEvent(self, args):
        self._Load(args['playerId'])

    def _Load(self, player_id):
        return {name: manager.LoadForPlayer(player_id) for name, manager in self.managers}
"""

    risks = analyze_python_source(source, "ModItemsClient.py")

    assert "循环内重复操作：LoadForPlayer" in risks[0].detail


def test_ignores_non_callback_helpers_until_reached_from_a_callback() -> None:
    source = """
class Helper(object):
    def _Render(self):
        for item in self.items:
            self.GetBaseUIControl(item).SetVisible(True)
"""

    assert analyze_python_source(source, "helper.py") == []


def test_matches_netease_module_and_function_to_source_risk() -> None:
    record = normalize_report_record(
        {
            "模块名称": "MarketMod.client.ui.marketScreen",
            "函数名称": "Update",
        }
    )
    risks = analyze_python_source(
        "class S:\n"
        "    def Update(self):\n"
        "        for path in self.paths:\n"
        "            self.GetBaseUIControl(path).SetVisible(1)\n",
        "behavior/MarketMod/client/ui/marketScreen.py",
    )

    assert match_report_to_risks(record, risks) == risks


def test_ignores_lightweight_update_without_loop_or_critical_operation() -> None:
    risks = analyze_python_source(
        "class S:\n    def Update(self):\n        self.label.SetText('tick')\n",
        "lightweight.py",
    )

    assert risks == []


def test_pack_scan_exposes_performance_warning_without_blocking(
    tmp_path: Path, monkeypatch
) -> None:
    pack = tmp_path / "behavior_demo"
    pack.mkdir()
    (pack / "manifest.json").write_text(
        '{"format_version":2,"header":{"name":"demo",'
        '"uuid":"00000000-0000-0000-0000-000000000001",'
        '"version":[1,0,0],"min_engine_version":[1,18,0]},'
        '"modules":[{"type":"data",'
        '"uuid":"00000000-0000-0000-0000-000000000002",'
        '"version":[1,0,0]}]}',
        encoding="utf-8",
    )
    (pack / "screen.py").write_text(
        "class Screen(object):\n"
        "    def Update(self):\n"
        "        for path in self.paths:\n"
        "            self.GetBaseUIControl(path).SetVisible(True)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("src.pack_scanner.run_legacy_pylint", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("src.pack_scanner.load_module_whitelist", lambda: set())

    issues = scan(str(tmp_path))
    performance = [issue for issue in issues if issue.code == 41]

    assert len(performance) == 1
    assert performance[0].severity == "warning"
    assert all(issue.severity != "error" for issue in performance)


def test_analyze_project_reads_python_files(tmp_path: Path) -> None:
    from src.performance_risk_audit import analyze_project

    path = tmp_path / "screen.py"
    path.write_text(
        "class Screen(object):\n"
        "    def Update(self):\n"
        "        for path in self.paths:\n"
        "            self.GetBaseUIControl(path).SetVisible(True)\n",
        encoding="utf-8",
    )

    risks = analyze_project(str(tmp_path))

    assert len(risks) == 1
    assert risks[0].path == str(path)
