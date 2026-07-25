# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
# 打包审核后端的 Python 实现。
# Python implementation of the audit backend.

from __future__ import annotations

import json
import logging
import os
import sys

from PySide6.QtCore import QObject, Property, QProcess, Signal, Slot


LOGGER = logging.getLogger(__name__)


def _audit_worker_command(project_dir: str) -> tuple[str, list[str]]:
    """Return the source or standalone command for the isolated audit worker."""

    executable = os.path.abspath(sys.executable)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    entry_point = os.path.join(project_root, "audit_worker.py")
    executable_name = os.path.basename(executable).casefold()
    if executable_name.startswith("python") and os.path.isfile(entry_point):
        return executable, ["-u", entry_point, "--audit-stream-json", project_dir]
    return executable, ["--audit-stream-json", project_dir]


class AuditBackend(QObject):
    """Run the GIL-heavy audit in a separate process and relay JSON Lines."""

    logMessage = Signal(str, str)
    progress = Signal(int, int, str)
    taskFailed = Signal(str)
    busyChanged = Signal()
    finished = Signal(bool, int, int, list)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._busy = False
        self._process: QProcess | None = None
        self._stdout_buffer = bytearray()
        self._stderr_buffer = bytearray()
        self._pending_issues: list[dict[str, object]] | None = None
        self._protocol_error = ""
        self._settled = False

    def _is_busy(self) -> bool:
        return self._busy

    busy = Property(bool, _is_busy, notify=busyChanged)

    def _set_busy(self, value: bool) -> None:
        if self._busy == value:
            return
        self._busy = value
        self.busyChanged.emit()

    @Slot(str)
    def audit(self, project_dir: str) -> None:
        if self._busy:
            self.logMessage.emit("正忙,请稍候", "warn")
            return
        program, arguments = _audit_worker_command(project_dir)
        process = QProcess(self)
        process.setProgram(program)
        process.setArguments(arguments)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.readyReadStandardOutput.connect(self._read_standard_output)
        process.readyReadStandardError.connect(self._read_standard_error)
        process.errorOccurred.connect(self._on_process_error)
        process.finished.connect(self._on_process_finished)
        self._process = process
        self._stdout_buffer.clear()
        self._stderr_buffer.clear()
        self._pending_issues = None
        self._protocol_error = ""
        self._settled = False
        self._set_busy(True)
        self.logMessage.emit(f"开始审核:{project_dir}", "info")
        process.start()

    def _read_standard_output(self) -> None:
        if self._process is None:
            return
        self._stdout_buffer.extend(bytes(self._process.readAllStandardOutput()))
        while True:
            newline = self._stdout_buffer.find(b"\n")
            if newline < 0:
                break
            line = bytes(self._stdout_buffer[:newline]).rstrip(b"\r")
            del self._stdout_buffer[: newline + 1]
            if line:
                self._handle_worker_line(line)

    def _read_standard_error(self) -> None:
        if self._process is not None:
            self._stderr_buffer.extend(bytes(self._process.readAllStandardError()))

    def _handle_worker_line(self, line: bytes) -> None:
        try:
            payload = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            self._record_protocol_error(f"审核子进程输出不是有效 JSON:{error}")
            return
        if not isinstance(payload, dict):
            self._record_protocol_error("审核子进程输出的 JSON 顶层不是对象")
            return
        message_type = payload.get("type")
        if message_type == "progress":
            self._handle_progress(payload)
            return
        if message_type == "result":
            issues = payload.get("issues")
            if not isinstance(issues, list) or not all(isinstance(issue, dict) for issue in issues):
                self._record_protocol_error("审核子进程返回的 issues 不是对象列表")
                return
            if self._pending_issues is not None:
                self._record_protocol_error("审核子进程重复返回结果")
                return
            self._pending_issues = issues
            return
        self._record_protocol_error(f"审核子进程返回未知消息类型:{message_type}")

    def _handle_progress(self, payload: dict[str, object]) -> None:
        current = payload.get("current")
        total = payload.get("total")
        status = payload.get("status")
        if (
            not isinstance(current, int)
            or not isinstance(total, int)
            or total <= 0
            or not isinstance(status, str)
        ):
            self._record_protocol_error("审核子进程返回无效进度")
            return
        self.progress.emit(max(0, min(current, total)), total, status)

    def _record_protocol_error(self, message: str) -> None:
        if self._protocol_error:
            return
        self._protocol_error = message
        LOGGER.error(message)

    def _on_process_error(self, error: QProcess.ProcessError) -> None:
        if self._process is None:
            return
        LOGGER.error("审核子进程错误:%s (%s)", error, self._process.errorString())
        if error == QProcess.ProcessError.FailedToStart:
            self._fail(f"审核子进程启动失败:{self._process.errorString()}")
            self._cleanup_process()

    def _on_process_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        if self._process is None:
            return
        self._read_standard_output()
        self._read_standard_error()
        if self._stdout_buffer.strip():
            line = bytes(self._stdout_buffer).rstrip(b"\r")
            self._stdout_buffer.clear()
            self._handle_worker_line(line)
        stderr = self._stderr_buffer.decode("utf-8", errors="replace").strip()
        if not self._settled:
            if exit_status != QProcess.ExitStatus.NormalExit or exit_code != 0:
                detail = stderr.splitlines()[-1] if stderr else f"退出码 {exit_code}"
                self._fail(f"审核子进程异常退出:{detail}")
            elif self._protocol_error:
                self._fail(self._protocol_error)
            elif self._pending_issues is None:
                self._fail("审核子进程未返回结果")
            else:
                self._complete(self._pending_issues)
        self._cleanup_process()

    def _complete(self, issues: list[dict[str, object]]) -> None:
        if self._settled:
            return
        self._settled = True
        self._set_busy(False)
        errors = sum(1 for issue in issues if issue.get("severity") == "error")
        warnings = sum(1 for issue in issues if issue.get("severity") == "warning")
        passed = errors == 0
        if passed:
            self.logMessage.emit(f"审核通过({warnings} 条警告)", "success")
        else:
            self.logMessage.emit(f"审核未通过:{errors} 个错误、{warnings} 个警告", "error")
        self.finished.emit(passed, errors, warnings, issues)

    def _fail(self, message: str) -> None:
        if self._settled:
            return
        self._settled = True
        self._set_busy(False)
        self.logMessage.emit(message, "error")
        self.taskFailed.emit(message)
        self.finished.emit(False, 1, 0, [])

    def _cleanup_process(self) -> None:
        process = self._process
        self._process = None
        if process is not None:
            process.deleteLater()


__all__ = ["AuditBackend"]
