"""キャラクターメディア音声 UI。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from nicegui import ui

from ...core.character.schemas import (
    CHARACTER_GEN_SERVER_TTS_MODE_CLONE,
    CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3,
    CHARACTER_TTS_API_DEFAULT,
    CHARACTER_TTS_API_GEN_SERVER,
    CHARACTER_TTS_API_TTS,
    CharacterSheet,
    CharacterTTSSettings,
)
from ...core.gen_server.schemas import (
    GEN_SERVER_DEFAULT_FIELDS,
    GEN_SERVER_MODE_IRODORI_VOICE_CLONE,
    GEN_SERVER_MODE_IRODORI_VOICE_DESIGN,
    GEN_SERVER_MODE_LABELS,
    clean_gen_server_mode_defaults,
)
from ...core.tts.schemas import TTS_PROVIDER_IRODORI_GRADIO, TTS_PROVIDER_IRODORI_SERVER
from ...services.ai_jobs import AIJobStatus
from ...services.llm_runtime import (
    API_KEY_LOCKED,
    ENDPOINT_NOT_FOUND,
    LLMRuntimeError,
    MODEL_ID_MISSING,
    PROFILE_NOT_FOUND,
    build_configured_llm,
)
from ...services.tts import TTSServiceError
from ..state import get_vault_password
from .character_media_image import _read_gen_server_param_value


_TTS_API_PREFIX = "tts:"

_GEN_SERVER_VOICE_CLONE_API = "gen_server:irodori_voice_clone"

_GEN_SERVER_TTS_MODE_OPTIONS = {
    CHARACTER_GEN_SERVER_TTS_MODE_CLONE: "ボイスクローン",
    CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3: "VoiceDesign v3",
}

_VOICE_CAPTION_LABEL_RE = re.compile(
    r"^(?:voice\s*design\s*)?(?:caption|キャプション|ボイスキャプション|音声キャプション)\s*[:：]\s*",
    re.IGNORECASE,
)

_VOICE_IMAGE_SECTION_RE = re.compile(r"(?ms)^## 声のイメージ\s*\n.*?(?=^## |\Z)")


def _voice_caption_sheet_source(sheet: CharacterSheet) -> str:
    raw_markdown = _VOICE_IMAGE_SECTION_RE.sub("", sheet.raw_markdown or "").strip()
    if raw_markdown:
        return raw_markdown

    sections: list[str] = [f"# {sheet.name or 'キャラクター'}"]
    basic_rows = [
        ("名前", sheet.name),
        ("年齢", sheet.age),
        ("性別", sheet.gender),
        ("職業・役割", sheet.occupation),
        ("出身・所属", sheet.origin),
    ]
    basic = "\n".join(f"- {label}: {value}" for label, value in basic_rows if str(value or "").strip())
    if basic:
        sections.append(f"## 基本情報\n{basic}")

    for label, value in [
        ("世界観・舞台", sheet.world),
        ("外見", sheet.appearance),
        ("性格・内面", sheet.personality),
        ("動機・目標", sheet.motivation),
        ("弱点・コンプレックス", sheet.weakness),
        ("過去・背景", sheet.background),
        ("スキル・能力", sheet.skills),
        ("個性・クセ・口癖", sheet.quirks),
        ("自己紹介台詞", sheet.self_intro),
        ("サンプル台詞", sheet.sample_dialogues),
    ]:
        text = str(value or "").strip()
        if text:
            sections.append(f"## {label}\n{text}")

    if sheet.relationships:
        relationships = "\n".join(
            f"- {rel.name}: {rel.description}".strip() for rel in sheet.relationships if (rel.name or rel.description)
        )
        if relationships:
            sections.append(f"## 人間関係\n{relationships}")

    return "\n\n".join(sections).strip()


def _message_content_text(message: object) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text:
                    parts.append(str(text))
        return "\n".join(parts)
    return str(content or "")


def _clean_voice_caption(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^```(?:\w+)?\s*|\s*```$", "", text).strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    caption = lines[0].lstrip("-・* ").strip()
    caption = _VOICE_CAPTION_LABEL_RE.sub("", caption).strip()
    return caption.strip("「」『』\"'")


def _select_voice_caption_llm_profile(ctx) -> Any | None:
    profiles = ctx.api_config.get_llm_profiles()
    if not profiles:
        return None
    app_llm_config = ctx.api_config.get_app_llm_config()
    selected = ctx.api_config.get_llm_profile(app_llm_config.generation_profile_id)
    if selected is not None and selected.model_id:
        return selected
    return next((profile for profile in profiles if profile.model_id), profiles[0])


def _create_voice_caption_llm(ctx):
    profile = _select_voice_caption_llm_profile(ctx)
    if profile is None:
        raise RuntimeError("LLMプロファイルを設定してください。")
    try:
        return build_configured_llm(ctx.api_config, profile.id, get_vault_password())
    except LLMRuntimeError as err:
        if err.kind == PROFILE_NOT_FOUND:
            raise RuntimeError("LLMプロファイルを設定してください。") from err
        if err.kind == MODEL_ID_MISSING:
            raise RuntimeError("LLMプロファイルのモデルIDが未設定です。") from err
        if err.kind == ENDPOINT_NOT_FOUND:
            raise RuntimeError("LLMプロファイルのエンドポイントが見つかりません。") from err
        if err.kind == API_KEY_LOCKED:
            raise RuntimeError("APIキーボルトをロック解除してください。") from err
        raise


async def _generate_voice_caption_from_sheet(sheet: CharacterSheet, ctx) -> str:
    source = _voice_caption_sheet_source(sheet)
    if not source:
        raise RuntimeError("キャラクターシート情報が不足しています。")

    llm = _create_voice_caption_llm(ctx)
    response = await llm.ainvoke(
        [
            SystemMessage(
                content=(
                    "あなたはVoiceDesign v3用の短い音声キャプションを書くアシスタントです。"
                    "出力はキャプション本文1行のみ。見出し、箇条書き、引用符、補足説明は出力しません。"
                )
            ),
            HumanMessage(
                content=(
                    "以下のキャラクターシートから、声質・話速・距離感・感情トーンが伝わる"
                    "VoiceDesign v3用キャプションを生成してください。\n\n"
                    "条件:\n"
                    "- 20〜50字程度の日本語1文にする\n"
                    "- 「男性話者」「女性話者」「中性的な話者」のいずれかを必ず含める\n"
                    "- 年齢感を表す語を含める。判断が難しい場合は「若い」または「大人の」を使う\n"
                    "- キャラクターシートにない固有名詞、過去、関係性、能力は追加しない\n"
                    "- 音声系の既存メモには依存しない\n\n"
                    f"## キャラクターシート\n{source}"
                )
            ),
        ]
    )
    caption = _clean_voice_caption(_message_content_text(response))
    if not caption:
        raise RuntimeError("キャプションを生成できませんでした。")
    return caption


def _open_voice_design_dialog(
    sheet,
    ctx,
    character_id: str,
    refresh_fn,
    actions,
) -> None:
    if ctx.tts.resolve_gen_server_voice_design_endpoint(raise_on_missing=False) is None:
        ui.notify("設定でボイスデザインにWizmy-Gen-Serverを割り当ててください。", type="warning")
        return

    mode = GEN_SERVER_MODE_IRODORI_VOICE_DESIGN
    fields = GEN_SERVER_DEFAULT_FIELDS.get(mode, {})
    defaults = ctx.api_config.get_gen_server_config().defaults_for_mode(mode)
    controls: dict[str, object] = {}
    generated: list[dict[str, object]] = []
    current_voice = sheet.media.primary_voice()
    current_voice_path = actions.media_path(current_voice.path) if current_voice and actions.media_path else None
    initial_caption = sheet.media.tts.voice_caption

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-2xl"):
        with ui.row().classes("w-full items-center justify-between gap-2"):
            ui.label("ボイスデザイン").classes("text-base font-semibold")
            ui.button(icon="close", on_click=dlg.close).props("flat round dense")

        text_input = (
            ui.textarea(
                label="自己紹介台詞",
                value=sheet.self_intro,
                placeholder="生成する音声で読み上げる台詞",
            )
            .props("outlined rows=4")
            .classes("w-full")
        )
        with ui.row().classes("w-full items-end gap-2 flex-wrap"):
            caption_input = (
                ui.textarea(
                    label="キャプション",
                    value=initial_caption,
                    placeholder="例: 明るく柔らかい少女声、少し早口で元気",
                )
                .props("outlined rows=4")
                .classes("flex-1 min-w-[260px]")
            )
            caption_generate_btn = (
                ui.button(
                    "生成",
                    icon="auto_awesome",
                )
                .props("outline color=secondary")
                .classes("mb-1")
            )
            caption_generate_btn.tooltip("キャラクターシートからキャプションを生成")
        reference_checkbox = None
        if current_voice_path is not None:
            reference_checkbox = ui.checkbox(
                "現在のキャラ音声を参照音声として使う",
                value=True,
            ).classes("w-full")

        with ui.expansion("詳細パラメータ", icon="tune").props("dense").classes("w-full"):
            with ui.grid(columns=2).classes("w-full gap-3"):
                for key, spec in fields.items():
                    value = defaults.get(key, spec.get("default"))
                    label = str(spec.get("label", key))
                    if spec.get("type") == "boolean":
                        controls[key] = ui.checkbox(label, value=bool(value)).classes("w-full")
                    elif spec.get("enum"):
                        options = list(spec["enum"])
                        controls[key] = (
                            ui.select(
                                options=options,
                                value=value if value in options else spec.get("default"),
                                label=label,
                            )
                            .props("outlined dense")
                            .classes("w-full")
                        )
                    elif spec.get("type") in {"integer", "number"}:
                        controls[key] = (
                            ui.number(
                                label=label,
                                value=value,
                                min=spec.get("minimum"),
                                step=spec.get("step"),
                            )
                            .props("outlined dense")
                            .classes("w-full")
                        )
                    elif key == "model_id":
                        with ui.row().classes("w-full items-end gap-2"):
                            model_input = (
                                ui.input(
                                    label=label,
                                    value=value or "",
                                )
                                .props("outlined dense clearable")
                                .classes("flex-1")
                            )
                            ui.button(
                                icon="refresh",
                                on_click=lambda model_input=model_input: _fetch_character_gen_server_model_id(
                                    model_input,
                                    ctx,
                                    mode,
                                ),
                            ).props("flat round").tooltip("モデルIDを取得")
                        controls[key] = model_input
                    else:
                        controls[key] = (
                            ui.input(
                                label=label,
                                value=value or "",
                            )
                            .props("outlined dense clearable")
                            .classes("w-full")
                        )

        status = ui.label("").classes("text-xs text-grey-6")
        with (
            ui.element("div")
            .classes("w-full rounded-md border p-2")
            .style(
                "max-height: 320px; overflow-y: auto; "
                "background: var(--cs-surface-soft); border-color: var(--cs-border);"
            )
        ):
            preview_container = ui.column().classes("w-full gap-2")

        def _read_params() -> dict[str, object]:
            return {key: _read_gen_server_param_value(spec, controls[key]) for key, spec in fields.items()}

        def _render_generated() -> None:
            preview_container.clear()
            with preview_container:
                if not generated:
                    return
                ui.label("生成候補").classes("text-sm font-semibold")
                for index, item in enumerate(generated, start=1):
                    audio_path = item["path"]
                    _ = item["audio"]
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
                        ui.audio(audio_path).classes("w-full")

        async def _generate_caption() -> None:
            caption_generate_btn.disable()
            status.set_text("キャプション生成中...")
            try:
                caption = await _generate_voice_caption_from_sheet(sheet, ctx)
                caption_input.set_value(caption)
                status.set_text("")
                ui.notify("キャプションを生成しました", type="positive")
            except Exception as err:
                status.set_text("")
                ui.notify(f"キャプション生成に失敗しました: {err}", type="negative", timeout=10000)
            finally:
                caption_generate_btn.enable()

        async def _generate() -> None:
            text = (text_input.value or "").strip()
            caption = (caption_input.value or "").strip()
            if not text:
                ui.notify("自己紹介台詞を入力してください。", type="warning")
                return
            if not caption:
                ui.notify("キャプションを入力してください。", type="warning")
                return

            generate_btn.disable()
            status.set_text("生成中...")
            try:
                params = _read_params()

                def _save_preview(audio: bytes, job) -> dict[str, object]:
                    if actions.save_tts_preview is None:
                        raise RuntimeError("音声プレビューの保存処理が設定されていません。")
                    preview_path = actions.save_tts_preview(
                        audio,
                        replace_existing=False,
                    )
                    generated.append(
                        {
                            "audio": audio,
                            "path": preview_path,
                            "caption": caption,
                            "params": params,
                        }
                    )
                    return {
                        "result_url": actions.result_url,
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
                    label=f"{sheet.name or 'キャラクター'}のボイスデザイン",
                    scope=f"{actions.scope_prefix}:tts",
                    metadata=dict(actions.metadata),
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
                ui.notify("ボイスデザイン音声を生成しました", type="positive")
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
                if actions.save_voice_bytes is None or actions.update_tts_settings is None:
                    raise RuntimeError("音声の保存処理が設定されていません。")
                saved = await actions.save_voice_bytes(
                    audio,
                    filename=f"voice-design-{index}.wav",
                    content_type="audio/wav",
                )
                previous_is_clone = saved.media.tts.gen_server_tts_mode == CHARACTER_GEN_SERVER_TTS_MODE_CLONE
                clone_params = saved.media.tts.gen_server_params if previous_is_clone else {}
                settings = saved.media.tts.model_copy(
                    update={
                        "api_type": CHARACTER_TTS_API_GEN_SERVER,
                        "gen_server_tts_mode": CHARACTER_GEN_SERVER_TTS_MODE_CLONE,
                        "voice_caption": str(item.get("caption") or "").strip(),
                        "gen_server_params": clean_gen_server_mode_defaults(
                            GEN_SERVER_MODE_IRODORI_VOICE_CLONE,
                            clone_params,
                        ),
                    }
                )
                updated = await actions.update_tts_settings(settings)
                sheet.media = updated.media
                ui.notify("生成音声をキャラ音声に保存しました", type="positive")
                dlg.close()
                refresh_fn()
            except Exception as err:
                ui.notify(f"音声の保存に失敗しました: {err}", type="negative")

        caption_generate_btn.on("click", _generate_caption)

        with ui.row().classes("justify-end gap-2 mt-3"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            generate_btn = ui.button("生成", icon="auto_awesome", on_click=_generate).props("color=primary unelevated")

    dlg.open()


def _render_tts_controls(
    sheet,
    ctx,
    character_id: str,
    voice,
    voice_path: Path,
    refresh_fn,
    actions,
) -> None:
    ui.separator().classes("my-3")
    endpoints = ctx.tts.get_endpoints()
    gen_server_config = ctx.api_config.get_gen_server_config()
    has_gen_server = bool(_assigned_gen_server_voice_endpoints(gen_server_config))
    if not endpoints and not has_gen_server:
        ui.label("使用できるTTSがありません。Wizmy-Gen-ServerまたはTTS APIを設定してください。").classes(
            "text-sm text-grey-6"
        )
        return

    current_settings = sheet.media.tts
    endpoint_by_id = {endpoint.id: endpoint for endpoint in endpoints}
    endpoint_options = _voice_api_options(endpoints, gen_server_config)
    selected_value = _selected_voice_api_value(current_settings, endpoints, has_gen_server)
    selected_endpoint = _selected_tts_endpoint(selected_value, endpoint_by_id)
    gen_server_tts_mode_state = {"value": _normalize_gen_server_tts_mode(current_settings.gen_server_tts_mode)}
    gen_server_backend_mode = _gen_server_backend_mode(gen_server_tts_mode_state["value"])
    gen_server_params_state = {
        "value": clean_gen_server_mode_defaults(
            gen_server_backend_mode,
            current_settings.gen_server_params,
        )
    }
    voice_caption_value = current_settings.voice_caption

    endpoint_select = (
        ui.select(
            options=endpoint_options,
            value=selected_value,
            label="使用API",
        )
        .props("outlined")
        .classes("w-full")
    )

    async def _change_endpoint() -> None:
        if actions.update_tts_settings is None:
            raise RuntimeError("TTS設定の保存処理が設定されていません。")
        saved = await actions.update_tts_settings(_current_tts_settings())
        sheet.media = saved.media
        refresh_fn()

    async def _on_endpoint_change(_) -> None:
        await _change_endpoint()

    endpoint_select.on_value_change(_on_endpoint_change)

    voice_id_input = None
    if selected_endpoint is not None and selected_endpoint.provider == TTS_PROVIDER_IRODORI_SERVER:
        default_voice_id = ctx.tts.voice_id_for_character(actions.target_id, current_settings.voice_id)
        voice_id_input = (
            ui.input(
                label="Voice ID",
                value=current_settings.voice_id,
                placeholder=default_voice_id,
            )
            .props("outlined clearable")
            .classes("w-full")
        )
        ui.label(f"既定値: {default_voice_id}").classes("text-xs text-grey-6 font-mono break-all")
        with ui.row().classes("gap-2 w-full"):
            register_btn = (
                ui.button("Irodoriに登録", icon="cloud_upload").props("outline color=primary").classes("flex-1")
            )
            delete_btn = (
                ui.button("Irodoriから削除", icon="delete_outline").props("outline color=negative").classes("flex-1")
            )

    mode_select = None
    voice_caption_input = None
    voice_caption_generate_btn = None
    if _is_gen_server_voice_api(selected_value):
        mode_select = (
            ui.select(
                options=_GEN_SERVER_TTS_MODE_OPTIONS,
                value=gen_server_tts_mode_state["value"],
                label="Gen-Server TTSモード",
            )
            .props("outlined")
            .classes("w-full")
        )

        async def _on_gen_server_mode_change(_) -> None:
            gen_server_tts_mode_state["value"] = _normalize_gen_server_tts_mode(mode_select.value)
            backend_mode = _gen_server_backend_mode(gen_server_tts_mode_state["value"])
            gen_server_params_state["value"] = clean_gen_server_mode_defaults(
                backend_mode,
                gen_server_params_state["value"],
            )
            await _save_tts_settings(notify=False)
            refresh_fn()

        mode_select.on_value_change(_on_gen_server_mode_change)
        if gen_server_tts_mode_state["value"] == CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3:
            with ui.row().classes("w-full items-end gap-2 flex-wrap"):
                voice_caption_input = (
                    ui.textarea(
                        label="キャプション",
                        value=voice_caption_value,
                        placeholder="例: 明るく柔らかい少女声、少し早口で元気",
                    )
                    .props("outlined rows=3")
                    .classes("flex-1 min-w-[220px]")
                )
                voice_caption_generate_btn = (
                    ui.button(
                        "生成",
                        icon="auto_awesome",
                    )
                    .props("outline color=secondary")
                    .classes("mb-1")
                )
                voice_caption_generate_btn.tooltip("キャラクターシートからキャプションを生成")

        ui.button(
            "パラメータ設定",
            icon="tune",
            on_click=lambda: _open_gen_server_tts_params_dialog(
                ctx,
                gen_server_params_state,
                _save_tts_settings,
                _gen_server_backend_mode(gen_server_tts_mode_state["value"]),
            ),
        ).props("outline color=primary").classes("w-full")

    tts_text = (
        ui.textarea(
            label="読み上げテキスト",
            value=sheet.self_intro,
            placeholder="読み上げるテキスト",
        )
        .props("outlined rows=4")
        .classes("w-full mt-2")
    )
    with ui.row().classes("gap-2 w-full"):
        save_settings_btn = ui.button("TTS設定を保存", icon="save").props("outline color=primary")
        synth_btn = ui.button("読み上げ", icon="play_arrow").props("color=primary unelevated").classes("flex-1")
    tts_status = ui.label("").classes("text-xs text-grey-6")
    preview_container = ui.column().classes("w-full gap-2")

    async def _generate_voice_caption_for_tts() -> None:
        if voice_caption_input is None or voice_caption_generate_btn is None:
            return
        voice_caption_generate_btn.disable()
        tts_status.set_text("キャプション生成中...")
        try:
            caption = await _generate_voice_caption_from_sheet(sheet, ctx)
            voice_caption_input.set_value(caption)
            tts_status.set_text("")
            ui.notify("キャプションを生成しました", type="positive")
        except Exception as err:
            tts_status.set_text("")
            ui.notify(f"キャプション生成に失敗しました: {err}", type="negative", timeout=10000)
        finally:
            voice_caption_generate_btn.enable()

    def _current_tts_settings() -> CharacterTTSSettings:
        api_type, endpoint_id = _parse_voice_api_value(endpoint_select.value)
        selected_mode = (
            _normalize_gen_server_tts_mode(mode_select.value)
            if mode_select is not None
            else gen_server_tts_mode_state["value"]
        )
        caption = (
            (voice_caption_input.value or "").strip()
            if voice_caption_input is not None
            else current_settings.voice_caption.strip()
        )
        backend_mode = _gen_server_backend_mode(selected_mode)
        return CharacterTTSSettings(
            api_type=api_type,
            endpoint_id=endpoint_id,
            voice_id=(voice_id_input.value or "").strip() if voice_id_input else current_settings.voice_id,
            gen_server_tts_mode=selected_mode,
            voice_caption=caption,
            gen_server_params=clean_gen_server_mode_defaults(
                backend_mode,
                dict(gen_server_params_state["value"]),
            ),
        )

    async def _save_tts_settings(*, notify: bool = True) -> CharacterTTSSettings:
        settings = _current_tts_settings()
        if actions.update_tts_settings is None:
            raise RuntimeError("TTS設定の保存処理が設定されていません。")
        saved = await actions.update_tts_settings(settings)
        sheet.media = saved.media
        if notify:
            ui.notify("TTS設定を保存しました", type="positive")
        return settings

    async def _register_tts_voice() -> None:
        settings = await _save_tts_settings(notify=False)
        register_btn.disable()
        try:
            await ctx.tts.register_voice(
                actions.target_id,
                voice_path,
                endpoint_id=settings.endpoint_id,
                voice_id=settings.voice_id,
                filename=voice.original_name,
                content_type=voice.content_type,
            )
            ui.notify("Irodori-TTS-Serverに登録しました", type="positive")
        except TTSServiceError as err:
            ui.notify(f"登録に失敗しました: {err}", type="negative")
        except Exception as err:
            ui.notify(f"登録に失敗しました: {err}", type="negative")
        finally:
            register_btn.enable()

    async def _delete_tts_voice() -> None:
        settings = await _save_tts_settings(notify=False)
        delete_btn.disable()
        try:
            deleted = await ctx.tts.delete_voice(
                actions.target_id,
                endpoint_id=settings.endpoint_id,
                voice_id=settings.voice_id,
            )
            if deleted:
                ui.notify("Irodori-TTS-Serverから削除しました", type="positive")
            else:
                ui.notify("Irodori-TTS-Serverに登録されていません", type="info")
        except TTSServiceError as err:
            ui.notify(f"削除に失敗しました: {err}", type="negative")
        except Exception as err:
            ui.notify(f"削除に失敗しました: {err}", type="negative")
        finally:
            delete_btn.enable()

    async def _synthesize_tts() -> None:
        text = (tts_text.value or "").strip()
        if not text:
            ui.notify("読み上げるテキストを入力してください", type="warning")
            return

        settings = await _save_tts_settings(notify=False)
        if (
            settings.api_type == CHARACTER_TTS_API_GEN_SERVER
            and settings.gen_server_tts_mode == CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3
            and not settings.voice_caption.strip()
        ):
            ui.notify("VoiceDesign v3モードではキャプションを入力してください。", type="warning")
            return
        synth_btn.disable()
        tts_status.set_text("生成中...")
        preview_container.clear()
        try:

            def _save_preview(audio: bytes, job) -> dict[str, str]:
                if actions.save_tts_preview is None:
                    raise RuntimeError("音声プレビューの保存処理が設定されていません。")
                preview_path = actions.save_tts_preview(audio)
                return {
                    "result_url": actions.result_url,
                    "preview_path": str(preview_path),
                }

            job = ctx.tts.start_synthesize_job(
                actions.target_id,
                voice_path,
                text,
                endpoint_id=settings.endpoint_id,
                voice_id=settings.voice_id,
                filename=voice.original_name,
                content_type=voice.content_type,
                api_type=settings.api_type,
                gen_server_tts_mode=settings.gen_server_tts_mode,
                voice_caption=settings.voice_caption,
                gen_server_params=settings.gen_server_params,
                label=f"{sheet.name or 'キャラクター'}の読み上げ",
                scope=f"{actions.scope_prefix}:tts",
                metadata=dict(actions.metadata),
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
            preview_container.clear()
            with preview_container:
                ui.audio(preview_path).classes("w-full")
            tts_status.set_text("")
            ui.notify("読み上げ音声を生成しました", type="positive")
        except TTSServiceError as err:
            tts_status.set_text("")
            ui.notify(f"読み上げに失敗しました: {err}", type="negative")
        except Exception as err:
            tts_status.set_text("")
            ui.notify(f"読み上げに失敗しました: {err}", type="negative")
        finally:
            synth_btn.enable()

    save_settings_btn.on("click", lambda: _save_tts_settings())
    if voice_caption_generate_btn is not None:
        voice_caption_generate_btn.on("click", _generate_voice_caption_for_tts)
    if selected_endpoint is not None and selected_endpoint.provider == TTS_PROVIDER_IRODORI_SERVER:
        register_btn.on("click", _register_tts_voice)
        delete_btn.on("click", _delete_tts_voice)
    synth_btn.on("click", _synthesize_tts)


def _voice_api_options(endpoints, gen_server_config) -> dict[str, str]:
    options: dict[str, str] = {}
    assigned = _assigned_gen_server_voice_endpoints(gen_server_config)
    if assigned:
        names = sorted({endpoint.name for endpoint in assigned if endpoint.name})
        name_label = ", ".join(names) if names else "割り当て済み"
        options[_GEN_SERVER_VOICE_CLONE_API] = f"Wizmy-Gen-Server (TTS: {name_label})"
    options.update(
        {
            f"{_TTS_API_PREFIX}{endpoint.id}": f"{endpoint.name} ({_tts_provider_label(endpoint.provider)})"
            for endpoint in endpoints
        }
    )
    return options


def _selected_voice_api_value(settings: CharacterTTSSettings, endpoints, has_gen_server: bool) -> str:
    if settings.api_type == CHARACTER_TTS_API_GEN_SERVER and has_gen_server:
        return _GEN_SERVER_VOICE_CLONE_API
    endpoint_ids = {endpoint.id for endpoint in endpoints}
    if settings.api_type == CHARACTER_TTS_API_TTS and settings.endpoint_id in endpoint_ids:
        return f"{_TTS_API_PREFIX}{settings.endpoint_id}"
    if has_gen_server:
        return _GEN_SERVER_VOICE_CLONE_API
    if endpoints:
        return f"{_TTS_API_PREFIX}{endpoints[0].id}"
    return ""


def _assigned_voice_clone_endpoint(gen_server_config):
    assigned_id = gen_server_config.assigned_endpoint_id(GEN_SERVER_MODE_IRODORI_VOICE_CLONE)
    return next(
        (endpoint for endpoint in gen_server_config.endpoints if endpoint.id == assigned_id),
        None,
    )


def _assigned_voice_design_endpoint(gen_server_config):
    assigned_id = gen_server_config.assigned_endpoint_id(GEN_SERVER_MODE_IRODORI_VOICE_DESIGN)
    return next(
        (endpoint for endpoint in gen_server_config.endpoints if endpoint.id == assigned_id),
        None,
    )


def _assigned_gen_server_voice_endpoints(gen_server_config) -> list:
    endpoints = [
        endpoint
        for endpoint in [
            _assigned_voice_clone_endpoint(gen_server_config),
            _assigned_voice_design_endpoint(gen_server_config),
        ]
        if endpoint is not None
    ]
    result = []
    seen: set[str] = set()
    for endpoint in endpoints:
        if endpoint.id in seen:
            continue
        result.append(endpoint)
        seen.add(endpoint.id)
    return result


def _normalize_gen_server_tts_mode(value: str | None) -> str:
    selected = str(value or "")
    if selected == CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3:
        return CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3
    return CHARACTER_GEN_SERVER_TTS_MODE_CLONE


def _gen_server_backend_mode(tts_mode: str) -> str:
    if tts_mode == CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3:
        return GEN_SERVER_MODE_IRODORI_VOICE_DESIGN
    return GEN_SERVER_MODE_IRODORI_VOICE_CLONE


def _parse_voice_api_value(value: str | None) -> tuple[str, str]:
    selected = str(value or "")
    if selected == _GEN_SERVER_VOICE_CLONE_API:
        return CHARACTER_TTS_API_GEN_SERVER, ""
    if selected.startswith(_TTS_API_PREFIX):
        return CHARACTER_TTS_API_TTS, selected[len(_TTS_API_PREFIX) :]
    return CHARACTER_TTS_API_DEFAULT, ""


def _selected_tts_endpoint(value: str | None, endpoint_by_id: dict):
    api_type, endpoint_id = _parse_voice_api_value(value)
    if api_type != CHARACTER_TTS_API_TTS:
        return None
    return endpoint_by_id.get(endpoint_id)


def _is_gen_server_voice_api(value: str | None) -> bool:
    return _parse_voice_api_value(value)[0] == CHARACTER_TTS_API_GEN_SERVER


def _open_gen_server_tts_params_dialog(ctx, params_state: dict, save_settings, mode: str) -> None:
    fields = GEN_SERVER_DEFAULT_FIELDS.get(mode, {})
    defaults = ctx.api_config.get_gen_server_config().defaults_for_mode(mode)
    current = {
        **defaults,
        **clean_gen_server_mode_defaults(mode, params_state["value"]),
    }
    controls: dict[str, object] = {}

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-2xl"):
        with ui.row().classes("w-full items-center justify-between gap-2"):
            ui.label("Wizmy-Gen-Server パラメータ").classes("text-base font-semibold")
            ui.button(icon="close", on_click=dlg.close).props("flat round dense")

        with ui.scroll_area().style("max-height: 65vh; width: 100%;"):
            with ui.grid(columns=2).classes("w-full gap-3 pr-2"):
                for key, spec in fields.items():
                    value = current.get(key, spec.get("default"))
                    label = str(spec.get("label", key))
                    if spec.get("type") == "boolean":
                        controls[key] = ui.checkbox(label, value=bool(value)).classes("w-full")
                    elif spec.get("enum"):
                        options = list(spec["enum"])
                        controls[key] = (
                            ui.select(
                                options=options,
                                value=value if value in options else spec.get("default"),
                                label=label,
                            )
                            .props("outlined dense")
                            .classes("w-full")
                        )
                    elif spec.get("type") in {"integer", "number"}:
                        controls[key] = (
                            ui.number(
                                label=label,
                                value=value,
                                min=spec.get("minimum"),
                                step=spec.get("step"),
                            )
                            .props("outlined dense")
                            .classes("w-full")
                        )
                    elif spec.get("multiline"):
                        controls[key] = (
                            ui.textarea(
                                label=label,
                                value=value or "",
                            )
                            .props("outlined rows=3")
                            .classes("w-full col-span-2")
                        )
                    elif key == "model_id":
                        with ui.row().classes("w-full items-end gap-2"):
                            model_input = (
                                ui.input(
                                    label=label,
                                    value=value or "",
                                )
                                .props("outlined dense clearable")
                                .classes("flex-1")
                            )
                            ui.button(
                                icon="refresh",
                                on_click=lambda model_input=model_input: _fetch_character_gen_server_model_id(
                                    model_input,
                                    ctx,
                                    mode,
                                ),
                            ).props("flat round").tooltip("モデルIDを取得")
                        controls[key] = model_input
                    else:
                        controls[key] = (
                            ui.input(
                                label=label,
                                value=value or "",
                            )
                            .props("outlined dense clearable")
                            .classes("w-full")
                        )

        def _read_params() -> dict[str, object]:
            return {key: _read_gen_server_param_value(spec, controls[key]) for key, spec in fields.items()}

        async def _clear_overrides() -> None:
            params_state["value"] = {}
            await save_settings(notify=False)
            ui.notify("キャラ固有パラメータをクリアしました", type="positive")
            dlg.close()

        async def _save() -> None:
            values = _read_params()
            overrides = {
                key: value for key, value in values.items() if value != defaults.get(key, fields[key].get("default"))
            }
            params_state["value"] = clean_gen_server_mode_defaults(
                mode,
                overrides,
            )
            await save_settings(notify=False)
            ui.notify("パラメータを保存しました", type="positive")
            dlg.close()

        with ui.row().classes("justify-end gap-2 mt-3"):
            ui.button("固有設定をクリア", icon="restart_alt", on_click=_clear_overrides).props("flat")
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("保存", icon="save", on_click=_save).props("color=primary unelevated")

    dlg.open()


async def _fetch_character_gen_server_model_id(
    model_input,
    ctx,
    mode: str = GEN_SERVER_MODE_IRODORI_VOICE_CLONE,
) -> None:
    config = ctx.api_config.get_gen_server_config()
    endpoint_id = config.assigned_endpoint_id(mode)
    mode_label = GEN_SERVER_MODE_LABELS.get(mode, mode)
    if not endpoint_id:
        ui.notify(f"先に{mode_label}へWizmy-Gen-Serverを割り当ててください。", type="warning")
        return

    try:
        models = await ctx.api_config.fetch_gen_server_models(endpoint_id, mode)
    except Exception as err:
        ui.notify(f"モデルIDを取得できませんでした: {err}", type="negative")
        return

    if not models:
        ui.notify(f"{mode_label}で利用できるモデルが見つかりませんでした。", type="warning")
        return

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg"):
        ui.label(f"{mode_label}のモデルID").classes("text-base font-semibold mb-2")
        with ui.scroll_area().style("max-height: 50vh; width: 100%"):
            with ui.list().props("dense separator").classes("w-full"):
                for model in models:
                    model_id = str(model.get("id") or "")
                    display_name = str(model.get("display_name") or model_id)

                    def _select(model_id: str = model_id) -> None:
                        model_input.set_value(model_id)
                        dlg.close()

                    with ui.item(on_click=_select).classes("cursor-pointer"):
                        with ui.item_section():
                            ui.label(display_name).classes("text-sm font-medium")
                            ui.label(model_id).classes("text-xs text-grey-6 font-mono break-all")

    dlg.open()


def _tts_provider_label(provider: str) -> str:
    if provider == TTS_PROVIDER_IRODORI_GRADIO:
        return "Irodori-TTS Gradio / 07dfa74"
    if provider == TTS_PROVIDER_IRODORI_SERVER:
        return "Irodori-TTS-Server"
    return provider
