"""グループチャット UI の共有ヘルパー。"""

from __future__ import annotations

import re

from nicegui import ui

from ...services.llm_runtime import (
    API_KEY_LOCKED,
    ENDPOINT_NOT_FOUND,
    MODEL_ID_MISSING,
    PROFILE_NOT_FOUND,
    LLMRuntimeError,
)

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
    return ctx.user_personas.get_user_persona(persona_id) if persona_id else None


def group_user_persona_tts_id(persona_id: str) -> str:
    return f"user-persona-{persona_id}"


def group_member_tts_id(group_id: str, member_id: str) -> str:
    return f"group-{group_id}-member-{member_id}"
