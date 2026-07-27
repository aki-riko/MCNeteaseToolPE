# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
# 自动 ZIP 打包后端回归测试。

from __future__ import annotations

from pathlib import Path
import zipfile

import pytest

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

import src.package_backend as package_backend
from src.package_backend import PackageBackend, create_zip_archive


def test_create_zip_archive_contains_only_component_packs_and_replaces_output(
    tmp_path: Path,
) -> None:
    project = tmp_path / "mojin"
    pack = project / "behavior_demo"
    pack.mkdir(parents=True)
    (pack / "manifest.json").write_text("{\"name\": \"demo\"}", encoding="utf-8")
    (pack / "script.py").write_text("value = 1\n", encoding="utf-8")
    (project / "README.txt").write_text("demo", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("must not be packaged", encoding="utf-8")
    try:
        (pack / "outside-link.txt").symlink_to(tmp_path / "outside.txt")
    except OSError:
        pass
    archive = project / "mojin.zip"
    archive.write_bytes(b"old archive")
    progress: list[tuple[int, int]] = []

    result = create_zip_archive(
        str(project),
        progress=lambda current, total: progress.append((current, total)),
    )

    assert Path(result.archive_path) == archive.resolve()
    assert result.file_count == 2
    assert result.size_bytes == archive.stat().st_size
    assert progress[0] == (0, 3)
    assert progress[-1] == (3, 3)
    with zipfile.ZipFile(archive) as bundle:
        assert sorted(name for name in bundle.namelist() if not name.endswith("/")) == [
            "behavior_demo/manifest.json",
            "behavior_demo/script.py",
        ]
        assert "README.txt" not in bundle.namelist()
        assert "mojin.zip" not in bundle.namelist()


def test_create_zip_archive_preserves_complete_map_and_excludes_output(tmp_path: Path) -> None:
    project = tmp_path / "world"
    database = project / "db"
    database.mkdir(parents=True)
    (project / "level.dat").write_bytes(b"bedrock-level")
    (project / "levelname.txt").write_text("真实地图", encoding="utf-8")
    (database / "000001.log").write_bytes(b"leveldb-wal")
    archive = project / "world.zip"
    archive.write_bytes(b"old archive")

    result = create_zip_archive(str(project))

    assert result.file_count == 3
    with zipfile.ZipFile(result.archive_path) as bundle:
        assert bundle.namelist()[0] == "world/"
        assert {name.split("/", 1)[0] for name in bundle.namelist()} == {"world"}
        assert sorted(name for name in bundle.namelist() if not name.endswith("/")) == [
            "world/db/000001.log",
            "world/level.dat",
            "world/levelname.txt",
        ]
        assert "world/world.zip" not in bundle.namelist()


def test_create_zip_archive_rejects_addon_pack_not_directly_under_project_root(
    tmp_path: Path,
) -> None:
    project = tmp_path / "addon"
    pack = project / "wrapper" / "behavior_demo"
    pack.mkdir(parents=True)
    (pack / "manifest.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="工程根目录下一层"):
        create_zip_archive(str(project))

    assert not (project / "addon.zip").exists()


def test_archive_validation_failure_preserves_previous_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "addon"
    pack = project / "behavior_demo"
    pack.mkdir(parents=True)
    (pack / "manifest.json").write_text("{}", encoding="utf-8")
    archive = project / "addon.zip"
    archive.write_bytes(b"previous-output")

    def reject_archive(*_args: object) -> None:
        raise ValueError("结构验收失败")

    monkeypatch.setattr(package_backend, "_validate_archive_structure", reject_archive)

    with pytest.raises(ValueError, match="结构验收失败"):
        create_zip_archive(str(project))

    assert archive.read_bytes() == b"previous-output"
    assert not list(project.glob(".addon.*.tmp"))


def _wait_for_task(backend: PackageBackend, timeout_ms: int = 10_000) -> bool:
    loop = QEventLoop()
    timed_out = {"value": True}
    poll = QTimer()
    poll.setInterval(10)

    def settle_when_stopped() -> None:
        if backend._task_handle is None:
            timed_out["value"] = False
            loop.quit()

    poll.timeout.connect(settle_when_stopped)
    poll.start()
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    poll.stop()
    return not timed_out["value"]


def test_package_backend_creates_zip_without_blocking_the_qt_event_loop(tmp_path: Path) -> None:
    application = QCoreApplication.instance() or QCoreApplication([])
    assert application is not None
    project = tmp_path / "demo_project"
    pack = project / "behavior_demo"
    pack.mkdir(parents=True)
    (pack / "manifest.json").write_text("{}", encoding="utf-8")
    (pack / "script.py").write_text("value = 1\n", encoding="utf-8")
    backend = PackageBackend()
    results: list[tuple[object, ...]] = []
    progress: list[tuple[int, int]] = []
    backend.progress.connect(lambda current, total: progress.append((current, total)))
    backend.finished.connect(lambda *args: results.append(args))

    backend.package(str(project))

    assert _wait_for_task(backend)
    assert backend.busy is False
    assert results and results[0][0] is True
    assert Path(results[0][1]) == project / "demo_project.zip"
    assert progress[0][0] == 0
    assert progress[-1][0] == progress[-1][1]


def test_package_backend_reports_missing_component_pack_and_settles_task(tmp_path: Path) -> None:
    application = QCoreApplication.instance() or QCoreApplication([])
    assert application is not None
    project = tmp_path / "empty_project"
    project.mkdir()
    backend = PackageBackend()
    results: list[tuple[object, ...]] = []
    failures: list[str] = []
    backend.finished.connect(lambda *args: results.append(args))
    backend.taskFailed.connect(failures.append)

    backend.package(str(project))

    assert _wait_for_task(backend)
    assert backend.busy is False
    assert results and results[0][0] is False
    assert failures and "未找到" in failures[0]
    assert not (project / "empty_project.zip").exists()


def test_package_backend_uses_prismqml_managed_task() -> None:
    source = Path("src/package_backend.py").read_text(encoding="utf-8")

    assert "run_in_thread(_create_zip_task, project_dir)" in source
    assert "current_task()" in source
    assert "QThread" not in source
    assert "_PackageWorker" not in source
