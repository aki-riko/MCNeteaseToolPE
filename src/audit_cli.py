# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
# 自动补全必需目录后执行打包审核的命令行入口。
# Audit CLI with safe required-directory normalization.

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import sys
from typing import TextIO

from src.pack_scanner import ensure_required_pack_directories, scan


def _write_json_line(stream: TextIO, payload: dict[str, object]) -> None:
    json.dump(payload, stream, ensure_ascii=True, separators=(",", ":"))
    stream.write("\n")
    stream.flush()


def _run_stream_audit(project_dir: str, stream: TextIO) -> int:
    def report_progress(payload: tuple[int, int, str]) -> None:
        current, total, status = payload
        _write_json_line(
            stream,
            {"type": "progress", "current": current, "total": total, "status": status},
        )

    ensure_required_pack_directories(project_dir)
    issues = scan(project_dir, progress=report_progress)
    _write_json_line(stream, {"type": "result", "issues": [issue.as_dict() for issue in issues]})
    return 0


def run_audit_cli(arguments: list[str], output: TextIO | None = None) -> int | None:
    """Run an audit CLI mode when requested, otherwise preserve GUI startup."""

    if "--audit-json" not in arguments and "--audit-stream-json" not in arguments:
        return None
    parser = argparse.ArgumentParser(description="补全网易必需目录并扫描组件工程，输出 JSON")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--audit-json", metavar="PROJECT_DIR")
    mode.add_argument("--audit-stream-json", metavar="PROJECT_DIR")
    options = parser.parse_args(arguments)
    stream = output if output is not None else sys.stdout
    if options.audit_stream_json is not None:
        return _run_stream_audit(options.audit_stream_json, stream)
    ensure_required_pack_directories(options.audit_json)
    payload = [asdict(issue) for issue in scan(options.audit_json)]
    json.dump(payload, stream, ensure_ascii=True)
    stream.write("\n")
    return 0


__all__ = ["run_audit_cli"]
