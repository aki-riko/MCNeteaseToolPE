# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
# 网易 Python 2.7 代码审核规则回归测试。
# Regression tests for Netease Python 2.7 code-review rules.

from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess

import pytest

import src.legacy_pylint_runner as legacy_pylint_runner
from src.legacy_pylint_runner import (
    LEGACY_PYLINT_IGNORED_MESSAGE_IDS,
    PY27_RUNTIME_ENV,
    WORKER_COUNT_ENV,
    LegacyPylintUnavailable,
    run_legacy_pylint,
)
from src.module_whitelist import find_import_references, load_module_whitelist
from src.pack_scanner import scan


def _manifest() -> dict[str, object]:
    return {
        "header": {
            "uuid": "56565656-5656-5656-5656-565656565656",
            "min_engine_version": [1, 20, 0],
        },
        "modules": [
            {
                "type": "data",
                "uuid": "78787878-7878-7878-7878-787878787878",
            }
        ],
    }


def _behavior_pack(tmp_path: Path) -> Path:
    pack = tmp_path / "behavior_review"
    pack.mkdir()
    (pack / "manifest.json").write_text(json.dumps(_manifest()), encoding="utf-8")
    return pack


def _code18_errors(project: Path) -> list:
    return [issue for issue in scan(str(project)) if issue.code == 18 and issue.severity == "error"]


def test_bundled_whitelist_matches_current_document_landmarks() -> None:
    whitelist = load_module_whitelist()

    assert len(whitelist) == 456
    assert "mod.client.ui.controls.baseUIControl" in whitelist
    assert "ast" in whitelist
    assert {"sys", "os", "typing"}.isdisjoint(whitelist)


def test_whitelisted_controls_and_python2_syntax_are_accepted(tmp_path: Path) -> None:
    pack = _behavior_pack(tmp_path)
    (pack / "screen.py").write_text(
        "from mod.client.ui.controls.baseUIControl import *\n"
        "for index in xrange(2):\n"
        "    print index\n",
        encoding="utf-8",
    )

    assert _code18_errors(tmp_path) == []


def test_modules_outside_whitelist_are_errors(tmp_path: Path) -> None:
    pack = _behavior_pack(tmp_path)
    (pack / "imports.py").write_text(
        "import json, os\n"
        "from typing import List\n",
        encoding="utf-8",
    )

    errors = _code18_errors(tmp_path)

    assert {"import os（第 1 行）", "import typing（第 2 行）"} == {issue.detail for issue in errors}
    assert not any("json" in issue.detail for issue in errors)


def test_developer_owned_local_modules_are_exempt(tmp_path: Path) -> None:
    pack = _behavior_pack(tmp_path)
    package = pack / "feature"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")
    nested = package / "nested"
    nested.mkdir()
    (nested / "worker.py").write_text("VALUE = 3\n", encoding="utf-8")
    (pack / "local_util.py").write_text("VALUE = 2\n", encoding="utf-8")
    (pack / "main.py").write_text(
        "import feature.helper\n"
        "from local_util import VALUE\n"
        "import nested.worker\n"
        "import worker\n",
        encoding="utf-8",
    )

    assert _code18_errors(tmp_path) == []


def test_scan_does_not_apply_python3_map_semantics(tmp_path: Path) -> None:
    pack = _behavior_pack(tmp_path)
    (pack / "map_result.py").write_text(
        "value = map(str, [1])\n"
        "result = value[0]\n",
        encoding="utf-8",
    )

    findings = [issue for issue in scan(str(tmp_path)) if "E1136" in issue.detail]

    assert findings == []


def test_real_python27_pylint_does_not_apply_python3_map_semantics(tmp_path: Path) -> None:
    script = tmp_path / "python2_map.py"
    script.write_text(
        "value = map(str, [1])\n"
        "result = value[0]\n",
        encoding="utf-8",
    )

    try:
        messages = run_legacy_pylint([str(script)])
    except LegacyPylintUnavailable as error:
        pytest.skip(str(error))

    assert not any(message.get("message-id") == "E1136" for message in messages)


def test_python27_full_e_filters_only_known_noise(tmp_path: Path) -> None:
    noise = tmp_path / "noise.py"
    noise.write_text(
        "import module_that_does_not_exist\n"
        "print 'python2'\n",
        encoding="utf-8",
    )
    invalid = tmp_path / "invalid.py"
    invalid.write_text("def 1(self):\n    pass\n", encoding="utf-8")

    try:
        messages = run_legacy_pylint([str(noise), str(invalid)])
    except LegacyPylintUnavailable as error:
        pytest.skip(str(error))

    message_ids = {message.get("message-id") for message in messages}
    assert "E0001" in message_ids
    assert set(LEGACY_PYLINT_IGNORED_MESSAGE_IDS) == {
        "E1601",
        "E0401",
        "E1101",
        "E1102",
    }
    assert set(LEGACY_PYLINT_IGNORED_MESSAGE_IDS).isdisjoint(message_ids)


def test_python27_audit_supports_non_ascii_project_paths(tmp_path: Path) -> None:
    directory = tmp_path / "中文目录"
    directory.mkdir()
    invalid = directory / "invalid.py"
    invalid.write_text("def 1(self):\n    pass\n", encoding="utf-8")

    try:
        messages = run_legacy_pylint([str(invalid)])
    except LegacyPylintUnavailable as error:
        pytest.skip(str(error))

    syntax_errors = [message for message in messages if message.get("message-id") == "E0001"]
    assert len(syntax_errors) == 1
    assert Path(str(syntax_errors[0]["path"])).resolve() == invalid.resolve()


def test_python27_full_e_avoids_disabled_cmp_checker_crash(tmp_path: Path) -> None:
    script = tmp_path / "super_sort.py"
    script.write_text(
        "class PropertyList(list):\n"
        "    def sort(self, cmp=None, key=None, reverse=False):\n"
        "        super(PropertyList, self).sort(cmp=cmp, key=key, reverse=reverse)\n",
        encoding="utf-8",
    )

    try:
        messages = run_legacy_pylint([str(script)])
    except LegacyPylintUnavailable as error:
        pytest.skip(str(error))

    assert isinstance(messages, list)


def test_python27_parallel_results_match_single_worker(
    tmp_path: Path, monkeypatch
) -> None:
    files = []
    for index in range(6):
        script = tmp_path / f"sample_{index}.py"
        script.write_text(
            "def no_return():\n"
            "    pass\n"
            f"value_{index} = no_return()\n",
            encoding="utf-8",
        )
        files.append(str(script))

    monkeypatch.setenv(WORKER_COUNT_ENV, "1")
    try:
        single_worker = run_legacy_pylint(files)
    except LegacyPylintUnavailable as error:
        pytest.skip(str(error))

    monkeypatch.setenv(WORKER_COUNT_ENV, "3")
    parallel = run_legacy_pylint(files)

    assert parallel == single_worker


def test_python27_progress_reports_every_completed_file(tmp_path: Path) -> None:
    files = []
    for index in range(4):
        script = tmp_path / f"progress_{index}.py"
        script.write_text(f"value_{index} = {index}\n", encoding="utf-8")
        files.append(str(script))
    progress: list[tuple[int, int, str]] = []

    try:
        run_legacy_pylint(files, progress=lambda *args: progress.append(args))
    except LegacyPylintUnavailable as error:
        pytest.skip(str(error))

    assert [current for current, _total, _path in progress] == [1, 2, 3, 4]
    assert {total for _current, total, _path in progress} == {4}
    assert {Path(path).resolve() for _current, _total, path in progress} == {
        Path(path).resolve() for path in files
    }


def test_python27_worker_count_is_adaptive_and_configurable(monkeypatch) -> None:
    monkeypatch.delenv(WORKER_COUNT_ENV, raising=False)
    monkeypatch.setattr(legacy_pylint_runner.os, "cpu_count", lambda: 28)

    assert legacy_pylint_runner._worker_count(100) == 28
    assert legacy_pylint_runner._worker_count(3) == 3

    monkeypatch.setenv(WORKER_COUNT_ENV, "2")
    assert legacy_pylint_runner._worker_count(100) == 2

    monkeypatch.setenv(WORKER_COUNT_ENV, "0")
    with pytest.raises(ValueError, match="必须大于 0"):
        legacy_pylint_runner._worker_count(100)


def test_python27_subprocesses_disable_windows_consoles() -> None:
    expected = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    assert legacy_pylint_runner._subprocess_creation_flags() == expected

    source_path = Path(legacy_pylint_runner.__file__).resolve()
    syntax_tree = ast.parse(source_path.read_text(encoding="utf-8"))
    process_calls = [
        node
        for node in ast.walk(syntax_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
        and node.func.attr in {"Popen", "run"}
    ]

    assert len(process_calls) == 3
    for call in process_calls:
        creation_flags = next(
            (keyword.value for keyword in call.keywords if keyword.arg == "creationflags"),
            None,
        )
        assert isinstance(creation_flags, ast.Call)
        assert isinstance(creation_flags.func, ast.Name)
        assert creation_flags.func.id == "_subprocess_creation_flags"


def test_missing_python27_runtime_is_advisory_only(tmp_path: Path, monkeypatch) -> None:
    pack = _behavior_pack(tmp_path)
    (pack / "sample.py").write_text("print 'python2'\n", encoding="utf-8")
    monkeypatch.setenv(PY27_RUNTIME_ENV, str(tmp_path / "missing-python.exe"))

    issues = scan(str(tmp_path))

    assert not any(issue.code == 18 and issue.severity == "error" for issue in issues)
    assert any(issue.title == "Python 2.7 代码审核不可用" for issue in issues)


def test_controls_are_allowed_and_legacy_e0203_is_rejection(tmp_path: Path) -> None:
    pack = _behavior_pack(tmp_path)
    (pack / "legacy.py").write_text(
        "from mod.client.ui.controls.baseUIControl import *\n\n"
        "class DoorProperties(object):\n"
        "    @property\n"
        "    def intoAble(self):\n"
        "        return True if self._intoAble is None else self._intoAble\n\n"
        "    @intoAble.setter\n"
        "    def intoAble(self, value):\n"
        "        oldValue = getattr(self, '_intoAble', None)\n"
        "        self._intoAble = value\n",
        encoding="utf-8",
    )

    code18 = [issue for issue in scan(str(tmp_path)) if issue.code == 18]
    controls = [issue for issue in code18 if "controls.baseUIControl" in issue.detail]
    legacy = [issue for issue in code18 if "E0203" in issue.detail]

    assert controls == []
    assert len(legacy) == 1
    assert legacy[0].severity == "error"


def test_python27_pylint_e_is_rejection(tmp_path: Path, monkeypatch) -> None:
    pack = _behavior_pack(tmp_path)
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
            },
            {
                "message-id": "E1101",
                "path": str(script),
                "line": 2,
                "column": 0,
                "symbol": "no-member",
                "message": "instance has no member",
            },
            {
                "message-id": "E1102",
                "path": str(script),
                "line": 3,
                "column": 0,
                "symbol": "not-callable",
                "message": "value is not callable",
            },
        ],
    )

    findings = [issue for issue in scan(str(tmp_path)) if "E0102" in issue.detail]

    assert len(findings) == 1
    assert findings[0].severity == "error"
    assert findings[0].title == "Python 2.7 Pylint E 类错误"
    assert not any("E1101" in issue.detail or "E1102" in issue.detail for issue in findings)


def test_legacy_e0203_accepts_explicit_initialization(tmp_path: Path) -> None:
    pack = _behavior_pack(tmp_path)
    (pack / "fixed.py").write_text(
        "class DoorProperties(object):\n"
        "    def __init__(self):\n"
        "        self._intoAble = None\n\n"
        "    @property\n"
        "    def intoAble(self):\n"
        "        return self._intoAble\n\n"
        "    @intoAble.setter\n"
        "    def intoAble(self, value):\n"
        "        oldValue = self._intoAble\n"
        "        self._intoAble = value\n",
        encoding="utf-8",
    )

    code18 = [issue for issue in scan(str(tmp_path)) if issue.code == 18]

    assert not any("E0203" in issue.detail for issue in code18)


def test_import_extraction_supports_multiline_and_python2_source() -> None:
    source = (
        "from mod.client.ui.controls.baseUIControl import (\n"
        "    BaseUIControl,\n"
        ")\n"
        "import json, \\\n"
        "    random as rng\n"
        "print 'python2'\n"
    )

    references = {(item.module, item.line) for item in find_import_references(source)}

    assert references == {
        ("mod.client.ui.controls.baseUIControl", 1),
        ("json", 4),
        ("random", 4),
    }
