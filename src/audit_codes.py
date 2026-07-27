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
        12: "NoLevelError 缺少地图数据",
        13: "HasLevelError 不应包含地图数据",
        16: "FileOrPathNameError 文件名非法",
        18: "CodeReviewError 代码审核",
        20: "FindBehaviorAndResourceError 目录命名冲突",
        23: "WriteLevelDatError 地图数据无法写入",
        24: "ResourcePackUnvalid 包结构非法",
        25: "TexturesListLoadError json 加载失败",
        26: "TexturesSizeError 贴图尺寸过大",
        27: "NameOverSizeError 文件名过长",
        29: "PlayerEntityJsonReviewError 玩家实体配置错误",
        30: "ReadLevelDataError 地图数据读取失败",
        31: "MapItemVersionError 地图版本过高",
        33: "AudioReviewError 音效审核",
        34: "GlyphReviewError 位图字体审核",
        35: "CodeExceptionError 命名连续重复字符",
        36: "McpFileError 含 .MCP 文件",
        37: "ManifestJsonError min_engine_version 缺失/过低",
        38: "MakeBehaviourPackJsonError manifest 含注释/非 UTF-8",
        40: "InvalidJsonDataError json 非 UTF-8",
    }
    return names.get(code, "静态检查")


__all__ = ["code_name"]
