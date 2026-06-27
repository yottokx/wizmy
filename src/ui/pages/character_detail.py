"""
キャラクター詳細・編集ページ。

Markdown シートの表示・直接編集、タグ編集、メディア参照、
修正/関連キャラ生成への送信、削除機能を提供する。
"""

from __future__ import annotations

import html
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from nicegui import app, ui
from nicegui.events import MouseEventArguments

from ...app_context import get_context
from ...core.character.schemas import (
    CHARACTER_GEN_SERVER_TTS_MODE_CLONE,
    CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3,
    CHARACTER_TTS_API_DEFAULT,
    CHARACTER_TTS_API_GEN_SERVER,
    CHARACTER_TTS_API_TTS,
    CharacterImageAsset,
    CharacterSheet,
    CharacterTTSSettings,
    FaceRect,
)
from ...core.gen_server.schemas import (
    GEN_SERVER_DEFAULT_FIELDS,
    GEN_SERVER_MODE_IRODORI_VOICE_CLONE,
    GEN_SERVER_MODE_IRODORI_VOICE_DESIGN,
    GEN_SERVER_MODE_LABELS,
    GEN_SERVER_MODE_SDXL_IMAGE,
    clean_gen_server_mode_defaults,
)
from ...core.image_generation.schemas import (
    IMAGE_GENERATION_PARAMETER_FIELDS,
    ImageGenerationProfile,
    image_generation_profile_values,
)
from ...core.llm.factory import create_llm
from ...core.tts.schemas import TTS_PROVIDER_IRODORI_GRADIO, TTS_PROVIDER_IRODORI_SERVER
from ...services.ai_jobs import AIJobStatus
from ...services.character_generation import parse_markdown_to_sheet
from ...services.danbooru_prompt import DanbooruPromptServiceError
from ...services.image_generation import ImageGenerationError
from ...services.tts import TTSServiceError
from ..layout import page_layout
from ..state import get_vault_password


_TTS_API_PREFIX = "tts:"
_GEN_SERVER_VOICE_CLONE_API = "gen_server:irodori_voice_clone"
_GEN_SERVER_TTS_MODE_OPTIONS = {
    CHARACTER_GEN_SERVER_TTS_MODE_CLONE: "ボイスクローン",
    CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3: "VoiceDesign v3",
}
_GENERATED_PROMPT_RE = re.compile(
    r"<(?:span|strong)\b(?=[^>]*(?:data-wizmy-generated-prompt|wizmy-generated-prompt))[^>]*>"
    r".*?</(?:span|strong)>\s*",
    re.IGNORECASE | re.DOTALL,
)
_GENERATED_NEGATIVE_PROMPT_RE = re.compile(
    r"<(?:span|strong)\b(?=[^>]*(?:data-wizmy-generated-negative-prompt|wizmy-generated-negative-prompt))[^>]*>"
    r".*?</(?:span|strong)>\s*",
    re.IGNORECASE | re.DOTALL,
)
_VOICE_CAPTION_LABEL_RE = re.compile(
    r"^(?:voice\s*design\s*)?(?:caption|キャプション|ボイスキャプション|音声キャプション)\s*[:：]\s*",
    re.IGNORECASE,
)
_VOICE_IMAGE_SECTION_RE = re.compile(r"(?ms)^## 声のイメージ\s*\n.*?(?=^## |\Z)")


@ui.page("/characters/{character_id}")
async def character_detail_page(character_id: str) -> None:
    ctx = get_context()
    sheet = await ctx.characters.get(character_id)

    if sheet is None:
        with page_layout("キャラクターが見つかりません"):
            ui.label("指定されたキャラクターは存在しません。").classes("text-grey-6")
            ui.button("一覧に戻る", on_click=lambda: ui.navigate.to("/characters")).props("flat color=primary")
        return

    with page_layout(sheet.name):
        with ui.row().classes("items-center gap-2 mb-4 flex-wrap"):
            ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/characters")).props("flat round")
            ui.label(sheet.name).classes("text-2xl font-bold flex-1")

            favorite_btn = ui.button(
                icon="star" if sheet.is_favorite else "star_border",
                on_click=lambda: _toggle_favorite(),
            ).props("flat round").style(
                f"color: {'#D9A441' if sheet.is_favorite else '#AAA8A0'};"
            )
            with favorite_btn:
                favorite_tooltip = ui.tooltip(
                    "お気に入りを解除" if sheet.is_favorite else "お気に入りに追加"
                )

            with ui.button_group().props("flat"):
                ui.button(
                    "チャット",
                    icon="forum",
                    on_click=lambda: ui.navigate.to(f"/characters/{character_id}/chat"),
                ).props("flat color=primary size=sm").tooltip("このキャラクターとチャットする")
                ui.button(
                    "修正に送る",
                    icon="edit",
                    on_click=lambda: _send_to_generation("modify"),
                ).props("flat color=primary size=sm").tooltip("このシートをベースに修正生成する")
                ui.button(
                    "関連キャラ作成",
                    icon="person_add",
                    on_click=lambda: _send_to_generation("related"),
                ).props("flat color=secondary size=sm").tooltip("このシートをベースに関連キャラを生成する")

            ui.button(
                icon="download",
                on_click=lambda: ui.download(sheet.raw_markdown.encode("utf-8"), f"{sheet.name}.md"),
            ).props("flat round").tooltip("Markdownをダウンロード")
            ui.button(
                icon="content_copy",
                on_click=lambda: _copy_to_clipboard(),
            ).props("flat round").tooltip("Markdownをコピー")
            ui.button(
                icon="delete",
                on_click=lambda: _confirm_delete(),
            ).props("flat round color=negative").tooltip("削除")

        def _send_to_generation(mode: str) -> None:
            app.storage.user["gen_mode"] = mode
            app.storage.user["gen_char_id"] = character_id
            ui.navigate.to("/")

        async def _toggle_favorite() -> None:
            saved = await ctx.characters.set_favorite(character_id, not sheet.is_favorite)
            sheet.is_favorite = saved.is_favorite
            favorite_btn.set_icon("star" if sheet.is_favorite else "star_border")
            favorite_btn.style(f"color: {'#D9A441' if sheet.is_favorite else '#AAA8A0'};")
            favorite_tooltip.set_text(
                "お気に入りを解除" if sheet.is_favorite else "お気に入りに追加"
            )
            ui.notify(
                "お気に入りに追加しました" if sheet.is_favorite else "お気に入りを解除しました",
                type="positive",
            )

        with ui.card().classes("w-full mb-4"):
            with ui.row().classes("gap-6 flex-wrap"):
                for label, value in sheet.to_display_dict().items():
                    if value:
                        with ui.column().classes("gap-0"):
                            ui.label(label).classes("text-xs text-grey-6")
                            ui.label(value).classes("text-sm font-medium")

            if sheet.tags:
                with ui.row().classes("gap-2 mt-3 flex-wrap"):
                    for tag in sheet.tags:
                        ui.badge(tag).props("outline color=primary")

        with ui.row().classes("items-center gap-2 mb-4"):
            ui.label("タグ:").classes("text-sm font-medium")
            tags_row = ui.row().classes("gap-2 flex-wrap items-center")
            with tags_row:
                _render_tags(sheet, tags_row, ctx)

        if sheet.generation_meta.model_id:
            with ui.expansion("生成情報", icon="info").props("dense").classes("w-full mb-4"):
                meta = sheet.generation_meta
                with ui.grid(columns=2).classes("gap-x-4 gap-y-1 text-sm"):
                    ui.label("プロファイル:").classes("text-grey-6")
                    ui.label(meta.llm_profile_name or "-")
                    ui.label("モデル:").classes("text-grey-6")
                    ui.label(meta.model_id or "-")
                    ui.label("Temperature:").classes("text-grey-6")
                    ui.label(str(meta.temperature) if meta.temperature is not None else "N/A (reasoning)")
                    ui.label("品質:").classes("text-grey-6")
                    _quality_label(meta.quality_status)
                    ui.label("ツール呼び出し:").classes("text-grey-6")
                    ui.label(f"{meta.tool_count} 件")

        edit_mode = {"active": False}

        with ui.row().classes("w-full items-start gap-4 flex-col lg:flex-row"):
            with ui.column().classes("w-full lg:flex-1 min-w-0"):
                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center justify-between mb-2"):
                        ui.label("キャラクターシート").classes("text-base font-semibold")
                        with ui.row().classes("gap-1"):
                            toggle_raw_btn = ui.button("Markdown表示", on_click=lambda: _toggle_raw()).props(
                                "flat size=sm"
                            )
                            edit_btn = ui.button("編集", icon="edit", on_click=lambda: _enter_edit()).props(
                                "flat size=sm color=primary"
                            )
                            save_edit_btn = ui.button("保存", icon="save", on_click=lambda: _save_edit()).props(
                                "unelevated size=sm color=primary"
                            ).classes("hidden")
                            cancel_edit_btn = ui.button("キャンセル", on_click=lambda: _cancel_edit()).props(
                                "flat size=sm"
                            ).classes("hidden")

                    sheet_container = ui.element("div").classes("w-full")
                    edit_area: dict[str, Any] = {"ref": None}
                    view_mode = {"raw": False}

                    with sheet_container:
                        ui.markdown(sheet.raw_markdown).classes("prose prose-sm max-w-none")

            media_panel = ui.column().classes("w-full lg:w-[360px] gap-4 shrink-0")

        def _refresh_media_panel() -> None:
            media_panel.clear()
            with media_panel:
                _render_media_panel(sheet, ctx, character_id, _refresh_media_panel)

        _refresh_media_panel()

        def _toggle_raw() -> None:
            if edit_mode["active"]:
                return
            view_mode["raw"] = not view_mode["raw"]
            sheet_container.clear()
            with sheet_container:
                if view_mode["raw"]:
                    ui.code(sheet.raw_markdown, language="markdown").classes("w-full text-xs")
                    toggle_raw_btn.set_text("レンダリング表示")
                else:
                    ui.markdown(sheet.raw_markdown).classes("prose prose-sm max-w-none")
                    toggle_raw_btn.set_text("Markdown表示")

        def _enter_edit() -> None:
            edit_mode["active"] = True
            sheet_container.clear()
            with sheet_container:
                ta = ui.textarea(value=sheet.raw_markdown).classes("w-full font-mono text-sm").props(
                    "rows=30 outlined"
                )
                edit_area["ref"] = ta
                with ui.row().classes("justify-end gap-2 mt-2"):
                    ui.button("キャンセル", on_click=lambda: _cancel_edit()).props("flat size=sm")
                    ui.button("保存", icon="save", on_click=lambda: _save_edit()).props(
                        "unelevated size=sm color=primary"
                    )
            toggle_raw_btn.classes("hidden")
            edit_btn.classes("hidden")
            save_edit_btn.classes(remove="hidden")
            cancel_edit_btn.classes(remove="hidden")

        async def _save_edit() -> None:
            ta = edit_area["ref"]
            if ta is None:
                return
            new_md = ta.value.strip()
            if not new_md:
                ui.notify("シートが空です", type="warning")
                return
            updated = parse_markdown_to_sheet(new_md, sheet.id)
            updated.tags = sheet.tags
            updated.media = sheet.media
            updated.is_favorite = sheet.is_favorite
            updated.generation_meta = sheet.generation_meta
            updated.created_at = sheet.created_at
            saved = await ctx.characters.save(updated)
            sheet.raw_markdown = new_md
            sheet.name = saved.name
            sheet.tags = saved.tags
            sheet.media = saved.media
            ui.notify(f"「{saved.name}」を保存しました", type="positive")
            _cancel_edit()

        def _cancel_edit() -> None:
            edit_mode["active"] = False
            sheet_container.clear()
            with sheet_container:
                if view_mode["raw"]:
                    ui.code(sheet.raw_markdown, language="markdown").classes("w-full text-xs")
                else:
                    ui.markdown(sheet.raw_markdown).classes("prose prose-sm max-w-none")
            toggle_raw_btn.classes(remove="hidden")
            edit_btn.classes(remove="hidden")
            save_edit_btn.classes("hidden")
            cancel_edit_btn.classes("hidden")

        def _copy_to_clipboard() -> None:
            ui.run_javascript(f"navigator.clipboard.writeText({repr(sheet.raw_markdown)})")
            ui.notify("コピーしました", type="positive")

        def _confirm_delete() -> None:
            with ui.dialog() as dlg, ui.card():
                ui.label(f"「{sheet.name}」を削除しますか？").classes("text-base font-medium mb-2")
                ui.label("この操作は取り消せません。").classes("text-sm text-grey-6")
                with ui.row().classes("justify-end gap-2 mt-4"):
                    ui.button("キャンセル", on_click=dlg.close).props("flat")
                    ui.button("削除", on_click=lambda: _do_delete(dlg)).props("color=negative unelevated")
            dlg.open()

        async def _do_delete(dlg) -> None:
            await ctx.characters.delete(character_id)
            ui.notify(f"「{sheet.name}」を削除しました", type="positive")
            dlg.close()
            ui.navigate.to("/characters")


def _render_media_panel(sheet, ctx, character_id: str, refresh_fn) -> None:
    with ui.card().classes("w-full"):
        with ui.row().classes("items-center gap-2 mb-2"):
            ui.icon("image").style("color: #6E9572;")
            ui.label("画像").classes("text-base font-semibold")

        image = sheet.media.primary_image()
        image_path = ctx.characters.media_path(image.path) if image else None
        if image and image_path:
            _render_image_editor(sheet, ctx, character_id, image, image_path, refresh_fn)
            if image.original_name:
                ui.label(image.original_name).classes("text-xs text-grey-6 break-all")
        else:
            with ui.element("div").classes(
                "w-full aspect-[4/3] rounded-md border border-dashed border-grey-4 "
                "bg-grey-2 flex items-center justify-center"
            ):
                ui.icon("image").classes("text-4xl text-grey-5")

        async def _on_image_upload(e) -> bool:
            try:
                saved = await ctx.characters.save_image(character_id, e.file)
                sheet.media = saved.media
                ui.notify("画像を保存しました", type="positive")
                refresh_fn()
                return True
            except Exception as err:
                ui.notify(f"画像の保存に失敗しました: {err}", type="negative")
                return False

        ui.button(
            "画像を差し替え" if image else "画像をアップロード",
            icon="upload",
            on_click=lambda: _open_media_upload_dialog(
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
            on_click=lambda: _open_image_generation_dialog(sheet, ctx, character_id, refresh_fn),
        ).props("outline color=secondary").classes("w-full")

    with ui.card().classes("w-full"):
        with ui.row().classes("items-center gap-2 mb-2"):
            ui.icon("graphic_eq").style("color: #6E9572;")
            ui.label("音声").classes("text-base font-semibold")

        voice = sheet.media.primary_voice()
        voice_path = ctx.characters.media_path(voice.path) if voice else None
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
                saved = await ctx.characters.save_voice(character_id, e.file)
                sheet.media = saved.media
                ui.notify("音声を保存しました", type="positive")
                refresh_fn()
                return True
            except Exception as err:
                ui.notify(f"音声の保存に失敗しました: {err}", type="negative")
                return False

        ui.button(
            "音声を差し替え" if voice else "音声をアップロード",
            icon="upload",
            on_click=lambda: _open_media_upload_dialog(
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
            on_click=lambda: _open_voice_design_dialog(sheet, ctx, character_id, refresh_fn),
        ).props("outline color=secondary").classes("w-full")

        if voice and voice_path:
            _render_tts_controls(sheet, ctx, character_id, voice, voice_path, refresh_fn)
            return


def _open_media_upload_dialog(
    *,
    title: str,
    label: str,
    accept: str,
    max_file_size: int,
    on_upload: Callable[[Any], Awaitable[bool]],
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
        ).props(f"accept={accept} flat bordered").classes("w-full cs-media-upload")

    dlg.open()


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
            f"- {rel.name}: {rel.description}".strip()
            for rel in sheet.relationships
            if (rel.name or rel.description)
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
    if not profile.model_id:
        raise RuntimeError("LLMプロファイルのモデルIDが未設定です。")

    endpoint = ctx.api_config.get_endpoint(profile.endpoint_id)
    if endpoint is None:
        raise RuntimeError("LLMプロファイルのエンドポイントが見つかりません。")

    api_key = ctx.api_config.get_api_key(profile.endpoint_id, get_vault_password())
    if ctx.api_config.is_api_key_locked(profile.endpoint_id, api_key):
        raise RuntimeError("APIキーボルトをロック解除してください。")
    return create_llm(profile, endpoint, api_key)


async def _generate_voice_caption_from_sheet(sheet: CharacterSheet, ctx) -> str:
    source = _voice_caption_sheet_source(sheet)
    if not source:
        raise RuntimeError("キャラクターシート情報が不足しています。")

    llm = _create_voice_caption_llm(ctx)
    response = await llm.ainvoke([
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
    ])
    caption = _clean_voice_caption(_message_content_text(response))
    if not caption:
        raise RuntimeError("キャプションを生成できませんでした。")
    return caption


def _open_image_generation_dialog(sheet, ctx, character_id: str, refresh_fn) -> None:
    profiles = ctx.api_config.get_image_generation_profiles()
    if not profiles:
        ui.notify("設定で画像生成プロファイルを追加してください。", type="warning")
        return

    config = ctx.api_config.get_image_generation_config()
    selected_profile = (
        ctx.api_config.get_image_generation_profile(config.default_profile_id)
        or profiles[0]
    )
    llm_profiles = ctx.api_config.get_llm_profiles()
    app_llm_config = ctx.api_config.get_app_llm_config()
    selected_llm_profile = (
        ctx.api_config.get_llm_profile(app_llm_config.generation_profile_id)
        or (llm_profiles[0] if llm_profiles else None)
    )
    fields = {
        "model_id": {"label": "モデルID", "type": "string", "default": ""},
        **IMAGE_GENERATION_PARAMETER_FIELDS,
    }
    controls: dict[str, object] = {}
    generated: list[dict[str, object]] = []
    prompt_candidates: list[object] = []

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-6xl").style("width: min(1100px, 96vw);"):
        with ui.row().classes("w-full items-center justify-between gap-2"):
            ui.label("画像生成").classes("text-base font-semibold")
            ui.space()
            status = ui.label("").classes("text-xs text-grey-6")
            ui.button(icon="close", on_click=dlg.close).props("flat round dense")

        with ui.row().classes("w-full gap-4 items-start flex-col xl:flex-row"):
            with ui.column().classes("w-full xl:w-[440px] gap-3 shrink-0"):
                profile_options = {
                    profile.id: profile.name or "無題のプロファイル"
                    for profile in profiles
                }
                with ui.row().classes("w-full items-end gap-2"):
                    profile_select = ui.select(
                        options=profile_options,
                        value=selected_profile.id,
                        label="画像生成プロファイル",
                    ).props("outlined dense").classes("flex-1 min-w-0")
                    generate_btn = ui.button("生成", icon="auto_awesome").props(
                        "color=primary unelevated"
                    )

                llm_profile_options = {
                    profile.id: f"{profile.name} / {profile.model_id or 'モデル未設定'}"
                    for profile in llm_profiles
                }
                with ui.row().classes("w-full items-end gap-2"):
                    llm_profile_select = ui.select(
                        options=llm_profile_options,
                        value=selected_llm_profile.id if selected_llm_profile else None,
                        label="LLMプロファイル",
                    ).props("outlined dense").classes("flex-1 min-w-0")
                    prompt_generate_btn = ui.button(
                        "プロンプト生成",
                        icon="auto_awesome",
                    ).props("color=secondary unelevated")
                    prompt_spinner = ui.spinner(size="sm").classes("hidden")
                prompt_candidate_container = ui.row().classes("w-full gap-2 hidden")
                prompt_status = ui.label("").classes("text-xs text-grey-6")

                ui.label("プロンプト").classes("text-xs text-grey-7")
                prompt_input = ui.editor(
                    value=_prompt_text_to_editor_html(selected_profile.prompt),
                    placeholder="画像生成プロンプト",
                ).classes("w-full cs-image-prompt-editor")
                controls["prompt"] = prompt_input

                ui.label("ネガティブプロンプト").classes("text-xs text-grey-7")
                negative_input = ui.editor(
                    value=_prompt_text_to_editor_html(selected_profile.negative_prompt),
                    placeholder="除外したい要素",
                ).classes("w-full cs-image-prompt-editor cs-image-negative-prompt-editor")
                controls["negative_prompt"] = negative_input

                with ui.expansion("詳細パラメータ", icon="tune").props("dense").classes("w-full"):
                    with ui.grid(columns=2).classes("w-full gap-3"):
                        initial_values = image_generation_profile_values(selected_profile)
                        for key, spec in fields.items():
                            value = initial_values.get(key, spec.get("default"))
                            label = str(spec.get("label", key))
                            if key == "model_id":
                                with ui.row().classes("w-full col-span-2 items-end gap-2"):
                                    model_input = ui.input(
                                        label=label,
                                        value=value or "",
                                    ).props("outlined dense clearable").classes("flex-1")
                                    ui.button(
                                        icon="refresh",
                                        on_click=lambda: _fetch_character_image_model_id(
                                            profile_select.value or "",
                                            model_input,
                                            ctx,
                                        ),
                                    ).props("flat round").tooltip("モデルIDを取得")
                                controls[key] = model_input
                            elif spec.get("type") == "boolean":
                                controls[key] = ui.checkbox(label, value=bool(value)).classes("w-full")
                            elif spec.get("enum"):
                                options = list(spec["enum"])
                                controls[key] = ui.select(
                                    options=options,
                                    value=value if value in options else spec.get("default"),
                                    label=label,
                                ).props("outlined dense").classes("w-full")
                            elif spec.get("type") in {"integer", "number"}:
                                controls[key] = ui.number(
                                    label=label,
                                    value=value,
                                    min=spec.get("minimum"),
                                    step=spec.get("step"),
                                ).props("outlined dense").classes("w-full")
                            elif spec.get("multiline"):
                                controls[key] = ui.textarea(
                                    label=label,
                                    value=value or "",
                                ).props("outlined rows=3").classes("w-full col-span-2")
                            else:
                                controls[key] = ui.input(
                                    label=label,
                                    value=value or "",
                                ).props("outlined dense clearable").classes("w-full")

                def _apply_profile(profile: ImageGenerationProfile) -> None:
                    values = image_generation_profile_values(profile)
                    prompt_input.set_value(_prompt_text_to_editor_html(str(values.get("prompt") or "")))
                    negative_input.set_value(_prompt_text_to_editor_html(str(values.get("negative_prompt") or "")))
                    for key, spec in fields.items():
                        if key in controls:
                            controls[key].set_value(values.get(key, spec.get("default")))

                def _on_profile_change() -> None:
                    profile = ctx.api_config.get_image_generation_profile(profile_select.value or "")
                    if profile is not None:
                        _apply_profile(profile)

                profile_select.on_value_change(lambda _: _on_profile_change())

            with ui.column().classes("w-full xl:flex-1 min-w-0 gap-2"):
                with ui.row().classes("w-full items-center gap-2"):
                    ui.label("生成候補").classes("text-sm font-semibold")
                    ui.space()
                    candidate_count = ui.label("0件").classes("text-xs text-grey-6")
                candidate_tabs = ui.tabs().props(
                    "dense no-caps active-color=primary indicator-color=primary align=left"
                ).classes("w-full hidden")
                preview_container = ui.column().classes("w-full")

        def _read_params() -> dict[str, object]:
            params: dict[str, object] = {}
            for key, spec in {
                "prompt": {"type": "string", "default": ""},
                "negative_prompt": {"type": "string", "default": ""},
                **fields,
            }.items():
                if key not in controls:
                    continue
                if key in {"prompt", "negative_prompt"}:
                    params[key] = _editor_html_to_prompt(str(getattr(controls[key], "value", "") or ""))
                else:
                    params[key] = _read_gen_server_param_value(spec, controls[key])
            return params

        def _render_prompt_candidate_buttons() -> None:
            prompt_candidate_container.clear()
            if not prompt_candidates:
                prompt_candidate_container.classes("hidden")
                return
            prompt_candidate_container.classes(remove="hidden")
            with prompt_candidate_container:
                for index, candidate in enumerate(prompt_candidates, start=1):
                    label = getattr(candidate, "label", "") or f"候補 {index}"
                    button = ui.button(
                        label,
                        on_click=lambda candidate=candidate: _apply_prompt_candidate(candidate),
                    ).props("outline color=secondary no-caps").classes("min-w-[110px]")
                    button.tooltip(getattr(candidate, "prompt", ""))

        def _apply_prompt_candidate(candidate: object) -> None:
            prompt = str(getattr(candidate, "prompt", "") or "").strip()
            if not prompt:
                return
            prompt_input.set_value(
                _replace_generated_prompt_html(str(prompt_input.value or ""), prompt)
            )
            negative_prompt = ", ".join(_candidate_negative_tags(candidate))
            negative_input.set_value(
                _replace_generated_negative_prompt_html(str(negative_input.value or ""), negative_prompt)
            )

        async def _generate_prompt_candidates() -> None:
            llm_profile_id = str(llm_profile_select.value or "")
            if not llm_profile_id:
                ui.notify("LLMプロファイルを選択してください。", type="warning")
                return

            prompt_generate_btn.disable()
            prompt_spinner.classes(remove="hidden")
            prompt_status.set_text("プロンプト生成中...")
            prompt_candidates.clear()
            _render_prompt_candidate_buttons()
            try:
                job = ctx.danbooru_prompt.start_generate_candidates_job(
                    sheet,
                    llm_profile_id=llm_profile_id,
                    vault_password=get_vault_password(),
                    count=3,
                    label=f"{sheet.name or 'キャラクター'}のプロンプト候補生成",
                    scope=f"character:{character_id}:prompt",
                    metadata={"character_id": character_id},
                )
                ctx.ai_jobs.set_result_meta(job.id, {"result_url": f"/characters/{character_id}"})
                finished = await ctx.ai_jobs.wait(job.id)
                if finished.status == AIJobStatus.CANCELLED:
                    prompt_status.set_text("")
                    ui.notify("プロンプト生成を停止しました", type="info")
                    return
                if finished.status != AIJobStatus.SUCCEEDED:
                    raise DanbooruPromptServiceError(finished.error_message or "プロンプト生成に失敗しました。")
                candidates = finished.result or []
                prompt_candidates.extend(candidates)
                _render_prompt_candidate_buttons()
                prompt_status.set_text("")
                ui.notify("プロンプト候補を生成しました", type="positive")
            except DanbooruPromptServiceError as err:
                prompt_status.set_text("")
                ui.notify(str(err), type="negative", timeout=10000)
            except Exception as err:
                prompt_status.set_text("")
                ui.notify(f"プロンプト生成に失敗しました: {err}", type="negative", timeout=10000)
            finally:
                prompt_spinner.classes("hidden")
                prompt_generate_btn.enable()

        def _render_generated() -> None:
            candidate_tabs.clear()
            preview_container.clear()
            candidate_count.set_text(f"{len(generated)}件")
            with preview_container:
                if not generated:
                    candidate_tabs.classes("hidden")
                    with ui.element("div").classes(
                        "w-full rounded-md border border-dashed flex items-center justify-center"
                    ).style(
                        "min-height: 360px; background: var(--cs-surface-soft); "
                        "border-color: var(--cs-border);"
                    ):
                        ui.label("生成するとここに画像が表示されます").classes("text-sm text-grey-6")
                    return

            candidate_tabs.classes(remove="hidden")
            selected_tab = f"candidate-{len(generated)}"
            with candidate_tabs:
                for index, item in enumerate(generated, start=1):
                    image = item["image"]
                    size_label = _generated_image_size_label(image)
                    label = f"候補 {index}"
                    if size_label:
                        label = f"{label} / {size_label}"
                    ui.tab(f"candidate-{index}", label=label)
            candidate_tabs.set_value(selected_tab)

            with preview_container:
                with ui.tab_panels(candidate_tabs, value=selected_tab, animated=False).classes(
                    "w-full"
                ).style("background: transparent;"):
                    for index, item in enumerate(generated, start=1):
                        with ui.tab_panel(f"candidate-{index}").classes("p-0"):
                            _render_generated_image_panel(item, index)

        def _render_generated_image_panel(item: dict[str, object], index: int) -> None:
            image = item["image"]
            image_path = item["path"]
            size_label = _generated_image_size_label(image)
            with ui.element("div").classes("w-full rounded-md border p-2").style(
                "background: var(--cs-surface); border-color: var(--cs-border);"
            ):
                with ui.row().classes("w-full items-center gap-2"):
                    label = f"候補 {index}"
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
                    "height: min(72vh, 760px); min-height: 360px; "
                    "background: var(--cs-surface-soft);"
                )

        async def _generate() -> None:
            generate_btn.disable()
            status.set_text("生成中...")
            try:
                def _save_previews(images: list[object], job) -> dict[str, object]:
                    items: list[dict[str, object]] = []
                    for image in images:
                        preview_path = ctx.characters.save_image_preview(
                            character_id,
                            image.data,
                            filename=image.filename,
                            content_type=image.content_type,
                            replace_existing=False,
                        )
                        items.append({
                            "image": image,
                            "path": preview_path,
                        })
                    generated.extend(items)
                    return {
                        "result_url": f"/characters/{character_id}",
                        "preview_paths": [str(item["path"]) for item in items],
                        "image_count": len(items),
                    }

                job = ctx.image_generation.start_sdxl_job(
                    profile_id=profile_select.value or "",
                    gen_server_params=_read_params(),
                    label=f"{sheet.name or 'キャラクター'}の画像生成",
                    scope=f"character:{character_id}:image",
                    metadata={"character_id": character_id},
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
            if not image:
                ui.notify("先に画像を生成してください。", type="warning")
                return
            try:
                saved = await ctx.characters.save_image_bytes(
                    character_id,
                    image.data,
                    filename=_generated_image_filename(image, index),
                    content_type=image.content_type,
                    width=image.width,
                    height=image.height,
                )
                sheet.media = saved.media
                ui.notify("生成画像をキャラ画像に保存しました", type="positive")
                dlg.close()
                refresh_fn()
            except Exception as err:
                ui.notify(f"画像の保存に失敗しました: {err}", type="negative")

        prompt_generate_btn.on("click", _generate_prompt_candidates)
        generate_btn.on("click", _generate)
        _render_generated()

    dlg.open()


def _open_voice_design_dialog(sheet, ctx, character_id: str, refresh_fn) -> None:
    if ctx.tts.resolve_gen_server_voice_design_endpoint(raise_on_missing=False) is None:
        ui.notify("設定でボイスデザインにWizmy-Gen-Serverを割り当ててください。", type="warning")
        return

    mode = GEN_SERVER_MODE_IRODORI_VOICE_DESIGN
    fields = GEN_SERVER_DEFAULT_FIELDS.get(mode, {})
    defaults = ctx.api_config.get_gen_server_config().defaults_for_mode(mode)
    controls: dict[str, object] = {}
    generated: list[dict[str, object]] = []
    current_voice = sheet.media.primary_voice()
    current_voice_path = ctx.characters.media_path(current_voice.path) if current_voice else None
    initial_caption = sheet.media.tts.voice_caption

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-2xl"):
        with ui.row().classes("w-full items-center justify-between gap-2"):
            ui.label("ボイスデザイン").classes("text-base font-semibold")
            ui.button(icon="close", on_click=dlg.close).props("flat round dense")

        text_input = ui.textarea(
            label="自己紹介台詞",
            value=sheet.self_intro,
            placeholder="生成する音声で読み上げる台詞",
        ).props("outlined rows=4").classes("w-full")
        with ui.row().classes("w-full items-end gap-2 flex-wrap"):
            caption_input = ui.textarea(
                label="キャプション",
                value=initial_caption,
                placeholder="例: 明るく柔らかい少女声、少し早口で元気",
            ).props("outlined rows=4").classes("flex-1 min-w-[260px]")
            caption_generate_btn = ui.button(
                "生成",
                icon="auto_awesome",
            ).props("outline color=secondary").classes("mb-1")
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
                        controls[key] = ui.select(
                            options=options,
                            value=value if value in options else spec.get("default"),
                            label=label,
                        ).props("outlined dense").classes("w-full")
                    elif spec.get("type") in {"integer", "number"}:
                        controls[key] = ui.number(
                            label=label,
                            value=value,
                            min=spec.get("minimum"),
                            step=spec.get("step"),
                        ).props("outlined dense").classes("w-full")
                    elif key == "model_id":
                        with ui.row().classes("w-full items-end gap-2"):
                            model_input = ui.input(
                                label=label,
                                value=value or "",
                            ).props("outlined dense clearable").classes("flex-1")
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
                        controls[key] = ui.input(
                            label=label,
                            value=value or "",
                        ).props("outlined dense clearable").classes("w-full")

        status = ui.label("").classes("text-xs text-grey-6")
        with ui.element("div").classes(
            "w-full rounded-md border p-2"
        ).style(
            "max-height: 320px; overflow-y: auto; "
            "background: var(--cs-surface-soft); border-color: var(--cs-border);"
        ):
            preview_container = ui.column().classes("w-full gap-2")

        def _read_params() -> dict[str, object]:
            return {
                key: _read_gen_server_param_value(spec, controls[key])
                for key, spec in fields.items()
            }

        def _render_generated() -> None:
            preview_container.clear()
            with preview_container:
                if not generated:
                    return
                ui.label("生成候補").classes("text-sm font-semibold")
                for index, item in enumerate(generated, start=1):
                    audio_path = item["path"]
                    audio = item["audio"]
                    with ui.element("div").classes("w-full rounded-md border p-2").style(
                        "background: var(--cs-surface); border-color: var(--cs-border);"
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
                    preview_path = ctx.characters.save_tts_preview(
                        character_id,
                        audio,
                        replace_existing=False,
                    )
                    generated.append({
                        "audio": audio,
                        "path": preview_path,
                        "caption": caption,
                        "params": params,
                    })
                    return {
                        "result_url": f"/characters/{character_id}",
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
                    scope=f"character:{character_id}:tts",
                    metadata={"character_id": character_id},
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
                saved = await ctx.characters.save_voice_bytes(
                    character_id,
                    audio,
                    filename=f"voice-design-{index}.wav",
                    content_type="audio/wav",
                )
                previous_is_clone = (
                    saved.media.tts.gen_server_tts_mode == CHARACTER_GEN_SERVER_TTS_MODE_CLONE
                )
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
                updated = await ctx.characters.update_tts_settings(character_id, settings)
                sheet.media = updated.media
                ui.notify("生成音声をキャラ音声に保存しました", type="positive")
                dlg.close()
                refresh_fn()
            except Exception as err:
                ui.notify(f"音声の保存に失敗しました: {err}", type="negative")

        caption_generate_btn.on("click", _generate_caption)

        with ui.row().classes("justify-end gap-2 mt-3"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            generate_btn = ui.button("生成", icon="auto_awesome", on_click=_generate).props(
                "color=primary unelevated"
            )

    dlg.open()


def _render_tts_controls(sheet, ctx, character_id: str, voice, voice_path: Path, refresh_fn) -> None:
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

    endpoint_select = ui.select(
        options=endpoint_options,
        value=selected_value,
        label="使用API",
    ).props("outlined").classes("w-full")

    async def _change_endpoint() -> None:
        saved = await ctx.characters.update_tts_settings(character_id, _current_tts_settings())
        sheet.media = saved.media
        refresh_fn()

    async def _on_endpoint_change(_) -> None:
        await _change_endpoint()

    endpoint_select.on_value_change(_on_endpoint_change)

    voice_id_input = None
    if selected_endpoint is not None and selected_endpoint.provider == TTS_PROVIDER_IRODORI_SERVER:
        default_voice_id = ctx.tts.voice_id_for_character(character_id, current_settings.voice_id)
        voice_id_input = ui.input(
            label="Voice ID",
            value=current_settings.voice_id,
            placeholder=default_voice_id,
        ).props("outlined clearable").classes("w-full")
        ui.label(f"既定値: {default_voice_id}").classes("text-xs text-grey-6 font-mono break-all")
        with ui.row().classes("gap-2 w-full"):
            register_btn = ui.button("Irodoriに登録", icon="cloud_upload").props(
                "outline color=primary"
            ).classes("flex-1")
            delete_btn = ui.button("Irodoriから削除", icon="delete_outline").props(
                "outline color=negative"
            ).classes("flex-1")

    mode_select = None
    voice_caption_input = None
    voice_caption_generate_btn = None
    if _is_gen_server_voice_api(selected_value):
        mode_select = ui.select(
            options=_GEN_SERVER_TTS_MODE_OPTIONS,
            value=gen_server_tts_mode_state["value"],
            label="Gen-Server TTSモード",
        ).props("outlined").classes("w-full")

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
                voice_caption_input = ui.textarea(
                    label="キャプション",
                    value=voice_caption_value,
                    placeholder="例: 明るく柔らかい少女声、少し早口で元気",
                ).props("outlined rows=3").classes("flex-1 min-w-[220px]")
                voice_caption_generate_btn = ui.button(
                    "生成",
                    icon="auto_awesome",
                ).props("outline color=secondary").classes("mb-1")
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

    tts_text = ui.textarea(
        label="読み上げテキスト",
        value=sheet.self_intro,
        placeholder="読み上げるテキスト",
    ).props("outlined rows=4").classes("w-full mt-2")
    with ui.row().classes("gap-2 w-full"):
        save_settings_btn = ui.button("TTS設定を保存", icon="save").props("outline color=primary")
        synth_btn = ui.button("読み上げ", icon="play_arrow").props(
            "color=primary unelevated"
        ).classes("flex-1")
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
        saved = await ctx.characters.update_tts_settings(character_id, settings)
        sheet.media = saved.media
        if notify:
            ui.notify("TTS設定を保存しました", type="positive")
        return settings

    async def _register_tts_voice() -> None:
        settings = await _save_tts_settings(notify=False)
        register_btn.disable()
        try:
            await ctx.tts.register_voice(
                character_id,
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
                character_id,
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
                preview_path = ctx.characters.save_tts_preview(character_id, audio)
                return {
                    "result_url": f"/characters/{character_id}",
                    "preview_path": str(preview_path),
                }

            job = ctx.tts.start_synthesize_job(
                character_id,
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
                scope=f"character:{character_id}:tts",
                metadata={"character_id": character_id},
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
    options.update({
        f"{_TTS_API_PREFIX}{endpoint.id}": f"{endpoint.name} ({_tts_provider_label(endpoint.provider)})"
        for endpoint in endpoints
    })
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
        return CHARACTER_TTS_API_TTS, selected[len(_TTS_API_PREFIX):]
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
                        controls[key] = ui.select(
                            options=options,
                            value=value if value in options else spec.get("default"),
                            label=label,
                        ).props("outlined dense").classes("w-full")
                    elif spec.get("type") in {"integer", "number"}:
                        controls[key] = ui.number(
                            label=label,
                            value=value,
                            min=spec.get("minimum"),
                            step=spec.get("step"),
                        ).props("outlined dense").classes("w-full")
                    elif spec.get("multiline"):
                        controls[key] = ui.textarea(
                            label=label,
                            value=value or "",
                        ).props("outlined rows=3").classes("w-full col-span-2")
                    elif key == "model_id":
                        with ui.row().classes("w-full items-end gap-2"):
                            model_input = ui.input(
                                label=label,
                                value=value or "",
                            ).props("outlined dense clearable").classes("flex-1")
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
                        controls[key] = ui.input(
                            label=label,
                            value=value or "",
                        ).props("outlined dense clearable").classes("w-full")

        def _read_params() -> dict[str, object]:
            return {
                key: _read_gen_server_param_value(spec, controls[key])
                for key, spec in fields.items()
            }

        async def _clear_overrides() -> None:
            params_state["value"] = {}
            await save_settings(notify=False)
            ui.notify("キャラ固有パラメータをクリアしました", type="positive")
            dlg.close()

        async def _save() -> None:
            values = _read_params()
            overrides = {
                key: value
                for key, value in values.items()
                if value != defaults.get(key, fields[key].get("default"))
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


def _read_gen_server_param_value(spec: dict, control) -> object:
    value = control.value
    if spec.get("nullable") and (value is None or value == ""):
        return None

    default = spec.get("default")
    field_type = spec.get("type")
    if field_type == "boolean":
        return bool(value)
    if field_type == "integer":
        if value is None or value == "":
            return default
        return int(value)
    if field_type == "number":
        if value is None or value == "":
            return default
        return float(value)
    if field_type == "string":
        if spec.get("nullable") and not str(value or "").strip():
            return None
        return value or ""
    return value


def _prompt_text_to_editor_html(value: str) -> str:
    lines = str(value or "").splitlines()
    if not lines:
        return ""
    return "<br>".join(html.escape(line) for line in lines)


def _replace_generated_prompt_html(current_html: str, generated_prompt: str) -> str:
    return _replace_generated_editor_html(
        current_html,
        generated_prompt,
        marker="data-wizmy-generated-prompt",
        css_class="wizmy-generated-prompt",
        pattern=_GENERATED_PROMPT_RE,
    )


def _replace_generated_negative_prompt_html(current_html: str, generated_prompt: str) -> str:
    return _replace_generated_editor_html(
        current_html,
        generated_prompt,
        marker="data-wizmy-generated-negative-prompt",
        css_class="wizmy-generated-negative-prompt",
        pattern=_GENERATED_NEGATIVE_PROMPT_RE,
    )


def _replace_generated_editor_html(
    current_html: str,
    generated_prompt: str,
    *,
    marker: str,
    css_class: str,
    pattern: re.Pattern[str],
) -> str:
    body = pattern.sub("", str(current_html or ""), count=1).lstrip()
    has_existing_prompt = bool(_editor_html_to_prompt(body))
    generated_text = generated_prompt.strip()
    if not generated_text:
        return body
    if has_existing_prompt:
        generated_text = f"{generated_text}, "
    generated_html = (
        f'<span {marker}="1" class="{css_class}">'
        f"{_prompt_text_to_editor_html(generated_text)}</span>"
    )
    return f"{generated_html}{body}"


def _remove_generated_prompt_html(value: str) -> str:
    return _GENERATED_PROMPT_RE.sub("", str(value or ""), count=1)


def _editor_html_to_prompt(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(?:p|div|li|h[1-6])>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return " ".join(lines).strip()


def _candidate_negative_tags(candidate: object) -> list[str]:
    tags: list[str] = []
    negative_prompt = str(getattr(candidate, "negative_prompt", "") or "")
    tags.extend(part.strip() for part in negative_prompt.split(",") if part.strip())
    negative_tags = getattr(candidate, "negative_tags", []) or []
    if isinstance(negative_tags, list):
        tags.extend(_editor_prompt_tag(str(tag).strip()) for tag in negative_tags if str(tag).strip())
    return _dedupe_prompt_parts(tags)


def _dedupe_prompt_parts(parts: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for part in parts:
        cleaned = part.strip()
        key = _prompt_part_key(cleaned)
        if not cleaned or key in seen:
            continue
        result.append(cleaned)
        seen.add(key)
    return result


def _prompt_part_key(value: str) -> str:
    return re.sub(r"\s+", "_", value.strip().lower())


def _editor_prompt_tag(value: str) -> str:
    if value in {"o_o", "x_x", "u_u"}:
        return value
    return value.replace("_", " ")


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


async def _fetch_character_image_model_id(profile_id: str, model_input, ctx) -> None:
    profile = ctx.api_config.get_image_generation_profile(profile_id)
    if profile is None:
        ui.notify("画像生成プロファイルを選択してください。", type="warning")
        return
    if not profile.endpoint_id:
        ui.notify("画像生成プロファイルのAPI接続先を設定してください。", type="warning")
        return
    try:
        models = await ctx.api_config.fetch_gen_server_models(
            profile.endpoint_id,
            GEN_SERVER_MODE_SDXL_IMAGE,
        )
    except Exception as err:
        ui.notify(f"モデルIDを取得できませんでした: {err}", type="negative")
        return

    if not models:
        ui.notify("SDXL画像生成で利用できるモデルが見つかりませんでした。", type="warning")
        return

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg"):
        ui.label("SDXL画像生成のモデルID").classes("text-base font-semibold mb-2")
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


def _generated_image_size_label(image: object) -> str:
    width = int(getattr(image, "width", 0) or 0)
    height = int(getattr(image, "height", 0) or 0)
    if width > 0 and height > 0:
        return f"{width}x{height}"
    return ""


def _generated_image_filename(image: object, index: int) -> str:
    suffix = Path(str(getattr(image, "filename", ""))).suffix or ".png"
    return f"generated-image-{index}{suffix}"


def _image_size(image: CharacterImageAsset, image_path: Path | None = None) -> tuple[int, int] | None:
    if image.width > 0 and image.height > 0:
        return image.width, image.height
    if image_path is not None:
        return _read_image_size(image_path)
    return None


def _image_frame_style(size: tuple[int, int] | None) -> str:
    max_height = "calc(100vh - 220px)"
    base = f"margin-left: auto; margin-right: auto; max-height: {max_height};"
    if size is None:
        return f"{base} aspect-ratio: 1 / 1; width: min(100%, {max_height});"
    width, height = size
    return f"{base} aspect-ratio: {width} / {height}; width: min(100%, calc({max_height} * {width} / {height}));"


def _read_image_size(path: Path) -> tuple[int, int] | None:
    try:
        with path.open("rb") as f:
            head = f.read(32)
            if head.startswith(b"\x89PNG\r\n\x1a\n") and len(head) >= 24:
                return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
            if head[:6] in (b"GIF87a", b"GIF89a") and len(head) >= 10:
                return int.from_bytes(head[6:8], "little"), int.from_bytes(head[8:10], "little")
            if head.startswith(b"\xff\xd8"):
                f.seek(2)
                return _read_jpeg_size(f)
    except OSError:
        return None
    return None


def _read_jpeg_size(f) -> tuple[int, int] | None:
    while True:
        marker_start = f.read(1)
        if not marker_start:
            return None
        if marker_start != b"\xff":
            continue
        marker = f.read(1)
        while marker == b"\xff":
            marker = f.read(1)
        if not marker or marker in (b"\xd8", b"\xd9"):
            continue
        length_bytes = f.read(2)
        if len(length_bytes) != 2:
            return None
        length = int.from_bytes(length_bytes, "big")
        if marker[0] in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            data = f.read(5)
            if len(data) != 5:
                return None
            return int.from_bytes(data[3:5], "big"), int.from_bytes(data[1:3], "big")
        f.seek(max(length - 2, 0), 1)


def _render_image_editor(sheet, ctx, character_id: str, image: CharacterImageAsset, image_path, refresh_fn) -> None:
    size = _image_size(image, image_path)
    ui.interactive_image(
        image_path,
        size=size,
        events=[],
        sanitize=False,
    ).classes("rounded-md overflow-hidden border bg-grey-2").style(_image_frame_style(size))

    with ui.row().classes("gap-2 mt-2 flex-wrap"):
        ui.button(
            "顔範囲を設定",
            icon="crop_free",
            on_click=lambda: _open_face_rect_dialog(sheet, ctx, character_id, image, image_path, refresh_fn),
        ).props("flat color=primary")
        ui.button(
            "バストショット範囲を設定",
            icon="crop_portrait",
            on_click=lambda: _open_bust_rect_dialog(sheet, ctx, character_id, image, image_path, refresh_fn),
        ).props("flat color=secondary")


def _open_face_rect_dialog(sheet, ctx, character_id: str, image: CharacterImageAsset, image_path, refresh_fn) -> None:
    _open_image_rect_dialog(
        sheet,
        ctx,
        character_id,
        image,
        image_path,
        refresh_fn,
        rect_kind="face",
        rect=image.face_rect,
        title="顔範囲を設定",
        tooltip="ドラッグで顔範囲を指定",
        too_small_message="顔範囲が小さすぎます",
        saved_message="顔範囲を保存しました",
        color="#6E9572",
    )


def _open_bust_rect_dialog(sheet, ctx, character_id: str, image: CharacterImageAsset, image_path, refresh_fn) -> None:
    _open_image_rect_dialog(
        sheet,
        ctx,
        character_id,
        image,
        image_path,
        refresh_fn,
        rect_kind="bust",
        rect=image.bust_rect,
        title="バストショット範囲を設定",
        tooltip="ドラッグでバストショット範囲を指定",
        too_small_message="バストショット範囲が小さすぎます",
        saved_message="バストショット範囲を保存しました",
        color="#3A7CA5",
    )


def _open_image_rect_dialog(
    sheet,
    ctx,
    character_id: str,
    image: CharacterImageAsset,
    image_path,
    refresh_fn,
    *,
    rect_kind: str,
    rect: FaceRect,
    title: str,
    tooltip: str,
    too_small_message: str,
    saved_message: str,
    color: str,
) -> None:
    size = _image_size(image, image_path)
    state: dict[str, Any] = {
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

        editor = ui.interactive_image(
            image_path,
            content=_rect_overlay(state["draft"], state["width"], state["height"], color),
            size=size,
            events=["mousedown", "mousemove", "mouseup", "mouseleave"],
            sanitize=False,
        ).classes("rounded-md overflow-hidden border bg-grey-2 cursor-crosshair").style(_image_frame_style(size))
        editor.tooltip(tooltip)

        def _on_loaded(e) -> None:
            args = e.args or {}
            state["width"] = int(args.get("width") or image.width or 0)
            state["height"] = int(args.get("height") or image.height or 0)
            if state["width"] > 0 and state["height"] > 0:
                image.width = state["width"]
                image.height = state["height"]
                editor.style(_image_frame_style((state["width"], state["height"])))
            editor.set_content(_rect_overlay(state["draft"], state["width"], state["height"], color))

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
                state["draft"] = _rect_from_points((x, y), (x, y), width, height)
                editor.set_content(_rect_overlay(state["draft"], width, height, color))
                return

            if e.type == "mousemove" and state["dragging"]:
                start = state["start"]
                if start is None:
                    return
                state["draft"] = _rect_from_points(start, (x, y), width, height)
                editor.set_content(_rect_overlay(state["draft"], width, height, color))
                return

            if e.type == "mouseup" and state["dragging"]:
                state["dragging"] = False
                start = state["start"]
                state["start"] = None
                if start is None:
                    return
                state["draft"] = _rect_from_points(start, (x, y), width, height)
                editor.set_content(_rect_overlay(state["draft"], width, height, color))
                return

            if e.type == "mouseleave" and state["dragging"]:
                state["dragging"] = False
                state["start"] = None
                editor.set_content(_rect_overlay(state["draft"], width, height, color))

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
            if rect_kind == "face":
                saved = await ctx.characters.update_face_rect(
                    character_id,
                    rect,
                    image_width=width,
                    image_height=height,
                )
            elif rect_kind == "bust":
                saved = await ctx.characters.update_bust_rect(
                    character_id,
                    rect,
                    image_width=width,
                    image_height=height,
                )
            else:
                ui.notify("未対応の範囲種別です", type="negative")
                return
            sheet.media = saved.media
            ui.notify(saved_message, type="positive")
            dlg.close()
            refresh_fn()

        def _reset() -> None:
            state["draft"] = FaceRect()
            editor.set_content(_rect_overlay(state["draft"], state["width"], state["height"], color))

        editor.on("loaded", _on_loaded)
        editor.on_mouse(_on_mouse)

        with ui.row().classes("justify-end gap-2 mt-3"):
            ui.button("リセット", icon="restart_alt", on_click=_reset).props("flat")
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("保存", icon="save", on_click=_save).props("color=primary unelevated")

    dlg.open()


def _rect_from_points(start: tuple[float, float], end: tuple[float, float], width: int, height: int) -> FaceRect:
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


def _rect_overlay(rect: FaceRect, width: int, height: int, color: str) -> str:
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


def _render_tags(sheet, container, ctx) -> None:
    container.clear()
    with container:
        for tag in list(sheet.tags):

            def _make_remove(t: str):
                async def _remove() -> None:
                    if t in sheet.tags:
                        sheet.tags.remove(t)
                        await ctx.characters.save(sheet)
                        _render_tags(sheet, container, ctx)

                return _remove

            with ui.row().classes("items-center gap-0"):
                ui.badge(tag).props("outline color=primary").classes("text-xs px-2 py-1")
                ui.button(icon="close", on_click=_make_remove(tag)).props("flat round dense size=xs").classes(
                    "text-grey-5"
                )

        def _open_tag_dialog() -> None:
            with ui.dialog() as dlg, ui.card().classes("min-w-[300px]"):
                ui.label("タグを追加").classes("text-base font-semibold mb-2")
                new_tag = ui.input(label="タグ名").classes("w-full")

                async def _add() -> None:
                    tag = new_tag.value.strip()
                    if tag and tag not in sheet.tags:
                        sheet.tags.append(tag)
                        await ctx.characters.save(sheet)
                        _render_tags(sheet, container, ctx)
                        ui.notify(f"タグ「{tag}」を追加しました", type="positive")
                    dlg.close()

                with ui.row().classes("justify-end gap-2 mt-3"):
                    ui.button("キャンセル", on_click=dlg.close).props("flat")
                    ui.button("追加", on_click=_add).props("color=primary unelevated")
            dlg.open()

        ui.button(icon="add", on_click=_open_tag_dialog).props("flat round dense color=primary").tooltip("タグを追加")


def _quality_label(status: str) -> None:
    labels = {"complete": ("良好", "positive"), "partial": ("部分的", "warning"), "failed": ("低い", "negative")}
    label, color = labels.get(status, ("不明", "grey"))
    ui.badge(label).props(f"color={color}")
