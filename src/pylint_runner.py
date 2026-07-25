# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
# pylint 库 API 的隔离适配层。
# Isolated adapter for pylint's library API.

"""Run the pinned pylint library and return JSON message dictionaries."""

from __future__ import annotations

import io
import json


def run_pylint(files: list[str], message_ids: tuple[str, ...]) -> list[dict[str, object]]:
    """Run the pinned pylint API without starting an external process."""

    from astroid import MANAGER
    from pylint.lint import Run
    from pylint.reporters.json_reporter import JSONReporter

    # Astroid caches modules by name across Run instances.  The desktop app is
    # long-lived, so a repaired file can otherwise keep reporting its old AST.
    MANAGER.clear_cache()
    report = io.StringIO()
    arguments = [
        "--disable=all",
        f"--enable={','.join(message_ids)}",
        "--reports=no",
        "--score=no",
        "--persistent=no",
        "--py-version=2.7",
        *files,
    ]
    Run(arguments, reporter=JSONReporter(report), exit=False)
    raw = report.getvalue().strip()
    if not raw:
        return []
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, list) else []


__all__ = ["run_pylint"]
