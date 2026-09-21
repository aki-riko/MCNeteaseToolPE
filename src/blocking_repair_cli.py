# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""独立阻塞项修复 worker 的 JSON 行协议。"""

from __future__ import annotations

import json
import sys
import traceback
from typing import TextIO

from .blocking_repair import BlockingRepairService


def _write(stream: TextIO, payload: dict[str, object]) -> None:
    json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
    stream.write("\n")
    stream.flush()


def _request_value(request: dict[str, object], name: str) -> str:
    value = request.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"worker 请求缺少有效字段:{name}")
    return value


def _run_request(request: dict[str, object]) -> tuple[dict[str, object], object | None]:
    operation = request.get("operation")
    project_dir = _request_value(request, "projectDir")
    service = BlockingRepairService()
    if operation == "inspect":
        return service.inspect(project_dir), None
    if operation == "inspect_from_audit":
        issues = request.get("issues")
        if not isinstance(issues, list) or not all(
            isinstance(item, dict) for item in issues
        ):
            raise ValueError("worker 请求的 issues 不是对象列表")
        return service.inspect_from_audit(project_dir, issues), None
    if operation == "apply":
        repair_id = _request_value(request, "repairId")
        return service.apply_and_inspect(project_dir, repair_id)
    if operation == "restore":
        undo = request.get("undo")
        if not isinstance(undo, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in undo.items()
        ):
            raise ValueError("worker 请求的 undo 不是字符串映射")
        return service.restore_and_inspect(project_dir, undo)
    raise ValueError(f"worker 不支持操作:{operation}")


def run_blocking_repair_worker(
    input_stream: TextIO | None = None,
    output: TextIO | None = None,
) -> int:
    """读取一个请求、执行一次服务操作并输出一个结果。"""

    source = input_stream if input_stream is not None else sys.stdin
    stream = output if output is not None else sys.stdout
    line = source.readline()
    if not line:
        _write(stream, {"success": False, "message": "worker 未收到请求"})
        return 2
    try:
        request = json.loads(line)
        if not isinstance(request, dict):
            raise ValueError("worker 请求的 JSON 顶层不是对象")
        state, outcome = _run_request(request)
        _write(stream, {"success": True, "state": state, "outcome": outcome})
        return 0
    except Exception as error:  # noqa: BLE001 - 协议边界必须把异常返回给 UI
        traceback.print_exc(file=sys.stderr)
        _write(stream, {"success": False, "message": str(error)})
        return 1


__all__ = ["run_blocking_repair_worker"]
