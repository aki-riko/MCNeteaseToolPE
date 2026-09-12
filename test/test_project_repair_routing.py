# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""工程处理失败到阻塞项修复页的路由回归测试。"""

from __future__ import annotations

import main


def test_project_blockers_are_adopted_before_repair_page_navigation() -> None:
    calls: list[tuple[str, object]] = []
    issues = [{"code": 37, "severity": "error", "title": "manifest 缺 min_engine_version"}]

    class _RepairBackend:
        def adoptAuditResult(self, project_dir: str, payload: list[dict[str, object]]) -> None:
            calls.append(("adopt", (project_dir, payload)))

    class _Window:
        def setCurrentIndex(self, index: int) -> None:
            calls.append(("navigate", index))

    main._route_project_blockers(
        _Window(),
        _RepairBackend(),
        4,
        "D:/workspace/project",
        issues,
    )

    assert calls == [
        ("adopt", ("D:/workspace/project", issues)),
        ("navigate", 4),
    ]
