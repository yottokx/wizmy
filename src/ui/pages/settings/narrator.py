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
from ....core.tts.schemas import TTS_PROVIDER_IRODORI_SERVER
from ...components.character_media import CharacterMediaActions
from ...components.character_media_voice import _open_voice_design_dialog, _render_tts_controls
from .user_personas import (
    persona_assigned_gen_server_voice_endpoints,
    persona_is_gen_server_voice_api,
    persona_parse_voice_api_value,
    persona_selected_tts_endpoint,
    persona_selected_voice_api_value,
    persona_voice_api_options,
)


def narrator_voice_text() -> str:
    return "夜の空気が静かに流れ、物語は次の場面へ進んだ。"


def narrator_media_target(ctx):
    config = ctx.user_personas.get_tts_config()
    voice = config.narrator_voice
    return SimpleNamespace(
        id=narrator_tts_id(),
        name="ナレーター",
        media=CharacterMedia(
            voices=[voice] if voice else [],
            primary_voice_id=voice.id if voice else "",
            tts=config.narrator,
        ),
    )


def narrator_media_actions(ctx) -> CharacterMediaActions:
    async def _update_tts_settings(settings: CharacterTTSSettings):
        config = ctx.user_personas.get_tts_config()
        config.narrator = settings
        ctx.user_personas.save_tts_config(config)
        return narrator_media_target(ctx)

    async def _save_voice_design_result(item: dict[str, object], index: int):
        audio = item.get("audio")
        if not audio:
            return narrator_media_target(ctx)
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
        return narrator_media_target(ctx)

    return CharacterMediaActions(
        target_id=narrator_tts_id(),
        tts_id=narrator_tts_id(),
        result_url="/settings",
        scope_prefix="narrator",
        metadata={"target": "narrator"},
        media_path=ctx.user_personas.media_path,
        update_tts_settings=_update_tts_settings,
        save_tts_preview=lambda audio_bytes, **kwargs: ctx.user_personas.save_narrator_tts_preview(
            audio_bytes,
            **kwargs,
        ),
        save_tts_playback=lambda audio_bytes: ctx.user_personas.save_narrator_tts_playback(audio_bytes),
        voice_design_title="ナレーターのボイスデザイン",
        voice_design_text_label="読み上げる例文",
        voice_design_text_value=lambda _: narrator_voice_text(),
        voice_design_text_placeholder="生成する音声で読み上げる例文",
        voice_design_empty_text_message="読み上げる例文を入力してください。",
        voice_design_caption_placeholder="落ち着いた低めの声。穏やかで、情景を丁寧に語る。",
        voice_design_reference_label="現在のナレーター音声を参照音声として使う",
        voice_design_job_label=lambda _: "ナレーターボイスデザイン",
        voice_design_generated_message="ナレーター音声を生成しました",
        voice_design_save_message="ナレーター音声を保存し、Voice Cloneに切り替えました",
        voice_design_save_result=_save_voice_design_result,
        voice_caption_generation_enabled=False,
        tts_no_api_message="利用できるTTS APIがありません。TTS APIまたはVoiceDesign用のWizmy-Gen-Serverを設定してください。",
        tts_text_value=lambda _: narrator_voice_text(),
        tts_text_rows=3,
        tts_text_placeholder="地の文として読み上げるテキスト",
        tts_caption_label="VoiceDesign caption",
        tts_caption_placeholder="落ち着いた低めの声。穏やかで、情景を丁寧に語る。",
        tts_caption_generation_enabled=False,
        tts_default_voice_id=lambda _: narrator_tts_id(),
        tts_fill_default_voice_id=True,
        tts_show_default_voice_id_label=False,
        tts_show_irodori_controls=False,
        tts_show_separator=False,
        tts_save_message="ナレーターTTS設定を保存しました",
        tts_synthesis_label=lambda _: "ナレーター読み上げ",
        tts_ready=lambda settings: narrator_tts_ready(ctx, settings),
        tts_not_ready_message="ナレーターTTS設定を確認してください",
        tts_error_timeout=10000,
        gen_server_model_settings_style=True,
        voice_api_options=narrator_voice_api_options,
        selected_voice_api_value=persona_selected_voice_api_value,
        parse_voice_api_value=persona_parse_voice_api_value,
        selected_tts_endpoint=persona_selected_tts_endpoint,
        is_gen_server_voice_api=persona_is_gen_server_voice_api,
        assigned_gen_server_voice_endpoints=persona_assigned_gen_server_voice_endpoints,
    )


def open_narrator_voice_design_dialog(ctx, refresh_fn) -> None:
    _open_voice_design_dialog(
        narrator_media_target(ctx),
        ctx,
        narrator_tts_id(),
        refresh_fn,
        narrator_media_actions(ctx),
    )


def narrator_tts_id() -> str:
    return "narrator"


def narrator_voice_api_options(endpoints, gen_server_config) -> dict[str, str]:
    return persona_voice_api_options(endpoints, gen_server_config)


def narrator_has_gen_server_voice_design(gen_server_config) -> bool:
    return bool(persona_assigned_gen_server_voice_endpoints(gen_server_config))


def narrator_tts_ready(ctx, settings: CharacterTTSSettings) -> bool:
    config = ctx.user_personas.get_tts_config()
    voice_path = ctx.user_personas.media_path(config.narrator_voice.path) if config.narrator_voice is not None else None
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


def render_narrator_tts_settings(ctx, refresh_fn) -> None:
    endpoints = ctx.tts.get_endpoints()
    gen_server_config = ctx.api_config.get_gen_server_config()
    has_gen_server = narrator_has_gen_server_voice_design(gen_server_config)
    tts_config = ctx.user_personas.get_tts_config()
    current_settings = tts_config.narrator
    narrator_voice = tts_config.narrator_voice
    narrator_voice_path = ctx.user_personas.media_path(narrator_voice.path) if narrator_voice else None

    with ui.card().classes("w-full mb-4"):
        with ui.card_section():
            with ui.row().classes("w-full items-center gap-2"):
                ui.icon("record_voice_over").classes("text-primary")
                ui.label("ナレーター").classes("text-base font-semibold")
                ui.space()
                ready_label = "有効" if narrator_tts_ready(ctx, current_settings) else "未設定"
                ready_color = "positive" if ready_label == "有効" else "grey"
                ui.badge(ready_label).props(f"color={ready_color}")
            ui.label("地の文の読み上げに使う声を設定します。").classes("text-sm text-grey-6")

        with ui.card_section().classes("pt-0"):
            if not endpoints and not has_gen_server:
                ui.label(
                    "利用できるTTS APIがありません。TTS APIまたはVoiceDesign用のWizmy-Gen-Serverを設定してください。"
                ).classes("text-sm text-grey-6")
                return

            with ui.row().classes("w-full items-center gap-2"):
                ui.button(
                    "VoiceDesignでサンプル作成",
                    icon="auto_awesome",
                    on_click=lambda: open_narrator_voice_design_dialog(ctx, refresh_fn),
                ).props("outline color=primary")
                if narrator_voice_path is not None:
                    ui.label(narrator_voice.original_name or "ナレーター音声").classes("text-sm text-grey-6")
            if narrator_voice_path is not None:
                ui.audio(narrator_voice_path).classes("w-full")

            _render_tts_controls(
                narrator_media_target(ctx),
                ctx,
                narrator_tts_id(),
                narrator_voice,
                narrator_voice_path,
                refresh_fn,
                narrator_media_actions(ctx),
            )
