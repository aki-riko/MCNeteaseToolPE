# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import asyncio

import pytest

from src.mcp_project_service import ProjectToolService
from src.mcp_server import (
    MCP_SAFETY_RULES,
    MCP_SERVER_INSTRUCTIONS,
    create_mcp_server,
)
from src.mcp_server_backend import McpServerBackend


def test_mcp_service_rejects_relative_project_and_world_paths() -> None:
    service = ProjectToolService()
    change = [{"token": "current-token", "value": "updated"}]

    with pytest.raises(ValueError, match="project_path 必须是绝对路径"):
        service.get_project_overview("relative-project")
    with pytest.raises(ValueError, match="project_path 必须是绝对路径"):
        service.clean_project("relative-project", confirm=True)
    with pytest.raises(ValueError, match="level_dat_path 必须是绝对路径"):
        service.inspect_world_data("relative-level.dat")
    with pytest.raises(ValueError, match="level_dat_path 必须是绝对路径"):
        service.get_world_data_value("relative-level.dat", "current-token")
    with pytest.raises(ValueError, match="level_dat_path 必须是绝对路径"):
        service.update_level_dat(
            "relative-level.dat", "fingerprint", change, confirm=True
        )
    with pytest.raises(ValueError, match="level_dat_path 必须是绝对路径"):
        service.update_world_database(
            "relative-level.dat", 1, "fingerprint", change, confirm=True
        )


def test_mcp_prompt_layers_share_complete_safety_rules() -> None:
    server = create_mcp_server(port=8766)
    access_prompt = McpServerBackend(port=8766, auto_start=False).accessPrompt

    assert server.instructions == MCP_SERVER_INSTRUCTIONS
    for rule in MCP_SAFETY_RULES:
        assert rule in server.instructions
        assert rule in access_prompt
    assert "不要假装已经接入" in access_prompt


def test_mcp_tool_descriptions_are_self_contained() -> None:
    tools = asyncio.run(create_mcp_server(port=8766).list_tools())
    by_name = {tool.name: tool for tool in tools}
    for name in (
        "get_project_overview",
        "audit_project",
        "preview_cleanup",
        "clean_project",
        "rewrite_project_uuids",
        "package_project",
        "process_project",
    ):
        assert "绝对 project_path" in by_name[name].description
    assert "一次性 scan_token" in by_name["scan_global_minecraft_data"].description
    assert "recommended_category" in by_name["scan_global_minecraft_data"].description
    assert "confirm=true" in by_name["clean_global_minecraft_data"].description
    assert "confirm_protected=true" in by_name["clean_global_minecraft_data"].description
    assert "fingerprint=最新 summary.fingerprint" in by_name["update_level_dat"].description
    database_description = by_name["update_world_database"].description
    assert "expected_sequence=summary.extraDataSequence" in database_description
    assert "expected_fingerprint=summary.extraDataFingerprint" in database_description
