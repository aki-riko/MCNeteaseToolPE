# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tracy 自动总结报告回归测试。"""

from __future__ import annotations

from src.tracy_report import (
    add_capture_to_session,
    build_capture_report,
    build_comparison_report,
    build_session_report,
    new_session_summary,
)


def _capture() -> dict[str, object]:
    return {
        "seconds": 10,
        "frames": 100,
        "averageFps": 10.0,
        "matchedFunctions": 2,
        "totalSelfMs": 30.0,
        "capturedAt": "2026-08-01 12:00:00",
        "top": [
            {
                "name": "hot @ Demo.Server.Main",
                "selfMs": 20.0,
                "totalMs": 40.0,
                "calls": 200,
            },
            {
                "name": "warm @ Demo.Server.Main",
                "selfMs": 10.0,
                "totalMs": 12.0,
                "calls": 20,
            },
        ],
    }


def test_capture_report_summarizes_top_hotspots_and_factual_actions() -> None:
    report = build_capture_report(_capture())

    assert report["kind"] == "capture"
    assert report["title"] == "本次检测总结"
    assert report["verdict"] == "检测完成"
    assert "hot @ Demo.Server.Main" in str(report["conclusion"])
    assert "66.7%" in str(report["conclusion"])
    assert {item["label"]: item["value"] for item in report["metrics"]}[
        "检测时间"
    ] == "2026-08-01 12:00:00"
    metrics = {item["label"]: item["value"] for item in report["metrics"]}
    assert metrics["Tracy FrameMark 数"] == "100"
    assert metrics["Tracy FrameMark 频率"] == "10.0 次/秒"
    assert len(report["highlights"]) == 2
    assert "调用 200 次" in str(report["highlights"][0]["detail"])
    recommendations = "\n".join(report["recommendations"])
    assert "平均每个 FrameMark 调用 2.00 次" in recommendations
    assert "下游调用链" in recommendations


def test_capture_report_separates_verified_wait_zone_from_actionable_hotspots() -> None:
    capture = _capture()
    wait_row = {
        "name": "sleep @ time",
        "selfMs": 40_392.973,
        "totalMs": 40_392.973,
        "calls": 358,
    }
    capture["rows"] = [wait_row, *capture["top"]]
    capture["top"] = [wait_row, *capture["top"]]
    capture["matchedFunctions"] = 3
    capture["totalSelfMs"] = 40_422.973

    report = build_capture_report(capture)
    metrics = {item["label"]: item["value"] for item in report["metrics"]}

    assert "sleep @ time" not in str(report["conclusion"])
    assert "hot @ Demo.Server.Main" in str(report["conclusion"])
    assert all(item["name"] != "sleep @ time" for item in report["highlights"])
    assert metrics["等待函数自身耗时"] == "40392.973 ms"
    assert any("等待函数不作为优化热点" in item for item in report["recommendations"])


def test_capture_report_explains_empty_capture() -> None:
    report = build_capture_report(
        {"seconds": 10, "frames": 0, "matchedFunctions": 0, "top": []}
    )

    assert report["verdict"] == "未发现热点"
    assert report["highlights"] == []
    assert "触发了目标玩法" in str(report["conclusion"])


def test_comparison_report_prioritizes_regressions_then_improvements() -> None:
    diff = {
        "summary": {
            "baseSelfMs": 30.0,
            "newSelfMs": 24.0,
            "deltaMs": -6.0,
            "percent": -20.0,
        },
        "regressed": [
            {"name": "warm", "baseMs": 5.0, "newMs": 8.0, "deltaMs": 3.0}
        ],
        "improved": [
            {"name": "hot", "baseMs": 20.0, "newMs": 11.0, "deltaMs": -9.0}
        ],
        "added": [],
        "removed": [],
    }

    report = build_comparison_report(_capture(), diff)

    assert report["kind"] == "comparison"
    assert report["verdict"] == "已有改善"
    assert report["tone"] == "success"
    assert "下降 6.000 ms（20.00%）" in str(report["conclusion"])
    assert [item["kind"] for item in report["highlights"]] == [
        "regressed",
        "improved",
    ]
    assert "优先检查回退最大的 warm" in report["recommendations"][0]


def test_comparison_report_marks_total_regression() -> None:
    report = build_comparison_report(
        _capture(),
        {
            "summary": {
                "baseSelfMs": 20.0,
                "newSelfMs": 25.0,
                "deltaMs": 5.0,
                "percent": 25.0,
            }
        },
    )

    assert report["verdict"] == "需要关注"
    assert report["tone"] == "warning"
    assert "上升 5.000 ms（25.00%）" in str(report["conclusion"])


def test_continuous_session_aggregates_windows_without_retaining_window_list() -> None:
    session = new_session_summary()
    first = _capture()
    first["rows"] = list(first["top"])
    second = _capture()
    second["rows"] = [
        {"name": "hot @ Demo.Server.Main", "selfMs": 5.0, "totalMs": 8.0, "calls": 4}
    ]

    add_capture_to_session(session, first)
    add_capture_to_session(session, second)
    report = build_session_report(session, active=False)

    assert session["windows"] == 2
    assert session["seconds"] == 20
    assert "captures" not in session
    assert len(session["functions"]) == 2
    assert report["kind"] == "session"
    assert report["verdict"] == "监测完成"
    assert "已完成 2 个连续窗口" in str(report["conclusion"])
    assert "自身 25.000 ms" in str(report["highlights"][0]["detail"])


def test_stopped_session_without_complete_window_explains_missing_hotspots() -> None:
    report = build_session_report(new_session_summary(), active=False)

    assert report["verdict"] == "监测完成"
    assert "首个完整窗口结束前停止" in str(report["conclusion"])
