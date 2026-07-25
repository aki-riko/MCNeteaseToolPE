# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
# Python 2.7 代码审核器的 Python 3 适配层。
# Python 3 adapter for the Python 2.7 code auditor.

"""Launch the bundled Python 2.7/Pylint 1.9.5 worker when available."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from hashlib import sha1
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
from typing import Callable, Iterator, Sequence


LEGACY_PYLINT_MESSAGE_IDS = ("E",)
LEGACY_PYLINT_IGNORED_MESSAGE_IDS = ("E1601", "E0401", "E1101", "E1102")
PY27_RUNTIME_ENV = "MCNETEASE_PY27_RUNTIME"
MC_STUBS_ENV = "MCNETEASE_MC_STUBS"
TIMEOUT_ENV = "MCNETEASE_PY27_TIMEOUT_SECONDS"
WORKER_COUNT_ENV = "MCNETEASE_PY27_WORKERS"
DEFAULT_TIMEOUT_SECONDS = 600


class LegacyPylintUnavailable(RuntimeError):
    """Raised when the optional Python 2.7 runtime is not installed."""


def _candidate_roots() -> list[Path]:
    roots: list[Path] = []
    source_root = Path(__file__).resolve().parents[1]
    roots.append(source_root)
    executable_root = Path(sys.executable).resolve().parent
    if executable_root not in roots:
        roots.append(executable_root)
    return roots


def _runtime_command() -> tuple[str, list[str]]:
    configured = os.environ.get(PY27_RUNTIME_ENV, "").strip()
    if configured:
        path = Path(configured).expanduser()
        if path.is_dir():
            path = path / "python.exe"
        if path.is_file():
            return str(path.resolve()), []
        raise LegacyPylintUnavailable(f"{PY27_RUNTIME_ENV} 指向的 Python 不存在: {path}")

    for root in _candidate_roots():
        packaged = root / "runtime" / "python27" / "python.exe"
        if packaged.is_file():
            return str(packaged), []

    launcher = shutil.which("py") or shutil.which("py.exe")
    if launcher:
        try:
            probe = subprocess.run(
                [launcher, "-2.7-32", "-c", "import sys; sys.exit(0 if sys.version_info[:2] == (2, 7) else 1)"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            probe = None
        if probe is not None and probe.returncode == 0:
            return launcher, ["-2.7-32"]
    raise LegacyPylintUnavailable(
        "未找到 Python 2.7 运行时；请设置 MCNETEASE_PY27_RUNTIME，"
        "或在发布包中提供 runtime/python27/python.exe"
    )


def _worker_path() -> Path:
    for root in _candidate_roots():
        worker = root / "src" / "legacy_pylint_worker.py"
        if worker.is_file():
            return worker
    raise LegacyPylintUnavailable("Python 2.7 审核器 worker 文件缺失")


def _stubs_path() -> Path | None:
    configured = os.environ.get(MC_STUBS_ENV, "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_dir():
            raise LegacyPylintUnavailable(f"{MC_STUBS_ENV} 指向的补全库目录不存在: {path}")
        return path.resolve()
    for root in _candidate_roots():
        packaged = root / "mc_stubs"
        if packaged.is_dir():
            return packaged
    return None


def _child_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("PYLINTRC", None)
    stubs = _stubs_path()
    if stubs is not None:
        existing = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = os.pathsep.join(
            item for item in (str(stubs), existing) if item
        )
    return environment


def _timeout_seconds() -> int:
    value = os.environ.get(TIMEOUT_ENV, "").strip()
    if not value:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        timeout = int(value)
    except ValueError as error:
        raise LegacyPylintUnavailable(f"{TIMEOUT_ENV} 不是整数: {value}") from error
    if timeout <= 0:
        raise LegacyPylintUnavailable(f"{TIMEOUT_ENV} 必须大于 0: {value}")
    return timeout


def _worker_count(file_count: int) -> int:
    if file_count <= 0:
        return 0
    value = os.environ.get(WORKER_COUNT_ENV, "").strip()
    if value:
        try:
            requested = int(value)
        except ValueError as error:
            raise ValueError(f"{WORKER_COUNT_ENV} 不是整数: {value}") from error
        if requested <= 0:
            raise ValueError(f"{WORKER_COUNT_ENV} 必须大于 0: {value}")
    else:
        logical_processors = os.cpu_count() or 1
        requested = logical_processors
    return min(requested, file_count)


def _has_non_ascii_path(path: Path) -> bool:
    return any(ord(character) > 127 for character in str(path))


def _safe_component(component: str) -> str:
    if all(ord(character) < 128 for character in component):
        return component
    digest = sha1(component.encode("utf-8")).hexdigest()[:12]
    return f"unicode_{digest}"


@contextmanager
def _worker_inputs(files: Sequence[str]) -> Iterator[tuple[list[str], dict[str, str], str]]:
    originals = [Path(path).resolve() for path in files]
    if not any(_has_non_ascii_path(path) for path in originals):
        yield [str(path) for path in originals], {}, str(_worker_path().parents[1])
        return

    common_root = Path(os.path.commonpath([str(path.parent) for path in originals]))
    with tempfile.TemporaryDirectory(prefix="mcnetease-py27-") as temporary:
        mirror_root = Path(temporary)
        mirrored: list[str] = []
        path_map: dict[str, str] = {}
        for original in originals:
            relative = original.relative_to(common_root)
            target = mirror_root.joinpath(*(_safe_component(part) for part in relative.parts))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target)
            resolved = str(target.resolve())
            mirrored.append(resolved)
            path_map[os.path.normcase(resolved)] = str(original)
        yield mirrored, path_map, str(mirror_root)


def _worker_payload(
    files: Sequence[str],
    message_ids: Sequence[str],
    ignored_message_ids: Sequence[str],
) -> bytes:
    return json.dumps(
        {
            "files": list(files),
            "message_ids": list(message_ids),
            "ignored_message_ids": list(ignored_message_ids),
        },
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _execute_worker_stream(
    command: list[str],
    payload: bytes,
    working_directory: str,
    line_received: Callable[[bytes], None],
) -> subprocess.CompletedProcess[bytes]:
    timeout = _timeout_seconds()
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=working_directory,
            env=_child_environment(),
        )
    except OSError as error:
        raise LegacyPylintUnavailable(f"Python 2.7 代码审核启动失败: {error}") from error

    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    stderr_chunks: list[bytes] = []
    stderr_reader = threading.Thread(
        target=lambda: stderr_chunks.append(process.stderr.read()),
        name="python27-audit-stderr",
        daemon=True,
    )
    timed_out = threading.Event()

    def kill_after_timeout() -> None:
        timed_out.set()
        try:
            process.kill()
        except OSError:
            pass

    timer = threading.Timer(timeout, kill_after_timeout)
    stdout = bytearray()
    stderr_reader.start()
    timer.start()
    try:
        process.stdin.write(payload)
        process.stdin.close()
        for line in process.stdout:
            stdout.extend(line)
            line_received(line)
        return_code = process.wait()
    except BaseException:
        process.kill()
        process.wait()
        raise
    finally:
        timer.cancel()
        stderr_reader.join()
    if timed_out.is_set():
        raise LegacyPylintUnavailable(
            f"Python 2.7 代码审核启动失败: 执行超过 {timeout} 秒"
        )
    return subprocess.CompletedProcess(
        command,
        return_code,
        bytes(stdout),
        b"".join(stderr_chunks),
    )


def _execute_worker(
    command: list[str],
    payload: bytes,
    working_directory: str,
    line_received: Callable[[bytes], None] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    if line_received is not None:
        return _execute_worker_stream(
            command,
            payload,
            working_directory,
            line_received,
        )
    try:
        return subprocess.run(
            command,
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=working_directory,
            env=_child_environment(),
            timeout=_timeout_seconds(),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise LegacyPylintUnavailable(f"Python 2.7 代码审核启动失败: {error}") from error


def _parse_worker_event(line: bytes) -> dict[str, object]:
    try:
        payload = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Python 2.7 Pylint 输出不是有效 JSON 行: {error}") from error
    if not isinstance(payload, dict):
        raise RuntimeError("Python 2.7 Pylint JSON 行顶层不是对象")
    event_type = payload.get("type")
    if event_type == "progress":
        if not isinstance(payload.get("path"), str):
            raise RuntimeError("Python 2.7 Pylint 进度事件缺少文件路径")
        return payload
    if event_type == "result":
        messages = payload.get("messages")
        if not isinstance(messages, list) or not all(isinstance(item, dict) for item in messages):
            raise RuntimeError("Python 2.7 Pylint 返回的 messages 不是对象列表")
        return payload
    raise RuntimeError(f"Python 2.7 Pylint 返回未知事件类型: {event_type}")


def _parse_worker_result(completed: subprocess.CompletedProcess[bytes]) -> list[dict[str, object]]:
    stderr = completed.stderr.decode("utf-8", errors="replace").strip()
    if completed.returncode != 0:
        detail = stderr.splitlines()[-1] if stderr else f"退出码 {completed.returncode}"
        raise RuntimeError(f"Python 2.7 Pylint 执行失败: {detail}")
    result: list[dict[str, object]] | None = None
    for line in completed.stdout.splitlines():
        event = _parse_worker_event(line)
        if event.get("type") != "result":
            continue
        if result is not None:
            raise RuntimeError("Python 2.7 Pylint 重复返回结果事件")
        result = event["messages"]
    if result is None:
        detail = stderr.splitlines()[-1] if stderr else "无 stderr"
        raise RuntimeError(f"Python 2.7 Pylint 未返回结果事件: {detail}")
    return result


def _restore_source_paths(
    messages: list[dict[str, object]], path_map: dict[str, str], working_directory: str
) -> None:
    for message in messages:
        value = str(message.get("path", ""))
        if not value:
            continue
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = Path(working_directory) / candidate
        original = path_map.get(os.path.normcase(str(candidate.resolve())))
        if original is not None:
            message["path"] = original


def _restore_progress_path(value: str, path_map: dict[str, str], working_directory: str) -> str:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = Path(working_directory) / candidate
    resolved = str(candidate.resolve())
    return path_map.get(os.path.normcase(resolved), resolved)


def _partition_files(files: Sequence[str], worker_count: int) -> list[list[str]]:
    chunk_size, remainder = divmod(len(files), worker_count)
    chunks: list[list[str]] = []
    cursor = 0
    for index in range(worker_count):
        size = chunk_size + (1 if index < remainder else 0)
        chunks.append(list(files[cursor:cursor + size]))
        cursor += size
    return chunks


def _run_worker_chunk(
    command: list[str],
    files: Sequence[str],
    message_ids: Sequence[str],
    ignored_message_ids: Sequence[str],
    working_directory: str,
    file_completed: Callable[[str], None] | None = None,
) -> list[dict[str, object]]:
    payload = _worker_payload(files, message_ids, ignored_message_ids)

    def handle_line(line: bytes) -> None:
        event = _parse_worker_event(line)
        if event.get("type") == "progress" and file_completed is not None:
            file_completed(event["path"])

    completed = _execute_worker(
        command,
        payload,
        working_directory,
        handle_line if file_completed is not None else None,
    )
    return _parse_worker_result(completed)


def _run_worker_chunks(
    command: list[str],
    files: Sequence[str],
    message_ids: Sequence[str],
    ignored_message_ids: Sequence[str],
    working_directory: str,
    file_completed: Callable[[str], None] | None = None,
) -> list[dict[str, object]]:
    chunks = _partition_files(files, _worker_count(len(files)))
    if len(chunks) == 1:
        return _run_worker_chunk(
            command,
            chunks[0],
            message_ids,
            ignored_message_ids,
            working_directory,
            file_completed,
        )

    with ThreadPoolExecutor(max_workers=len(chunks), thread_name_prefix="python27-audit") as executor:
        futures = [
            executor.submit(
                _run_worker_chunk,
                command,
                chunk,
                message_ids,
                ignored_message_ids,
                working_directory,
                file_completed,
            )
            for chunk in chunks
        ]
        messages: list[dict[str, object]] = []
        for future in futures:
            messages.extend(future.result())
        return messages


def run_legacy_pylint(
    files: Sequence[str],
    message_ids: Sequence[str] = LEGACY_PYLINT_MESSAGE_IDS,
    ignored_message_ids: Sequence[str] = LEGACY_PYLINT_IGNORED_MESSAGE_IDS,
    progress: Callable[[int, int, str], None] | None = None,
) -> list[dict[str, object]]:
    """Run the real Python 2.7 Pylint worker and return its JSON messages."""

    if not files:
        return []
    program, prefix = _runtime_command()
    worker = _worker_path()
    command = [program, *prefix, "-u", str(worker)]
    with _worker_inputs(files) as (worker_files, path_map, working_directory):
        completed_count = 0
        progress_lock = threading.Lock()

        def report_file_completed(path: str) -> None:
            nonlocal completed_count
            if progress is None:
                return
            restored_path = _restore_progress_path(path, path_map, working_directory)
            with progress_lock:
                completed_count += 1
                progress(completed_count, len(worker_files), restored_path)

        result = _run_worker_chunks(
            command,
            worker_files,
            message_ids,
            ignored_message_ids,
            working_directory,
            report_file_completed if progress is not None else None,
        )
        if progress is not None and completed_count != len(worker_files):
            raise RuntimeError(
                "Python 2.7 Pylint 文件进度不完整: "
                f"{completed_count}/{len(worker_files)}"
            )
        _restore_source_paths(result, path_map, working_directory)
        return result


def python27_command() -> tuple[str, list[str]]:
    """Return the configured Python 2.7 executable and launcher arguments."""

    return _runtime_command()


__all__ = [
    "LEGACY_PYLINT_MESSAGE_IDS",
    "LEGACY_PYLINT_IGNORED_MESSAGE_IDS",
    "WORKER_COUNT_ENV",
    "LegacyPylintUnavailable",
    "python27_command",
    "run_legacy_pylint",
]
