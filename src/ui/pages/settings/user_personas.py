from __future__ import annotations

import uuid

from nicegui import ui
from nicegui.events import MouseEventArguments

from ....core.chat.schemas import UserPersona
from ....core.character.schemas import (
    CHARACTER_GEN_SERVER_TTS_MODE_CLONE,
    CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3,
    CHARACTER_TTS_API_DEFAULT,
    CHARACTER_TTS_API_GEN_SERVER,
    CharacterImageAsset,
    CharacterTTSSettings,
    FaceRect,
)
from ....core.gen_server.schemas import (
    GEN_SERVER_DEFAULT_FIELDS,
    GEN_SERVER_MODE_IRODORI_VOICE_CLONE,
    GEN_SERVER_MODE_IRODORI_VOICE_DESIGN,
    GEN_SERVER_MODE_SDXL_IMAGE,
    clean_gen_server_mode_defaults,
)
from ....core.image_generation.schemas import (
    IMAGE_GENERATION_PARAMETER_FIELDS,
    ImageGenerationProfile,
    image_generation_profile_values,
)
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
from ....core.tts.schemas import TTS_PROVIDER_IRODORI_SERVER
from ....services.ai_jobs import AIJobStatus
from ....services.image_generation import ImageGenerationError
from ....services.tts import TTSServiceError
from ...chat.media import cropped_background_style, read_image_size
from .common import (
    build_profile_param_control,
    enable_drag_sort,
    fetch_gen_server_model_id_from_endpoint,
    moved_order,
    notify_order_saved,
    read_gen_server_default_value,
    short_text,
)
from .media_generation import fetch_gen_server_model_id


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
    async def _save(rect: FaceRect, image_width: int, image_height: int) -> None:
        saved = ctx.user_personas.update_user_persona_face_rect(
            persona.id,
            rect,
            image_width=image_width,
            image_height=image_height,
        )
        await refresh_media(saved)

    open_user_persona_image_rect_dialog(
        image=image,
        image_path=image_path,
        rect=image.face_rect,
        title="顔範囲を設定",
        tooltip="ドラッグで顔範囲を指定",
        too_small_message="顔範囲が小さすぎます",
        saved_message="顔範囲を保存しました",
        color="#6E9572",
        save_rect=_save,
    )


def open_user_persona_image_rect_dialog(
    *,
    image: CharacterImageAsset,
    image_path,
    rect: FaceRect,
    title: str,
    tooltip: str,
    too_small_message: str,
    saved_message: str,
    color: str,
    save_rect,
) -> None:
    size = user_persona_image_size(image, image_path)
    state = {
        "width": size[0] if size else image.width,
        "height": size[1] if size else image.height,
        "start": None,
        "dragging": False,
        "draft": rect.model_copy(),
    }

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-3xl"):
        with ui.row().classes("items-center justify-between w-full mb-2"):
            ui.label(title).classes("text-base font-semibold")
            ui.button(icon="close", on_click=dlg.close).props("flat round dense")

        editor = (
            ui.interactive_image(
                image_path,
                content=user_persona_rect_overlay(state["draft"], state["width"], state["height"], color),
                size=size,
                events=["mousedown", "mousemove", "mouseup", "mouseleave"],
                sanitize=False,
            )
            .classes("rounded-md overflow-hidden border bg-grey-2 cursor-crosshair")
            .style(user_persona_image_frame_style(size))
        )
        editor.tooltip(tooltip)

        def _on_loaded(e) -> None:
            args = e.args or {}
            state["width"] = int(args.get("width") or image.width or 0)
            state["height"] = int(args.get("height") or image.height or 0)
            if state["width"] > 0 and state["height"] > 0:
                image.width = state["width"]
                image.height = state["height"]
                editor.style(user_persona_image_frame_style((state["width"], state["height"])))
            editor.set_content(user_persona_rect_overlay(state["draft"], state["width"], state["height"], color))

        async def _on_mouse(e: MouseEventArguments) -> None:
            width = int(state["width"] or 0)
            height = int(state["height"] or 0)
            if width <= 0 or height <= 0:
                return

            x = min(max(float(e.image_x), 0.0), float(width))
            y = min(max(float(e.image_y), 0.0), float(height))

            if e.type == "mousedown" and e.button == 0:
                state["start"] = (x, y)
                state["dragging"] = True
                state["draft"] = user_persona_rect_from_points((x, y), (x, y), width, height)
                editor.set_content(user_persona_rect_overlay(state["draft"], width, height, color))
                return

            if e.type == "mousemove" and state["dragging"]:
                start = state["start"]
                if start is None:
                    return
                state["draft"] = user_persona_rect_from_points(start, (x, y), width, height)
                editor.set_content(user_persona_rect_overlay(state["draft"], width, height, color))
                return

            if e.type == "mouseup" and state["dragging"]:
                state["dragging"] = False
                start = state["start"]
                state["start"] = None
                if start is None:
                    return
                state["draft"] = user_persona_rect_from_points(start, (x, y), width, height)
                editor.set_content(user_persona_rect_overlay(state["draft"], width, height, color))
                return

            if e.type == "mouseleave" and state["dragging"]:
                state["dragging"] = False
                state["start"] = None
                editor.set_content(user_persona_rect_overlay(state["draft"], width, height, color))

        async def _save() -> None:
            width = int(state["width"] or 0)
            height = int(state["height"] or 0)
            rect = state["draft"]
            if width <= 0 or height <= 0:
                ui.notify("画像サイズを取得できませんでした", type="warning")
                return
            if rect.width < 0.02 or rect.height < 0.02:
                ui.notify(too_small_message, type="warning")
                return
            await save_rect(rect, width, height)
            ui.notify(saved_message, type="positive")
            dlg.close()

        def _reset() -> None:
            state["draft"] = FaceRect()
            editor.set_content(user_persona_rect_overlay(state["draft"], state["width"], state["height"], color))

        editor.on("loaded", _on_loaded)
        editor.on_mouse(_on_mouse)

        with ui.row().classes("justify-end gap-2 mt-3"):
            ui.button("リセット", icon="restart_alt", on_click=_reset).props("flat")
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("保存", icon="save", on_click=_save).props("color=primary unelevated")

    dlg.open()


def user_persona_image_size(image: CharacterImageAsset, image_path) -> tuple[int, int] | None:
    if image.width > 0 and image.height > 0:
        return image.width, image.height
    if image_path is not None:
        return read_image_size(image_path)
    return None


def user_persona_image_frame_style(size: tuple[int, int] | None) -> str:
    max_height = "calc(100vh - 220px)"
    base = f"margin-left: auto; margin-right: auto; max-height: {max_height};"
    if size is None:
        return f"{base} aspect-ratio: 1 / 1; width: min(100%, {max_height});"
    width, height = size
    return f"{base} aspect-ratio: {width} / {height}; width: min(100%, calc({max_height} * {width} / {height}));"


def user_persona_rect_from_points(
    start: tuple[float, float],
    end: tuple[float, float],
    width: int,
    height: int,
) -> FaceRect:
    left = min(start[0], end[0])
    top = min(start[1], end[1])
    right = max(start[0], end[0])
    bottom = max(start[1], end[1])
    return FaceRect(
        x=left / width,
        y=top / height,
        width=(right - left) / width,
        height=(bottom - top) / height,
    )


def user_persona_rect_overlay(rect: FaceRect, width: int, height: int, color: str) -> str:
    if width <= 0 or height <= 0:
        return ""
    x = rect.x * width
    y = rect.y * height
    w = rect.width * width
    h = rect.height * height
    if w <= 0 or h <= 0:
        return ""
    stroke = max(2.0, min(width, height) * 0.006)
    handle = stroke * 2.5
    return f"""
        <rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}"
              fill="{color}" fill-opacity="0.15" stroke="{color}"
              stroke-width="{stroke:.2f}" vector-effect="non-scaling-stroke" />
        <circle cx="{x:.2f}" cy="{y:.2f}" r="{handle:.2f}" fill="{color}" />
        <circle cx="{x + w:.2f}" cy="{y:.2f}" r="{handle:.2f}" fill="{color}" />
        <circle cx="{x:.2f}" cy="{y + h:.2f}" r="{handle:.2f}" fill="{color}" />
        <circle cx="{x + w:.2f}" cy="{y + h:.2f}" r="{handle:.2f}" fill="{color}" />
    """


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
    with ui.dialog() as dlg, ui.card().classes("w-full max-w-md"):
        with ui.row().classes("w-full items-center justify-between gap-2"):
            ui.label(title).classes("text-base font-semibold")
            ui.button(icon="close", on_click=dlg.close).props("flat round dense")

        async def _handle_upload(e) -> None:
            if await on_upload(e):
                dlg.close()

        ui.upload(
            label=label,
            on_upload=_handle_upload,
            auto_upload=True,
            max_file_size=max_file_size,
        ).props(f"accept={accept} flat bordered").classes("w-full")

    dlg.open()


def open_user_persona_image_generation_dialog(persona: UserPersona, ctx, refresh_media) -> None:
    profiles = ctx.api_config.get_image_generation_profiles()
    if not profiles:
        ui.notify("設定で画像生成プロファイルを追加してください。", type="warning")
        return

    config = ctx.api_config.get_image_generation_config()
    selected_profile = ctx.api_config.get_image_generation_profile(config.default_profile_id) or profiles[0]
    controls: dict[str, object] = {}
    generated: list[dict[str, object]] = []

    def _profile_prompt(profile: ImageGenerationProfile) -> str:
        return profile.prompt or user_persona_image_prompt(persona)

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-5xl").style("width: min(980px, 96vw);"):
        with ui.row().classes("w-full items-center justify-between gap-2"):
            ui.label("ペルソナ画像生成").classes("text-base font-semibold")
            status = ui.label("").classes("text-xs text-grey-6")
            ui.button(icon="close", on_click=dlg.close).props("flat round dense")

        profile_options = {profile.id: profile.name or "無題のプロファイル" for profile in profiles}
        with ui.row().classes("w-full gap-4 items-start flex-col lg:flex-row"):
            with ui.column().classes("w-full lg:w-[420px] gap-3 shrink-0"):
                profile_select = (
                    ui.select(
                        options=profile_options,
                        value=selected_profile.id,
                        label="画像生成プロファイル",
                    )
                    .props("outlined dense")
                    .classes("w-full")
                )
                prompt_input = (
                    ui.textarea(
                        label="プロンプト",
                        value=_profile_prompt(selected_profile),
                    )
                    .props("outlined rows=5")
                    .classes("w-full")
                )
                negative_input = (
                    ui.textarea(
                        label="ネガティブプロンプト",
                        value=selected_profile.negative_prompt,
                    )
                    .props("outlined rows=4")
                    .classes("w-full")
                )
                with ui.row().classes("w-full items-end gap-2"):
                    model_input = (
                        ui.input(
                            label="モデルID",
                            value=selected_profile.model_id,
                        )
                        .props("outlined dense clearable")
                        .classes("flex-1")
                    )
                    ui.button(
                        icon="refresh",
                        on_click=lambda: fetch_user_persona_image_model_id(profile_select, model_input, ctx),
                    ).props("flat round").tooltip("モデルIDを取得")

                with ui.expansion("詳細パラメータ", icon="tune").props("dense").classes("w-full"):
                    with ui.grid(columns=2).classes("w-full gap-3"):
                        initial_values = image_generation_profile_values(selected_profile)
                        for key, spec in IMAGE_GENERATION_PARAMETER_FIELDS.items():
                            controls[key] = build_profile_param_control(
                                key,
                                spec,
                                initial_values.get(key, spec.get("default")),
                            )

            with ui.column().classes("w-full lg:flex-1 min-w-0 gap-2"):
                preview_container = ui.column().classes("w-full gap-2")

        def _apply_profile(profile: ImageGenerationProfile) -> None:
            values = image_generation_profile_values(profile)
            prompt_input.set_value(profile.prompt or user_persona_image_prompt(persona))
            negative_input.set_value(str(values.get("negative_prompt") or ""))
            model_input.set_value(str(values.get("model_id") or ""))
            for key, spec in IMAGE_GENERATION_PARAMETER_FIELDS.items():
                if key in controls:
                    controls[key].set_value(values.get(key, spec.get("default")))

        def _on_profile_change() -> None:
            profile = ctx.api_config.get_image_generation_profile(profile_select.value or "")
            if profile is not None:
                _apply_profile(profile)

        def _read_params() -> dict[str, object]:
            params = {
                "prompt": (prompt_input.value or "").strip(),
                "negative_prompt": (negative_input.value or "").strip(),
                "model_id": (model_input.value or "").strip(),
            }
            params.update(
                {
                    key: read_gen_server_default_value(spec, controls[key])
                    for key, spec in IMAGE_GENERATION_PARAMETER_FIELDS.items()
                }
            )
            return params

        def _render_generated() -> None:
            preview_container.clear()
            with preview_container:
                if not generated:
                    with (
                        ui.element("div")
                        .classes("w-full rounded-md border border-dashed flex items-center justify-center")
                        .style("min-height: 320px; background: var(--cs-surface-soft); border-color: var(--cs-border);")
                    ):
                        ui.label("生成するとここに画像が表示されます").classes("text-sm text-grey-6")
                    return
                for index, item in enumerate(generated, start=1):
                    image = item["image"]
                    image_path = item["path"]
                    with (
                        ui.element("div")
                        .classes("w-full rounded-md border p-2")
                        .style("background: var(--cs-surface); border-color: var(--cs-border);")
                    ):
                        with ui.row().classes("w-full items-center gap-2"):
                            label = f"候補 {index}"
                            size_label = user_persona_generated_image_size_label(image)
                            if size_label:
                                label = f"{label} / {size_label}"
                            ui.label(label).classes("text-sm font-semibold")
                            ui.space()
                            ui.button(
                                "この画像を保存",
                                icon="save",
                                on_click=lambda image=image, index=index: _save_image(image, index),
                            ).props("outline color=primary")
                        ui.image(image_path).props("fit=contain").classes("w-full rounded-md").style(
                            "height: min(62vh, 620px); min-height: 300px; background: var(--cs-surface-soft);"
                        )

        async def _generate() -> None:
            if not (prompt_input.value or "").strip():
                ui.notify("プロンプトを入力してください。", type="warning")
                return
            generate_btn.disable()
            status.set_text("生成中...")
            try:

                def _save_previews(images: list[object], job) -> dict[str, object]:
                    items: list[dict[str, object]] = []
                    for image in images:
                        preview_path = ctx.user_personas.save_user_persona_image_preview(
                            persona.id,
                            image.data,
                            filename=user_persona_generated_image_filename(
                                image,
                                len(generated) + len(items) + 1,
                            ),
                            content_type=image.content_type,
                            replace_existing=False,
                        )
                        item = {"image": image, "path": preview_path}
                        generated.append(item)
                        items.append(item)
                    return {
                        "result_url": "/settings",
                        "preview_paths": [str(item["path"]) for item in items],
                        "image_count": len(items),
                    }

                job = ctx.image_generation.start_sdxl_job(
                    profile_id=profile_select.value or "",
                    gen_server_params=_read_params(),
                    label="ユーザーペルソナ画像生成",
                    scope=f"user_persona:{persona.id}:image",
                    metadata={"persona_id": persona.id},
                    result_handler=_save_previews,
                )
                finished = await ctx.ai_jobs.wait(job.id)
                if finished.status == AIJobStatus.CANCELLED:
                    status.set_text("")
                    ui.notify("画像生成を停止しました", type="info")
                    return
                if finished.status != AIJobStatus.SUCCEEDED:
                    raise ImageGenerationError(finished.error_message or "画像生成に失敗しました。")
                _render_generated()
                status.set_text("")
                ui.notify("画像を生成しました", type="positive")
            except ImageGenerationError as err:
                status.set_text("")
                ui.notify(f"画像生成に失敗しました: {err}", type="negative", timeout=10000)
            except Exception as err:
                status.set_text("")
                ui.notify(f"画像生成に失敗しました: {err}", type="negative", timeout=10000)
            finally:
                generate_btn.enable()

        async def _save_image(image: object, index: int) -> None:
            try:
                saved = await ctx.user_personas.save_user_persona_image_bytes(
                    persona.id,
                    image.data,
                    filename=user_persona_generated_image_filename(image, index),
                    content_type=image.content_type,
                    width=image.width,
                    height=image.height,
                )
                ui.notify("生成画像をペルソナ画像に保存しました", type="positive")
                dlg.close()
                await refresh_media(saved)
            except Exception as err:
                ui.notify(f"画像の保存に失敗しました: {err}", type="negative")

        profile_select.on_value_change(lambda _: _on_profile_change())
        with ui.row().classes("justify-end gap-2 mt-3"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            generate_btn = ui.button("生成", icon="auto_awesome", on_click=_generate).props("color=primary unelevated")
        _render_generated()

    dlg.open()


def open_user_persona_voice_design_dialog(persona: UserPersona, ctx, refresh_media) -> None:
    if ctx.tts.resolve_gen_server_voice_design_endpoint(raise_on_missing=False) is None:
        ui.notify("設定でボイスデザインにWizmy-Gen-Serverを割り当ててください。", type="warning")
        return

    mode = GEN_SERVER_MODE_IRODORI_VOICE_DESIGN
    fields = GEN_SERVER_DEFAULT_FIELDS.get(mode, {})
    defaults = ctx.api_config.get_gen_server_config().defaults_for_mode(mode)
    controls: dict[str, object] = {}
    generated: list[dict[str, object]] = []
    current_voice = persona.media.primary_voice()
    current_voice_path = ctx.user_personas.media_path(current_voice.path) if current_voice else None

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-2xl"):
        with ui.row().classes("w-full items-center justify-between gap-2"):
            ui.label("ペルソナボイスデザイン").classes("text-base font-semibold")
            ui.button(icon="close", on_click=dlg.close).props("flat round dense")

        text_input = (
            ui.textarea(
                label="読み上げる台詞",
                value=user_persona_voice_text(persona),
                placeholder="生成する音声で読み上げる台詞",
            )
            .props("outlined rows=4")
            .classes("w-full")
        )
        caption_input = (
            ui.textarea(
                label="キャプション",
                value=persona.media.tts.voice_caption,
                placeholder="例: 落ち着いた低めの声、柔らかく自然な話し方",
            )
            .props("outlined rows=4")
            .classes("w-full")
        )
        reference_checkbox = None
        if current_voice_path is not None:
            reference_checkbox = ui.checkbox(
                "現在のペルソナ音声を参照音声として使う",
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
                ui.notify("読み上げる台詞を入力してください。", type="warning")
                return
            if not caption:
                ui.notify("キャプションを入力してください。", type="warning")
                return
            generate_btn.disable()
            status.set_text("生成中...")
            try:
                params = _read_params()

                def _save_preview(audio: bytes, job) -> dict[str, str]:
                    preview_path = ctx.user_personas.save_user_persona_tts_preview(
                        persona.id,
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
                    label="ユーザーペルソナボイスデザイン",
                    scope=f"user_persona:{persona.id}:tts",
                    metadata={"persona_id": persona.id},
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
                saved = await ctx.user_personas.save_user_persona_voice_bytes(
                    persona.id,
                    audio,
                    filename=f"persona-voice-design-{index}.wav",
                    content_type="audio/wav",
                )
                settings = saved.media.tts.model_copy(
                    update={
                        "api_type": CHARACTER_TTS_API_GEN_SERVER,
                        "gen_server_tts_mode": CHARACTER_GEN_SERVER_TTS_MODE_CLONE,
                        "voice_caption": str(item.get("caption") or "").strip(),
                        "gen_server_params": clean_gen_server_mode_defaults(
                            GEN_SERVER_MODE_IRODORI_VOICE_CLONE,
                            saved.media.tts.gen_server_params,
                        ),
                    }
                )
                saved = ctx.user_personas.update_user_persona_tts_settings(persona.id, settings)
                ui.notify("生成音声をペルソナ音声に保存しました", type="positive")
                dlg.close()
                await refresh_media(saved)
            except Exception as err:
                ui.notify(f"音声の保存に失敗しました: {err}", type="negative")

        with ui.row().classes("justify-end gap-2 mt-3"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            generate_btn = ui.button("生成", icon="auto_awesome", on_click=_generate).props("color=primary unelevated")

    dlg.open()


def render_user_persona_tts_controls(persona: UserPersona, ctx, voice, voice_path, refresh_media, refresh_fn) -> None:
    ui.separator().classes("my-3")
    endpoints = ctx.tts.get_endpoints()
    gen_server_config = ctx.api_config.get_gen_server_config()
    has_gen_server = bool(persona_assigned_gen_server_voice_endpoints(gen_server_config))
    if not endpoints and not has_gen_server:
        ui.label("使用できるTTSがありません。音声生成APIを設定してください。").classes("text-sm text-grey-6")
        return

    current_settings = persona.media.tts
    endpoint_by_id = {endpoint.id: endpoint for endpoint in endpoints}
    endpoint_select = (
        ui.select(
            options=persona_voice_api_options(endpoints, gen_server_config),
            value=persona_selected_voice_api_value(current_settings, endpoints, has_gen_server),
            label="使用API",
        )
        .props("outlined")
        .classes("w-full")
    )
    selected_endpoint = persona_selected_tts_endpoint(endpoint_select.value, endpoint_by_id)

    voice_id_input = None
    if selected_endpoint is not None and selected_endpoint.provider == TTS_PROVIDER_IRODORI_SERVER:
        default_voice_id = user_persona_tts_id(persona.id)
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
        if voice_path is not None:
            with ui.row().classes("gap-2 w-full"):
                register_btn = (
                    ui.button("Irodoriに登録", icon="cloud_upload").props("outline color=primary").classes("flex-1")
                )
                delete_btn = (
                    ui.button("Irodoriから削除", icon="delete_outline")
                    .props("outline color=negative")
                    .classes("flex-1")
                )
        else:
            register_btn = None
            delete_btn = None
    else:
        register_btn = None
        delete_btn = None

    mode_select = None
    voice_caption_input = None
    gen_server_tts_mode_state = {"value": persona_normalize_gen_server_tts_mode(current_settings.gen_server_tts_mode)}
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
                    label="キャプション",
                    value=current_settings.voice_caption,
                    placeholder="例: 落ち着いた低めの声、柔らかく自然な話し方",
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
                _save_tts_settings,
                persona_gen_server_backend_mode(gen_server_tts_mode_state["value"]),
            ),
        ).props("outline color=primary").classes("w-full")

    tts_text = (
        ui.textarea(
            label="読み上げテキスト",
            value=user_persona_voice_text(persona),
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

    def _current_tts_settings() -> CharacterTTSSettings:
        api_type, endpoint_id = persona_parse_voice_api_value(endpoint_select.value)
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
        saved = ctx.user_personas.update_user_persona_tts_settings(persona.id, settings)
        if notify:
            ui.notify("TTS設定を保存しました", type="positive")
            await refresh_media(saved)
        return settings

    async def _on_endpoint_change(_) -> None:
        await _save_tts_settings(notify=False)
        await refresh_media()

    async def _on_gen_server_mode_change(_) -> None:
        if mode_select is None:
            return
        gen_server_tts_mode_state["value"] = persona_normalize_gen_server_tts_mode(mode_select.value)
        gen_server_params_state["value"] = clean_gen_server_mode_defaults(
            persona_gen_server_backend_mode(gen_server_tts_mode_state["value"]),
            gen_server_params_state["value"],
        )
        await _save_tts_settings(notify=False)
        await refresh_media()

    async def _register_tts_voice() -> None:
        if voice_path is None or voice is None:
            ui.notify("先に音声をアップロードしてください", type="warning")
            return
        settings = await _save_tts_settings(notify=False)
        register_btn.disable()
        try:
            await ctx.tts.register_voice(
                user_persona_tts_id(persona.id),
                voice_path,
                endpoint_id=settings.endpoint_id,
                voice_id=settings.voice_id,
                filename=voice.original_name,
                content_type=voice.content_type,
            )
            ui.notify("Irodori-TTS-Serverに登録しました", type="positive")
        except Exception as err:
            ui.notify(f"登録に失敗しました: {err}", type="negative")
        finally:
            register_btn.enable()

    async def _delete_tts_voice() -> None:
        settings = await _save_tts_settings(notify=False)
        delete_btn.disable()
        try:
            deleted = await ctx.tts.delete_voice(
                user_persona_tts_id(persona.id),
                endpoint_id=settings.endpoint_id,
                voice_id=settings.voice_id,
            )
            if deleted:
                ui.notify("Irodori-TTS-Serverから削除しました", type="positive")
            else:
                ui.notify("Irodori-TTS-Serverに登録されていません", type="info")
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
                preview_path = ctx.user_personas.save_user_persona_tts_preview(persona.id, audio)
                return {
                    "result_url": "/settings",
                    "preview_path": str(preview_path),
                }

            job = ctx.tts.start_synthesize_job(
                user_persona_tts_id(persona.id),
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
                label="ユーザーペルソナ読み上げ",
                scope=f"user_persona:{persona.id}:tts",
                metadata={"persona_id": persona.id},
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
    save_settings_btn.on("click", lambda: _save_tts_settings())
    if register_btn is not None:
        register_btn.on("click", _register_tts_voice)
    if delete_btn is not None:
        delete_btn.on("click", _delete_tts_voice)
    synth_btn.on("click", _synthesize_tts)


def open_user_persona_gen_server_tts_params_dialog(ctx, params_state: dict, save_settings, mode: str) -> None:
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

        with ui.grid(columns=2).classes("w-full gap-3"):
            for key, spec in fields.items():
                value = current.get(key, spec.get("default"))
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
                            on_click=lambda model_input=model_input: fetch_gen_server_model_id(mode, model_input, ctx),
                        ).props("flat round").tooltip("モデルIDを取得")
                    controls[key] = model_input
                else:
                    controls[key] = build_profile_param_control(key, spec, value)

        def _read_params() -> dict:
            return {key: read_gen_server_default_value(spec, controls[key]) for key, spec in fields.items()}

        async def _clear_overrides() -> None:
            params_state["value"] = {}
            await save_settings(notify=False)
            ui.notify("固有パラメータをクリアしました", type="positive")
            dlg.close()

        async def _save() -> None:
            values = _read_params()
            params_state["value"] = clean_gen_server_mode_defaults(
                mode,
                {key: value for key, value in values.items() if value != defaults.get(key, fields[key].get("default"))},
            )
            await save_settings(notify=False)
            ui.notify("パラメータを保存しました", type="positive")
            dlg.close()

        with ui.row().classes("justify-end gap-2 mt-3"):
            ui.button("固有設定をクリア", icon="restart_alt", on_click=_clear_overrides).props("flat")
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("保存", icon="save", on_click=_save).props("color=primary unelevated")

    dlg.open()


async def fetch_user_persona_image_model_id(profile_select, model_input, ctx) -> None:
    profile = ctx.api_config.get_image_generation_profile(profile_select.value or "")
    if profile is None:
        ui.notify("画像生成プロファイルを選択してください。", type="warning")
        return
    if not profile.endpoint_id:
        ui.notify("画像生成プロファイルのAPI接続先を設定してください。", type="warning")
        return
    await fetch_gen_server_model_id_from_endpoint(
        profile.endpoint_id,
        GEN_SERVER_MODE_SDXL_IMAGE,
        model_input,
        ctx,
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


def user_persona_generated_image_size_label(image: object) -> str:
    width = int(getattr(image, "width", 0) or 0)
    height = int(getattr(image, "height", 0) or 0)
    return f"{width}x{height}" if width and height else ""


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
