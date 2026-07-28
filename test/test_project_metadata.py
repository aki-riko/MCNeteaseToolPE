# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""项目许可证与四段版本号的一致性契约。"""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "0.1.0.3"
SPDX_HEADER = "SPDX-License-Identifier: GPL-3.0-or-later"
LEGACY_LICENSE_HEADER = "MIT License " + chr(0x2014) + " MCNeteaseToolPE"
SOURCE_PATTERNS = (
    "*.py",
    "*.ps1",
    ".github/workflows/**/*.yml",
    "installer/**/*.iss",
    "qml/**/*.qml",
    "src/**/*.py",
    "test/**/*.py",
)
LEGACY_CPP_PATHS = (
    "CMakeLists.txt",
    "HANDOFF.md",
    "assets/app_icon.rc",
    "build.bat",
    "src/AuditBackend.cpp",
    "src/AuditBackend.h",
    "src/CleanupBackend.cpp",
    "src/CleanupBackend.h",
    "src/PackScanner.cpp",
    "src/PackScanner.h",
    "src/UuidBackend.cpp",
    "src/UuidBackend.h",
    "src/main.cpp",
    "test/build_test.bat",
    "test/scan_test.cpp",
)


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8-sig")


def _source_files() -> list[Path]:
    files = {
        path
        for pattern in SOURCE_PATTERNS
        for path in PROJECT_ROOT.glob(pattern)
        if path.is_file()
    }
    return sorted(files)


def test_project_version_is_consistent() -> None:
    assert f'"v{EXPECTED_VERSION}"' in _read("src/config.py")
    assert f'#define MyAppVersion "{EXPECTED_VERSION}"' in _read(
        "installer/MCNeteaseToolPE.iss"
    )
    workflow = _read(".github/workflows/release.yml")
    assert r"^v\d+\.\d+\.\d+\.\d+$" in workflow
    assert "vX.Y.Z.W" in workflow
    assert "vX.Y.Z.W" in _read("README.md")


def test_installer_shortcuts_match_prismqml_app_identity() -> None:
    installer = _read("installer/MCNeteaseToolPE.iss")

    assert '#define MyAppUserModelID "PrismQML." + MyAppName' in installer
    assert installer.count('IconFilename: "{app}\\{#MyAppExeName}"') == 2
    assert installer.count('AppUserModelID: "{#MyAppUserModelID}"') == 2


def test_legacy_cpp_implementation_is_removed() -> None:
    for relative_path in LEGACY_CPP_PATHS:
        assert not (PROJECT_ROOT / relative_path).exists(), relative_path


def test_repository_declares_gpl_v3_or_later() -> None:
    license_text = _read("LICENSE")
    assert "GNU GENERAL PUBLIC LICENSE" in license_text
    assert "Version 3, 29 June 2007" in license_text
    assert "END OF TERMS AND CONDITIONS" in license_text
    assert "GPL-3.0-or-later" in _read("README.md")


def test_project_sources_use_gpl_spdx_header() -> None:
    for path in _source_files():
        text = path.read_text(encoding="utf-8-sig")
        header = "\n".join(text.splitlines()[:5])
        assert SPDX_HEADER in header, path.relative_to(PROJECT_ROOT)
        assert LEGACY_LICENSE_HEADER not in text
