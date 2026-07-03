"""グループチャット UI の共有ヘルパー。"""

from __future__ import annotations

import re
from typing import Any

from nicegui import ui

from ...core.character.schemas import CharacterMedia
from ...core.group_chat.schemas import GroupUserPersona
from ...services.llm_runtime import (
    API_KEY_LOCKED,
    ENDPOINT_NOT_FOUND,
    LLMRuntimeError,
    MODEL_ID_MISSING,
    PROFILE_NOT_FOUND,
)
from ..chat.media import cropped_background_style


HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{3,12}$")


def notify_on_client(page_client, message: str, **kwargs) -> None:
    try:
        if page_client is not None and not getattr(page_client, "_deleted", False):
            with page_client:
                ui.notify(message, **kwargs)
        else:
            ui.notify(message, **kwargs)
    except RuntimeError:
        return


def notify_setup_llm_runtime_error(err: LLMRuntimeError) -> None:
    if err.kind == PROFILE_NOT_FOUND:
        ui.notify("補完用LLMプロファイルを選択してください", type="warning")
    elif err.kind == MODEL_ID_MISSING:
        ui.notify("補完用LLMプロファイルのモデルIDが未設定です", type="negative")
    elif err.kind == ENDPOINT_NOT_FOUND:
        ui.notify("補完用LLMプロファイルのエンドポイントが見つかりません", type="negative")
    elif err.kind == API_KEY_LOCKED:
        ui.notify("APIキーボルトをロック解除してください", type="warning", timeout=8000)


def notify_group_chat_llm_runtime_error(err: LLMRuntimeError) -> None:
    if err.kind == PROFILE_NOT_FOUND:
        ui.notify("LLMプロファイルを選択してください", type="warning")
    elif err.kind == MODEL_ID_MISSING:
        ui.notify("LLMプロファイルのモデルIDが未設定です", type="negative")
    elif err.kind == ENDPOINT_NOT_FOUND:
        ui.notify("LLMプロファイルのエンドポイントが見つかりません", type="negative")
    elif err.kind == API_KEY_LOCKED:
        ui.notify("APIキーがロックされています。設定画面で解除してください。", type="warning")


def render_participant_face(ctx, participant: dict[str, Any], *, large: bool = False) -> None:
    classes = "cs-group-face"
    if large:
        classes += " cs-group-face-large"
    style = participant_media_style(ctx, participant, rect_kind="face")
    with ui.element("div").classes(classes).style(style):
        if not style:
            ui.icon("person").classes("text-sm")


def render_group_user_menu_face(ctx, persona: GroupUserPersona | None) -> None:
    if persona is None:
        with ui.element("div").classes("cs-group-face"):
            ui.icon("person").classes("text-sm")
        return
    participant = {
        "kind": "user",
        "media": persona.media,
    }
    render_participant_face(ctx, participant)


def participant_media_style(ctx, participant: dict[str, Any], *, rect_kind: str) -> str:
    media = participant.get("media")
    if not isinstance(media, CharacterMedia):
        return ""
    image = media.primary_image()
    if image is None:
        return ""
    if participant.get("kind") == "user":
        image_path = ctx.api_config.media_path(image.path)
    else:
        image_path = ctx.group_chats.media_path(image.path)
    rect = image.bust_rect if rect_kind == "bust" else image.face_rect
    return cropped_background_style(image, image_path, rect, 1.0) if image_path else ""


def profile_options(ctx, profiles) -> dict[str, str]:
    endpoints = {endpoint.id: endpoint for endpoint in ctx.api_config.get_endpoints()}
    options: dict[str, str] = {}
    for profile in profiles:
        endpoint = endpoints.get(profile.endpoint_id)
        endpoint_name = endpoint.name if endpoint else "不明"
        model = profile.model_id or "未設定"
        options[profile.id] = f"{profile.name} [{endpoint_name} / {model}]"
    return options


def default_profile_id(ctx, options: dict[str, str]) -> str:
    config = ctx.api_config.get_app_llm_config()
    for profile_id in (config.chat_profile_id, config.generation_profile_id):
        if profile_id in options:
            return profile_id
    return next(iter(options), "")


def default_persona_id(options: dict[str, str]) -> str:
    return next(iter(options), "")


def selected_persona(ctx, persona_id: str):
    return ctx.api_config.get_user_persona(persona_id) if persona_id else None
