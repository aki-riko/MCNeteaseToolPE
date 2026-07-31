# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
# Adapted from mcdk-mcp-tracy 491d339 (MIT); see THIRD_PARTY_NOTICES.md.
"""原生 Tracy 抓取、CSV 归约与前后采样对比。"""

from __future__ import annotations

import csv
import io
import ipaddress
import logging
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
from typing import Iterable, Mapping

from .config import TRACY_HOST, TRACY_PORT
from .tracy_semantics import is_wait_zone_name


LOGGER = logging.getLogger(__name__)
TRACY_BIN_DIR_ENV = "MCNETEASE_TRACY_BIN_DIR"
UPSTREAM_TRACY_BIN_DIR_ENV = "TRACY_BIN_DIR"
MAX_CAPTURE_SECONDS = 60
MAX_RESULT_ROWS = 500
DEFAULT_TOP_ROWS = 25
TRACY_EXECUTABLES = ("tracy-capture.exe", "tracy-csvexport.exe")
_CREATE_NO_WINDOW = 0x08000000
_NS_PER_MS = 1_000_000.0
_DURATION_UNITS = {
    "ns": 1e-9,
    "us": 1e-6,
    "µs": 1e-6,
    "ms": 1e-3,
    "s": 1.0,
}


class TracyAnalysisError(RuntimeError):
    """可直接反馈给性能页的 Tracy 诊断错误。"""


def bundled_tracy_bin_dir() -> Path:
    """返回源码或 Nuitka standalone 根目录中的随包 CLI 目录。"""

    return Path(__file__).resolve().parents[1] / "tracy_bin"


def resolve_tracy_bin_dir(
    environment: Mapping[str, str] | None = None,
) -> Path:
    env = environment if environment is not None else os.environ
    configured = (
        env.get(TRACY_BIN_DIR_ENV, "").strip()
        or env.get(UPSTREAM_TRACY_BIN_DIR_ENV, "").strip()
    )
    return Path(configured).expanduser() if configured else bundled_tracy_bin_dir()


def tracy_tool_paths(
    environment: Mapping[str, str] | None = None,
) -> dict[str, Path]:
    root = resolve_tracy_bin_dir(environment)
    return {name: root / name for name in TRACY_EXECUTABLES}


def validate_tracy_endpoint(address: str, port: int) -> tuple[str, int]:
    host = address.strip()
    if not host or host.casefold() == "localhost":
        host = "127.0.0.1"
    try:
        parsed = ipaddress.ip_address(host)
    except ValueError as error:
        raise TracyAnalysisError("Tracy 主机必须是 localhost 或回环 IP") from error
    if not parsed.is_loopback:
        raise TracyAnalysisError("Tracy 仅允许连接本机回环地址")
    try:
        normalized_port = int(port)
    except (TypeError, ValueError) as error:
        raise TracyAnalysisError("Tracy 端口不是有效整数") from error
    if normalized_port < 1 or normalized_port > 65_535:
        raise TracyAnalysisError("Tracy 端口必须在 1-65535 之间")
    return host, normalized_port


def probe_tracy(
    address: str = TRACY_HOST,
    port: int = TRACY_PORT,
    timeout: float = 0.25,
    environment: Mapping[str, str] | None = None,
) -> dict[str, object]:
    host, normalized_port = validate_tracy_endpoint(address, port)
    paths = tracy_tool_paths(environment)
    available = all(path.is_file() for path in paths.values())
    reachable = False
    try:
        with socket.create_connection((host, normalized_port), timeout=max(0.05, timeout)):
            reachable = True
    except OSError as error:
        LOGGER.debug("Tracy 端点暂不可达：%s:%s：%s", host, normalized_port, error)
    return {
        "address": host,
        "port": normalized_port,
        "reachable": reachable,
        "binAvailable": available,
        "binDir": str(resolve_tracy_bin_dir(environment)),
        "tools": {name: str(path) for name, path in paths.items()},
    }


def _parse_csv(text: str) -> dict[tuple[str, str], dict[str, object]]:
    result: dict[tuple[str, str], dict[str, object]] = {}
    for row in csv.DictReader(io.StringIO(text)):
        name = (row.get("name") or "").strip()
        if not name:
            continue
        source = (row.get("src_file") or "").strip()
        key = (name, source)
        try:
            nanoseconds = float(row.get("total_ns") or 0.0)
        except ValueError:
            LOGGER.debug("Tracy CSV total_ns 无效：%r", row.get("total_ns"))
            nanoseconds = 0.0
        try:
            calls = int(float(row.get("counts") or 0))
        except ValueError:
            LOGGER.debug("Tracy CSV counts 无效：%r", row.get("counts"))
            calls = 0
        current = result.get(key)
        if current is None:
            result[key] = {
                "nanoseconds": nanoseconds,
                "calls": calls,
                "sourceLine": (row.get("src_line") or "").strip(),
            }
            continue
        current["nanoseconds"] = float(current["nanoseconds"]) + nanoseconds
        current["calls"] = int(current["calls"]) + calls
    return result


def reduce_tracy_csv(self_text: str, total_text: str) -> list[dict[str, object]]:
    """合并 exclusive/inclusive CSV，并以 self 耗时稳定降序排列。"""

    self_map = _parse_csv(self_text)
    total_map = _parse_csv(total_text)
    rows: list[dict[str, object]] = []
    for key in set(self_map) | set(total_map):
        name, source = key
        self_row = self_map.get(key)
        total_row = total_map.get(key)
        self_ms = (
            float(self_row["nanoseconds"]) / _NS_PER_MS if self_row else 0.0
        )
        total_ms = (
            float(total_row["nanoseconds"]) / _NS_PER_MS if total_row else 0.0
        )
        calls = int((total_row or self_row or {}).get("calls", 0))
        display_name = f"{name} @ {source}" if source else name
        rows.append(
            {
                "name": display_name,
                "function": name,
                "sourceFile": source,
                "sourceLine": str((total_row or self_row or {}).get("sourceLine", "")),
                "selfMs": round(self_ms, 3),
                "totalMs": round(total_ms, 3),
                "calls": calls,
                "selfPerCallMs": round(self_ms / calls, 6) if calls else 0.0,
            }
        )
    rows.sort(
        key=lambda row: (
            -float(row["selfMs"]),
            -float(row["totalMs"]),
            -int(row["calls"]),
            str(row["name"]).casefold(),
        )
    )
    return rows


def parse_capture_stats(text: str) -> dict[str, int | None]:
    def _value(label: str) -> int | None:
        match = re.search(label + r"\s*:?\s*([\d,]+)", text)
        if match is None:
            return None
        try:
            return int(match.group(1).replace(",", ""))
        except ValueError:
            LOGGER.debug("Tracy 统计字段 %s 无效：%s", label, match.group(1))
            return None

    return {"frames": _value("Frames"), "zones": _value("Zones")}


def parse_capture_span_seconds(text: str) -> float | None:
    """读取 tracy-capture 的真实 Time span，并统一换算为秒。"""

    match = re.search(
        r"Time\s+span\s*:\s*([\d.]+)\s*(ns|us|µs|ms|s)\b",
        text,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    return value * _DURATION_UNITS[match.group(2).casefold()]


def filter_tracy_rows(
    rows: Iterable[dict[str, object]],
    name_contains: str = "",
    limit: int = DEFAULT_TOP_ROWS,
) -> list[dict[str, object]]:
    bounded_limit = max(1, min(MAX_RESULT_ROWS, int(limit)))
    return _matching_tracy_rows(rows, name_contains)[:bounded_limit]


def _matching_tracy_rows(
    rows: Iterable[dict[str, object]],
    name_contains: str,
) -> list[dict[str, object]]:
    needle = name_contains.strip().casefold()
    return [
        dict(row)
        for row in rows
        if not needle or needle in str(row.get("name", "")).casefold()
    ]


def _completed_process_text(result: subprocess.CompletedProcess[bytes]) -> str:
    return (
        (result.stdout or b"").decode("utf-8", "replace")
        + "\n"
        + (result.stderr or b"").decode("utf-8", "replace")
    )


def _run_tool(arguments: list[str], timeout: float) -> subprocess.CompletedProcess[bytes]:
    creationflags = _CREATE_NO_WINDOW if sys.platform == "win32" else 0
    return subprocess.run(
        arguments,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
        creationflags=creationflags,
    )


def _capture_setup(
    seconds: int,
    address: str,
    port: int,
    environment: Mapping[str, str] | None,
) -> tuple[int, str, int, dict[str, Path]]:
    try:
        duration = int(seconds)
    except (TypeError, ValueError) as error:
        raise TracyAnalysisError("采样时长不是有效整数") from error
    if duration < 1 or duration > MAX_CAPTURE_SECONDS:
        raise TracyAnalysisError(f"采样时长必须在 1-{MAX_CAPTURE_SECONDS} 秒之间")
    host, normalized_port = validate_tracy_endpoint(address, port)
    tools = tracy_tool_paths(environment)
    missing = [str(path) for path in tools.values() if not path.is_file()]
    if missing:
        raise TracyAnalysisError("缺少 Tracy CLI：" + "、".join(missing))
    return duration, host, normalized_port, tools


def _capture_trace(
    trace_path: Path,
    tools: Mapping[str, Path],
    host: str,
    port: int,
    duration: int,
) -> str:
    result = _run_tool(
        [
            str(tools["tracy-capture.exe"]),
            "-o", str(trace_path),
            "-a", host,
            "-p", str(port),
            "-s", str(duration),
            "-f",
        ],
        timeout=duration + 25.0,
    )
    output = _completed_process_text(result)
    if result.returncode != 0:
        detail = output.strip()[-300:]
        raise TracyAnalysisError(f"Tracy 抓取失败（退出码 {result.returncode}）：{detail}")
    instrumentation_failure = re.search(
        r"Instrumentation failure:\s*([^\r\n]+)",
        output,
        flags=re.IGNORECASE,
    )
    if instrumentation_failure is not None:
        raise TracyAnalysisError(
            "Tracy 抓取失败：Instrumentation failure: "
            + instrumentation_failure.group(1).strip()
        )
    captured_seconds = parse_capture_span_seconds(output)
    minimum_seconds = max(0.5, duration * 0.8)
    if captured_seconds is not None and captured_seconds < minimum_seconds:
        raise TracyAnalysisError(
            "Tracy 抓取提前结束："
            f"实际 {captured_seconds:.3f} 秒，预期 {duration} 秒"
        )
    if not trace_path.is_file() or trace_path.stat().st_size == 0:
        raise TracyAnalysisError("Tracy 未生成有效采样文件，请确认 ModPC 正在运行")
    return output


def _export_trace_rows(
    trace_path: Path,
    csv_exporter: Path,
) -> list[dict[str, object]]:
    self_result = _run_tool([str(csv_exporter), "-e", str(trace_path)], timeout=60.0)
    total_result = _run_tool([str(csv_exporter), str(trace_path)], timeout=60.0)
    if self_result.returncode != 0 or total_result.returncode != 0:
        raise TracyAnalysisError(
            "Tracy CSV 导出失败"
            f"（退出码 {self_result.returncode}/{total_result.returncode}）"
        )
    return reduce_tracy_csv(
        (self_result.stdout or b"").decode("utf-8", "replace"),
        (total_result.stdout or b"").decode("utf-8", "replace"),
    )


def _decorate_rows(
    rows: Iterable[dict[str, object]],
    frames: int | None,
) -> list[dict[str, object]]:
    decorated: list[dict[str, object]] = []
    for row in rows:
        payload = dict(row)
        payload["selfPerFrameMs"] = (
            round(float(row["selfMs"]) / frames, 6) if frames else 0.0
        )
        decorated.append(payload)
    return decorated


def capture_tracy(
    seconds: int,
    name_contains: str = "",
    top_n: int = DEFAULT_TOP_ROWS,
    address: str = TRACY_HOST,
    port: int = TRACY_PORT,
    environment: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """从运行中的 ModPC 原生 Tracy 服务抓取并归约一次采样。"""

    duration, host, normalized_port, tools = _capture_setup(
        seconds, address, port, environment
    )
    with tempfile.TemporaryDirectory(prefix="mcnetease-tracy-") as temp_dir:
        trace_path = Path(temp_dir) / "capture.tracy"
        capture_output = _capture_trace(
            trace_path, tools, host, normalized_port, duration
        )
        rows = _export_trace_rows(trace_path, tools["tracy-csvexport.exe"])
    stats = parse_capture_stats(capture_output)
    capture_span_seconds = parse_capture_span_seconds(capture_output)
    if capture_span_seconds is None:
        capture_span_seconds = float(duration)
    frames = stats["frames"]
    decorated_rows = _decorate_rows(rows, frames)
    visible_rows = filter_tracy_rows(decorated_rows, name_contains, top_n)
    return {
        "seconds": duration,
        "captureSpanSeconds": round(capture_span_seconds, 3),
        "address": host,
        "port": normalized_port,
        "frames": frames,
        "zones": stats["zones"],
        "averageFps": (
            round(frames / capture_span_seconds, 2)
            if frames is not None and capture_span_seconds > 0
            else None
        ),
        "filter": name_contains.strip(),
        "uniqueFunctions": len(decorated_rows),
        "matchedFunctions": len(_matching_tracy_rows(decorated_rows, name_contains)),
        "totalSelfMs": round(sum(float(row["selfMs"]) for row in decorated_rows), 3),
        "totalTotalMs": round(sum(float(row["totalMs"]) for row in decorated_rows), 3),
        "rows": decorated_rows,
        "top": visible_rows,
    }


def _capture_self_index(
    capture: Mapping[str, object],
    name_contains: str,
) -> dict[str, float]:
    rows = capture.get("rows", [])
    if not isinstance(rows, Iterable) or isinstance(rows, (str, bytes, Mapping)):
        raise TracyAnalysisError("Tracy 采样记录的函数数据无效")
    filtered = _matching_tracy_rows(rows, name_contains)  # type: ignore[arg-type]
    return {
        str(row["name"]): float(row["selfMs"])
        for row in filtered
        if not is_wait_zone_name(row["name"])
    }


def _diff_rows(
    base_index: Mapping[str, float],
    new_index: Mapping[str, float],
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    improved: list[dict[str, object]] = []
    regressed: list[dict[str, object]] = []
    for name in base_index.keys() & new_index.keys():
        before = base_index[name]
        after = new_index[name]
        delta = after - before
        if delta == 0:
            continue
        item = {
            "name": name,
            "baseMs": round(before, 3),
            "newMs": round(after, 3),
            "deltaMs": round(delta, 3),
            "percent": round(delta / before * 100.0, 2) if before else None,
        }
        (improved if delta < 0 else regressed).append(item)
    added = [
        _presence_diff_row(name, 0.0, new_index[name])
        for name in new_index.keys() - base_index.keys()
    ]
    removed = [
        _presence_diff_row(name, base_index[name], 0.0)
        for name in base_index.keys() - new_index.keys()
    ]
    improved.sort(key=lambda item: (float(item["deltaMs"]), str(item["name"])))
    regressed.sort(key=lambda item: (-float(item["deltaMs"]), str(item["name"])))
    added.sort(key=lambda item: (-float(item["newMs"]), str(item["name"])))
    removed.sort(key=lambda item: (-float(item["baseMs"]), str(item["name"])))
    return improved, regressed, added, removed


def _presence_diff_row(name: str, before: float, after: float) -> dict[str, object]:
    delta = after - before
    return {
        "name": name,
        "baseMs": round(before, 3),
        "newMs": round(after, 3),
        "deltaMs": round(delta, 3),
        "percent": round(delta / before * 100.0, 2) if before else None,
    }


def diff_tracy_captures(
    base: Mapping[str, object],
    new: Mapping[str, object],
    name_contains: str = "",
    top_n: int = DEFAULT_TOP_ROWS,
) -> dict[str, object]:
    """按函数 self 耗时对两次等长采样做 before/after 对比。"""

    if int(base.get("seconds", 0)) != int(new.get("seconds", 0)):
        raise TracyAnalysisError("基线与复测采样时长不同，不能直接比较")
    base_index = _capture_self_index(base, name_contains)
    new_index = _capture_self_index(new, name_contains)
    improved, regressed, added, removed = _diff_rows(base_index, new_index)
    base_total = sum(base_index.values())
    new_total = sum(new_index.values())
    delta_total = new_total - base_total
    bounded = max(1, min(MAX_RESULT_ROWS, int(top_n)))
    return {
        "baseId": str(base.get("captureId", "")),
        "newId": str(new.get("captureId", "")),
        "filter": name_contains.strip(),
        "summary": {
            "baseSelfMs": round(base_total, 3),
            "newSelfMs": round(new_total, 3),
            "deltaMs": round(delta_total, 3),
            "percent": round(delta_total / base_total * 100.0, 2) if base_total else None,
        },
        "improved": improved[:bounded],
        "regressed": regressed[:bounded],
        "added": added[:bounded],
        "removed": removed[:bounded],
    }


__all__ = [
    "DEFAULT_TOP_ROWS",
    "MAX_CAPTURE_SECONDS",
    "TRACY_BIN_DIR_ENV",
    "TRACY_EXECUTABLES",
    "TracyAnalysisError",
    "capture_tracy",
    "diff_tracy_captures",
    "filter_tracy_rows",
    "parse_capture_stats",
    "probe_tracy",
    "reduce_tracy_csv",
    "resolve_tracy_bin_dir",
    "tracy_tool_paths",
    "validate_tracy_endpoint",
]
