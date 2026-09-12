# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""非代码阻塞项修复的计划、写入和异步边界回归测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.blocking_repair import (
    BlockingRepairService,
    REPAIR_CREATE_REQUIRED_DIRECTORY,
    REPAIR_NORMALIZE_MANIFEST_COMMENTS,
    REPAIR_REMOVE_SAFE_RESIDUE,
    REPAIR_RENAME_RESOURCE_ENTITIES,
)
from src.blocking_repair_backend import BlockingRepairBackend
from src.pack_scanner import scan


def _manifest(module_type: str) -> dict[str, object]:
    return {
        "header": {
            "uuid": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "version": [1, 0, 0],
            "min_engine_version": [1, 20, 0],
        },
        "modules": [
            {
                "type": module_type,
                "uuid": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            }
        ],
    }


def _write_manifest(directory: Path, module_type: str) -> Path:
    directory.mkdir(parents=True)
    path = directory / "manifest.json"
    path.write_text(json.dumps(_manifest(module_type)), encoding="utf-8")
    return path


def _repair_id(state: dict[str, object], kind: str) -> str:
    items = state["items"]
    assert isinstance(items, list)
    for item in items:
        if isinstance(item, dict) and item.get("kind") == kind:
            return str(item["id"])
    raise AssertionError(f"未找到修复类型:{kind}")


def test_inspection_and_apply_create_only_missing_required_directories(tmp_path: Path) -> None:
    behavior = tmp_path / "behavior_pack"
    resource = tmp_path / "resource_pack"
    _write_manifest(behavior, "data")
    _write_manifest(resource, "resources")
    service = BlockingRepairService()

    state = service.inspect(str(tmp_path))

    assert state["repairableCount"] == 2
    behavior_id = _repair_id(state, REPAIR_CREATE_REQUIRED_DIRECTORY)
    first_state, first_outcome = service.apply_and_inspect(str(tmp_path), behavior_id)

    assert first_outcome["success"] is True
    assert (behavior / "entities").is_dir() or (resource / "textures").is_dir()
    assert first_state["repairableCount"] == 1
    second_id = _repair_id(first_state, REPAIR_CREATE_REQUIRED_DIRECTORY)
    second_state, _outcome = service.apply_and_inspect(str(tmp_path), second_id)

    assert (behavior / "entities").is_dir()
    assert (resource / "textures").is_dir()
    assert second_state["repairableCount"] == 0


def test_resource_entities_rename_preserves_files_and_auto_reaudits(tmp_path: Path) -> None:
    resource = tmp_path / "resource_pack"
    _write_manifest(resource, "resources")
    source = resource / "entities"
    source.mkdir()
    source_file = source / "player.entity.json"
    source_file.write_text("{}", encoding="utf-8")
    service = BlockingRepairService()

    state = service.inspect(str(tmp_path))
    repair_id = _repair_id(state, REPAIR_RENAME_RESOURCE_ENTITIES)
    rechecked, outcome = service.apply_and_inspect(str(tmp_path), repair_id)

    assert outcome["success"] is True
    assert not source.exists()
    assert (resource / "entity" / source_file.name).read_text(encoding="utf-8") == "{}"
    assert all(
        item["kind"] != REPAIR_RENAME_RESOURCE_ENTITIES
        for item in rechecked["items"]
    )
    assert not any("资源包错误包含 entities" in issue.title for issue in scan(str(tmp_path)))


def test_comment_only_manifest_repair_preserves_document_and_removes_code_38(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "resource_pack" / "manifest.json"
    manifest.parent.mkdir()
    manifest.write_text(
        "// 包头注释\n" + json.dumps(_manifest("resources")),
        encoding="utf-8",
    )
    service = BlockingRepairService()

    state = service.inspect(str(tmp_path))
    repair_id = _repair_id(state, REPAIR_NORMALIZE_MANIFEST_COMMENTS)
    rechecked, outcome = service.apply_and_inspect(str(tmp_path), repair_id)

    assert outcome["success"] is True
    assert json.loads(manifest.read_text(encoding="utf-8")) == _manifest("resources")
    assert all(issue.code != 38 for issue in scan(str(tmp_path)))
    assert all(
        item["kind"] != REPAIR_NORMALIZE_MANIFEST_COMMENTS
        for item in rechecked["items"]
    )


def test_repair_rejects_stale_comment_plan_without_overwriting_new_content(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "resource_pack" / "manifest.json"
    manifest.parent.mkdir()
    manifest.write_text(
        "// 初始注释\n" + json.dumps(_manifest("resources")),
        encoding="utf-8",
    )
    service = BlockingRepairService()
    repair_id = _repair_id(
        service.inspect(str(tmp_path)), REPAIR_NORMALIZE_MANIFEST_COMMENTS
    )
    replacement = "// 新的外部修改\n" + json.dumps(_manifest("resources"))
    manifest.write_text(replacement, encoding="utf-8")

    with pytest.raises(ValueError, match="已过期"):
        service.apply_and_inspect(str(tmp_path), repair_id)

    assert manifest.read_text(encoding="utf-8") == replacement


def test_project_audit_result_is_adopted_without_rescanning_the_same_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    behavior = tmp_path / "behavior_pack"
    manifest = _write_manifest(behavior, "data")
    issues = [
        {
            "code": 37,
            "codeName": "ManifestJsonError",
            "severity": "error",
            "title": "manifest 缺 min_engine_version",
            "detail": "来自工程处理的真实失败结果",
            "path": str(manifest),
        },
        {
            "code": 41,
            "codeName": "PerformanceRiskWarning",
            "severity": "warning",
            "title": "性能风险",
            "detail": "真实警告",
            "path": str(manifest),
        },
    ]
    service = BlockingRepairService()

    monkeypatch.setattr(
        "src.blocking_repair.scan",
        lambda *_args, **_kwargs: pytest.fail("不应重新扫描工程审核"),
    )
    state = service.inspect_from_audit(str(tmp_path), issues)

    assert state["source"] == "projectWorkflow"
    assert state["rootPath"] == str(tmp_path.resolve())
    assert state["auditErrorCount"] == 1
    assert state["auditWarningCount"] == 1
    assert state["blockingPreview"][0]["detail"] == "来自工程处理的真实失败结果"
    assert state["blockingPreview"][0]["path"] == "behavior_pack/manifest.json"
    assert state["blockingPreview"][0]["guidance"]


def test_qml_backend_dispatches_inspection_and_writes_to_background_pool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import prismqml

    behavior = tmp_path / "behavior_pack"
    _write_manifest(behavior, "data")
    calls: list[tuple[object, tuple[object, ...]]] = []

    class _Succeeded:
        def __init__(self, payload: object) -> None:
            self._payload = payload

        def connect(self, callback) -> None:
            callback(self._payload)

    class _Ignored:
        def connect(self, _callback) -> None:
            return None

    class _Handle:
        def __init__(self, payload: object) -> None:
            self.succeeded = _Succeeded(payload)
            self.failed = _Ignored()

    def fake_run_in_pool(operation, *arguments):
        calls.append((operation, arguments))
        return _Handle(operation(*arguments))

    monkeypatch.setattr(prismqml, "run_in_pool", fake_run_in_pool)
    backend = BlockingRepairBackend()
    results: list[dict[str, object]] = []
    backend.result.connect(results.append)

    backend.inspect(str(tmp_path))
    repair_id = _repair_id(backend.state, REPAIR_CREATE_REQUIRED_DIRECTORY)
    backend.applyRepair(repair_id)

    assert len(calls) == 2
    assert (behavior / "entities").is_dir()
    assert backend.state["repairableCount"] == 0
    assert results[-1]["success"] is True

    adopted: list[str] = []
    backend.auditResultAdopted.connect(adopted.append)
    issues = [
        {
            "code": 37,
            "codeName": "ManifestJsonError",
            "severity": "error",
            "title": "manifest 缺 min_engine_version",
            "detail": "工程处理失败",
            "path": str(behavior / "manifest.json"),
        }
    ]
    backend.adoptAuditResult(str(tmp_path), issues)

    assert len(calls) == 3
    assert backend.projectPath == str(tmp_path.resolve())
    assert backend.state["source"] == "projectWorkflow"
    assert adopted == [str(tmp_path.resolve())]


def test_qml_backend_undoes_the_last_isolated_cleanup_in_background_pool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import prismqml

    cache = tmp_path / "__pycache__"
    cache.mkdir()
    cached_file = cache / "module.pyc"
    cached_file.write_bytes(b"cache")
    calls: list[tuple[object, tuple[object, ...]]] = []

    class _Succeeded:
        def __init__(self, payload: object) -> None:
            self._payload = payload

        def connect(self, callback) -> None:
            callback(self._payload)

    class _Ignored:
        def connect(self, _callback) -> None:
            return None

    class _Handle:
        def __init__(self, payload: object) -> None:
            self.succeeded = _Succeeded(payload)
            self.failed = _Ignored()

    def fake_run_in_pool(operation, *arguments):
        calls.append((operation, arguments))
        return _Handle(operation(*arguments))

    monkeypatch.setattr(prismqml, "run_in_pool", fake_run_in_pool)
    backend = BlockingRepairBackend()

    backend.inspect(str(tmp_path))
    repair_id = _repair_id(backend.state, REPAIR_REMOVE_SAFE_RESIDUE)
    backend.applyRepair(repair_id)

    assert backend.canUndo is True
    assert not cache.exists()

    backend.undoLastRemoval()

    assert len(calls) == 3
    assert backend.canUndo is False
    assert cached_file.read_bytes() == b"cache"
