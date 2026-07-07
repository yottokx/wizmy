"""
/v2/settings — ナレーター(地の文の読み上げに使う声)。

旧 `ui/pages/settings/narrator.py` の機能を P3 スキンで再実装。
ボイスデザイン/TTS設定は `media_ui.py` の共有レンダラを使う。
"""

from __future__ import annotations

from types import SimpleNamespace

from nicegui import ui

from ....core.character.schemas import (
    CHARACTER_GEN_SERVER_TTS_MODE_CLONE,
    CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3,
    CHARACTER_TTS_API_GEN_SERVER,
    CHARACTER_TTS_API_TTS,
    CharacterMedia,
    CharacterTTSSettings,
)
from ....core.gen_server.schemas import (
    GEN_SERVER_MODE_IRODORI_VOICE_CLONE,
    clean_gen_server_mode_defaults,
)
from ....core.tts.options import PERSONA_GEN_SERVER_VOICE_API_VALUE
from ....core.tts.schemas import TTS_PROVIDER_IRODORI_SERVER
from ...components.portrait import media_url as portrait_media_url
from ...media_ui import MediaTarget, render_tts_settings, render_voice_design, render_voice_now
from .common import settings_dialog

_NARRATOR_TTS_ID = "narrator"


def narrator_voice_text() -> str:
    return "夜の空気が静かに流れ、物語は次の場面へ進んだ。"


def _narrator_sheet(ctx):
    config = ctx.user_personas.get_tts_config()
    voice = config.narrator_voice
    return SimpleNamespace(
        id=_NARRATOR_TTS_ID,
        name="ナレーター",
        media=CharacterMedia(
            voices=[voice] if voice else [],
            primary_voice_id=voice.id if voice else "",
            tts=config.narrator,
        ),
    )


def narrator_tts_ready(ctx, settings: CharacterTTSSettings) -> bool:
    config = ctx.user_personas.get_tts_config()
    voice_path = (
        ctx.user_personas.media_path(config.narrator_voice.path) if config.narrator_voice is not None else None
    )
    if settings.api_type == CHARACTER_TTS_API_GEN_SERVER:
        if settings.gen_server_tts_mode == CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3:
            return bool(
                settings.voice_caption.strip()
                and ctx.tts.resolve_gen_server_voice_design_endpoint(raise_on_missing=False) is not None
            )
        return bool(
            voice_path is not None
            and ctx.tts.resolve_gen_server_voice_clone_endpoint(raise_on_missing=False) is not None
        )
    if settings.api_type != CHARACTER_TTS_API_TTS:
        return False
    endpoint = ctx.api_config.get_tts_endpoint(settings.endpoint_id)
    if endpoint is None:
        return False
    if endpoint.provider == TTS_PROVIDER_IRODORI_SERVER:
        return bool(settings.voice_id.strip())
    return voice_path is not None


def _narrator_media_target(ctx, state: dict) -> MediaTarget:
    def _sheet():
        return state["sheet"]

    def _apply(saved) -> None:
        state["sheet"] = _narrator_sheet(ctx)

    async def _update_tts_settings(settings: CharacterTTSSettings):
        config = ctx.user_personas.get_tts_config()
        config.narrator = settings
        ctx.user_personas.save_tts_config(config)
        return _narrator_sheet(ctx)

    async def _save_voice_design_result(item: dict[str, object], index: int):
        audio = item.get("audio")
        if not audio:
            return _narrator_sheet(ctx)
        await ctx.user_personas.save_narrator_voice_bytes(
            audio,
            filename=f"narrator-voice-design-{index}.wav",
            content_type="audio/wav",
        )
        config = ctx.user_personas.get_tts_config()
        config.narrator = config.narrator.model_copy(
            update={
                "api_type": CHARACTER_TTS_API_GEN_SERVER,
                "gen_server_tts_mode": CHARACTER_GEN_SERVER_TTS_MODE_CLONE,
                "voice_caption": str(item.get("caption") or "").strip(),
                "gen_server_params": clean_gen_server_mode_defaults(
                    GEN_SERVER_MODE_IRODORI_VOICE_CLONE,
                    config.narrator.gen_server_params,
                ),
            }
        )
        ctx.user_personas.save_tts_config(config)
        return _narrator_sheet(ctx)

    return MediaTarget(
        name="ナレーター",
        tts_id=_NARRATOR_TTS_ID,
        result_url="/v2/settings",
        scope_prefix="narrator",
        metadata={"target": "narrator"},
        sheet=_sheet,
        apply_saved=_apply,
        media_path=ctx.user_personas.media_path,
        media_url=portrait_media_url,
        update_tts_settings=_update_tts_settings,
        save_tts_preview=lambda audio_bytes, **kwargs: ctx.user_personas.save_narrator_tts_preview(
            audio_bytes, **kwargs
        ),
        gen_server_voice_api_value=PERSONA_GEN_SERVER_VOICE_API_VALUE,
        caption_generation_enabled=False,
        voice_design_text_label="読み上げる例文",
        voice_design_text=lambda _: narrator_voice_text(),
        voice_design_caption_placeholder="落ち着いた低めの声。穏やかで、情景を丁寧に語る。",
        voice_design_reference_label="現在のナレーター音声を参照音声として使う",
        voice_design_save_result=_save_voice_design_result,
        voice_design_save_message="ナレーター音声を保存し、ボイスクローンに切り替えました",
        tts_text=lambda _: narrator_voice_text(),
        default_voice_id=lambda _: _NARRATOR_TTS_ID,
        fill_default_voice_id=True,
        show_irodori_controls=False,
        tts_save_message="ナレーターTTS設定を保存しました",
        job_label_prefix="ナレーター",
    )


def open_narrator_dialog(ctx, on_change) -> None:
    state = {"sheet": _narrator_sheet(ctx)}
    target = _narrator_media_target(ctx, state)
    dlg, body = settings_dialog("ナレーター", max_width="1000px")
    with body:
        ui.label("地の文の読み上げに使う声を設定します。").classes("note")
        container = ui.column().classes("w-full gap-2")

    def _refresh() -> None:
        state["sheet"] = _narrator_sheet(ctx)
        container.clear()
        with container:
            with ui.element("div").classes("state-lbl"):
                ui.html("音声")
            render_voice_now(ctx, target, _refresh)
            with ui.element("div").classes("state-lbl"):
                ui.html("ボイスデザイン")
            render_voice_design(ctx, target, _refresh)
            with ui.element("div").classes("state-lbl"):
                ui.html("TTS設定")
            render_tts_settings(ctx, target, _refresh)
        on_change()

    _refresh()
    dlg.open()


def narrator_summary(ctx) -> tuple[str, str]:
    settings = ctx.user_personas.get_tts_config().narrator
    if narrator_tts_ready(ctx, settings):
        return "有効", "ok"
    return "未設定", "muted"
