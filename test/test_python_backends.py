# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
# Python 后端纯逻辑回归测试。
# Pure-logic regression tests for the Python backends.

from __future__ import annotations

import json
from io import StringIO
import os
from pathlib import Path
import sys

import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop, QObject, QTimer, Signal
from prismqml.python.core import NotificationPosition

import main as application_main
from src.audit_cli import run_audit_cli
from src.audit_backend import AuditBackend, _audit_worker_command
from src.backends import ProjectBackend
from src.cleanup_backend import CleanupBackend, _clean, _scan
from src.package_backend import PackageBackend
from src.pack_scanner import scan
from src.project_structure import PROJECT_KIND_ADDONS, PROJECT_KIND_MAP, classify_project
from src.uuid_backend import UuidBackend, _generate


class _FakeUuidBackend(QObject):
    logMessage = Signal(str, str)
    finished = Signal(bool, int, str)

    def __init__(self, calls: list[str], success: bool = True) -> None:
        super().__init__()
        self._calls = calls
        self._success = success

    def generate(self, project_dir: str) -> None:
        self._calls.append("uuid")
        changed = 2 if self._success else 0
        message = "UUID 完成" if self._success else "UUID 失败"
        self.finished.emit(self._success, changed, message)


class _FakeCleanupBackend(QObject):
    logMessage = Signal(str, str)
    finished = Signal(bool, int, "qint64", str)

    def __init__(self, calls: list[str]) -> None:
        super().__init__()
        self._calls = calls

    def clean(self, project_dir: str) -> None:
        self._calls.append("cleanup")
        self.finished.emit(True, 3, 128, "清理完成")


class _FakeAuditBackend(QObject):
    logMessage = Signal(str, str)
    progress = Signal(int, int, str)
    taskFailed = Signal(str)
    finished = Signal(bool, int, int, list)

    def __init__(self, calls: list[str]) -> None:
        super().__init__()
        self._calls = calls

    def audit(self, project_dir: str) -> None:
        self._calls.append("audit")
        self.progress.emit(1, 2, "检查 manifest 配置")
        self.progress.emit(2, 2, "审核完成")
        self.finished.emit(True, 0, 1, [])


class _FakePackageBackend(QObject):
    logMessage = Signal(str, str)
    progress = Signal(int, int)
    taskFailed = Signal(str)
    finished = Signal(bool, str, int, "qint64")

    def __init__(self, calls: list[str], archive_path: Path | None = None) -> None:
        super().__init__()
        self._calls = calls
        self._archive_path = archive_path

    def package(self, project_dir: str) -> None:
        self._calls.append("package")
        self.progress.emit(1, 1)
        archive = self._archive_path or Path(project_dir).parent / "project.zip"
        self.finished.emit(True, str(archive), 1, 128)


def _manifest(pack_type: str, pack_uuid: str) -> dict[str, object]:
    module_type = "data" if pack_type == "behavior" else "resources"
    return {
        "header": {
            "uuid": pack_uuid,
            "version": [1, 0, 0],
            "min_engine_version": [1, 20, 0],
        },
        "modules": [{"type": module_type, "uuid": f"{pack_uuid[:8]}-1111-1111-1111-111111111111"}],
    }


def test_uuid_generation_rewrites_dependencies(tmp_path: Path) -> None:
    behavior = tmp_path / "behavior_pack"
    resource = tmp_path / "resource_pack"
    behavior.mkdir()
    resource.mkdir()
    behavior_uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    resource_uuid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    behavior_manifest = _manifest("behavior", behavior_uuid)
    behavior_manifest["dependencies"] = [{"uuid": resource_uuid}]
    (behavior / "manifest.json").write_text(json.dumps(behavior_manifest), encoding="utf-8")
    (resource / "manifest.json").write_text(json.dumps(_manifest("resource", resource_uuid)), encoding="utf-8")

    success, changed, _message, _logs = _generate(str(tmp_path))

    assert success is True
    assert changed == 2
    behavior_after = json.loads((behavior / "manifest.json").read_text(encoding="utf-8"))
    resource_after = json.loads((resource / "manifest.json").read_text(encoding="utf-8"))
    assert behavior_after["header"]["uuid"] != behavior_uuid
    assert behavior_after["dependencies"][0]["uuid"] == resource_after["header"]["uuid"]
    assert not (tmp_path / "world_behavior_packs.json").exists()
    assert not (tmp_path / "world_resource_packs.json").exists()


def test_uuid_generation_allows_map_without_component_packs(tmp_path: Path) -> None:
    (tmp_path / "level.dat").write_bytes(b"bedrock-level")
    (tmp_path / "db").mkdir()

    success, changed, message, _logs = _generate(str(tmp_path))

    assert success is True
    assert changed == 0
    assert "无需重写" in message


def test_uuid_generation_rebuilds_map_world_bindings(tmp_path: Path) -> None:
    behavior_uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    resource_uuid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    behavior = tmp_path / "behavior_pack"
    resource = tmp_path / "resource_pack"
    behavior.mkdir()
    resource.mkdir()
    behavior_manifest = _manifest("behavior", behavior_uuid)
    behavior_manifest["dependencies"] = [{"uuid": resource_uuid}]
    (behavior / "manifest.json").write_text(json.dumps(behavior_manifest), encoding="utf-8")
    (resource / "manifest.json").write_text(
        json.dumps(_manifest("resource", resource_uuid)),
        encoding="utf-8",
    )
    (tmp_path / "level.dat").write_bytes(b"bedrock-level")
    old_binding = [{"pack_id": "stale", "type": "Addon", "version": [0, 0, 1]}]
    (tmp_path / "world_behavior_packs.json").write_text(json.dumps(old_binding), encoding="utf-8")
    (tmp_path / "world_resource_packs.json").write_text(json.dumps(old_binding), encoding="utf-8")

    success, changed, _message, _logs = _generate(str(tmp_path))

    behavior_after = json.loads((behavior / "manifest.json").read_text(encoding="utf-8"))
    resource_after = json.loads((resource / "manifest.json").read_text(encoding="utf-8"))
    behavior_binding = json.loads(
        (tmp_path / "world_behavior_packs.json").read_text(encoding="utf-8")
    )
    resource_binding = json.loads(
        (tmp_path / "world_resource_packs.json").read_text(encoding="utf-8")
    )
    assert success is True
    assert changed == 2
    assert behavior_after["dependencies"][0]["uuid"] == resource_after["header"]["uuid"]
    assert behavior_binding == [
        {"pack_id": behavior_after["header"]["uuid"], "version": [1, 0, 0], "type": "Addon"}
    ]
    assert resource_binding == [
        {"pack_id": resource_after["header"]["uuid"], "version": [1, 0, 0], "type": "Addon"}
    ]


def test_uuid_generation_rejects_invalid_map_version_before_writing(tmp_path: Path) -> None:
    pack = tmp_path / "behavior_pack"
    pack.mkdir()
    manifest = _manifest("behavior", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    del manifest["header"]["version"]
    manifest_path = pack / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "level.dat").write_bytes(b"bedrock-level")
    binding_path = tmp_path / "world_behavior_packs.json"
    binding_path.write_text(
        json.dumps([{"pack_id": "stale", "type": "Addon", "version": [0, 0, 1]}]),
        encoding="utf-8",
    )
    manifest_before = manifest_path.read_bytes()
    binding_before = binding_path.read_bytes()

    with pytest.raises(ValueError, match="header.version"):
        _generate(str(tmp_path))

    assert manifest_path.read_bytes() == manifest_before
    assert binding_path.read_bytes() == binding_before


def test_project_backend_exposes_four_owned_tools() -> None:
    backend = ProjectBackend()

    assert isinstance(backend.uuidBackend, UuidBackend)
    assert isinstance(backend.cleanupBackend, CleanupBackend)
    assert isinstance(backend.auditBackend, AuditBackend)
    assert isinstance(backend.packageBackend, PackageBackend)
    assert backend.uuidBackend.parent() is backend
    assert backend.cleanupBackend.parent() is backend
    assert backend.auditBackend.parent() is backend
    assert backend.packageBackend.parent() is backend


def test_project_backend_classifies_map_and_addons_directories(tmp_path: Path) -> None:
    map_project = tmp_path / "map"
    addons_project = tmp_path / "addons"
    map_project.mkdir()
    addons_project.mkdir()
    (map_project / "level.dat").write_bytes(b"bedrock-level")
    backend = ProjectBackend()

    assert classify_project(map_project) == PROJECT_KIND_MAP
    assert classify_project(addons_project) == PROJECT_KIND_ADDONS
    assert backend.classifyProject(str(map_project)) == PROJECT_KIND_MAP
    assert backend.classifyProject(str(addons_project)) == PROJECT_KIND_ADDONS
    assert backend.classifyProject(str(tmp_path / "missing")) == ""


def test_project_backend_runs_one_click_steps_in_order(tmp_path: Path) -> None:
    calls: list[str] = []
    backend = ProjectBackend(
        uuid_backend=_FakeUuidBackend(calls),
        cleanup_backend=_FakeCleanupBackend(calls),
        audit_backend=_FakeAuditBackend(calls),
        package_backend=_FakePackageBackend(calls),
    )
    results: list[tuple[object, ...]] = []
    backend.finished.connect(lambda *args: results.append(args))

    backend.run(str(tmp_path))

    assert calls == ["cleanup", "audit", "uuid", "package"]
    assert backend.busy is False
    assert backend.phase == "done"
    assert backend.progress == 100
    assert results and results[0][0] is True
    assert results[0][2] == 1


def test_project_backend_reveals_generated_archive_and_clears_path(tmp_path: Path) -> None:
    calls: list[str] = []
    revealed: list[Path] = []
    archive = tmp_path / "project.zip"
    archive.write_bytes(b"zip")
    backend = ProjectBackend(
        uuid_backend=_FakeUuidBackend(calls),
        cleanup_backend=_FakeCleanupBackend(calls),
        audit_backend=_FakeAuditBackend(calls),
        package_backend=_FakePackageBackend(calls, archive),
        file_revealer=lambda path: revealed.append(path) is None,
    )

    backend.run(str(tmp_path))

    assert Path(backend.archivePath) == archive.resolve()
    assert backend.revealArchive() is True
    assert revealed == [archive.resolve()]
    backend.reset()
    assert backend.archivePath == ""


def test_project_backend_rejects_missing_archive_before_reveal(tmp_path: Path) -> None:
    calls: list[str] = []
    revealed: list[Path] = []
    logs: list[tuple[str, str]] = []
    backend = ProjectBackend(
        uuid_backend=_FakeUuidBackend(calls),
        cleanup_backend=_FakeCleanupBackend(calls),
        audit_backend=_FakeAuditBackend(calls),
        package_backend=_FakePackageBackend(calls, tmp_path / "missing.zip"),
        file_revealer=lambda path: revealed.append(path) is None,
    )
    backend.logMessage.connect(lambda text, level: logs.append((text, level)))

    backend.run(str(tmp_path))

    assert backend.revealArchive() is False
    assert revealed == []
    assert logs[-1] == ("ZIP 文件不存在，无法在文件夹中定位", "error")


def test_project_backend_windows_reveal_selects_archive(
    tmp_path: Path,
    monkeypatch,
) -> None:
    archive = tmp_path / "bundle.zip"
    calls: list[tuple[str, list[str]]] = []

    class _FakeProcess:
        @staticmethod
        def startDetached(program: str, arguments: list[str]) -> tuple[bool, int]:
            calls.append((program, arguments))
            return True, 42

    monkeypatch.setattr("src.backends.QProcess", _FakeProcess)
    monkeypatch.setattr("src.backends.sys.platform", "win32")

    assert ProjectBackend._reveal_local_file(archive) is True
    assert calls == [
        ("explorer.exe", ["/select,", os.path.normpath(str(archive))]),
    ]


def test_project_backend_stops_before_uuid_and_package_when_audit_fails(tmp_path: Path) -> None:
    calls: list[str] = []

    class _FailingAuditBackend(_FakeAuditBackend):
        def audit(self, project_dir: str) -> None:
            self._calls.append("audit")
            self.finished.emit(False, 1, 0, [{"severity": "error"}])

    backend = ProjectBackend(
        uuid_backend=_FakeUuidBackend(calls),
        cleanup_backend=_FakeCleanupBackend(calls),
        audit_backend=_FailingAuditBackend(calls),
        package_backend=_FakePackageBackend(calls),
    )

    backend.run(str(tmp_path))

    assert calls == ["cleanup", "audit"]
    assert backend.phase == "done"
    assert backend.busy is False


def test_project_backend_stops_after_uuid_failure(tmp_path: Path) -> None:
    calls: list[str] = []
    backend = ProjectBackend(
        uuid_backend=_FakeUuidBackend(calls, success=False),
        cleanup_backend=_FakeCleanupBackend(calls),
        audit_backend=_FakeAuditBackend(calls),
        package_backend=_FakePackageBackend(calls),
    )

    backend.run(str(tmp_path))

    assert calls == ["cleanup", "audit", "uuid"]
    assert backend.busy is False
    assert backend.phase == "failed"
    assert backend.status == "UUID 失败"


def test_cleanup_scans_and_removes_only_allowlisted_items(tmp_path: Path) -> None:
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "module.pyc").write_bytes(b"1234")
    (tmp_path / "build.log").write_bytes(b"12")
    keep = tmp_path / "keep.txt"
    keep.write_text("keep", encoding="utf-8")

    result, _logs = _scan(str(tmp_path))
    assert len(result.items) == 2
    assert result.total_bytes == 6

    success, removed, freed, _message, _logs = _clean(str(tmp_path))
    assert success is True
    assert removed == 2
    assert freed == 6
    assert keep.exists()
    assert not cache.exists()
    assert not (tmp_path / "build.log").exists()


def test_cleanup_preserves_map_leveldb_log(tmp_path: Path) -> None:
    database = tmp_path / "db"
    database.mkdir()
    (tmp_path / "level.dat").write_bytes(b"bedrock-level")
    leveldb_log = database / "000001.log"
    leveldb_log.write_bytes(b"leveldb-wal")
    build_log = tmp_path / "build.log"
    build_log.write_bytes(b"ordinary-log")

    result, _logs = _scan(str(tmp_path))
    success, removed, _freed, _message, _logs = _clean(str(tmp_path))

    assert result.items == [str(build_log.resolve())]
    assert success is True
    assert removed == 1
    assert leveldb_log.read_bytes() == b"leveldb-wal"
    assert not build_log.exists()


def test_cleanup_skips_junk_file_symlink(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    target = tmp_path / "outside.log"
    target.write_bytes(b"must-stay")
    link = project / "linked.log"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("当前 Windows 环境不允许创建符号链接")

    result, _logs = _scan(str(project))
    success, removed, _freed, _message, _logs = _clean(str(project))

    assert result.items == []
    assert success is True
    assert removed == 0
    assert target.read_bytes() == b"must-stay"
    assert link.is_symlink()


def test_audit_reports_monotonic_real_work_progress(tmp_path: Path, monkeypatch) -> None:
    pack = tmp_path / "behavior_progress"
    pack.mkdir()
    (pack / "manifest.json").write_text(
        json.dumps(_manifest("behavior", "12121212-1212-1212-1212-121212121212")),
        encoding="utf-8",
    )
    (pack / "settings.json").write_text("{}", encoding="utf-8")
    scripts = [pack / "first.py", pack / "second.py"]
    for script in scripts:
        script.write_text("value = 1\n", encoding="utf-8")

    def report_fake_python_files(files, *_args, progress=None, **_kwargs):
        for index, path in enumerate(files, start=1):
            if progress is not None:
                progress(index, len(files), path)
        return []

    monkeypatch.setattr("src.pack_scanner.run_legacy_pylint", report_fake_python_files)
    progress: list[tuple[int, int, str]] = []

    scan(str(tmp_path), progress=progress.append)

    assert progress[0][0] == 0
    assert progress[-1][0] == progress[-1][1]
    assert all(current <= total for current, total, _status in progress)
    assert [item[0] for item in progress] == sorted(item[0] for item in progress)
    assert any("behavior_progress" in status for _current, _total, status in progress)
    json_files = [
        item for item in progress if item[2].startswith("检查 JSON 编码与语法（")
    ]
    python_files = [
        item for item in progress if item[2].startswith("Python 2.7 代码审核（")
    ]
    assert any("（2/2）" in status for _current, _total, status in json_files)
    assert any("（2/2）" in status for _current, _total, status in python_files)
    assert any(status.endswith("first.py") for _current, _total, status in python_files)
    assert any(status.endswith("second.py") for _current, _total, status in python_files)
    assert not any("兼容审核" in status for _current, _total, status in progress)


def test_project_backend_preserves_fractional_audit_progress() -> None:
    backend = ProjectBackend()

    backend._on_audit_progress(2828, 3175, "Python 2.7 代码审核（1/347）")
    assert backend.progress == 0

    backend._set_busy(True)
    backend._set_state("audit", "准备审核", 5)
    backend._on_audit_progress(2828, 3175, "Python 2.7 代码审核（1/347）")

    assert backend.progress == pytest.approx(62.8960629921)


def test_project_backend_uses_workload_balanced_phase_ranges() -> None:
    backend = ProjectBackend()
    backend._set_busy(True)

    backend._set_state("audit", "准备审核", 5)
    backend._on_audit_progress(1, 2, "审核中")
    assert backend.progress == pytest.approx(37.5)

    backend._on_audit_progress(2, 2, "审核完成")
    assert backend.progress == 70

    backend._set_state("uuid", "重写 UUID", 70)
    assert backend.progress == 70

    backend._set_state("package", "输出 ZIP", 75)
    backend._on_package_progress(1, 2)
    assert backend.progress == pytest.approx(87.5)

    backend._on_package_progress(2, 2)
    assert backend.progress == 100


def test_audit_cli_outputs_machine_readable_json(tmp_path: Path) -> None:
    pack = tmp_path / "behavior_cli"
    pack.mkdir()
    (pack / "manifest.json").write_text(
        json.dumps(_manifest("behavior", "dddddddd-dddd-dddd-dddd-dddddddddddd")),
        encoding="utf-8",
    )
    (pack / "broken.json").write_text("{", encoding="utf-8")
    output = StringIO()

    status = run_audit_cli(["--audit-json", str(tmp_path)], output)
    issues = json.loads(output.getvalue())

    assert status == 0
    assert any(
        issue["code"] == 25
        and issue["severity"] == "error"
        for issue in issues
    )


def test_audit_cli_reports_rejecting_python27_pylint_e(tmp_path: Path, monkeypatch) -> None:
    pack = tmp_path / "behavior_rejected"
    pack.mkdir()
    (pack / "manifest.json").write_text(
        json.dumps(_manifest("behavior", "abababab-abab-abab-abab-abababababab")),
        encoding="utf-8",
    )
    script = pack / "duplicate.py"
    script.write_text("def value():\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(
        "src.pack_scanner.run_legacy_pylint",
        lambda *_args, **_kwargs: [
            {
                "message-id": "E0102",
                "path": str(script),
                "line": 1,
                "column": 0,
                "symbol": "function-redefined",
                "message": "function already defined",
            }
        ],
    )
    output = StringIO()

    status = run_audit_cli(["--audit-json", str(tmp_path)], output)
    issues = json.loads(output.getvalue())

    assert status == 0
    assert any(
        issue["code"] == 18
        and issue["severity"] == "error"
        and "E0102" in issue["detail"]
        for issue in issues
    )


def test_audit_completion_uses_prismqml_bottom_right_toasts(monkeypatch) -> None:
    success_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    error_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(
        application_main,
        "showDesktopSuccess",
        lambda *args, **kwargs: success_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        application_main,
        "showDesktopError",
        lambda *args, **kwargs: error_calls.append((args, kwargs)),
    )

    application_main._notify_audit_finished(True, 0, 2, [])
    application_main._notify_audit_finished(False, 3, 1, [])

    assert success_calls == [
        (
            ("审核通过", "0 个错误，2 个警告"),
            {"position": NotificationPosition.BottomRight},
        )
    ]
    assert error_calls == [
        (
            ("审核未通过", "3 个错误，1 个警告"),
            {"position": NotificationPosition.BottomRight},
        )
    ]


def test_audit_cli_streams_progress_and_result(tmp_path: Path) -> None:
    pack = tmp_path / "behavior_stream"
    pack.mkdir()
    (pack / "manifest.json").write_text(
        json.dumps(_manifest("behavior", "34343434-3434-3434-3434-343434343434")),
        encoding="utf-8",
    )
    output = StringIO()

    status = run_audit_cli(["--audit-stream-json", str(tmp_path)], output)
    messages = [json.loads(line) for line in output.getvalue().splitlines()]

    assert status == 0
    assert messages[0]["type"] == "progress"
    assert messages[-1]["type"] == "result"
    progress = [message for message in messages if message["type"] == "progress"]
    assert progress[-1]["current"] == progress[-1]["total"]
    assert isinstance(messages[-1]["issues"], list)
    assert (pack / "entities").is_dir()


def test_audit_worker_command_selects_source_and_standalone_modes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    program, arguments = _audit_worker_command(str(tmp_path))

    assert Path(program).resolve() == Path(sys.executable).resolve()
    assert arguments[0] == "-u"
    assert Path(arguments[1]).name == "audit_worker.py"
    assert arguments[-2:] == ["--audit-stream-json", str(tmp_path)]

    packaged = tmp_path / "MCNeteaseToolPE.exe"
    monkeypatch.setattr(sys, "executable", str(packaged))

    program, arguments = _audit_worker_command(str(tmp_path))

    assert program == str(packaged.resolve())
    assert arguments == ["--audit-stream-json", str(tmp_path)]


def test_audit_backend_receives_isolated_worker_progress(tmp_path: Path) -> None:
    application = QCoreApplication.instance() or QCoreApplication([])
    assert application is not None
    pack = tmp_path / "behavior_process"
    pack.mkdir()
    (pack / "manifest.json").write_text(
        json.dumps(_manifest("behavior", "56565656-5656-5656-5656-565656565656")),
        encoding="utf-8",
    )
    backend = AuditBackend()
    progress: list[tuple[int, int, str]] = []
    results: list[tuple[object, ...]] = []
    loop = QEventLoop()
    timed_out = {"value": True}

    backend.progress.connect(lambda *args: progress.append(args))
    backend.finished.connect(lambda *args: (results.append(args), timed_out.update(value=False), loop.quit()))
    QTimer.singleShot(15_000, loop.quit)

    backend.audit(str(tmp_path))
    loop.exec()

    assert timed_out["value"] is False
    assert backend.busy is False
    assert results and results[0][0] is True
    assert progress and progress[-1][0] == progress[-1][1]
    assert (pack / "entities").is_dir()


def test_audit_backend_rejects_error_issues() -> None:
    backend = AuditBackend()
    results: list[tuple[object, ...]] = []
    backend.finished.connect(lambda *args: results.append(args))

    issues = [{"severity": "error"}, {"severity": "warning"}]
    backend._complete(issues)

    assert results == [(False, 1, 1, issues)]


def test_manifest_and_filename_rules(tmp_path: Path) -> None:
    pack = tmp_path / "behavior_pack"
    pack.mkdir()
    (pack / "manifest.json").write_text(
        json.dumps({"header": {"min_engine_version": [1, 17, 0]}, "modules": [{"type": "data"}]}),
        encoding="utf-8",
    )
    (pack / "中文.txt").write_text("x", encoding="utf-8")

    issues = scan(str(tmp_path))
    codes = {issue.code for issue in issues}
    assert 16 in codes
    assert 37 in codes


def test_utf8_bom_json_is_accepted_but_malformed_json_still_reports_code25(tmp_path: Path) -> None:
    pack = tmp_path / "resource_bom"
    pack.mkdir()
    manifest = json.dumps(_manifest("resource", "cdcdcdcd-cdcd-cdcd-cdcd-cdcdcdcdcdcd"))
    (pack / "manifest.json").write_bytes(b"\xef\xbb\xbf" + manifest.encode("utf-8"))
    (pack / "valid.json").write_bytes(b"\xef\xbb\xbf{\"accepted\": true}")
    (pack / "broken.json").write_text('{"broken":', encoding="utf-8")

    issues = scan(str(tmp_path))

    assert not any(issue.code == 38 and issue.file_path.endswith("manifest.json") for issue in issues)
    assert not any(issue.code == 25 and issue.file_path.endswith("valid.json") for issue in issues)
    assert any(issue.code == 25 and issue.file_path.endswith("broken.json") for issue in issues)
