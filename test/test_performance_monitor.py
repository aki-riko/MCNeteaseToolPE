# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""Win32 进程采样器的生命周期回归测试。"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from src.performance_monitor import WindowsProcessSampler


@pytest.mark.skipif(os.name != "nt", reason="Win32 进程 API 仅在 Windows 可用")
def test_sampler_rejects_exited_process_while_an_external_handle_keeps_it_alive() -> None:
    """AirPerf 等外部句柄保留进程对象时也不能返回退出后的残留指标。"""

    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        creationflags=creation_flags,
    )
    sampler = WindowsProcessSampler()
    try:
        sampler.sample(process.pid)
        process.terminate()
        process.wait(timeout=5)

        with pytest.raises(ProcessLookupError, match="已退出"):
            sampler.sample(process.pid)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
