"""Image crop helpers for character chat."""

from __future__ import annotations

from pathlib import Path

from nicegui import app

from ...core.character.schemas import CharacterImageAsset, FaceRect


def cropped_background_style(
    image: CharacterImageAsset | None,
    image_path: Path | None,
    rect: FaceRect,
    frame_aspect: float,
) -> str:
    if image is None or image_path is None:
        return ""

    url = app.add_static_file(local_file=image_path, max_cache_age=0).replace('"', "%22")
    image_width, image_height = image_dimensions(image, image_path)
    image_aspect = image_width / image_height if image_width > 0 and image_height > 0 else 1.0
    scale = max(
        1.0 / max(rect.width, 0.01),
        image_aspect / max(rect.height * frame_aspect, 0.01),
    )
    scale = min(max(scale * 1.04, 1.0), 8.0)
    rendered_width = scale
    rendered_height = scale * frame_aspect / max(image_aspect, 0.01)
    position_x = background_position(rect.x + rect.width / 2, rendered_width)
    position_y = background_position(rect.y + rect.height / 2, rendered_height)

    return (
        f'background-image: url("{url}"); '
        f"background-size: {scale * 100:.1f}% auto; "
        f"background-position: {position_x:.1f}% {position_y:.1f}%; "
        "background-repeat: no-repeat; background-color: var(--cs-surface-soft);"
    )


def background_position(center: float, rendered_size: float) -> float:
    if rendered_size <= 1.0001:
        return 50.0
    position = (0.5 - center * rendered_size) / (1.0 - rendered_size) * 100
    return min(max(position, 0.0), 100.0)


def image_dimensions(image: CharacterImageAsset, image_path: Path) -> tuple[int, int]:
    if image.width > 0 and image.height > 0:
        return image.width, image.height
    size = read_image_size(image_path)
    if size is not None:
        return size
    return 1, 1


def read_image_size(path: Path) -> tuple[int, int] | None:
    try:
        with path.open("rb") as f:
            head = f.read(32)
            if head.startswith(b"\x89PNG\r\n\x1a\n") and len(head) >= 24:
                return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
            if head[:6] in (b"GIF87a", b"GIF89a") and len(head) >= 10:
                return int.from_bytes(head[6:8], "little"), int.from_bytes(head[8:10], "little")
            if head.startswith(b"\xff\xd8"):
                f.seek(2)
                return read_jpeg_size(f)
    except OSError:
        return None
    return None


def read_jpeg_size(f) -> tuple[int, int] | None:
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
        if marker[0] in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            data = f.read(5)
            if len(data) != 5:
                return None
            return int.from_bytes(data[3:5], "big"), int.from_bytes(data[1:3], "big")
        f.seek(max(length - 2, 0), 1)

