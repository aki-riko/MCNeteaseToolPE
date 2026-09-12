# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""目录、资源包和 manifest 基础确认修复动作。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .blocking_repair import (
    REPAIR_CREATE_REQUIRED_DIRECTORY,
    REPAIR_NORMALIZE_MANIFEST_COMMENTS,
    REPAIR_RENAME_RESOURCE_ENTITIES,
    RepairCandidate,
    _atomic_write,
    _candidate_id,
    _is_link,
    _is_within_root,
    _iter_manifests,
    _manifest_document,
    _module_type,
    _read_utf8,
    _required_directory,
)
from .pack_scanner import _strip_json_comments


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
    if _module_type(document) != "resources":
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


def discover_basic_repairs(root: Path) -> list[RepairCandidate]:
    candidates: list[RepairCandidate] = []
    for manifest in _iter_manifests(root):
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
    replacement = json.dumps(document, ensure_ascii=False, indent=4, allow_nan=False).encode("utf-8") + b"\n"
    try:
        _atomic_write(candidate.target_path, replacement)
        parsed = json.loads(candidate.target_path.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("写入后的 manifest 顶层不是对象")
    except Exception as error:
        try:
            _atomic_write(candidate.target_path, raw)
        except Exception as rollback_error:
            raise OSError("manifest 写入校验失败且回滚失败") from rollback_error
        raise OSError("manifest 写入校验失败，已回滚原文件") from error
    return [candidate.target_path]


def apply_basic_candidate(candidate: RepairCandidate) -> list[Path] | None:
    handlers = {
        REPAIR_CREATE_REQUIRED_DIRECTORY: _create_required_directory,
        REPAIR_RENAME_RESOURCE_ENTITIES: _rename_resource_entities,
        REPAIR_NORMALIZE_MANIFEST_COMMENTS: _normalize_manifest_comments,
    }
    handler = handlers.get(candidate.kind)
    return handler(candidate) if handler is not None else None


__all__ = ["apply_basic_candidate", "discover_basic_repairs"]
