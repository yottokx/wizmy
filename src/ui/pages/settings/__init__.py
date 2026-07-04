from __future__ import annotations

from nicegui import ui

from ....app_context import get_context
from ...layout import page_layout
from .appearance import build_appearance_tab
from .common import install_drag_sort_script
from .llm_defaults import (
    build_character_generation_settings_tab,
    build_chat_settings_tab,
    build_llm_settings_tab,
)
from .media_generation import build_media_generation_tab
from .vault import build_vault_tab


@ui.page("/settings")
async def settings_page() -> None:
    ctx = get_context()
    install_drag_sort_script()

    with page_layout("設定"):
        tabs = ui.tabs().classes("w-full")
        with tabs:
            tab_llm = ui.tab("LLM", icon="psychology")
            tab_character_generation = ui.tab("キャラクター生成", icon="auto_awesome")
            tab_chat = ui.tab("チャット", icon="forum")
            tab_media_generation = ui.tab("画像&音声生成", icon="perm_media")
            tab_vault = ui.tab("APIキーボルト", icon="lock")
            tab_appearance = ui.tab("外観", icon="palette")

        with ui.tab_panels(tabs, value=tab_llm).classes("w-full mt-4"):
            with ui.tab_panel(tab_llm):
                await build_llm_settings_tab(ctx)
            with ui.tab_panel(tab_character_generation):
                await build_character_generation_settings_tab(ctx)
            with ui.tab_panel(tab_chat):
                await build_chat_settings_tab(ctx)
            with ui.tab_panel(tab_media_generation):
                build_media_generation_tab(ctx)
            with ui.tab_panel(tab_vault):
                await build_vault_tab(ctx)
            with ui.tab_panel(tab_appearance):
                build_appearance_tab()


__all__ = ["settings_page"]
