# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""网易可在本地确定复现的内容、媒体与地图审核规则。"""

from __future__ import annotations

from dataclasses import dataclass
import io
import json
import os
from pathlib import Path
import re
import stat
import struct
import tokenize

from .config import (
    AUDIT_MAX_NETWORK_VERSION,
    AUDIT_MAX_TEXTURE_DIMENSION,
    LEVEL_DAT_MAX_COLLECTION_ITEMS,
    LEVEL_DAT_MAX_DEPTH,
)
from .level_dat import LevelDatParseError, NbtList, NbtTag, parse_level_dat
from .image_audit_utils import image_dimensions, png_has_invalid_transparent_pixels


INT32_MIN = -2_147_483_648
INT32_MAX = 2_147_483_647
NUMERIC_JSON_KEY = re.compile(r":(-?\d+)$")
REPEATED_IDENTIFIER = re.compile(r"(.)\1{5,}")
PLAYER_RENDER_CONTROLLERS = {
    "controller.render.player.first_person": "variable.is_first_person",
    "controller.render.player.third_person": (
        "!variable.is_first_person && !variable.map_face_icon"
    ),
    "controller.render.player.first_person_bloom": "variable.is_first_person",
    "controller.render.player.third_person_bloom": (
        "!variable.is_first_person && !variable.map_face_icon"
    ),
}
KNOWN_AUDIO_SUFFIXES = frozenset(
    {".aac", ".flac", ".m4a", ".mp3", ".opus", ".wav", ".wma"}
)


@dataclass(frozen=True)
class ContentFinding:
    code: int
    severity: str
    title: str
    detail: str
    path: str


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _finding(
    root: Path,
    path: Path,
    code: int,
    severity: str,
    title: str,
    detail: str,
) -> ContentFinding:
    return ContentFinding(code, severity, title, detail, _relative(root, path))


def _manifest_type(path: Path) -> str:
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ""
    modules = document.get("modules") if isinstance(document, dict) else None
    if not isinstance(modules, list) or not modules or not isinstance(modules[0], dict):
        return ""
    return str(modules[0].get("type", ""))


def _manifest_paths(root: Path) -> list[Path]:
    return [path for path in root.rglob("manifest.json") if path.is_file()]


def _strip_json_comments(text: str) -> str:
    output: list[str] = []
    in_string = escaped = in_line = in_block = False
    index = 0
    while index < len(text):
        char = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if in_line:
            if char == "\n":
                in_line = False
                output.append(char)
        elif in_block:
            if char == "*" and following == "/":
                in_block = False
                index += 1
            elif char == "\n":
                output.append(char)
        elif in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
            output.append(char)
        elif char == "/" and following == "/":
            in_line = True
            index += 1
        elif char == "/" and following == "*":
            in_block = True
            index += 1
        else:
            output.append(char)
        index += 1
    return "".join(output)


def check_pack_layout(root: Path) -> list[ContentFinding]:
    """Codes 6/10: map/add-on nesting, missing manifests and pack misclassification."""

    findings: list[ContentFinding] = []
    manifests = _manifest_paths(root)
    is_map = (root / "level.dat").is_file()
    for manifest in manifests:
        relative = manifest.relative_to(root)
        if is_map:
            valid = (
                len(relative.parts) == 3
                and relative.parts[0].casefold() in {"behavior_packs", "resource_packs"}
            )
            if not valid:
                findings.append(
                    _finding(root, manifest, 6, "error", "地图组件包目录层级错误", relative.as_posix())
                )
        elif len(relative.parts) != 2:
            findings.append(
                _finding(
                    root,
                    manifest,
                    10,
                    "error",
                    "Addon 组件包必须直接位于 ZIP 根目录下一层",
                    relative.as_posix(),
                )
            )

        if _manifest_type(manifest) == "resources" and (manifest.parent / "entities").is_dir():
            entities = manifest.parent / "entities"
            findings.append(
                _finding(
                    root,
                    entities,
                    10,
                    "error",
                    "资源包错误包含 entities 文件夹",
                    "网易机审会用 entities 判断行为包，请改为资源包的 entity 文件夹",
                )
            )

    for collection_name in ("behavior_packs", "resource_packs"):
        collection = root / collection_name
        if not collection.is_dir():
            continue
        for child in collection.iterdir():
            if child.is_dir() and not (child / "manifest.json").is_file():
                findings.append(
                    _finding(root, child, 10, "error", "组件包缺少 manifest.json", _relative(root, child))
                )
    return findings


def _manifest_binding(root: Path, manifest: Path) -> tuple[str, tuple[str, tuple[int, ...]]] | None:
    """Return the world-binding kind and identity for one valid map pack."""

    relative = manifest.relative_to(root)
    if len(relative.parts) != 3:
        return None
    collection = relative.parts[0].casefold()
    if collection == "behavior_packs":
        kind = "behavior"
    elif collection == "resource_packs":
        kind = "resource"
    else:
        return None
    try:
        document = json.loads(manifest.read_text(encoding="utf-8-sig"))
        header = document["header"]
        pack_id = header["uuid"]
        version = header["version"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError):
        return None
    if not isinstance(pack_id, str) or not (
        isinstance(version, list)
        and len(version) == 3
        and all(
            isinstance(item, int) and not isinstance(item, bool) and item >= 0
            for item in version
        )
    ):
        return None
    return kind, (pack_id, tuple(version))


def check_map_upload_structure(root: Path) -> list[ContentFinding]:
    """Warn about conditional lobby-map files without blocking ordinary maps."""

    if not (root / "level.dat").is_file():
        return []
    findings: list[ContentFinding] = []
    for name in ("level.dat_old", "levelname.txt"):
        path = root / name
        if not path.is_file():
            findings.append(
                _finding(
                    root,
                    path,
                    6,
                    "warning",
                    f"联机大厅投稿建议补充 {name}",
                    "普通地图不强制；联机大厅目录示例和 Code 6 已知原因包含此文件",
                )
            )

    expected: dict[str, set[tuple[str, tuple[int, ...]]]] = {
        "behavior": set(),
        "resource": set(),
    }
    for manifest in _manifest_paths(root):
        binding = _manifest_binding(root, manifest)
        if binding is not None:
            kind, identity = binding
            expected[kind].add(identity)

    binding_files = {
        "behavior": "world_behavior_packs.json",
        "resource": "world_resource_packs.json",
    }
    for kind, identities in expected.items():
        if not identities:
            continue
        path = root / binding_files[kind]
        if not path.is_file():
            findings.append(
                _finding(
                    root,
                    path,
                    6,
                    "warning",
                    f"联机地图携带组件包但缺少 {path.name}",
                    "普通地图不强制；投稿联机地图时需要此绑定文件",
                )
            )
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(document, list):
            findings.append(
                _finding(
                    root,
                    path,
                    6,
                    "warning",
                    f"联机地图绑定文件 {path.name} 顶层不是 JSON 数组",
                    "普通地图不阻断；投稿联机地图前需要修正",
                )
            )
            continue
        actual: set[tuple[str, tuple[int, ...]]] = set()
        invalid_type = False
        for item in document:
            if not isinstance(item, dict):
                continue
            pack_id = item.get("pack_id")
            version = item.get("version")
            if item.get("type") != "Addon":
                invalid_type = True
            if isinstance(pack_id, str) and isinstance(version, list) and all(
                isinstance(part, int) and not isinstance(part, bool) for part in version
            ):
                actual.add((pack_id, tuple(version)))
        if invalid_type or actual != identities:
            findings.append(
                _finding(
                    root,
                    path,
                    6,
                    "warning",
                    f"联机地图绑定文件 {path.name} 与 manifest 不一致",
                    "投稿联机地图时每项必须使用对应 header.uuid、header.version，并包含 type=Addon",
                )
            )
    return findings


def _walk_json_keys(value: object, path: Path, root: Path) -> list[ContentFinding]:
    findings: list[ContentFinding] = []
    if isinstance(value, dict):
        for key, child in value.items():
            match = NUMERIC_JSON_KEY.search(str(key))
            if match:
                number = int(match.group(1))
                if number < INT32_MIN or number > INT32_MAX:
                    findings.append(
                        _finding(
                            root,
                            path,
                            40,
                            "error",
                            "JSON 数字键超出 Int32 范围",
                            str(key),
                        )
                    )
            findings.extend(_walk_json_keys(child, path, root))
    elif isinstance(value, list):
        for child in value:
            findings.extend(_walk_json_keys(child, path, root))
    return findings


def check_json_numeric_keys(root: Path) -> list[ContentFinding]:
    findings: list[ContentFinding] = []
    for path in root.rglob("*.json"):
        try:
            value = json.loads(_strip_json_comments(path.read_text(encoding="utf-8-sig")))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        findings.extend(_walk_json_keys(value, path, root))
    return findings


def check_python_identifiers(root: Path) -> list[ContentFinding]:
    """Code 35 identifier check that also accepts Python 2 token streams."""

    findings: list[ContentFinding] = []
    for path in root.rglob("*.py"):
        try:
            source = path.read_text(encoding="utf-8-sig")
            tokens = tokenize.generate_tokens(io.StringIO(source).readline)
            seen: set[tuple[str, int]] = set()
            for token in tokens:
                if token.type != tokenize.NAME or not REPEATED_IDENTIFIER.search(token.string):
                    continue
                marker = (token.string, token.start[0])
                if marker in seen:
                    continue
                seen.add(marker)
                findings.append(
                    _finding(
                        root,
                        path,
                        35,
                        "error",
                        "标识符含5个以上连续相同字符",
                        f"{token.string}（第 {token.start[0]} 行）",
                    )
                )
        except (OSError, UnicodeError, tokenize.TokenError, IndentationError):
            continue
    return findings


def check_editor_metadata(root: Path) -> list[ContentFinding]:
    """Code 18: reject the documented 'export with editing information' markers."""

    findings: list[ContentFinding] = []
    for name in (".mcs", "studio.json", "work.mcscfg"):
        path = root / name
        if not path.exists():
            continue
        findings.append(
            _finding(
                root,
                path,
                18,
                "error",
                "工程包含编辑信息",
                "请使用开发工作台的普通导出，而不是“导出（含编辑信息）”",
            )
        )
    return findings


def check_texture_dimensions(root: Path) -> list[ContentFinding]:
    findings: list[ContentFinding] = []
    for path in root.rglob("*"):
        path_parts = {part.casefold() for part in path.parts}
        if (
            not path.is_file()
            or "textures" not in path_parts
            or path.suffix.casefold() not in {".jpeg", ".jpg", ".png", ".tga"}
        ):
            continue
        dimensions = image_dimensions(path)
        if (
            AUDIT_MAX_TEXTURE_DIMENSION
            and dimensions
            and max(dimensions) > AUDIT_MAX_TEXTURE_DIMENSION
        ):
            findings.append(
                _finding(
                    root,
                    path,
                    26,
                    "error",
                    "贴图尺寸超过审核上限",
                    f"{dimensions[0]}x{dimensions[1]} > {AUDIT_MAX_TEXTURE_DIMENSION}",
                )
            )
    return findings


def check_player_entity(root: Path) -> list[ContentFinding]:
    findings: list[ContentFinding] = []
    for path in root.rglob("player.entity.json"):
        if path.parent.name.casefold() != "entity":
            continue
        try:
            document = json.loads(_strip_json_comments(path.read_text(encoding="utf-8-sig")))
            description = document["minecraft:client_entity"]["description"]
            controllers = description.get("render_controllers", [])
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError):
            continue
        present: dict[str, str] = {}
        if isinstance(controllers, list):
            for entry in controllers:
                if not isinstance(entry, dict):
                    continue
                present.update(
                    (str(key), re.sub(r"\s+", "", str(value)))
                    for key, value in entry.items()
                )
        invalid = [
            name
            for name, expression in PLAYER_RENDER_CONTROLLERS.items()
            if present.get(name) != re.sub(r"\s+", "", expression)
        ]
        if invalid:
            findings.append(
                _finding(
                    root,
                    path,
                    29,
                    "error",
                    "player.entity.json 必需渲染控制器缺失或条件错误",
                    "、".join(invalid),
                )
            )
    return findings


def _tag_values(tag: NbtTag, name: str) -> list[object]:
    found = [tag.value] if tag.name == name else []
    if tag.tag_type == 10:
        for child in tag.value:
            found.extend(_tag_values(child, name))
    elif tag.tag_type == 9 and isinstance(tag.value, NbtList):
        for item in tag.value.items:
            if isinstance(item, NbtTag):
                found.extend(_tag_values(item, name))
    return found


def check_level_data(root: Path) -> list[ContentFinding]:
    findings: list[ContentFinding] = []
    level = root / "level.dat"
    map_markers = any((root / name).exists() for name in ("db", "behavior_packs", "resource_packs"))
    if not level.is_file():
        if map_markers:
            findings.append(_finding(root, root, 12, "error", "地图工程缺少 level.dat", "."))
        return findings
    addon_style_manifests = [
        path
        for path in _manifest_paths(root)
        if path.relative_to(root).parts[0].casefold() not in {"behavior_packs", "resource_packs"}
    ]
    if addon_style_manifests:
        findings.append(
            _finding(root, level, 13, "error", "Addon 工程不应包含 Level 地图数据", "level.dat")
        )
    for writable_path in (level, root / "level.dat_old"):
        if writable_path.exists() and not writable_path.stat().st_mode & stat.S_IWRITE:
            findings.append(
                _finding(
                    root,
                    writable_path,
                    23,
                    "error",
                    f"{writable_path.name} 为只读，无法写入",
                    writable_path.name,
                )
            )
    try:
        document = parse_level_dat(
            level.read_bytes(),
            max_depth=LEVEL_DAT_MAX_DEPTH,
            max_items=LEVEL_DAT_MAX_COLLECTION_ITEMS,
        )
    except (OSError, LevelDatParseError) as error:
        findings.append(_finding(root, level, 30, "error", "level.dat 读取或解析失败", str(error)))
        return findings
    versions = _tag_values(document.root, "NetworkVersion")
    numeric_versions = [int(value) for value in versions if isinstance(value, int)]
    if AUDIT_MAX_NETWORK_VERSION and numeric_versions:
        actual = max(numeric_versions)
        if actual > AUDIT_MAX_NETWORK_VERSION:
            findings.append(
                _finding(
                    root,
                    level,
                    31,
                    "error",
                    "地图网络版本高于配置的中国版上限",
                    f"{actual} > {AUDIT_MAX_NETWORK_VERSION}",
                )
            )
    return findings


def check_audio(root: Path) -> list[ContentFinding]:
    findings: list[ContentFinding] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        suffix = path.suffix.casefold()
        if suffix in KNOWN_AUDIO_SUFFIXES:
            findings.append(_finding(root, path, 33, "error", "音效不是 OGG 格式", suffix))
            continue
        if suffix != ".ogg":
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        marker = data.find(b"\x01vorbis")
        if marker < 0 or marker + 24 > len(data):
            findings.append(_finding(root, path, 33, "error", "无法读取 OGG Vorbis 音频信息", "缺少 Vorbis 识别头"))
            continue
        nominal = struct.unpack("<i", data[marker + 20 : marker + 24])[0]
        if nominal > 128_000:
            findings.append(_finding(root, path, 33, "error", "OGG 音效码率超过128kbps", str(nominal)))
    return findings


def check_glyphs(root: Path) -> list[ContentFinding]:
    findings: list[ContentFinding] = []
    for path in root.rglob("glyph_*.png"):
        if path.parent.name.casefold() != "font":
            continue
        dimensions = image_dimensions(path)
        if dimensions != (256, 256):
            findings.append(
                _finding(root, path, 34, "error", "位图字体尺寸必须为256x256", str(dimensions or "无法读取"))
            )
            continue
        invalid_transparency = png_has_invalid_transparent_pixels(path)
        if invalid_transparency is True:
            findings.append(
                _finding(
                    root,
                    path,
                    34,
                    "error",
                    "位图字体透明像素的 RGBA 必须全部为0",
                    "发现透明像素保留了非零 RGB，或图片不是8位 RGBA PNG",
                )
            )
    return findings


def run_content_checks(root_dir: str) -> list[ContentFinding]:
    root = Path(root_dir).resolve()
    checks = (
        check_pack_layout,
        check_map_upload_structure,
        check_level_data,
        check_json_numeric_keys,
        check_python_identifiers,
        check_editor_metadata,
        check_texture_dimensions,
        check_player_entity,
        check_audio,
        check_glyphs,
    )
    return [finding for check in checks for finding in check(root)]


__all__ = ["ContentFinding", "run_content_checks"]
