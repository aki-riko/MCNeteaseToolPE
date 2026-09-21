# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""源码运行时的独立阻塞项修复 worker 入口。"""

from __future__ import annotations

from src.blocking_repair_cli import run_blocking_repair_worker


if __name__ == "__main__":
    raise SystemExit(run_blocking_repair_worker())
