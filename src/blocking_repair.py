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

from .pack_scanner import _strip_json_comments, scan


REPAIR_CREATE_REQUIRED_DIRECTORY = "create_required_directory"
REPAIR_NORMALIZE_MANIFEST_COMMENTS = "normalize_manifest_comments"
REPAIR_RENAME_RESOURCE_ENTITIES = "rename_resource_entities"
BLOCKING_ISSUE_PREVIEW_LIMIT = 8

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

    def as_dict(self, root: Path) -> dict[str, str]:
        return {
            "id": self.identifier,
            "kind": self.kind,
            "title": self.title,
            "detail": self.detail,
            "change": self.change,
            "path": _relative(root, self.display_path),
        }


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


def _missing_directory_candidate(
    root: Path,
    manifest: Path,
    document: dict[str, object],
) -> RepairCandidate | None:
    required_name = _required_directory(_module_type(document))
    target = manifest.parent / required_name if required_name else None
    if target is None or target.exists() or not _is_within_root(root, target):
        return None
    title = "补全行为包必需目录" if required_name == "entities" else "补全资源包必需目录"
    return RepairCandidate(
        root,
        _candidate_id(root, REPAIR_CREATE_REQUIRED_DIRECTORY, manifest, target),
        REPAIR_CREATE_REQUIRED_DIRECTORY,
        title,
        f"{manifest.parent.name} 缺少 {required_name}，网易打包前置检查会要求该目录存在。",
        f"新增空目录 {required_name}，不会修改现有文件。",
        target,
        manifest,
        target,
    )


def _resource_entities_candidate(
    root: Path,
    manifest: Path,
    document: dict[str, object],
) -> RepairCandidate | None:
    if _module_type(document) != _RESOURCE_MODULE_TYPE:
        return None
    source = manifest.parent / "entities"
    target = manifest.parent / "entity"
    if not source.is_dir() or target.exists() or _is_link(source):
        return None
    if not _is_within_root(root, source) or not _is_within_root(root, target):
        return None
    return RepairCandidate(
        root,
        _candidate_id(root, REPAIR_RENAME_RESOURCE_ENTITIES, source, target),
        REPAIR_RENAME_RESOURCE_ENTITIES,
        "更正资源包实体目录名称",
        "资源包中的 entities 会被网易机审误判为行为包目录。",
        "将 entities 原子重命名为 entity，保留其中全部文件。",
        source,
        source,
        target,
    )


def _comment_manifest_candidate(root: Path, manifest: Path) -> RepairCandidate | None:
    content = _read_utf8(manifest)
    if content is None:
        return None
    raw, text = content
    stripped = _strip_json_comments(text)
    if stripped == text:
        return None
    try:
        json.loads(text)
        return None
    except json.JSONDecodeError:
        pass
    try:
        document = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(document, dict):
        return None
    digest = hashlib.sha256(raw).hexdigest()
    return RepairCandidate(
        root,
        _candidate_id(root, REPAIR_NORMALIZE_MANIFEST_COMMENTS, manifest, manifest, digest),
        REPAIR_NORMALIZE_MANIFEST_COMMENTS,
        "移除 manifest JSON 注释",
        "当前 manifest 在移除注释后可完整解析；注释会导致网易打包机拒绝该文件。",
        "以 UTF-8 重新输出等价 JSON，仅移除注释与原有排版。",
        manifest,
        manifest,
        manifest,
        digest,
    )


def discover_repairs(project_dir: str) -> list[RepairCandidate]:
    """只从当前可验证的工程状态生成修复计划，不写入任何文件。"""

    root = _project_root(project_dir)
    candidates: list[RepairCandidate] = []
    for manifest in sorted(_iter_manifests(root), key=lambda item: _relative(root, item)):
        document = _manifest_document(manifest)
        if document is not None:
            for candidate in (
                _missing_directory_candidate(root, manifest, document),
                _resource_entities_candidate(root, manifest, document),
            ):
                if candidate is not None:
                    candidates.append(candidate)
        comment_candidate = _comment_manifest_candidate(root, manifest)
        if comment_candidate is not None:
            candidates.append(comment_candidate)
    return candidates


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


def _create_required_directory(candidate: RepairCandidate) -> list[Path]:
    target = candidate.target_path
    if target.exists() or not target.parent.is_dir():
        raise ValueError("必需目录的工程状态已变化，请重新检查")
    target.mkdir()
    if not target.is_dir() or _is_link(target):
        raise OSError(f"未能创建安全目录:{target}")
    return [target]


def _rename_resource_entities(candidate: RepairCandidate) -> list[Path]:
    source, target = candidate.source_path, candidate.target_path
    if not source.is_dir() or _is_link(source) or target.exists():
        raise ValueError("资源目录的工程状态已变化，请重新检查")
    source.rename(target)
    if target.is_dir() and not _is_link(target):
        return [target]
    if target.exists() and not source.exists():
        target.rename(source)
    raise OSError(f"未能确认目录重命名结果:{target}")


def _normalize_manifest_comments(candidate: RepairCandidate) -> list[Path]:
    content = _read_utf8(candidate.source_path)
    if content is None:
        raise OSError(f"无法读取 manifest:{candidate.source_path}")
    raw, text = content
    if hashlib.sha256(raw).hexdigest() != candidate.source_digest:
        raise ValueError("manifest 已变化，请重新检查后再修复")
    try:
        document = json.loads(_strip_json_comments(text))
    except json.JSONDecodeError as error:
        raise ValueError("manifest 注释移除后仍无法解析，未执行修改") from error
    replacement = json.dumps(document, ensure_ascii=False, indent=4).encode("utf-8") + b"\n"
    try:
        _atomic_write(candidate.target_path, replacement)
        json.loads(candidate.target_path.read_text(encoding="utf-8"))
    except Exception as error:
        try:
            _atomic_write(candidate.target_path, raw)
        except Exception as rollback_error:
            raise OSError("manifest 写入校验失败且回滚失败") from rollback_error
        raise OSError("manifest 写入校验失败，已回滚原文件") from error
    return [candidate.target_path]


def _apply_candidate(candidate: RepairCandidate) -> list[Path]:
    for path in (candidate.source_path, candidate.target_path):
        if not _is_within_root(candidate.root_path, path):
            raise ValueError("修复目标已离开工程目录，请重新检查")
        if path.exists() and _is_link(path):
            raise ValueError("修复目标已变为链接，请重新检查")
    handlers = {
        REPAIR_CREATE_REQUIRED_DIRECTORY: _create_required_directory,
        REPAIR_RENAME_RESOURCE_ENTITIES: _rename_resource_entities,
        REPAIR_NORMALIZE_MANIFEST_COMMENTS: _normalize_manifest_comments,
    }
    handler = handlers.get(candidate.kind)
    if handler is None:
        raise ValueError("未知的修复类型")
    return handler(candidate)


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
        changed_paths = _apply_candidate(candidate)
        state = _build_state(root)
        return state, {
            "success": True,
            "message": f"已完成“{candidate.title}”，并已自动复审。",
            "changedPaths": [_relative(root, path) for path in changed_paths],
        }


__all__ = [
    "BLOCKING_ISSUE_PREVIEW_LIMIT",
    "BlockingRepairService",
    "REPAIR_CREATE_REQUIRED_DIRECTORY",
    "REPAIR_NORMALIZE_MANIFEST_COMMENTS",
    "REPAIR_RENAME_RESOURCE_ENTITIES",
    "RepairCandidate",
    "discover_repairs",
    "empty_repair_state",
]
