# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""Manifest、玩家实体与组件包层级的确认修复动作。"""

from __future__ import annotations

from pathlib import Path
import re

from .blocking_repair import (
    REPAIR_FIX_PLAYER_CONTROLLERS,
    REPAIR_MOVE_PACK_LAYOUT,
    REPAIR_SET_MIN_ENGINE_VERSION,
    RepairCandidate,
    _is_within_root,
    _iter_manifests,
    _manifest_document,
    _module_type,
    _relative,
)
from .blocking_repair_extensions import (
    _candidate,
    _canonical_json,
    _current_json,
    _is_link,
    _iter_files,
    _path_fingerprint,
    _raw_digest,
    _read_jsonc,
    _replace_and_verify,
)
from .config import AUDIT_MIN_ENGINE_VERSION
from .netease_content_audit import PLAYER_RENDER_CONTROLLERS


_BEHAVIOR_MODULE_TYPES = frozenset({"data", "client_data", "javascript"})
_RESOURCE_MODULE_TYPE = "resources"


def _minimum_engine_needs_update(document: dict[str, object]) -> bool:
    header = document.get("header")
    if not isinstance(header, dict):
        return False
    version = header.get("min_engine_version")
    if not isinstance(version, list) or len(version) < 2:
        return True
    try:
        major, minor = int(version[0]), int(version[1])
    except (TypeError, ValueError):
        return True
    return (major, minor) < AUDIT_MIN_ENGINE_VERSION[:2]


def _minimum_engine_candidates(root: Path) -> list[RepairCandidate]:
    candidates: list[RepairCandidate] = []
    for manifest in _iter_manifests(root):
        document = _manifest_document(manifest)
        if document is None or not _minimum_engine_needs_update(document):
            continue
        raw = manifest.read_bytes()
        candidates.append(
            _candidate(
                root,
                REPAIR_SET_MIN_ENGINE_VERSION,
                "补全最低引擎版本",
                "当前 manifest 缺少或低于审核要求的 min_engine_version。",
                f"将 header.min_engine_version 设为 {list(AUDIT_MIN_ENGINE_VERSION)}。",
                manifest,
                manifest,
                manifest,
                _raw_digest(raw),
                impact="会提高该组件包可加载的最低客户端版本，旧版本客户端将无法使用它。",
            )
        )
    return candidates


def _invalid_player_controller_names(document: object) -> list[str] | None:
    if not isinstance(document, dict):
        return None
    client = document.get("minecraft:client_entity")
    description = client.get("description") if isinstance(client, dict) else None
    controllers = description.get("render_controllers", []) if isinstance(description, dict) else None
    if not isinstance(controllers, list):
        return None
    present: dict[str, str] = {}
    for entry in controllers:
        if isinstance(entry, dict):
            present.update((str(key), re.sub(r"\s+", "", str(value))) for key, value in entry.items())
    return [
        name
        for name, expression in PLAYER_RENDER_CONTROLLERS.items()
        if present.get(name) != re.sub(r"\s+", "", expression)
    ]


def _player_controller_candidates(root: Path) -> list[RepairCandidate]:
    candidates: list[RepairCandidate] = []
    for path in _iter_files(root, ".json"):
        if path.name.casefold() != "player.entity.json" or path.parent.name.casefold() != "entity":
            continue
        content = _read_jsonc(path)
        if content is None:
            continue
        raw, document = content
        invalid = _invalid_player_controller_names(document)
        if not invalid:
            continue
        candidates.append(
            _candidate(
                root,
                REPAIR_FIX_PLAYER_CONTROLLERS,
                "修正 player.entity 渲染控制器",
                "当前玩家实体缺少审核要求的渲染控制器，或条件表达式不符合固定规则。",
                f"写入已验证的控制器条件：{'、'.join(invalid)}。",
                path,
                path,
                path,
                _raw_digest(raw),
                impact="会调整玩家第一、第三人称的渲染控制器条件。",
            )
        )
    return candidates


def _expected_pack_collection(module_type: str) -> str:
    if module_type in _BEHAVIOR_MODULE_TYPES:
        return "behavior_packs"
    if module_type == _RESOURCE_MODULE_TYPE:
        return "resource_packs"
    return ""


def _is_nested_in(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def _is_pack_collection(path: Path) -> bool:
    return path.name.casefold() in {"behavior_packs", "resource_packs"}


def _is_complete_pack_boundary(source: Path, manifest: Path) -> bool:
    manifests = list(_iter_manifests(source))
    if len(manifests) != 1 or manifests[0].resolve() != manifest.resolve():
        return False
    if _is_pack_collection(source.parent):
        return True
    try:
        entries = [entry for entry in source.parent.iterdir() if not _is_link(entry)]
    except OSError:
        return False
    return entries == [source]


def _pack_layout_candidate(root: Path, manifest: Path) -> RepairCandidate | None:
    document = _manifest_document(manifest)
    if document is None:
        return None
    source = manifest.parent
    if source == root or _is_link(source):
        return None
    relative = manifest.relative_to(root)
    map_project = (root / "level.dat").is_file()
    if map_project:
        valid = len(relative.parts) == 3 and relative.parts[0].casefold() in {
            "behavior_packs",
            "resource_packs",
        }
        destination_parent = root / _expected_pack_collection(_module_type(document))
    else:
        valid = len(relative.parts) == 2
        destination_parent = root
    if valid or destination_parent == root and len(relative.parts) < 2:
        return None
    if destination_parent == root and map_project:
        return None
    target = destination_parent / source.name
    if target.exists() or _is_nested_in(source, target):
        return None
    if not _is_within_root(root, source) or not _is_within_root(root, target):
        return None
    if not _is_complete_pack_boundary(source, manifest):
        return None
    fingerprint = _path_fingerprint(source)
    if not fingerprint:
        return None
    destination = _relative(root, target)
    return _candidate(
        root,
        REPAIR_MOVE_PACK_LAYOUT,
        "整理组件包目录层级",
        f"当前组件包不在机审要求的位置；可无冲突迁移至 {destination}。",
        f"移动整个组件包目录到 {destination}，不修改包内文件。",
        source,
        source,
        target,
        fingerprint,
        impact="仅移动完整组件包目录；不会改写包内文件，但自定义外部路径引用需人工确认。",
    )


def _pack_layout_candidates(root: Path) -> list[RepairCandidate]:
    return [
        candidate
        for manifest in _iter_manifests(root)
        if (candidate := _pack_layout_candidate(root, manifest)) is not None
    ]


def discover_manifest_repairs(root: Path) -> list[RepairCandidate]:
    return [
        *_minimum_engine_candidates(root),
        *_player_controller_candidates(root),
        *_pack_layout_candidates(root),
    ]


def _verify_minimum_engine(path: Path) -> None:
    content = _read_jsonc(path)
    if content is None or not isinstance(content[1], dict):
        raise ValueError("写入后的 manifest 无法解析")
    if _minimum_engine_needs_update(content[1]):
        raise ValueError("写入后的 manifest 仍不满足最低引擎版本")


def _verify_player_controllers(path: Path) -> None:
    content = _read_jsonc(path)
    if content is None or _invalid_player_controller_names(content[1]):
        raise ValueError("写入后的玩家渲染控制器仍不符合审核规则")


def _set_minimum_engine_version(candidate: RepairCandidate) -> list[Path]:
    raw, document = _current_json(candidate)
    if not isinstance(document, dict) or not _minimum_engine_needs_update(document):
        raise ValueError("manifest 状态已变化，请重新检查")
    header = document.get("header")
    if not isinstance(header, dict):
        raise ValueError("manifest header 不是对象，无法安全修复")
    header["min_engine_version"] = list(AUDIT_MIN_ENGINE_VERSION)
    _replace_and_verify(
        candidate.target_path,
        raw,
        _canonical_json(document),
        lambda: _verify_minimum_engine(candidate.target_path),
    )
    return [candidate.target_path]


def _repair_player_controller_document(document: dict[str, object]) -> None:
    client = document["minecraft:client_entity"]
    description = client["description"]
    controllers = description.get("render_controllers", [])
    repaired: list[object] = []
    present: set[str] = set()
    for entry in controllers:
        if not isinstance(entry, dict):
            repaired.append(entry)
            continue
        copied = dict(entry)
        for name, expression in PLAYER_RENDER_CONTROLLERS.items():
            if name in copied:
                copied[name] = expression
                present.add(name)
        repaired.append(copied)
    for name, expression in PLAYER_RENDER_CONTROLLERS.items():
        if name not in present:
            repaired.append({name: expression})
    description["render_controllers"] = repaired


def _fix_player_controllers(candidate: RepairCandidate) -> list[Path]:
    raw, document = _current_json(candidate)
    invalid = _invalid_player_controller_names(document)
    if not invalid or not isinstance(document, dict):
        raise ValueError("玩家实体配置已变化，请重新检查")
    _repair_player_controller_document(document)
    _replace_and_verify(
        candidate.target_path,
        raw,
        _canonical_json(document),
        lambda: _verify_player_controllers(candidate.target_path),
    )
    return [candidate.target_path]


def _move_pack_layout(candidate: RepairCandidate) -> list[Path]:
    source, target = candidate.source_path, candidate.target_path
    if not source.is_dir() or target.exists() or _is_link(source):
        raise ValueError("组件包目录已变化，请重新检查")
    if _path_fingerprint(source) != candidate.source_digest:
        raise ValueError("组件包目录已变化，请重新检查")
    created_parent = not target.parent.exists()
    if created_parent:
        target.parent.mkdir()
    try:
        source.rename(target)
        manifests = list(_iter_manifests(target))
        if len(manifests) != 1 or manifests[0].parent != target:
            raise OSError("迁移后的组件包边界不完整")
        if _path_fingerprint(target) != candidate.source_digest:
            raise OSError("迁移后的组件包内容与预览不一致")
    except Exception:
        if target.exists() and not source.exists():
            target.rename(source)
        if created_parent and target.parent.exists() and not any(target.parent.iterdir()):
            target.parent.rmdir()
        raise
    return [target]


def apply_manifest_candidate(candidate: RepairCandidate) -> list[Path] | None:
    handlers = {
        REPAIR_SET_MIN_ENGINE_VERSION: _set_minimum_engine_version,
        REPAIR_FIX_PLAYER_CONTROLLERS: _fix_player_controllers,
        REPAIR_MOVE_PACK_LAYOUT: _move_pack_layout,
    }
    handler = handlers.get(candidate.kind)
    return handler(candidate) if handler is not None else None


__all__ = ["apply_manifest_candidate", "discover_manifest_repairs"]
