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
    on_chat: Callable | None = None,
    on_delete: Callable | None = None,
    on_toggle_favorite: Callable | None = None,
) -> None:
    """キャラクター一覧用カード。"""
    with (
        ui.card()
        .classes("cursor-pointer w-full h-full overflow-hidden transition-all flex flex-col")
        .style("min-height: 320px; border-radius: 12px;")
        .on("click", lambda: on_click(sheet.id) if on_click else None)
    ):
        with ui.card_section().classes("min-w-0 overflow-hidden pb-0 flex-1 flex flex-col"):
            with ui.row().classes("items-start gap-3 mb-3 min-w-0 flex-nowrap"):
                _avatar(sheet)
                with (
                    ui.column()
                    .classes("gap-0.5 min-w-0 flex-1 overflow-hidden")
                    .style("min-width: 0; max-width: 100%;")
                ):
                    _wrap_label(
                        sheet.name,
                        "text-base font-bold leading-snug",
                        extra_style=_line_clamp_style(3),
                    )
                    if sheet.origin:
                        _wrap_label(
                            sheet.origin,
                            "text-xs leading-snug",
                            extra_style=f"color: var(--cs-muted); {_line_clamp_style(2)}",
                        )
                with ui.row().classes("gap-1 shrink-0"):
                    if on_toggle_favorite:
                        favorite_icon = "star" if sheet.is_favorite else "star_border"
                        favorite_color = "#D9A441" if sheet.is_favorite else "var(--cs-muted)"
                        favorite_tip = "お気に入りを解除" if sheet.is_favorite else "お気に入りに追加"
                        ui.button(icon=favorite_icon).props("flat round dense size=sm").style(
                            f"color: {favorite_color};"
                        ).on("click.stop", on_toggle_favorite).tooltip(favorite_tip)
                    if on_delete:
                        ui.button(icon="delete_outline").props("flat round dense size=sm color=negative").on(
                            "click.stop", on_delete
                        ).tooltip("削除")

            summary = _summary_text(sheet)
            if summary:
                _wrap_label(
                    summary,
                    "text-sm leading-relaxed mb-3",
                    extra_style=f"color: var(--cs-muted); {_line_clamp_style(4)}",
                )

            if sheet.tags:
                with ui.row().classes("gap-1 mb-3 flex-wrap min-w-0"):
                    for tag in sheet.tags[:3]:
                        ui.badge(tag).props("outline color=primary").classes(
                            f"text-xs px-2 py-1 {_TEXT_WRAP_CLASSES}"
                        ).style(_TEXT_WRAP_STYLE)

            ui.separator().classes("mb-3")

            with ui.column().classes("gap-2 min-w-0 mb-3"):
                if sheet.age or sheet.gender:
                    with ui.element("div").classes("grid grid-cols-2 gap-2 w-full"):
                        if sheet.age:
                            _info_item("person_outline", "年齢", sheet.age, "var(--cs-accent)")
                        if sheet.gender:
                            _info_item(_gender_icon(sheet.gender), "性別", sheet.gender, "var(--cs-negative)")
                if sheet.occupation:
                    _info_item("work_outline", "職業", sheet.occupation, "var(--cs-accent)")

            ui.space()
            ui.separator().classes("mb-3")

        with ui.card_section().classes("pt-0 pb-4"):
            with ui.row().classes("items-center gap-3 flex-nowrap"):
                with ui.row().classes("items-center gap-2 min-w-0 flex-1 flex-nowrap"):
                    ui.icon("schedule").classes("shrink-0").style("color: var(--cs-muted); font-size: 1.1rem;")
                    ui.label(sheet.updated_at.strftime("%Y/%m/%d %H:%M") if sheet.updated_at else "").classes(
                        "text-xs min-w-0 whitespace-nowrap"
                    ).style("color: var(--cs-muted);")
                if on_chat:
                    ui.button("チャット", icon="chat_bubble").props("unelevated color=primary size=sm").classes(
                        "shrink-0 px-4"
                    ).style("border-radius: 8px; font-weight: 700;").on(
                        "click.stop", lambda: on_chat(sheet.id)
                    ).tooltip("このキャラクターとチャットする")


def _wrap_label(text: str, classes: str = "", extra_style: str = "") -> None:
    el = ui.label(text).classes(f"{classes} {_TEXT_WRAP_CLASSES}".strip()).style(_TEXT_WRAP_STYLE)
    if extra_style:
        el.style(extra_style)


def _line_clamp_style(lines: int) -> str:
    return f"display: -webkit-box; -webkit-line-clamp: {lines}; -webkit-box-orient: vertical; overflow: hidden;"


def _summary_text(sheet: CharacterSheet) -> str:
    for value in (sheet.world, sheet.self_intro, sheet.background, sheet.personality):
        text = " ".join(str(value or "").split())
        if text:
            return _truncate_text(text, 110)
    return ""


def _truncate_text(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    return f"{text[:max_length].rstrip()}..."


def _gender_icon(gender: str) -> str:
    if "女" in gender:
        return "female"
    if "男" in gender:
        return "male"
    return "wc"


def _info_item(icon: str, label: str, value: str, color: str) -> None:
    with ui.row().classes("items-center gap-2 min-w-0 flex-nowrap"):
        with (
            ui.element("div")
            .classes("w-7 h-7 rounded-md shrink-0 flex items-center justify-center")
            .style("background: var(--cs-surface-soft); border: 1px solid var(--cs-border);")
        ):
            ui.icon(icon).style(f"color: {color}; font-size: 1rem;")
        with ui.row().classes("items-baseline gap-2 min-w-0 flex-nowrap"):
            ui.label(label).classes("text-xs shrink-0").style("color: var(--cs-muted);")
            _wrap_label(
                value,
                "text-sm font-bold leading-snug",
                extra_style=_line_clamp_style(2),
            )


def _avatar(sheet: CharacterSheet) -> None:
    image = sheet.media.primary_image()
    style = _face_avatar_style(image) if image else ""
    if style:
        ui.element("div").classes("w-16 h-16 rounded-full shrink-0").style(
            f"border: 2px solid var(--cs-border); {style}"
        )
        return

    with (
        ui.element("div")
        .classes("w-16 h-16 rounded-full shrink-0 flex items-center justify-center")
        .style("background: var(--cs-accent-bg); border: 2px solid var(--cs-accent-border);")
    ):
        ui.icon("person").style("color: var(--cs-accent); font-size: 1.65rem;")


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
