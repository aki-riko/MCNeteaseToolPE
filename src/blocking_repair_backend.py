# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""阻塞项修复中心的 Qt/QML 异步适配层。"""

from __future__ import annotations

from functools import partial
import logging
import json
import os
import sys

from PySide6.QtCore import (
    QObject,
    Property,
    QProcess,
    QProcessEnvironment,
    Signal,
    Slot,
)

from .blocking_repair import BlockingRepairService, empty_repair_state


LOGGER = logging.getLogger(__name__)


class BlockingRepairBackend(QObject):
    """将扫描、复审和写盘隔离到独立 worker 进程。"""

    stateChanged = Signal()
    busyChanged = Signal()
    canUndoChanged = Signal()
    projectPathChanged = Signal()
    auditResultAdopted = Signal(str)
    result = Signal("QVariant")

    def __init__(
        self,
        parent: QObject | None = None,
        service: BlockingRepairService | None = None,
    ) -> None:
        super().__init__(parent)
        # 保留 service 参数兼容旧调用；实际耗时工作在独立 worker 进程中执行。
        self._service = service or BlockingRepairService()
        self._state = empty_repair_state()
        self._busy = False
        self._process: QProcess | None = None
        self._stdout_buffer = bytearray()
        self._stderr_buffer = bytearray()
        self._request_id = 0
        self._operation_label = "阻塞项修复"
        self._last_undo: dict[str, str] | None = None
        self._project_path = ""

    @Property("QVariantMap", notify=stateChanged)
    def state(self) -> dict[str, object]:
        return self._state

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    @Property(bool, notify=canUndoChanged)
    def canUndo(self) -> bool:
        return self._last_undo is not None

    @Property(str, notify=projectPathChanged)
    def projectPath(self) -> str:
        return self._project_path

    @Slot(str)
    def inspect(self, project_dir: str) -> None:
        self._start_process(
            {"operation": "inspect", "projectDir": project_dir},
            "检查可自动优化项",
            project_path=project_dir,
        )

    @Slot(str, list)
    def adoptAuditResult(self, project_dir: str, issues: list[dict[str, object]]) -> None:
        self._start_process(
            {
                "operation": "inspect_from_audit",
                "projectDir": project_dir,
                "issues": [dict(item) for item in issues if isinstance(item, dict)],
            },
            "同步工程处理的审核阻塞项",
            project_path=project_dir,
            audit_adoption=True,
        )

    @Slot(str)
    def applyRepair(self, repair_id: str) -> None:
        root_path = self._state.get("rootPath")
        if not isinstance(root_path, str) or not root_path:
            self._emit_failure("请先完成一次工程检查")
            return
        self._start_process(
            {"operation": "apply", "projectDir": root_path, "repairId": repair_id},
            "执行修复",
        )

    @Slot()
    def undoLastRemoval(self) -> None:
        root_path = self._state.get("rootPath")
        if not isinstance(root_path, str) or not root_path or self._last_undo is None:
            self._emit_failure("没有可撤销的隔离清理")
            return
        undo = dict(self._last_undo)
        self._start_process(
            {"operation": "restore", "projectDir": root_path, "undo": undo},
            "撤销清理",
        )

    @Slot()
    def reset(self) -> None:
        if self._busy:
            return
        self._state = empty_repair_state()
        self._set_last_undo(None)
        self._set_project_path("")
        self.stateChanged.emit()

    def _start_process(
        self,
        request: dict[str, object],
        label: str,
        *,
        project_path: str = "",
        audit_adoption: bool = False,
    ) -> None:
        if self._busy or self._process is not None:
            return
        self._set_busy(True)
        self._operation_label = label
        self._request_id += 1
        process = QProcess(self)
        process.setProgram(self._worker_program())
        process.setArguments(self._worker_arguments())
        process.setProcessEnvironment(self._worker_environment())
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.readyReadStandardOutput.connect(self._read_standard_output)
        process.readyReadStandardError.connect(self._read_standard_error)
        process.errorOccurred.connect(self._on_process_error)
        request_bytes = (json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8")
        process.started.connect(partial(self._write_request, process, request_bytes))
        process.finished.connect(
            partial(
                self._on_process_finished,
                process,
                self._request_id,
                project_path=project_path,
                audit_adoption=audit_adoption,
            )
        )
        self._process = process
        self._stdout_buffer.clear()
        self._stderr_buffer.clear()
        try:
            process.start()
        except Exception as error:  # noqa: BLE001 - 调度失败必须反馈至界面
            LOGGER.exception("阻塞项修复 worker 启动失败")
            self._fail_process(f"{label}无法启动:{error}")
            return

    @staticmethod
    def _write_request(process: QProcess, payload: bytes) -> None:
        if process.state() != QProcess.ProcessState.Running:
            return
        process.write(payload)
        process.closeWriteChannel()

    @staticmethod
    def _worker_program() -> str:
        return os.path.abspath(sys.executable)

    @staticmethod
    def _worker_arguments() -> list[str]:
        executable_name = os.path.basename(sys.executable).casefold()
        if executable_name.startswith("python"):
            entry_point = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "repair_worker.py",
            )
            return ["-u", entry_point]
        return ["--blocking-repair-worker"]

    @staticmethod
    def _worker_environment() -> QProcessEnvironment:
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONUTF8", "1")
        environment.insert("PYTHONIOENCODING", "utf-8")
        return environment

    def _read_standard_output(self) -> None:
        process = self._process
        if process is None:
            return
        self._stdout_buffer.extend(bytes(process.readAllStandardOutput()))

    def _read_standard_error(self) -> None:
        process = self._process
        if process is not None:
            self._stderr_buffer.extend(bytes(process.readAllStandardError()))

    def _on_process_error(self, error: QProcess.ProcessError) -> None:
        process = self._process
        if process is None:
            return
        LOGGER.error("阻塞项修复 worker 错误:%s (%s)", error, process.errorString())
        if error == QProcess.ProcessError.FailedToStart:
            self._fail_process(f"{self._operation_label}启动失败:{process.errorString()}")

    def _on_process_finished(
        self,
        process: QProcess,
        request_id: int,
        exit_code: int,
        exit_status: QProcess.ExitStatus,
        project_path: str,
        audit_adoption: bool,
    ) -> None:
        if process is not self._process or request_id != self._request_id:
            return
        self._read_standard_output()
        self._read_standard_error()
        payload_line = bytes(self._stdout_buffer).strip()
        stderr = self._stderr_buffer.decode("utf-8", errors="replace").strip()
        self._process = None
        process.deleteLater()
        if exit_status != QProcess.ExitStatus.NormalExit or exit_code != 0:
            detail = stderr.splitlines()[-1] if stderr else f"退出码 {exit_code}"
            self._fail_process(f"{self._operation_label}失败:{detail}")
            return
        try:
            payload = json.loads(payload_line.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("worker 返回的 JSON 顶层不是对象")
            if payload.get("success") is not True:
                raise ValueError(str(payload.get("message") or "worker 未返回成功结果"))
            state = payload.get("state")
            if not isinstance(state, dict):
                raise ValueError("worker 返回了无效状态")
            outcome = payload.get("outcome")
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
            LOGGER.error("阻塞项修复 worker 结果无效:%s", error)
            self._fail_process(f"{self._operation_label}失败:{error}")
            return
        self._finish_result(state, outcome, project_path, audit_adoption)

    def _finish_result(
        self,
        state: dict[str, object],
        outcome: object,
        project_path: str,
        audit_adoption: bool,
    ) -> None:
        self._set_busy(False)
        self._state = state
        if project_path:
            root_path = state.get("rootPath")
            if isinstance(root_path, str):
                self._set_project_path(root_path)
        self.stateChanged.emit()
        if audit_adoption and self._project_path:
            self.auditResultAdopted.emit(self._project_path)
        if outcome is not None:
            self._update_undo(outcome)
            self.result.emit(outcome)

    def _fail_process(self, message: str) -> None:
        process = self._process
        self._process = None
        if process is not None:
            process.kill()
            process.deleteLater()
        self._set_busy(False)
        LOGGER.error("阻塞项修复 worker 失败: %s", message)
        self._emit_failure(message)

    def _emit_failure(self, message: str) -> None:
        self._state = {**self._state, "phase": "failed", "message": message}
        self.stateChanged.emit()
        self.result.emit({"success": False, "message": message, "changedPaths": []})

    def _update_undo(self, outcome: object) -> None:
        if not isinstance(outcome, dict):
            return
        undo = outcome.get("undo")
        if isinstance(undo, dict) and all(isinstance(value, str) for value in undo.values()):
            self._set_last_undo(dict(undo))
        elif outcome.get("clearUndo") is True:
            self._set_last_undo(None)

    def _set_last_undo(self, value: dict[str, str] | None) -> None:
        had_undo = self._last_undo is not None
        self._last_undo = value
        if had_undo != (value is not None):
            self.canUndoChanged.emit()

    def _set_project_path(self, value: str) -> None:
        if self._project_path == value:
            return
        self._project_path = value
        self.projectPathChanged.emit()

    def _set_busy(self, value: bool) -> None:
        if self._busy == value:
            return
        self._busy = value
        self.busyChanged.emit()


__all__ = ["BlockingRepairBackend"]
