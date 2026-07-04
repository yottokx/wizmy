from __future__ import annotations

from nicegui import ui

from .chat_modes import build_chat_modes_tab
from .endpoints import build_endpoints_tab
from .presets import build_options_tab, build_presets_tab
from .profiles import build_profiles_tab
from .user_personas import build_user_personas_tab


async def build_llm_settings_tab(ctx) -> None:
    sub_tabs = ui.tabs().classes("w-full")
    with sub_tabs:
        tab_endpoints = ui.tab("エンドポイント", icon="cloud")
        tab_profiles = ui.tab("LLMプロファイル", icon="tune")

    with ui.tab_panels(sub_tabs, value=tab_endpoints).classes("w-full mt-3"):
        with ui.tab_panel(tab_endpoints):
            await build_endpoints_tab(ctx)
        with ui.tab_panel(tab_profiles):
            await build_profiles_tab(ctx)


async def build_character_generation_settings_tab(ctx) -> None:
    sub_tabs = ui.tabs().classes("w-full")
    with sub_tabs:
        tab_presets = ui.tab("生成プリセット", icon="bookmark")
        tab_options = ui.tab("生成オプション", icon="list")

    with ui.tab_panels(sub_tabs, value=tab_presets).classes("w-full mt-3"):
        with ui.tab_panel(tab_presets):
            await build_presets_tab(ctx)
        with ui.tab_panel(tab_options):
            build_options_tab(ctx)


async def build_chat_settings_tab(ctx) -> None:
    sub_tabs = ui.tabs().classes("w-full")
    with sub_tabs:
        tab_chat_modes = ui.tab("チャットモード", icon="forum")
        tab_personas = ui.tab("ユーザーペルソナ", icon="badge")

    with ui.tab_panels(sub_tabs, value=tab_chat_modes).classes("w-full mt-3"):
        with ui.tab_panel(tab_chat_modes):
            await build_chat_modes_tab(ctx)
        with ui.tab_panel(tab_personas):
            await build_user_personas_tab(ctx)
