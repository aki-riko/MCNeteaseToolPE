# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
# 我的世界中国版打包工具 (Python + PrismQML)
# Netease Minecraft packaging tool, Python rewrite atop PrismQML.

"""Application entry. 应用入口。

装配窗口与五个页面(工程处理 / NBT / 缓存清理 / MCP / 设置),
复用 PrismQML 的 Bar 窗口与导航。
"""

import os
import sys

from prismqml import App, WindowType
from prismqml.python.core import (
    NotificationPosition,
    showDesktopError,
    showDesktopSuccess,
)
from prismqml.python.window.async_qml_page import AsyncQmlPage

from src.audit_cli import run_audit_cli
from src.backends import ProjectBackend
from src.config import (
    APP_TITLE,
    APP_VERSION,
    INSTALLER_SILENT_ARGS,
    PRISMQML_HOMEPAGE,
    PROJECT_HOMEPAGE,
    UPDATE_ASSET_KEYWORD,
    UPDATE_REPO,
)
from src.minecraft_cleanup_qt_backend import MinecraftCleanupBackend
from src.level_dat_backend import LevelDatBackend
from src.mcp_server import MCP_SERVER_FLAG
from src.mcp_server_backend import McpServerBackend
from src.settings_backend import ApplicationSettingsBackend

# 窗口尺寸；版本与更新配置集中在 src/config.py，可由环境变量覆盖。
WINDOW_W = 1000
WINDOW_H = 720

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_QML_DIR = os.path.join(_PROJECT_ROOT, "qml")
_APP_ICON = os.path.join(_PROJECT_ROOT, "assets", "app_icon.png")


def _page_factory(name, backend=None):
    """Build a factory that loads an app QML page by file name.
    构造按文件名加载应用 QML 页面的工厂(供 addPage 延迟实例化)。"""
    path = os.path.join(_QML_DIR, name)
    if backend is None:
        return lambda: AsyncQmlPage(path)
    return lambda: AsyncQmlPage(path, backend=backend)


def _notify_audit_finished(
    passed: bool,
    errors: int,
    warnings: int,
    _issues: list[dict[str, object]],
) -> None:
    """Show the PrismQML desktop toast when an audit settles."""

    message = f"{errors} 个错误，{warnings} 个警告"
    if passed:
        showDesktopSuccess(
            "审核通过",
            message,
            position=NotificationPosition.BottomRight,
        )
        return
    showDesktopError(
        "审核未通过",
        message,
        position=NotificationPosition.BottomRight,
    )


def main() -> int:
    if sys.argv[1:2] == [MCP_SERVER_FLAG]:
        from src.mcp_server import run_mcp_server_cli

        return run_mcp_server_cli(sys.argv[2:])

    cli_status = run_audit_cli(sys.argv[1:])
    if cli_status is not None:
        return cli_status

    App.setApplicationName(APP_TITLE)
    app = App(application_icon=_APP_ICON)
    app.enable_auto_update(UPDATE_REPO, APP_VERSION, UPDATE_ASSET_KEYWORD)
    # Python 引擎只自动注入 appUpdater；安装参数属于应用配置，由宿主显式提供。
    app.engine.rootContext().setContextProperty("appInstallerSilentArgs", INSTALLER_SILENT_ARGS)
    app.engine.rootContext().setContextProperty("appProjectHomepage", PROJECT_HOMEPAGE)
    app.engine.rootContext().setContextProperty("prismQmlHomepage", PRISMQML_HOMEPAGE)

    win = app.create_window(WindowType.BAR)
    win.setWindowTitle(APP_TITLE)
    win.resize(WINDOW_W, WINDOW_H)

    # 三项工程能力共享一个顶级页面与目录选择，子后端仍保持职责隔离。
    settings_backend = ApplicationSettingsBackend()
    project_backend = ProjectBackend(settings_backend=settings_backend)
    level_dat_backend = LevelDatBackend(settings_backend=settings_backend)
    minecraft_cleanup_backend = MinecraftCleanupBackend()
    mcp_server_backend = McpServerBackend()
    project_backend.auditBackend.finished.connect(_notify_audit_finished)
    win.addPage(
        _page_factory("ProjectPage.qml", project_backend),
        "AppsListDetail",
        "工程处理",
        position="top",
    )
    win.addPage(
        _page_factory("LevelDatPage.qml", level_dat_backend),
        "DocumentData",
        "NBT",
        position="top",
    )
    win.addPage(
        _page_factory("MinecraftCleanupPage.qml", minecraft_cleanup_backend),
        "Delete",
        "缓存清理",
        position="top",
    )

    # 底部 MCP 服务器与设置
    win.addPage(
        _page_factory("McpServerPage.qml", mcp_server_backend),
        "DeveloperBoard",
        "MCP",
        position="bottom",
    )
    win.addPage(
        _page_factory("SettingsPage.qml", settings_backend),
        "Settings",
        "设置",
        position="bottom",
    )

    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
