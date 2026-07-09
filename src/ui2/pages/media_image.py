"""
/characters/{id}/images と /groups/{gid}/members/{mid}/images(Phase 6)。

モック media-image.html 準拠。画像の管理(いま)+画像生成ワークスペース(常設)。
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
    render_image_now,
    render_image_workspace,
)
from ..scaffold import p3_page


def _render_not_found(message: str, back_route: str, back_label: str) -> None:
    with ui.element("div").style("max-width: 640px; margin: 0 auto; padding: 60px 26px;"):
        ui.label(message).classes("note").style("font-size: 14px;")
        with ui.element("div").style("margin-top: 18px;"):
            p3_button(back_label, lambda route=back_route: ui.navigate.to(route))


def _render_image_page(ctx, target: MediaTarget, *, back_route: str, back_label: str) -> None:
    ui.add_css(MEDIA_CSS)
    with ui.element("div").classes("wrap"):
        with ui.element("div").classes("mhead"):
            p3_button(back_label, lambda: ui.navigate.to(back_route), classes="btn quiet")
            with ui.element("div").classes("t"):
                with ui.element("h1").classes("serif"):
                    ui.html(html.escape(target.name))
                with ui.element("div").classes("sub"):
                    ui.html("画像 — 立ち絵・顔範囲・画像生成")

        with ui.element("div").classes("state-lbl"):
            ui.html("画像")
        now_container = ui.element("div").mark("ui2-media-image-now")

        with ui.element("div").classes("state-lbl"):
            ui.html("画像生成")

        def _refresh_now() -> None:
            now_container.clear()
            with now_container:
                render_image_now(ctx, target, _refresh_now)

        _refresh_now()
        # ワークスペースは常設(候補の状態を保持するため、保存後も再描画しない)
        render_image_workspace(ctx, target, _refresh_now)


@ui.page("/characters/{character_id}/images")
async def ui2_character_images_page(character_id: str) -> None:
    ctx = get_context()
    sheet = await ctx.characters.get(character_id)
    if sheet is None:
        with p3_page("キャラクター"):
            _render_not_found("指定されたキャラクターは存在しません。", "/characters", "キャラクター一覧へ")
        return

    state: dict = {"sheet": sheet}
    target = character_media_target(ctx, character_id, state)
    with p3_page("キャラクター"):
        _render_image_page(
            ctx,
            target,
            back_route=f"/characters/{character_id}",
            back_label="← シートへ",
        )


@ui.page("/groups/{group_id}/members/{member_id}/images")
async def ui2_group_member_images_page(group_id: str, member_id: str) -> None:
    ctx = get_context()
    group = await ctx.group_chats.get(group_id)
    if group is None:
        with p3_page("グループ"):
            _render_not_found("指定されたグループは存在しません。", "/groups", "グループ一覧へ")
        return
    member = next((item for item in group.members if item.id == member_id), None)
    if member is None:
        with p3_page("グループ"):
            _render_not_found(
                "指定されたメンバーはこのグループに存在しません。",
                f"/groups/{group.id}",
                "グループへ戻る",
            )
        return

    state: dict = {"member": member}
    target = group_member_media_target(ctx, group, member_id, state)
    with p3_page("グループ"):
        _render_image_page(
            ctx,
            target,
            back_route=f"/groups/{group_id}/members/{member_id}",
            back_label="← シートへ",
        )
