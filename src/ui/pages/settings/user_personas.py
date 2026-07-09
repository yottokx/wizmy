from __future__ import annotations

import uuid

from nicegui import ui

from ....core.character.schemas import (
    CHARACTER_TTS_API_DEFAULT,
    CharacterImageAsset,
    CharacterTTSSettings,
)
from ....core.chat.schemas import UserPersona
from ....core.tts.options import (
    GEN_SERVER_TTS_MODE_OPTIONS,
    PERSONA_GEN_SERVER_VOICE_API_VALUE,
    TTS_API_PREFIX,
    assigned_gen_server_voice_endpoints,
    gen_server_backend_mode,
    is_gen_server_voice_api,
    normalize_gen_server_tts_mode,
    parse_voice_api_value,
    selected_tts_endpoint,
    selected_voice_api_value,
    voice_api_options,
)
from ...chat.media import cropped_background_style
from ...components.character_media import CharacterMediaActions, _open_media_upload_dialog
from ...components.character_media_image import _open_image_rect_dialog, open_simple_image_generation_dialog
from ...components.character_media_voice import (
    _open_voice_design_dialog,
    _render_tts_controls,
)
from .common import (
    enable_drag_sort,
    moved_order,
    notify_order_saved,
    short_text,
)

PERSONA_TTS_API_PREFIX = TTS_API_PREFIX
PERSONA_GEN_SERVER_VOICE_API = PERSONA_GEN_SERVER_VOICE_API_VALUE
PERSONA_GEN_SERVER_TTS_MODE_OPTIONS = GEN_SERVER_TTS_MODE_OPTIONS


async def build_user_personas_tab(ctx) -> None:
    personas_container = ui.column().classes("w-full gap-3")

    async def reorder(e) -> None:
        args = e.args
        ordered = moved_order(
            [persona.id for persona in ctx.user_personas.get_user_personas()],
            args["old_index"],
            args["new_index"],
        )
        if ordered is None:
            return
        ctx.user_personas.reorder_user_personas(ordered)
        notify_order_saved()

    enable_drag_sort(personas_container, reorder)

    async def refresh() -> None:
        personas = ctx.user_personas.get_user_personas()
        personas_container.clear()
        with personas_container:
            if not personas:
                ui.label("ユーザーペルソナが登録されていません。チャット開始前に追加してください。").classes(
                    "text-grey-6 py-4"
                )
            for persona in personas:
                user_persona_card(persona, ctx, refresh)

    await refresh()

    ui.button(
        "ユーザーペルソナを追加",
        icon="add",
        on_click=lambda: open_user_persona_dialog(None, ctx, refresh),
    ).props("color=primary unelevated").classes("mt-2")


def user_persona_card(persona: UserPersona, ctx, refresh_fn) -> None:
    with ui.card().classes("w-full cursor-grab"):
        with ui.card_section():
            with ui.row().classes("w-full items-start gap-4 flex-col md:flex-row"):
                with ui.column().classes("flex-1 gap-1 min-w-0"):
                    ui.label(persona.display_name).classes("text-base font-semibold")
                    if persona.persona_name.strip():
                        ui.label(f"名前: {persona.name}").classes("text-xs text-grey-6")
                    ui.label(short_text(persona.description)).classes("text-sm text-grey-6").style(
                        "white-space: pre-wrap; overflow-wrap: anywhere;"
                    )
                    with ui.row().classes("gap-2 mt-2"):
                        ui.button(
                            icon="edit",
                            on_click=lambda p=persona: open_user_persona_dialog(p, ctx, refresh_fn),
                        ).props("flat round dense color=primary")
                        ui.button(
                            icon="delete",
                            on_click=lambda p=persona: confirm_delete_user_persona(p, ctx, refresh_fn),
                        ).props("flat round dense color=negative")
                user_persona_media_summary(persona, ctx, refresh_fn)


def user_persona_media_summary(persona: UserPersona, ctx, refresh_fn) -> None:
    image = persona.media.primary_image()
    image_path = ctx.user_personas.media_path(image.path) if image else None
    voice = persona.media.primary_voice()
    has_tts = user_persona_has_tts_settings(persona)

    with (
        ui.element("div")
        .classes("w-full md:w-[280px] shrink-0 rounded-md border p-3")
        .style("border-color: var(--cs-border); background: var(--cs-surface-soft);")
    ):
        with ui.row().classes("w-full items-center gap-3"):
            if image and image_path:
                ui.element("div").classes("w-14 h-14 rounded-md shrink-0 border").style(
                    f"border-color: var(--cs-border); {cropped_background_style(image, image_path, image.face_rect, 1.0)}"
                )
            else:
                with (
                    ui.element("div")
                    .classes("w-14 h-14 rounded-md shrink-0 border flex items-center justify-center")
                    .style("border-color: var(--cs-border); background: var(--cs-surface);")
                ):
                    ui.icon("person").classes("text-2xl text-grey-5")
            with ui.column().classes("gap-1 min-w-0 flex-1"):
                ui.label("画像・音声設定").classes("text-sm font-semibold")
                ui.label(f"画像: {'設定済み' if image else '未設定'}").classes("text-xs text-grey-6")
                ui.label(
                    f"音声: {'設定済み' if voice else '未設定'} / TTS: {'設定済み' if has_tts else '未設定'}"
                ).classes("text-xs text-grey-6")
        ui.button(
            "画像・音声を設定",
            icon="perm_media",
            on_click=lambda p=persona: open_user_persona_media_dialog(p, ctx, refresh_fn),
        ).props("outline color=secondary").classes("w-full mt-3")


def user_persona_has_tts_settings(persona: UserPersona) -> bool:
    settings = persona.media.tts
    return bool(
        settings.api_type != CHARACTER_TTS_API_DEFAULT
        or settings.endpoint_id.strip()
        or settings.voice_id.strip()
        or settings.voice_caption.strip()
        or settings.gen_server_params
    )


def open_user_persona_dialog(persona: UserPersona | None, ctx, refresh_fn) -> None:
    is_edit = persona is not None

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg"):
        ui.label("ユーザーペルソナを編集" if is_edit else "ユーザーペルソナを追加").classes(
            "text-lg font-semibold mb-3"
        )
        name_input = (
            ui.input(
                label="名前（会話内で使う名前）",
                value=persona.name if persona else "",
            )
            .props("outlined")
            .classes("w-full")
        )
        persona_name_input = (
            ui.input(
                label="ペルソナ名（表示用・任意）",
                value=persona.persona_name if persona else "",
                placeholder="同じ名前の設定を区別するための名前",
            )
            .props("outlined clearable")
            .classes("w-full")
        )
        description_input = (
            ui.textarea(
                label="設定",
                value=persona.description if persona else "",
            )
            .props("outlined rows=5")
            .classes("w-full")
        )

        async def _save_user_persona() -> None:
            name = (name_input.value or "").strip()
            persona_name = (persona_name_input.value or "").strip()
            description = (description_input.value or "").strip()
            if not name or not description:
                ui.notify("名前と設定を入力してください", type="negative")
                return

            values = {
                "id": persona.id if persona else str(uuid.uuid4())[:8],
                "name": name,
                "persona_name": persona_name,
                "description": description,
            }
            if persona is not None:
                values["media"] = persona.media
            updated = UserPersona(**values)
            if is_edit:
                ctx.user_personas.update_user_persona(updated)
            else:
                ctx.user_personas.create_user_persona(updated)
            ui.notify("保存しました", type="positive")
            dlg.close()
            await refresh_fn()

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("保存", icon="save", on_click=_save_user_persona).props("color=primary unelevated")

    dlg.open()


def confirm_delete_user_persona(persona: UserPersona, ctx, refresh_fn) -> None:
    with ui.dialog() as dlg, ui.card().classes("w-full max-w-sm"):
        ui.label(f"「{persona.display_name}」を削除しますか？").classes("font-medium mb-2")
        ui.label("このユーザーペルソナは新しいチャット開始時に選べなくなります。").classes("text-sm text-grey-6")
        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")

            async def _do() -> None:
                ctx.user_personas.delete_user_persona(persona.id)
                ui.notify("削除しました", type="positive")
                dlg.close()
                await refresh_fn()

            ui.button("削除", on_click=_do).props("color=negative unelevated")
    dlg.open()


def open_user_persona_media_dialog(persona: UserPersona, ctx, refresh_fn) -> None:
    state = {"persona": persona}

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-4xl"):
        with ui.row().classes("w-full items-center justify-between gap-2"):
            ui.label(f"{persona.display_name} の画像・音声").classes("text-lg font-semibold")
            ui.button(icon="close", on_click=dlg.close).props("flat round dense")

        container = ui.column().classes("w-full gap-4")

        async def _refresh(saved: UserPersona | None = None) -> None:
            latest = saved or ctx.user_personas.get_user_persona(state["persona"].id)
            if latest is None:
                dlg.close()
                await refresh_fn()
                return
            state["persona"] = latest
            container.clear()
            with container:
                render_user_persona_media_sections(latest, ctx, _refresh, refresh_fn)
            await refresh_fn()

        with container:
            render_user_persona_media_sections(persona, ctx, _refresh, refresh_fn)

    dlg.open()


def render_user_persona_media_sections(
    persona: UserPersona,
    ctx,
    refresh_media,
    refresh_fn,
) -> None:
    with ui.grid(columns=2).classes("w-full gap-4"):
        render_user_persona_image_section(persona, ctx, refresh_media)
        render_user_persona_voice_section(persona, ctx, refresh_media, refresh_fn)


def user_persona_media_actions(persona: UserPersona, ctx) -> CharacterMediaActions:
    async def _save_image(upload):
        return await ctx.user_personas.save_user_persona_image(persona.id, upload)

    async def _save_image_bytes(image_bytes: bytes, **kwargs):
        return await ctx.user_personas.save_user_persona_image_bytes(persona.id, image_bytes, **kwargs)

    async def _save_voice(upload):
        return await ctx.user_personas.save_user_persona_voice(persona.id, upload)

    async def _save_voice_bytes(audio_bytes: bytes, **kwargs):
        return await ctx.user_personas.save_user_persona_voice_bytes(persona.id, audio_bytes, **kwargs)

    async def _update_tts_settings(settings: CharacterTTSSettings):
        return ctx.user_personas.update_user_persona_tts_settings(persona.id, settings)

    async def _update_face_rect(rect, **kwargs):
        return ctx.user_personas.update_user_persona_face_rect(persona.id, rect, **kwargs)

    return CharacterMediaActions(
        target_id=user_persona_tts_id(persona.id),
        tts_id=user_persona_tts_id(persona.id),
        result_url="/legacy/settings",
        scope_prefix=f"user_persona:{persona.id}",
        metadata={"persona_id": persona.id},
        media_path=ctx.user_personas.media_path,
        save_image=_save_image,
        save_image_bytes=_save_image_bytes,
        save_voice=_save_voice,
        save_voice_bytes=_save_voice_bytes,
        update_tts_settings=_update_tts_settings,
        update_face_rect=_update_face_rect,
        save_tts_preview=lambda audio_bytes, **kwargs: ctx.user_personas.save_user_persona_tts_preview(
            persona.id,
            audio_bytes,
            **kwargs,
        ),
        save_image_preview=lambda image_bytes, **kwargs: ctx.user_personas.save_user_persona_image_preview(
            persona.id,
            image_bytes,
            **kwargs,
        ),
        save_tts_playback=lambda audio_bytes: ctx.user_personas.save_user_persona_tts_playback(
            persona.id,
            audio_bytes,
        ),
        image_generation_title="ペルソナ画像生成",
        image_generation_save_message="生成画像をペルソナ画像に保存しました",
        image_generation_job_label=lambda _: "ユーザーペルソナ画像生成",
        image_generation_filename=user_persona_generated_image_filename,
        voice_design_title="ペルソナボイスデザイン",
        voice_design_text_label="読み上げる台詞",
        voice_design_text_value=lambda p: user_persona_voice_text(p),
        voice_design_text_placeholder="生成する音声で読み上げる台詞",
        voice_design_empty_text_message="読み上げる台詞を入力してください。",
        voice_design_caption_placeholder="例: 落ち着いた低めの声、柔らかく自然な話し方",
        voice_design_reference_label="現在のペルソナ音声を参照音声として使う",
        voice_design_job_label=lambda _: "ユーザーペルソナボイスデザイン",
        voice_design_save_message="生成音声をペルソナ音声に保存しました",
        voice_design_filename=lambda index: f"persona-voice-design-{index}.wav",
        voice_caption_generation_enabled=False,
        tts_no_api_message="使用できるTTSがありません。音声生成APIを設定してください。",
        tts_text_value=lambda p: user_persona_voice_text(p),
        tts_caption_placeholder="例: 落ち着いた低めの声、柔らかく自然な話し方",
        tts_caption_generation_enabled=False,
        tts_default_voice_id=lambda p: user_persona_tts_id(p.id),
        tts_synthesis_label=lambda _: "ユーザーペルソナ読み上げ",
        tts_error_timeout=10000,
        gen_server_model_settings_style=True,
        voice_api_options=persona_voice_api_options,
        selected_voice_api_value=persona_selected_voice_api_value,
        parse_voice_api_value=persona_parse_voice_api_value,
        selected_tts_endpoint=persona_selected_tts_endpoint,
        is_gen_server_voice_api=persona_is_gen_server_voice_api,
        assigned_gen_server_voice_endpoints=persona_assigned_gen_server_voice_endpoints,
    )


def render_user_persona_image_section(persona: UserPersona, ctx, refresh_media) -> None:
    with ui.card().classes("w-full"):
        with ui.row().classes("items-center gap-2 mb-2"):
            ui.icon("image").style("color: #6E8EBF;")
            ui.label("顔画像").classes("text-base font-semibold")

        image = persona.media.primary_image()
        image_path = ctx.user_personas.media_path(image.path) if image else None
        if image and image_path:
            ui.image(image_path).props("fit=cover").classes("w-full rounded-md").style(
                "aspect-ratio: 1 / 1; background: var(--cs-surface-soft);"
            )
            if image.original_name:
                ui.label(image.original_name).classes("text-xs text-grey-6 break-all")
        else:
            with (
                ui.element("div")
                .classes(
                    "w-full rounded-md border border-dashed border-grey-4 bg-grey-2 flex items-center justify-center"
                )
                .style("aspect-ratio: 1 / 1;")
            ):
                ui.icon("person").classes("text-5xl text-grey-5")

        async def _on_image_upload(e) -> bool:
            try:
                saved = await ctx.user_personas.save_user_persona_image(persona.id, e.file)
                ui.notify("画像を保存しました", type="positive")
                await refresh_media(saved)
                return True
            except Exception as err:
                ui.notify(f"画像の保存に失敗しました: {err}", type="negative")
                return False

        ui.button(
            "画像を差し替え" if image else "画像をアップロード",
            icon="upload",
            on_click=lambda: open_user_persona_upload_dialog(
                title="画像をアップロード",
                label="画像ファイルをドロップ / 選択",
                accept="image/*",
                max_file_size=20 * 1024 * 1024,
                on_upload=_on_image_upload,
            ),
        ).props("outline color=primary").classes("w-full")
        ui.button(
            "画像生成",
            icon="auto_awesome",
            on_click=lambda: open_user_persona_image_generation_dialog(persona, ctx, refresh_media),
        ).props("outline color=secondary").classes("w-full")
        if image and image_path:
            ui.button(
                "顔範囲を設定",
                icon="crop_free",
                on_click=lambda: open_user_persona_face_rect_dialog(
                    persona,
                    ctx,
                    image,
                    image_path,
                    refresh_media,
                ),
            ).props("outline color=primary").classes("w-full")


def open_user_persona_face_rect_dialog(
    persona: UserPersona,
    ctx,
    image: CharacterImageAsset,
    image_path,
    refresh_media,
) -> None:
    _open_image_rect_dialog(
        persona,
        ctx,
        persona.id,
        image=image,
        image_path=image_path,
        rect=image.face_rect,
        refresh_fn=refresh_media,
        rect_kind="face",
        title="顔範囲を設定",
        tooltip="ドラッグで顔範囲を指定",
        too_small_message="顔範囲が小さすぎます",
        saved_message="顔範囲を保存しました",
        color="#6E9572",
        actions=user_persona_media_actions(persona, ctx),
    )


def render_user_persona_voice_section(persona: UserPersona, ctx, refresh_media, refresh_fn) -> None:
    with ui.card().classes("w-full"):
        with ui.row().classes("items-center gap-2 mb-2"):
            ui.icon("graphic_eq").style("color: #6E9572;")
            ui.label("音声").classes("text-base font-semibold")

        voice = persona.media.primary_voice()
        voice_path = ctx.user_personas.media_path(voice.path) if voice else None
        if voice and voice_path:
            ui.audio(voice_path).classes("w-full")
            if voice.original_name:
                ui.label(voice.original_name).classes("text-xs text-grey-6 break-all")
        else:
            with ui.element("div").classes(
                "w-full min-h-[88px] rounded-md border border-dashed border-grey-4 "
                "bg-grey-2 flex items-center justify-center"
            ):
                ui.icon("volume_up").classes("text-4xl text-grey-5")

        async def _on_voice_upload(e) -> bool:
            try:
                saved = await ctx.user_personas.save_user_persona_voice(persona.id, e.file)
                ui.notify("音声を保存しました", type="positive")
                await refresh_media(saved)
                return True
            except Exception as err:
                ui.notify(f"音声の保存に失敗しました: {err}", type="negative")
                return False

        ui.button(
            "音声を差し替え" if voice else "音声をアップロード",
            icon="upload",
            on_click=lambda: open_user_persona_upload_dialog(
                title="音声をアップロード",
                label="音声ファイルをドロップ / 選択",
                accept="audio/*",
                max_file_size=50 * 1024 * 1024,
                on_upload=_on_voice_upload,
            ),
        ).props("outline color=primary").classes("w-full")
        ui.button(
            "ボイスデザイン",
            icon="record_voice_over",
            on_click=lambda: open_user_persona_voice_design_dialog(persona, ctx, refresh_media),
        ).props("outline color=secondary").classes("w-full")
        render_user_persona_tts_controls(persona, ctx, voice, voice_path, refresh_media, refresh_fn)


def open_user_persona_upload_dialog(
    *,
    title: str,
    label: str,
    accept: str,
    max_file_size: int,
    on_upload,
) -> None:
    _open_media_upload_dialog(
        title=title,
        label=label,
        accept=accept,
        max_file_size=max_file_size,
        on_upload=on_upload,
    )


def open_user_persona_image_generation_dialog(persona: UserPersona, ctx, refresh_media) -> None:
    open_simple_image_generation_dialog(
        persona,
        ctx,
        refresh_media,
        user_persona_media_actions(persona, ctx),
        title="ペルソナ画像生成",
        profile_prompt=lambda profile: profile.prompt or user_persona_image_prompt(persona),
        save_message="生成画像をペルソナ画像に保存しました",
        job_label="ユーザーペルソナ画像生成",
    )


def open_user_persona_voice_design_dialog(persona: UserPersona, ctx, refresh_media) -> None:
    _open_voice_design_dialog(
        persona,
        ctx,
        persona.id,
        refresh_media,
        user_persona_media_actions(persona, ctx),
    )


def render_user_persona_tts_controls(persona: UserPersona, ctx, voice, voice_path, refresh_media, refresh_fn) -> None:
    _render_tts_controls(
        persona,
        ctx,
        persona.id,
        voice,
        voice_path,
        refresh_media,
        user_persona_media_actions(persona, ctx),
    )


def user_persona_image_prompt(persona: UserPersona) -> str:
    parts = [
        "portrait",
        "one person",
        persona.name,
        persona.description,
    ]
    return ", ".join(part.strip() for part in parts if part and part.strip())


def user_persona_voice_text(persona: UserPersona) -> str:
    name = persona.name.strip() or "ユーザー"
    return f"こんにちは。{name}です。"


def user_persona_tts_id(persona_id: str) -> str:
    return f"user-persona-{persona_id}"


def user_persona_generated_image_filename(image: object, index: int) -> str:
    filename = str(getattr(image, "filename", "") or "").strip()
    if filename:
        return filename
    return f"user-persona-image-{index}.png"


def persona_voice_api_options(endpoints, gen_server_config) -> dict[str, str]:
    return voice_api_options(
        endpoints,
        gen_server_config,
        gen_server_api_value=PERSONA_GEN_SERVER_VOICE_API,
        tts_api_prefix=PERSONA_TTS_API_PREFIX,
    )


def persona_selected_voice_api_value(settings: CharacterTTSSettings, endpoints, has_gen_server: bool) -> str:
    return selected_voice_api_value(
        settings,
        endpoints,
        has_gen_server,
        gen_server_api_value=PERSONA_GEN_SERVER_VOICE_API,
        tts_api_prefix=PERSONA_TTS_API_PREFIX,
    )


def persona_parse_voice_api_value(value: str | None) -> tuple[str, str]:
    return parse_voice_api_value(
        value,
        gen_server_api_value=PERSONA_GEN_SERVER_VOICE_API,
        tts_api_prefix=PERSONA_TTS_API_PREFIX,
    )


def persona_selected_tts_endpoint(value: str | None, endpoint_by_id: dict):
    return selected_tts_endpoint(
        value,
        endpoint_by_id,
        gen_server_api_value=PERSONA_GEN_SERVER_VOICE_API,
        tts_api_prefix=PERSONA_TTS_API_PREFIX,
    )


def persona_is_gen_server_voice_api(value: str | None) -> bool:
    return is_gen_server_voice_api(
        value,
        gen_server_api_value=PERSONA_GEN_SERVER_VOICE_API,
        tts_api_prefix=PERSONA_TTS_API_PREFIX,
    )


def persona_normalize_gen_server_tts_mode(value: str | None) -> str:
    return normalize_gen_server_tts_mode(value)


def persona_gen_server_backend_mode(tts_mode: str) -> str:
    return gen_server_backend_mode(tts_mode)


def persona_assigned_gen_server_voice_endpoints(gen_server_config) -> list:
    return assigned_gen_server_voice_endpoints(gen_server_config)
