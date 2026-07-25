# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
# 源码运行时的独立审核进程入口。
# Isolated audit-process entry point for source runs.

from __future__ import annotations

import sys

from src.audit_cli import run_audit_cli


def main() -> int:
    status = run_audit_cli(sys.argv[1:])
    if status is None:
        raise RuntimeError("audit_worker.py requires an audit CLI argument")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
