# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tracy 函数区间的已验证语义分类。"""

from __future__ import annotations


WAIT_ZONE_NAMES = frozenset({"sleep @ time"})


def is_wait_zone_name(name: object) -> bool:
    return str(name).strip().casefold() in WAIT_ZONE_NAMES


__all__ = ["WAIT_ZONE_NAMES", "is_wait_zone_name"]
