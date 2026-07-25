# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
# 应用配置集中处；环境变量可覆盖打包/部署时的值。
# Central application configuration; environment variables may override build values.
"""应用运行时与构建配置。"""

from __future__ import annotations

import logging
import os


LOGGER = logging.getLogger(__name__)


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value else default


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    value = os.getenv(name)
    try:
        parsed = int(value) if value else default
    except ValueError:
        LOGGER.warning("环境变量 %s 不是有效整数，使用默认值", name)
        return default
    return max(minimum, min(parsed, maximum))


APP_TITLE = _env("MCNETEASE_APP_TITLE", "我的世界中国版打包工具")
APP_VERSION = _env("MCNETEASE_APP_VERSION", "v0.1.0.1")
UPDATE_REPO = _env("MCNETEASE_UPDATE_REPO", "aki-riko/MCNeteaseToolPE")
UPDATE_ASSET_KEYWORD = _env("MCNETEASE_UPDATE_ASSET_KEYWORD", "Setup")
PROJECT_HOMEPAGE = _env(
    "MCNETEASE_PROJECT_HOMEPAGE",
    f"https://github.com/{UPDATE_REPO}",
)
PRISMQML_HOMEPAGE = _env(
    "MCNETEASE_PRISMQML_HOMEPAGE",
    "https://github.com/aki-riko/PrismQML",
)
INSTALLER_SILENT_ARGS = _env(
    "MCNETEASE_INSTALLER_SILENT_ARGS",
    "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS",
)
ZIP_COMPRESSION_LEVEL = _env_int("MCNETEASE_ZIP_COMPRESSION_LEVEL", 6, 0, 9)
MCP_PORT_MIN = 1024
MCP_PORT_MAX = 65535
MCP_HOST = _env("MCNETEASE_MCP_HOST", "127.0.0.1").strip()
MCP_PORT = _env_int("MCNETEASE_MCP_PORT", 8765, MCP_PORT_MIN, MCP_PORT_MAX)
MCP_PATH = _env("MCNETEASE_MCP_PATH", "/mcp").strip()
MCP_STOP_TIMEOUT_MS = _env_int("MCNETEASE_MCP_STOP_TIMEOUT_MS", 2000, 100, 10_000)
LEVEL_DAT_MAX_BYTES = _env_int(
    "MCNETEASE_LEVEL_DAT_MAX_BYTES",
    32 * 1024 * 1024,
    1024,
    512 * 1024 * 1024,
)
LEVEL_DAT_MAX_DEPTH = _env_int("MCNETEASE_LEVEL_DAT_MAX_DEPTH", 64, 8, 512)
LEVEL_DAT_MAX_COLLECTION_ITEMS = _env_int(
    "MCNETEASE_LEVEL_DAT_MAX_COLLECTION_ITEMS",
    100_000,
    1,
    1_000_000,
)
LEVEL_DAT_BACKUP_SUFFIX = "_old"
LEVEL_DB_BACKUP_SUFFIX = _env("MCNETEASE_LEVEL_DB_BACKUP_SUFFIX", "_old")
LEVEL_DB_MAX_MANIFEST_BYTES = _env_int(
    "MCNETEASE_LEVEL_DB_MAX_MANIFEST_BYTES",
    64 * 1024 * 1024,
    1024,
    512 * 1024 * 1024,
)
LEVEL_DB_MAX_LOG_BYTES = _env_int(
    "MCNETEASE_LEVEL_DB_MAX_LOG_BYTES",
    512 * 1024 * 1024,
    1024,
    2 * 1024 * 1024 * 1024,
)
LEVEL_DB_MAX_TABLE_BYTES = _env_int(
    "MCNETEASE_LEVEL_DB_MAX_TABLE_BYTES",
    512 * 1024 * 1024,
    1024,
    2 * 1024 * 1024 * 1024,
)
LEVEL_DB_MAX_BLOCK_BYTES = _env_int(
    "MCNETEASE_LEVEL_DB_MAX_BLOCK_BYTES",
    64 * 1024 * 1024,
    1024,
    512 * 1024 * 1024,
)
LEVEL_DB_MAX_SCRIPT_BYTES = _env_int(
    "MCNETEASE_LEVEL_DB_MAX_SCRIPT_BYTES",
    64 * 1024 * 1024,
    1024,
    512 * 1024 * 1024,
)
LEVEL_DB_MAX_MESSAGEPACK_ITEMS = _env_int(
    "MCNETEASE_LEVEL_DB_MAX_MESSAGEPACK_ITEMS",
    1_000_000,
    1_000,
    10_000_000,
)
LEVEL_DB_MAX_TABLES = _env_int(
    "MCNETEASE_LEVEL_DB_MAX_TABLES",
    10_000,
    1,
    100_000,
)
LEVEL_DB_MAX_VIEW_ROWS = _env_int(
    "MCNETEASE_LEVEL_DB_MAX_VIEW_ROWS",
    100_000,
    100,
    1_000_000,
)
LEVEL_DB_VALUE_PREVIEW_CHARS = _env_int(
    "MCNETEASE_LEVEL_DB_VALUE_PREVIEW_CHARS",
    8 * 1024,
    512,
    1024 * 1024,
)

__all__ = [
    "APP_TITLE",
    "APP_VERSION",
    "UPDATE_REPO",
    "UPDATE_ASSET_KEYWORD",
    "PROJECT_HOMEPAGE",
    "PRISMQML_HOMEPAGE",
    "INSTALLER_SILENT_ARGS",
    "ZIP_COMPRESSION_LEVEL",
    "MCP_HOST",
    "MCP_PORT",
    "MCP_PATH",
    "MCP_PORT_MIN",
    "MCP_PORT_MAX",
    "MCP_STOP_TIMEOUT_MS",
    "LEVEL_DAT_MAX_BYTES",
    "LEVEL_DAT_MAX_DEPTH",
    "LEVEL_DAT_MAX_COLLECTION_ITEMS",
    "LEVEL_DAT_BACKUP_SUFFIX",
    "LEVEL_DB_BACKUP_SUFFIX",
    "LEVEL_DB_MAX_MANIFEST_BYTES",
    "LEVEL_DB_MAX_LOG_BYTES",
    "LEVEL_DB_MAX_TABLE_BYTES",
    "LEVEL_DB_MAX_BLOCK_BYTES",
    "LEVEL_DB_MAX_SCRIPT_BYTES",
    "LEVEL_DB_MAX_MESSAGEPACK_ITEMS",
    "LEVEL_DB_MAX_TABLES",
    "LEVEL_DB_MAX_VIEW_ROWS",
    "LEVEL_DB_VALUE_PREVIEW_CHARS",
]
