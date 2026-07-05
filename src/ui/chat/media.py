"""Image crop helpers for character chat."""

from __future__ import annotations

from pathlib import Path

from nicegui import app

from ...core.character.schemas import CharacterImageAsset, FaceRect
from ...core.media import read_image_size


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
