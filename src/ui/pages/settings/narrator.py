from __future__ import annotations

from nicegui import ui

from ....core.character.schemas import (
    CHARACTER_GEN_SERVER_TTS_MODE_CLONE,
    CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3,
    CHARACTER_TTS_API_GEN_SERVER,
    CHARACTER_TTS_API_TTS,
    CharacterTTSSettings,
)
from ....core.gen_server.schemas import (
    GEN_SERVER_DEFAULT_FIELDS,
    GEN_SERVER_MODE_IRODORI_VOICE_CLONE,
    GEN_SERVER_MODE_IRODORI_VOICE_DESIGN,
    clean_gen_server_mode_defaults,
)
from ....core.tts.schemas import TTS_PROVIDER_IRODORI_SERVER
from ....services.ai_jobs import AIJobStatus
from ....services.tts import TTSServiceError
from .common import TTS_PROVIDER_LABELS, build_profile_param_control, read_gen_server_default_value
from .media_generation import fetch_gen_server_model_id
from .user_personas import (
    PERSONA_GEN_SERVER_TTS_MODE_OPTIONS,
    PERSONA_GEN_SERVER_VOICE_API,
    PERSONA_TTS_API_PREFIX,
    open_user_persona_gen_server_tts_params_dialog,
    persona_assigned_gen_server_voice_endpoints,
    persona_gen_server_backend_mode,
    persona_is_gen_server_voice_api,
    persona_normalize_gen_server_tts_mode,
    persona_parse_voice_api_value,
    persona_selected_tts_endpoint,
    persona_selected_voice_api_value,
    persona_voice_api_options,
)


def narrator_voice_text() -> str:
    return "夜の空気が静かに流れ、物語は次の場面へ進んだ。"


def open_narrator_voice_design_dialog(ctx, refresh_fn) -> None:
    if ctx.tts.resolve_gen_server_voice_design_endpoint(raise_on_missing=False) is None:
        ui.notify("設定でボイスデザインにWizmy-Gen-Serverを割り当ててください。", type="warning")
        return

    mode = GEN_SERVER_MODE_IRODORI_VOICE_DESIGN
    fields = GEN_SERVER_DEFAULT_FIELDS.get(mode, {})
    defaults = ctx.api_config.get_gen_server_config().defaults_for_mode(mode)
    controls: dict[str, object] = {}
    generated: list[dict[str, object]] = []
    config = ctx.user_personas.get_tts_config()
    current_voice = config.narrator_voice
    current_voice_path = ctx.user_personas.media_path(current_voice.path) if current_voice else None

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-2xl"):
        with ui.row().classes("w-full items-center justify-between gap-2"):
            ui.label("ナレーターのボイスデザイン").classes("text-base font-semibold")
            ui.button(icon="close", on_click=dlg.close).props("flat round dense")

        text_input = (
            ui.textarea(
                label="読み上げる例文",
                value=narrator_voice_text(),
                placeholder="生成する音声で読み上げる例文",
            )
            .props("outlined rows=4")
            .classes("w-full")
        )
        caption_input = (
            ui.textarea(
                label="キャプション",
                value=config.narrator.voice_caption,
                placeholder="落ち着いた低めの声。穏やかで、情景を丁寧に語る。",
            )
            .props("outlined rows=4")
            .classes("w-full")
        )
        reference_checkbox = None
        if current_voice_path is not None:
            reference_checkbox = ui.checkbox(
                "現在のナレーター音声を参照音声として使う",
                value=True,
            ).classes("w-full")

        with ui.expansion("詳細パラメータ", icon="tune").props("dense").classes("w-full"):
            with ui.grid(columns=2).classes("w-full gap-3"):
                for key, spec in fields.items():
                    value = defaults.get(key, spec.get("default"))
                    if key == "model_id":
                        with ui.row().classes("w-full items-end gap-2"):
                            model_input = (
                                ui.input(
                                    label=str(spec.get("label", key)),
                                    value=value or "",
                                )
                                .props("outlined dense clearable")
                                .classes("flex-1")
                            )
                            ui.button(
                                icon="refresh",
                                on_click=lambda model_input=model_input: fetch_gen_server_model_id(
                                    mode,
                                    model_input,
                                    ctx,
                                ),
                            ).props("flat round").tooltip("モデルIDを取得")
                        controls[key] = model_input
                    else:
                        controls[key] = build_profile_param_control(key, spec, value)

        preview_container = ui.column().classes("w-full gap-2")
        status = ui.label("").classes("text-xs text-grey-6")

        def _read_params() -> dict[str, object]:
            return {key: read_gen_server_default_value(spec, controls[key]) for key, spec in fields.items()}

        def _render_generated() -> None:
            preview_container.clear()
            with preview_container:
                if not generated:
                    return
                ui.label("生成候補").classes("text-sm font-semibold")
                for index, item in enumerate(generated, start=1):
                    with (
                        ui.element("div")
                        .classes("w-full rounded-md border p-2")
                        .style("background: var(--cs-surface); border-color: var(--cs-border);")
                    ):
                        with ui.row().classes("w-full items-center gap-2"):
                            ui.label(f"候補 {index}").classes("text-sm font-semibold")
                            ui.space()
                            ui.button(
                                "この音声を保存",
                                icon="save",
                                on_click=lambda item=item, index=index: _save_voice(item, index),
                            ).props("outline color=primary")
                        ui.audio(item["path"]).classes("w-full")

        async def _generate() -> None:
            text = (text_input.value or "").strip()
            caption = (caption_input.value or "").strip()
            if not text:
                ui.notify("読み上げる例文を入力してください。", type="warning")
                return
            if not caption:
                ui.notify("キャプションを入力してください。", type="warning")
                return
            generate_btn.disable()
            status.set_text("生成中...")
            try:
                params = _read_params()

                def _save_preview(audio: bytes, job) -> dict[str, str]:
                    preview_path = ctx.user_personas.save_narrator_tts_preview(
                        audio,
                        replace_existing=False,
                    )
                    generated.append(
                        {
                            "audio": audio,
                            "path": preview_path,
                            "caption": caption,
                        }
                    )
                    return {
                        "result_url": "/settings",
                        "preview_path": str(preview_path),
                    }

                job = ctx.tts.start_design_voice_job(
                    text,
                    caption,
                    voice_path=current_voice_path
                    if reference_checkbox is not None and bool(reference_checkbox.value)
                    else None,
                    filename=current_voice.original_name if current_voice else "",
                    content_type=current_voice.content_type if current_voice else "",
                    gen_server_params=params,
                    label="ナレーターボイスデザイン",
                    scope="narrator:tts",
                    metadata={"target": "narrator"},
                    result_handler=_save_preview,
                )
                finished = await ctx.ai_jobs.wait(job.id)
                if finished.status == AIJobStatus.CANCELLED:
                    status.set_text("")
                    ui.notify("ボイスデザインを停止しました", type="info")
                    return
                if finished.status != AIJobStatus.SUCCEEDED:
                    raise TTSServiceError(finished.error_message or "ボイスデザインに失敗しました。")
                _render_generated()
                status.set_text("")
                ui.notify("ナレーター音声を生成しました", type="positive")
            except TTSServiceError as err:
                status.set_text("")
                ui.notify(f"ボイスデザインに失敗しました: {err}", type="negative", timeout=10000)
            except Exception as err:
                status.set_text("")
                ui.notify(f"ボイスデザインに失敗しました: {err}", type="negative", timeout=10000)
            finally:
                generate_btn.enable()

        async def _save_voice(item: dict[str, object], index: int) -> None:
            audio = item.get("audio")
            if not audio:
                ui.notify("先に音声を生成してください。", type="warning")
                return
            try:
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
                ui.notify("ナレーター音声を保存し、Voice Cloneに切り替えました", type="positive")
                dlg.close()
                refresh_fn()
            except Exception as err:
                ui.notify(f"音声の保存に失敗しました: {err}", type="negative")

        with ui.row().classes("justify-end gap-2 mt-3"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            generate_btn = ui.button("生成", icon="auto_awesome", on_click=_generate).props("color=primary unelevated")

    dlg.open()


def narrator_tts_id() -> str:
    return "narrator"


def narrator_voice_api_options(endpoints, gen_server_config) -> dict[str, str]:
    return persona_voice_api_options(endpoints, gen_server_config)

    options: dict[str, str] = {}
    assigned_id = gen_server_config.assigned_endpoint_id(GEN_SERVER_MODE_IRODORI_VOICE_DESIGN)
    assigned_endpoint = next(
        (endpoint for endpoint in gen_server_config.endpoints if endpoint.id == assigned_id),
        None,
    )
    if assigned_endpoint is not None:
        name_label = assigned_endpoint.name or "割り当て済み"
        options[PERSONA_GEN_SERVER_VOICE_API] = f"Wizmy-Gen-Server (VoiceDesign: {name_label})"
    options.update(
        {
            f"{PERSONA_TTS_API_PREFIX}{endpoint.id}": f"{endpoint.name} ({TTS_PROVIDER_LABELS.get(endpoint.provider, endpoint.provider)})"
            for endpoint in endpoints
        }
    )
    return options


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
    endpoint_by_id = {endpoint.id: endpoint for endpoint in endpoints}

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

            endpoint_select = (
                ui.select(
                    options=narrator_voice_api_options(endpoints, gen_server_config),
                    value=persona_selected_voice_api_value(current_settings, endpoints, has_gen_server),
                    label="使用API",
                )
                .props("outlined")
                .classes("w-full")
            )
            selected_endpoint = persona_selected_tts_endpoint(endpoint_select.value, endpoint_by_id)

            voice_id_input = None
            if selected_endpoint is not None and selected_endpoint.provider == TTS_PROVIDER_IRODORI_SERVER:
                voice_id_input = (
                    ui.input(
                        label="Voice ID",
                        value=current_settings.voice_id or narrator_tts_id(),
                        placeholder=narrator_tts_id(),
                    )
                    .props("outlined clearable")
                    .classes("w-full")
                )

            voice_caption_input = None
            mode_select = None
            gen_server_tts_mode_state = {
                "value": persona_normalize_gen_server_tts_mode(current_settings.gen_server_tts_mode)
            }
            gen_server_params_state = {
                "value": clean_gen_server_mode_defaults(
                    persona_gen_server_backend_mode(gen_server_tts_mode_state["value"]),
                    current_settings.gen_server_params,
                )
            }
            if persona_is_gen_server_voice_api(endpoint_select.value):
                mode_select = (
                    ui.select(
                        options=PERSONA_GEN_SERVER_TTS_MODE_OPTIONS,
                        value=gen_server_tts_mode_state["value"],
                        label="Gen-Server TTSモード",
                    )
                    .props("outlined")
                    .classes("w-full")
                )
                if gen_server_tts_mode_state["value"] == CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3:
                    voice_caption_input = (
                        ui.textarea(
                            label="VoiceDesign caption",
                            value=current_settings.voice_caption,
                            placeholder="落ち着いた低めの声。穏やかで、情景を丁寧に語る。",
                        )
                        .props("outlined rows=3")
                        .classes("w-full")
                    )
                ui.button(
                    "パラメータ設定",
                    icon="tune",
                    on_click=lambda: open_user_persona_gen_server_tts_params_dialog(
                        ctx,
                        gen_server_params_state,
                        _save_narrator_tts_settings,
                        persona_gen_server_backend_mode(gen_server_tts_mode_state["value"]),
                    ),
                ).props("outline color=primary").classes("w-full")
            if False and persona_is_gen_server_voice_api(endpoint_select.value):
                voice_caption_input = (
                    ui.textarea(
                        label="VoiceDesign caption",
                        value=current_settings.voice_caption,
                        placeholder="落ち着いた低めの声。穏やかで、情景を丁寧に語る。",
                    )
                    .props("outlined rows=3")
                    .classes("w-full")
                )
                ui.button(
                    "パラメータ設定",
                    icon="tune",
                    on_click=lambda: open_user_persona_gen_server_tts_params_dialog(
                        ctx,
                        gen_server_params_state,
                        _save_narrator_tts_settings,
                        GEN_SERVER_MODE_IRODORI_VOICE_DESIGN,
                    ),
                ).props("outline color=primary").classes("w-full")

            tts_text = (
                ui.textarea(
                    label="読み上げテキスト",
                    value="夜の空気が静かに流れ、物語は次の場面へ進んだ。",
                    placeholder="地の文として読み上げるテキスト",
                )
                .props("outlined rows=3")
                .classes("w-full mt-2")
            )
            with ui.row().classes("gap-2 w-full"):
                save_settings_btn = ui.button("TTS設定を保存", icon="save").props("outline color=primary")
                synth_btn = ui.button("読み上げ", icon="play_arrow").props("color=primary unelevated").classes("flex-1")
            tts_status = ui.label("").classes("text-xs text-grey-6")
            preview_container = ui.column().classes("w-full gap-2")

            def _current_narrator_tts_settings() -> CharacterTTSSettings:
                api_type, endpoint_id = persona_parse_voice_api_value(endpoint_select.value)
                selected_tts_endpoint = persona_selected_tts_endpoint(endpoint_select.value, endpoint_by_id)
                voice_id = (voice_id_input.value or "").strip() if voice_id_input else current_settings.voice_id.strip()
                if selected_tts_endpoint is not None and selected_tts_endpoint.provider == TTS_PROVIDER_IRODORI_SERVER:
                    voice_id = voice_id or narrator_tts_id()
                selected_mode = (
                    persona_normalize_gen_server_tts_mode(mode_select.value)
                    if mode_select is not None
                    else gen_server_tts_mode_state["value"]
                )
                caption = (
                    (voice_caption_input.value or "").strip()
                    if voice_caption_input is not None
                    else current_settings.voice_caption.strip()
                )
                backend_mode = persona_gen_server_backend_mode(selected_mode)
                return CharacterTTSSettings(
                    api_type=api_type,
                    endpoint_id=endpoint_id,
                    voice_id=voice_id,
                    gen_server_tts_mode=selected_mode,
                    voice_caption=caption,
                    gen_server_params=clean_gen_server_mode_defaults(
                        backend_mode,
                        dict(gen_server_params_state["value"]),
                    ),
                )

            async def _save_narrator_tts_settings(*, notify: bool = True) -> CharacterTTSSettings:
                settings = _current_narrator_tts_settings()
                config = ctx.user_personas.get_tts_config()
                config.narrator = settings
                ctx.user_personas.save_tts_config(config)
                if notify:
                    ui.notify("ナレーターTTS設定を保存しました", type="positive")
                return settings

            async def _on_endpoint_change(_) -> None:
                await _save_narrator_tts_settings(notify=False)
                refresh_fn()

            async def _on_gen_server_mode_change(_) -> None:
                if mode_select is None:
                    return
                gen_server_tts_mode_state["value"] = persona_normalize_gen_server_tts_mode(mode_select.value)
                gen_server_params_state["value"] = clean_gen_server_mode_defaults(
                    persona_gen_server_backend_mode(gen_server_tts_mode_state["value"]),
                    gen_server_params_state["value"],
                )
                await _save_narrator_tts_settings(notify=False)
                refresh_fn()

            async def _synthesize_narrator() -> None:
                text = (tts_text.value or "").strip()
                if not text:
                    ui.notify("読み上げるテキストを入力してください", type="warning")
                    return
                settings = await _save_narrator_tts_settings(notify=False)
                if not narrator_tts_ready(ctx, settings):
                    ui.notify("ナレーターTTS設定を確認してください", type="warning")
                    return
                config = ctx.user_personas.get_tts_config()
                voice = config.narrator_voice
                voice_path = ctx.user_personas.media_path(voice.path) if voice else None
                synth_btn.disable()
                tts_status.set_text("生成中...")
                preview_container.clear()
                try:

                    def _save_preview(audio: bytes, job) -> dict[str, str]:
                        preview_path = ctx.user_personas.save_narrator_tts_preview(audio)
                        return {
                            "result_url": "/settings",
                            "preview_path": str(preview_path),
                        }

                    job = ctx.tts.start_synthesize_job(
                        narrator_tts_id(),
                        voice_path,
                        text,
                        endpoint_id=settings.endpoint_id,
                        voice_id=settings.voice_id,
                        filename=voice.original_name if voice else "",
                        content_type=voice.content_type if voice else "",
                        api_type=settings.api_type,
                        gen_server_tts_mode=settings.gen_server_tts_mode,
                        voice_caption=settings.voice_caption,
                        gen_server_params=settings.gen_server_params,
                        label="ナレーター読み上げ",
                        scope="narrator:tts",
                        metadata={"target": "narrator"},
                        result_handler=_save_preview,
                    )
                    finished = await ctx.ai_jobs.wait(job.id)
                    if finished.status == AIJobStatus.CANCELLED:
                        tts_status.set_text("")
                        ui.notify("読み上げを停止しました", type="info")
                        return
                    if finished.status != AIJobStatus.SUCCEEDED:
                        raise TTSServiceError(finished.error_message or "読み上げに失敗しました。")
                    preview_path = finished.result_meta.get("preview_path")
                    if not preview_path:
                        raise TTSServiceError("読み上げ音声を取得できませんでした。")
                    with preview_container:
                        ui.audio(preview_path).classes("w-full")
                    tts_status.set_text("")
                    ui.notify("読み上げ音声を生成しました", type="positive")
                except Exception as err:
                    tts_status.set_text("")
                    ui.notify(f"読み上げに失敗しました: {err}", type="negative", timeout=10000)
                finally:
                    synth_btn.enable()

            endpoint_select.on_value_change(_on_endpoint_change)
            if mode_select is not None:
                mode_select.on_value_change(_on_gen_server_mode_change)
            save_settings_btn.on("click", lambda: _save_narrator_tts_settings())
            synth_btn.on("click", _synthesize_narrator)
