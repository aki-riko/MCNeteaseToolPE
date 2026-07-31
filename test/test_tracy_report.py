# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tracy 自动总结报告回归测试。"""

from __future__ import annotations

from src.tracy_report import build_capture_report, build_comparison_report


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
    assert len(report["highlights"]) == 2
    assert "调用 200 次" in str(report["highlights"][0]["detail"])
    recommendations = "\n".join(report["recommendations"])
    assert "平均每帧调用 2.00 次" in recommendations
    assert "下游调用链" in recommendations


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
