# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""阻塞项修复中心的扩展性非代码修复动作。"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
from typing import Callable, Iterator
import uuid

from .blocking_repair import (
    REPAIR_CLEAR_LEVEL_READONLY,
    REPAIR_NORMALIZE_GLYPH_TRANSPARENCY,
    REPAIR_NORMALIZE_JSON_BOM,
    REPAIR_REMOVE_SAFE_RESIDUE,
    RepairApplyResult,
    RepairCandidate,
    _atomic_write,
    _candidate_id,
    _is_link,
    _is_within_root,
    _relative,
)
from .cleanup_backend import _scan as scan_cleanup
from .image_audit_utils import (
    normalize_png_transparent_pixels,
    png_transparent_pixel_status,
)
from .pack_scanner import _strip_json_comments


_UTF8_BOM = b"\xef\xbb\xbf"
_STUDIO_METADATA_NAMES = frozenset({".mcs", "studio.json", "work.mcscfg"})
REPAIR_BACKUP_DIR_ENV = "MCNETEASE_REPAIR_BACKUP_DIR"


def _candidate(
    root: Path,
    kind: str,
    title: str,
    detail: str,
    change: str,
    display_path: Path,
    source_path: Path,
    target_path: Path,
    source_digest: str = "",
    destructive: bool = False,
    impact: str = "",
) -> RepairCandidate:
    return RepairCandidate(
        root,
        _candidate_id(root, kind, source_path, target_path, source_digest),
        kind,
        title,
        detail,
        change,
        display_path,
        source_path,
        target_path,
        source_digest,
        destructive,
        impact,
    )


def _iter_files(root: Path, suffix: str | None = None) -> Iterator[Path]:
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        directories[:] = [
            name for name in directories if not _is_link(Path(current, name))
        ]
        for name in files:
            path = Path(current, name)
            if _is_link(path) or not _is_within_root(root, path):
                continue
            if suffix is None or name.casefold().endswith(suffix.casefold()):
                yield path


def _read_jsonc(path: Path) -> tuple[bytes, object] | None:
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
        return raw, json.loads(_strip_json_comments(text))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _raw_digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _append_file_fingerprint(digest, path: Path, marker: str) -> None:
    status = path.stat()
    digest.update(f"{marker}:{path.name}:{status.st_size}:{status.st_mode}".encode("utf-8"))
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1_048_576), b""):
            digest.update(block)


def _path_fingerprint(path: Path) -> str:
    if not path.exists() or _is_link(path):
        return ""
    digest = hashlib.sha256()
    if path.is_file():
        _append_file_fingerprint(digest, path, "file")
        return digest.hexdigest()
    if not path.is_dir():
        return ""
    for current, directories, files in os.walk(path, topdown=True, followlinks=False):
        directories.sort(key=str.casefold)
        files.sort(key=str.casefold)
        current_path = Path(current)
        relative = current_path.relative_to(path).as_posix()
        digest.update(f"directory:{relative}".encode("utf-8"))
        if any(_is_link(current_path / name) for name in [*directories, *files]):
            return ""
        for name in files:
            child = current_path / name
            _append_file_fingerprint(digest, child, f"file:{relative}")
    return digest.hexdigest()


def _safe_residue_candidates(root: Path) -> list[RepairCandidate]:
    result, _logs = scan_cleanup(str(root))
    candidates: list[RepairCandidate] = []
    for value in sorted(result.items):
        path = Path(value)
        if not path.exists() or _is_link(path) or not _is_within_root(root, path):
            continue
        fingerprint = _path_fingerprint(path)
        if not fingerprint:
            continue
        is_metadata = path.name.casefold() in _STUDIO_METADATA_NAMES
        title = "移除开发工作台编辑信息" if is_metadata else "清理打包残留"
        detail = (
            "该项属于开发工作台编辑信息，普通导出与机审不应携带。"
            if is_metadata
            else "该项已被现有安全清理规则识别为缓存、编译产物或临时文件。"
        )
        candidates.append(
            _candidate(
                root,
                REPAIR_REMOVE_SAFE_RESIDUE,
                title,
                detail,
                "移入工程外隔离区；执行前需要确认，可在本次程序会话中撤销。",
                path,
                path,
                path,
                fingerprint,
                destructive=True,
                impact="该项会移入工程外隔离区，可在当前程序会话中撤销。",
            )
        )
    return candidates


def _json_bom_candidates(root: Path) -> list[RepairCandidate]:
    candidates: list[RepairCandidate] = []
    for path in _iter_files(root, ".json"):
        content = _read_jsonc(path)
        if content is None:
            continue
        raw, _document = content
        if not raw.startswith(_UTF8_BOM):
            continue
        candidates.append(
            _candidate(
                root,
                REPAIR_NORMALIZE_JSON_BOM,
                "移除 JSON UTF-8 BOM",
                "该 JSON 已可解析，但文件头包含 EF BB BF，网易打包器会将其识别为 invalid json data。",
                "仅移除文件头 BOM，保留其余字节与注释。",
                path,
                path,
                path,
                _raw_digest(raw),
            )
        )
    return candidates


def _readonly_level_candidates(root: Path) -> list[RepairCandidate]:
    candidates: list[RepairCandidate] = []
    for name in ("level.dat", "level.dat_old"):
        path = root / name
        if not path.is_file() or _is_link(path):
            continue
        if path.stat().st_mode & stat.S_IWRITE:
            continue
        fingerprint = _path_fingerprint(path)
        if not fingerprint:
            continue
        candidates.append(
            _candidate(
                root,
                REPAIR_CLEAR_LEVEL_READONLY,
                f"解除 {name} 的只读属性",
                "当前世界文件不可写，保存世界数据或打包时会失败。",
                "仅恢复文件写入属性，不修改世界数据内容。",
                path,
                path,
                path,
                fingerprint,
            )
        )
    return candidates


def _glyph_transparency_candidates(root: Path) -> list[RepairCandidate]:
    candidates: list[RepairCandidate] = []
    for path in _iter_files(root, ".png"):
        if not path.name.casefold().startswith("glyph_") or path.parent.name.casefold() != "font":
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if png_transparent_pixel_status(path) != "invalid":
            continue
        if normalize_png_transparent_pixels(raw) is None:
            continue
        candidates.append(
            _candidate(
                root,
                REPAIR_NORMALIZE_GLYPH_TRANSPARENCY,
                "归零位图字体透明像素 RGB",
                "该字体图是8位 RGBA PNG，仅完全透明像素保留了非零 RGB。",
                "仅将 alpha=0 像素的 RGB 归零，视觉结果不变。",
                path,
                path,
                path,
                _raw_digest(raw),
            )
        )
    return candidates


def discover_extra_repairs(root: Path) -> list[RepairCandidate]:
    """返回需要明确确认、但可由当前工程事实验证的额外修复动作。"""

    from .blocking_repair_manifest_actions import discover_manifest_repairs

    return [
        *_safe_residue_candidates(root),
        *_json_bom_candidates(root),
        *_readonly_level_candidates(root),
        *_glyph_transparency_candidates(root),
        *discover_manifest_repairs(root),
    ]


def _replace_and_verify(
    path: Path,
    original: bytes,
    replacement: bytes,
    verifier: Callable[[], None],
) -> None:
    try:
        _atomic_write(path, replacement)
        verifier()
    except Exception as error:
        try:
            _atomic_write(path, original)
        except Exception as rollback_error:
            raise OSError("文件写入校验失败且回滚失败") from rollback_error
        raise OSError("文件写入校验失败，已回滚原文件") from error


def _current_json(candidate: RepairCandidate) -> tuple[bytes, object]:
    content = _read_jsonc(candidate.source_path)
    if content is None:
        raise ValueError("JSON 已无法解析，请重新检查")
    raw, document = content
    if _raw_digest(raw) != candidate.source_digest:
        raise ValueError("文件已变化，请重新检查后再修复")
    return raw, document


def _canonical_json(document: object) -> bytes:
    try:
        return json.dumps(
            document,
            ensure_ascii=False,
            indent=4,
            allow_nan=False,
        ).encode("utf-8") + b"\n"
    except (TypeError, ValueError) as error:
        raise ValueError("JSON 包含无法安全重写的值") from error


def _verify_jsonc(path: Path) -> None:
    if _read_jsonc(path) is None:
        raise ValueError("写入后的 JSON 无法解析")


def _verify_no_json_bom(path: Path) -> None:
    if path.read_bytes().startswith(_UTF8_BOM):
        raise ValueError("写入后的 JSON 仍包含 BOM")
    _verify_jsonc(path)


def _backup_root(root: Path) -> Path:
    configured = os.environ.get(REPAIR_BACKUP_DIR_ENV)
    base = Path(configured).expanduser() if configured else root.parent / f".{root.name}.repair-backups"
    backup = base.resolve(strict=False)
    if _is_within_root(root, backup):
        raise ValueError("修复隔离区不能位于工程目录内")
    return backup


def _quarantine_safe_residue(candidate: RepairCandidate) -> RepairApplyResult:
    path = candidate.source_path
    if not path.exists() or _is_link(path):
        raise ValueError("待清理项已变化，请重新检查")
    if _path_fingerprint(path) != candidate.source_digest:
        raise ValueError("待清理项已变化，请重新检查")
    backup_root = _backup_root(candidate.root_path)
    session = backup_root / uuid.uuid4().hex
    target = session / path.name
    session.mkdir(parents=True, exist_ok=False)
    try:
        shutil.move(str(path), str(target))
        if path.exists() or not target.exists() or _is_link(target):
            raise OSError(f"未能隔离打包残留:{path}")
        backup_fingerprint = _path_fingerprint(target)
        if not backup_fingerprint:
            raise OSError(f"未能校验隔离打包残留:{target}")
    except Exception:
        if target.exists() and not path.exists() and not _is_link(target):
            shutil.move(str(target), str(path))
        if session.exists() and not any(session.iterdir()):
            session.rmdir()
        raise
    return RepairApplyResult(
        [path],
        {
            "backupPath": str(target),
            "backupRoot": str(backup_root),
            "backupFingerprint": backup_fingerprint,
            "originalPath": _relative(candidate.root_path, path),
        },
    )


def restore_safe_residue(root: Path, undo: dict[str, str]) -> Path:
    backup_value = undo.get("backupPath", "")
    original_value = undo.get("originalPath", "")
    backup_root_value = undo.get("backupRoot", "")
    backup_fingerprint = undo.get("backupFingerprint", "")
    if not backup_value or not original_value or not backup_root_value or not backup_fingerprint:
        raise ValueError("隔离清理记录不完整，无法恢复")
    expected_root = _backup_root(root)
    if Path(backup_root_value).resolve(strict=False) != expected_root:
        raise ValueError("隔离清理记录不属于当前工程")
    backup = Path(backup_value).resolve(strict=True)
    original = (root / original_value).resolve(strict=False)
    if not _is_within_root(expected_root, backup) or not _is_within_root(root, original):
        raise ValueError("隔离清理记录的路径无效")
    if original.exists() or _is_link(backup) or not backup.exists():
        raise ValueError("恢复目标已变化，无法覆盖现有文件")
    if _path_fingerprint(backup) != backup_fingerprint:
        raise ValueError("隔离文件已变化，拒绝恢复未知内容")
    original.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(backup), str(original))
    if not original.exists() or backup.exists():
        raise OSError("隔离清理恢复失败")
    if backup.parent.exists() and not any(backup.parent.iterdir()):
        backup.parent.rmdir()
    if not os.environ.get(REPAIR_BACKUP_DIR_ENV) and expected_root.exists() and not any(expected_root.iterdir()):
        expected_root.rmdir()
    return original


def _clear_level_readonly(candidate: RepairCandidate) -> list[Path]:
    path = candidate.source_path
    if not path.is_file() or _path_fingerprint(path) != candidate.source_digest:
        raise ValueError("世界文件已变化，请重新检查")
    os.chmod(path, path.stat().st_mode | stat.S_IWRITE)
    if not path.stat().st_mode & stat.S_IWRITE:
        raise OSError(f"未能解除只读属性:{path}")
    return [path]


def _normalize_glyph_transparency(candidate: RepairCandidate) -> list[Path]:
    try:
        raw = candidate.source_path.read_bytes()
    except OSError as error:
        raise OSError(f"无法读取位图字体:{candidate.source_path}") from error
    if _raw_digest(raw) != candidate.source_digest:
        raise ValueError("位图字体已变化，请重新检查")
    replacement = normalize_png_transparent_pixels(raw)
    if replacement is None:
        raise ValueError("位图字体不再满足无视觉变化的修复前提")
    _replace_and_verify(
        candidate.target_path,
        raw,
        replacement,
        lambda: _verify_glyph_transparency(candidate.target_path),
    )
    return [candidate.target_path]


def _verify_glyph_transparency(path: Path) -> None:
    if png_transparent_pixel_status(path) != "valid":
        raise ValueError("写入后的位图字体仍未通过透明像素审核")


def apply_extra_candidate(candidate: RepairCandidate) -> list[Path]:
    from .blocking_repair_manifest_actions import apply_manifest_candidate

    manifest_result = apply_manifest_candidate(candidate)
    if manifest_result is not None:
        return manifest_result
    handlers = {
        REPAIR_REMOVE_SAFE_RESIDUE: _quarantine_safe_residue,
        REPAIR_NORMALIZE_JSON_BOM: _normalize_json_bom,
        REPAIR_NORMALIZE_GLYPH_TRANSPARENCY: _normalize_glyph_transparency,
        REPAIR_CLEAR_LEVEL_READONLY: _clear_level_readonly,
    }
    handler = handlers.get(candidate.kind)
    if handler is None:
        raise ValueError("未知的修复类型")
    return handler(candidate)


def _normalize_json_bom(candidate: RepairCandidate) -> list[Path]:
    raw, _document = _current_json(candidate)
    if not raw.startswith(_UTF8_BOM):
        raise ValueError("JSON BOM 已变化，请重新检查")
    _replace_and_verify(
        candidate.target_path,
        raw,
        raw[len(_UTF8_BOM) :],
        lambda: _verify_no_json_bom(candidate.target_path),
    )
    return [candidate.target_path]


__all__ = ["apply_extra_candidate", "discover_extra_repairs", "restore_safe_residue"]
