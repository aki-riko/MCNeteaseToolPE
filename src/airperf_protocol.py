# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""AirPerf aphost 的本地 ZeroMQ RPC 协议实现。"""

from __future__ import annotations

import ctypes
import json
import logging
import os
from pathlib import Path
import threading
from typing import Callable, Protocol


LOGGER = logging.getLogger(__name__)
ZMQ_REQ = 3
ZMQ_LINGER = 17
ZMQ_RCVTIMEO = 27
ZMQ_SNDTIMEO = 28
ZMQ_EAGAIN = 11


class AirPerfProtocolError(RuntimeError):
    """aphost 协议、传输或返回值无效。"""


class AirPerfRpcError(AirPerfProtocolError):
    """aphost 返回 isOk=false。"""


class _RequestTransport(Protocol):
    def request(self, payload: bytes) -> bytes: ...

    def close(self) -> None: ...


def encode_request(
    class_name: str,
    method_name: str,
    arguments: list[object] | None = None,
) -> bytes:
    """按 aphost 的 ``Class___method`` 格式编码请求。"""

    command = f"{class_name}___{method_name}"
    body = {"cmd": command, "parameter": arguments}
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def decode_response(payload: bytes) -> object:
    """校验并解出 aphost 的 ``isOk/return`` 响应。"""

    try:
        response = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AirPerfProtocolError("aphost 返回了无效 JSON") from error
    if not isinstance(response, dict) or not isinstance(response.get("isOk"), bool):
        raise AirPerfProtocolError("aphost 响应缺少 isOk 字段")
    result = response.get("return")
    if not response["isOk"]:
        raise AirPerfRpcError(str(result or "aphost RPC 调用失败"))
    return result


class _ZmqMessage(ctypes.Structure):
    _fields_ = [("data", ctypes.c_ubyte * 64)]


class CtypesZmqTransport:
    """仅通过 libzmq C ABI 通信，不引入 pyzmq 运行时依赖。"""

    def __init__(self, dll_path: Path, endpoint: str, timeout_ms: int) -> None:
        self._dll_path = Path(dll_path)
        self._endpoint = endpoint.encode("ascii")
        self._timeout_ms = int(timeout_ms)
        self._lock = threading.Lock()
        self._dll_directory = None
        self._library = self._load_library()
        self._configure_abi()
        self._context = self._library.zmq_ctx_new()
        self._socket: int | None = None
        if not self._context:
            raise AirPerfProtocolError("无法创建 ZeroMQ 上下文")

    def _load_library(self) -> ctypes.CDLL:
        if not self._dll_path.is_file():
            raise AirPerfProtocolError(f"未找到 AirPerf libzmq：{self._dll_path}")
        if os.name == "nt" and hasattr(os, "add_dll_directory"):
            self._dll_directory = os.add_dll_directory(str(self._dll_path.parent))
        try:
            return ctypes.CDLL(str(self._dll_path))
        except OSError as error:
            raise AirPerfProtocolError(f"加载 AirPerf libzmq 失败：{error}") from error

    def _configure_abi(self) -> None:
        self._configure_socket_abi()
        self._configure_message_abi()

    def _configure_socket_abi(self) -> None:
        library = self._library
        library.zmq_ctx_new.argtypes = []
        library.zmq_ctx_new.restype = ctypes.c_void_p
        library.zmq_ctx_term.argtypes = [ctypes.c_void_p]
        library.zmq_ctx_term.restype = ctypes.c_int
        library.zmq_socket.argtypes = [ctypes.c_void_p, ctypes.c_int]
        library.zmq_socket.restype = ctypes.c_void_p
        library.zmq_close.argtypes = [ctypes.c_void_p]
        library.zmq_close.restype = ctypes.c_int
        library.zmq_connect.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        library.zmq_connect.restype = ctypes.c_int
        library.zmq_setsockopt.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_size_t,
        ]
        library.zmq_setsockopt.restype = ctypes.c_int
        library.zmq_send.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
        library.zmq_send.restype = ctypes.c_int
        library.zmq_errno.argtypes = []
        library.zmq_errno.restype = ctypes.c_int
        library.zmq_strerror.argtypes = [ctypes.c_int]
        library.zmq_strerror.restype = ctypes.c_char_p

    def _configure_message_abi(self) -> None:
        library = self._library
        library.zmq_msg_init.argtypes = [ctypes.POINTER(_ZmqMessage)]
        library.zmq_msg_init.restype = ctypes.c_int
        library.zmq_msg_recv.argtypes = [ctypes.POINTER(_ZmqMessage), ctypes.c_void_p, ctypes.c_int]
        library.zmq_msg_recv.restype = ctypes.c_int
        library.zmq_msg_size.argtypes = [ctypes.POINTER(_ZmqMessage)]
        library.zmq_msg_size.restype = ctypes.c_size_t
        library.zmq_msg_data.argtypes = [ctypes.POINTER(_ZmqMessage)]
        library.zmq_msg_data.restype = ctypes.c_void_p
        library.zmq_msg_close.argtypes = [ctypes.POINTER(_ZmqMessage)]
        library.zmq_msg_close.restype = ctypes.c_int

    def _set_integer_option(self, socket: int, option: int, value: int) -> None:
        raw_value = ctypes.c_int(value)
        result = self._library.zmq_setsockopt(
            socket,
            option,
            ctypes.byref(raw_value),
            ctypes.sizeof(raw_value),
        )
        if result == -1:
            self._raise_last_error("设置 ZeroMQ socket 选项失败")

    def _create_socket(self) -> int:
        socket = self._library.zmq_socket(self._context, ZMQ_REQ)
        if not socket:
            self._raise_last_error("创建 ZeroMQ REQ socket 失败")
        self._set_integer_option(socket, ZMQ_LINGER, 0)
        self._set_integer_option(socket, ZMQ_RCVTIMEO, self._timeout_ms)
        self._set_integer_option(socket, ZMQ_SNDTIMEO, self._timeout_ms)
        if self._library.zmq_connect(socket, self._endpoint) == -1:
            self._library.zmq_close(socket)
            self._raise_last_error("连接 aphost 失败")
        return socket

    def _raise_last_error(self, prefix: str) -> None:
        number = self._library.zmq_errno()
        if number == ZMQ_EAGAIN:
            raise TimeoutError(f"{prefix}：等待 aphost 超时")
        raw_message = self._library.zmq_strerror(number)
        message = raw_message.decode("utf-8", "replace") if raw_message else str(number)
        raise AirPerfProtocolError(f"{prefix}：{message}")

    def _reset_socket(self) -> None:
        if self._socket:
            self._library.zmq_close(self._socket)
        self._socket = None

    def request(self, payload: bytes) -> bytes:
        with self._lock:
            try:
                return self._request_locked(payload)
            except (AirPerfProtocolError, TimeoutError):
                self._reset_socket()
                raise

    def _request_locked(self, payload: bytes) -> bytes:
        if not self._socket:
            self._socket = self._create_socket()
        buffer = ctypes.create_string_buffer(payload)
        sent = self._library.zmq_send(self._socket, buffer, len(payload), 0)
        if sent == -1:
            self._raise_last_error("发送 aphost 请求失败")
        message = _ZmqMessage()
        if self._library.zmq_msg_init(ctypes.byref(message)) == -1:
            self._raise_last_error("初始化 ZeroMQ 消息失败")
        try:
            if self._library.zmq_msg_recv(ctypes.byref(message), self._socket, 0) == -1:
                self._raise_last_error("接收 aphost 响应失败")
            size = self._library.zmq_msg_size(ctypes.byref(message))
            address = self._library.zmq_msg_data(ctypes.byref(message))
            return ctypes.string_at(address, size)
        finally:
            self._library.zmq_msg_close(ctypes.byref(message))

    def close(self) -> None:
        with self._lock:
            self._reset_socket()
            if self._context:
                self._library.zmq_ctx_term(self._context)
                self._context = None
            if self._dll_directory is not None:
                self._dll_directory.close()
                self._dll_directory = None


class AirPerfProtocol:
    """aphost RPC 的类型安全薄封装。"""

    def __init__(
        self,
        dll_path: Path | None = None,
        endpoint: str | None = None,
        timeout_ms: int = 1500,
        transport: _RequestTransport | None = None,
    ) -> None:
        if transport is None and (dll_path is None or endpoint is None):
            raise ValueError("创建 AirPerfProtocol 时必须提供 dll_path、endpoint 或 transport")
        self._transport = transport or CtypesZmqTransport(
            Path(dll_path), endpoint, timeout_ms  # type: ignore[arg-type]
        )

    def call(self, class_name: str, method_name: str, arguments: list[object] | None = None) -> object:
        payload = encode_request(class_name, method_name, arguments)
        return decode_response(self._transport.request(payload))

    def check_init_done(self) -> bool:
        return bool(self.call("ServerUtil", "checkInitDone"))

    def get_counter(self, category: str) -> dict[str, object]:
        result = self.call("Profiler", "get_counter", [category])
        return result if isinstance(result, dict) else {}

    def get_data(self, category: str, counter: str, instance: str, host: str = "") -> object:
        return self.call("Profiler", "get_data", [host, category, counter, instance])

    def clear_data(self, category: str, counter: str, instance: str, host: str = "") -> object:
        return self.call("Profiler", "clear_data", [host, category, counter, instance])

    def remove_counter(self, key: str) -> object:
        return self.call("PerfmonUtil", "removeCounter", [key])

    def close(self) -> None:
        self._transport.close()


__all__ = [
    "AirPerfProtocol",
    "AirPerfProtocolError",
    "AirPerfRpcError",
    "CtypesZmqTransport",
    "decode_response",
    "encode_request",
]
