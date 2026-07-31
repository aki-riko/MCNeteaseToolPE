# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""自动性能监测的启动稳定门与平台默认依赖。"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QProcess

from .performance_monitor import ProcessDescriptor, WindowsProcessSampler


LOGGER = logging.getLogger(__name__)


def default_launcher(executable: Path) -> bool:
    launched, _pid = QProcess.startDetached(
        str(executable),
        [],
        str(executable.parent),
    )
    return bool(launched)


def create_default_sampler() -> WindowsProcessSampler | None:
    try:
        return WindowsProcessSampler()
    except OSError:
        LOGGER.warning("当前系统不支持 Windows 进程性能采样", exc_info=True)
        return None


def empty_performance_discovery() -> dict[str, object]:
    return {
        "root": "",
        "configured": False,
        "tools": {
            "tracy": {"available": False, "path": ""},
            "airperf": {"available": False, "path": ""},
        },
    }


def process_payload(process: ProcessDescriptor) -> dict[str, object]:
    return {"pid": process.pid, "name": process.name, "text": process.label}


class AutomaticProfessionalStartGate:
    """要求同一目标和 Tracy 连续稳定后才允许启动侵入性较高的采集器。"""

    def __init__(
        self,
        stability_ms: int,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._stability_ms = max(0, int(stability_ms))
        self._monotonic = monotonic or time.monotonic
        self._target_pid = 0
        self._target_name = ""
        self._target_seen_at: float | None = None
        self._tracy_reachable_at: float | None = None

    @property
    def state(self) -> dict[str, object]:
        now = self._monotonic()
        elapsed_ms = self._elapsed_ms(now)
        return {
            "targetPid": self._target_pid,
            "stabilityMs": self._stability_ms,
            "tracyStableMs": elapsed_ms,
            "remainingMs": max(0, self._stability_ms - elapsed_ms),
        }

    def observe(self, pid: int, name: str, tracy_ready: bool) -> bool:
        now = self._monotonic()
        self._observe_target(pid, name, now)
        return self._observe_tracy(tracy_ready, now)

    def _observe_target(self, pid: int, name: str, now: float) -> None:
        if pid != self._target_pid:
            self.reset("target_changed")
            self._target_pid = int(pid)
            self._target_name = str(name)
            self._target_seen_at = now
            LOGGER.info(
                "performance_auto event=target_detected pid=%s name=%s seen_at=%.3f",
                self._target_pid,
                self._target_name,
                now,
            )

    def _observe_tracy(self, tracy_ready: bool, now: float) -> bool:
        if not tracy_ready:
            if self._tracy_reachable_at is not None:
                LOGGER.info(
                    "performance_auto event=tracy_lost pid=%s stable_ms=%s",
                    self._target_pid,
                    self._elapsed_ms(now),
                )
            self._tracy_reachable_at = None
            return False
        if self._tracy_reachable_at is None:
            self._tracy_reachable_at = now
            LOGGER.info(
                "performance_auto event=tracy_reachable pid=%s reachable_at=%.3f",
                self._target_pid,
                now,
            )
        return self._elapsed_ms(now) >= self._stability_ms

    def mark_started(self, airperf_active: bool) -> None:
        now = self._monotonic()
        process_age_ms = 0
        if self._target_seen_at is not None:
            process_age_ms = max(0, int((now - self._target_seen_at) * 1000))
        LOGGER.info(
            "performance_auto event=professional_started pid=%s "
            "process_age_ms=%s tracy_stable_ms=%s airperf_active=%s",
            self._target_pid,
            process_age_ms,
            self._elapsed_ms(now),
            bool(airperf_active),
        )

    def reset(self, reason: str) -> None:
        if self._target_pid:
            LOGGER.info(
                "performance_auto event=readiness_reset pid=%s reason=%s",
                self._target_pid,
                reason,
            )
        self._target_pid = 0
        self._target_name = ""
        self._target_seen_at = None
        self._tracy_reachable_at = None

    def _elapsed_ms(self, now: float) -> int:
        if self._tracy_reachable_at is None:
            return 0
        return max(0, int((now - self._tracy_reachable_at) * 1000))


__all__ = [
    "AutomaticProfessionalStartGate",
    "create_default_sampler",
    "default_launcher",
    "empty_performance_discovery",
    "process_payload",
]
