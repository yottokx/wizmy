"""
キャラクターカードコンポーネント。
"""

from __future__ import annotations

from typing import Callable

from nicegui import app, ui

from ...app_context import get_context
from ...core.character.schemas import CharacterImageAsset, CharacterSheet

_TEXT_WRAP_CLASSES = "min-w-0 max-w-full whitespace-normal break-words"
_TEXT_WRAP_STYLE = "white-space: normal; overflow-wrap: anywhere; word-break: break-word;"


def character_card(
    sheet: CharacterSheet,
    on_click: Callable | None = None,
    on_delete: Callable | None = None,
    on_toggle_favorite: Callable | None = None,
) -> None:
    """キャラクター一覧用カード。"""
    with ui.card().classes(
        "cursor-pointer w-full overflow-hidden transition-all"
    ).on("click", lambda: on_click(sheet.id) if on_click else None):
        with ui.card_section().classes("min-w-0 overflow-hidden pb-2"):
            with ui.row().classes("items-start gap-3 mb-2 min-w-0 flex-nowrap"):
                _avatar(sheet)
                with ui.column().classes("gap-0 min-w-0 flex-1 overflow-hidden").style(
                    "min-width: 0; max-width: 100%;"
                ):
                    _wrap_label(sheet.name, "text-sm font-bold leading-snug")
                    if sheet.world:
                        _wrap_label(
                            sheet.world[:55] + "..." if len(sheet.world) > 55 else sheet.world,
                            "text-xs leading-snug mt-0.5",
                            extra_style="color: #8A8880;",
                        )
                with ui.row().classes("gap-1 shrink-0"):
                    if on_toggle_favorite:
                        favorite_icon = "star" if sheet.is_favorite else "star_border"
                        favorite_color = "#D9A441" if sheet.is_favorite else "#AAA8A0"
                        favorite_tip = "お気に入りを解除" if sheet.is_favorite else "お気に入りに追加"
                        ui.button(icon=favorite_icon).props(
                            "flat round dense size=sm"
                        ).style(f"color: {favorite_color};").on(
                            "click.stop", on_toggle_favorite
                        ).tooltip(favorite_tip)
                    if on_delete:
                        ui.button(icon="delete_outline").props(
                            "flat round dense size=xs color=negative"
                        ).on("click.stop", on_delete).tooltip("削除")

            with ui.row().classes("gap-x-3 gap-y-1 flex-wrap min-w-0").style("font-size: 0.78rem; color: #8A8880;"):
                if sheet.age:
                    with ui.row().classes("items-start gap-1 min-w-0 max-w-full flex-nowrap"):
                        ui.icon("cake").classes("text-xs shrink-0 mt-0.5")
                        _wrap_label(sheet.age)
                if sheet.gender:
                    _wrap_label(sheet.gender)
                if sheet.occupation:
                    with ui.row().classes("items-start gap-1 min-w-0 max-w-full w-full flex-nowrap"):
                        ui.icon("work").classes("text-xs shrink-0 mt-0.5")
                        _wrap_label(sheet.occupation)

            if sheet.tags:
                with ui.row().classes("gap-1 mt-2 flex-wrap min-w-0"):
                    for tag in sheet.tags[:4]:
                        ui.badge(tag).props("outline color=primary").classes(
                            f"text-xs {_TEXT_WRAP_CLASSES}"
                        ).style(_TEXT_WRAP_STYLE)

        with ui.card_section().classes("pt-0 pb-2"):
            ui.label(
                sheet.updated_at.strftime("%Y/%m/%d %H:%M") if sheet.updated_at else ""
            ).classes("text-xs").style("color: #C0BCB4;")


def _wrap_label(text: str, classes: str = "", extra_style: str = "") -> None:
    el = ui.label(text).classes(f"{classes} {_TEXT_WRAP_CLASSES}".strip()).style(_TEXT_WRAP_STYLE)
    if extra_style:
        el.style(extra_style)


def _avatar(sheet: CharacterSheet) -> None:
    image = sheet.media.primary_image()
    style = _face_avatar_style(image) if image else ""
    if style:
        ui.element("div").classes(
            "w-11 h-11 rounded-full shrink-0"
        ).style(f"border: 1px solid #E4E0D8; {style}")
        return

    with ui.element("div").classes(
        "w-11 h-11 rounded-full shrink-0 flex items-center justify-center"
    ).style("background: #EEF4EF; border: 1px solid #C0D8C4;"):
        ui.icon("person").style("color: #6E9572; font-size: 1.25rem;")


def _face_avatar_style(image: CharacterImageAsset | None) -> str:
    if image is None:
        return ""
    image_path = get_context().characters.media_path(image.path)
    if image_path is None:
        return ""

    url = app.add_static_file(local_file=image_path, max_cache_age=0).replace('"', "%22")
    rect = image.face_rect

    if image.width > 0 and image.height > 0:
        aspect = image.width / image.height
        scale = max(1.0 / max(rect.width, 0.01), aspect / max(rect.height, 0.01))
    else:
        aspect = 1.0
        scale = 1.0 / max(min(rect.width, rect.height), 0.01)
    scale = min(max(scale * 1.08, 1.0), 8.0)
    rendered_width = scale
    rendered_height = scale / max(aspect, 0.01)
    position_x = _background_position(rect.x + rect.width / 2, rendered_width)
    position_y = _background_position(rect.y + rect.height / 2, rendered_height)

    return (
        f'background-image: url("{url}"); '
        "background-color: #EEF4EF; "
        f"background-size: {scale * 100:.1f}% auto; "
        f"background-position: {position_x:.1f}% {position_y:.1f}%; "
        "background-repeat: no-repeat;"
    )


def _background_position(center: float, rendered_size: float) -> float:
    if rendered_size <= 1.0001:
        return 50.0
    position = (0.5 - center * rendered_size) / (1.0 - rendered_size) * 100
    return min(max(position, 0.0), 100.0)
