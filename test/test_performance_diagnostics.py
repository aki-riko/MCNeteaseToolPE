# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""性能诊断后端、官方工具桥接与 QML 页面的回归测试。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication

from src.performance_backend import (
    CPU_PROFILE_SNIPPET,
    MAX_HISTORY_SAMPLES,
    MEMORY_PROFILE_SNIPPET,
    PerformanceBackend,
)
from src.performance_monitor import (
    MCSTUDIO_ROOT_ENV,
    PerformanceToolLocator,
    ProcessDescriptor,
    ProcessSample,
    is_minecraft_process,
    mcstudio_root_candidates,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN = REPO_ROOT / "main.py"
PAGE = REPO_ROOT / "qml" / "PerformancePage.qml"
TRACY_CARD = REPO_ROOT / "qml" / "TracyAnalysisCard.qml"


class _FakeLocator:
    def __init__(self, root: Path, available: bool = True) -> None:
        self._root = root
        self._available = available

    def discover(self) -> dict[str, object]:
        tools = {
            "tracy": {
                "available": self._available,
                "path": str(self._root / "tracy" / "tracy-profiler.exe"),
            },
            "airperf": {
                "available": self._available,
                "path": str(self._root / "airperf" / "airperf.exe"),
            },
        }
        return {"root": str(self._root), "configured": True, "tools": tools}


class _FakeSampler:
    def __init__(self) -> None:
        self.processes = [ProcessDescriptor(42, "Minecraft.Windows.exe")]
        self.samples: list[ProcessSample] = [ProcessSample(42, 12.5, 640.0, 700.0)]
        self.reset_calls: list[int] = []
        self.list_error: OSError | None = None
        self.sample_error: OSError | None = None

    def list_candidates(self) -> list[ProcessDescriptor]:
        if self.list_error is not None:
            raise self.list_error
        return list(self.processes)

    def reset(self, pid: int) -> None:
        self.reset_calls.append(pid)

    def sample(self, _pid: int) -> ProcessSample:
        if self.sample_error is not None:
            raise self.sample_error
        if self.samples:
            return self.samples.pop(0)
        return ProcessSample(42, 25.0, 650.0, 710.0)


def _application() -> QCoreApplication:
    return QCoreApplication.instance() or QCoreApplication([])


def _create_tool_tree(root: Path) -> None:
    tracy = root / "tracy" / "tracy-profiler.exe"
    airperf = root / "airperf" / "airperf.exe"
    tracy.parent.mkdir(parents=True)
    airperf.parent.mkdir(parents=True)
    tracy.write_bytes(b"tracy")
    airperf.write_bytes(b"airperf")


def test_minecraft_process_filter_excludes_studio_and_accepts_modpc() -> None:
    assert is_minecraft_process("Minecraft.Windows.exe") is True
    assert is_minecraft_process("CustomModPC.exe") is True
    assert is_minecraft_process("MCStudio.exe") is False
    assert is_minecraft_process("MinecraftLauncher.exe") is False
    assert is_minecraft_process("explorer.exe") is False


def test_mcstudio_root_override_and_tool_discovery(tmp_path: Path) -> None:
    root = tmp_path / "MCStudio"
    _create_tool_tree(root)
    environment = {
        MCSTUDIO_ROOT_ENV: str(root),
        "PROGRAMFILES(X86)": str(tmp_path / "Program Files x86"),
    }

    candidates = mcstudio_root_candidates(environment)
    discovery = PerformanceToolLocator(environment=environment).discover()

    assert candidates[0] == root
    assert discovery["root"] == str(root)
    assert discovery["tools"]["tracy"]["available"] is True
    assert discovery["tools"]["airperf"]["available"] is True
    assert discovery["configured"] is True


def test_mcstudio_candidates_use_only_injected_path(monkeypatch, tmp_path: Path) -> None:
    injected_path = str(tmp_path / "isolated-bin")
    calls: list[tuple[str, str]] = []

    def fake_which(command: str, *, path: str) -> None:
        calls.append((command, path))
        return None

    monkeypatch.setattr("src.performance_monitor.shutil.which", fake_which)

    mcstudio_root_candidates({"PATH": injected_path})

    assert calls == [("MCStudio.exe", injected_path)]


def test_explicit_mcstudio_root_is_authoritative_when_incomplete(tmp_path: Path) -> None:
    configured_root = tmp_path / "configured"
    configured_root.mkdir()
    complete_root = tmp_path / "Program Files x86" / "Netease" / "MCStudio"
    _create_tool_tree(complete_root)
    environment = {
        MCSTUDIO_ROOT_ENV: str(configured_root),
        "PATH": "",
        "PROGRAMFILES(X86)": str(tmp_path / "Program Files x86"),
    }

    discovery = PerformanceToolLocator(environment=environment).discover()

    assert discovery["root"] == str(configured_root)
    assert discovery["configured"] is True
    assert discovery["tools"]["tracy"]["available"] is False
    assert discovery["tools"]["airperf"]["available"] is False


def test_auto_discovery_prefers_candidate_with_all_tools(tmp_path: Path) -> None:
    incomplete_root = tmp_path / "incomplete"
    incomplete_root.mkdir()
    complete_root = tmp_path / "complete"
    _create_tool_tree(complete_root)

    discovery = PerformanceToolLocator(
        lambda: [incomplete_root, complete_root],
        environment={},
    ).discover()

    assert discovery["root"] == str(complete_root)
    assert discovery["tools"]["tracy"]["available"] is True
    assert discovery["tools"]["airperf"]["available"] is True


def test_backend_samples_process_and_caps_history(tmp_path: Path) -> None:
    _application()
    root = tmp_path / "MCStudio"
    _create_tool_tree(root)
    sampler = _FakeSampler()
    backend = PerformanceBackend(locator=_FakeLocator(root), sampler=sampler)

    backend.refresh()
    backend.startMonitoring()
    for _index in range(MAX_HISTORY_SAMPLES + 5):
        backend._sample_selected_process()

    state = backend.state
    backend.stopMonitoring()

    assert sampler.reset_calls == [42]
    assert state["selectedPid"] == 42
    assert state["cpuPercent"] == 25.0
    assert state["workingSetMb"] == 650.0
    assert state["peakWorkingSetMb"] == 710.0
    assert len(state["cpuHistory"]) == MAX_HISTORY_SAMPLES
    assert len(state["memoryHistory"]) == MAX_HISTORY_SAMPLES


def test_backend_refresh_target_auto_selects_late_modpc_process(tmp_path: Path) -> None:
    _application()
    sampler = _FakeSampler()
    sampler.processes = []
    probe_calls: list[bool] = []

    def tracy_probe() -> dict[str, object]:
        probe_calls.append(True)
        return {
            "address": "127.0.0.1",
            "port": 8086,
            "reachable": False,
            "binAvailable": True,
            "binDir": "tracy_bin",
            "tools": {},
        }

    backend = PerformanceBackend(
        locator=_FakeLocator(tmp_path),
        sampler=sampler,
        tracy_probe=tracy_probe,
    )
    backend.refresh()
    assert backend.state["selectedPid"] == 0

    sampler.processes = [ProcessDescriptor(84, "ModPC.exe")]
    backend.refreshPerformanceTarget()

    assert backend.state["selectedPid"] == 84
    assert backend.state["processes"][0]["name"] == "ModPC.exe"
    assert len(probe_calls) == 2


def test_backend_launches_only_discovered_official_tools(tmp_path: Path) -> None:
    _application()
    root = tmp_path / "MCStudio"
    _create_tool_tree(root)
    launched: list[Path] = []
    results: list[dict[str, object]] = []
    backend = PerformanceBackend(
        locator=_FakeLocator(root),
        sampler=_FakeSampler(),
        launcher=lambda path: launched.append(path) is None,
    )
    backend.result.connect(lambda result: results.append(result))

    backend.refresh()
    backend.launchTracy()
    backend.launchAirPerf()

    assert launched == [
        root / "tracy" / "tracy-profiler.exe",
        root / "airperf" / "airperf.exe",
    ]
    assert all(result["success"] is True for result in results)


def test_backend_does_not_launch_missing_tool(tmp_path: Path) -> None:
    _application()
    launched: list[Path] = []
    results: list[dict[str, object]] = []
    backend = PerformanceBackend(
        locator=_FakeLocator(tmp_path, available=False),
        sampler=_FakeSampler(),
        launcher=lambda path: launched.append(path) is None,
    )
    backend.result.connect(results.append)

    backend.refresh()
    backend.launchTracy()

    assert launched == []
    assert results[-1]["success"] is False
    assert "未找到" in str(results[-1]["message"])


def test_backend_reports_launcher_false_and_oserror(tmp_path: Path) -> None:
    _application()
    root = tmp_path / "MCStudio"
    _create_tool_tree(root)
    results: list[dict[str, object]] = []
    backend = PerformanceBackend(
        locator=_FakeLocator(root),
        sampler=_FakeSampler(),
        launcher=lambda _path: False,
    )
    backend.result.connect(results.append)
    backend.refresh()

    backend.launchTracy()
    assert results[-1]["success"] is False
    assert results[-1]["message"] == "启动 方块探针（Tracy） 失败"

    def raise_launch_error(_path: Path) -> bool:
        raise OSError("拒绝访问")

    backend._launcher = raise_launch_error
    backend.launchAirPerf()
    assert results[-1]["success"] is False
    assert "拒绝访问" in str(results[-1]["message"])


def test_backend_requires_a_selected_process_before_monitoring(tmp_path: Path) -> None:
    _application()
    sampler = _FakeSampler()
    sampler.processes = []
    results: list[dict[str, object]] = []
    backend = PerformanceBackend(locator=_FakeLocator(tmp_path), sampler=sampler)
    backend.result.connect(results.append)

    backend.refresh()
    backend.startMonitoring()

    assert backend.state["monitoring"] is False
    assert backend._timer.isActive() is False
    assert results[-1]["success"] is False
    assert "请先启动并选择" in str(results[-1]["message"])


def test_sampling_process_exit_stops_timer_and_refreshes_processes(tmp_path: Path) -> None:
    _application()
    sampler = _FakeSampler()
    sampler.sample_error = ProcessLookupError("进程已退出")
    results: list[dict[str, object]] = []
    backend = PerformanceBackend(locator=_FakeLocator(tmp_path), sampler=sampler)
    backend.result.connect(results.append)
    backend.refresh()
    sampler.processes = []

    backend.startMonitoring()

    assert backend.state["monitoring"] is False
    assert backend.state["selectedPid"] == 0
    assert backend.state["processes"] == []
    assert backend._timer.isActive() is False
    assert results[-1]["success"] is False
    assert "目标进程不可用" in str(results[-1]["message"])


def test_refresh_process_exit_stops_monitoring_as_failure(tmp_path: Path) -> None:
    _application()
    sampler = _FakeSampler()
    results: list[dict[str, object]] = []
    backend = PerformanceBackend(locator=_FakeLocator(tmp_path), sampler=sampler)
    backend.result.connect(results.append)
    backend.refresh()
    backend.startMonitoring()
    sampler.processes = []

    backend.refresh()

    assert backend.state["monitoring"] is False
    assert backend.state["selectedPid"] == 0
    assert backend._timer.isActive() is False
    assert results[-1]["success"] is False
    assert "目标进程已退出" in str(results[-1]["message"])


def test_refresh_enumeration_error_preserves_active_target(tmp_path: Path) -> None:
    _application()
    sampler = _FakeSampler()
    results: list[dict[str, object]] = []
    backend = PerformanceBackend(locator=_FakeLocator(tmp_path), sampler=sampler)
    backend.result.connect(results.append)
    backend.refresh()
    backend.startMonitoring()
    sampler.list_error = OSError("快照失败")

    backend.refresh()
    state = backend.state
    backend.stopMonitoring()

    assert state["monitoring"] is True
    assert state["selectedPid"] == 42
    assert len(state["processes"]) == 1
    assert results[-2]["success"] is False
    assert "快照失败" in str(results[-2]["message"])


def test_profile_snippets_use_only_documented_modapi_and_copy(tmp_path: Path) -> None:
    _application()
    copied: list[str] = []
    backend = PerformanceBackend(
        locator=_FakeLocator(tmp_path, available=False),
        sampler=_FakeSampler(),
        clipboard_setter=copied.append,
    )

    backend.copyProfileSnippet("cpu")
    backend.copyProfileSnippet("memory")

    assert copied == [CPU_PROFILE_SNIPPET, MEMORY_PROFILE_SNIPPET]
    assert "serverApi.StartProfile()" in CPU_PROFILE_SNIPPET
    assert "serverApi.StopProfile(fileName)" in CPU_PROFILE_SNIPPET
    assert "serverApi.StartMemProfile()" in MEMORY_PROFILE_SNIPPET
    assert "serverApi.StopMemProfile(fileName)" in MEMORY_PROFILE_SNIPPET
    assert "gameComp.AddTimer" in CPU_PROFILE_SNIPPET


def test_performance_page_is_registered_and_declares_fidelity_boundary() -> None:
    main_source = MAIN.read_text(encoding="utf-8")
    page_source = PAGE.read_text(encoding="utf-8")
    tracy_source = TRACY_CARD.read_text(encoding="utf-8")

    assert "performance_backend = PerformanceBackend()" in main_source
    assert '_page_factory("PerformancePage.qml", performance_backend)' in main_source
    assert '"性能诊断"' in main_source
    for contract in (
        'objectName: "performancePage"',
        'objectName: "performanceOfficialToolsCard"',
        'objectName: "performanceProcessCard"',
        'objectName: "performanceProfileCard"',
        'objectName: "performanceThresholdCard"',
        'objectName: "performanceCpuChart"',
        'objectName: "performanceMemoryChart"',
        "TracyAnalysisCard",
        "专业工具（可选）",
        'backend.copyProfileSnippet("cpu")',
        'backend.copyProfileSnippet("memory")',
        "不能直接替代网易手机集群",
        "官方未公开采样窗口",
    ):
        assert contract in page_source
    assert page_source.index("TracyAnalysisCard {") < page_source.index(
        'objectName: "performanceOfficialToolsCard"'
    )
    for contract in (
        'objectName: "tracyAnalysisCard"',
        'objectName: "tracyQuickCaptureButton"',
        'qsTr("开始检测")',
        'qsTr("再次检测并对比")',
        'qsTr("等待 ModPC 启动…")',
        'qsTr("新增")',
        'qsTr("消失")',
        "结果用于本机优化，不等于网易机审成绩",
        "backend.captureTracyQuick()",
        "backend.refreshPerformanceTarget()",
        'objectName: "tracyReportSection"',
        'objectName: "tracyReportTitle"',
        'objectName: "tracyReportConclusion"',
        'qsTr("优先关注")',
        'qsTr("下一步建议")',
    ):
        assert contract in tracy_source
    for removed_control in (
        'objectName: "tracyDurationSpinBox"',
        'objectName: "tracyFilterInput"',
        'objectName: "tracyRefreshButton"',
        'objectName: "tracyResetButton"',
    ):
        assert removed_control not in tracy_source
