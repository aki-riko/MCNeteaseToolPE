# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""原生 Tracy 抓取、归约和对比回归测试。"""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess

import pytest

from src.tracy_analysis import (
    TracyAnalysisError,
    capture_tracy,
    diff_tracy_captures,
    parse_capture_stats,
    probe_tracy,
    reduce_tracy_csv,
    validate_tracy_endpoint,
)


ROOT = Path(__file__).resolve().parents[1]
TRACY_BIN = ROOT / "tracy_bin"
BUILD_SCRIPT = ROOT / "build_nuitka.ps1"
THIRD_PARTY_NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"
CSV_HEADER = "name,src_file,src_line,total_ns,total_perc,counts,mean_ns,min_ns,max_ns,std_ns"
SELF_CSV = "\n".join(
    [
        CSV_HEADER,
        "update,Demo.Server.Main,10,2000000,0,4,500000,1,2,3",
        "render,Demo.Client.Main,20,500000,0,8,62500,1,2,3",
    ]
) + "\n"
TOTAL_CSV = "\n".join(
    [
        CSV_HEADER,
        "update,Demo.Server.Main,10,9000000,0,4,2250000,1,2,3",
        "render,Demo.Client.Main,20,1200000,0,8,150000,1,2,3",
    ]
) + "\n"


def test_bundled_tracy_cli_matches_official_v0111_hashes() -> None:
    expected = {
        "tracy-capture.exe": "ca5f7e69bdf4194e14563c8ef9005187032b7a77c3ad464c01a507b2a1e6c659",
        "tracy-csvexport.exe": "67d7afed782bd84d8a2d4fa04f3d65062e7088bb54f3b7c90f628c3a97b1d144",
    }
    for name, digest in expected.items():
        assert hashlib.sha256((TRACY_BIN / name).read_bytes()).hexdigest() == digest
    assert (TRACY_BIN / "TRACY_LICENSE.txt").is_file()
    assert (TRACY_BIN / "MCDK_MCP_TRACY_LICENSE.txt").is_file()


def test_tracy_cli_is_declared_for_packaging_and_attribution() -> None:
    build_source = BUILD_SCRIPT.read_text(encoding="utf-8-sig")
    notices = THIRD_PARTY_NOTICES.read_text(encoding="utf-8")

    assert '--include-data-dir=$tracyBin=tracy_bin' in build_source
    assert '--include-data-file=$thirdPartyNotices=THIRD_PARTY_NOTICES.md' in build_source
    assert 'Join-Path $tracyBin "tracy-capture.exe"' in build_source
    assert 'Join-Path $tracyBin "tracy-csvexport.exe"' in build_source
    assert "491d3390aa470c3d8a9e9932c038741277391a6a" in notices
    assert "E01E73903DD8BABB634CB9AE48F3D5B52F3B519CF895548DD06538190554DC8A" in notices
    assert "CA5F7E69BDF4194E14563C8EF9005187032B7A77C3AD464C01A507B2A1E6C659" in notices
    assert "67D7AFED782BD84D8A2D4FA04F3D65062E7088BB54F3B7C90F628C3A97B1D144" in notices


def test_reduce_csv_merges_and_ranks_function_costs() -> None:
    rows = reduce_tracy_csv(SELF_CSV, TOTAL_CSV)

    assert [row["function"] for row in rows] == ["update", "render"]
    assert rows[0]["selfMs"] == 2.0
    assert rows[0]["totalMs"] == 9.0
    assert rows[0]["calls"] == 4
    assert rows[0]["selfPerCallMs"] == 0.5


def test_reduce_csv_sums_calls_when_same_function_has_multiple_lines() -> None:
    duplicated = "\n".join(
        [
            CSV_HEADER,
            "update,Demo.Server.Main,10,1000000,0,2,0,0,0,0",
            "update,Demo.Server.Main,11,2000000,0,3,0,0,0,0",
        ]
    ) + "\n"

    row = reduce_tracy_csv(duplicated, duplicated)[0]

    assert row["selfMs"] == 3.0
    assert row["calls"] == 5


def test_parse_capture_stats_handles_counts_and_missing_fields() -> None:
    assert parse_capture_stats("Frames: 830\nZones: 180,446\n") == {
        "frames": 830,
        "zones": 180446,
    }
    assert parse_capture_stats("Connecting...\n") == {"frames": None, "zones": None}


def test_capture_keeps_full_rows_while_filtering_inline(monkeypatch, tmp_path: Path) -> None:
    for name in ("tracy-capture.exe", "tracy-csvexport.exe"):
        (tmp_path / name).write_bytes(b"verified-test-placeholder")
    calls: list[list[str]] = []

    def fake_run(arguments: list[str], timeout: float) -> subprocess.CompletedProcess[bytes]:
        calls.append(arguments)
        if arguments[0].endswith("tracy-capture.exe"):
            output_path = Path(arguments[arguments.index("-o") + 1])
            output_path.write_bytes(b"trace")
            return subprocess.CompletedProcess(
                arguments,
                0,
                stdout=b"Frames: 120\nZones: 2,400\n",
                stderr=b"",
            )
        csv_output = SELF_CSV if "-e" in arguments else TOTAL_CSV
        return subprocess.CompletedProcess(
            arguments,
            0,
            stdout=csv_output.encode("utf-8"),
            stderr=b"",
        )

    monkeypatch.setattr("src.tracy_analysis._run_tool", fake_run)
    result = capture_tracy(
        2,
        name_contains="Demo.Server",
        environment={"MCNETEASE_TRACY_BIN_DIR": str(tmp_path)},
    )

    assert len(calls) == 3
    assert result["frames"] == 120
    assert result["averageFps"] == 60.0
    assert result["uniqueFunctions"] == 2
    assert result["matchedFunctions"] == 1
    assert len(result["rows"]) == 2
    assert len(result["top"]) == 1
    assert result["top"][0]["selfPerFrameMs"] == pytest.approx(2.0 / 120, abs=1e-6)


def test_diff_reports_improvements_and_regressions() -> None:
    base = {
        "captureId": "capture-1",
        "seconds": 10,
        "rows": [
            {"name": "hot @ Demo", "selfMs": 10.0},
            {"name": "warm @ Demo", "selfMs": 5.0},
        ],
    }
    new = {
        "captureId": "capture-2",
        "seconds": 10,
        "rows": [
            {"name": "hot @ Demo", "selfMs": 4.0},
            {"name": "warm @ Demo", "selfMs": 7.0},
        ],
    }

    result = diff_tracy_captures(base, new, "Demo")

    assert result["summary"]["deltaMs"] == -4.0
    assert result["improved"][0]["name"] == "hot @ Demo"
    assert result["improved"][0]["deltaMs"] == -6.0
    assert result["regressed"][0]["name"] == "warm @ Demo"
    assert result["regressed"][0]["deltaMs"] == 2.0


def test_diff_excludes_verified_wait_zone_from_change_summary() -> None:
    result = diff_tracy_captures(
        {
            "captureId": "base",
            "seconds": 10,
            "rows": [
                {"name": "sleep @ time", "selfMs": 100.0},
                {"name": "update @ Engine", "selfMs": 10.0},
            ],
        },
        {
            "captureId": "new",
            "seconds": 10,
            "rows": [
                {"name": "sleep @ time", "selfMs": 10.0},
                {"name": "update @ Engine", "selfMs": 12.0},
            ],
        },
    )

    assert result["summary"]["deltaMs"] == 2.0
    changed_names = {
        item["name"]
        for key in ("improved", "regressed", "added", "removed")
        for item in result[key]
    }
    assert "sleep @ time" not in changed_names


def test_diff_separates_added_and_removed_functions() -> None:
    result = diff_tracy_captures(
        {
            "captureId": "base",
            "seconds": 10,
            "rows": [{"name": "removed", "selfMs": 5.0}],
        },
        {
            "captureId": "new",
            "seconds": 10,
            "rows": [{"name": "added", "selfMs": 7.0}],
        },
    )

    assert result["summary"]["deltaMs"] == 2.0
    assert result["improved"] == []
    assert result["regressed"] == []
    assert result["removed"][0]["name"] == "removed"
    assert result["removed"][0]["newMs"] == 0.0
    assert result["added"][0]["name"] == "added"
    assert result["added"][0]["baseMs"] == 0.0


def test_diff_uses_complete_rows_beyond_display_limit() -> None:
    base_rows = [
        {"name": f"function-{index:03d}", "selfMs": 1.0}
        for index in range(501)
    ]
    new_rows = [dict(row) for row in base_rows]
    new_rows[-1]["selfMs"] = 3.0

    result = diff_tracy_captures(
        {"captureId": "base", "seconds": 10, "rows": base_rows},
        {"captureId": "new", "seconds": 10, "rows": new_rows},
    )

    assert result["summary"]["deltaMs"] == 2.0
    assert result["regressed"][0]["name"] == "function-500"


def test_diff_rejects_different_capture_windows() -> None:
    with pytest.raises(TracyAnalysisError, match="采样时长不同"):
        diff_tracy_captures(
            {"captureId": "a", "seconds": 5, "rows": []},
            {"captureId": "b", "seconds": 10, "rows": []},
        )


@pytest.mark.parametrize("address", ["192.168.1.10", "example.com"])
def test_tracy_endpoint_rejects_non_loopback_hosts(address: str) -> None:
    with pytest.raises(TracyAnalysisError):
        validate_tracy_endpoint(address, 8086)


def test_probe_reports_injected_bin_state_without_external_connection(tmp_path: Path) -> None:
    result = probe_tracy(
        timeout=0.05,
        environment={"MCNETEASE_TRACY_BIN_DIR": str(tmp_path)},
    )

    assert result["binAvailable"] is False
    assert result["binDir"] == str(tmp_path)
