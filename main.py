# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
# 我的世界中国版打包工具 (Python + PrismQML)
# Netease Minecraft packaging tool, Python rewrite atop PrismQML.

"""Application entry. 应用入口。

装配窗口与七个页面(工程处理 / 阻塞项修复 / NBT / 性能诊断 / 缓存清理 / MCP / 设置),
复用 PrismQML 的 Bar 窗口与导航。
"""

import logging
import os
import sys

from prismqml import (
    App,
    SystemTrayIcon,
    Window,
    WindowCloseEvent,
    WindowType,
)
from prismqml.python.runtime import (
    NotificationPosition,
    showDesktopError,
    showDesktopSuccess,
)
from prismqml.python.window.async_qml_page import AsyncQmlPage
from prismqml.python.window.tray_types import ActivationReason

from src.audit_cli import run_audit_cli
from src.backends import ProjectBackend
from src.blocking_repair_backend import BlockingRepairBackend
from src.config import (
    APP_TITLE,
    APP_VERSION,
    INSTALLER_SILENT_ARGS,
    PRISMQML_HOMEPAGE,
    PROJECT_HOMEPAGE,
    SPLASH_SUBTITLE,
    UPDATE_ASSET_KEYWORD,
    UPDATE_REPO,
)
from src.minecraft_cleanup_qt_backend import MinecraftCleanupBackend
from src.level_dat_backend import LevelDatBackend
from src.mcp_server import MCP_SERVER_FLAG
from src.mcp_server_backend import McpServerBackend
from src.performance_backend import PerformanceBackend
from src.settings_backend import (
    CLOSE_ACTION_QUIT,
    ApplicationSettingsBackend,
    ensure_mica_default_enabled,
    resolve_prismqml_config_path,
)

# 窗口尺寸；版本与更新配置集中在 src/config.py，可由环境变量覆盖。
WINDOW_W = 1000
WINDOW_H = 720

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_QML_DIR = os.path.join(_PROJECT_ROOT, "qml")
_APP_ICON = os.path.join(_PROJECT_ROOT, "assets", "app_icon.png")

LOGGER = logging.getLogger(__name__)


def _move_close_request_to_tray(
    window: Window,
    tray_icon: SystemTrayIcon | None,
    event: WindowCloseEvent,
) -> bool:
    """Hide an app window when its tray icon is active."""

    if tray_icon is None or not tray_icon.isVisible():
        return False
    # 请求引擎播完关闭动画后隐藏, 而不是窗口直接消失。
    # 由引擎在动画收尾时执行隐藏, 这里不能提前调 window.hide()。
    event.requestHideOnClose()
    return True


class _CloseActionController:
    """决定关闭请求走向: 隐藏到托盘, 或带关闭动画退出进程。"""

    def __init__(self) -> None:
        self.tray_icon: SystemTrayIcon | None = None
        self.close_to_tray = True

    def closeEvent(
        self,
        window: Window,
        event: WindowCloseEvent,
        super_close_event,
    ) -> bool:
        """处理关闭请求; 返回 True 表示已转为隐藏到托盘。"""

        if self.close_to_tray and _move_close_request_to_tray(
            window, self.tray_icon, event
        ):
            return True
        # 退出必须走已接受关闭: QML 在本处理器返回后才播放收缩动画, 动画
        # 收尾 window.close() 后由 quitOnLastWindowClosed 退出进程。这里若
        # 同步调 app.quit() 会在动画开始前杀死事件循环, 窗口瞬间消失。
        super_close_event(event)
        return False


class MainWindow(Window):
    """Main window whose close button hides it to the tray or quits by setting."""

    def __init__(self, window_type: int = WindowType.BAR) -> None:
        super().__init__(window_type=window_type)
        self._close_controller = _CloseActionController()

    def enableCloseToTray(self, tray_icon: SystemTrayIcon) -> None:
        self._close_controller.tray_icon = tray_icon

    def setCloseToTray(self, enabled: bool) -> None:
        self._close_controller.close_to_tray = enabled

    def closeEvent(self, event: WindowCloseEvent) -> None:
        self._close_controller.closeEvent(self, event, super().closeEvent)


def _show_main_window(window: Window) -> None:
    window.show()
    window.raise_()
    window.activateWindow()


def _restore_window_from_tray(reason: int, window: Window) -> None:
    if reason in (
        ActivationReason.Trigger.value,
        ActivationReason.DoubleClick.value,
    ):
        _show_main_window(window)


def _create_main_window(app: App) -> MainWindow:
    """Create an App-owned main window with the shared application icon."""

    window = MainWindow(WindowType.BAR)
    if app.application_icon:
        window.setWindowIcon(app.application_icon, app.application_icon_colored)
    app.windows.append(window)
    return window


def _configure_splash(window: MainWindow) -> None:
    """Apply explicit branding instead of relying on empty Splash defaults."""

    window.showSplash(
        icon=_APP_ICON,
        title=APP_TITLE,
        subtitle=SPLASH_SUBTITLE,
    )


def _build_system_tray(app: App, window: MainWindow) -> SystemTrayIcon:
    """Build the PrismQML tray icon, menu, and activation behavior."""

    tray_icon = SystemTrayIcon(
        icon=window.windowIcon(),
        parent=window,
        toolTip=APP_TITLE,
        menuOnLeftClick=False,
    )
    tray_icon.addAction(
        "显示主窗口",
        actionId="show-main-window",
        triggered=lambda: _show_main_window(window),
    )
    tray_icon.addSeparator()
    tray_icon.addAction(
        "退出",
        actionId="quit-application",
        triggered=app.quit,
    )
    tray_icon.activated.connect(
        lambda reason: _restore_window_from_tray(reason, window)
    )
    return tray_icon


def _enable_system_tray(app: App, window: MainWindow) -> SystemTrayIcon | None:
    """Enable the tray when supported, preserving normal exit otherwise."""

    if not SystemTrayIcon.isSystemTrayAvailable():
        LOGGER.warning("系统托盘不可用；关闭主窗口将正常退出应用")
        return None

    tray_icon = _build_system_tray(app, window)
    tray_icon.show()

    window.enableCloseToTray(tray_icon)
    app.setQuitOnLastWindowClosed(False)
    return tray_icon


def _page_factory(name, backend=None):
    """Build a factory that loads an app QML page by file name.
    构造按文件名加载应用 QML 页面的工厂(供 addPage 延迟实例化)。"""
    path = os.path.join(_QML_DIR, name)
    if backend is None:
        return lambda: AsyncQmlPage(path)
    return lambda: AsyncQmlPage(path, backend=backend)


def _route_project_blockers(
    window: Window,
    repair_backend: BlockingRepairBackend,
    repair_page_index: int,
    project_dir: str,
    issues: list[dict[str, object]],
) -> None:
    """将同一次工程审核的真实阻塞项同步到修复页并异步切页。"""

    repair_backend.adoptAuditResult(project_dir, issues)
    window.setCurrentIndex(repair_page_index)


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

    # FastSplash 在 App 创建阶段读取 display name，提前发布品牌信息。
    App.setApplicationDisplayName(APP_TITLE)
    app = App(
        application_icon=_APP_ICON,
        splash_subtitle=SPLASH_SUBTITLE,
        window_width=WINDOW_W,
        window_height=WINDOW_H,
        config_path=resolve_prismqml_config_path(),
        persist_appearance=True,
    )
    app.enable_auto_update(UPDATE_REPO, APP_VERSION, UPDATE_ASSET_KEYWORD)
    # 引擎默认关闭云母；首次运行(或旧配置未写过该键)时默认开启。
    ensure_mica_default_enabled(resolve_prismqml_config_path())
    # Python 引擎只自动注入 appUpdater；安装参数属于应用配置，由宿主显式提供。
    app.engine.rootContext().setContextProperty("appInstallerSilentArgs", INSTALLER_SILENT_ARGS)
    app.engine.rootContext().setContextProperty("appProjectHomepage", PROJECT_HOMEPAGE)
    app.engine.rootContext().setContextProperty("prismQmlHomepage", PRISMQML_HOMEPAGE)

    win = _create_main_window(app)
    win.setWindowTitle(APP_TITLE)
    _configure_splash(win)

    # 三项工程能力共享一个顶级页面与目录选择，子后端仍保持职责隔离。
    settings_backend = ApplicationSettingsBackend()
    project_backend = ProjectBackend(settings_backend=settings_backend)
    blocking_repair_backend = BlockingRepairBackend()
    level_dat_backend = LevelDatBackend(settings_backend=settings_backend)
    performance_backend = PerformanceBackend()
    minecraft_cleanup_backend = MinecraftCleanupBackend()
    mcp_server_backend = McpServerBackend()
    project_backend.auditBackend.finished.connect(_notify_audit_finished)
    win.addPage(
        _page_factory("ProjectPage.qml", project_backend),
        "AppsListDetail",
        "工程处理",
        position="top",
    )
    blocking_repair_page_index = win.addPage(
        _page_factory("BlockingRepairPage.qml", blocking_repair_backend),
        "WrenchScrewdriver",
        "阻塞项修复",
        position="top",
    )

    project_backend.blockingIssuesReady.connect(
        lambda project_dir, issues: _route_project_blockers(
            win,
            blocking_repair_backend,
            blocking_repair_page_index,
            project_dir,
            issues,
        )
    )
    win.addPage(
        _page_factory("LevelDatPage.qml", level_dat_backend),
        "DocumentData",
        "NBT",
        position="top",
    )
    win.addPage(
        _page_factory("PerformancePage.qml", performance_backend),
        "PulseSquare",
        "性能诊断",
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

    # 托盘必须在主窗口可关闭前完成装配，避免关闭后留下无入口的后台进程。
    tray_icon = _enable_system_tray(app, win)

    def apply_close_action() -> None:
        quit_on_close = settings_backend.closeAction == CLOSE_ACTION_QUIT
        win.setCloseToTray(not quit_on_close)
        if tray_icon is not None:
            # 退出模式交还 Qt 默认行为: 引擎播完关闭动画、真正关窗后由
            # lastWindowClosed 退出进程。托盘模式必须禁用, 否则普通关闭
            # (如托盘失效兜底)也会直接退出。
            app.setQuitOnLastWindowClosed(quit_on_close)

    apply_close_action()
    settings_backend.closeActionChanged.connect(apply_close_action)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
