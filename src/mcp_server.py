# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later

"""Official-SDK Streamable HTTP MCP server with path-driven tools."""

from __future__ import annotations

import argparse
import ipaddress
import json
import logging
from urllib.parse import urlsplit

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from .config import (
    APP_TITLE,
    MCP_HOST,
    MCP_PATH,
    MCP_PORT,
    MCP_PORT_MAX,
    MCP_PORT_MIN,
)
from .mcp_project_service import ProjectToolService


LOGGER = logging.getLogger(__name__)
MCP_SERVER_FLAG = "--mcp-server"
LOOPBACK_HOSTNAMES = frozenset({"localhost"})
MCP_PATH_RULE = (
    "每次调用的 project_path 或 level_dat_path 只能取自用户提示词、已确认的对话上下文，"
    "或客户端明确标注且用户已确认的工作区绝对路径；必须传绝对路径，不得绑定固定目录、"
    "猜测路径或把相对路径按服务器工作目录解析。缺少绝对路径时先询问用户。"
)
MCP_WRITE_CONFIRMATION_RULE = (
    "调用 destructiveHint=true 的工具前，必须确认用户已明确同意本次具体写入；"
    "仅在确认后传 confirm=true。"
)
MCP_GLOBAL_CLEANUP_RULE = (
    "全局清理使用服务器已配置的 Minecraft 数据目录，不接收或猜测路径。调用 "
    "clean_global_minecraft_data 前必须先调用 scan_global_minecraft_data，向用户说明真实分类、大小和"
    "文件数；不得猜测 category，category 只能使用扫描返回的 key 或 recommended_category，并原样传回 scan_token。"
    "scan_token 仅可使用一次，数据变化或令牌已使用时必须重新扫描；清理保护分类还必须确认用户同意，"
    "再传 confirm_protected=true。"
)
MCP_WORLD_UPDATE_RULE = (
    "修改世界数据前必须重新调用 inspect_world_data；若 value_truncated=true，先用 "
    "get_world_data_value 读取完整值。update_level_dat 的 fingerprint 必须取自最新 "
    "summary.fingerprint；update_world_database 的 expected_sequence 和 expected_fingerprint 必须分别取自"
    "最新 summary.extraDataSequence 和 summary.extraDataFingerprint；changes 只能使用本次读取的 token，"
    "不得复用旧值。"
)
MCP_SAFETY_RULES = (
    MCP_PATH_RULE,
    MCP_WRITE_CONFIRMATION_RULE,
    MCP_GLOBAL_CLEANUP_RULE,
    MCP_WORLD_UPDATE_RULE,
)
MCP_SERVER_INSTRUCTIONS = "\n".join(MCP_SAFETY_RULES)


def validate_loopback_host(host: str) -> str:
    """Reject network exposure; this desktop integration is local-only."""

    normalized = host.strip().lower()
    if normalized in LOOPBACK_HOSTNAMES:
        return normalized
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError as error:
        raise ValueError("MCP 主机必须是 localhost 或回环 IP") from error
    if not address.is_loopback:
        raise ValueError("MCP 服务器仅允许监听本机回环地址")
    return normalized


def validate_port(port: int) -> int:
    if port < MCP_PORT_MIN or port > MCP_PORT_MAX:
        raise ValueError(f"MCP 端口必须在 {MCP_PORT_MIN}-{MCP_PORT_MAX} 之间")
    return port


def validate_mcp_path(path: str) -> str:
    parsed = urlsplit(path.strip())
    if not parsed.path.startswith("/") or parsed.scheme or parsed.netloc:
        raise ValueError("MCP 路径必须是以 / 开头的本地 URL 路径")
    if parsed.query or parsed.fragment or parsed.path != path.strip():
        raise ValueError("MCP 路径不能包含查询参数或片段")
    return parsed.path


def _http_host(host: str) -> str:
    return f"[{host}]" if ":" in host else host


def _transport_security(host: str) -> TransportSecuritySettings:
    """Enable SDK Host/Origin validation for every accepted loopback IP."""

    http_host = _http_host(host)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[f"{http_host}:*"],
        allowed_origins=[f"http://{http_host}:*"],
    )


def format_endpoint(host: str, port: int, path: str) -> str:
    normalized_host = validate_loopback_host(host)
    normalized_port = validate_port(port)
    normalized_path = validate_mcp_path(path)
    display_host = _http_host(normalized_host)
    return f"http://{display_host}:{normalized_port}{normalized_path}"


def _read_annotations(title: str) -> ToolAnnotations:
    return ToolAnnotations(
        title=title,
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )


def _write_annotations(title: str, *, idempotent: bool) -> ToolAnnotations:
    return ToolAnnotations(
        title=title,
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=idempotent,
        openWorldHint=False,
    )


def _project_read_tool_registrations(
    service: ProjectToolService,
) -> tuple[tuple[object, ...], ...]:
    return (
        (
            service.get_project_overview,
            "get_project_overview",
            "读取绝对 project_path 指定的工程概况",
            _read_annotations("读取工程概况"),
        ),
        (
            service.audit_project,
            "audit_project",
            "审核绝对 project_path 指定的工程目录",
            _read_annotations("执行打包审核"),
        ),
        (
            service.preview_cleanup,
            "preview_cleanup",
            "预览绝对 project_path 指定目录的垃圾项",
            _read_annotations("预览垃圾清理"),
        ),
    )


def _project_write_tool_registrations(
    service: ProjectToolService,
) -> tuple[tuple[object, ...], ...]:
    return (
        (
            service.clean_project,
            "clean_project",
            "清理绝对 project_path 指定目录；必须传入 confirm=true",
            _write_annotations("清理工程", idempotent=True),
        ),
        (
            service.rewrite_project_uuids,
            "rewrite_project_uuids",
            "重写绝对 project_path 指定目录的 UUID；必须传入 confirm=true",
            _write_annotations("重写 UUID", idempotent=False),
        ),
        (
            service.package_project,
            "package_project",
            "为绝对 project_path 指定目录输出 ZIP；必须传入 confirm=true",
            _write_annotations("输出 ZIP", idempotent=False),
        ),
        (
            service.process_project,
            "process_project",
            "按清理、审核、UUID、ZIP 顺序处理绝对 project_path；必须传入 confirm=true",
            _write_annotations("一键处理并审核", idempotent=False),
        ),
    )


def _project_tool_registrations(
    service: ProjectToolService,
) -> tuple[tuple[object, ...], ...]:
    return (
        *_project_read_tool_registrations(service),
        *_project_write_tool_registrations(service),
    )


def _world_tool_registrations(
    service: ProjectToolService,
) -> tuple[tuple[object, ...], ...]:
    return (
        (
            service.inspect_world_data,
            "inspect_world_data",
            "读取并搜索绝对 level_dat_path 及同世界当前有效的 scriptData",
            _read_annotations("读取世界存档数据"),
        ),
        (
            service.get_world_data_value,
            "get_world_data_value",
            "按绝对 level_dat_path 的最新 inspect_world_data token 读取完整当前值",
            _read_annotations("读取完整世界数据值"),
        ),
        (
            service.update_level_dat,
            "update_level_dat",
            "绝对 level_dat_path；fingerprint=最新 summary.fingerprint；必须传 confirm=true",
            _write_annotations("保存 level.dat", idempotent=False),
        ),
        (
            service.update_world_database,
            "update_world_database",
            "绝对 level_dat_path；expected_sequence=summary.extraDataSequence，"
            "expected_fingerprint=summary.extraDataFingerprint；必须传 confirm=true",
            _write_annotations("保存世界数据库", idempotent=False),
        ),
    )


def _global_cleanup_tool_registrations(
    service: ProjectToolService,
) -> tuple[tuple[object, ...], ...]:
    return (
        (
            service.scan_global_minecraft_data,
            "scan_global_minecraft_data",
            "扫描全局数据并返回一次性 scan_token、recommended_category 和分类 key",
            _read_annotations("扫描全局缓存"),
        ),
        (
            service.clean_global_minecraft_data,
            "clean_global_minecraft_data",
            "用一次性 scan_token 清理扫描分类；confirm=true，保护分类还需 confirm_protected=true",
            _write_annotations("清理全局数据", idempotent=False),
        ),
    )


def _tool_registrations(service: ProjectToolService) -> tuple[tuple[object, ...], ...]:
    return (
        *_project_tool_registrations(service),
        *_world_tool_registrations(service),
        *_global_cleanup_tool_registrations(service),
    )


def _register_tools(server: FastMCP, service: ProjectToolService) -> None:
    for function, name, description, annotations in _tool_registrations(service):
        server.add_tool(
            function,
            name=name,
            description=description,
            annotations=annotations,
            structured_output=True,
        )


def create_mcp_server(
    service: ProjectToolService | None = None,
    host: str = MCP_HOST,
    port: int = MCP_PORT,
    path: str = MCP_PATH,
) -> FastMCP:
    """Create one stateless server whose calls carry their required inputs."""

    normalized_host = validate_loopback_host(host)
    normalized_port = validate_port(port)
    normalized_path = validate_mcp_path(path)
    server = FastMCP(
        APP_TITLE,
        instructions=MCP_SERVER_INSTRUCTIONS,
        host=normalized_host,
        port=normalized_port,
        streamable_http_path=normalized_path,
        json_response=True,
        stateless_http=True,
        transport_security=_transport_security(normalized_host),
    )
    _register_tools(server, service or ProjectToolService())
    return server


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MCNeteaseToolPE MCP server")
    parser.add_argument("--host", default=MCP_HOST)
    parser.add_argument("--port", type=int, default=MCP_PORT)
    parser.add_argument("--path", default=MCP_PATH)
    return parser


def run_mcp_server_cli(arguments: list[str]) -> int:
    """Run the server in the current process until its host terminates it."""

    options = _parser().parse_args(arguments)
    endpoint = format_endpoint(options.host, options.port, options.path)
    server = create_mcp_server(
        host=options.host,
        port=options.port,
        path=options.path,
    )
    print(json.dumps({"event": "starting", "endpoint": endpoint}, ensure_ascii=False), flush=True)
    try:
        server.run(transport="streamable-http")
    except Exception:
        LOGGER.exception("MCP 服务器运行失败：%s", endpoint)
        return 1
    return 0


__all__ = [
    "MCP_GLOBAL_CLEANUP_RULE",
    "MCP_PATH_RULE",
    "MCP_SAFETY_RULES",
    "MCP_SERVER_FLAG",
    "MCP_SERVER_INSTRUCTIONS",
    "MCP_WORLD_UPDATE_RULE",
    "MCP_WRITE_CONFIRMATION_RULE",
    "create_mcp_server",
    "format_endpoint",
    "run_mcp_server_cli",
    "validate_loopback_host",
    "validate_mcp_path",
    "validate_port",
]
