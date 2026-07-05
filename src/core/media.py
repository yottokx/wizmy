"""画像メディアの軽量なヘッダー解析。"""

from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

_JPEG_SIZE_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def read_image_size(path: Path) -> tuple[int, int] | None:
    """画像ファイルのヘッダーから幅と高さを取得する。"""
    try:
        with path.open("rb") as f:
            head = f.read(32)
            if head.startswith(b"\x89PNG\r\n\x1a\n") and len(head) >= 24:
                return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
            if head[:6] in (b"GIF87a", b"GIF89a") and len(head) >= 10:
                return int.from_bytes(head[6:8], "little"), int.from_bytes(head[8:10], "little")
            if head.startswith(b"\xff\xd8"):
                f.seek(2)
                return _read_jpeg_size(f)
            if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
                f.seek(12)
                return _read_webp_size(f)
    except OSError:
        return None
    return None


def _read_jpeg_size(f: BinaryIO) -> tuple[int, int] | None:
    while True:
        marker_start = f.read(1)
        if not marker_start:
            return None
        if marker_start != b"\xff":
            continue
        marker = f.read(1)
        while marker == b"\xff":
            marker = f.read(1)
        if not marker or marker in (b"\xd8", b"\xd9"):
            continue
        length_bytes = f.read(2)
        if len(length_bytes) != 2:
            return None
        length = int.from_bytes(length_bytes, "big")
        if length < 2:
            return None
        if marker[0] in _JPEG_SIZE_MARKERS:
            data = f.read(5)
            if len(data) != 5:
                return None
            return int.from_bytes(data[3:5], "big"), int.from_bytes(data[1:3], "big")
        f.seek(length - 2, 1)


def _read_webp_size(f: BinaryIO) -> tuple[int, int] | None:
    while True:
        chunk_header = f.read(8)
        if len(chunk_header) != 8:
            return None
        chunk_type = chunk_header[:4]
        chunk_size = int.from_bytes(chunk_header[4:8], "little")
        if chunk_type == b"VP8X":
            data = f.read(min(chunk_size, 10))
            if len(data) != 10:
                return None
            width = int.from_bytes(data[4:7], "little") + 1
            height = int.from_bytes(data[7:10], "little") + 1
            return width, height
        if chunk_type == b"VP8L":
            data = f.read(min(chunk_size, 5))
            if len(data) != 5 or data[0] != 0x2F:
                return None
            bits = int.from_bytes(data[1:5], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if chunk_type == b"VP8 ":
            data = f.read(min(chunk_size, 10))
            if len(data) != 10 or data[3:6] != b"\x9d\x01\x2a":
                return None
            width = int.from_bytes(data[6:8], "little") & 0x3FFF
            height = int.from_bytes(data[8:10], "little") & 0x3FFF
            return width, height
        f.seek(chunk_size + chunk_size % 2, 1)
