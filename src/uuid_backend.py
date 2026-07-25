# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
# UUID 后端的 Python 实现。
# Python implementation of the UUID backend.

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import tempfile
import uuid

from PySide6.QtCore import QObject, Signal, Slot

from .pack_scanner import (
    _absolute,
    _collect_pack_dirs,
    _json_document,
    _manifest_type,
)
from .project_structure import is_map_project


LOGGER = logging.getLogger(__name__)
WORLD_BINDING_FILES = {
    "behavior": "world_behavior_packs.json",
    "resource": "world_resource_packs.json",
}


@dataclass(frozen=True)
class _Pack:
    directory: str
    manifest_path: str
    name: str
    pack_type: str


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _packs(root: str) -> list[_Pack]:
    result: list[_Pack] = []
    for directory in _collect_pack_dirs(root):
        manifest = os.path.join(directory, "manifest.json")
        module_type = _manifest_type(manifest)
        if module_type in {"data", "client_data", "javascript"}:
            pack_type = "behavior"
        elif module_type == "resources":
            pack_type = "resource"
        elif module_type == "skin_pack":
            pack_type = "skin"
        else:
            pack_type = module_type or "other"
        result.append(_Pack(directory, manifest, os.path.basename(directory), pack_type))
    return result


def _structure_type(root: str) -> str:
    if is_map_project(root):
        return "标准存档(地图)"
    if os.path.isdir(os.path.join(root, "behavior_packs")) or os.path.isdir(os.path.join(root, "resource_packs")):
        return "MCStudio 工程"
    return "扁平 Add-on"


def _read_manifest(path: str) -> dict[str, object] | None:
    document = _json_document(path)
    return document if isinstance(document, dict) else None


def _write_json_atomic(path: str, document: object) -> None:
    directory = os.path.dirname(path)
    fd, temporary = tempfile.mkstemp(prefix=".mcn_manifest_", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=4)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError as cleanup_error:
            LOGGER.warning("清理 UUID 临时文件失败 %s: %s", temporary, cleanup_error)
        raise


def _manifest_version(document: dict[str, object], pack_name: str) -> list[int]:
    header = document.get("header")
    version = header.get("version") if isinstance(header, dict) else None
    if not (
        isinstance(version, list)
        and len(version) == 3
        and all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in version)
    ):
        raise ValueError(f"地图组件包 {pack_name} 的 manifest header.version 必须是三个非负整数")
    return list(version)


def _binding_type(path: str) -> str | None:
    if not os.path.isfile(path):
        return None
    document = _json_document(path)
    if not isinstance(document, list):
        raise ValueError(f"{os.path.basename(path)} 必须是 JSON 数组")
    return next(
        (
            item["type"]
            for item in document
            if isinstance(item, dict) and isinstance(item.get("type"), str)
        ),
        None,
    )


def _world_binding_updates(
    root: str,
    pending: list[tuple[_Pack, dict[str, object]]],
) -> list[tuple[str, list[dict[str, object]]]]:
    updates: list[tuple[str, list[dict[str, object]]]] = []
    for pack_type, filename in WORLD_BINDING_FILES.items():
        selected = [(pack, document) for pack, document in pending if pack.pack_type == pack_type]
        if not selected:
            continue
        path = os.path.join(root, filename)
        binding_type = _binding_type(path)
        payload: list[dict[str, object]] = []
        for pack, document in selected:
            header = document["header"]
            item: dict[str, object] = {
                "pack_id": header["uuid"],
                "version": _manifest_version(document, pack.name),
            }
            if binding_type is not None:
                item["type"] = binding_type
            payload.append(item)
        updates.append((path, payload))
    return updates


def _analyze(root_dir: str) -> tuple[str, list[str], list[tuple[str, str]]]:
    root = _absolute(root_dir)
    if not os.path.isdir(root):
        return "", [], [("error", f"目录无效:{root_dir}")]
    packs = _packs(root)
    if not packs:
        if is_map_project(root):
            return "标准存档(地图)", [], [("success", "地图未包含组件包,无需重写 UUID")]
        return "", [], [("error", "未找到任何 manifest.json,无法识别 MC 工程结构")]
    summaries = [f"[{pack.pack_type}] {pack.name}" for pack in packs]
    return _structure_type(root), summaries, [("success", f"识别到 {len(packs)} 个包(结构:{_structure_type(root)})")]


def _replace_module_uuids(document: dict[str, object]) -> None:
    modules = document.get("modules")
    if not isinstance(modules, list):
        return
    rewritten: list[object] = []
    for module in modules:
        if isinstance(module, dict):
            module = dict(module)
            module["uuid"] = _new_uuid()
        rewritten.append(module)
    document["modules"] = rewritten


def _prepare_manifests(
    packs: list[_Pack],
    logs: list[tuple[str, str]],
) -> tuple[list[tuple[_Pack, dict[str, object]]], dict[str, str]]:
    pending: list[tuple[_Pack, dict[str, object]]] = []
    uuid_map: dict[str, str] = {}
    for pack in packs:
        document = _read_manifest(pack.manifest_path)
        if document is None:
            logs.append(("warn", f"跳过(json 解析失败):{pack.name}"))
            continue
        header = document.get("header")
        if not isinstance(header, dict):
            header = {}
        old_uuid = str(header.get("uuid", ""))
        fresh_uuid = _new_uuid()
        if old_uuid:
            uuid_map[old_uuid] = fresh_uuid
        header["uuid"] = fresh_uuid
        document["header"] = header
        _replace_module_uuids(document)
        pending.append((pack, document))
    return pending, uuid_map


def _rewrite_dependencies(document: dict[str, object], uuid_map: dict[str, str]) -> None:
    dependencies = document.get("dependencies")
    if not isinstance(dependencies, list):
        return
    rewritten: list[object] = []
    for dependency in dependencies:
        if isinstance(dependency, dict):
            dependency = dict(dependency)
            dependency_uuid = dependency.get("uuid")
            if dependency_uuid in uuid_map:
                dependency["uuid"] = uuid_map[dependency_uuid]
        rewritten.append(dependency)
    document["dependencies"] = rewritten


def _write_manifests(
    pending: list[tuple[_Pack, dict[str, object]]],
    logs: list[tuple[str, str]],
) -> int:
    changed = 0
    for pack, document in pending:
        try:
            _write_json_atomic(pack.manifest_path, document)
        except OSError as error:
            logs.append(("error", f"写入失败:{pack.manifest_path} ({error})"))
            continue
        changed += 1
        logs.append(("info", f"已更新:{pack.manifest_path}"))
    return changed


def _write_world_bindings(
    updates: list[tuple[str, list[dict[str, object]]]],
    logs: list[tuple[str, str]],
) -> None:
    for path, document in updates:
        _write_json_atomic(path, document)
        logs.append(("info", f"已同步地图绑定:{path}"))


def _generate(root_dir: str) -> tuple[bool, int, str, list[tuple[str, str]]]:
    root = _absolute(root_dir)
    if not os.path.isdir(root):
        return False, 0, "目录无效", []
    packs = _packs(root)
    if not packs:
        if is_map_project(root):
            message = "地图未包含组件包,无需重写 UUID"
            return True, 0, message, [("success", message)]
        return False, 0, "未找到 manifest.json", []

    logs: list[tuple[str, str]] = []
    pending, uuid_map = _prepare_manifests(packs, logs)
    for _pack, document in pending:
        _rewrite_dependencies(document, uuid_map)

    map_project = is_map_project(root)
    if map_project and len(pending) != len(packs):
        return False, 0, "地图组件包 manifest 解析失败,未执行 UUID 重写", logs
    world_updates = _world_binding_updates(root, pending) if map_project else []

    changed = _write_manifests(pending, logs)
    if map_project and changed != len(pending):
        return False, changed, "地图组件包未全部写入,未同步 world 绑定", logs
    _write_world_bindings(world_updates, logs)
    return changed > 0, changed, f"完成,共重写 {changed} 个 manifest 的 UUID", logs


class UuidBackend(QObject):
    """UUID 重写后端。"""

    logMessage = Signal(str, str)
    analyzed = Signal(str, list)
    finished = Signal(bool, int, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._task_handle = None

    @Slot(str)
    def analyze(self, project_dir: str) -> None:
        from prismqml import run_in_pool

        handle = run_in_pool(_analyze, project_dir)
        self._task_handle = handle
        handle.succeeded.connect(self._on_analyzed)
        handle.failed.connect(self._on_task_failed)

    @Slot(str)
    def generate(self, project_dir: str) -> None:
        from prismqml import run_in_pool

        handle = run_in_pool(_generate, project_dir)
        self._task_handle = handle
        handle.succeeded.connect(self._on_generated)
        handle.failed.connect(self._on_task_failed)

    @Slot(object)
    def _on_analyzed(self, result: tuple[str, list[str], list[tuple[str, str]]]) -> None:
        structure, summaries, logs = result
        for level, message in logs:
            self.logMessage.emit(message, level)
        self.analyzed.emit(structure, summaries)

    @Slot(object)
    def _on_generated(self, result: tuple[bool, int, str, list[tuple[str, str]]]) -> None:
        success, changed, message, logs = result
        for level, text in logs:
            self.logMessage.emit(text, level)
        self.finished.emit(success, changed, message)

    @Slot(object)
    def _on_task_failed(self, failure: object) -> None:
        exception = getattr(failure, "exception", failure)
        LOGGER.error("UUID 后台任务失败: %s", exception, exc_info=True)
        self.finished.emit(False, 0, f"UUID 操作失败:{exception}")


__all__ = ["UuidBackend"]
