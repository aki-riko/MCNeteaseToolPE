# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later

"""Application capabilities exposed by the path-driven local MCP server."""

from __future__ import annotations

from pathlib import Path
import secrets
from threading import RLock

from .cleanup_backend import _clean, _scan
from .config import LEVEL_DB_VALUE_PREVIEW_CHARS
from .level_dat_backend import (
    load_level_dat_view,
    save_extra_data_edits,
    save_level_dat_edits,
)
from .level_dat_model import matching_level_dat_rows
from .minecraft_cleanup_backend import MinecraftCleanupService
from .minecraft_cleanup_definitions import MC_CLEANUP_PROTECTED_DEFINITIONS
from .package_backend import create_zip_archive
from .pack_scanner import scan
from .project_structure import classify_project
from .uuid_backend import _analyze, _generate


DEFAULT_RESULT_LIMIT = 200
MAX_RESULT_LIMIT = 1000
WORLD_DATA_SOURCES = frozenset({"all", "levelDat", "extraData"})
PROTECTED_CLEANUP_KEYS = frozenset(
    str(definition["key"])
    for definition in MC_CLEANUP_PROTECTED_DEFINITIONS
)
PROJECT_PIPELINE_STEPS = ("cleanup", "audit", "uuid", "package")
RECOMMENDED_CLEANUP_CATEGORY = "recommended"


def _validated_limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("结果数量上限必须是整数")
    if value < 1 or value > MAX_RESULT_LIMIT:
        raise ValueError(f"结果数量上限必须在 1-{MAX_RESULT_LIMIT} 之间")
    return value


def _validated_changes(changes: list[dict[str, str]]) -> list[dict[str, str]]:
    if not changes:
        raise ValueError("修改列表不能为空")
    normalized: list[dict[str, str]] = []
    for change in changes:
        if set(change) != {"token", "value"}:
            raise ValueError("每项修改必须且只能包含 token 和 value")
        token = change["token"]
        value = change["value"]
        if not isinstance(token, str) or not token:
            raise ValueError("修改 token 必须是非空字符串")
        if not isinstance(value, str):
            raise ValueError("修改 value 必须是字符串")
        normalized.append({"token": token, "value": value})
    return normalized


class ProjectToolService:
    """Serialize MCP operations while resolving paths supplied to each call."""

    def __init__(
        self,
        global_cleanup_service: MinecraftCleanupService | None = None,
    ) -> None:
        self._lock = RLock()
        self._global_cleanup = global_cleanup_service or MinecraftCleanupService()
        self._global_scan_token: str | None = None
        self._global_scan_snapshot: tuple[object, ...] | None = None

    @staticmethod
    def _absolute_path(value: str, parameter: str) -> Path:
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            raise ValueError(f"{parameter} 必须是绝对路径")
        return candidate.resolve()

    @classmethod
    def _root(cls, project_path: str) -> Path:
        root = cls._absolute_path(project_path, "project_path")
        if not root.is_dir():
            raise ValueError(f"工程目录无效：{project_path}")
        return root

    @classmethod
    def _level_dat_path(cls, level_dat_path: str) -> str:
        return str(cls._absolute_path(level_dat_path, "level_dat_path"))

    @staticmethod
    def _relative(root: Path, path: str | Path) -> str:
        candidate = Path(path).resolve()
        try:
            return candidate.relative_to(root).as_posix()
        except ValueError:
            return candidate.name

    @staticmethod
    def _require_confirmation(confirm: bool, operation: str) -> None:
        if confirm is not True:
            raise PermissionError(f"{operation}会修改本地数据；请将 confirm 明确设为 true")

    def get_project_overview(self, project_path: str) -> dict[str, object]:
        """Read the MC project path supplied by the MCP client."""

        root = self._root(project_path)
        with self._lock:
            structure, packs, logs = _analyze(str(root))
            return {
                "project_root": str(root),
                "project_kind": classify_project(root),
                "structure": structure,
                "pack_count": len(packs),
                "packs": packs,
                "messages": [message for _level, message in logs],
            }

    def audit_project(
        self,
        project_path: str,
        max_issues: int = DEFAULT_RESULT_LIMIT,
    ) -> dict[str, object]:
        """Run the read-only audit for the supplied MC project path."""

        root = self._root(project_path)
        limit = _validated_limit(max_issues)
        with self._lock:
            return self._audit_result(root, limit)

    def _audit_result(self, root: Path, limit: int) -> dict[str, object]:
        issues = scan(str(root))
        payloads = [self._audit_payload(root, issue.as_dict()) for issue in issues]
        error_count = sum(item["severity"] == "error" for item in payloads)
        warning_count = sum(item["severity"] == "warning" for item in payloads)
        return {
            "passed": error_count == 0,
            "error_count": error_count,
            "warning_count": warning_count,
            "issue_count": len(payloads),
            "issues": payloads[:limit],
            "truncated": len(payloads) > limit,
        }

    def _audit_payload(
        self,
        root: Path,
        payload: dict[str, object],
    ) -> dict[str, object]:
        normalized = dict(payload)
        path = normalized.get("path")
        if isinstance(path, str) and path:
            normalized["path"] = self._relative(root, path)
        return normalized

    def preview_cleanup(
        self,
        project_path: str,
        max_items: int = DEFAULT_RESULT_LIMIT,
    ) -> dict[str, object]:
        """List junk entries under the supplied path without deleting them."""

        root = self._root(project_path)
        limit = _validated_limit(max_items)
        with self._lock:
            result, _logs = _scan(str(root))
            items = [self._relative(root, path) for path in result.items]
        return {
            "item_count": len(items),
            "total_bytes": result.total_bytes,
            "items": items[:limit],
            "truncated": len(items) > limit,
        }

    def clean_project(
        self,
        project_path: str,
        confirm: bool = False,
    ) -> dict[str, object]:
        """Delete junk under the supplied path after explicit confirmation."""

        self._require_confirmation(confirm, "清理工程")
        root = self._root(project_path)
        with self._lock:
            success, removed, freed, message, _logs = _clean(str(root))
        return {
            "success": success,
            "removed_count": removed,
            "freed_bytes": freed,
            "message": message,
        }

    def rewrite_project_uuids(
        self,
        project_path: str,
        confirm: bool = False,
    ) -> dict[str, object]:
        """Rewrite UUIDs under the supplied path after confirmation."""

        self._require_confirmation(confirm, "UUID 重写")
        root = self._root(project_path)
        with self._lock:
            success, changed, message, _logs = _generate(str(root))
        return {"success": success, "changed_count": changed, "message": message}

    def package_project(
        self,
        project_path: str,
        confirm: bool = False,
    ) -> dict[str, object]:
        """Create or replace the ZIP for the supplied path after confirmation."""

        self._require_confirmation(confirm, "ZIP 输出")
        root = self._root(project_path)
        with self._lock:
            result = create_zip_archive(str(root))
        return {
            "archive_path": result.archive_path,
            "file_count": result.file_count,
            "size_bytes": result.size_bytes,
        }

    def process_project(
        self,
        project_path: str,
        max_issues: int = DEFAULT_RESULT_LIMIT,
        confirm: bool = False,
    ) -> dict[str, object]:
        """Run cleanup, audit, UUID rewrite and ZIP output in UI order."""

        self._require_confirmation(confirm, "一键处理并审核")
        root = self._root(project_path)
        limit = _validated_limit(max_issues)
        with self._lock:
            cleanup = self._pipeline_cleanup(root)
            if not cleanup["success"]:
                return self._pipeline_stopped("cleanup", cleanup=cleanup)
            audit = self._audit_result(root, limit)
            if not audit["passed"]:
                return self._pipeline_stopped("audit", cleanup=cleanup, audit=audit)
            uuid_result = self._pipeline_uuid(root)
            if not uuid_result["success"]:
                return self._pipeline_stopped(
                    "uuid", cleanup=cleanup, audit=audit, uuid=uuid_result
                )
            package = self._pipeline_package(root)
        return self._pipeline_completed(cleanup, audit, uuid_result, package)

    @staticmethod
    def _pipeline_completed(
        cleanup: dict[str, object],
        audit: dict[str, object],
        uuid_result: dict[str, object],
        package: dict[str, object],
    ) -> dict[str, object]:
        return {
            "success": True,
            "completed_steps": list(PROJECT_PIPELINE_STEPS),
            "cleanup": cleanup,
            "audit": audit,
            "uuid": uuid_result,
            "package": package,
        }

    @staticmethod
    def _pipeline_cleanup(root: Path) -> dict[str, object]:
        success, removed, freed, message, _logs = _clean(str(root))
        return {
            "success": success,
            "removed_count": removed,
            "freed_bytes": freed,
            "message": message,
        }

    @staticmethod
    def _pipeline_uuid(root: Path) -> dict[str, object]:
        success, changed, message, _logs = _generate(str(root))
        return {"success": success, "changed_count": changed, "message": message}

    @staticmethod
    def _pipeline_package(root: Path) -> dict[str, object]:
        result = create_zip_archive(str(root))
        return {
            "archive_path": result.archive_path,
            "file_count": result.file_count,
            "size_bytes": result.size_bytes,
        }

    @staticmethod
    def _pipeline_stopped(step: str, **results: object) -> dict[str, object]:
        stopped_index = PROJECT_PIPELINE_STEPS.index(step)
        return {
            "success": False,
            "stopped_at": step,
            "completed_steps": list(PROJECT_PIPELINE_STEPS[:stopped_index]),
            **results,
        }

    def inspect_world_data(
        self,
        level_dat_path: str,
        query: str = "",
        source_kind: str = "all",
        max_items: int = DEFAULT_RESULT_LIMIT,
    ) -> dict[str, object]:
        """Read and search level.dat plus the sibling NetEase world database."""

        if source_kind not in WORLD_DATA_SOURCES:
            raise ValueError("source_kind 必须是 all、levelDat 或 extraData")
        limit = _validated_limit(max_items)
        source_path = self._level_dat_path(level_dat_path)
        with self._lock:
            summary, rows, _netease_rows = load_level_dat_view(source_path)
        if source_kind != "all":
            rows = [row for row in rows if row.get("sourceKind") == source_kind]
        matched = matching_level_dat_rows(rows, query, []) or []
        return {
            "summary": summary,
            "item_count": len(matched),
            "items": [self._world_row(row) for row in matched[:limit]],
            "truncated": len(matched) > limit,
        }

    def get_world_data_value(
        self,
        level_dat_path: str,
        token: str,
    ) -> dict[str, object]:
        """Return the complete current value for one inspected world-data token."""

        source_path = self._level_dat_path(level_dat_path)
        with self._lock:
            summary, rows, _netease_rows = load_level_dat_view(source_path)
        row = next((item for item in rows if item.get("token") == token), None)
        if row is None:
            raise ValueError("指定 token 不存在；请重新读取世界数据")
        return {
            "summary": summary,
            "path": str(row.get("path", "")),
            "token": token,
            "source_kind": str(row.get("sourceKind", "")),
            "editable": bool(row.get("editable", False)),
            "value": str(row.get("value", "")),
        }

    @staticmethod
    def _world_row(row: dict[str, object]) -> dict[str, object]:
        value = str(row.get("value", ""))
        truncated = len(value) > LEVEL_DB_VALUE_PREVIEW_CHARS
        return {
            "path": str(row.get("path", "")),
            "value": value[:LEVEL_DB_VALUE_PREVIEW_CHARS] if truncated else value,
            "token": str(row.get("token", "")),
            "source_kind": str(row.get("sourceKind", "")),
            "editable": bool(row.get("editable", False)),
            "container": bool(row.get("container", False)),
            "editor_kind": str(row.get("editorKind", "none")),
            "value_truncated": truncated,
            "full_value_length": len(value),
        }

    def update_level_dat(
        self,
        level_dat_path: str,
        fingerprint: str,
        changes: list[dict[str, str]],
        confirm: bool = False,
    ) -> dict[str, object]:
        """Safely apply primitive NBT edits with level.dat_old backup."""

        self._require_confirmation(confirm, "保存 level.dat")
        normalized = _validated_changes(changes)
        source_path = self._level_dat_path(level_dat_path)
        with self._lock:
            summary, _rows, _netease, backup, changed = save_level_dat_edits(
                source_path, fingerprint, normalized
            )
        return {"summary": summary, "backup_path": backup, "changed_count": changed}

    def update_world_database(
        self,
        level_dat_path: str,
        expected_sequence: int,
        expected_fingerprint: str,
        changes: list[dict[str, str]],
        confirm: bool = False,
    ) -> dict[str, object]:
        """Safely apply JSON edits to the current NetEase scriptData record."""

        self._require_confirmation(confirm, "保存世界数据库")
        normalized = _validated_changes(changes)
        source_path = self._level_dat_path(level_dat_path)
        with self._lock:
            summary, _rows, _netease, backup, changed = save_extra_data_edits(
                source_path,
                str(expected_sequence),
                expected_fingerprint,
                normalized,
            )
        return {"summary": summary, "backup_path": backup, "changed_count": changed}

    def scan_global_minecraft_data(self) -> dict[str, object]:
        """Scan recommended caches and protected NetEase Minecraft data."""

        with self._lock:
            state = self._global_cleanup.scan()
            scan_token = secrets.token_urlsafe()
            self._global_scan_token = scan_token
            self._global_scan_snapshot = self._scan_snapshot(state)
        return {
            **state,
            "recommended_category": RECOMMENDED_CLEANUP_CATEGORY,
            "scan_token": scan_token,
        }

    @staticmethod
    def _scan_snapshot(state: dict[str, object]) -> tuple[object, ...]:
        rows = [
            *state.get("cleanableRows", []),
            *state.get("protectedRows", []),
        ]
        category_state = tuple(
            (row.get("key"), row.get("files"), row.get("bytes"), row.get("exists"))
            for row in rows
        )
        return (state.get("rootPath"), state.get("rootExists"), category_state)

    @staticmethod
    def _scanned_categories(state: dict[str, object]) -> frozenset[str]:
        rows = [
            *state.get("cleanableRows", []),
            *state.get("protectedRows", []),
        ]
        return frozenset(
            [RECOMMENDED_CLEANUP_CATEGORY]
            + [str(row.get("key", "")) for row in rows]
        )

    def _require_fresh_global_scan(
        self,
        category: str,
        scan_token: str,
    ) -> None:
        expected_token = self._global_scan_token
        token_matches = (
            isinstance(scan_token, str)
            and expected_token is not None
            and secrets.compare_digest(scan_token, expected_token)
        )
        if not token_matches:
            raise PermissionError("清理前必须先调用 scan_global_minecraft_data 并传回 scan_token")
        current = self._global_cleanup.scan()
        if self._scan_snapshot(current) != self._global_scan_snapshot:
            self._invalidate_global_scan()
            raise RuntimeError("Minecraft 数据在扫描后发生变化；请重新扫描")
        if category not in self._scanned_categories(current):
            raise ValueError("category 必须来自 scan_global_minecraft_data 的扫描结果")

    def _invalidate_global_scan(self) -> None:
        self._global_scan_token = None
        self._global_scan_snapshot = None

    def clean_global_minecraft_data(
        self,
        category: str,
        scan_token: str,
        confirm: bool = False,
        confirm_protected: bool = False,
    ) -> dict[str, object]:
        """Clean a recommended or explicitly double-confirmed protected category."""

        self._require_confirmation(confirm, "清理 Minecraft 全局数据")
        if category in PROTECTED_CLEANUP_KEYS and confirm_protected is not True:
            raise PermissionError("清理有用数据还必须将 confirm_protected 明确设为 true")
        with self._lock:
            self._require_fresh_global_scan(category, scan_token)
            self._invalidate_global_scan()
            result = (
                self._global_cleanup.clean_all()
                if category == RECOMMENDED_CLEANUP_CATEGORY
                else self._global_cleanup.clean(category)
            )
            state = self._global_cleanup.scan()
        return {"result": result, "state": state}


__all__ = ["ProjectToolService"]
