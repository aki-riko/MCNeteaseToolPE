# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""非代码阻塞项修复的计划、写入和异步边界回归测试。"""

from __future__ import annotations

import gc
import json
from pathlib import Path
import sys

import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from src.blocking_repair import (
    BlockingRepairService,
    REPAIR_CREATE_REQUIRED_DIRECTORY,
    REPAIR_NORMALIZE_MANIFEST_COMMENTS,
    REPAIR_REMOVE_SAFE_RESIDUE,
    REPAIR_RENAME_RESOURCE_ENTITIES,
)
from src.blocking_repair_backend import BlockingRepairBackend
from src.blocking_repair_cli import run_blocking_repair_worker
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


def test_blocking_repair_worker_round_trips_inspection_and_apply(tmp_path: Path) -> None:
    behavior = tmp_path / "behavior_pack"
    _write_manifest(behavior, "data")
    from io import StringIO

    request = json.dumps({"operation": "inspect", "projectDir": str(tmp_path)})
    output = StringIO()
    assert run_blocking_repair_worker(StringIO(request + "\n"), output) == 0
    first = json.loads(output.getvalue())
    assert first["success"] is True
    repair_id = _repair_id(first["state"], REPAIR_CREATE_REQUIRED_DIRECTORY)

    output = StringIO()
    request = json.dumps(
        {"operation": "apply", "projectDir": str(tmp_path), "repairId": repair_id}
    )
    assert run_blocking_repair_worker(StringIO(request + "\n"), output) == 0
    second = json.loads(output.getvalue())
    assert second["success"] is True
    assert second["outcome"]["success"] is True
    assert (behavior / "entities").is_dir()


def test_qml_backend_starts_an_isolated_worker_process(
    tmp_path: Path,
) -> None:
    backend = BlockingRepairBackend()
    assert backend._worker_program() == str(Path(sys.executable).resolve())
    assert backend._worker_arguments()[-1].endswith("repair_worker.py")
    assert backend._worker_arguments()[0] == "-u"


def test_qml_backend_undoes_the_last_isolated_cleanup_in_worker_process(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    cached_file = cache / "module.pyc"
    cached_file.write_bytes(b"cache")
    backend = BlockingRepairBackend()

    app = QCoreApplication.instance() or QCoreApplication([])

    def wait_for_state_change() -> None:
        loop = QEventLoop()
        QTimer.singleShot(30_000, loop.quit)
        backend.stateChanged.connect(loop.quit)
        loop.exec()

    backend.inspect(str(tmp_path))
    wait_for_state_change()
    repair_id = _repair_id(backend.state, REPAIR_REMOVE_SAFE_RESIDUE)
    backend.applyRepair(repair_id)
    wait_for_state_change()

    assert backend.canUndo is True
    assert not cache.exists()

    backend.undoLastRemoval()
    wait_for_state_change()

    assert backend.canUndo is False
    assert cached_file.read_bytes() == b"cache"
    backend.deleteLater()
    app.processEvents()
    del backend
    gc.collect()
    app.processEvents()
