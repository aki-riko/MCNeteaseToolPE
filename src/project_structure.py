# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""网易 Minecraft 工程结构识别。"""

from __future__ import annotations

import os
from pathlib import Path


MAP_MARKER_FILE_NAME = "level.dat"
PROJECT_KIND_ADDONS = "addons"
PROJECT_KIND_MAP = "map"


def is_map_project(root: str | os.PathLike[str]) -> bool:
    """根目录存在 level.dat 时按完整地图工程处理。"""

    return (Path(root).expanduser().resolve() / MAP_MARKER_FILE_NAME).is_file()


def classify_project(root: str | os.PathLike[str]) -> str:
    """返回供界面展示的工程类型；无效目录不显示类型。"""

    project_root = Path(root).expanduser().resolve()
    if not project_root.is_dir():
        return ""
    return PROJECT_KIND_MAP if is_map_project(project_root) else PROJECT_KIND_ADDONS
