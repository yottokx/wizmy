"""
/v2/characters/{id}/voice と /v2/groups/{gid}/members/{mid}/voice(Phase 6)。

モック media-voice.html 準拠。音声(いま)+ボイスデザイン(常設)+TTS設定。
描画は `media_ui.py` の共有レンダラで、保存先だけ MediaTarget で差し替える。
"""

from __future__ import annotations

import html

from nicegui import ui

from ...app_context import get_context
from ..media_ui import (
    MEDIA_CSS,
    MediaTarget,
    character_media_target,
    group_member_media_target,
    p3_button,
    render_tts_settings,
    render_voice_design,
    render_voice_now,
)
from ..scaffold import p3_page


def _render_not_found(message: str, back_route: str, back_label: str) -> None:
    with ui.element("div").style("max-width: 640px; margin: 0 auto; padding: 60px 26px;"):
        ui.label(message).classes("note").style("font-size: 14px;")
        with ui.element("div").style("margin-top: 18px;"):
            p3_button(back_label, lambda route=back_route: ui.navigate.to(route))


def _render_voice_page(ctx, target: MediaTarget, *, back_route: str, back_label: str) -> None:
    ui.add_css(MEDIA_CSS)
    with ui.element("div").classes("wrap"):
        with ui.element("div").classes("mhead"):
            p3_button(back_label, lambda: ui.navigate.to(back_route), classes="btn quiet")
            with ui.element("div").classes("t"):
                with ui.element("h1").classes("serif"):
                    ui.html(html.escape(target.name))
                with ui.element("div").classes("sub"):
                    ui.html("音声 — 声の差し替え・ボイスデザイン・読み上げ設定")

        with ui.element("div").classes("state-lbl"):
            ui.html("音声")
        now_container = ui.element("div").mark("ui2-media-voice-now")

        with ui.element("div").classes("state-lbl"):
            ui.html("ボイスデザイン")
        design_container = ui.element("div")

        with ui.element("div").classes("state-lbl"):
            ui.html("TTS設定")
        tts_container = ui.element("div").mark("ui2-media-tts")

        def _refresh() -> None:
            # 音声・TTS設定は保存で状態が変わるため再描画する。
            # ボイスデザインは候補の聴き比べ状態を保持するため据え置き。
            now_container.clear()
            with now_container:
                render_voice_now(ctx, target, _refresh)
            tts_container.clear()
            with tts_container:
                render_tts_settings(ctx, target, _refresh)

        _refresh()
        with design_container:
            render_voice_design(ctx, target, _refresh)


@ui.page("/v2/characters/{character_id}/voice")
async def ui2_character_voice_page(character_id: str) -> None:
    ctx = get_context()
    sheet = await ctx.characters.get(character_id)
    if sheet is None:
        with p3_page("キャラクター"):
            _render_not_found("指定されたキャラクターは存在しません。", "/v2/characters", "キャラクター一覧へ")
        return

    state: dict = {"sheet": sheet}
    target = character_media_target(ctx, character_id, state)
    with p3_page("キャラクター"):
        _render_voice_page(
            ctx,
            target,
            back_route=f"/v2/characters/{character_id}",
            back_label="← シートへ",
        )


@ui.page("/v2/groups/{group_id}/members/{member_id}/voice")
async def ui2_group_member_voice_page(group_id: str, member_id: str) -> None:
    ctx = get_context()
    group = await ctx.group_chats.get(group_id)
    if group is None:
        with p3_page("グループ"):
            _render_not_found("指定されたグループは存在しません。", "/v2/groups", "グループ一覧へ")
        return
    member = next((item for item in group.members if item.id == member_id), None)
    if member is None:
        with p3_page("グループ"):
            _render_not_found(
                "指定されたメンバーはこのグループに存在しません。",
                f"/v2/groups/{group.id}",
                "グループへ戻る",
            )
        return

    state: dict = {"member": member}
    target = group_member_media_target(ctx, group, member_id, state)
    with p3_page("グループ"):
        _render_voice_page(
            ctx,
            target,
            back_route=f"/v2/groups/{group_id}/members/{member_id}",
            back_label="← シートへ",
        )
