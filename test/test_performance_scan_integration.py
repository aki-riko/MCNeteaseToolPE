# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""性能风险分析与打包扫描器的集成回归。"""

from __future__ import annotations

from pathlib import Path

from src.pack_scanner import _check_behavior_pack, scan
from src.performance_risk_audit import analyze_project


def _write_manifest(pack: Path) -> None:
    (pack / "manifest.json").write_text(
        '{"format_version":2,"header":{"name":"demo",'
        '"uuid":"00000000-0000-0000-0000-000000000001",'
        '"version":[1,0,0],"min_engine_version":[1,18,0]},'
        '"modules":[{"type":"data",'
        '"uuid":"00000000-0000-0000-0000-000000000002",'
        '"version":[1,0,0]}]}',
        encoding="utf-8",
    )


def test_pack_scan_exposes_performance_warning_without_blocking(
    tmp_path: Path, monkeypatch
) -> None:
    pack = tmp_path / "behavior_demo"
    pack.mkdir()
    _write_manifest(pack)
    (pack / "screen.py").write_text(
        "class Screen(object):\n"
        "    def Update(self):\n"
        "        for path in self.paths:\n"
        "            self.GetBaseUIControl(path).SetVisible(True)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("src.pack_scanner.run_legacy_pylint", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("src.pack_scanner.load_module_whitelist", lambda: set())

    issues = scan(str(tmp_path))
    performance = [issue for issue in issues if issue.code == 41]

    assert len(performance) == 1
    assert performance[0].severity == "warning"
    assert all(issue.severity != "error" for issue in performance)


def test_pack_scan_exposes_performance_parser_failure_as_non_blocking_warning(
    tmp_path: Path, monkeypatch
) -> None:
    pack = tmp_path / "behavior_broken"
    pack.mkdir()
    _write_manifest(pack)
    (pack / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    monkeypatch.setattr("src.pack_scanner.run_legacy_pylint", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("src.pack_scanner.load_module_whitelist", lambda: set())

    issues = scan(str(tmp_path))
    performance = [issue for issue in issues if issue.code == 41]

    assert len(performance) == 1
    assert performance[0].severity == "warning"
    assert performance[0].title == "Python 性能风险分析未完成"


def test_behavior_pack_reuses_each_python_source_for_all_local_checks(
    tmp_path: Path, monkeypatch
) -> None:
    pack = tmp_path / "behavior_once"
    pack.mkdir()
    script = pack / "screen.py"
    script.write_text(
        "class Screen(object):\n"
        "    def Update(self):\n"
        "        for path in self.paths:\n"
        "            self.GetBaseUIControl(path).SetVisible(True)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("src.pack_scanner.load_module_whitelist", lambda: set())
    original_open = open
    reads = {"count": 0}

    def counting_open(file, *args, **kwargs):
        if Path(file).resolve() == script.resolve():
            reads["count"] += 1
        return original_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", counting_open)
    issues = []

    _check_behavior_pack(str(tmp_path), str(pack), issues)

    assert reads["count"] == 1
    assert any(issue.code == 41 for issue in issues)


def test_analyze_project_reads_python_files(tmp_path: Path) -> None:
    path = tmp_path / "screen.py"
    path.write_text(
        "class Screen(object):\n"
        "    def Update(self):\n"
        "        for path in self.paths:\n"
        "            self.GetBaseUIControl(path).SetVisible(True)\n",
        encoding="utf-8",
    )

    risks = analyze_project(str(tmp_path))

    assert len(risks) == 1
    assert risks[0].path == str(path)
