# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""AirPerf aphost 协议、运行时解包和指标归约测试。"""

from __future__ import annotations

import json
from pathlib import Path
import struct
import time
import zlib

import pytest

from src.airperf_backend import (
    AirPerfGraphicsAccumulator,
    AirPerfMonitor,
    AirPerfSession,
    build_airperf_report_metrics,
)
from src.airperf_protocol import (
    APHOST_RPC_SIGNATURES,
    APHOST_RPC_SURFACE,
    AirPerfProtocol,
    AirPerfProtocolError,
    AirPerfRpcError,
    decode_response,
    encode_request,
)
from src.airperf_runtime import (
    CARCHIVE_COOKIE_FORMAT,
    CARCHIVE_ENTRY_FORMAT,
    CARCHIVE_MAGIC,
    extract_aphost_runtime,
    find_airperf_libzmq,
)


class _FakeTransport:
    def __init__(self, response: bytes) -> None:
        self.response = response
        self.requests: list[bytes] = []
        self.closed = False

    def request(self, payload: bytes) -> bytes:
        self.requests.append(payload)
        return self.response

    def close(self) -> None:
        self.closed = True


class _FakeProtocol:
    def __init__(self) -> None:
        self.removed: list[str] = []
        self.closed = False
        self.values: dict[tuple[str, str, str], float] = {
            ("Process", "ID Process", "ModPC"): 100,
            ("Process", "ID Process", "ModPC#1"): 4242,
            ("Processor", "% Processor Time", "_Total"): 50,
            ("Process", "% Processor Time", "ModPC#1"): 80,
            ("Process", "Working Set - Private", "ModPC#1"): 20 * 1_048_576,
        }

    def check_init_done(self) -> bool:
        return True

    def get_counter(self, _category: str) -> dict[str, object]:
        return {"Process": {"Instances": ["Other", "ModPC", "ModPC#1"]}}

    def get_data(self, category: str, counter: str, instance: str, host: str = "") -> object:
        del host
        return self.values.get((category, counter, instance), 1.0)

    def remove_counter(self, key: str) -> bool:
        self.removed.append(key)
        return True

    def close(self) -> None:
        self.closed = True


def test_protocol_encodes_verified_aphost_request_and_decodes_response() -> None:
    payload = encode_request("Profiler", "get_data", ["", "Memory", "Available MBytes", ""])
    request = json.loads(payload.decode("utf-8"))
    transport = _FakeTransport(b'{"isOk":true,"return":123.5}')
    protocol = AirPerfProtocol(transport=transport)

    result = protocol.get_data("Memory", "Available MBytes", "")
    protocol.close()

    assert request == {
        "cmd": "Profiler___get_data",
        "parameter": ["", "Memory", "Available MBytes", ""],
    }
    assert result == 123.5
    assert transport.closed is True


def test_protocol_rejects_rpc_failure_and_invalid_response() -> None:
    with pytest.raises(AirPerfRpcError, match="counter failed"):
        decode_response(b'{"isOk":false,"return":"counter failed"}')
    with pytest.raises(AirPerfProtocolError, match="无效 JSON"):
        decode_response(b"not-json")
    with pytest.raises(AirPerfProtocolError, match="缺少 isOk"):
        decode_response(b'{"return":1}')


def test_protocol_wraps_reversed_rpc_surface() -> None:
    transport = _FakeTransport(b'{"isOk":true,"return":true}')
    protocol = AirPerfProtocol(transport=transport)

    assert protocol.hook_process(4242) is True
    request = json.loads(transport.requests[-1].decode("utf-8"))

    assert request == {
        "cmd": "DxHooker___injectProcessWithDll",
        "parameter": [4242],
    }
    assert set(APHOST_RPC_SURFACE) == {
        "DxHooker",
        "Profiler",
        "PerfmonUtil",
        "ProcessUtil",
        "ScreenshotUtil",
        "ServerUtil",
        "SystemInfoUtil",
    }
    assert sum(map(len, APHOST_RPC_SURFACE.values())) == 23
    assert sum(map(len, APHOST_RPC_SIGNATURES.values())) == 23


def test_protocol_decodes_verified_method_name_and_arity_format() -> None:
    transport = _FakeTransport(
        b'{"isOk":true,"return":["get_data%%4","get_counter%%1","Equals%%1"]}'
    )
    protocol = AirPerfProtocol(transport=transport)

    assert protocol.get_method_signatures("Profiler") == [
        ("get_data", 4),
        ("get_counter", 1),
        ("Equals", 1),
    ]
    assert protocol.get_methods("Profiler") == ["get_data", "get_counter", "Equals"]


def test_protocol_decodes_verified_screenshot_handle_response_shape() -> None:
    transport = _FakeTransport(b'{"isOk":true,"return":{"value":12345}}')
    protocol = AirPerfProtocol(transport=transport)

    assert protocol.get_process_handle(4242) == 12345
    assert json.loads(transport.requests[-1].decode("utf-8")) == {
        "cmd": "ScreenshotUtil___getHandleByProcessId",
        "parameter": [4242],
    }


def test_graphics_accumulator_matches_official_second_bucket_formula() -> None:
    accumulator = AirPerfGraphicsAccumulator()
    timestamps = [
        1_000_000_000,
        1_016_000_000,
        1_032_000_000,
        1_048_000_000,
        1_198_000_000,
        2_000_000_000,
    ]
    raw_frames = [
        {
            "timestamp": timestamp,
            "drawCallCount": index * 10,
            "trangleCount": index * 100,
        }
        for index, timestamp in enumerate(timestamps, start=1)
    ]

    sample = accumulator.feed(raw_frames)

    assert sample["frameAverageFps"] == pytest.approx(20.202020, rel=1e-5)
    assert sample["frameDrawCalls"] == 10.0
    assert sample["frameTriangleCount"] == 100.0
    assert sample["frameJankCount"] == 0.0
    assert sample["frameBigJankCount"] == 1.0
    assert sample["frameTimeMaxMs"] == 150.0


def test_graphics_accumulator_preserves_every_completed_second_bucket() -> None:
    accumulator = AirPerfGraphicsAccumulator()
    raw_frames = [
        {"timestamp": 1_800_000_000, "drawCallCount": 10, "trangleCount": 100},
        {"timestamp": 1_900_000_000, "drawCallCount": 20, "trangleCount": 200},
        {"timestamp": 2_000_000_000, "drawCallCount": 30, "trangleCount": 300},
        {"timestamp": 2_050_000_000, "drawCallCount": 40, "trangleCount": 400},
        {"timestamp": 2_100_000_000, "drawCallCount": 50, "trangleCount": 500},
        {"timestamp": 3_000_000_000, "drawCallCount": 60, "trangleCount": 600},
    ]

    samples = accumulator.feed_all(raw_frames)

    assert [sample["frameAverageFps"] for sample in samples] == [10.0, 15.0]
    assert [sample["frameDrawCalls"] for sample in samples] == [10.0, 10.0]


def _build_carchive(path: Path, files: dict[str, bytes]) -> None:
    data_parts: list[bytes] = []
    toc_parts: list[bytes] = []
    offset = 0
    header_size = struct.calcsize(CARCHIVE_ENTRY_FORMAT)
    for name, payload in files.items():
        compressed = zlib.compress(payload)
        raw_name = name.encode("utf-8") + b"\0"
        entry_size = header_size + len(raw_name)
        toc_parts.append(
            struct.pack(
                CARCHIVE_ENTRY_FORMAT,
                entry_size,
                offset,
                len(compressed),
                len(payload),
                1,
                b"b",
            )
            + raw_name
        )
        data_parts.append(compressed)
        offset += len(compressed)
    data = b"".join(data_parts)
    toc = b"".join(toc_parts)
    cookie_size = struct.calcsize(CARCHIVE_COOKIE_FORMAT)
    package_size = len(data) + len(toc) + cookie_size
    cookie = struct.pack(
        CARCHIVE_COOKIE_FORMAT,
        CARCHIVE_MAGIC,
        package_size,
        len(data),
        len(toc),
        312,
        b"python312.dll".ljust(64, b"\0"),
    )
    path.write_bytes(b"MZ-SYNTHETIC" + data + toc + cookie + b"SIGNED-TRAILER")


def test_extracts_only_selected_aphost_architecture_from_signed_archive(tmp_path: Path) -> None:
    source = tmp_path / "airperf_service.exe"
    _build_carchive(
        source,
        {
            r"win\lib\x64\aphost.exe": b"x64-host",
            r"win\lib\x64\NetMQ.dll": b"x64-netmq",
            r"win\lib\win32\aphost.exe": b"x86-host",
            r"win\lib\x64\nested\ignored.dll": b"ignored",
        },
    )
    runtime = extract_aphost_runtime(
        source,
        "x64",
        {"MCNETEASE_AIRPERF_RUNTIME_DIR": str(tmp_path / "runtime")},
    )

    assert runtime.read_bytes() == b"x64-host"
    assert (runtime.parent / "NetMQ.dll").read_bytes() == b"x64-netmq"
    assert not (runtime.parent / "ignored.dll").exists()


def test_finds_root_or_pyzmq_libzmq_without_guessing_filename(tmp_path: Path) -> None:
    nested = tmp_path / "pyzmq.libs"
    nested.mkdir()
    dll = nested / "libzmq-build-id.dll"
    dll.write_bytes(b"dll")
    assert find_airperf_libzmq(tmp_path) == dll


def test_session_matches_pid_and_pname_then_converts_process_metrics(monkeypatch) -> None:
    protocol = _FakeProtocol()
    session = AirPerfSession(Path("MCStudio"), 4242, "ModPC.exe")
    session._protocol = protocol
    assert session._resolve_process_instance() == "ModPC#1"
    session._process_instance = "ModPC#1"
    monkeypatch.setattr("src.airperf_backend.os.cpu_count", lambda: 8)
    session._active_specs = session._resolved_specs()

    sample = session.sample()

    assert sample["systemCpuPercent"] == 50
    assert sample["processCpuPercent"] == 10
    assert sample["processPrivateWorkingSetMb"] == 20


class _FakeSession:
    def __init__(self, _root: Path, _pid: int, _name: str) -> None:
        self.closed = False
        self.value = 0

    def open(self) -> None:
        return None

    def sample(self) -> dict[str, float]:
        self.value += 1
        return {
            "systemCpuPercent": float(self.value * 10),
            "gpuUsagePercent": float(self.value * 20),
        }

    def close(self) -> None:
        self.closed = True


def test_monitor_collects_constant_space_summary_until_manual_stop() -> None:
    changes: list[bool] = []
    monitor = AirPerfMonitor(lambda: changes.append(True), _FakeSession, interval_ms=5)
    assert monitor.start(Path("MCStudio"), 42, "ModPC.exe") is True
    deadline = time.monotonic() + 1
    while monitor.state["sampleCount"] < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    monitor.stop()
    assert monitor._thread is not None
    monitor._thread.join(timeout=1)

    state = monitor.state
    assert state["active"] is False
    assert state["status"] == "complete"
    assert state["sampleCount"] >= 2
    assert state["summary"]["systemCpuPercent"]["maximum"] >= 20
    assert any(item["label"] == "AirPerf GPU 峰值" for item in state["metrics"])
    assert changes


def test_monitor_records_every_graphics_bucket_without_duplicating_system_sample() -> None:
    monitor = AirPerfMonitor(lambda: None, _FakeSession)

    monitor._record(
        {"systemCpuPercent": 30.0, "frameAverageFps": 20.0},
        [
            {"frameAverageFps": 10.0, "frameJankCount": 1.0},
            {"frameAverageFps": 20.0, "frameJankCount": 2.0},
        ],
    )

    summary = monitor.state["summary"]
    assert summary["systemCpuPercent"]["count"] == 1
    assert summary["frameAverageFps"]["count"] == 2
    assert summary["frameAverageFps"]["average"] == 15.0
    assert summary["frameJankCount"]["sum"] == 3.0
    assert {item["label"]: item["value"] for item in monitor.state["metrics"]}[
        "AirPerf 卡顿数"
    ] == "3"


def test_report_metrics_skip_unavailable_indicators() -> None:
    metrics = build_airperf_report_metrics(
        {"gpuTemperatureC": {"maximum": 61.5}},
        3,
    )
    assert metrics == [
        {"label": "AirPerf 采样", "value": "3"},
        {"label": "AirPerf GPU 温度峰值", "value": "61.5 °C"},
    ]


def test_monitor_reports_unavailable_backend_in_unified_metrics() -> None:
    monitor = AirPerfMonitor(lambda: None, _FakeSession)
    monitor.mark_unavailable("Windows PDH 不可用")
    assert monitor.state["status"] == "failed"
    assert monitor.state["message"] == "Windows PDH 不可用"
    assert monitor.state["metrics"] == [
        {"label": "AirPerf 状态", "value": "采集不可用"},
    ]
