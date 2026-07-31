# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""从已安装的 AirPerf 中定位和按需解包 aphost 运行时。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
from pathlib import Path
import struct
import tempfile
import threading
from typing import Mapping
import zlib

from .airperf_protocol import AirPerfProtocolError
from .config import AIRPERF_RUNTIME_DIR, AIRPERF_X64_PORT, AIRPERF_X86_PORT


CARCHIVE_MAGIC = b"MEI\x0c\x0b\x0a\x0b\x0e"
CARCHIVE_COOKIE_FORMAT = "!8sIIII64s"
CARCHIVE_ENTRY_FORMAT = "!IIIIBc"
ARCHIVE_SEARCH_BYTES = 8 * 1024 * 1024
AIRPERF_SERVICE_NAME = "airperf_service.exe"
APHOST_PORTS = {"x64": AIRPERF_X64_PORT, "win32": AIRPERF_X86_PORT}
APHOST_PREFIXES = {"x64": "win\\lib\\x64\\", "win32": "win\\lib\\win32\\"}
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


@dataclass(frozen=True)
class _ArchiveEntry:
    name: str
    offset: int
    compressed_size: int
    uncompressed_size: int
    compressed: bool


def _find_archive_cookie(stream, file_size: int) -> tuple[int, tuple[object, ...]]:
    search_size = min(file_size, ARCHIVE_SEARCH_BYTES)
    stream.seek(file_size - search_size)
    tail = stream.read(search_size)
    relative = tail.rfind(CARCHIVE_MAGIC)
    if relative < 0:
        raise AirPerfProtocolError("AirPerf 服务文件不是受支持的 PyInstaller CArchive")
    cookie_offset = file_size - search_size + relative
    cookie_size = struct.calcsize(CARCHIVE_COOKIE_FORMAT)
    raw_cookie = tail[relative : relative + cookie_size]
    if len(raw_cookie) != cookie_size:
        raise AirPerfProtocolError("AirPerf CArchive cookie 不完整")
    return cookie_offset, struct.unpack(CARCHIVE_COOKIE_FORMAT, raw_cookie)


def _read_archive_entries(source: Path) -> tuple[int, list[_ArchiveEntry]]:
    with source.open("rb") as stream:
        file_size = source.stat().st_size
        cookie_offset, cookie = _find_archive_cookie(stream, file_size)
        _, package_size, toc_offset, toc_size, _python_version, _library = cookie
        cookie_size = struct.calcsize(CARCHIVE_COOKIE_FORMAT)
        package_start = cookie_offset + cookie_size - int(package_size)
        toc_start = package_start + int(toc_offset)
        if package_start < 0 or toc_start + int(toc_size) != cookie_offset:
            raise AirPerfProtocolError("AirPerf CArchive 目录边界无效")
        stream.seek(toc_start)
        toc = stream.read(int(toc_size))
    return package_start, _parse_archive_toc(toc)


def _parse_archive_toc(toc: bytes) -> list[_ArchiveEntry]:
    header_size = struct.calcsize(CARCHIVE_ENTRY_FORMAT)
    entries: list[_ArchiveEntry] = []
    position = 0
    while position < len(toc):
        if position + header_size > len(toc):
            raise AirPerfProtocolError("AirPerf CArchive 目录项被截断")
        values = struct.unpack(CARCHIVE_ENTRY_FORMAT, toc[position : position + header_size])
        entry_size, offset, compressed_size, uncompressed_size, compressed, _type = values
        if entry_size < header_size or position + entry_size > len(toc):
            raise AirPerfProtocolError("AirPerf CArchive 目录项长度无效")
        raw_name = toc[position + header_size : position + entry_size]
        name = raw_name.split(b"\0", 1)[0].decode("utf-8", "replace")
        entries.append(_ArchiveEntry(name, offset, compressed_size, uncompressed_size, bool(compressed)))
        position += entry_size
    return entries


def _runtime_cache_root(environment: Mapping[str, str]) -> Path:
    configured = environment.get("MCNETEASE_AIRPERF_RUNTIME_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    if AIRPERF_RUNTIME_DIR:
        return Path(AIRPERF_RUNTIME_DIR).expanduser()
    local_app_data = environment.get("LOCALAPPDATA", "").strip()
    base = Path(local_app_data) if local_app_data else Path(tempfile.gettempdir())
    return base / "MCNeteaseToolPE" / "airperf_runtime"


def extract_aphost_runtime(
    service_executable: Path,
    architecture: str,
    environment: Mapping[str, str] | None = None,
) -> Path:
    """从 CArchive 中只解出目标架构的 aphost 运行目录。"""

    source = Path(service_executable)
    if not source.is_file():
        raise AirPerfProtocolError(f"未找到 AirPerf 服务：{source}")
    if architecture not in APHOST_PREFIXES:
        raise AirPerfProtocolError(f"不支持的 aphost 架构：{architecture}")
    stat = source.stat()
    version = f"{stat.st_size}-{stat.st_mtime_ns}"
    selected_environment = environment if environment is not None else os.environ
    root = _runtime_cache_root(selected_environment) / version / architecture
    executable = root / "aphost.exe"
    if executable.is_file():
        return executable
    package_start, entries = _read_archive_entries(source)
    selected = _select_runtime_entries(entries, APHOST_PREFIXES[architecture])
    _extract_entries(source, package_start, selected, root)
    if not executable.is_file():
        raise AirPerfProtocolError("AirPerf 服务包中缺少 aphost.exe")
    return executable


def _select_runtime_entries(entries: list[_ArchiveEntry], prefix: str) -> list[_ArchiveEntry]:
    selected: list[_ArchiveEntry] = []
    for entry in entries:
        normalized = entry.name.replace("/", "\\")
        if normalized.casefold().startswith(prefix.casefold()):
            relative = normalized[len(prefix) :]
            if relative and "\\" not in relative and relative not in (".", ".."):
                selected.append(entry)
    if not selected:
        raise AirPerfProtocolError(f"AirPerf 服务包中缺少 {prefix} 运行文件")
    return selected


def _extract_entries(source: Path, package_start: int, entries: list[_ArchiveEntry], root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as stream:
        for entry in entries:
            target = root / Path(entry.name.replace("/", "\\")).name
            if target.is_file() and target.stat().st_size == entry.uncompressed_size:
                continue
            stream.seek(package_start + entry.offset)
            payload = stream.read(entry.compressed_size)
            payload = zlib.decompress(payload) if entry.compressed else payload
            if len(payload) != entry.uncompressed_size:
                raise AirPerfProtocolError(f"解包 {entry.name} 后长度不匹配")
            temporary = target.with_name(f"{target.name}.tmp-{os.getpid()}-{threading.get_ident()}")
            temporary.write_bytes(payload)
            temporary.replace(target)


def find_airperf_libzmq(airperf_directory: Path) -> Path:
    root = Path(airperf_directory)
    candidates = sorted(root.glob("libzmq-*.dll"))
    if not candidates:
        candidates = sorted((root / "pyzmq.libs").glob("libzmq-*.dll"))
    if not candidates:
        raise AirPerfProtocolError(f"AirPerf 安装目录缺少 libzmq：{root}")
    return candidates[0]


def process_architecture(pid: int) -> str:
    """识别目标进程位数，用于选择官方 x64/win32 aphost。"""

    if os.name != "nt":
        raise OSError("AirPerf aphost 仅支持 Windows")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.IsWow64Process.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    kernel32.IsWow64Process.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        wow64 = wintypes.BOOL()
        if not kernel32.IsWow64Process(handle, ctypes.byref(wow64)):
            raise ctypes.WinError(ctypes.get_last_error())
        return "win32" if wow64.value else "x64"
    finally:
        kernel32.CloseHandle(handle)


__all__ = [
    "AIRPERF_SERVICE_NAME",
    "APHOST_PORTS",
    "extract_aphost_runtime",
    "find_airperf_libzmq",
    "process_architecture",
]
