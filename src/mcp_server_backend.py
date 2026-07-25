# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later

"""Qt process controller for the application-lifetime MCP server."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import sys

from PySide6.QtCore import (
    QCoreApplication,
    QObject,
    Property,
    QProcess,
    QProcessEnvironment,
    QTimer,
    Signal,
    Slot,
)
from prismqml import get_clipboard_helper

from .config import (
    MCP_HOST,
    MCP_PATH,
    MCP_PORT,
    MCP_STOP_TIMEOUT_MS,
)
from .mcp_server import (
    MCP_GLOBAL_CLEANUP_RULE,
    MCP_PATH_RULE,
    MCP_SERVER_FLAG,
    MCP_WORLD_UPDATE_RULE,
    MCP_WRITE_CONFIRMATION_RULE,
    format_endpoint,
)


LOGGER = logging.getLogger(__name__)
UVICORN_READY_MARKER = "Uvicorn running on "


def _format_access_prompt(endpoint: str) -> str:
    return (
        "请将以下 MCP 服务器接入你当前运行的 AI 客户端，并实际验证连接：\n"
        "名称：MCNeteaseToolPE\n"
        "传输方式：Streamable HTTP\n"
        f"端点：{endpoint}\n\n"
        "接入要求：\n"
        "1. 完成配置后连接服务器，并告诉我实际枚举到的工具列表。\n"
        f"2. {MCP_PATH_RULE}\n"
        f"3. {MCP_WRITE_CONFIRMATION_RULE}\n"
        f"4. {MCP_GLOBAL_CLEANUP_RULE}\n"
        f"5. {MCP_WORLD_UPDATE_RULE}\n"
        "如果当前客户端不允许你自行修改 MCP 配置，请明确告诉我应该在哪里填写以上信息，"
        "不要假装已经接入。"
    )


def _mcp_server_command(
    host: str,
    port: int,
    path: str,
) -> tuple[str, list[str]]:
    executable = os.path.abspath(sys.executable)
    repository_root = Path(__file__).resolve().parents[1]
    entry_point = repository_root / "main.py"
    arguments = [
        MCP_SERVER_FLAG,
        "--host",
        host,
        "--port",
        str(port),
        "--path",
        path,
    ]
    if Path(executable).name.casefold().startswith("python") and entry_point.is_file():
        return executable, ["-u", str(entry_point), *arguments]
    return executable, arguments


class McpServerBackend(QObject):
    """Auto-start, observe and stop the isolated MCP HTTP process."""

    stateChanged = Signal()
    statusChanged = Signal()
    logMessage = Signal(str, str)

    def __init__(
        self,
        parent: QObject | None = None,
        port: int = MCP_PORT,
        auto_start: bool = True,
    ) -> None:
        super().__init__(parent)
        self._port = int(port)
        self._process: QProcess | None = None
        self._starting = False
        self._running = False
        self._stop_requested = False
        self._status = "等待程序自动启动 MCP 服务器"
        self._stdout_buffer = bytearray()
        self._stderr_buffer = bytearray()
        application = QCoreApplication.instance()
        if application is not None:
            application.aboutToQuit.connect(self._shutdown_now)
            if auto_start:
                QTimer.singleShot(0, self.start)
        elif auto_start:
            LOGGER.warning("没有 QCoreApplication，无法安排 MCP 服务器自动启动")

    @Property(bool, notify=stateChanged)
    def active(self) -> bool:
        return self._starting or self._running

    @Property(bool, notify=stateChanged)
    def starting(self) -> bool:
        return self._starting

    @Property(bool, notify=stateChanged)
    def running(self) -> bool:
        return self._running

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        return self._status

    @Property(str, constant=True)
    def endpoint(self) -> str:
        try:
            return format_endpoint(MCP_HOST, self._port, MCP_PATH)
        except (TypeError, ValueError):
            return ""

    @Property(str, constant=True)
    def accessPrompt(self) -> str:
        endpoint = self.endpoint
        return _format_access_prompt(endpoint) if endpoint else ""

    def _set_state(self, *, starting: bool, running: bool) -> None:
        changed = self._starting != starting or self._running != running
        self._starting = starting
        self._running = running
        if changed:
            self.stateChanged.emit()

    def _set_status(self, status: str) -> None:
        if self._status == status:
            return
        self._status = status
        self.statusChanged.emit()

    @Slot(result=bool)
    def start(self) -> bool:
        if self.active:
            self.logMessage.emit("MCP 服务器已经在运行", "warn")
            return False
        endpoint = self.endpoint
        if not endpoint:
            self._reject_start("MCP 监听配置无效")
            return False
        self._launch_process(endpoint)
        return True

    def _reject_start(self, message: str) -> None:
        self._set_status(message)
        self.logMessage.emit(message, "error")

    def _launch_process(self, endpoint: str) -> None:
        program, arguments = _mcp_server_command(
            MCP_HOST,
            self._port,
            MCP_PATH,
        )
        process = QProcess(self)
        process.setProgram(program)
        process.setArguments(arguments)
        process.setProcessEnvironment(self._process_environment())
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.readyReadStandardOutput.connect(self._read_standard_output)
        process.readyReadStandardError.connect(self._read_standard_error)
        process.errorOccurred.connect(self._on_process_error)
        process.finished.connect(self._on_process_finished)
        self._process = process
        self._stdout_buffer.clear()
        self._stderr_buffer.clear()
        self._stop_requested = False
        self._set_state(starting=True, running=False)
        self._set_status(f"正在启动：{endpoint}")
        self.logMessage.emit(f"启动 MCP 服务器：{endpoint}", "info")
        process.start()

    @staticmethod
    def _process_environment() -> QProcessEnvironment:
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONUNBUFFERED", "1")
        environment.insert("PYTHONUTF8", "1")
        return environment

    def _read_standard_output(self) -> None:
        if self._process is None:
            return
        self._stdout_buffer.extend(bytes(self._process.readAllStandardOutput()))
        self._drain_lines(self._stdout_buffer, self._handle_stdout_line)

    def _read_standard_error(self) -> None:
        if self._process is None:
            return
        self._stderr_buffer.extend(bytes(self._process.readAllStandardError()))
        self._drain_lines(self._stderr_buffer, self._handle_stderr_line)

    @staticmethod
    def _drain_lines(buffer: bytearray, handler) -> None:
        while True:
            newline = buffer.find(b"\n")
            if newline < 0:
                return
            line = bytes(buffer[:newline]).rstrip(b"\r")
            del buffer[: newline + 1]
            if line:
                handler(line.decode("utf-8", errors="replace"))

    def _handle_stdout_line(self, line: str) -> None:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            self.logMessage.emit(line, "info")
            return
        if isinstance(payload, dict) and payload.get("event") == "starting":
            endpoint = payload.get("endpoint", "")
            self.logMessage.emit(f"服务进程已加载：{endpoint}", "info")
            return
        self.logMessage.emit(line, "info")

    def _handle_stderr_line(self, line: str) -> None:
        if UVICORN_READY_MARKER in line:
            self._set_state(starting=False, running=True)
            self._set_status("MCP 服务器正在运行")
            self.logMessage.emit("MCP 服务器已就绪", "success")
            return
        level = "error" if "ERROR" in line else "info"
        self.logMessage.emit(line, level)

    @Slot()
    def stop(self) -> None:
        process = self._process
        if process is None or process.state() == QProcess.ProcessState.NotRunning:
            return
        self._stop_requested = True
        self._set_status("正在停止 MCP 服务器")
        process.terminate()
        QTimer.singleShot(MCP_STOP_TIMEOUT_MS, lambda: self._kill_if_running(process))

    @staticmethod
    def _kill_if_running(process: QProcess) -> None:
        if process.state() != QProcess.ProcessState.NotRunning:
            process.kill()

    @Slot()
    def copyAccessPrompt(self) -> None:
        prompt = self.accessPrompt
        if not prompt:
            self.logMessage.emit("MCP 接入 Prompt 无效，无法复制", "error")
            return
        get_clipboard_helper().copy(prompt)
        self.logMessage.emit("已复制 MCP 接入 Prompt", "success")

    def _on_process_error(self, error: QProcess.ProcessError) -> None:
        if self._process is None:
            return
        if self._stop_requested and error == QProcess.ProcessError.Crashed:
            LOGGER.debug("MCP 服务器进程已随应用退出")
            return
        message = f"MCP 服务器进程错误：{self._process.errorString()}"
        LOGGER.error("%s (%s)", message, error)
        if error == QProcess.ProcessError.FailedToStart:
            self._settle_process(message, "error")

    def _on_process_finished(
        self,
        exit_code: int,
        exit_status: QProcess.ExitStatus,
    ) -> None:
        if self._process is None:
            return
        self._read_standard_output()
        self._read_standard_error()
        if self._stop_requested:
            self._settle_process("MCP 服务器已停止", "info")
            return
        detail = f"退出码 {exit_code}，状态 {exit_status.name}"
        self._settle_process(f"MCP 服务器异常退出：{detail}", "error")

    def _settle_process(self, status: str, level: str) -> None:
        process = self._process
        self._process = None
        self._set_state(starting=False, running=False)
        self._set_status(status)
        self.logMessage.emit(status, level)
        if process is not None:
            process.deleteLater()

    @Slot()
    def _shutdown_now(self) -> None:
        process = self._process
        if process is not None and process.state() != QProcess.ProcessState.NotRunning:
            self._stop_requested = True
            process.kill()
            if not process.waitForFinished(MCP_STOP_TIMEOUT_MS):
                LOGGER.warning("MCP 服务器进程未在应用退出前结束")


__all__ = ["McpServerBackend"]
