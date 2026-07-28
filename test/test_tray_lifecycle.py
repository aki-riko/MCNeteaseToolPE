# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""System tray and close-to-tray lifecycle regression tests."""

from __future__ import annotations

from prismqml import ActivationReason

import main


class _FakeEvent:
    def __init__(self) -> None:
        self.ignored = False

    def ignore(self) -> None:
        self.ignored = True


class _FakeWindow:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.tray_icon = None

    def hide(self) -> None:
        self.calls.append("hide")

    def show(self) -> None:
        self.calls.append("show")

    def raise_(self) -> None:
        self.calls.append("raise")

    def activateWindow(self) -> None:
        self.calls.append("activate")

    def windowIcon(self) -> str:
        return "app-icon"

    def enableCloseToTray(self, tray_icon) -> None:
        self.tray_icon = tray_icon


class _FakeTray:
    available = True

    @classmethod
    def isSystemTrayAvailable(cls) -> bool:
        return cls.available

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.actions: list[dict[str, object]] = []
        self.activated_callbacks = []
        self.visible = False
        self.activated = self

    def connect(self, callback) -> None:
        self.activated_callbacks.append(callback)

    def addAction(self, text: str, **kwargs) -> None:
        self.actions.append({"text": text, **kwargs})

    def addSeparator(self) -> None:
        self.actions.append({"separator": True})

    def show(self) -> None:
        self.visible = True

    def isVisible(self) -> bool:
        return self.visible


class _FakeApp:
    def __init__(self) -> None:
        self.quit_calls = 0
        self.quit_on_last_window_closed = True

    def quit(self) -> None:
        self.quit_calls += 1

    def setQuitOnLastWindowClosed(self, enabled: bool) -> None:
        self.quit_on_last_window_closed = enabled


def test_close_request_hides_window_when_tray_is_visible() -> None:
    window = _FakeWindow()
    tray_icon = _FakeTray()
    tray_icon.show()
    event = _FakeEvent()

    handled = main._move_close_request_to_tray(window, tray_icon, event)

    assert handled is True
    assert window.calls == ["hide"]
    assert event.ignored is True


def test_close_request_is_not_intercepted_without_visible_tray() -> None:
    window = _FakeWindow()
    tray_icon = _FakeTray()
    event = _FakeEvent()

    handled = main._move_close_request_to_tray(window, tray_icon, event)

    assert handled is False
    assert window.calls == []
    assert event.ignored is False


def test_enabled_tray_restores_window_and_exposes_real_exit(monkeypatch) -> None:
    monkeypatch.setattr(main, "SystemTrayIcon", _FakeTray)
    app = _FakeApp()
    window = _FakeWindow()

    tray_icon = main._enable_system_tray(app, window)

    assert tray_icon is not None
    assert tray_icon.visible is True
    assert window.tray_icon is tray_icon
    assert app.quit_on_last_window_closed is False
    assert [action.get("text") for action in tray_icon.actions] == [
        "显示主窗口",
        None,
        "退出",
    ]

    tray_icon.activated_callbacks[0](ActivationReason.Trigger.value)
    assert window.calls == ["show", "raise", "activate"]

    tray_icon.actions[-1]["triggered"]()
    assert app.quit_calls == 1


def test_unavailable_tray_keeps_normal_last_window_exit(monkeypatch) -> None:
    class _UnavailableTray(_FakeTray):
        available = False

    monkeypatch.setattr(main, "SystemTrayIcon", _UnavailableTray)
    app = _FakeApp()
    window = _FakeWindow()

    assert main._enable_system_tray(app, window) is None
    assert window.tray_icon is None
    assert app.quit_on_last_window_closed is True
