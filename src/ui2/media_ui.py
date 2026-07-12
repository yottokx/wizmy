"""
メディア編集(画像/音声)ページの共有UI(Phase 6)。

モック media-image.html / media-voice.html 準拠。キャラクター版とグループ
メンバー版(および設定ページのペルソナ/ナレーター音声)で同じレンダラを
`MediaTarget` アダプタ経由で共有する(旧 CharacterMediaActions の ui2 再設計)。

- 画像: いま(メイン+rect+グリッド)/ 生成ワークスペース(常設)
- 音声: いま(プレイヤー+差し替え)/ ボイスデザイン(常設)/ TTS設定
"""

from __future__ import annotations

import html
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from nicegui import ui

from ..core.character.schemas import (
    CHARACTER_GEN_SERVER_TTS_MODE_CLONE,
    CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3,
    CHARACTER_TTS_API_GEN_SERVER,
    CharacterImageAsset,
    CharacterSheet,
    CharacterTTSSettings,
)
from ..core.gen_server.schemas import (
    GEN_SERVER_DEFAULT_FIELDS,
    GEN_SERVER_MODE_IRODORI_VOICE_CLONE,
    GEN_SERVER_MODE_IRODORI_VOICE_DESIGN,
    GEN_SERVER_MODE_LABELS,
    GEN_SERVER_MODE_SDXL_IMAGE,
    clean_gen_server_mode_defaults,
)
from ..core.image_generation.schemas import (
    IMAGE_GENERATION_PARAMETER_FIELDS,
    ImageGenerationProfile,
    image_generation_profile_values,
)
from ..core.tts.options import (
    CHARACTER_GEN_SERVER_VOICE_API_VALUE,
    GEN_SERVER_TTS_MODE_OPTIONS,
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
from ..core.tts.schemas import TTS_PROVIDER_IRODORI_SERVER
from ..services.ai_jobs import AIJobStatus
from ..services.llm_runtime import (
    API_KEY_LOCKED,
    ENDPOINT_NOT_FOUND,
    MODEL_ID_MISSING,
    PROFILE_NOT_FOUND,
    LLMRuntimeError,
    build_configured_llm,
)
from .media_logic import (
    candidate_negative_tags,
    clean_voice_caption,
    editor_html_to_prompt,
    generated_image_size_label,
    join_prompt_tags,
    message_content_text,
    prompt_text_to_editor_html,
    read_param_value,
    replace_generated_negative_prompt_html,
    replace_generated_prompt_html,
    voice_caption_sheet_source,
)
from .sheet_logic import kanji_number
from .state import get_vault_password

# ---------------------------------------------------------------------------
# ページ共通CSS(モック media-image.html / media-voice.html の <style> 移植)
# ---------------------------------------------------------------------------

MEDIA_CSS = """
.wrap { max-width: 1080px; margin: 0 auto; padding: 34px 26px 30px; }

.mhead { display: flex; align-items: center; gap: 14px; margin-bottom: 6px; flex-wrap: wrap; }
.mhead .t h1 { margin: 0; font-size: 21px; letter-spacing: .12em; font-weight: 600; }
.mhead .t .sub { font-size: 12px; color: var(--muted); letter-spacing: .05em; }

.state-lbl {
  display: flex; align-items: center; gap: 14px;
  margin: 56px 0 20px;
  color: var(--muted); font-size: 12px; letter-spacing: .3em;
  scroll-margin-top: 70px;
}
.state-lbl:first-of-type { margin-top: 18px; }
.state-lbl::after { content: ""; flex: 1; height: 1px; background: var(--line); }

.panel {
  position: relative;
  padding: 6px 0 10px;
  overflow: hidden;
}

/* ---------- 画像: いま ---------- */
.img-now { display: grid; grid-template-columns: 340px minmax(0, 1fr); gap: 30px; }
.img-main { position: relative; border-radius: 6px; overflow: hidden; aspect-ratio: 3 / 4; background: var(--bg-2); }
.img-main img { width: 100%; height: 100%; object-fit: cover; object-position: center 8%; }
.img-main .main-ph {
  width: 100%; height: 100%;
  display: grid; place-items: center;
  color: var(--muted); font-size: 13px;
  letter-spacing: .08em;
}
.img-main .tag {
  position: absolute; top: 12px; left: 12px;
  font-size: 11px; letter-spacing: .1em;
  color: var(--accent-ink); background: var(--accent);
  border-radius: 4px; padding: 3px 12px;
  box-shadow: 0 4px 16px var(--glow);
}
.img-side { min-width: 0; }
.img-side .lbl { font-size: 10.5px; letter-spacing: .3em; color: var(--muted); margin: 0 0 10px; }
.img-side .fname { font-size: 11.5px; color: var(--muted); word-break: break-all; margin-bottom: 14px; }
.rect-chips { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 22px; }

.th-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(96px, 1fr)); gap: 10px; }
.th {
  position: relative; border-radius: 6px; overflow: hidden;
  aspect-ratio: 3 / 4; border: 1px solid var(--line-2);
  background: var(--bg-2); cursor: pointer;
}
.th img { width: 100%; height: 100%; object-fit: cover; object-position: center 10%; }
.th.main { border-color: var(--accent); box-shadow: 0 0 0 2px var(--glow); }
.th .ops {
  position: absolute; inset: auto 0 0 0;
  display: flex; justify-content: center; gap: 6px;
  padding: 6px;
  background: linear-gradient(to top, rgba(7,9,26,.85), transparent);
  opacity: 0; transition: opacity .18s;
}
.th:hover .ops, .th:focus-within .ops { opacity: 1; }
.th .ops button {
  border: none; border-radius: 4px; cursor: pointer;
  font-size: 10.5px; padding: 3px 10px;
  background: rgba(240,242,255,.16); color: #f4f5ff;
  backdrop-filter: blur(4px);
}
.th .ops button:hover { background: rgba(240,242,255,.3); }
.th.add {
  display: grid; place-items: center;
  border-style: dashed; color: var(--muted); font-size: 12px;
  text-align: center; line-height: 1.6;
}
.th.add:hover { color: var(--text); border-color: var(--accent); }

/* ---------- 生成ワークスペース ---------- */
.ws { display: grid; grid-template-columns: minmax(0, 1fr) 420px; gap: 30px; }
.gen-side { min-width: 0; display: flex; flex-direction: column; }
.gen-run { display: flex; gap: 10px; align-items: center; }
.gen-run .p3-fd { flex: 1; min-width: 0; }
.gen-run .btn { flex: none; }
.tools { min-width: 0; }
.tools .frow { margin-bottom: 14px; }
.tools .fl { display: block; font-size: 11px; letter-spacing: .14em; color: var(--muted); margin-bottom: 6px; }

/* Quasar 部品の P3 スキン(シートページの .p3-ta と同系) */
.p3-fd { width: 100%; }
.p3-fd .q-field__control { background: var(--bg-2) !important; border-radius: 6px; }
.p3-fd .q-field__control:before { border-color: var(--line-2) !important; }
.p3-fd textarea, .p3-fd input, .p3-fd .q-field__native { color: var(--text) !important; }

/* プロンプト = 色分けテキストボックス(候補由来だけ色が付く) */
.p3-editor {
  width: 100%;
  background: var(--bg-2);
  border: 1px solid var(--line-2) !important;
  border-radius: 6px;
  transition: border-color .18s;
}
.p3-editor .q-editor__toolbar, .p3-editor .q-editor__toolbars-container { display: none !important; }
.p3-editor .q-editor__content {
  min-height: 88px;
  padding: 10px 14px !important;
  color: var(--text) !important;
  font-size: 13px;
  line-height: 1.9 !important;
}
.p3-editor .q-editor__content:focus { outline: none; }
.p3-editor:focus-within { border-color: var(--accent) !important; }
.p3-editor-negative .q-editor__content { min-height: 60px; }
.p3-editor .wizmy-generated-prompt { color: var(--accent); font-weight: 600; }
.p3-editor .wizmy-generated-negative-prompt { color: var(--negative, #e08a8a); font-weight: 600; }
.tagnote { font-size: 11px; color: var(--muted); margin-top: 6px; }
.tagnote .sw { display: inline-block; width: 9px; height: 9px; border-radius: 3px; vertical-align: -1px; margin: 0 4px 0 10px; }

.cand-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 8px; }
.cand-row .chip.cand { border-style: dashed; }

/* 詳細パラメータ */
details.params { margin-top: 16px; border-top: 1px solid var(--line); padding-top: 14px; }
details.params summary {
  cursor: pointer; list-style: none;
  font-size: 12px; letter-spacing: .18em; color: var(--muted);
}
details.params summary::before { content: "▸ "; color: var(--peri); }
details.params[open] summary::before { content: "▾ "; }
.pgrid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 12px; margin-top: 12px; }
.pgrid .pf-wide { grid-column: 1 / -1; }
.pgrid .withbtn { display: flex; gap: 6px; align-items: center; }
.ws-go { margin-top: 20px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.ws-status { font-size: 12px; color: var(--muted); }

/* 生成候補(右) */
.cands { min-width: 0; display: flex; flex-direction: column; }
.cands .cttl { font-size: 15px; letter-spacing: .18em; color: var(--muted); margin-bottom: 14px; }
.cand-tabs { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.cand-view { position: relative; border-radius: 6px; overflow: hidden; background: var(--bg-2); border: 1px solid var(--line); }
.cand-view img { width: 100%; max-height: 560px; object-fit: contain; display: block; margin: 0 auto; }
.cand-bar { display: flex; align-items: center; gap: 12px; margin-top: 12px; flex-wrap: wrap; }
.cand-bar .meta { font-size: 12px; color: var(--muted); word-break: break-all; }
.cand-empty {
  border: 1px dashed var(--line-2); border-radius: 6px;
  min-height: 320px; display: grid; place-items: center;
  color: var(--muted); font-size: 13px;
  text-align: center; padding: 20px;
}

/* ---------- 音声 ---------- */
.voice-now { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.voice-now audio, .vd-cands audio, .tts-play audio { width: 100%; height: 40px; }
.vplayer {
  flex: 1; min-width: 280px;
  background: var(--bg-2); border: 1px solid var(--line-2);
  border-radius: 6px; padding: 10px 14px;
}
.vfile { font-size: 11.5px; color: var(--muted); word-break: break-all; width: 100%; margin-top: 10px; }

.vd-cands .vrow {
  display: flex; align-items: center; gap: 14px;
  background: var(--bg-2); border: 1px solid var(--line-2);
  border-radius: 6px; padding: 12px 16px; margin-bottom: 10px;
}
.vd-cands .vrow .no { color: var(--peri); font-family: "Yu Mincho", serif; flex: none; }
.vd-cands .vrow .vplayer { padding: 4px 8px; min-width: 0; border: none; background: transparent; }
.cap-row { display: flex; gap: 10px; align-items: flex-start; }
.cap-row .p3-fd { flex: 1; }
.ckb { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--muted); margin: 12px 0 0; }

/* ---------- TTS設定(行リスト・罫線なし) ---------- */
.tts-row { display: flex; align-items: center; gap: 16px; padding: 9px 4px; flex-wrap: wrap; }
.tts-row .t { font-size: 13px; font-weight: 600; letter-spacing: .04em; width: 130px; flex: none; }
.tts-row .d { font-size: 11px; color: var(--muted); width: 100%; }
.tts-row .end { margin-left: auto; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; min-width: 0; }
.tts-row .end .p3-fd { min-width: 240px; width: auto; }
.tts-go { display: flex; gap: 10px; align-items: center; margin-top: 16px; flex-wrap: wrap; }
.tts-play { flex: 1; min-width: 240px; max-width: 380px; }

/* ============ 縦画面・スマホ ============ */
@media (max-width: 900px) {
  .wrap { padding: 24px 16px 24px; }
  .panel { padding: 4px 0 8px; }
  .img-now, .ws { grid-template-columns: 1fr; gap: 22px; }
  .img-main { max-width: 300px; margin: 0 auto; width: 100%; }
  .pgrid { grid-template-columns: 1fr; }
  .tts-row .t { width: 100%; }
  .tts-row .end { margin-left: 0; width: 100%; justify-content: flex-start; }
  .cand-view img { max-height: 60vh; }
}
"""

_DIALOG_CARD_STYLE = "background: var(--panel); color: var(--text);"


# ---------------------------------------------------------------------------
# ターゲットアダプタ
# ---------------------------------------------------------------------------


@dataclass
class MediaTarget:
    """メディアUIの保存先アダプタ(キャラクター/グループメンバー/ペルソナ/ナレーター)。"""

    name: str
    tts_id: str
    result_url: str
    scope_prefix: str
    metadata: dict[str, Any] = field(default_factory=dict)
    sheet: Callable[[], Any] = lambda: None  # .media を持つオブジェクト(CharacterSheet 等)
    apply_saved: Callable[[Any], None] = lambda saved: None
    # 保存APIの戻り値からシート相当を取り出す(グループメンバーは saved.character)
    saved_sheet: Callable[[Any], Any] = lambda saved: saved
    media_path: Callable[[str], Path | None] = lambda _: None
    media_url: Callable[[str], str | None] = lambda _: None
    save_image: Callable[[Any], Awaitable[Any]] | None = None
    save_image_bytes: Callable[..., Awaitable[Any]] | None = None
    save_image_preview: Callable[..., Path] | None = None
    delete_image: Callable[[CharacterImageAsset], Awaitable[Any]] | None = None
    set_primary_image: Callable[[str], Awaitable[Any]] | None = None
    save_voice: Callable[[Any], Awaitable[Any]] | None = None
    save_voice_bytes: Callable[..., Awaitable[Any]] | None = None
    update_tts_settings: Callable[[CharacterTTSSettings], Awaitable[Any]] | None = None
    update_face_rect: Callable[..., Awaitable[Any]] | None = None
    update_bust_rect: Callable[..., Awaitable[Any]] | None = None
    save_tts_preview: Callable[..., Path] | None = None
    # ボイスデザイン/TTS のカスタマイズ(旧 CharacterMediaActions のノブ相当)
    gen_server_voice_api_value: str = CHARACTER_GEN_SERVER_VOICE_API_VALUE
    caption_generation_enabled: bool = True
    voice_design_text_label: str = "読み上げる台詞(自己紹介台詞から)"
    voice_design_text: Callable[[Any], str] | None = None
    voice_design_caption_placeholder: str = "例: 明るく柔らかい少女声、少し早口で元気"
    voice_design_reference_label: str = "現在の音声を参照音声として使う"
    voice_design_filename: Callable[[int], str] | None = None
    voice_design_save_result: Callable[[dict[str, object], int], Awaitable[Any]] | None = None
    voice_design_save_message: str = "生成音声を保存しました"
    tts_text: Callable[[Any], str] | None = None
    default_voice_id: Callable[[Any], str] | None = None
    fill_default_voice_id: bool = False
    show_irodori_controls: bool = True
    tts_save_message: str = "TTS設定を保存しました"
    job_label_prefix: str = ""

    def label(self, suffix: str) -> str:
        prefix = self.job_label_prefix or self.name or "キャラクター"
        return f"{prefix}の{suffix}"


def _sheet_text(factory: Callable[[Any], str] | None, sheet: Any) -> str:
    if factory is not None:
        return str(factory(sheet))
    return str(getattr(sheet, "self_intro", "") or "")


def _unlink_media_file(media_path: Callable[[str], Path | None], relative_path: str) -> None:
    """削除済みアセットの実ファイルを掃除する(失敗しても致命ではない)。"""
    try:
        path = media_path(relative_path)
        if path is not None and path.is_file():
            path.unlink()
    except OSError:
        pass


def _media_without_image(media, asset: CharacterImageAsset):
    """画像アセットを除いた CharacterMedia を返す(メイン画像は削除させない)。"""
    if media.primary_image_id == asset.id:
        raise RuntimeError("メイン画像は削除できません。先に別の画像をメインにしてください。")
    updated = media.model_copy(deep=True)
    updated.images = [item for item in updated.images if item.id != asset.id]
    return updated


def character_media_target(ctx, character_id: str, state: dict) -> MediaTarget:
    """キャラクター用の MediaTarget(state["sheet"] を最新に保つ)。"""
    from .components.portrait import media_url as portrait_media_url

    def _sheet() -> CharacterSheet:
        return state["sheet"]

    def _apply(saved: Any) -> None:
        if saved is not None:
            state["sheet"] = saved

    async def _delete_image(asset: CharacterImageAsset) -> CharacterSheet:
        sheet = _sheet().model_copy(deep=True)
        sheet.media = _media_without_image(sheet.media, asset)
        saved = await ctx.characters.save(sheet)
        _unlink_media_file(ctx.characters.media_path, asset.path)
        return saved

    async def _set_primary(asset_id: str) -> CharacterSheet:
        sheet = _sheet().model_copy(deep=True)
        sheet.media.primary_image_id = asset_id
        return await ctx.characters.save(sheet)

    return MediaTarget(
        name=_sheet().name or "キャラクター",
        tts_id=character_id,
        result_url=f"/characters/{character_id}",
        scope_prefix=f"character:{character_id}",
        metadata={"character_id": character_id},
        sheet=_sheet,
        apply_saved=_apply,
        media_path=ctx.characters.media_path,
        media_url=portrait_media_url,
        save_image=lambda upload: ctx.characters.save_image(character_id, upload),
        save_image_bytes=lambda image_bytes, **kwargs: ctx.characters.save_image_bytes(
            character_id, image_bytes, **kwargs
        ),
        save_image_preview=lambda image_bytes, **kwargs: ctx.characters.save_image_preview(
            character_id, image_bytes, **kwargs
        ),
        delete_image=_delete_image,
        set_primary_image=_set_primary,
        save_voice=lambda upload: ctx.characters.save_voice(character_id, upload),
        save_voice_bytes=lambda audio_bytes, **kwargs: ctx.characters.save_voice_bytes(
            character_id, audio_bytes, **kwargs
        ),
        update_tts_settings=lambda settings: ctx.characters.update_tts_settings(character_id, settings),
        update_face_rect=lambda rect, **kwargs: ctx.characters.update_face_rect(character_id, rect, **kwargs),
        update_bust_rect=lambda rect, **kwargs: ctx.characters.update_bust_rect(character_id, rect, **kwargs),
        save_tts_preview=lambda audio_bytes, **kwargs: ctx.characters.save_tts_preview(
            character_id, audio_bytes, **kwargs
        ),
    )


def group_member_media_target(ctx, group, member_id: str, state: dict) -> MediaTarget:
    """グループメンバー用の MediaTarget(state["member"] を最新に保つ)。"""
    from .components.portrait import media_url as portrait_media_url

    group_id = group.id

    def _member():
        return state["member"]

    def _sheet() -> CharacterSheet:
        return _member().character

    def _apply(saved: Any) -> None:
        if saved is None:
            raise RuntimeError("グループ内キャラクターが見つかりませんでした。")
        state["member"] = saved

    async def _delete_image(asset: CharacterImageAsset):
        sheet = _sheet().model_copy(deep=True)
        sheet.media = _media_without_image(sheet.media, asset)
        saved = await ctx.group_chats.update_member_character(group_id, member_id, sheet)
        _unlink_media_file(ctx.group_chats.media_path, asset.path)
        return saved

    async def _set_primary(asset_id: str):
        sheet = _sheet().model_copy(deep=True)
        sheet.media.primary_image_id = asset_id
        return await ctx.group_chats.update_member_character(group_id, member_id, sheet)

    return MediaTarget(
        name=_sheet().name or "住人",
        tts_id=f"group-{group_id}-member-{member_id}",
        result_url=f"/groups/{group_id}/members/{member_id}",
        scope_prefix=f"group_member:{group_id}:{member_id}",
        metadata={"group_id": group_id, "member_id": member_id},
        sheet=_sheet,
        apply_saved=_apply,
        saved_sheet=lambda saved: saved.character,
        media_path=ctx.group_chats.media_path,
        media_url=portrait_media_url,
        save_image=lambda upload: ctx.group_chats.save_member_image(group_id, member_id, upload),
        save_image_bytes=lambda image_bytes, **kwargs: ctx.group_chats.save_member_image_bytes(
            group_id, member_id, image_bytes, **kwargs
        ),
        save_image_preview=lambda image_bytes, **kwargs: ctx.group_chats.save_member_image_preview(
            group_id, member_id, image_bytes, **kwargs
        ),
        delete_image=_delete_image,
        set_primary_image=_set_primary,
        save_voice=lambda upload: ctx.group_chats.save_member_voice(group_id, member_id, upload),
        save_voice_bytes=lambda audio_bytes, **kwargs: ctx.group_chats.save_member_voice_bytes(
            group_id, member_id, audio_bytes, **kwargs
        ),
        update_tts_settings=lambda settings: ctx.group_chats.update_member_tts_settings(
            group_id, member_id, settings
        ),
        update_face_rect=lambda rect, **kwargs: ctx.group_chats.update_member_face_rect(
            group_id, member_id, rect, **kwargs
        ),
        update_bust_rect=lambda rect, **kwargs: ctx.group_chats.update_member_bust_rect(
            group_id, member_id, rect, **kwargs
        ),
        save_tts_preview=lambda audio_bytes, **kwargs: ctx.group_chats.save_member_tts_preview(
            group_id, member_id, audio_bytes, **kwargs
        ),
    )


# ---------------------------------------------------------------------------
# 小物
# ---------------------------------------------------------------------------


def p3_button(label: str, on_click, *, classes: str = "btn", title: str = "") -> ui.element:
    btn = ui.element("button").classes(classes)
    if title:
        btn.props(f'title="{html.escape(title)}"')
    with btn:
        ui.html(html.escape(label))
    btn.on("click", on_click)
    return btn


def chip_button(label: str, on_click, *, title: str = "") -> ui.element:
    return p3_button(label, on_click, classes="chip", title=title)


def open_upload_dialog(*, title: str, accept: str, max_file_size: int, on_upload) -> None:
    with ui.dialog() as dlg, ui.card().classes("min-w-[380px]").style(_DIALOG_CARD_STYLE):
        ui.label(title).classes("text-base font-semibold mb-2")

        async def _handle(e) -> None:
            if await on_upload(e):
                dlg.close()

        ui.upload(
            label="ファイルをドロップ / 選択",
            on_upload=_handle,
            auto_upload=True,
            max_file_size=max_file_size,
        ).props(f"accept={accept} flat bordered").classes("w-full")
        with ui.row().classes("justify-end mt-3 w-full"):
            p3_button("閉じる", dlg.close, classes="btn quiet")
    dlg.open()


def build_param_control(key: str, spec: dict, value: object) -> ui.element:
    """gen_server パラメータ1項目分の Quasar 入力(P3スキン)を生成する。"""
    label = str(spec.get("label", key))
    if spec.get("type") == "boolean":
        return ui.checkbox(label, value=bool(value)).classes("p3-fd")
    if spec.get("enum"):
        options = list(spec["enum"])
        return (
            ui.select(options=options, value=value if value in options else spec.get("default"), label=label)
            .props("outlined dense")
            .classes("p3-fd")
        )
    if spec.get("type") in {"integer", "number"}:
        return (
            ui.number(label=label, value=value, min=spec.get("minimum"), step=spec.get("step"))
            .props("outlined dense")
            .classes("p3-fd")
        )
    if spec.get("multiline"):
        return ui.textarea(label=label, value=value or "").props("outlined rows=3").classes("p3-fd pf-wide")
    return ui.input(label=label, value=value or "").props("outlined dense clearable").classes("p3-fd")


async def open_model_id_picker(ctx, endpoint_id: str, mode: str, model_input) -> None:
    """gen_server のモデルID一覧を取得して選択ダイアログを開く。"""
    if not endpoint_id:
        ui.notify("先にこの機能へWizmy-Gen-Serverを割り当ててください。", type="warning")
        return
    try:
        models = await ctx.api_config.fetch_gen_server_models(endpoint_id, mode)
    except Exception as err:
        ui.notify(f"モデルIDを取得できませんでした: {err}", type="negative")
        return
    if not models:
        ui.notify("この機能で利用できるモデルが見つかりませんでした。", type="warning")
        return

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg").style(_DIALOG_CARD_STYLE):
        ui.label(f"{GEN_SERVER_MODE_LABELS.get(mode, mode)} のモデルID").classes("text-base font-semibold mb-2")
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


# ---------------------------------------------------------------------------
# ボイスキャプション生成(シートから・LLM)
# ---------------------------------------------------------------------------


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


async def generate_voice_caption_from_sheet(sheet: CharacterSheet, ctx) -> str:
    """キャラクターシートから VoiceDesign v3 用キャプションを生成する。"""
    source = voice_caption_sheet_source(sheet)
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
    caption = clean_voice_caption(message_content_text(response))
    if not caption:
        raise RuntimeError("キャプションを生成できませんでした。")
    return caption


# ---------------------------------------------------------------------------
# 画像: いま(セクションA)
# ---------------------------------------------------------------------------


def render_image_now(ctx, target: MediaTarget, refresh: Callable[[], None]) -> None:
    """メイン画像+rect チップ+全画像グリッド(メイン切替/削除/アップロード)。"""
    sheet = target.sheet()
    media = sheet.media
    primary = media.primary_image()

    def _open_upload() -> None:
        async def _on_upload(e) -> bool:
            try:
                if target.save_image is None:
                    raise RuntimeError("画像の保存処理が設定されていません。")
                target.apply_saved(await target.save_image(e.file))
                ui.notify("画像を保存しました", type="positive")
                refresh()
                return True
            except Exception as err:  # noqa: BLE001 - UI通知のための包括捕捉
                ui.notify(f"画像の保存に失敗しました: {err}", type="negative")
                return False

        open_upload_dialog(
            title="画像をアップロード",
            accept="image/*",
            max_file_size=20 * 1024 * 1024,
            on_upload=_on_upload,
        )

    def _open_rect(kind: str) -> None:
        from .components.rect_editor import open_rect_dialog

        image = target.sheet().media.primary_image()
        if image is None:
            ui.notify("範囲を設定する画像がありません", type="warning")
            return
        image_path = target.media_path(image.path)
        if image_path is None:
            ui.notify("画像ファイルが見つかりません", type="warning")
            return

        async def _on_save(rect, width: int, height: int) -> None:
            if kind == "face":
                if target.update_face_rect is None:
                    raise RuntimeError("顔範囲の保存処理が設定されていません。")
                saved = await target.update_face_rect(rect, image_width=width, image_height=height)
            else:
                if target.update_bust_rect is None:
                    raise RuntimeError("バスト範囲の保存処理が設定されていません。")
                saved = await target.update_bust_rect(rect, image_width=width, image_height=height)
            target.apply_saved(saved)
            refresh()

        open_rect_dialog(image=image, image_path=image_path, kind=kind, on_save=_on_save)

    async def _set_primary(asset_id: str) -> None:
        if target.set_primary_image is None:
            return
        target.apply_saved(await target.set_primary_image(asset_id))
        refresh()
        ui.notify("メイン画像を変更しました", type="positive")

    def _confirm_delete(asset: CharacterImageAsset) -> None:
        with ui.dialog() as dlg, ui.card().style(_DIALOG_CARD_STYLE):
            ui.label("この画像を削除しますか?").classes("text-base font-medium mb-2")
            ui.label("この操作は取り消せません。").classes("note")

            async def _do() -> None:
                try:
                    if target.delete_image is None:
                        raise RuntimeError("画像の削除処理が設定されていません。")
                    target.apply_saved(await target.delete_image(asset))
                    ui.notify("画像を削除しました", type="positive")
                    dlg.close()
                    refresh()
                except Exception as err:  # noqa: BLE001 - UI通知のための包括捕捉
                    ui.notify(f"画像の削除に失敗しました: {err}", type="negative")

            with ui.row().classes("justify-end gap-2 mt-4 w-full"):
                p3_button("キャンセル", dlg.close, classes="btn quiet")
                p3_button("削除", _do, classes="btn primary").mark("ui2-media-image-delete-confirm")
        dlg.open()

    with ui.element("section").classes("panel img-now"):
        with ui.element("div").classes("img-main"):
            url = target.media_url(primary.path) if primary is not None else None
            if url is not None:
                ui.element("img").props(f'src="{url}"')
                with ui.element("span").classes("tag"):
                    ui.html("メイン")
            else:
                with ui.element("div").classes("main-ph"):
                    ui.html("画像がありません")

        with ui.element("div").classes("img-side"):
            with ui.element("div").classes("lbl"):
                ui.html("メイン画像")
            if primary is not None:
                fname_parts = [primary.original_name or Path(primary.path).name]
                size_label = generated_image_size_label(primary)
                if size_label:
                    fname_parts.append(size_label)
                with ui.element("div").classes("fname"):
                    ui.html(html.escape(" ・ ".join(fname_parts)))
                with ui.element("div").classes("rect-chips"):
                    if target.update_face_rect is not None:
                        chip_button("顔範囲を編集", lambda: _open_rect("face"))
                    if target.update_bust_rect is not None:
                        chip_button("バスト範囲を編集", lambda: _open_rect("bust"))
            else:
                with ui.element("div").classes("fname"):
                    ui.html("まだ画像がありません。アップロードするか、下のワークスペースで生成できます。")

            with ui.element("div").classes("lbl"):
                ui.html("すべての画像")
            with ui.element("div").classes("th-grid"):
                for asset in media.images:
                    asset_url = target.media_url(asset.path)
                    if asset_url is None:
                        continue
                    is_main = primary is not None and asset.id == primary.id
                    th = ui.element("div").classes("th main" if is_main else "th")
                    if is_main:
                        th.props('title="メイン画像"')
                    with th:
                        ui.element("img").props(f'src="{asset_url}" loading="lazy"')
                        if not is_main:
                            with ui.element("div").classes("ops"):
                                if target.set_primary_image is not None:
                                    make_main = ui.element("button")
                                    with make_main:
                                        ui.html("メインにする")
                                    make_main.on("click", lambda a=asset: _set_primary(a.id))
                                if target.delete_image is not None:
                                    delete_btn = ui.element("button").mark("ui2-media-image-delete")
                                    with delete_btn:
                                        ui.html("削除")
                                    delete_btn.on("click", lambda a=asset: _confirm_delete(a))
                add = ui.element("div").classes("th add").mark("ui2-media-image-upload")
                with add:
                    ui.html("+ アップロード<br>(ドロップも可)")
                add.on("click", _open_upload)


# ---------------------------------------------------------------------------
# 画像生成ワークスペース(セクションB)
# ---------------------------------------------------------------------------


def render_image_workspace(
    ctx,
    target: MediaTarget,
    refresh: Callable[[], None],
    *,
    simple: bool = False,
    default_prompt: str = "",
) -> None:
    """画像生成ワークスペース(常設)。simple=True で候補行と詳細パラメータを畳んだ同型。"""
    profiles = ctx.api_config.get_image_generation_profiles()
    with ui.element("section").classes("panel ws"):
        ui.element("div").classes("sparkle-field").props('data-count="10"')
        if not profiles:
            with ui.element("div").classes("cand-empty").style("grid-column: 1 / -1; min-height: 120px;"):
                ui.html("設定で画像生成プロファイルを追加すると、ここから画像を生成できます。")
            return

        config = ctx.api_config.get_image_generation_config()
        selected_profile = ctx.api_config.get_image_generation_profile(config.default_profile_id) or profiles[0]
        llm_profiles = ctx.api_config.get_llm_profiles()
        app_llm_config = ctx.api_config.get_app_llm_config()
        selected_llm = ctx.api_config.get_llm_profile(app_llm_config.generation_profile_id) or (
            llm_profiles[0] if llm_profiles else None
        )

        param_fields = {
            "model_id": {"label": "モデルID", "type": "string", "default": ""},
            **IMAGE_GENERATION_PARAMETER_FIELDS,
        }
        initial_prompt = selected_profile.prompt or default_prompt
        state: dict[str, Any] = {
            "candidates": [],
            "generated": [],
            "selected_index": 0,
        }
        controls: dict[str, Any] = {}

        candidate_chips: ui.element | None = None
        llm_select = None
        candidates_btn: ui.element | None = None

        with ui.element("div").classes("tools"):
            if not simple:
                with ui.element("div").classes("frow"):
                    with ui.element("span").classes("fl"):
                        ui.html("プロンプト生成プロファイル")
                    with ui.element("div").classes("cand-row"):
                        llm_select = (
                            ui.select(
                                options={p.id: f"{p.name} / {p.model_id or 'モデル未設定'}" for p in llm_profiles},
                                value=selected_llm.id if selected_llm else None,
                            )
                            .props("outlined dense")
                            .classes("p3-fd")
                            .style("flex: 1; min-width: 160px; width: auto;")
                        )
                        candidates_btn = chip_button("プロンプト生成", lambda: _generate_prompt_candidates())
                    candidate_chips = ui.element("div").classes("cand-row")

            with ui.element("div").classes("frow"):
                with ui.element("span").classes("fl"):
                    ui.html("プロンプト")
                prompt_editor = (
                    ui.editor(
                        value=prompt_text_to_editor_html(initial_prompt),
                        placeholder="画像生成プロンプト",
                    )
                    .classes("p3-editor")
                    .mark("ui2-media-prompt-box")
                )
                with ui.element("div").classes("tagnote"):
                    ui.html(
                        '<span class="sw" style="background: var(--accent);"></span>'
                        "色付きの部分は候補から反映(候補を選び直すと置き換わります)"
                    )

            with ui.element("div").classes("frow"):
                with ui.element("span").classes("fl"):
                    ui.html("ネガティブプロンプト")
                negative_editor = (
                    ui.editor(
                        value=prompt_text_to_editor_html(selected_profile.negative_prompt),
                        placeholder="除外したい要素",
                    )
                    .classes("p3-editor p3-editor-negative")
                )

        # ---- 右: 実行(プロファイル+生成)+詳細パラメータ+生成候補 ----

        with ui.element("div").classes("gen-side"):
            with ui.element("div").classes("frow"):
                with ui.element("span").classes("fl"):
                    ui.html("画像生成プロファイル")
                with ui.element("div").classes("gen-run"):
                    profile_select = (
                        ui.select(
                            options={p.id: p.name or "無題のプロファイル" for p in profiles},
                            value=selected_profile.id,
                        )
                        .props("outlined dense")
                        .classes("p3-fd")
                    )
                    generate_btn = p3_button("生成する", lambda: _generate(), classes="btn primary")
                    generate_btn.mark("ui2-media-image-generate")
                status = ui.element("span").classes("ws-status")

            with ui.element("details").classes("params"):
                with ui.element("summary"):
                    ui.html("詳細パラメータ", tag="span")
                with ui.element("div").classes("pgrid"):
                    initial_values = image_generation_profile_values(selected_profile)
                    for key, spec in param_fields.items():
                        value = initial_values.get(key, spec.get("default"))
                        if key == "model_id":
                            with ui.element("div").classes("pf-wide withbtn"):
                                model_input = (
                                    ui.input(label="モデルID", value=value or "")
                                    .props("outlined dense clearable")
                                    .classes("p3-fd")
                                    .style("flex: 1;")
                                )
                                controls[key] = model_input

                                async def _fetch_model_id() -> None:
                                    profile = ctx.api_config.get_image_generation_profile(profile_select.value or "")
                                    if profile is None or not profile.endpoint_id:
                                        ui.notify("画像生成プロファイルのAPI接続先を設定してください。", type="warning")
                                        return
                                    await open_model_id_picker(
                                        ctx, profile.endpoint_id, GEN_SERVER_MODE_SDXL_IMAGE, model_input
                                    )

                                chip_button("取得", _fetch_model_id)
                        else:
                            controls[key] = build_param_control(key, spec, value)

            with ui.element("div").classes("cands").style("margin-top: 18px;"):
                with ui.element("div").classes("cttl serif"):
                    ui.html("生成候補")
                cand_tabs = ui.element("div").classes("cand-tabs")
                cand_view = ui.element("div")

        def _set_status(text: str) -> None:
            status.clear()
            with status:
                ui.html(html.escape(text))

        def _apply_profile(profile: ImageGenerationProfile) -> None:
            values = image_generation_profile_values(profile)
            prompt_editor.set_value(prompt_text_to_editor_html(str(values.get("prompt") or "") or default_prompt))
            negative_editor.set_value(prompt_text_to_editor_html(str(values.get("negative_prompt") or "")))
            for key, spec in param_fields.items():
                if key in controls:
                    controls[key].set_value(values.get(key, spec.get("default")))

        def _on_profile_change() -> None:
            profile = ctx.api_config.get_image_generation_profile(profile_select.value or "")
            if profile is not None:
                _apply_profile(profile)

        profile_select.on_value_change(lambda _: _on_profile_change())

        def _read_params() -> dict[str, object]:
            params: dict[str, object] = {
                "prompt": editor_html_to_prompt(str(prompt_editor.value or "")),
                "negative_prompt": editor_html_to_prompt(str(negative_editor.value or "")),
            }
            for key, spec in param_fields.items():
                if key in controls:
                    params[key] = read_param_value(spec, controls[key].value)
            return params

        # ---- プロンプト候補 ----

        def _render_candidate_chips() -> None:
            if candidate_chips is None:
                return
            candidate_chips.clear()
            with candidate_chips:
                for index, candidate in enumerate(state["candidates"], start=1):
                    label = str(getattr(candidate, "label", "") or f"候補 {kanji_number(index)}")
                    chip = ui.element("button").classes("chip cand").props(
                        f'title="{html.escape(str(getattr(candidate, "prompt", "")))}"'
                    )
                    with chip:
                        ui.html(html.escape(label))
                    chip.on("click", lambda c=candidate: _apply_candidate(c))

        def _apply_candidate(candidate: object) -> None:
            prompt = str(getattr(candidate, "prompt", "") or "").strip()
            if not prompt:
                return
            prompt_editor.set_value(replace_generated_prompt_html(str(prompt_editor.value or ""), prompt))
            negative_editor.set_value(
                replace_generated_negative_prompt_html(
                    str(negative_editor.value or ""),
                    join_prompt_tags(candidate_negative_tags(candidate)),
                )
            )

        async def _generate_prompt_candidates() -> None:
            if llm_select is None:
                return
            llm_profile_id = str(llm_select.value or "")
            if not llm_profile_id:
                ui.notify("LLMプロファイルを選択してください。", type="warning")
                return
            candidates_btn.props("disabled")
            _set_status("プロンプト候補を生成中…")
            try:
                job = ctx.danbooru_prompt.start_generate_candidates_job(
                    target.sheet(),
                    llm_profile_id=llm_profile_id,
                    vault_password=get_vault_password(),
                    count=3,
                    label=target.label("プロンプト候補生成"),
                    scope=f"{target.scope_prefix}:prompt",
                    metadata=dict(target.metadata),
                )
                ctx.ai_jobs.set_result_meta(job.id, {"result_url": target.result_url})
                finished = await ctx.ai_jobs.wait(job.id)
                if finished.status == AIJobStatus.CANCELLED:
                    _set_status("")
                    ui.notify("プロンプト生成を停止しました", type="info")
                    return
                if finished.status != AIJobStatus.SUCCEEDED:
                    raise RuntimeError(finished.error_message or "プロンプト生成に失敗しました。")
                state["candidates"] = list(finished.result or [])
                _render_candidate_chips()
                _set_status("")
                ui.notify("プロンプト候補を生成しました", type="positive")
            except Exception as err:  # noqa: BLE001 - UI通知のための包括捕捉
                _set_status("")
                ui.notify(f"プロンプト生成に失敗しました: {err}", type="negative", timeout=10000)
            finally:
                candidates_btn.props(remove="disabled")

        # ---- 生成候補の描画 ----

        def _render_generated() -> None:
            cand_tabs.clear()
            cand_view.clear()
            generated: list[dict[str, Any]] = state["generated"]
            index = min(state["selected_index"], len(generated) - 1)
            with cand_view:
                if not generated:
                    with ui.element("div").classes("cand-empty"):
                        ui.html("生成するとここに候補が表示されます")
                    return
            with cand_tabs:
                for i, _item in enumerate(generated):
                    chip = ui.element("button").classes("chip on" if i == index else "chip")
                    with chip:
                        ui.html(html.escape(f"候補 {kanji_number(i + 1)}"))
                    chip.on("click", lambda i=i: _select_candidate(i))
            item = generated[index]
            image = item["image"]
            with cand_view:
                with ui.element("div").classes("cand-view"):
                    ui.image(item["path"]).props("fit=contain").style(
                        "max-height: 560px; width: 100%; background: transparent;"
                    )
                with ui.element("div").classes("cand-bar"):
                    meta_parts = []
                    size_label = generated_image_size_label(image)
                    if size_label:
                        meta_parts.append(size_label)
                    filename = str(getattr(image, "filename", "") or "")
                    if filename:
                        meta_parts.append(filename)
                    with ui.element("span").classes("meta"):
                        ui.html(html.escape(" ・ ".join(meta_parts)))
                    ui.element("span").style("flex: 1;")
                    p3_button(
                        "この画像を保存",
                        lambda item=item, i=index: _save_image(item, i),
                        classes="btn primary",
                    ).mark("ui2-media-image-save")

        def _select_candidate(index: int) -> None:
            state["selected_index"] = index
            _render_generated()

        async def _generate() -> None:
            generate_btn.props("disabled")
            _set_status("生成中…")
            try:

                def _save_previews(images: list[object], job) -> dict[str, object]:
                    if target.save_image_preview is None:
                        raise RuntimeError("画像プレビューの保存処理が設定されていません。")
                    items: list[dict[str, object]] = []
                    for image in images:
                        preview_path = target.save_image_preview(
                            image.data,
                            filename=image.filename,
                            content_type=image.content_type,
                            replace_existing=False,
                        )
                        items.append({"image": image, "path": preview_path})
                    state["generated"].extend(items)
                    return {
                        "result_url": target.result_url,
                        "preview_paths": [str(item["path"]) for item in items],
                        "image_count": len(items),
                    }

                job = ctx.image_generation.start_sdxl_job(
                    profile_id=profile_select.value or "",
                    gen_server_params=_read_params(),
                    label=target.label("画像生成"),
                    scope=f"{target.scope_prefix}:image",
                    metadata=dict(target.metadata),
                    result_handler=_save_previews,
                )
                finished = await ctx.ai_jobs.wait(job.id)
                if finished.status == AIJobStatus.CANCELLED:
                    _set_status("")
                    ui.notify("画像生成を停止しました", type="info")
                    return
                if finished.status != AIJobStatus.SUCCEEDED:
                    raise RuntimeError(finished.error_message or "画像生成に失敗しました。")
                state["selected_index"] = len(state["generated"]) - 1
                _render_generated()
                _set_status("")
                ui.notify("画像を生成しました", type="positive")
            except Exception as err:  # noqa: BLE001 - UI通知のための包括捕捉
                _set_status("")
                ui.notify(f"画像生成に失敗しました: {err}", type="negative", timeout=10000)
            finally:
                generate_btn.props(remove="disabled")

        async def _save_image(item: dict[str, Any], index: int) -> None:
            image = item["image"]
            try:
                if target.save_image_bytes is None:
                    raise RuntimeError("画像の保存処理が設定されていません。")
                suffix = Path(str(getattr(image, "filename", ""))).suffix or ".png"
                saved = await target.save_image_bytes(
                    image.data,
                    filename=f"generated-image-{index + 1}{suffix}",
                    content_type=image.content_type,
                    width=image.width,
                    height=image.height,
                )
                target.apply_saved(saved)
                ui.notify("生成画像を保存しました", type="positive")
                refresh()
            except Exception as err:  # noqa: BLE001 - UI通知のための包括捕捉
                ui.notify(f"画像の保存に失敗しました: {err}", type="negative")

        _render_generated()


# ---------------------------------------------------------------------------
# 音声: いま(セクションC)
# ---------------------------------------------------------------------------


def render_voice_now(ctx, target: MediaTarget, refresh: Callable[[], None]) -> None:
    sheet = target.sheet()
    voice = sheet.media.primary_voice()
    voice_url = target.media_url(voice.path) if voice is not None else None

    def _open_upload() -> None:
        async def _on_upload(e) -> bool:
            try:
                if target.save_voice is None:
                    raise RuntimeError("音声の保存処理が設定されていません。")
                target.apply_saved(await target.save_voice(e.file))
                ui.notify("音声を保存しました", type="positive")
                refresh()
                return True
            except Exception as err:  # noqa: BLE001 - UI通知のための包括捕捉
                ui.notify(f"音声の保存に失敗しました: {err}", type="negative")
                return False

        open_upload_dialog(
            title="音声をアップロード",
            accept="audio/*",
            max_file_size=50 * 1024 * 1024,
            on_upload=_on_upload,
        )

    with ui.element("section").classes("panel"):
        with ui.element("div").classes("voice-now"):
            with ui.element("div").classes("vplayer"):
                if voice_url is not None:
                    ui.audio(voice_url)
                else:
                    ui.html("まだ音声がありません。アップロードするか、下のボイスデザインで生成できます。").classes(
                        "note"
                    )
            if target.save_voice is not None:
                chip_button(
                    "アップロードで差し替え" if voice is not None else "アップロード",
                    _open_upload,
                ).mark("ui2-media-voice-upload")
        parts: list[str] = []
        if voice is not None and voice.original_name:
            parts.append(voice.original_name)
        caption = sheet.media.tts.voice_caption.strip()
        if caption:
            parts.append(f"キャプション: {caption}")
        voice_image = str(getattr(sheet, "voice_image", "") or "").strip()
        if not parts and voice_image:
            parts.append(f"声イメージ: {voice_image}")
        if parts:
            with ui.element("div").classes("vfile"):
                ui.html(html.escape(" ・ ".join(parts)))


# ---------------------------------------------------------------------------
# ボイスデザイン(セクションD)
# ---------------------------------------------------------------------------


def render_voice_design(ctx, target: MediaTarget, refresh: Callable[[], None]) -> None:
    sheet = target.sheet()
    design_ready = ctx.tts.resolve_gen_server_voice_design_endpoint(raise_on_missing=False) is not None
    mode = GEN_SERVER_MODE_IRODORI_VOICE_DESIGN
    fields = GEN_SERVER_DEFAULT_FIELDS.get(mode, {})
    defaults = ctx.api_config.get_gen_server_config().defaults_for_mode(mode)
    current_voice = sheet.media.primary_voice()
    current_voice_path = target.media_path(current_voice.path) if current_voice is not None else None
    controls: dict[str, Any] = {}
    state: dict[str, Any] = {"generated": []}

    with ui.element("section").classes("panel ws"):
        ui.element("div").classes("sparkle-field").props('data-count="10"')
        with ui.element("div").classes("tools"):
            if not design_ready:
                with ui.element("div").classes("note").style("margin-bottom: 12px;"):
                    ui.html("設定でボイスデザインにWizmy-Gen-Serverを割り当てると声を生成できます。")

            with ui.element("div").classes("frow"):
                with ui.element("span").classes("fl"):
                    ui.html(html.escape(target.voice_design_text_label))
                text_input = (
                    ui.textarea(value=_sheet_text(target.voice_design_text, sheet))
                    .props("outlined rows=3")
                    .classes("p3-fd")
                )

            with ui.element("div").classes("frow"):
                with ui.element("span").classes("fl"):
                    ui.html("声のキャプション")
                with ui.element("div").classes("cap-row"):
                    caption_input = (
                        ui.textarea(
                            value=sheet.media.tts.voice_caption,
                            placeholder=target.voice_design_caption_placeholder,
                        )
                        .props("outlined rows=3")
                        .classes("p3-fd")
                    )
                    caption_btn = None
                    if target.caption_generation_enabled:
                        caption_btn = chip_button(
                            "シートから生成",
                            lambda: _generate_caption(),
                            title="キャラクターシートからキャプションを生成",
                        )

            reference_checkbox = None
            if current_voice_path is not None:
                with ui.element("label").classes("ckb"):
                    reference_checkbox = ui.checkbox(value=True).props("dense")
                    ui.html(html.escape(target.voice_design_reference_label))

            with ui.element("details").classes("params"):
                with ui.element("summary"):
                    ui.html("詳細パラメータ", tag="span")
                with ui.element("div").classes("pgrid"):
                    for key, spec in fields.items():
                        value = defaults.get(key, spec.get("default"))
                        if key == "model_id":
                            with ui.element("div").classes("pf-wide withbtn"):
                                model_input = (
                                    ui.input(label=str(spec.get("label", key)), value=value or "")
                                    .props("outlined dense clearable")
                                    .classes("p3-fd")
                                    .style("flex: 1;")
                                )
                                controls[key] = model_input

                                async def _fetch_model_id(model_input=model_input) -> None:
                                    endpoint_id = ctx.api_config.get_gen_server_config().assigned_endpoint_id(mode)
                                    await open_model_id_picker(ctx, endpoint_id, mode, model_input)

                                chip_button("取得", _fetch_model_id)
                        else:
                            controls[key] = build_param_control(key, spec, value)

            with ui.element("div").classes("ws-go"):
                generate_btn = p3_button("声を生成する", lambda: _generate(), classes="btn primary")
                generate_btn.mark("ui2-media-voice-generate")
                if not design_ready:
                    generate_btn.props("disabled")
                status = ui.element("span").classes("ws-status")

        with ui.element("div").classes("cands vd-cands"):
            with ui.element("div").classes("cttl serif"):
                ui.html("声の候補")
            cands_container = ui.element("div")
            with ui.element("div").classes("note").style("margin-top: 8px;"):
                ui.html("「この声にする」で音声に保存し、TTSモードをボイスクローンへ自動設定")

    def _set_status(text: str) -> None:
        status.clear()
        with status:
            ui.html(html.escape(text))

    def _read_params() -> dict[str, object]:
        return {key: read_param_value(spec, controls[key].value) for key, spec in fields.items()}

    def _render_candidates() -> None:
        cands_container.clear()
        with cands_container:
            if not state["generated"]:
                with ui.element("div").classes("cand-empty").style("min-height: 160px;"):
                    ui.html("生成するとここで聴き比べできます")
                return
            for index, item in enumerate(state["generated"], start=1):
                with ui.element("div").classes("vrow"):
                    with ui.element("span").classes("no"):
                        ui.html(kanji_number(index))
                    with ui.element("div").classes("vplayer"):
                        ui.audio(item["path"])
                    p3_button(
                        "この声にする",
                        lambda item=item, index=index: _save_voice(item, index),
                    ).mark("ui2-media-voice-adopt")

    async def _generate_caption() -> None:
        if caption_btn is None:
            return
        caption_btn.props("disabled")
        _set_status("キャプション生成中…")
        try:
            caption = await generate_voice_caption_from_sheet(target.sheet(), ctx)
            caption_input.set_value(caption)
            _set_status("")
            ui.notify("キャプションを生成しました", type="positive")
        except Exception as err:  # noqa: BLE001 - UI通知のための包括捕捉
            _set_status("")
            ui.notify(f"キャプション生成に失敗しました: {err}", type="negative", timeout=10000)
        finally:
            caption_btn.props(remove="disabled")

    async def _generate() -> None:
        text = str(text_input.value or "").strip()
        caption = str(caption_input.value or "").strip()
        if not text:
            ui.notify("読み上げる台詞を入力してください。", type="warning")
            return
        if not caption:
            ui.notify("キャプションを入力してください。", type="warning")
            return
        generate_btn.props("disabled")
        _set_status("生成中…")
        try:
            params = _read_params()

            def _save_preview(audio: bytes, job) -> dict[str, object]:
                if target.save_tts_preview is None:
                    raise RuntimeError("音声プレビューの保存処理が設定されていません。")
                preview_path = target.save_tts_preview(audio, replace_existing=False)
                state["generated"].append(
                    {"audio": audio, "path": preview_path, "caption": caption, "params": params}
                )
                return {"result_url": target.result_url, "preview_path": str(preview_path)}

            job = ctx.tts.start_design_voice_job(
                text,
                caption,
                voice_path=current_voice_path
                if reference_checkbox is not None and bool(reference_checkbox.value)
                else None,
                filename=current_voice.original_name if current_voice else "",
                content_type=current_voice.content_type if current_voice else "",
                gen_server_params=params,
                label=target.label("ボイスデザイン"),
                scope=f"{target.scope_prefix}:tts",
                metadata=dict(target.metadata),
                result_handler=_save_preview,
            )
            finished = await ctx.ai_jobs.wait(job.id)
            if finished.status == AIJobStatus.CANCELLED:
                _set_status("")
                ui.notify("ボイスデザインを停止しました", type="info")
                return
            if finished.status != AIJobStatus.SUCCEEDED:
                raise RuntimeError(finished.error_message or "ボイスデザインに失敗しました。")
            _render_candidates()
            _set_status("")
            ui.notify("ボイスデザイン音声を生成しました", type="positive")
        except Exception as err:  # noqa: BLE001 - UI通知のための包括捕捉
            _set_status("")
            ui.notify(f"ボイスデザインに失敗しました: {err}", type="negative", timeout=10000)
        finally:
            if design_ready:
                generate_btn.props(remove="disabled")

    async def _save_voice(item: dict[str, Any], index: int) -> None:
        audio = item.get("audio")
        if not audio:
            ui.notify("先に音声を生成してください。", type="warning")
            return
        try:
            if target.voice_design_save_result is not None:
                saved = await target.voice_design_save_result(item, index)
            else:
                if target.save_voice_bytes is None or target.update_tts_settings is None:
                    raise RuntimeError("音声の保存処理が設定されていません。")
                filename = (
                    target.voice_design_filename(index)
                    if target.voice_design_filename is not None
                    else f"voice-design-{index}.wav"
                )
                interim = target.saved_sheet(await target.save_voice_bytes(audio, filename=filename, content_type="audio/wav"))
                previous_is_clone = interim.media.tts.gen_server_tts_mode == CHARACTER_GEN_SERVER_TTS_MODE_CLONE
                clone_params = interim.media.tts.gen_server_params if previous_is_clone else {}
                settings = interim.media.tts.model_copy(
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
                saved = await target.update_tts_settings(settings)
            target.apply_saved(saved)
            ui.notify(target.voice_design_save_message, type="positive")
            refresh()
        except Exception as err:  # noqa: BLE001 - UI通知のための包括捕捉
            ui.notify(f"音声の保存に失敗しました: {err}", type="negative")

    _render_candidates()


# ---------------------------------------------------------------------------
# TTS設定(セクションE)
# ---------------------------------------------------------------------------


def render_tts_settings(ctx, target: MediaTarget, refresh: Callable[[], None]) -> None:
    """TTS設定の行リスト+試し読み。設定ページ(ペルソナ/ナレーター)からも共用する。"""
    sheet = target.sheet()
    voice = sheet.media.primary_voice()
    voice_path = target.media_path(voice.path) if voice is not None else None
    endpoints = ctx.tts.get_endpoints()
    gen_server_config = ctx.api_config.get_gen_server_config()
    has_gen_server = bool(assigned_gen_server_voice_endpoints(gen_server_config))
    api_value = target.gen_server_voice_api_value

    with ui.element("section").classes("panel"):
        if not endpoints and not has_gen_server:
            with ui.element("div").classes("note"):
                ui.html("使用できるTTSがありません。設定でWizmy-Gen-ServerまたはTTS APIを追加してください。")
            return

        current_settings: CharacterTTSSettings = sheet.media.tts
        endpoint_by_id = {endpoint.id: endpoint for endpoint in endpoints}
        endpoint_options = voice_api_options(
            endpoints, gen_server_config, gen_server_api_value=api_value, tts_api_prefix=TTS_API_PREFIX
        )
        selected_value = selected_voice_api_value(
            current_settings,
            endpoints,
            has_gen_server,
            gen_server_api_value=api_value,
            tts_api_prefix=TTS_API_PREFIX,
        )
        selected_endpoint = selected_tts_endpoint(
            selected_value, endpoint_by_id, gen_server_api_value=api_value, tts_api_prefix=TTS_API_PREFIX
        )
        mode_state = {"value": normalize_gen_server_tts_mode(current_settings.gen_server_tts_mode)}
        params_state = {
            "value": clean_gen_server_mode_defaults(
                gen_server_backend_mode(mode_state["value"]),
                current_settings.gen_server_params,
            )
        }

        with ui.element("div").classes("tts-rows"):
            with ui.element("div").classes("tts-row"):
                with ui.element("span").classes("t"):
                    ui.html("使用API")
                with ui.element("div").classes("end"):
                    endpoint_select = (
                        ui.select(options=endpoint_options, value=selected_value)
                        .props("outlined dense")
                        .classes("p3-fd")
                        .mark("ui2-media-tts-api")
                    )

            mode_select = None
            caption_input = None
            caption_btn = None
            if is_gen_server_voice_api(
                selected_value, gen_server_api_value=api_value, tts_api_prefix=TTS_API_PREFIX
            ):
                with ui.element("div").classes("tts-row"):
                    with ui.element("span").classes("t"):
                        ui.html("TTSモード")
                    with ui.element("div").classes("end"):
                        mode_select = (
                            ui.select(options=GEN_SERVER_TTS_MODE_OPTIONS, value=mode_state["value"])
                            .props("outlined dense")
                            .classes("p3-fd")
                        )
                        chip_button("パラメータ設定", lambda: _open_params_dialog())
                    with ui.element("span").classes("d"):
                        ui.html("パラメータ設定は固有の上書き(クリア可)")
                if mode_state["value"] == CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3:
                    with ui.element("div").classes("tts-row"):
                        with ui.element("span").classes("t"):
                            ui.html("キャプション")
                        with ui.element("div").classes("end").style("flex: 1;"):
                            caption_input = (
                                ui.textarea(
                                    value=current_settings.voice_caption,
                                    placeholder=target.voice_design_caption_placeholder,
                                )
                                .props("outlined rows=2 dense")
                                .classes("p3-fd")
                                .style("flex: 1; min-width: 240px;")
                            )
                            if target.caption_generation_enabled:
                                caption_btn = chip_button(
                                    "シートから生成",
                                    lambda: _generate_caption(),
                                    title="キャラクターシートからキャプションを生成",
                                )

            voice_id_input = None
            if selected_endpoint is not None and selected_endpoint.provider == TTS_PROVIDER_IRODORI_SERVER:
                default_voice_id = (
                    target.default_voice_id(sheet)
                    if target.default_voice_id is not None
                    else ctx.tts.voice_id_for_character(target.tts_id, current_settings.voice_id)
                )
                with ui.element("div").classes("tts-row"):
                    with ui.element("span").classes("t"):
                        ui.html("Voice ID")
                    with ui.element("div").classes("end"):
                        voice_id_input = (
                            ui.input(
                                value=current_settings.voice_id or default_voice_id
                                if target.fill_default_voice_id
                                else current_settings.voice_id,
                                placeholder=default_voice_id,
                            )
                            .props("outlined dense clearable")
                            .classes("p3-fd")
                        )
                        if target.show_irodori_controls and voice_path is not None:
                            chip_button("Irodoriに登録", lambda: _register_voice())
                            chip_button("登録を削除", lambda: _delete_voice())
                    with ui.element("span").classes("d"):
                        ui.html(html.escape(f"既定値: {default_voice_id}"))

        with ui.element("div").style("margin-top: 18px;"):
            with ui.element("span").classes("fl").style(
                "display: block; font-size: 11px; letter-spacing: .14em; color: var(--muted); margin-bottom: 6px;"
            ):
                ui.html("試し読みのテキスト")
            tts_text = (
                ui.textarea(value=_sheet_text(target.tts_text, sheet))
                .props("outlined rows=2")
                .classes("p3-fd")
            )
        with ui.element("div").classes("tts-go"):
            synth_btn = p3_button("読み上げ", lambda: _synthesize(), classes="btn primary")
            synth_btn.mark("ui2-media-tts-synthesize")
            p3_button("TTS設定を保存", lambda: _save_settings(), classes="btn quiet").mark("ui2-media-tts-save")
            tts_status = ui.element("span").classes("ws-status")
            play_container = ui.element("div").classes("tts-play")

    def _set_status(text: str) -> None:
        tts_status.clear()
        with tts_status:
            ui.html(html.escape(text))

    def _current_settings() -> CharacterTTSSettings:
        api_type, endpoint_id = parse_voice_api_value(
            endpoint_select.value, gen_server_api_value=api_value, tts_api_prefix=TTS_API_PREFIX
        )
        selected_mode = (
            normalize_gen_server_tts_mode(mode_select.value) if mode_select is not None else mode_state["value"]
        )
        caption = (
            str(caption_input.value or "").strip()
            if caption_input is not None
            else current_settings.voice_caption.strip()
        )
        return CharacterTTSSettings(
            api_type=api_type,
            endpoint_id=endpoint_id,
            voice_id=str(voice_id_input.value or "").strip() if voice_id_input else current_settings.voice_id,
            gen_server_tts_mode=selected_mode,
            voice_caption=caption,
            gen_server_params=clean_gen_server_mode_defaults(
                gen_server_backend_mode(selected_mode),
                dict(params_state["value"]),
            ),
        )

    async def _save_settings(*, notify: bool = True) -> CharacterTTSSettings:
        settings = _current_settings()
        if target.update_tts_settings is None:
            raise RuntimeError("TTS設定の保存処理が設定されていません。")
        target.apply_saved(await target.update_tts_settings(settings))
        if notify:
            ui.notify(target.tts_save_message, type="positive")
        return settings

    async def _on_api_change(_) -> None:
        await _save_settings(notify=False)
        refresh()

    endpoint_select.on_value_change(_on_api_change)

    if mode_select is not None:

        async def _on_mode_change(_) -> None:
            mode_state["value"] = normalize_gen_server_tts_mode(mode_select.value)
            params_state["value"] = clean_gen_server_mode_defaults(
                gen_server_backend_mode(mode_state["value"]),
                params_state["value"],
            )
            await _save_settings(notify=False)
            refresh()

        mode_select.on_value_change(_on_mode_change)

    def _open_params_dialog() -> None:
        backend_mode = gen_server_backend_mode(mode_state["value"])
        fields = GEN_SERVER_DEFAULT_FIELDS.get(backend_mode, {})
        defaults = ctx.api_config.get_gen_server_config().defaults_for_mode(backend_mode)
        current = {**defaults, **clean_gen_server_mode_defaults(backend_mode, params_state["value"])}
        controls: dict[str, Any] = {}

        with ui.dialog() as dlg, ui.card().classes("w-full max-w-2xl").style(_DIALOG_CARD_STYLE):
            ui.label("Wizmy-Gen-Server パラメータ").classes("text-base font-semibold mb-2")
            with ui.scroll_area().style("max-height: 60vh; width: 100%;"):
                with ui.grid(columns=2).classes("w-full gap-3 pr-2"):
                    for key, spec in fields.items():
                        value = current.get(key, spec.get("default"))
                        if key == "model_id":
                            with ui.row().classes("w-full col-span-2 items-end gap-2"):
                                model_input = (
                                    ui.input(label=str(spec.get("label", key)), value=value or "")
                                    .props("outlined dense clearable")
                                    .classes("p3-fd flex-1")
                                )
                                controls[key] = model_input

                                async def _fetch(model_input=model_input, backend_mode=backend_mode) -> None:
                                    endpoint_id = ctx.api_config.get_gen_server_config().assigned_endpoint_id(
                                        backend_mode
                                    )
                                    await open_model_id_picker(ctx, endpoint_id, backend_mode, model_input)

                                chip_button("取得", _fetch)
                        else:
                            controls[key] = build_param_control(key, spec, value)

            async def _clear() -> None:
                params_state["value"] = {}
                await _save_settings(notify=False)
                ui.notify("固有パラメータをクリアしました", type="positive")
                dlg.close()

            async def _save() -> None:
                values = {key: read_param_value(spec, controls[key].value) for key, spec in fields.items()}
                overrides = {
                    key: value
                    for key, value in values.items()
                    if value != defaults.get(key, fields[key].get("default"))
                }
                params_state["value"] = clean_gen_server_mode_defaults(backend_mode, overrides)
                await _save_settings(notify=False)
                ui.notify("パラメータを保存しました", type="positive")
                dlg.close()

            with ui.row().classes("justify-end gap-2 mt-3 w-full"):
                p3_button("固有設定をクリア", _clear, classes="btn quiet")
                p3_button("キャンセル", dlg.close, classes="btn quiet")
                p3_button("保存", _save, classes="btn primary")
        dlg.open()

    async def _generate_caption() -> None:
        if caption_input is None or caption_btn is None:
            return
        caption_btn.props("disabled")
        _set_status("キャプション生成中…")
        try:
            caption = await generate_voice_caption_from_sheet(target.sheet(), ctx)
            caption_input.set_value(caption)
            _set_status("")
            ui.notify("キャプションを生成しました", type="positive")
        except Exception as err:  # noqa: BLE001 - UI通知のための包括捕捉
            _set_status("")
            ui.notify(f"キャプション生成に失敗しました: {err}", type="negative", timeout=10000)
        finally:
            caption_btn.props(remove="disabled")

    async def _register_voice() -> None:
        if voice_path is None:
            ui.notify("先にキャラ音声を設定してください。", type="warning")
            return
        settings = await _save_settings(notify=False)
        try:
            await ctx.tts.register_voice(
                target.tts_id,
                voice_path,
                endpoint_id=settings.endpoint_id,
                voice_id=settings.voice_id,
                filename=voice.original_name if voice else "",
                content_type=voice.content_type if voice else "",
            )
            ui.notify("Irodori-TTS-Serverに登録しました", type="positive")
        except Exception as err:  # noqa: BLE001 - UI通知のための包括捕捉
            ui.notify(f"登録に失敗しました: {err}", type="negative")

    async def _delete_voice() -> None:
        settings = await _save_settings(notify=False)
        try:
            deleted = await ctx.tts.delete_voice(
                target.tts_id,
                endpoint_id=settings.endpoint_id,
                voice_id=settings.voice_id,
            )
            if deleted:
                ui.notify("Irodori-TTS-Serverから削除しました", type="positive")
            else:
                ui.notify("Irodori-TTS-Serverに登録されていません", type="info")
        except Exception as err:  # noqa: BLE001 - UI通知のための包括捕捉
            ui.notify(f"削除に失敗しました: {err}", type="negative")

    async def _synthesize() -> None:
        text = str(tts_text.value or "").strip()
        if not text:
            ui.notify("読み上げるテキストを入力してください", type="warning")
            return
        settings = await _save_settings(notify=False)
        if (
            settings.api_type == CHARACTER_TTS_API_GEN_SERVER
            and settings.gen_server_tts_mode == CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3
            and not settings.voice_caption.strip()
        ):
            ui.notify("ボイスデザインv3モードではキャプションを入力してください。", type="warning")
            return
        synth_btn.props("disabled")
        _set_status("生成中…")
        play_container.clear()
        try:

            def _save_preview(audio: bytes, job) -> dict[str, str]:
                if target.save_tts_preview is None:
                    raise RuntimeError("音声プレビューの保存処理が設定されていません。")
                # ボイスデザイン候補(preview-*)を消さないよう、試し読みは専用 prefix で保存する
                preview_path = target.save_tts_preview(audio, prefix="tryout")
                return {"result_url": target.result_url, "preview_path": str(preview_path)}

            job = ctx.tts.start_synthesize_job(
                target.tts_id,
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
                label=target.label("読み上げ"),
                scope=f"{target.scope_prefix}:tts",
                metadata=dict(target.metadata),
                result_handler=_save_preview,
            )
            finished = await ctx.ai_jobs.wait(job.id)
            if finished.status == AIJobStatus.CANCELLED:
                _set_status("")
                ui.notify("読み上げを停止しました", type="info")
                return
            if finished.status != AIJobStatus.SUCCEEDED:
                raise RuntimeError(finished.error_message or "読み上げに失敗しました。")
            preview_path = finished.result_meta.get("preview_path")
            if not preview_path:
                raise RuntimeError("読み上げ音声を取得できませんでした。")
            play_container.clear()
            with play_container:
                ui.audio(preview_path)
            _set_status("")
            ui.notify("読み上げ音声を生成しました", type="positive")
        except Exception as err:  # noqa: BLE001 - UI通知のための包括捕捉
            _set_status("")
            ui.notify(f"読み上げに失敗しました: {err}", type="negative", timeout=10000)
        finally:
            synth_btn.props(remove="disabled")
