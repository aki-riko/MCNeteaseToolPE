# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""无第三方依赖的审核用图片头与 PNG 像素读取工具。"""

from __future__ import annotations

from pathlib import Path
import struct
import zlib


def image_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if path.suffix.casefold() == ".tga" and len(data) >= 18:
        return struct.unpack("<HH", data[12:16])
    if data.startswith(b"\xff\xd8"):
        offset = 2
        while offset + 9 <= len(data):
            if data[offset] != 0xFF:
                offset += 1
                continue
            marker = data[offset + 1]
            offset += 2
            if marker in {0xD8, 0xD9}:
                continue
            if offset + 2 > len(data):
                break
            size = struct.unpack(">H", data[offset : offset + 2])[0]
            start_of_frame = {
                0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
            }
            if marker in start_of_frame:
                height, width = struct.unpack(">HH", data[offset + 3 : offset + 7])
                return width, height
            offset += max(size, 2)
    return None


def png_has_invalid_transparent_pixels(path: Path) -> bool | None:
    """Return whether an 8-bit RGBA PNG has nonzero RGB under alpha zero."""

    try:
        data = path.read_bytes()
    except OSError:
        return None
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    offset = 8
    width = height = 0
    image_data = bytearray()
    supported = False
    while offset + 12 <= len(data):
        size = struct.unpack(">I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + size]
        offset += 12 + size
        if kind == b"IHDR" and len(payload) == 13:
            width, height, depth, color_type, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
            supported = (depth, color_type, compression, filtering, interlace) == (8, 6, 0, 0, 0)
        elif kind == b"IDAT":
            image_data.extend(payload)
        elif kind == b"IEND":
            break
    if not supported or width <= 0 or height <= 0:
        return True
    try:
        raw = zlib.decompress(bytes(image_data))
    except zlib.error:
        return None
    stride = width * 4
    if len(raw) != height * (stride + 1):
        return None
    previous = bytearray(stride)
    cursor = 0
    for _row in range(height):
        filter_type = raw[cursor]
        current = bytearray(raw[cursor + 1 : cursor + 1 + stride])
        cursor += stride + 1
        for index in range(stride):
            left = current[index - 4] if index >= 4 else 0
            up = previous[index]
            upper_left = previous[index - 4] if index >= 4 else 0
            if filter_type == 1:
                current[index] = (current[index] + left) & 0xFF
            elif filter_type == 2:
                current[index] = (current[index] + up) & 0xFF
            elif filter_type == 3:
                current[index] = (current[index] + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                predictor = left + up - upper_left
                candidates = (left, up, upper_left)
                distances = tuple(abs(predictor - value) for value in candidates)
                predicted = candidates[distances.index(min(distances))]
                current[index] = (current[index] + predicted) & 0xFF
            elif filter_type != 0:
                return None
        for index in range(0, stride, 4):
            if current[index + 3] == 0 and any(current[index : index + 3]):
                return True
        previous = current
    return False


def png_transparent_pixel_status(path: Path) -> str | None:
    """Classify transparent-pixel validity without treating every code 34 alike."""

    invalid = png_has_invalid_transparent_pixels(path)
    if invalid is False:
        return "valid"
    if invalid is None:
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) < 33 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "unsupported"
    payload = data[16:29]
    if data[12:16] != b"IHDR" or len(payload) != 13:
        return "unsupported"
    _width, _height, depth, color_type, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", payload
    )
    supported = (depth, color_type, compression, filtering, interlace) == (8, 6, 0, 0, 0)
    return "invalid" if supported else "unsupported"


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)


def normalize_png_transparent_pixels(data: bytes) -> bytes | None:
    """Return a visually identical RGBA PNG with RGB cleared under alpha zero.

    Unsupported PNG variants and already-valid images return ``None``. Ancillary
    chunks are preserved byte-for-byte; only IDAT is regenerated with filter 0.
    """

    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    offset = 8
    chunks: list[tuple[bytes, bytes, bytes]] = []
    image_data = bytearray()
    width = height = 0
    supported = False
    saw_iend = False
    while offset + 12 <= len(data):
        size = struct.unpack(">I", data[offset : offset + 4])[0]
        end = offset + 12 + size
        if end > len(data):
            return None
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + size]
        raw_chunk = data[offset:end]
        chunks.append((kind, payload, raw_chunk))
        offset = end
        if kind == b"IHDR" and len(payload) == 13:
            width, height, depth, color_type, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
            supported = (depth, color_type, compression, filtering, interlace) == (8, 6, 0, 0, 0)
        elif kind == b"IDAT":
            image_data.extend(payload)
        elif kind == b"IEND":
            saw_iend = True
            break
    if not saw_iend or offset != len(data) or not supported or width <= 0 or height <= 0:
        return None
    try:
        raw = zlib.decompress(bytes(image_data))
    except zlib.error:
        return None
    normalized = _normalize_rgba_scanlines(raw, width, height)
    if normalized is None:
        return None
    scanlines, changed = normalized
    if not changed:
        return None
    output = bytearray(data[:8])
    emitted_idat = False
    for kind, _payload, raw_chunk in chunks:
        if kind == b"IDAT":
            if not emitted_idat:
                output.extend(_png_chunk(b"IDAT", zlib.compress(scanlines)))
                emitted_idat = True
            continue
        output.extend(raw_chunk)
    return bytes(output) if emitted_idat else None


def _normalize_rgba_scanlines(raw: bytes, width: int, height: int) -> tuple[bytes, bool] | None:
    stride = width * 4
    if len(raw) != height * (stride + 1):
        return None
    previous = bytearray(stride)
    output = bytearray()
    changed = False
    cursor = 0
    for _row in range(height):
        filter_type = raw[cursor]
        current = bytearray(raw[cursor + 1 : cursor + 1 + stride])
        cursor += stride + 1
        if not _unfilter_rgba_row(current, previous, filter_type):
            return None
        for index in range(0, stride, 4):
            if current[index + 3] == 0 and any(current[index : index + 3]):
                current[index : index + 3] = b"\0\0\0"
                changed = True
        output.append(0)
        output.extend(current)
        previous = current
    return bytes(output), changed


def _unfilter_rgba_row(current: bytearray, previous: bytearray, filter_type: int) -> bool:
    for index in range(len(current)):
        left = current[index - 4] if index >= 4 else 0
        up = previous[index]
        upper_left = previous[index - 4] if index >= 4 else 0
        if filter_type == 1:
            current[index] = (current[index] + left) & 0xFF
        elif filter_type == 2:
            current[index] = (current[index] + up) & 0xFF
        elif filter_type == 3:
            current[index] = (current[index] + ((left + up) // 2)) & 0xFF
        elif filter_type == 4:
            predictor = left + up - upper_left
            values = (left, up, upper_left)
            distances = tuple(abs(predictor - value) for value in values)
            current[index] = (current[index] + values[distances.index(min(distances))]) & 0xFF
        elif filter_type != 0:
            return False
    return True


__all__ = [
    "image_dimensions",
    "normalize_png_transparent_pixels",
    "png_has_invalid_transparent_pixels",
    "png_transparent_pixel_status",
]
