# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""网易周报驱动的 Python UI 性能风险分析测试。"""

from __future__ import annotations

from src.performance_risk_audit import (
    PerformanceAnalysis,
    analyze_python_source,
    analyze_python_source_result,
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
    assert "外部调用边界" in risks[0].detail
    assert "未跨文件展开" in risks[0].detail


def test_flags_real_reported_on_ui_init_finished_callback() -> None:
    """网易周报中的 voiceprintClientSystem.OnUiInitFinished 不能漏报。"""
    source = """
class VoiceprintClient(object):
    def OnUiInitFinished(self, args):
        self._create_hud()

    def _create_hud(self):
        clientApi.RegisterUI('voiceprint', 'hud', 'module.Screen', 'screen')
        self._hud_node = clientApi.CreateUI('voiceprint', 'hud', {'isHud': 1})
"""

    risks = analyze_python_source(
        source,
        "voiceprintScripts/modClient/clientSystem/voiceprintClientSystem.py",
    )
    report = normalize_report_record(
        {
            "组件ID": "4687438332819910536",
            "本周卡顿次数": 1027,
            "平均卡顿时长(秒)": 2.052,
            "模块名称": (
                "voiceprintScripts.modClient.clientSystem.voiceprintClientSystem"
            ),
            "函数名称": "OnUiInitFinished",
        }
    )

    assert len(risks) == 1
    assert risks[0].function_name == "OnUiInitFinished"
    assert "CreateUI" in risks[0].detail
    assert match_report_to_risks(report, risks) == risks


def test_flags_real_reported_notice_callback() -> None:
    """网易周报中的 UiClient.py.Notice 不能因无 Event 后缀而漏报。"""
    source = """
class UiClient(object):
    def Notice(self, attr_name, value, instance):
        self._refresh_property(attr_name, value)

    def _refresh_property(self, attr_name, value):
        self.GetBaseUIControl('/notice').SetText(str(value))
        self.GetBaseUIControl('/notice').SetVisible(True)
        self.GetBaseUIControl('/notice').SetPosition((0, 0))
"""

    risks = analyze_python_source(
        source,
        "behavior/Script_NeteaseModousIYC/System/Client/UtilClient.py",
    )
    report = normalize_report_record(
        {
            "组件ID": "4683781490213153055",
            "本周卡顿次数": 1024,
            "平均卡顿时长(秒)": 0.874,
            "模块名称": "Script_NeteaseModousIYC/System/Client/UtilClient.py",
            "函数名称": "Notice",
        }
    )

    assert len(risks) == 1
    assert risks[0].function_name == "Notice"
    assert "SetText" in risks[0].detail
    assert match_report_to_risks(report, risks) == risks


def test_does_not_treat_notice_prefixed_helpers_as_reported_notice_callback() -> None:
    source = """
class Server(object):
    def NoticePlayerOpenWarehouse(self, player_id):
        for path in self.paths:
            self.GetBaseUIControl(path).SetVisible(True)
"""

    assert analyze_python_source(source, "WarehouseServer.py") == []


def test_tracks_public_same_class_helpers_without_following_other_objects() -> None:
    source = """
class Client(object):
    def OnUiInitFinished(self, args):
        self.CreateHud()
        self.manager.CreateHud()

    def CreateHud(self):
        clientApi.CreateUI('demo', 'hud', {'isHud': 1})
"""

    risks = analyze_python_source(source, "clientSystem.py")

    assert len(risks) == 1
    assert "CreateUI" in risks[0].detail


def test_reports_static_analysis_parse_failure_instead_of_silently_skipping() -> None:
    analysis = analyze_python_source_result("def broken(:\n", "broken.py")

    assert isinstance(analysis, PerformanceAnalysis)
    assert analysis.risks == ()
    assert "性能风险分析无法解析 Python 源码" in analysis.diagnostic


def test_python2_fallback_accepts_file_without_trailing_newline() -> None:
    analysis = analyze_python_source_result(
        "class UiClient(object):\n"
        "    def Notice(self, name, value, instance):\n"
        "        print value\n"
        "        self.a.SetText(str(value))\n"
        "        self.b.SetText(str(value))\n"
        "        self.c.SetText(str(value))",
        "UiClient.py",
    )

    assert analysis.diagnostic == ""
    assert len(analysis.risks) == 1


def test_python2_fallback_accepts_long_integer_literals() -> None:
    analysis = analyze_python_source_result(
        "LONG_IDS = {15932062081653170275L}\n"
        "class UiClient(object):\n"
        "    def Notice(self, name, value, instance):\n"
        "        self.a.SetText(str(value))\n"
        "        self.b.SetText(str(value))\n"
        "        self.c.SetText(str(value))\n",
        "UiClient.py",
    )

    assert analysis.diagnostic == ""
    assert len(analysis.risks) == 1


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


def test_follows_deterministic_same_class_chain_without_arbitrary_depth_cutoff() -> None:
    source = """
class Screen(object):
    def Update(self):
        self._first()

    def _first(self):
        self._second()

    def _second(self):
        self._third()

    def _third(self):
        self._fourth()

    def _fourth(self):
        self.GetBaseUIControl('/item').SetUiItem('a', 0)
"""

    risks = analyze_python_source(source, "deep_screen.py")

    assert len(risks) == 1
    assert "SetUiItem" in risks[0].detail


def test_ignores_uninvoked_nested_function_body() -> None:
    source = """
class Screen(object):
    def Update(self):
        def expensive_but_unused():
            for path in self.paths:
                self.GetBaseUIControl(path).SetUiItem('a', 0)
        self.label.SetText('tick')
"""

    assert analyze_python_source(source, "nested.py") == []


def test_ignores_uninstantiated_nested_class_body() -> None:
    source = """
class Screen(object):
    def Update(self):
        class Deferred(object):
            def expensive(self):
                for path in self.paths:
                    self.GetBaseUIControl(path).SetUiItem('a', 0)
        self.label.SetText('tick')
"""

    assert analyze_python_source(source, "nested_class.py") == []


def test_counts_repeated_direct_engine_calls_not_only_unique_call_names() -> None:
    source = """
class UiClient(object):
    def Notice(self, attr_name, value, instance):
        self.title.SetText(str(value))
        self.subtitle.SetText(str(value))
        self.detail.SetText(str(value))
"""

    risks = analyze_python_source(source, "UiClient.py")

    assert len(risks) == 1
    assert risks[0].severity == "warning"


def test_counts_repeated_same_class_helper_invocations() -> None:
    source = """
class UiClient(object):
    def Notice(self, attr_name, value, instance):
        self._refresh(value)
        self._refresh(value)
        self._refresh(value)

    def _refresh(self, value):
        self.title.SetText(str(value))
"""

    risks = analyze_python_source(source, "UiClient.py")

    assert len(risks) == 1
    assert risks[0].severity == "warning"


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


def test_matches_real_report_module_path_with_py_suffix() -> None:
    record = normalize_report_record(
        {
            "模块名称": "Script_NeteaseModousIYC/System/Client/UtilClient.py",
            "函数名称": "Notice",
        }
    )
    risks = analyze_python_source(
        "class UiClient:\n"
        "    def Notice(self, name, value, instance):\n"
        "        self.a.SetText(str(value))\n"
        "        self.b.SetText(str(value))\n"
        "        self.c.SetText(str(value))\n",
        "behavior/Script_NeteaseModousIYC/System/Client/UtilClient.py",
    )

    assert match_report_to_risks(record, risks) == risks


def test_matches_report_with_only_python_filename() -> None:
    record = normalize_report_record(
        {"模块名称": "UiClient.py", "函数名称": "Notice"}
    )
    risks = analyze_python_source(
        "class UiClient:\n"
        "    def Notice(self, name, value, instance):\n"
        "        self.a.SetText(str(value))\n"
        "        self.b.SetText(str(value))\n"
        "        self.c.SetText(str(value))\n",
        "behavior/UiClient.py",
    )

    assert match_report_to_risks(record, risks) == risks


def test_ignores_lightweight_update_without_loop_or_critical_operation() -> None:
    risks = analyze_python_source(
        "class S:\n    def Update(self):\n        self.label.SetText('tick')\n",
        "lightweight.py",
    )

    assert risks == []
