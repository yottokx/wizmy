"""キャラクターメディア管理 UI コンポーネント。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nicegui import ui

from ...core.character.schemas import CharacterSheet, CharacterTTSSettings
from .character_media_image import _open_image_generation_dialog, _render_image_editor
from .character_media_voice import _open_voice_design_dialog, _render_tts_controls


@dataclass(slots=True)
class CharacterMediaActions:
    """キャラクターメディアUIが保存先を差し替えるための操作セット。"""

    target_id: str
    result_url: str
    scope_prefix: str
    metadata: dict[str, Any] = field(default_factory=dict)
    media_path: Callable[[str], Path | None] | None = None
    save_image: Callable[[Any], Awaitable[CharacterSheet]] | None = None
    save_image_bytes: Callable[..., Awaitable[CharacterSheet]] | None = None
    save_voice: Callable[[Any], Awaitable[CharacterSheet]] | None = None
    save_voice_bytes: Callable[..., Awaitable[CharacterSheet]] | None = None
    update_tts_settings: Callable[[CharacterTTSSettings], Awaitable[CharacterSheet]] | None = None
    update_face_rect: Callable[..., Awaitable[CharacterSheet]] | None = None
    update_bust_rect: Callable[..., Awaitable[CharacterSheet]] | None = None
    save_tts_preview: Callable[..., Path] | None = None
    save_image_preview: Callable[..., Path] | None = None
    save_tts_playback: Callable[[bytes], Path] | None = None


def character_media_actions(ctx, character_id: str) -> CharacterMediaActions:
    return CharacterMediaActions(
        target_id=character_id,
        result_url=f"/characters/{character_id}",
        scope_prefix=f"character:{character_id}",
        metadata={"character_id": character_id},
        media_path=ctx.characters.media_path,
        save_image=lambda upload: ctx.characters.save_image(character_id, upload),
        save_image_bytes=lambda image_bytes, **kwargs: ctx.characters.save_image_bytes(
            character_id,
            image_bytes,
            **kwargs,
        ),
        save_voice=lambda upload: ctx.characters.save_voice(character_id, upload),
        save_voice_bytes=lambda audio_bytes, **kwargs: ctx.characters.save_voice_bytes(
            character_id,
            audio_bytes,
            **kwargs,
        ),
        update_tts_settings=lambda settings: ctx.characters.update_tts_settings(
            character_id,
            settings,
        ),
        update_face_rect=lambda rect, **kwargs: ctx.characters.update_face_rect(
            character_id,
            rect,
            **kwargs,
        ),
        update_bust_rect=lambda rect, **kwargs: ctx.characters.update_bust_rect(
            character_id,
            rect,
            **kwargs,
        ),
        save_tts_preview=lambda audio_bytes, **kwargs: ctx.characters.save_tts_preview(
            character_id,
            audio_bytes,
            **kwargs,
        ),
        save_image_preview=lambda image_bytes, **kwargs: ctx.characters.save_image_preview(
            character_id,
            image_bytes,
            **kwargs,
        ),
        save_tts_playback=lambda audio_bytes: ctx.characters.save_tts_playback(
            character_id,
            audio_bytes,
        ),
    )


def render_character_media_panel(
    sheet,
    ctx,
    character_id: str,
    refresh_fn,
    actions: CharacterMediaActions | None = None,
) -> None:
    actions = actions or character_media_actions(ctx, character_id)
    with ui.card().classes("w-full"):
        with ui.row().classes("items-center gap-2 mb-2"):
            ui.icon("image").style("color: #6E9572;")
            ui.label("画像").classes("text-base font-semibold")

        image = sheet.media.primary_image()
        image_path = actions.media_path(image.path) if image and actions.media_path else None
        if image and image_path:
            _render_image_editor(sheet, ctx, character_id, image, image_path, refresh_fn, actions)
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
                if actions.save_image is None:
                    raise RuntimeError("画像の保存処理が設定されていません。")
                saved = await actions.save_image(e.file)
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
            on_click=lambda: _open_image_generation_dialog(sheet, ctx, character_id, refresh_fn, actions),
        ).props("outline color=secondary").classes("w-full")

    with ui.card().classes("w-full"):
        with ui.row().classes("items-center gap-2 mb-2"):
            ui.icon("graphic_eq").style("color: #6E9572;")
            ui.label("音声").classes("text-base font-semibold")

        voice = sheet.media.primary_voice()
        voice_path = actions.media_path(voice.path) if voice and actions.media_path else None
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
                if actions.save_voice is None:
                    raise RuntimeError("音声の保存処理が設定されていません。")
                saved = await actions.save_voice(e.file)
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
            on_click=lambda: _open_voice_design_dialog(sheet, ctx, character_id, refresh_fn, actions),
        ).props("outline color=secondary").classes("w-full")

        if voice and voice_path:
            _render_tts_controls(sheet, ctx, character_id, voice, voice_path, refresh_fn, actions)
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
