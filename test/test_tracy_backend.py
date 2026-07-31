# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""性能页 Tracy 后台状态机回归测试。"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from src.tracy_backend import TracyPerformanceController


class _FakeTaskHandle(QObject):
    succeeded = Signal(object)
    failed = Signal(object)


def _probe(*, reachable: bool = True) -> dict[str, object]:
    return {
        "address": "127.0.0.1",
        "port": 8086,
        "reachable": reachable,
        "binAvailable": True,
        "binDir": "tracy_bin",
        "tools": {},
    }


def _capture_payload(self_ms: float, *, seconds: int = 10) -> dict[str, object]:
    row = {
        "name": "update @ Demo.Server.Main",
        "function": "update",
        "sourceFile": "Demo.Server.Main",
        "sourceLine": "10",
        "selfMs": self_ms,
        "totalMs": self_ms + 2.0,
        "calls": 10,
        "selfPerCallMs": self_ms / 10,
        "selfPerFrameMs": self_ms / 600,
    }
    return {
        "seconds": seconds,
        "address": "127.0.0.1",
        "port": 8086,
        "frames": 600,
        "zones": 1000,
        "averageFps": 60.0,
        "filter": "Demo",
        "uniqueFunctions": 1,
        "matchedFunctions": 1,
        "totalSelfMs": self_ms,
        "totalTotalMs": self_ms + 2.0,
        "rows": [row],
        "top": [row],
    }


def _controller(
    results: list[tuple[bool, str]],
    *,
    reachable: bool = True,
) -> TracyPerformanceController:
    return TracyPerformanceController(
        lambda: None,
        lambda success, message: results.append((success, message)),
        probe=lambda: _probe(reachable=reachable),
        capture_runner=lambda _seconds, _filter, _top: {},
    )


def test_controller_captures_baseline_and_builds_diff(monkeypatch) -> None:
    handles = [_FakeTaskHandle(), _FakeTaskHandle()]
    scheduled: list[tuple[object, ...]] = []
    results: list[tuple[bool, str]] = []

    def fake_run_in_pool(_operation, *arguments):
        scheduled.append(arguments)
        return handles[len(scheduled) - 1]

    monkeypatch.setattr("prismqml.run_in_pool", fake_run_in_pool)
    controller = _controller(results)

    controller.capture(10, "Demo", "before")
    assert controller.state["busy"] is True
    assert scheduled[0] == (10, "Demo", 25)
    handles[0].succeeded.emit(_capture_payload(20.0))

    assert controller.state["baselineCaptureId"] == "capture-1"
    assert controller.state["hotspots"][0]["selfMs"] == 20.0

    controller.capture(10, "Demo", "after")
    handles[1].succeeded.emit(_capture_payload(8.0))

    state = controller.state
    assert state["comparisonCaptureId"] == "capture-2"
    assert len(state["captures"]) == 2
    assert state["diff"]["summary"]["deltaMs"] == -12.0
    assert state["diff"]["summary"]["percent"] == -60.0


def test_controller_capture_requires_reachable_native_server() -> None:
    results: list[tuple[bool, str]] = []
    controller = _controller(results, reachable=False)

    controller.capture(10, "", "before")

    assert controller.state["busy"] is False
    assert results[-1][0] is False
    assert "未连接到 ModPC 原生 Tracy" in results[-1][1]


def test_controller_rejects_invalid_worker_payload(monkeypatch) -> None:
    handle = _FakeTaskHandle()
    results: list[tuple[bool, str]] = []
    monkeypatch.setattr("prismqml.run_in_pool", lambda _operation, *_args: handle)
    controller = _controller(results)

    controller.capture(10, "", "before")
    handle.succeeded.emit("invalid payload")

    assert controller.state["busy"] is False
    assert controller.state["captures"] == []
    assert results[-1][0] is False
    assert "后台返回值不是有效采样数据" in results[-1][1]
