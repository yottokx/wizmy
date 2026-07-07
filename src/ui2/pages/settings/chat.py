"""
/v2/settings — チャット(チャットモード / ユーザーペルソナ)。

旧 `ui/pages/settings/chat_modes.py` / `user_personas.py` の機能を P3 スキンで再実装。
ペルソナのメディア(画像・音声・TTS)は `media_ui.py` の共有レンダラを使う。
"""

from __future__ import annotations

import uuid

from nicegui import ui

from ....core.chat.schemas import ChatMode, UserPersona
from ....core.chat.templates import TemplateError, validate_chat_mode_templates
from ....core.tts.options import PERSONA_GEN_SERVER_VOICE_API_VALUE
from ...components.portrait import media_url as portrait_media_url
from ...media_ui import (
    MediaTarget,
    render_image_now,
    render_image_workspace,
    render_tts_settings,
    render_voice_design,
    render_voice_now,
)
from .common import (
    DIALOG_CARD_STYLE,
    chip_button,
    confirm_dialog,
    enable_drag_sort,
    entry_card,
    moved_order,
    notify_order_saved,
    p3_button,
    settings_dialog,
    short_text,
)

# ---------------------------------------------------------------------------
# チャットモード
# ---------------------------------------------------------------------------


def open_chat_modes_dialog(ctx, on_change) -> None:
    dlg, body = settings_dialog("チャットモード")
    with body:
        container = ui.column().classes("w-full gap-3")
        with ui.row().classes("w-full"):
            p3_button("チャットモードを追加", lambda: _open_mode_edit(None, ctx, _refresh), classes="btn primary")

    async def _reorder(e) -> None:
        ordered = moved_order(
            [mode.id for mode in ctx.api_config.get_chat_modes()],
            e.args["old_index"],
            e.args["new_index"],
        )
        if ordered is None:
            return
        ctx.api_config.reorder_chat_modes(ordered)
        notify_order_saved()
        on_change()

    enable_drag_sort(container, _reorder)

    def _refresh() -> None:
        modes = ctx.api_config.get_chat_modes()
        container.clear()
        with container:
            if not modes:
                ui.label("チャットモードが登録されていません").classes("note")
            for mode in modes:
                _mode_card(mode)
        on_change()

    def _mode_card(mode: ChatMode) -> None:
        with entry_card():
            with ui.row().classes("items-start gap-3 w-full"):
                with ui.column().classes("flex-1 gap-1 min-w-0"):
                    ui.label(mode.name).classes("text-sm font-semibold")
                    ui.label("前提テンプレート").classes("text-xs font-semibold").style("color: var(--muted);")
                    ui.label(short_text(mode.premise_template)).classes("text-xs").style(
                        "white-space: pre-wrap; overflow-wrap: anywhere; color: var(--muted);"
                    )
                    ui.label("シチュエーションテンプレート").classes("text-xs font-semibold").style(
                        "color: var(--muted);"
                    )
                    ui.label(short_text(mode.situation_template)).classes("text-xs").style(
                        "white-space: pre-wrap; overflow-wrap: anywhere; color: var(--muted);"
                    )
                with ui.row().classes("gap-2"):
                    chip_button("編集", lambda m=mode: _open_mode_edit(m, ctx, _refresh))
                    chip_button("削除", lambda m=mode: _confirm_delete(m))

    def _confirm_delete(mode: ChatMode) -> None:
        async def _do() -> None:
            if len(ctx.api_config.get_chat_modes()) <= 1:
                ui.notify("チャットモードは少なくとも1件必要です", type="warning")
                return
            ctx.api_config.delete_chat_mode(mode.id)
            ui.notify("削除しました", type="positive")
            _refresh()

        confirm_dialog(
            f"「{mode.name}」を削除しますか?",
            "このチャットモードは新しいチャット開始時に選べなくなります。",
            _do,
        )

    _refresh()
    dlg.open()


def _open_mode_edit(mode: ChatMode | None, ctx, refresh_fn) -> None:
    is_edit = mode is not None
    with ui.dialog() as dlg, ui.card().classes("w-full max-w-2xl").style(DIALOG_CARD_STYLE):
        ui.label("チャットモードを編集" if is_edit else "チャットモードを追加").classes(
            "text-base font-semibold mb-2"
        )
        name_input = ui.input(label="モード名", value=mode.name if mode else "").props("outlined dense").classes(
            "w-full p3-fd"
        )
        ui.label("使用できる変数: {{ character_name }}, {{ user_persona_name }}").classes("text-xs").style(
            "color: var(--muted);"
        )
        premise_input = ui.textarea(
            label="前提テンプレート", value=mode.premise_template if mode else ""
        ).props("outlined rows=4").classes("w-full p3-fd")
        situation_input = ui.textarea(
            label="シチュエーションテンプレート", value=mode.situation_template if mode else ""
        ).props("outlined rows=3").classes("w-full p3-fd")

        async def _save() -> None:
            name = str(name_input.value or "").strip()
            premise = str(premise_input.value or "").strip()
            situation = str(situation_input.value or "").strip()
            if not name or not premise or not situation:
                ui.notify("モード名、前提、シチュエーションを入力してください", type="negative")
                return
            updated = ChatMode(
                id=mode.id if mode else str(uuid.uuid4())[:8],
                name=name,
                premise_template=premise,
                situation_template=situation,
            )
            try:
                validate_chat_mode_templates(updated)
            except TemplateError as err:
                ui.notify(f"テンプレートを確認してください: {err}", type="negative", timeout=8000)
                return
            if is_edit:
                ctx.api_config.update_chat_mode(updated)
            else:
                ctx.api_config.create_chat_mode(updated)
            ui.notify("保存しました", type="positive")
            dlg.close()
            refresh_fn()

        with ui.row().classes("justify-end gap-2 mt-3 w-full"):
            p3_button("キャンセル", dlg.close, classes="btn quiet")
            p3_button("保存", _save, classes="btn primary")
    dlg.open()


# ---------------------------------------------------------------------------
# ユーザーペルソナ
# ---------------------------------------------------------------------------


def _persona_voice_text(persona: UserPersona) -> str:
    name = persona.name.strip() or "ユーザー"
    return f"こんにちは。{name}です。"


def _persona_image_prompt(persona: UserPersona) -> str:
    parts = ["portrait", "one person", persona.name, persona.description]
    return ", ".join(part.strip() for part in parts if part and part.strip())


def _persona_media_target(ctx, state: dict, refresh_list) -> MediaTarget:
    def _persona() -> UserPersona:
        return state["persona"]

    def _apply(saved) -> None:
        if saved is not None:
            state["persona"] = saved

    persona_id = _persona().id

    async def _update_face_rect(rect, **kwargs):
        return ctx.user_personas.update_user_persona_face_rect(persona_id, rect, **kwargs)

    async def _update_tts(settings):
        return ctx.user_personas.update_user_persona_tts_settings(persona_id, settings)

    return MediaTarget(
        name=_persona().display_name or "ユーザー",
        tts_id=f"user-persona-{persona_id}",
        result_url="/v2/settings",
        scope_prefix=f"user_persona:{persona_id}",
        metadata={"persona_id": persona_id},
        sheet=_persona,
        apply_saved=_apply,
        media_path=ctx.user_personas.media_path,
        media_url=portrait_media_url,
        save_image=lambda upload: ctx.user_personas.save_user_persona_image(persona_id, upload),
        save_image_bytes=lambda image_bytes, **kwargs: ctx.user_personas.save_user_persona_image_bytes(
            persona_id, image_bytes, **kwargs
        ),
        save_image_preview=lambda image_bytes, **kwargs: ctx.user_personas.save_user_persona_image_preview(
            persona_id, image_bytes, **kwargs
        ),
        save_voice=lambda upload: ctx.user_personas.save_user_persona_voice(persona_id, upload),
        save_voice_bytes=lambda audio_bytes, **kwargs: ctx.user_personas.save_user_persona_voice_bytes(
            persona_id, audio_bytes, **kwargs
        ),
        update_tts_settings=_update_tts,
        update_face_rect=_update_face_rect,
        save_tts_preview=lambda audio_bytes, **kwargs: ctx.user_personas.save_user_persona_tts_preview(
            persona_id, audio_bytes, **kwargs
        ),
        gen_server_voice_api_value=PERSONA_GEN_SERVER_VOICE_API_VALUE,
        caption_generation_enabled=False,
        voice_design_text_label="読み上げる台詞",
        voice_design_text=lambda p: _persona_voice_text(p),
        voice_design_caption_placeholder="例: 落ち着いた低めの声、柔らかく自然な話し方",
        voice_design_reference_label="現在のペルソナ音声を参照音声として使う",
        voice_design_filename=lambda index: f"persona-voice-design-{index}.wav",
        voice_design_save_message="生成音声をペルソナ音声に保存しました",
        tts_text=lambda p: _persona_voice_text(p),
        default_voice_id=lambda p: f"user-persona-{persona_id}",
        job_label_prefix="ユーザーペルソナ",
    )


def open_user_personas_dialog(ctx, on_change) -> None:
    dlg, body = settings_dialog("ユーザーペルソナ")
    with body:
        container = ui.column().classes("w-full gap-3")
        with ui.row().classes("w-full"):
            p3_button(
                "ユーザーペルソナを追加",
                lambda: _open_persona_edit(None, ctx, _refresh),
                classes="btn primary",
            )

    async def _reorder(e) -> None:
        ordered = moved_order(
            [persona.id for persona in ctx.user_personas.get_user_personas()],
            e.args["old_index"],
            e.args["new_index"],
        )
        if ordered is None:
            return
        ctx.user_personas.reorder_user_personas(ordered)
        notify_order_saved()
        on_change()

    enable_drag_sort(container, _reorder)

    def _refresh() -> None:
        personas = ctx.user_personas.get_user_personas()
        container.clear()
        with container:
            if not personas:
                ui.label("ユーザーペルソナが登録されていません。チャット開始前に追加してください。").classes(
                    "note"
                )
            for persona in personas:
                _persona_card(persona)
        on_change()

    def _persona_card(persona: UserPersona) -> None:
        image = persona.media.primary_image()
        voice = persona.media.primary_voice()
        with entry_card():
            with ui.row().classes("items-start gap-3 w-full flex-wrap"):
                image_url = portrait_media_url(image.path) if image is not None else None
                if image_url is not None:
                    ui.element("img").props(f'src="{image_url}"').style(
                        "width: 56px; height: 56px; border-radius: 12px; object-fit: cover;"
                        " border: 1px solid var(--line-2); flex: none;"
                    )
                with ui.column().classes("flex-1 gap-1 min-w-0"):
                    ui.label(persona.display_name).classes("text-sm font-semibold")
                    if persona.persona_name.strip():
                        ui.label(f"名前: {persona.name}").classes("text-xs").style("color: var(--muted);")
                    ui.label(short_text(persona.description)).classes("text-xs").style(
                        "white-space: pre-wrap; overflow-wrap: anywhere; color: var(--muted);"
                    )
                    ui.label(
                        f"画像: {'設定済み' if image else '未設定'} / 音声: {'設定済み' if voice else '未設定'}"
                    ).classes("text-xs").style("color: var(--muted);")
                with ui.row().classes("gap-2"):
                    chip_button("画像・音声", lambda p=persona: _open_persona_media(p))
                    chip_button("編集", lambda p=persona: _open_persona_edit(p, ctx, _refresh))
                    chip_button("削除", lambda p=persona: _confirm_delete(p))

    def _open_persona_media(persona: UserPersona) -> None:
        open_persona_media_dialog(ctx, persona, _refresh)

    def _confirm_delete(persona: UserPersona) -> None:
        async def _do() -> None:
            ctx.user_personas.delete_user_persona(persona.id)
            ui.notify("削除しました", type="positive")
            _refresh()

        confirm_dialog(
            f"「{persona.display_name}」を削除しますか?",
            "このユーザーペルソナは新しいチャット開始時に選べなくなります。",
            _do,
        )

    _refresh()
    dlg.open()


def _open_persona_edit(persona: UserPersona | None, ctx, refresh_fn) -> None:
    is_edit = persona is not None
    with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg").style(DIALOG_CARD_STYLE):
        ui.label("ユーザーペルソナを編集" if is_edit else "ユーザーペルソナを追加").classes(
            "text-base font-semibold mb-2"
        )
        name_input = ui.input(
            label="名前(会話内で使う名前)", value=persona.name if persona else ""
        ).props("outlined dense").classes("w-full p3-fd")
        persona_name_input = (
            ui.input(
                label="ペルソナ名(表示用・任意)",
                value=persona.persona_name if persona else "",
                placeholder="同じ名前の設定を区別するための名前",
            )
            .props("outlined dense clearable")
            .classes("w-full p3-fd")
        )
        description_input = ui.textarea(label="設定", value=persona.description if persona else "").props(
            "outlined rows=5"
        ).classes("w-full p3-fd")

        async def _save() -> None:
            name = str(name_input.value or "").strip()
            persona_name = str(persona_name_input.value or "").strip()
            description = str(description_input.value or "").strip()
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
            refresh_fn()

        with ui.row().classes("justify-end gap-2 mt-3 w-full"):
            p3_button("キャンセル", dlg.close, classes="btn quiet")
            p3_button("保存", _save, classes="btn primary").mark("ui2-settings-persona-save")
    dlg.open()


def open_persona_media_dialog(ctx, persona: UserPersona, on_change) -> None:
    """ペルソナの画像・音声・TTS(共有レンダラの組み合わせ)。"""
    state = {"persona": persona}
    target = _persona_media_target(ctx, state, on_change)
    dlg, body = settings_dialog(f"{persona.display_name} の画像・音声", max_width="1000px")
    with body:
        image_container = ui.column().classes("w-full gap-2")
        voice_container = ui.column().classes("w-full gap-2")

    def _refresh() -> None:
        latest = ctx.user_personas.get_user_persona(state["persona"].id)
        if latest is not None:
            state["persona"] = latest
        image_container.clear()
        with image_container:
            with ui.element("div").classes("state-lbl"):
                ui.html("画像")
            render_image_now(ctx, target, _refresh)
            with ui.row().classes("w-full"):
                chip_button("画像を生成(シンプル版)", _open_image_generation)
        voice_container.clear()
        with voice_container:
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

    def _open_image_generation() -> None:
        gen_dlg, gen_body = settings_dialog("ペルソナ画像生成", max_width="1100px")
        with gen_body:
            render_image_workspace(
                ctx,
                target,
                _refresh,
                simple=True,
                default_prompt=_persona_image_prompt(state["persona"]),
            )
        gen_dlg.open()

    _refresh()
    dlg.open()


def chat_modes_summary(ctx) -> tuple[str, str]:
    modes = ctx.api_config.get_chat_modes()
    if not modes:
        return "未登録", "muted"
    return f"{len(modes)}件", "ok"


def personas_summary(ctx) -> tuple[str, str]:
    personas = ctx.user_personas.get_user_personas()
    if not personas:
        return "未登録", "muted"
    return f"{len(personas)}件", "ok"
