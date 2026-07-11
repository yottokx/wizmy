"""/groups/new 新しいグループ(作成フロー)。

一覧(/groups)から分離した専用ページ。フロー本体は groups.py の
`_render_create_flow` を共用する。
※ルートは /groups/{group_id}(pages/group.py)より先に登録される必要がある。
  pages/__init__ の import はアルファベット順のため create_group が group より
  先に読み込まれることで成立している。
"""

from __future__ import annotations

from nicegui import ui

from ...app_context import get_context
from ..group_setup import PICKER_CSS
from ..scaffold import p3_page
from .groups import _PAGE_CSS, _render_create_flow


@ui.page("/groups/new")
async def ui2_group_create_page() -> None:
    ctx = get_context()
    with p3_page("グループ"):
        ui.add_css(_PAGE_CSS + PICKER_CSS)
        with ui.element("div").classes("wrap"):
            with ui.element("div").classes("page-head"):
                back = ui.element("button").classes("btn quiet")
                with back:
                    ui.html("← グループ一覧へ")
                back.on("click", lambda: ui.navigate.to("/groups"))
                with ui.element("h1").classes("serif"):
                    ui.html("新しいグループ")
            with ui.element("section").classes("create"):
                ui.element("div").classes("sparkle-field").props('data-count="12"')
                _render_create_flow(ctx)
