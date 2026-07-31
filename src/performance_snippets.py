# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""性能诊断页可复制的网易公开 ModAPI 分析脚本。"""

from __future__ import annotations


CPU_PROFILE_SNIPPET = """import time
import mod.server.extraServerApi as serverApi

def StartCpuProfile(seconds):
    if not serverApi.StartProfile():
        return False
    fileName = "profile_%d.svg" % int(time.time())
    gameComp = serverApi.GetEngineCompFactory().CreateGame(serverApi.GetLevelId())
    gameComp.AddTimer(seconds, lambda: serverApi.StopProfile(fileName))
    return True
"""

MEMORY_PROFILE_SNIPPET = """import time
import mod.server.extraServerApi as serverApi

def StartMemoryProfile(seconds):
    if not serverApi.StartMemProfile():
        return False
    fileName = "memory_profile_%d.svg" % int(time.time())
    gameComp = serverApi.GetEngineCompFactory().CreateGame(serverApi.GetLevelId())
    gameComp.AddTimer(seconds, lambda: serverApi.StopMemProfile(fileName))
    return True
"""

PROFILE_SNIPPETS = {
    "cpu": CPU_PROFILE_SNIPPET,
    "memory": MEMORY_PROFILE_SNIPPET,
}


def default_clipboard_setter(text: str) -> None:
    from PySide6.QtGui import QGuiApplication

    clipboard = QGuiApplication.clipboard()
    if clipboard is None:
        raise RuntimeError("系统剪贴板不可用")
    clipboard.setText(text)


__all__ = [
    "CPU_PROFILE_SNIPPET",
    "MEMORY_PROFILE_SNIPPET",
    "PROFILE_SNIPPETS",
    "default_clipboard_setter",
]
