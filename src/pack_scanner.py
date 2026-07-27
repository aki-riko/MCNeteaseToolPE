# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
# 网易 MC 工程的只读静态审核逻辑。
# Read-only static checks for Netease Minecraft projects.

"""Pure Python replacement for the original C++ ``PackScanner``."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import re
from typing import Callable, Iterable, Iterator

from .audit_codes import code_name
from .code_review_compat import find_legacy_property_accesses
from .legacy_pylint_runner import (
    LEGACY_PYLINT_IGNORED_MESSAGE_IDS,
    LEGACY_PYLINT_MESSAGE_IDS,
    LegacyPylintUnavailable,
    run_legacy_pylint,
)
from .module_whitelist import collect_local_modules, find_disallowed_imports, load_module_whitelist


LOGGER = logging.getLogger(__name__)

JUNK_DIR_NAMES = (
    "__pycache__",
    ".pytest_cache",
    ".git",
    ".idea",
    ".vscode",
    ".mypy_cache",
    ".ruff_cache",
)
JUNK_FILE_NAMES = (".DS_Store", "Thumbs.db", "desktop.ini")
JUNK_FILE_SUFFIXES = (".pyc", ".pyo", ".log", ".tmp", ".bak")
REPEATED_NAME = re.compile(r"(.)\1{4,}")


@dataclass(frozen=True)
class AuditIssue:
    """One issue exposed to the QML audit page."""

    code: int
    severity: str
    title: str
    detail: str
    file_path: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "codeName": code_name(self.code),
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "path": self.file_path,
        }


def _absolute(path: str | os.PathLike[str]) -> str:
    return os.path.abspath(os.path.realpath(os.fspath(path)))


def _relative(root: str, path: str) -> str:
    return os.path.relpath(path, root).replace(os.sep, "/")


def _walk(root: str) -> Iterator[tuple[str, list[str], list[str]]]:
    """Walk without following symlinked directories."""

    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        dirs[:] = [name for name in dirs if not os.path.islink(os.path.join(current, name))]
        yield current, dirs, files


def _iter_named(root: str, filename: str | None = None, suffix: str | None = None) -> Iterator[str]:
    for current, _dirs, files in _walk(root):
        for name in files:
            if filename is not None and name.lower() != filename.lower():
                continue
            if suffix is not None and not name.lower().endswith(suffix.lower()):
                continue
            yield _absolute(os.path.join(current, name))


def _collect_pack_dirs(root: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for manifest in _iter_named(root, filename="manifest.json"):
        directory = _absolute(os.path.dirname(manifest))
        if directory not in seen:
            seen.add(directory)
            result.append(directory)
    return result


def _issue(code: int, severity: str, title: str, detail: str, path: str = "") -> AuditIssue:
    return AuditIssue(code, severity, title, detail, path)


def _is_junk_name(path: str) -> bool:
    name = os.path.basename(path)
    if os.path.isdir(path):
        return name.lower() in {item.lower() for item in JUNK_DIR_NAMES}
    if name.lower() in {item.lower() for item in JUNK_FILE_NAMES}:
        return True
    return name.lower().endswith(tuple(item.lower() for item in JUNK_FILE_SUFFIXES))


def _has_non_ascii(name: str) -> bool:
    return any(ord(char) > 127 for char in name)


def _read_bytes(path: str) -> bytes | None:
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError as error:
        LOGGER.warning("无法读取文件 %s: %s", path, error)
        return None


def _json_document(path: str, raw: bytes | None = None) -> object | None:
    if raw is None:
        raw = _read_bytes(path)
    if raw is None:
        return None
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        LOGGER.debug("JSON 解析失败 %s: %s", path, error)
        return None


def _strip_json_comments(raw: str) -> str:
    """Remove JSONC comments while preserving string contents and newlines."""

    output: list[str] = []
    in_string = False
    escaped = False
    in_line = False
    in_block = False
    index = 0
    while index < len(raw):
        char = raw[index]
        next_char = raw[index + 1] if index + 1 < len(raw) else ""
        if in_line:
            if char == "\n":
                in_line = False
                output.append(char)
            index += 1
            continue
        if in_block:
            if char == "*" and next_char == "/":
                in_block = False
                index += 2
                continue
            if char == "\n":
                output.append(char)
            index += 1
            continue
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            output.append(char)
        elif char == "/" and next_char == "/":
            in_line = True
            index += 2
            continue
        elif char == "/" and next_char == "*":
            in_block = True
            index += 2
            continue
        else:
            output.append(char)
        index += 1
    return "".join(output)


def _dir_size(path: str) -> int:
    total = 0
    for current, _dirs, files in _walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(current, name))
            except OSError as error:
                LOGGER.warning("无法统计文件 %s: %s", os.path.join(current, name), error)
    return total


def _manifest_type(path: str) -> str:
    document = _json_document(path)
    if not isinstance(document, dict):
        return ""
    modules = document.get("modules")
    if not isinstance(modules, list) or not modules or not isinstance(modules[0], dict):
        return ""
    return str(modules[0].get("type", ""))


def _is_behavior_pack(pack_dir: str) -> bool:
    manifest = os.path.join(pack_dir, "manifest.json")
    module_type = _manifest_type(manifest)
    if module_type in {"data", "client_data", "javascript"}:
        return True
    return "behavior" in os.path.basename(pack_dir).lower()


def _append_manual_behavior_issues(
    root: str,
    pack: str,
    files: Iterable[str],
    output: list[AuditIssue],
) -> None:
    try:
        whitelist = load_module_whitelist()
    except (OSError, UnicodeError, ValueError) as error:
        LOGGER.exception("网易模块白名单加载失败")
        output.append(_issue(18, "error", "网易模块白名单不可用", str(error), _relative(root, pack)))
        return
    file_list = list(files)
    local_modules = collect_local_modules(pack, file_list)
    for path in file_list:
        rel = _relative(root, path)
        try:
            with open(path, "r", encoding="utf-8-sig") as handle:
                source = handle.read()
                for reference in find_disallowed_imports(source, whitelist, local_modules):
                    detail = f"import {reference.module}（第 {reference.line} 行）"
                    output.append(_issue(18, "error", "使用网易白名单外模块", detail, rel))
        except (OSError, UnicodeDecodeError) as error:
            LOGGER.warning("行为包脚本无法读取 %s: %s", path, error)


def _append_historical_compatibility_issues(
    pack_files: list[str], root: str, output: list[AuditIssue]
) -> None:
    """Add historically proven errors that modern pylint no longer emits."""

    for path in pack_files:
        rel = _relative(root, path)
        try:
            with open(path, "r", encoding="utf-8-sig") as handle:
                source = handle.read()
        except (OSError, UnicodeDecodeError) as error:
            LOGGER.warning("历史审核规则无法读取 %s: %s", path, error)
            continue
        for finding in find_legacy_property_accesses(source):
            line_marker = f"第 {finding.line} 行"
            duplicate = any(
                issue.file_path == rel and finding.message_id in issue.detail and line_marker in issue.detail
                for issue in output)
            if duplicate:
                continue
            detail = (f"{finding.message_id} {finding.symbol}: {finding.message}"
                      f"（第 {finding.line} 行，第 {finding.column} 列）")
            output.append(_issue(18, "error", "历史已确认的网易拒审规则", detail, rel))


def _append_python2_pylint_issues(
    pack_files: list[str],
    root: str,
    output: list[AuditIssue],
    progress: Callable[[int, int, str], None] | None = None,
) -> None:
    """Run the real Python 2.7 Pylint as a rejecting code audit."""

    if not pack_files:
        return
    try:
        messages = run_legacy_pylint(
            pack_files,
            LEGACY_PYLINT_MESSAGE_IDS,
            progress=progress,
        )
    except LegacyPylintUnavailable as error:
        LOGGER.warning("Python 2.7 代码审核不可用: %s", error)
        output.append(
            _issue(
                18,
                "warning",
                "Python 2.7 代码审核不可用",
                str(error),
                _relative(root, pack_files[0]),
            )
        )
        return
    except (OSError, RuntimeError, ValueError, TypeError) as error:
        LOGGER.exception("Python 2.7 Pylint 审核执行失败")
        output.append(
            _issue(
                18,
                "warning",
                "Python 2.7 代码审核执行失败",
                str(error),
                _relative(root, pack_files[0]),
            )
        )
        return

    ignored = set(LEGACY_PYLINT_IGNORED_MESSAGE_IDS)
    for message in messages:
        message_id = str(message.get("message-id", ""))
        if not message_id.startswith("E") or message_id in ignored:
            continue
        path_value = str(message.get("path", ""))
        path = _absolute(path_value) if path_value else ""
        if path and not os.path.isfile(path):
            path = _relative(root, path_value)
        else:
            path = _relative(root, path) if path else ""
        line = message.get("line", "?")
        column = message.get("column", "?")
        symbol = message.get("symbol", "")
        text = str(message.get("message", ""))
        detail = f"{message_id} {symbol}: {text}（第 {line} 行，第 {column} 列）"
        duplicate = any(
            issue.file_path == path
            and issue.detail.startswith(f"{message_id} ")
            and f"第 {line} 行" in issue.detail
            for issue in output
        )
        if duplicate:
            continue
        output.append(
            _issue(
                18,
                "error",
                "Python 2.7 Pylint E 类错误",
                detail,
                path,
            )
        )


def _check_root_junk(root: str, output: list[AuditIssue]) -> None:
    seen: set[str] = set()
    for pack in _collect_pack_dirs(root):
        for current, dirs, files in _walk(pack):
            for name in [*dirs, *files]:
                path = _absolute(os.path.join(current, name))
                if path in seen or os.path.islink(path):
                    continue
                if _is_junk_name(path):
                    seen.add(path)
                    output.append(_issue(24, "error", "包内含无关文件/缓存", _relative(root, path), path))
                if os.path.isfile(path) and name.lower().endswith(".mcp"):
                    output.append(_issue(36, "error", "包内含 .MCP 编译文件", _relative(root, path), path))


def _check_file_names(root: str, output: list[AuditIssue]) -> None:
    targets: list[str] = []
    for pack in _collect_pack_dirs(root):
        targets.append(pack)
        for current, dirs, files in _walk(pack):
            targets.extend(os.path.join(current, name) for name in [*dirs, *files])
    for path in targets:
        name = os.path.basename(path)
        rel = _relative(root, path)
        if _has_non_ascii(name):
            output.append(_issue(16, "error", "文件名含中文/非 ASCII 字符", rel, path))
        if len(name) > 80:
            output.append(_issue(27, "warning", f"文件名过长({len(name)} 字符)", rel, path))
        base = os.path.splitext(name)[0]
        if REPEATED_NAME.search(base):
            output.append(_issue(35, "warning", "命名含 5 个以上连续相同字符", rel, path))


def _check_manifests(root: str, output: list[AuditIssue]) -> None:
    manifests = list(_iter_named(root, filename="manifest.json"))
    for path in manifests:
        rel = _relative(root, path)
        raw = _read_bytes(path)
        if raw is None:
            continue
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            output.append(_issue(38, "error", "manifest.json 非 UTF-8 编码", rel, path))
            continue
        if "/*" in text or "*/" in text:
            output.append(_issue(38, "error", "manifest.json 含 /* */ 注释", rel, path))
        try:
            document = json.loads(text)
        except json.JSONDecodeError as error:
            output.append(_issue(38, "error", f"manifest.json 解析失败:{error.msg}", rel, path))
            continue
        if not isinstance(document, dict):
            output.append(_issue(38, "error", "manifest.json 顶层不是对象", rel, path))
            continue
        header = document.get("header")
        version = header.get("min_engine_version") if isinstance(header, dict) else None
        if not isinstance(version, list) or len(version) < 2:
            output.append(_issue(37, "error", "manifest 缺 min_engine_version", rel, path))
        else:
            try:
                major, minor = int(version[0]), int(version[1])
            except (TypeError, ValueError):
                major, minor = 0, 0
            if (major, minor) < (1, 18):
                output.append(_issue(37, "error", f"min_engine_version 过低({major}.{minor} < 1.18.0)", rel, path))
    behavior_dir = os.path.join(root, "behavior_packs")
    if os.path.isdir(behavior_dir) and not manifests:
        output.append(_issue(10, "error", "behavior_packs 下缺少 manifest.json", "behavior_packs", behavior_dir))


def ensure_required_pack_directories(project_dir: str) -> list[str]:
    """Create NetEase-required pack directories and return created paths."""

    root = _absolute(project_dir)
    if not os.path.isdir(root):
        raise ValueError(f"目录无效:{project_dir}")
    created: list[str] = []
    for path in _iter_named(root, filename="manifest.json"):
        module_type = _manifest_type(path)
        if module_type in {"data", "client_data", "javascript"}:
            required_name = "entities"
        elif module_type == "resources":
            required_name = "textures"
        else:
            continue
        pack = os.path.dirname(path)
        required = os.path.join(pack, required_name)
        if os.path.exists(required):
            if not os.path.isdir(required):
                raise OSError(f"必需目录路径已被文件占用:{required}")
            continue
        os.mkdir(required)
        created.append(_absolute(required))
    return created


def _check_bad_resource_dir(root: str, output: list[AuditIssue]) -> None:
    for path in _iter_named(root, filename="manifest.json"):
        pack = os.path.dirname(path)
        bad = os.path.join(pack, "resource_pack")
        if os.path.isdir(bad):
            output.append(_issue(20, "error", "manifest 同级存在名为 resource_pack 的文件夹,需改名", _relative(root, bad), bad))


def _check_json_encoding(
    root: str,
    output: list[AuditIssue],
    files: Iterable[str] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> None:
    file_list = list(files) if files is not None else list(_iter_named(root, suffix=".json"))
    for index, path in enumerate(file_list, start=1):
        rel = _relative(root, path)
        raw = _read_bytes(path)
        if raw is not None:
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                output.append(_issue(40, "error", "json 非 UTF-8 编码", rel, path))
            else:
                try:
                    json.loads(_strip_json_comments(text))
                except json.JSONDecodeError as error:
                    output.append(_issue(25, "warning", f"json 解析失败:{error.msg}", rel, path))
        if progress is not None:
            progress(index, len(file_list), path)


def _check_behavior_pack(root: str, pack: str, output: list[AuditIssue]) -> None:
    files = [path for path in _iter_named(pack, suffix=".py") if "__pycache__" not in path]
    _append_manual_behavior_issues(root, pack, files, output)
    _append_historical_compatibility_issues(files, root, output)


def _check_structures_depth(root: str, output: list[AuditIssue]) -> None:
    for current, dirs, _files in _walk(root):
        for name in dirs:
            if name.lower() != "structures":
                continue
            struct_dir = os.path.join(current, name)
            for file_path in _iter_all_files(struct_dir):
                rel = os.path.relpath(file_path, struct_dir).replace(os.sep, "/")
                depth = rel.count("/")
                if depth > 1:
                    output.append(_issue(6, "warning", f"structures 嵌套过深({depth + 1} 层)", _relative(root, file_path), file_path))


def _iter_all_files(root: str) -> Iterator[str]:
    for current, _dirs, files in _walk(root):
        for name in files:
            yield _absolute(os.path.join(current, name))


def scan(
    project_dir: str,
    progress: Callable[[tuple[int, int, str]], None] | None = None,
) -> list[AuditIssue]:
    """Run all static checks without modifying the project."""

    root = _absolute(project_dir) if project_dir else ""
    if not root or not os.path.isdir(root):
        return [_issue(0, "error", "目录无效", project_dir)]
    issues: list[AuditIssue] = []
    checks = (
        ("检查缓存与无关文件", _check_root_junk),
        ("检查文件与目录命名", _check_file_names),
        ("检查 manifest 配置", _check_manifests),
        ("检查资源目录冲突", _check_bad_resource_dir),
    )
    behavior_packs = [pack for pack in _collect_pack_dirs(root) if _is_behavior_pack(pack)]
    json_files = list(_iter_named(root, suffix=".json"))
    behavior_files = [
        path
        for pack in behavior_packs
        for path in _iter_named(pack, suffix=".py")
        if "__pycache__" not in path
    ]
    json_units = max(1, len(json_files))
    python_units = max(1, len(behavior_files))
    total = len(checks) + json_units + len(behavior_packs) + python_units + 1
    current = 0
    if progress:
        progress((current, total, "准备审核工程"))
    for status, check in checks:
        if progress:
            progress((current, total, status))
        check(root, issues)
        current += 1
    if progress:
        progress((current, total, f"检查 JSON 编码与语法（0/{len(json_files)}）"))

    def report_json_file(completed: int, _total: int, path: str) -> None:
        if progress:
            progress(
                (
                    current + completed,
                    total,
                    f"检查 JSON 编码与语法（{completed}/{len(json_files)}）：{_relative(root, path)}",
                )
            )

    _check_json_encoding(
        root,
        issues,
        files=json_files,
        progress=report_json_file if progress else None,
    )
    current += json_units
    for index, pack in enumerate(behavior_packs, start=1):
        if progress:
            name = os.path.basename(pack)
            progress((current, total, f"审核 Python 代码（{index}/{len(behavior_packs)}）：{name}"))
        _check_behavior_pack(root, pack, issues)
        current += 1
    if progress:
        progress((current, total, f"Python 2.7 代码审核（0/{len(behavior_files)}）"))

    def report_python_file(completed: int, _total: int, path: str) -> None:
        if progress:
            progress(
                (
                    current + completed,
                    total,
                    f"Python 2.7 代码审核（{completed}/{len(behavior_files)}）：{_relative(root, path)}",
                )
            )

    _append_python2_pylint_issues(
        behavior_files,
        root,
        issues,
        progress=report_python_file if progress else None,
    )
    current += python_units
    if progress:
        progress((current, total, "检查 structures 目录层级"))
    _check_structures_depth(root, issues)
    current += 1
    if progress:
        progress((current, total, "审核完成"))
    return issues


__all__ = ["AuditIssue", "code_name", "ensure_required_pack_directories", "scan"]
