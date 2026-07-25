# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
# 网易打包审核错误码的用户可读名称。
# User-facing names for Netease packaging audit codes.

from __future__ import annotations


def code_name(code: int) -> str:
    """Return the user-facing name for a Netease error code."""

    names = {
        6: "DirError 目录组织错误",
        10: "NoManifestError 缺少 manifest",
        16: "FileOrPathNameError 文件名非法",
        18: "CodeReviewError 代码审核",
        20: "FindBehaviorAndResourceError 目录命名冲突",
        24: "ResourcePackUnvalid 包结构非法",
        25: "TexturesListLoadError json 加载失败",
        27: "NameOverSizeError 文件名过长",
        35: "CodeExceptionError 命名连续重复字符",
        36: "McpFileError 含 .MCP 文件",
        37: "ManifestJsonError min_engine_version 缺失/过低",
        38: "MakeBehaviourPackJsonError manifest 含注释/非 UTF-8",
        40: "InvalidJsonDataError json 非 UTF-8",
    }
    return names.get(code, "静态检查")


__all__ = ["code_name"]
