# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import socket
import struct
import subprocess
import sys

import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

import src.mcp_project_service as mcp_service_module
import src.mcp_server_backend as mcp_backend_module
from src.mcp_project_service import ProjectToolService
from src.mcp_server import (
    create_mcp_server,
    format_endpoint,
    validate_loopback_host,
    validate_mcp_path,
    validate_port,
)
from src.mcp_server_backend import McpServerBackend, _mcp_server_command
from test.test_level_db import _PackedMap, _pack, _script_data_nbt, _write_batch, _write_db


ROOT = Path(__file__).resolve().parents[1]


def _make_project(root: Path) -> Path:
    pack = root / "behavior_demo"
    pack.mkdir(parents=True)
    manifest = {
        "format_version": 2,
        "header": {
            "name": "Demo",
            "description": "Demo pack",
            "uuid": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "version": [1, 0, 0],
            "min_engine_version": [1, 20, 0],
        },
        "modules": [
            {
                "type": "data",
                "uuid": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "version": [1, 0, 0],
            }
        ],
    }
    (pack / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (pack / "modMain.py").write_text("VALUE = 1\n", encoding="utf-8")
    return root


def _nbt_string(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return struct.pack("<H", len(encoded)) + encoded


def _make_level_dat(path: Path, level_name: str = "测试存档") -> Path:
    child = b"\x08" + _nbt_string("LevelName") + _nbt_string(level_name)
    root = b"\x0a\x00\x00" + child + b"\x00"
    path.write_bytes(struct.pack("<II", 10, len(root)) + root)
    return path


def test_project_service_uses_call_path_and_read_tools_do_not_modify(tmp_path: Path) -> None:
    project = _make_project(tmp_path / "project")
    service = ProjectToolService()
    before = (project / "behavior_demo" / "manifest.json").read_bytes()

    overview = service.get_project_overview(str(project))
    cleanup = service.preview_cleanup(str(project))
    audit = service.audit_project(str(project))

    assert overview["project_root"] == str(project.resolve())
    assert overview["pack_count"] == 1
    assert cleanup == {
        "item_count": 0,
        "total_bytes": 0,
        "items": [],
        "truncated": False,
    }
    assert audit["issue_count"] >= 0
    assert (project / "behavior_demo" / "manifest.json").read_bytes() == before


def test_mcp_result_limits_cap_expensive_payload_normalization(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = _make_project(tmp_path / "project")
    service = ProjectToolService()
    audit_payload_calls = 0
    relative_calls = 0

    class FakeIssue:
        def __init__(self, index: int) -> None:
            self.index = index

        def as_dict(self) -> dict[str, object]:
            return {
                "severity": "error" if self.index % 2 == 0 else "warning",
                "path": str(project / f"issue-{self.index}.json"),
            }

    original_audit_payload = service._audit_payload
    original_relative = service._relative

    def tracked_audit_payload(root: Path, payload: dict[str, object]):
        nonlocal audit_payload_calls
        audit_payload_calls += 1
        return original_audit_payload(root, payload)

    def tracked_relative(root: Path, path: str | Path) -> str:
        nonlocal relative_calls
        relative_calls += 1
        return original_relative(root, path)

    cleanup_result = type(
        "CleanupResult",
        (),
        {
            "items": [str(project / f"junk-{index}.pyc") for index in range(100)],
            "total_bytes": 1234,
        },
    )()
    monkeypatch.setattr(
        mcp_service_module,
        "scan",
        lambda _root: [FakeIssue(index) for index in range(100)],
    )
    monkeypatch.setattr(mcp_service_module, "_scan", lambda _root: (cleanup_result, []))
    monkeypatch.setattr(service, "_audit_payload", tracked_audit_payload)
    monkeypatch.setattr(service, "_relative", tracked_relative)

    audit = service.audit_project(str(project), max_issues=3)
    audit_relative_calls = relative_calls
    cleanup = service.preview_cleanup(str(project), max_items=4)

    assert audit["issue_count"] == 100
    assert audit["error_count"] == 50
    assert audit["warning_count"] == 50
    assert len(audit["issues"]) == 3
    assert audit["truncated"] is True
    assert audit_payload_calls == 3
    assert audit_relative_calls == 3
    assert cleanup["item_count"] == 100
    assert cleanup["items"] == [f"junk-{index}.pyc" for index in range(4)]
    assert cleanup["truncated"] is True
    assert relative_calls == 7


def test_mutating_tools_require_confirmation_and_stay_in_project(tmp_path: Path) -> None:
    project = _make_project(tmp_path / "project")
    junk = project / "behavior_demo" / "cache.pyc"
    junk.write_bytes(b"junk")
    service = ProjectToolService()

    with pytest.raises(PermissionError, match="confirm"):
        service.clean_project(str(project))
    with pytest.raises(PermissionError, match="confirm"):
        service.rewrite_project_uuids(str(project))
    with pytest.raises(PermissionError, match="confirm"):
        service.package_project(str(project))

    cleaned = service.clean_project(str(project), confirm=True)
    rewritten = service.rewrite_project_uuids(str(project), confirm=True)
    packaged = service.package_project(str(project), confirm=True)

    assert cleaned["success"] is True
    assert cleaned["removed_count"] == 1
    assert not junk.exists()
    assert rewritten["success"] is True
    assert rewritten["changed_count"] == 1
    archive = Path(packaged["archive_path"])
    assert archive == project / "project.zip"
    assert archive.is_file()
    assert archive.parent == project.resolve()


def test_one_service_accepts_different_project_paths_per_call(tmp_path: Path) -> None:
    first = _make_project(tmp_path / "first")
    second = _make_project(tmp_path / "second")
    service = ProjectToolService()

    first_overview = service.get_project_overview(str(first))
    second_overview = service.get_project_overview(str(second))

    assert first_overview["project_root"] == str(first.resolve())
    assert second_overview["project_root"] == str(second.resolve())


def test_one_click_project_tool_runs_all_four_steps(tmp_path: Path) -> None:
    project = _make_project(tmp_path / "project")
    junk = project / "behavior_demo" / "cache.pyc"
    junk.write_bytes(b"junk")

    result = ProjectToolService().process_project(str(project), confirm=True)

    assert result["success"] is True
    assert result["completed_steps"] == ["cleanup", "audit", "uuid", "package"]
    assert result["cleanup"]["removed_count"] == 1
    assert result["cleanup"]["created_required_directories"] == [
        "behavior_demo/entities"
    ]
    assert (project / "behavior_demo" / "entities").is_dir()
    assert Path(result["package"]["archive_path"]).is_file()


def test_world_data_tools_read_and_safely_update_level_dat(tmp_path: Path) -> None:
    level_dat = _make_level_dat(tmp_path / "level.dat", "修改前")
    service = ProjectToolService()

    inspected = service.inspect_world_data(str(level_dat), query="LevelName")
    row = inspected["items"][0]
    complete = service.get_world_data_value(str(level_dat), str(row["token"]))
    assert complete["value"] == "修改前"
    with pytest.raises(PermissionError, match="confirm"):
        service.update_level_dat(
            str(level_dat),
            str(inspected["summary"]["fingerprint"]),
            [{"token": row["token"], "value": "修改后"}],
        )
    updated = service.update_level_dat(
        str(level_dat),
        str(inspected["summary"]["fingerprint"]),
        [{"token": row["token"], "value": "修改后"}],
        confirm=True,
    )

    assert updated["summary"]["levelName"] == "修改后"
    assert Path(updated["backup_path"]).read_bytes() != level_dat.read_bytes()


def test_world_database_tool_backs_up_and_updates_current_script_data(
    tmp_path: Path,
) -> None:
    original = _script_data_nbt(_pack(_PackedMap(((b"key", b"original"),))))
    _write_db(tmp_path / "db", _write_batch(30, (b"scriptData", original)))
    level_dat = _make_level_dat(tmp_path / "level.dat")
    service = ProjectToolService()
    inspected = service.inspect_world_data(
        str(level_dat), query="db.scriptData.key", source_kind="extraData"
    )
    summary = inspected["summary"]

    result = service.update_world_database(
        str(level_dat),
        int(summary["extraDataSequence"]),
        str(summary["extraDataFingerprint"]),
        [{"token": "extra:db.scriptData.key", "value": '"changed"'}],
        confirm=True,
    )

    assert Path(result["backup_path"]) == tmp_path / "db_old"
    assert result["summary"]["extraDataSequence"] == 31
    assert result["summary"]["extraDataFingerprint"] != hashlib.sha256(
        original
    ).hexdigest()
    current = service.get_world_data_value(
        str(level_dat), "extra:db.scriptData.key"
    )
    assert current["value"] == '"changed"'


EXPECTED_MCP_TOOL_NAMES = {
        "get_project_overview",
        "audit_project",
        "preview_cleanup",
        "clean_project",
        "rewrite_project_uuids",
        "package_project",
        "process_project",
        "inspect_world_data",
        "get_world_data_value",
        "update_level_dat",
        "update_world_database",
        "scan_global_minecraft_data",
        "clean_global_minecraft_data",
}


def _assert_mcp_tool_annotations(by_name: dict[str, object]) -> None:
    assert by_name["audit_project"].annotations.readOnlyHint is True
    assert by_name["clean_project"].annotations.destructiveHint is True
    assert by_name["inspect_world_data"].annotations.readOnlyHint is True
    assert by_name["update_level_dat"].annotations.destructiveHint is True
    assert by_name["clean_global_minecraft_data"].annotations.destructiveHint is True
    assert by_name["clean_global_minecraft_data"].annotations.idempotentHint is False


def _assert_mcp_tool_parameters(by_name: dict[str, object]) -> None:
    required = {
        name: set(tool.inputSchema.get("required", []))
        for name, tool in by_name.items()
    }
    for name in (
        "get_project_overview",
        "audit_project",
        "preview_cleanup",
        "clean_project",
        "rewrite_project_uuids",
        "package_project",
        "process_project",
    ):
        assert required[name] == {"project_path"}
    assert required["inspect_world_data"] == {"level_dat_path"}
    assert required["get_world_data_value"] == {"level_dat_path", "token"}
    assert required["update_level_dat"] == {
        "level_dat_path", "fingerprint", "changes"
    }
    assert required["update_world_database"] == {
        "level_dat_path", "expected_sequence", "expected_fingerprint", "changes"
    }
    assert required["scan_global_minecraft_data"] == set()
    assert required["clean_global_minecraft_data"] == {"category", "scan_token"}
    assert "confirm" in by_name["rewrite_project_uuids"].inputSchema["properties"]


def test_mcp_server_registers_thirteen_annotated_structured_tools(
    tmp_path: Path,
) -> None:
    project = _make_project(tmp_path / "project")
    server = create_mcp_server(ProjectToolService(), port=8766)
    tools = asyncio.run(server.list_tools())
    by_name = {tool.name: tool for tool in tools}

    assert set(by_name) == EXPECTED_MCP_TOOL_NAMES
    _assert_mcp_tool_annotations(by_name)
    _assert_mcp_tool_parameters(by_name)
    _content, structured_result = asyncio.run(
        server.call_tool("get_project_overview", {"project_path": str(project)})
    )
    assert structured_result["pack_count"] == 1


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_mcp_endpoint_accepts_only_loopback_hosts(host: str) -> None:
    assert validate_loopback_host(host) == host
    endpoint = format_endpoint(host, 8765, "/mcp")
    assert endpoint.startswith("http://")
    assert endpoint.endswith(":8765/mcp")


@pytest.mark.parametrize(
    ("host", "authority"),
    [
        ("127.0.0.2", "127.0.0.2"),
        ("localhost", "localhost"),
        ("::1", "[::1]"),
    ],
)
def test_mcp_server_enables_dns_rebinding_protection_for_every_loopback(
    host: str,
    authority: str,
) -> None:
    server = create_mcp_server(host=host, port=8766)
    security = server.settings.transport_security

    assert security is not None
    assert security.enable_dns_rebinding_protection is True
    assert security.allowed_hosts == [f"{authority}:*"]
    assert security.allowed_origins == [f"http://{authority}:*"]


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.99", "example.com"])
def test_mcp_endpoint_rejects_network_exposure(host: str) -> None:
    with pytest.raises(ValueError, match="MCP"):
        validate_loopback_host(host)


def test_mcp_endpoint_validates_port_and_path() -> None:
    with pytest.raises(ValueError, match="端口"):
        validate_port(80)
    with pytest.raises(ValueError, match="路径"):
        validate_mcp_path("https://example.com/mcp")
    with pytest.raises(ValueError, match="查询参数"):
        validate_mcp_path("/mcp?token=secret")


def test_mcp_server_command_has_no_bound_project_argument() -> None:
    program, arguments = _mcp_server_command(
        "127.0.0.1",
        8765,
        "/mcp",
    )

    assert Path(program).resolve() == Path(sys.executable).resolve()
    assert Path(arguments[1]).resolve() == ROOT / "main.py"
    assert arguments[2:] == [
        "--mcp-server",
        "--host",
        "127.0.0.1",
        "--port",
        "8765",
        "--path",
        "/mcp",
    ]


def test_backend_exposes_connection_prompt_with_actual_endpoint() -> None:
    backend = McpServerBackend(port=8766, auto_start=False)

    assert "Streamable HTTP" in backend.accessPrompt
    assert "http://127.0.0.1:8766/mcp" in backend.accessPrompt
    assert "project_path" in backend.accessPrompt
    assert "level_dat_path" in backend.accessPrompt
    assert "confirm=true" in backend.accessPrompt
    assert "confirm_protected=true" in backend.accessPrompt
    assert "scan_global_minecraft_data" in backend.accessPrompt
    assert "scan_token" in backend.accessPrompt
    assert "不得猜测 category" in backend.accessPrompt
    assert "不要假装已经接入" in backend.accessPrompt


def test_backend_copies_complete_connection_prompt(monkeypatch) -> None:
    copied: list[str] = []
    clipboard = type("Clipboard", (), {"copy": lambda _self, text: copied.append(text)})()
    monkeypatch.setattr(
        mcp_backend_module,
        "get_clipboard_helper",
        lambda: clipboard,
    )
    backend = McpServerBackend(port=8766, auto_start=False)

    backend.copyAccessPrompt()

    assert copied == [backend.accessPrompt]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_until(predicate, timeout_ms: int = 10_000) -> bool:
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(20)

    def poll() -> None:
        if predicate():
            loop.quit()

    timer.timeout.connect(poll)
    timer.start()
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    timer.stop()
    return bool(predicate())


async def _call_real_server(
    endpoint: str,
    project_path: str,
) -> tuple[set[str], dict[str, object], bool, dict[str, object]]:
    async with streamable_http_client(endpoint) as (
        read_stream,
        write_stream,
        _session_id,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            result = await session.call_tool(
                "get_project_overview",
                {"project_path": project_path},
            )
            refused_cleanup = await session.call_tool(
                "clean_project",
                {"project_path": project_path},
            )
            confirmed_cleanup = await session.call_tool(
                "clean_project",
                {"project_path": project_path, "confirm": True},
            )
            return (
                {tool.name for tool in tools.tools},
                result.structuredContent or {},
                refused_cleanup.isError,
                confirmed_cleanup.structuredContent or {},
            )


def test_qt_backend_auto_starts_serves_real_client_and_stops_with_app(
    tmp_path: Path,
) -> None:
    application = QCoreApplication.instance() or QCoreApplication([])
    assert application is not None
    project = _make_project(tmp_path / "project")
    junk = project / "behavior_demo" / "protocol-test.pyc"
    junk.write_bytes(b"junk")
    port = _free_port()
    backend = McpServerBackend(port=port)
    messages: list[tuple[str, str]] = []
    backend.logMessage.connect(lambda text, level: messages.append((text, level)))

    try:
        assert _wait_until(lambda: backend.running), messages
        tool_names, overview, refused_cleanup, confirmed_cleanup = asyncio.run(
            _call_real_server(backend.endpoint, str(project))
        )
        assert "audit_project" in tool_names
        assert overview["pack_count"] == 1
        assert refused_cleanup is True
        assert confirmed_cleanup["removed_count"] == 1
        assert not junk.exists()
    finally:
        backend._shutdown_now()
        assert _wait_until(lambda: not backend.active), messages


MCP_PAGE_PROBE_SCRIPT = r"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QObject, QUrl
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from PySide6.QtWidgets import QApplication
from prismqml import register_types
from prismqml.python.core.engine import EngineManager
from src.mcp_server_backend import McpServerBackend

app = QApplication.instance() or QApplication([])
engine = QQmlApplicationEngine()
EngineManager.set_engine(engine)
register_types(engine)
component = QQmlComponent(engine, QUrl.fromLocalFile(r'{page_path}'))
assert not component.isError(), [error.toString() for error in component.errors()]
page = component.create()
assert page is not None, [error.toString() for error in component.errors()]
backend = McpServerBackend(auto_start=False)
assert page.setProperty('backend', backend)
assert page.setProperty('width', 1100)
assert page.setProperty('height', 900)
app.processEvents()
prompt = page.findChild(QObject, 'mcpAccessPromptField')
assert prompt is not None
assert prompt.property('contentHeight') > 0
assert abs(prompt.property('height') - prompt.property('contentHeight')) < 0.01
assert page.property('endpoint').endswith('/mcp')
assert page.property('accessPrompt') == backend.accessPrompt
assert backend.endpoint in backend.accessPrompt
assert page.property('objectName') == 'mcpServerPage'
print('mcp page ok')
"""


def test_mcp_page_instantiates_with_real_backend_offscreen() -> None:
    page_path = ROOT / "qml" / "McpServerPage.qml"
    script = MCP_PAGE_PROBE_SCRIPT.format(page_path=page_path)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert "mcp page ok" in result.stdout
