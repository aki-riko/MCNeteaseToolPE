# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""可确认执行的非代码阻塞项修复计划。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .pack_scanner import scan


REPAIR_CREATE_REQUIRED_DIRECTORY = "create_required_directory"
REPAIR_CLEAR_LEVEL_READONLY = "clear_level_readonly"
REPAIR_FIX_PLAYER_CONTROLLERS = "fix_player_controllers"
REPAIR_MOVE_PACK_LAYOUT = "move_pack_layout"
REPAIR_NORMALIZE_GLYPH_TRANSPARENCY = "normalize_glyph_transparency"
REPAIR_NORMALIZE_MANIFEST_COMMENTS = "normalize_manifest_comments"
REPAIR_NORMALIZE_JSON_BOM = "normalize_json_bom"
REPAIR_REMOVE_SAFE_RESIDUE = "remove_safe_residue"
REPAIR_RENAME_RESOURCE_ENTITIES = "rename_resource_entities"
REPAIR_SET_MIN_ENGINE_VERSION = "set_min_engine_version"
BLOCKING_ISSUE_PREVIEW_LIMIT = 8
NON_CODE_ERROR_CODES = frozenset(
    {0, 6, 10, 12, 13, 16, 20, 23, 24, 25, 26, 27, 29, 30, 31, 33, 34, 36, 37, 38, 40}
)
NON_CODE_ERROR_TITLES = frozenset(
    {
        (18, "工程包含编辑信息"),
        (35, "命名含 5 个以上连续相同字符"),
    }
)
KNOWN_AUDIT_ERROR_CODES = NON_CODE_ERROR_CODES | frozenset({18, 35})

_BEHAVIOR_MODULE_TYPES = frozenset({"data", "client_data", "javascript"})
_RESOURCE_MODULE_TYPE = "resources"


@dataclass(frozen=True)
class RepairCandidate:
    """一项从当前工程状态推导出的、可逆或原子化的写入操作。"""

    root_path: Path
    identifier: str
    kind: str
    title: str
    detail: str
    change: str
    display_path: Path
    source_path: Path
    target_path: Path
    source_digest: str = ""
    destructive: bool = False
    impact: str = ""

    def as_dict(self, root: Path) -> dict[str, str]:
        return {
            "id": self.identifier,
            "kind": self.kind,
            "title": self.title,
            "detail": self.detail,
            "change": self.change,
            "path": _relative(root, self.display_path),
            "destructive": self.destructive,
            "impact": self.impact,
        }


@dataclass(frozen=True)
class RepairApplyResult:
    """一次修复写入后的变更与可选撤销信息。"""

    changed_paths: list[Path]
    undo: dict[str, str] | None = None


def empty_repair_state(message: str = "选择工程目录后即可检查可自动优化项") -> dict[str, object]:
    """返回 QML 可以直接绑定的空状态。"""

    return {
        "phase": "idle",
        "rootPath": "",
        "message": message,
        "repairableCount": 0,
        "auditErrorCount": 0,
        "auditWarningCount": 0,
        "items": [],
        "blockingPreview": [],
        "blockingPreviewTruncated": False,
    }


def _project_root(project_dir: str) -> Path:
    if not project_dir:
        raise ValueError("请选择有效的工程目录")
    root = Path(project_dir).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"目录无效:{project_dir}")
    return root


def _relative(root: Path, path: Path) -> str:
    return path.resolve(strict=False).relative_to(root).as_posix()


def _is_link(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or (callable(is_junction) and is_junction())


def _is_within_root(root: Path, path: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root)
    except ValueError:
        return False
    return True


def _iter_manifests(root: Path):
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        directories[:] = [
            name
            for name in directories
            if not _is_link(Path(current, name))
        ]
        for name in files:
            path = Path(current, name)
            if name.casefold() == "manifest.json" and not _is_link(path):
                if _is_within_root(root, path):
                    yield path


def _read_utf8(path: Path) -> tuple[bytes, str] | None:
    try:
        raw = path.read_bytes()
        return raw, raw.decode("utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None


def _manifest_document(path: Path) -> dict[str, object] | None:
    content = _read_utf8(path)
    if content is None:
        return None
    _raw, text = content
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        return None
    return document if isinstance(document, dict) else None


def _module_type(document: dict[str, object]) -> str:
    modules = document.get("modules")
    if not isinstance(modules, list) or not modules:
        return ""
    first = modules[0]
    return str(first.get("type", "")) if isinstance(first, dict) else ""


def _required_directory(module_type: str) -> str:
    if module_type in _BEHAVIOR_MODULE_TYPES:
        return "entities"
    if module_type == _RESOURCE_MODULE_TYPE:
        return "textures"
    return ""


def _candidate_id(
    root: Path,
    kind: str,
    source_path: Path,
    target_path: Path,
    source_digest: str = "",
) -> str:
    material = "\0".join(
        (kind, _relative(root, source_path), _relative(root, target_path), source_digest)
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def discover_repairs(project_dir: str) -> list[RepairCandidate]:
    """只从当前可验证的工程状态生成修复计划，不写入任何文件。"""

    root = _project_root(project_dir)
    from .blocking_repair_basic_actions import discover_basic_repairs
    from .blocking_repair_extensions import discover_extra_repairs

    candidates = [*discover_basic_repairs(root), *discover_extra_repairs(root)]
    return sorted(candidates, key=lambda item: (item.kind, _relative(root, item.display_path)))


def is_non_code_issue(code: int, title: str) -> bool:
    return code in NON_CODE_ERROR_CODES or (code, title) in NON_CODE_ERROR_TITLES


def issue_guidance(code: int, title: str) -> str:
    if code == 18 and title == "工程包含编辑信息":
        return "可安全删除的工作台编辑信息会在上方显示为确认清理项。"
    if code == 18:
        return "这是代码或 API 审核问题，必须修改源码后重新审核。"
    if code in {24, 36}:
        return "安全缓存、编译产物和编辑信息会显示为确认清理项；.git 等受保护内容不会自动删除。"
    if code in {6, 10}:
        return "仅当能无冲突确定组件包目标目录时会显示迁移项；缺 manifest、structures 引用等情况需人工处理。"
    if code == 23:
        return "仅 level.dat 或 level.dat_old 的只读属性可自动解除；其他写入失败需检查文件占用和权限。"
    if code in {29, 37, 40}:
        return "存在经过源码规则验证的修复时会显示在上方；无法验证的内容保持只读。"
    if code == 38:
        return "可解析的 JSON 注释、UTF-8 BOM 会显示修复项；未知编码或损坏结构不能可靠自动转换。"
    if code in {0, 12, 13, 30, 31}:
        return "涉及工程类型或世界数据，程序不会生成、删除或降级世界数据。"
    if code == 35 and "标识符" in title:
        return "这是 Python 代码标识符审核问题，必须修改源码后重新审核。"
    if code in {16, 27, 35}:
        return "重命名可能遗漏资源引用或改变代码标识符，需人工确认后处理。"
    if code == 34:
        return "仅 8-bit RGBA 字体图的全透明像素 RGB 残留可无视觉变化归零；尺寸、位深和结构问题需人工处理。"
    if code in {25, 26, 33}:
        return "解析、贴图、音频和位图字体需要保留资源语义，程序只定位，不会盲目重写。"
    if code == 20:
        return "resource_pack 的目标名称无法从工程内容唯一确定，需人工选择正确目录结构。"
    if code == 41:
        return "这是性能警告而非机审阻断项，需要结合真实玩法采样优化代码。"
    return "该问题暂无可验证的自动修复方案，已保留原始定位。"


def _display_issue_path(root: Path, value: object) -> str:
    if not isinstance(value, str) or not value:
        return ""
    path = Path(value)
    if path.is_absolute() and _is_within_root(root, path):
        return _relative(root, path)
    return value


def _blocking_preview(root: Path) -> tuple[int, int, list[dict[str, object]]]:
    issues = scan(str(root))
    errors = [issue for issue in issues if issue.severity == "error"]
    warnings = sum(1 for issue in issues if issue.severity == "warning")
    preview: list[dict[str, object]] = []
    for issue in errors[:BLOCKING_ISSUE_PREVIEW_LIMIT]:
        item = issue.as_dict()
        item["path"] = _display_issue_path(root, item.get("path"))
        item["guidance"] = issue_guidance(issue.code, issue.title)
        preview.append(item)
    return len(errors), warnings, preview


def _inspection_message(repair_count: int, error_count: int) -> str:
    if repair_count:
        return f"已发现 {repair_count} 项可自动优化项；执行后会自动复审。"
    if error_count:
        return "没有可安全自动修复的项目；其余阻塞项已保持只读。"
    return "未发现可自动优化的阻塞项。"


def _build_state(root: Path) -> dict[str, object]:
    candidates = discover_repairs(str(root))
    error_count, warning_count, preview = _blocking_preview(root)
    return {
        "phase": "ready",
        "rootPath": str(root),
        "message": _inspection_message(len(candidates), error_count),
        "repairableCount": len(candidates),
        "auditErrorCount": error_count,
        "auditWarningCount": warning_count,
        "items": [candidate.as_dict(root) for candidate in candidates],
        "blockingPreview": preview,
        "blockingPreviewTruncated": error_count > len(preview),
    }


def _atomic_write(path: Path, content: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(
        prefix=".mcn_repair_", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


def _apply_candidate(candidate: RepairCandidate) -> list[Path]:
    for path in (candidate.source_path, candidate.target_path):
        if not _is_within_root(candidate.root_path, path):
            raise ValueError("修复目标已离开工程目录，请重新检查")
        if path.exists() and _is_link(path):
            raise ValueError("修复目标已变为链接，请重新检查")
    from .blocking_repair_basic_actions import apply_basic_candidate
    from .blocking_repair_extensions import apply_extra_candidate

    basic_result = apply_basic_candidate(candidate)
    if basic_result is not None:
        return basic_result
    return apply_extra_candidate(candidate)


class BlockingRepairService:
    """为桌面页提供预览、确认写入和自动复审的纯逻辑服务。"""

    @staticmethod
    def inspect(project_dir: str) -> dict[str, object]:
        return _build_state(_project_root(project_dir))

    @staticmethod
    def apply_and_inspect(
        project_dir: str,
        repair_id: str,
    ) -> tuple[dict[str, object], dict[str, object]]:
        root = _project_root(project_dir)
        candidates = {candidate.identifier: candidate for candidate in discover_repairs(str(root))}
        candidate = candidates.get(repair_id)
        if candidate is None:
            raise ValueError("修复计划已过期或不存在，请重新检查")
        applied = _apply_candidate(candidate)
        if isinstance(applied, RepairApplyResult):
            changed_paths = applied.changed_paths
            undo = applied.undo
        else:
            changed_paths = applied
            undo = None
        try:
            state = _build_state(root)
        except Exception as error:
            if undo is None:
                raise
            from .blocking_repair_extensions import restore_safe_residue

            try:
                restore_safe_residue(root, undo)
            except Exception as rollback_error:
                raise OSError("修复后复审失败且隔离清理撤销失败") from rollback_error
            raise OSError("修复后复审失败，已自动撤销隔离清理") from error
        outcome: dict[str, object] = {
            "success": True,
            "message": f"已完成“{candidate.title}”，并已自动复审。",
            "changedPaths": [_relative(root, path) for path in changed_paths],
        }
        if undo is not None:
            outcome["undo"] = undo
        return state, outcome

    @staticmethod
    def restore_and_inspect(
        project_dir: str,
        undo: dict[str, str],
    ) -> tuple[dict[str, object], dict[str, object]]:
        from .blocking_repair_extensions import restore_safe_residue

        root = _project_root(project_dir)
        restored_path = restore_safe_residue(root, undo)
        state = _build_state(root)
        return state, {
            "success": True,
            "message": "已恢复上次清理的打包残留，并已自动复审。",
            "changedPaths": [_relative(root, restored_path)],
            "clearUndo": True,
        }


__all__ = [
    "BLOCKING_ISSUE_PREVIEW_LIMIT",
    "BlockingRepairService",
    "KNOWN_AUDIT_ERROR_CODES",
    "NON_CODE_ERROR_CODES",
    "NON_CODE_ERROR_TITLES",
    "REPAIR_CLEAR_LEVEL_READONLY",
    "REPAIR_CREATE_REQUIRED_DIRECTORY",
    "REPAIR_FIX_PLAYER_CONTROLLERS",
    "REPAIR_MOVE_PACK_LAYOUT",
    "REPAIR_NORMALIZE_GLYPH_TRANSPARENCY",
    "REPAIR_NORMALIZE_MANIFEST_COMMENTS",
    "REPAIR_NORMALIZE_JSON_BOM",
    "REPAIR_REMOVE_SAFE_RESIDUE",
    "REPAIR_RENAME_RESOURCE_ENTITIES",
    "REPAIR_SET_MIN_ENGINE_VERSION",
    "RepairApplyResult",
    "RepairCandidate",
    "discover_repairs",
    "empty_repair_state",
    "is_non_code_issue",
    "issue_guidance",
]
