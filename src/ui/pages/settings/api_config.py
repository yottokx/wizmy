"""
API設定ページ。

LLM、チャット、画像・音声生成、KeyVault、外観の設定を提供する。
"""

from __future__ import annotations

import uuid

from pydantic import ValidationError

from nicegui import ui

from ....app_context import get_context
from ....core.chat.schemas import ChatMode, UserPersona
from ....core.chat.templates import TemplateError, validate_chat_mode_templates
from ....core.gen_server.schemas import (
    GEN_SERVER_DEFAULT_FIELDS,
    GEN_SERVER_MODE_SDXL_IMAGE,
    GEN_SERVER_MODE_LABELS,
    GEN_SERVER_MODES,
    GenServerEndpoint,
)
from ....core.image_generation.schemas import (
    IMAGE_GENERATION_PARAMETER_FIELDS,
    IMAGE_PROVIDER_LABELS,
    IMAGE_PROVIDER_WIZMY_GEN_SERVER,
    ImageGenerationProfile,
    clean_image_generation_params,
    default_image_generation_params,
)
from ....core.llm.schemas import Endpoint, LLMProfile
from ....core.tts.schemas import (
    TTS_PROVIDER_IRODORI_GRADIO,
    TTS_PROVIDER_IRODORI_SERVER,
    TTSEndpoint,
)
from ...layout import THEMES, DEFAULT_THEME, apply_theme_js, page_layout
from ...state import (
    clear_vault_password,
    get_vault_password,
    is_vault_unlocked,
    set_vault_password,
)


_SORTABLE_FILTER = (
    "button, input, textarea, select, .q-btn, .q-field, .q-checkbox, "
    ".q-slider, .q-menu, [role=button]"
)
_GEN_SERVER_ASSIGNABLE_MODES = tuple(mode for mode in GEN_SERVER_MODES if mode != GEN_SERVER_MODE_SDXL_IMAGE)


def _moved_order(ids: list[str], old_index: int, new_index: int) -> list[str] | None:
    if old_index == new_index:
        return None
    if old_index < 0 or old_index >= len(ids) or new_index < 0 or new_index >= len(ids):
        return None
    moved = ids.pop(old_index)
    ids.insert(new_index, moved)
    return ids


def _notify_order_saved() -> None:
    ui.notify("並び順を保存しました", type="positive", timeout=1200)


def _install_drag_sort_script() -> None:
    ui.add_body_html(f"""
<script>
(() => {{
  if (window.charagenSetupSortable) return;

  const interactiveSelector = {_SORTABLE_FILTER!r};
  const pending = new Set();

  const style = document.createElement('style');
  style.textContent = `
    .charagen-sortable-item {{ cursor: grab; touch-action: none; }}
    .charagen-sortable-item.charagen-dragging {{
      cursor: grabbing;
      box-shadow: 0 18px 36px rgba(0, 0, 0, .22);
      opacity: .96;
      pointer-events: none;
      transform: scale(1.01);
      z-index: 10000;
    }}
    .charagen-sortable-placeholder {{
      min-height: 72px;
      border: 1px dashed var(--cs-accent);
      border-radius: 4px;
      background: var(--cs-accent-bg);
      box-sizing: border-box;
    }}
    body.charagen-sort-active,
    body.charagen-sort-active * {{
      cursor: grabbing !important;
    }}
  `;
  document.head.appendChild(style);

  const isInteractive = target =>
    target instanceof Element && Boolean(target.closest(interactiveSelector));

  const directChildOf = (container, target) => {{
    let node = target;
    while (node && node.parentElement !== container) node = node.parentElement;
    return node && node.parentElement === container ? node : null;
  }};

  const sortableChildren = container =>
    [...container.children].filter(child => !child.classList.contains('charagen-sortable-placeholder'));

  const itemAfter = (container, y) => {{
    const siblings = sortableChildren(container);
    return siblings.reduce((closest, child) => {{
      const box = child.getBoundingClientRect();
      const offset = y - box.top - box.height / 2;
      if (offset < 0 && offset > closest.offset) {{
        return {{ offset, element: child }};
      }}
      return closest;
    }}, {{ offset: Number.NEGATIVE_INFINITY, element: null }}).element;
  }};

  const setup = id => {{
    const container = document.getElementById(id);
    if (!container) {{
      pending.add(id);
      return;
    }}
    pending.delete(id);
    if (container.dataset.charagenSortable === '1') return;
    container.dataset.charagenSortable = '1';

    let dragged = null;
    let placeholder = null;
    let oldIndex = -1;
    let startY = 0;
    let active = false;
    let pointerId = null;
    let offsetX = 0;
    let offsetY = 0;
    let previousUserSelect = '';
    let previousStyle = {{}};

    const refreshItems = () => {{
      [...container.children].forEach(child => {{
        if (child.classList.contains('charagen-sortable-placeholder')) return;
        child.draggable = false;
        child.classList.add('charagen-sortable-item');
      }});
    }};
    refreshItems();
    new MutationObserver(refreshItems).observe(container, {{ childList: true }});

    container.addEventListener('pointerdown', event => {{
      if (isInteractive(event.target)) return;
      const item = directChildOf(container, event.target);
      if (!item) return;
      dragged = item;
      oldIndex = sortableChildren(container).indexOf(item);
      startY = event.clientY;
      active = false;
      pointerId = event.pointerId;
      item.setPointerCapture?.(event.pointerId);
    }}, true);

    const startFloating = event => {{
      const rect = dragged.getBoundingClientRect();
      offsetX = event.clientX - rect.left;
      offsetY = event.clientY - rect.top;
      previousUserSelect = document.body.style.userSelect;
      previousStyle = {{
        position: dragged.style.position,
        left: dragged.style.left,
        top: dragged.style.top,
        width: dragged.style.width,
        margin: dragged.style.margin,
        transition: dragged.style.transition,
      }};

      placeholder = document.createElement('div');
      placeholder.className = 'charagen-sortable-placeholder';
      placeholder.style.height = `${{rect.height}}px`;
      container.insertBefore(placeholder, dragged);

      Object.assign(dragged.style, {{
        position: 'fixed',
        left: `${{rect.left}}px`,
        top: `${{rect.top}}px`,
        width: `${{rect.width}}px`,
        margin: '0',
        transition: 'none',
      }});
      document.body.appendChild(dragged);
      document.body.style.userSelect = 'none';
      document.body.classList.add('charagen-sort-active');
      dragged.classList.add('charagen-dragging');
      active = true;
    }};

    const moveFloating = event => {{
      dragged.style.left = `${{event.clientX - offsetX}}px`;
      dragged.style.top = `${{event.clientY - offsetY}}px`;
      const after = itemAfter(container, event.clientY);
      if (after) container.insertBefore(placeholder, after);
      else container.appendChild(placeholder);
    }};

    window.addEventListener('pointermove', event => {{
      if (!dragged) return;
      if (!active) {{
        if (Math.abs(event.clientY - startY) < 6) return;
        startFloating(event);
      }}
      event.preventDefault();
      moveFloating(event);
    }}, true);

    const finishDrag = () => {{
      if (!dragged) return;
      const newIndex = placeholder ? [...container.children].indexOf(placeholder) : oldIndex;
      try {{ dragged.releasePointerCapture?.(pointerId); }} catch {{}}
      if (placeholder) {{
        container.insertBefore(dragged, placeholder);
        placeholder.remove();
      }}
      dragged.classList.remove('charagen-dragging');
      document.body.classList.remove('charagen-sort-active');
      document.body.style.userSelect = previousUserSelect;
      Object.assign(dragged.style, previousStyle);
      if (active && oldIndex >= 0 && newIndex >= 0 && oldIndex !== newIndex) {{
        container.dispatchEvent(new CustomEvent('charagen-sortable-end', {{
          detail: {{ old_index: oldIndex, new_index: newIndex }},
          bubbles: true,
        }}));
      }}
      dragged = null;
      placeholder = null;
      oldIndex = -1;
      startY = 0;
      active = false;
      pointerId = null;
      offsetX = 0;
      offsetY = 0;
      previousStyle = {{}};
    }};

    window.addEventListener('pointerup', finishDrag, true);
    window.addEventListener('pointercancel', finishDrag, true);
  }};

  new MutationObserver(() => {{
    [...pending].forEach(setup);
  }}).observe(document.body, {{ childList: true, subtree: true }});

  window.charagenSetupSortable = setup;
}})();
</script>
""")


def _enable_drag_sort(container, handler) -> None:
    container.on(
        "charagen-sortable-end",
        handler,
        js_handler="event => emit(event.detail)",
    )
    ui.timer(
        0.1,
        lambda c=container: ui.run_javascript(
            f"window.charagenSetupSortable && window.charagenSetupSortable('{c.html_id}')"
        ),
        once=True,
    )


@ui.page("/settings")
async def settings_page() -> None:
    ctx = get_context()
    _install_drag_sort_script()

    with page_layout("設定"):
        tabs = ui.tabs().classes("w-full")
        with tabs:
            tab_endpoints = ui.tab("エンドポイント", icon="cloud")
            tab_profiles = ui.tab("LLMプロファイル", icon="tune")
            tab_chat_modes = ui.tab("チャットモード", icon="forum")
            tab_personas = ui.tab("ユーザーペルソナ", icon="badge")
            tab_presets = ui.tab("生成プリセット", icon="bookmark")
            tab_vault = ui.tab("APIキーボルト", icon="lock")
            tab_options = ui.tab("生成オプション", icon="list")
            tab_media_generation = ui.tab("画像&音声生成", icon="perm_media")
            tab_appearance = ui.tab("外観", icon="palette")

        with ui.tab_panels(tabs, value=tab_endpoints).classes("w-full mt-4"):
            with ui.tab_panel(tab_endpoints):
                await _build_endpoints_tab(ctx)
            with ui.tab_panel(tab_profiles):
                await _build_profiles_tab(ctx)
            with ui.tab_panel(tab_chat_modes):
                await _build_chat_modes_tab(ctx)
            with ui.tab_panel(tab_personas):
                await _build_user_personas_tab(ctx)
            with ui.tab_panel(tab_presets):
                await _build_presets_tab(ctx)
            with ui.tab_panel(tab_vault):
                await _build_vault_tab(ctx)
            with ui.tab_panel(tab_options):
                _build_options_tab(ctx)
            with ui.tab_panel(tab_media_generation):
                _build_media_generation_tab(ctx)
            with ui.tab_panel(tab_appearance):
                _build_appearance_tab()


# ══════════════════════════════════════════
# エンドポイント タブ
# ══════════════════════════════════════════

async def _build_endpoints_tab(ctx) -> None:
    endpoints_container = ui.column().classes("w-full gap-3")

    async def reorder(e) -> None:
        args = e.args
        ordered = _moved_order(
            [ep.id for ep in ctx.api_config.get_endpoints()],
            args["old_index"],
            args["new_index"],
        )
        if ordered is None:
            return
        ctx.api_config.reorder_endpoints(ordered)
        _notify_order_saved()

    _enable_drag_sort(endpoints_container, reorder)

    async def refresh() -> None:
        endpoints = ctx.api_config.get_endpoints()
        endpoints_container.clear()
        with endpoints_container:
            if not endpoints:
                ui.label("エンドポイントが登録されていません").classes("text-grey-6 py-4")
            for ep in endpoints:
                _endpoint_card(ep, ctx, refresh)

    await refresh()

    ui.button(
        "エンドポイントを追加",
        icon="add",
        on_click=lambda: _open_endpoint_dialog(None, ctx, refresh),
    ).props("color=primary unelevated").classes("mt-2")


def _endpoint_card(ep: Endpoint, ctx, refresh_fn) -> None:
    type_labels = {"ollama": "Ollama", "openai_compat": "OpenAI互換"}
    type_colors = {"ollama": "green", "openai_compat": "blue"}
    key_set = ctx.api_config.is_api_key_configured(ep.id) if ep.type == "openai_compat" else False

    with ui.card().classes("w-full cursor-grab"):
        with ui.card_section():
            with ui.row().classes("items-center gap-3 flex-wrap"):
                with ui.column().classes("flex-1 gap-1"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label(ep.name).classes("text-base font-semibold")
                        color = type_colors.get(ep.type, "grey")
                        ui.badge(type_labels.get(ep.type, ep.type)).props(f"color={color}")
                    ui.label(ep.base_url).classes("text-sm text-grey-6 font-mono")
                    if ep.type == "openai_compat":
                        with ui.row().classes("items-center gap-2 mt-1"):
                            ui.icon("key").classes(
                                "text-positive text-sm" if key_set else "text-grey-4 text-sm"
                            )
                            ui.label("APIキー設定済" if key_set else "APIキー未設定").classes(
                                "text-xs " + ("text-positive" if key_set else "text-grey-5")
                            )
                            if not is_vault_unlocked():
                                ui.label("（ボルトをロック解除してください）").classes("text-xs text-warning")
                            else:
                                ui.button(
                                    "削除" if key_set else "設定",
                                    icon="delete" if key_set else "add",
                                    on_click=lambda e=ep, ks=key_set: (
                                        _delete_endpoint_key(e, ctx, refresh_fn) if ks
                                        else _open_key_dialog(e, ctx, refresh_fn)
                                    ),
                                ).props(f"flat size=xs color={'negative' if key_set else 'primary'}")

                with ui.row().classes("gap-2"):
                    status_icon = ui.icon("circle").classes("text-grey-4 text-base")
                    ui.button(
                        icon="wifi_tethering",
                        on_click=lambda e=ep: _test_connection(e, status_icon, ctx),
                    ).props("flat round dense").tooltip("接続テスト")
                    ui.button(
                        icon="edit",
                        on_click=lambda e=ep: _open_endpoint_dialog(e, ctx, refresh_fn),
                    ).props("flat round dense color=primary")
                    ui.button(
                        icon="delete",
                        on_click=lambda e=ep: _confirm_delete_endpoint(e, ctx, refresh_fn),
                    ).props("flat round dense color=negative")


async def _delete_endpoint_key(ep: Endpoint, ctx, refresh_fn) -> None:
    ctx.api_config.delete_api_key(ep.id)
    ui.notify(f"「{ep.name}」のAPIキーを削除しました", type="positive")
    await refresh_fn()


async def _test_connection(ep: Endpoint, status_icon: ui.icon, ctx) -> None:
    status_icon.classes("text-grey-4")
    vault_pw = get_vault_password()
    ok = await ctx.api_config.test_connection(ep.id, vault_pw)
    if ok:
        status_icon.classes(remove="text-grey-4 text-negative").classes("text-positive")
        ui.notify(f"「{ep.name}」に接続できました", type="positive")
    else:
        status_icon.classes(remove="text-grey-4 text-positive").classes("text-negative")
        ui.notify(f"「{ep.name}」に接続できませんでした", type="negative")


def _open_endpoint_dialog(ep: Endpoint | None, ctx, refresh_fn) -> None:
    is_edit = ep is not None

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg"):
        ui.label("エンドポイントを編集" if is_edit else "エンドポイントを追加").classes(
            "text-lg font-semibold mb-3"
        )
        name_input = ui.input(
            label="表示名", value=ep.name if ep else ""
        ).classes("w-full")
        type_select = ui.select(
            options={"ollama": "Ollama", "openai_compat": "OpenAI互換"},
            value=ep.type if ep else "ollama",
            label="プロバイダー種別",
        ).classes("w-full")
        url_input = ui.input(
            label="ベースURL",
            value=ep.base_url if ep else "http://localhost:11434",
            placeholder="http://localhost:11434",
        ).classes("w-full")

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("保存", on_click=lambda: _save_endpoint(dlg)).props(
                "color=primary unelevated"
            )

    async def _save_endpoint(dlg) -> None:
        name = name_input.value.strip()
        url = url_input.value.strip()
        if not name or not url:
            ui.notify("表示名とURLを入力してください", type="negative")
            return
        if is_edit:
            updated = ep.model_copy(update={
                "name": name,
                "type": type_select.value,
                "base_url": url,
            })
            ctx.api_config.update_endpoint(updated)
        else:
            ctx.api_config.create_endpoint(name, type_select.value, url)
        ui.notify("保存しました", type="positive")
        dlg.close()
        await refresh_fn()

    dlg.open()


def _confirm_delete_endpoint(ep: Endpoint, ctx, refresh_fn) -> None:
    with ui.dialog() as dlg, ui.card():
        ui.label(f"「{ep.name}」を削除しますか？").classes("font-medium mb-2")
        ui.label("このエンドポイントを使用するLLMプロファイルも影響を受けます。").classes(
            "text-sm text-grey-6"
        )
        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")

            async def _do_delete() -> None:
                ctx.api_config.delete_endpoint(ep.id)
                ui.notify(f"「{ep.name}」を削除しました", type="positive")
                dlg.close()
                await refresh_fn()

            ui.button("削除", on_click=_do_delete).props("color=negative unelevated")
    dlg.open()


# ══════════════════════════════════════════
# LLMプロファイル タブ
# ══════════════════════════════════════════

async def _build_profiles_tab(ctx) -> None:
    profiles_container = ui.column().classes("w-full gap-3")
    app_config = ctx.api_config.get_app_llm_config()
    default_ids = {
        "generation": app_config.generation_profile_id,
        "chat": app_config.chat_profile_id,
    }

    async def reorder(e) -> None:
        args = e.args
        ordered = _moved_order(
            [profile.id for profile in ctx.api_config.get_llm_profiles()],
            args["old_index"],
            args["new_index"],
        )
        if ordered is None:
            return
        ctx.api_config.reorder_llm_profiles(ordered)
        _notify_order_saved()

    _enable_drag_sort(profiles_container, reorder)

    async def refresh() -> None:
        profiles = ctx.api_config.get_llm_profiles()
        endpoints = {ep.id: ep for ep in ctx.api_config.get_endpoints()}
        app_config = ctx.api_config.get_app_llm_config()
        default_ids["generation"] = app_config.generation_profile_id
        default_ids["chat"] = app_config.chat_profile_id
        profiles_container.clear()
        with profiles_container:
            if not profiles:
                ui.label("LLMプロファイルが登録されていません").classes("text-grey-6 py-4")
            for p in profiles:
                ep = endpoints.get(p.endpoint_id)
                _profile_card(p, ep, ctx, refresh, default_ids)

    await refresh()

    ui.button(
        "プロファイルを追加",
        icon="add",
        on_click=lambda: _open_profile_dialog(None, ctx, refresh),
    ).props("color=primary unelevated").classes("mt-2")


def _profile_card(
    profile: LLMProfile, endpoint, ctx, refresh_fn, default_ids: dict,
) -> None:
    ep_name = endpoint.name if endpoint else "不明なエンドポイント"
    is_generation_default = profile.id == default_ids["generation"]
    is_chat_default = profile.id == default_ids["chat"]
    caps = ctx.api_config.get_llm_parameter_capabilities(profile.endpoint_id)

    with ui.card().classes("w-full cursor-grab"):
        with ui.card_section():
            with ui.row().classes("items-center gap-3 flex-wrap"):
                with ui.column().classes("flex-1 gap-1"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label(profile.name).classes("text-base font-semibold")
                        if is_generation_default:
                            ui.badge("生成").props("color=primary")
                        if is_chat_default:
                            ui.badge("チャット").props("color=secondary")
                    with ui.row().classes("gap-4 text-sm text-grey-6"):
                        ui.label(ep_name)
                        ui.label(f"モデル: {profile.model_id or '未設定'}")
                        if caps.temperature and not (caps.reasoning and profile.reasoning_enabled):
                            ui.label(f"T={profile.temperature}")
                        if caps.reasoning and profile.reasoning_enabled:
                            ui.badge("Reasoning").props("color=deep-purple outline")

                with ui.row().classes("gap-2"):
                    ui.button(
                        icon="star",
                        on_click=lambda p=profile: _open_default_profile_dialog(
                            p, ctx, refresh_fn, default_ids
                        ),
                    ).props("flat round dense color=amber").tooltip("生成/チャットの既定を選択")
                    ui.button(
                        icon="content_copy",
                        on_click=lambda p=profile: _dup_profile(p, ctx, refresh_fn),
                    ).props("flat round dense").tooltip("複製")
                    ui.button(
                        icon="edit",
                        on_click=lambda p=profile: _open_profile_dialog(p, ctx, refresh_fn),
                    ).props("flat round dense color=primary")
                    ui.button(
                        icon="delete",
                        on_click=lambda p=profile: _confirm_delete_profile(p, ctx, refresh_fn),
                    ).props("flat round dense color=negative")


def _open_default_profile_dialog(
    profile: LLMProfile,
    ctx,
    refresh_fn,
    default_ids: dict,
) -> None:
    with ui.dialog() as dlg, ui.card().classes("w-full max-w-sm"):
        ui.label("既定の用途").classes("text-lg font-semibold")
        ui.label(profile.name).classes("text-sm text-grey-6")
        generation_check = ui.checkbox(
            "キャラクター生成",
            value=profile.id == default_ids["generation"],
        )
        chat_check = ui.checkbox(
            "チャット",
            value=profile.id == default_ids["chat"],
        )

        async def _save_defaults() -> None:
            generation_id = default_ids["generation"]
            chat_id = default_ids["chat"]

            if generation_check.value:
                generation_id = profile.id
            elif generation_id == profile.id:
                generation_id = ""

            if chat_check.value:
                chat_id = profile.id
            elif chat_id == profile.id:
                chat_id = ""

            ctx.api_config.set_default_profiles(generation_id, chat_id)
            default_ids["generation"] = generation_id
            default_ids["chat"] = chat_id
            await refresh_fn()
            dlg.close()
            ui.notify("デフォルト設定を保存しました", type="positive")

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("保存", on_click=_save_defaults).props("color=primary unelevated")

    dlg.open()


async def _dup_profile(profile: LLMProfile, ctx, refresh_fn) -> None:
    copy = ctx.api_config.duplicate_llm_profile(profile.id)
    if copy:
        await refresh_fn()
        ui.notify(f"「{copy.name}」を作成しました", type="positive")


def _open_profile_dialog(profile: LLMProfile | None, ctx, refresh_fn) -> None:
    is_edit = profile is not None
    endpoints = ctx.api_config.get_endpoints()
    endpoint_by_id = {ep.id: ep for ep in endpoints}
    ep_options: dict[str, str] = {ep.id: f"{ep.name} ({ep.base_url})" for ep in endpoints}
    if not ep_options:
        ui.notify("先にエンドポイントを登録してください", type="warning")
        return
    first_ep_id = next(iter(ep_options))

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg"):
        ui.label("LLMプロファイルを編集" if is_edit else "LLMプロファイルを追加").classes(
            "text-lg font-semibold mb-3"
        )
        name_input = ui.input(
            label="プロファイル名", value=profile.name if profile else ""
        ).classes("w-full")
        ep_select = ui.select(
            options=ep_options,
            value=profile.endpoint_id if profile else first_ep_id,
            label="エンドポイント",
        ).classes("w-full")

        model_row = ui.row().classes("w-full items-end gap-2")
        with model_row:
            model_input = ui.input(
                label="モデルID",
                value=profile.model_id if profile else "",
            ).classes("flex-1")
            fetch_btn = ui.button(
                icon="refresh",
                on_click=lambda: _fetch_and_fill_model(ep_select, model_input, fetch_btn, ctx),
            ).props("flat round").tooltip("モデル一覧を取得")

        with ui.column().classes("w-full gap-1") as reasoning_group:
            reasoning_check = ui.checkbox(
                "Reasoning モード",
                value=profile.reasoning_enabled if profile else False,
            )

        with ui.column().classes("w-full gap-1") as temperature_group:
            temp_label = ui.label(f"Temperature: {profile.temperature if profile else 0.8}").classes("text-sm")
            temp_slider = ui.slider(
                min=0.0, max=2.0, step=0.05,
                value=profile.temperature if profile else 0.8,
                on_change=lambda e: temp_label.set_text(f"Temperature: {e.value:.2f}"),
            ).classes("w-full")

        with ui.column().classes("w-full gap-1") as max_tokens_group:
            max_tokens_input = ui.number(
                label="最大トークン数（省略可）",
                value=profile.max_tokens if profile else None,
                min=1, max=100000,
            ).classes("w-full")

        def _set_hidden(element, hidden: bool) -> None:
            if hidden:
                element.classes("hidden")
            else:
                element.classes(remove="hidden")

        def _selected_capabilities():
            endpoint_id = ep_select.value or ""
            return ctx.api_config.get_llm_parameter_capabilities(endpoint_id)

        def _sync_parameter_visibility() -> None:
            caps = _selected_capabilities()
            _set_hidden(reasoning_group, not caps.reasoning)
            _set_hidden(temperature_group, not caps.temperature)
            _set_hidden(max_tokens_group, not caps.max_tokens)
            if not caps.reasoning and reasoning_check.value:
                reasoning_check.set_value(False)
            if not caps.max_tokens and max_tokens_input.value:
                max_tokens_input.set_value(None)

            reasoning_active = bool(reasoning_check.value) and caps.reasoning
            temp_slider.set_enabled(caps.temperature and not reasoning_active)
            if not caps.temperature or reasoning_active:
                temp_label.classes("text-grey-5")
            else:
                temp_label.classes(remove="text-grey-5")

        reasoning_check.on("update:model-value", lambda _: _sync_parameter_visibility())
        ep_select.on_value_change(lambda _: _sync_parameter_visibility())
        if (profile is None or endpoint_by_id.get(profile.endpoint_id) is None) and first_ep_id:
            ep_select.set_value(first_ep_id)
        _sync_parameter_visibility()

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("保存", on_click=lambda: _save_profile(dlg)).props(
                "color=primary unelevated"
            )

    async def _save_profile(dlg) -> None:
        name = name_input.value.strip()
        model = model_input.value.strip()
        if not name:
            ui.notify("プロファイル名を入力してください", type="negative")
            return
        caps = _selected_capabilities()
        reasoning_enabled = bool(reasoning_check.value) if caps.reasoning else False
        temperature = float(temp_slider.value) if caps.temperature else (
            profile.temperature if profile else 0.8
        )
        max_tokens = (
            int(max_tokens_input.value)
            if caps.max_tokens and max_tokens_input.value
            else None
        )
        if is_edit:
            updated = profile.model_copy(update={
                "name": name,
                "endpoint_id": ep_select.value,
                "model_id": model,
                "temperature": temperature,
                "reasoning_enabled": reasoning_enabled,
                "max_tokens": max_tokens,
            })
            ctx.api_config.update_llm_profile(updated)
        else:
            ctx.api_config.create_llm_profile(
                name=name,
                endpoint_id=ep_select.value,
                model_id=model,
                temperature=temperature,
                reasoning_enabled=reasoning_enabled,
                max_tokens=max_tokens,
            )
        ui.notify("保存しました", type="positive")
        dlg.close()
        await refresh_fn()

    dlg.open()


async def _fetch_and_fill_model(ep_select, model_input, fetch_btn, ctx) -> None:
    fetch_btn.set_enabled(False)
    fetch_btn.props("loading=true")

    ep_id = ep_select.value
    vault_pw = get_vault_password()
    try:
        models = await ctx.api_config.fetch_endpoint_models(ep_id, vault_pw)
    finally:
        fetch_btn.set_enabled(True)
        fetch_btn.props(remove="loading")

    if not models:
        ui.notify("モデル一覧を取得できませんでした。エンドポイントへの接続を確認してください。", type="warning")
        return

    with ui.dialog() as model_dlg, ui.card().classes("min-w-[300px]"):
        ui.label(f"モデルを選択（{len(models)} 件）").classes("text-base font-semibold mb-2")
        with ui.scroll_area().style("height: 50vh; width: 100%"):
            model_list = ui.list().props("dense separator").classes("w-full")
            with model_list:
                for m in models:
                    ui.item(m, on_click=lambda m=m: _select_model(m, model_dlg, model_input)).classes(
                        "cursor-pointer hover:bg-grey-2"
                    )
    model_dlg.open()


def _select_model(model: str, dlg, model_input) -> None:
    model_input.set_value(model)
    dlg.close()


def _confirm_delete_profile(profile: LLMProfile, ctx, refresh_fn) -> None:
    with ui.dialog() as dlg, ui.card():
        ui.label(f"「{profile.name}」を削除しますか？").classes("font-medium mb-2")
        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")

            async def _do() -> None:
                ctx.api_config.delete_llm_profile(profile.id)
                ui.notify("削除しました", type="positive")
                dlg.close()
                await refresh_fn()

            ui.button("削除", on_click=_do).props("color=negative unelevated")
    dlg.open()


# ══════════════════════════════════════════
# チャットモード タブ
# ══════════════════════════════════════════

async def _build_chat_modes_tab(ctx) -> None:
    modes_container = ui.column().classes("w-full gap-3")

    async def reorder(e) -> None:
        args = e.args
        ordered = _moved_order(
            [mode.id for mode in ctx.api_config.get_chat_modes()],
            args["old_index"],
            args["new_index"],
        )
        if ordered is None:
            return
        ctx.api_config.reorder_chat_modes(ordered)
        _notify_order_saved()

    _enable_drag_sort(modes_container, reorder)

    async def refresh() -> None:
        modes = ctx.api_config.get_chat_modes()
        modes_container.clear()
        with modes_container:
            if not modes:
                ui.label("チャットモードが登録されていません").classes("text-grey-6 py-4")
            for mode in modes:
                _chat_mode_card(mode, ctx, refresh)

    await refresh()

    ui.button(
        "チャットモードを追加",
        icon="add",
        on_click=lambda: _open_chat_mode_dialog(None, ctx, refresh),
    ).props("color=primary unelevated").classes("mt-2")


def _chat_mode_card(mode: ChatMode, ctx, refresh_fn) -> None:
    with ui.card().classes("w-full cursor-grab"):
        with ui.card_section():
            with ui.row().classes("items-start gap-3"):
                with ui.column().classes("flex-1 gap-2"):
                    ui.label(mode.name).classes("text-base font-semibold")
                    ui.label("前提テンプレート").classes("text-xs font-semibold text-grey-6")
                    ui.label(_short_text(mode.premise_template)).classes("text-sm").style(
                        "white-space: pre-wrap; overflow-wrap: anywhere;"
                    )
                    ui.label("シチュエーションテンプレート").classes("text-xs font-semibold text-grey-6")
                    ui.label(_short_text(mode.situation_template)).classes("text-sm").style(
                        "white-space: pre-wrap; overflow-wrap: anywhere;"
                    )
                with ui.row().classes("gap-2"):
                    ui.button(
                        icon="edit",
                        on_click=lambda m=mode: _open_chat_mode_dialog(m, ctx, refresh_fn),
                    ).props("flat round dense color=primary")
                    ui.button(
                        icon="delete",
                        on_click=lambda m=mode: _confirm_delete_chat_mode(m, ctx, refresh_fn),
                    ).props("flat round dense color=negative")


def _open_chat_mode_dialog(mode: ChatMode | None, ctx, refresh_fn) -> None:
    is_edit = mode is not None

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-2xl"):
        ui.label("チャットモードを編集" if is_edit else "チャットモードを追加").classes(
            "text-lg font-semibold mb-3"
        )
        name_input = ui.input(
            label="モード名",
            value=mode.name if mode else "",
        ).props("outlined").classes("w-full")
        ui.label("使用できる変数: {{ character_name }}, {{ user_persona_name }}").classes(
            "text-xs text-grey-6"
        )
        premise_input = ui.textarea(
            label="前提テンプレート",
            value=mode.premise_template if mode else "",
        ).props("outlined rows=4").classes("w-full")
        situation_input = ui.textarea(
            label="シチュエーションテンプレート",
            value=mode.situation_template if mode else "",
        ).props("outlined rows=3").classes("w-full")

        async def _save_chat_mode() -> None:
            name = (name_input.value or "").strip()
            premise = (premise_input.value or "").strip()
            situation = (situation_input.value or "").strip()
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
            await refresh_fn()

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("保存", icon="save", on_click=_save_chat_mode).props(
                "color=primary unelevated"
            )

    dlg.open()


def _confirm_delete_chat_mode(mode: ChatMode, ctx, refresh_fn) -> None:
    with ui.dialog() as dlg, ui.card().classes("w-full max-w-sm"):
        ui.label(f"「{mode.name}」を削除しますか？").classes("font-medium mb-2")
        ui.label("このチャットモードは新しいチャット開始時に選べなくなります。").classes(
            "text-sm text-grey-6"
        )
        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")

            async def _do() -> None:
                if len(ctx.api_config.get_chat_modes()) <= 1:
                    ui.notify("チャットモードは少なくとも1件必要です", type="warning")
                    return
                ctx.api_config.delete_chat_mode(mode.id)
                ui.notify("削除しました", type="positive")
                dlg.close()
                await refresh_fn()

            ui.button("削除", on_click=_do).props("color=negative unelevated")
    dlg.open()


# ══════════════════════════════════════════
# ユーザーペルソナ タブ
# ══════════════════════════════════════════

async def _build_user_personas_tab(ctx) -> None:
    personas_container = ui.column().classes("w-full gap-3")

    async def reorder(e) -> None:
        args = e.args
        ordered = _moved_order(
            [persona.id for persona in ctx.api_config.get_user_personas()],
            args["old_index"],
            args["new_index"],
        )
        if ordered is None:
            return
        ctx.api_config.reorder_user_personas(ordered)
        _notify_order_saved()

    _enable_drag_sort(personas_container, reorder)

    async def refresh() -> None:
        personas = ctx.api_config.get_user_personas()
        personas_container.clear()
        with personas_container:
            if not personas:
                ui.label("ユーザーペルソナが登録されていません。チャット開始前に追加してください。").classes(
                    "text-grey-6 py-4"
                )
            for persona in personas:
                _user_persona_card(persona, ctx, refresh)

    await refresh()

    ui.button(
        "ユーザーペルソナを追加",
        icon="add",
        on_click=lambda: _open_user_persona_dialog(None, ctx, refresh),
    ).props("color=primary unelevated").classes("mt-2")


def _user_persona_card(persona: UserPersona, ctx, refresh_fn) -> None:
    with ui.card().classes("w-full cursor-grab"):
        with ui.card_section():
            with ui.row().classes("items-start gap-3"):
                with ui.column().classes("flex-1 gap-1"):
                    ui.label(persona.name).classes("text-base font-semibold")
                    ui.label(_short_text(persona.description)).classes("text-sm text-grey-6").style(
                        "white-space: pre-wrap; overflow-wrap: anywhere;"
                    )
                with ui.row().classes("gap-2"):
                    ui.button(
                        icon="edit",
                        on_click=lambda p=persona: _open_user_persona_dialog(p, ctx, refresh_fn),
                    ).props("flat round dense color=primary")
                    ui.button(
                        icon="delete",
                        on_click=lambda p=persona: _confirm_delete_user_persona(p, ctx, refresh_fn),
                    ).props("flat round dense color=negative")


def _open_user_persona_dialog(persona: UserPersona | None, ctx, refresh_fn) -> None:
    is_edit = persona is not None

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg"):
        ui.label("ユーザーペルソナを編集" if is_edit else "ユーザーペルソナを追加").classes(
            "text-lg font-semibold mb-3"
        )
        name_input = ui.input(
            label="名前",
            value=persona.name if persona else "",
        ).props("outlined").classes("w-full")
        description_input = ui.textarea(
            label="設定",
            value=persona.description if persona else "",
        ).props("outlined rows=5").classes("w-full")

        async def _save_user_persona() -> None:
            name = (name_input.value or "").strip()
            description = (description_input.value or "").strip()
            if not name or not description:
                ui.notify("名前と設定を入力してください", type="negative")
                return

            updated = UserPersona(
                id=persona.id if persona else str(uuid.uuid4())[:8],
                name=name,
                description=description,
            )
            if is_edit:
                ctx.api_config.update_user_persona(updated)
            else:
                ctx.api_config.create_user_persona(updated)
            ui.notify("保存しました", type="positive")
            dlg.close()
            await refresh_fn()

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("保存", icon="save", on_click=_save_user_persona).props(
                "color=primary unelevated"
            )

    dlg.open()


def _confirm_delete_user_persona(persona: UserPersona, ctx, refresh_fn) -> None:
    with ui.dialog() as dlg, ui.card().classes("w-full max-w-sm"):
        ui.label(f"「{persona.name}」を削除しますか？").classes("font-medium mb-2")
        ui.label("このユーザーペルソナは新しいチャット開始時に選べなくなります。").classes(
            "text-sm text-grey-6"
        )
        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")

            async def _do() -> None:
                ctx.api_config.delete_user_persona(persona.id)
                ui.notify("削除しました", type="positive")
                dlg.close()
                await refresh_fn()

            ui.button("削除", on_click=_do).props("color=negative unelevated")
    dlg.open()


def _short_text(text: str, limit: int = 180) -> str:
    normalized = (text or "").strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "..."


# ══════════════════════════════════════════
# 生成プリセット タブ
# ══════════════════════════════════════════

async def _build_presets_tab(ctx) -> None:
    from ....core.llm.schemas import GenerationPreset
    from ....core.character_generation.prompts import WORLD_OPTIONS, GENDER_OPTIONS, AGE_OPTIONS

    presets_container = ui.column().classes("w-full gap-3")

    async def reorder(e) -> None:
        args = e.args
        ordered = _moved_order(
            [preset.id for preset in ctx.api_config.get_generation_presets()],
            args["old_index"],
            args["new_index"],
        )
        if ordered is None:
            return
        ctx.api_config.reorder_generation_presets(ordered)
        _notify_order_saved()

    _enable_drag_sort(presets_container, reorder)

    async def refresh() -> None:
        presets = ctx.api_config.get_generation_presets()
        presets_container.clear()
        with presets_container:
            if not presets:
                ui.label("生成プリセットが登録されていません").classes("text-grey-6 py-4")
            for p in presets:
                _preset_card(p, ctx, refresh)

    await refresh()

    def _open_new() -> None:
        _open_preset_dialog(None, ctx, refresh, WORLD_OPTIONS, GENDER_OPTIONS, AGE_OPTIONS)

    ui.button(
        "プリセットを追加", icon="add", on_click=_open_new
    ).props("color=primary unelevated").classes("mt-2")


def _preset_card(preset, ctx, refresh_fn) -> None:
    from ....core.character_generation.prompts import WORLD_OPTIONS, GENDER_OPTIONS, AGE_OPTIONS

    with ui.card().classes("w-full cursor-grab"):
        with ui.card_section():
            with ui.row().classes("items-center gap-3"):
                with ui.column().classes("flex-1 gap-1"):
                    ui.label(preset.name).classes("text-base font-semibold")
                    parts = []
                    if preset.world and preset.world != "おまかせ":
                        parts.append(f"世界観: {preset.world}")
                    if preset.gender and preset.gender != "おまかせ":
                        parts.append(f"性別: {preset.gender}")
                    if preset.age and preset.age != "おまかせ":
                        parts.append(f"年齢: {preset.age}")
                    if preset.theme:
                        parts.append(f"テーマ: {preset.theme}")
                    ui.label(" / ".join(parts) if parts else "（指定なし）").classes("text-sm text-grey-6")

                with ui.row().classes("gap-2"):
                    ui.button(
                        icon="edit",
                        on_click=lambda p=preset: _open_preset_dialog(p, ctx, refresh_fn, WORLD_OPTIONS, GENDER_OPTIONS, AGE_OPTIONS),
                    ).props("flat round dense color=primary")
                    ui.button(
                        icon="delete",
                        on_click=lambda p=preset: _confirm_delete_preset(p, ctx, refresh_fn),
                    ).props("flat round dense color=negative")


def _open_preset_dialog(preset, ctx, refresh_fn, WORLD_OPTIONS, GENDER_OPTIONS, AGE_OPTIONS) -> None:
    is_edit = preset is not None

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg"):
        ui.label("生成プリセットを編集" if is_edit else "生成プリセットを追加").classes(
            "text-lg font-semibold mb-3"
        )
        name_input = ui.input(
            label="プリセット名", value=preset.name if preset else ""
        ).classes("w-full")
        world_select = ui.select(
            options=WORLD_OPTIONS,
            value=preset.world if preset else "おまかせ",
            label="世界観",
        ).classes("w-full")
        gender_select = ui.select(
            options=GENDER_OPTIONS,
            value=preset.gender if preset else "おまかせ",
            label="性別",
        ).classes("w-full")
        age_select = ui.select(
            options=AGE_OPTIONS,
            value=preset.age if preset else "おまかせ",
            label="年齢帯",
        ).classes("w-full")
        theme_input = ui.input(
            label="テーマ・雰囲気",
            value=preset.theme if preset else "",
        ).classes("w-full")
        extra_input = ui.textarea(
            label="その他の要望",
            value=preset.extra if preset else "",
        ).classes("w-full").props("rows=3")

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("保存", on_click=lambda: _save_preset(dlg)).props("color=primary unelevated")

    async def _save_preset(dlg) -> None:
        from ....core.llm.schemas import GenerationPreset

        name = name_input.value.strip()
        if not name:
            ui.notify("プリセット名を入力してください", type="negative")
            return
        p = GenerationPreset(
            id=preset.id if is_edit else str(uuid.uuid4())[:8],
            name=name,
            world=world_select.value,
            gender=gender_select.value,
            age=age_select.value,
            theme=theme_input.value,
            extra=extra_input.value,
        )
        if is_edit:
            ctx.api_config.update_generation_preset(p)
        else:
            ctx.api_config.create_generation_preset(p)
        ui.notify("保存しました", type="positive")
        dlg.close()
        await refresh_fn()

    dlg.open()


def _confirm_delete_preset(preset, ctx, refresh_fn) -> None:
    with ui.dialog() as dlg, ui.card():
        ui.label(f"「{preset.name}」を削除しますか？").classes("font-medium mb-2")
        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")

            async def _do() -> None:
                ctx.api_config.delete_generation_preset(preset.id)
                ui.notify("削除しました", type="positive")
                dlg.close()
                await refresh_fn()

            ui.button("削除", on_click=_do).props("color=negative unelevated")
    dlg.open()


# ══════════════════════════════════════════
# KeyVault タブ
# ══════════════════════════════════════════

async def _build_vault_tab(ctx) -> None:
    vault_container = ui.column().classes("w-full gap-4")

    async def refresh() -> None:
        vault_container.clear()
        with vault_container:
            if not ctx.api_config.is_vault_setup():
                _build_vault_setup(ctx, refresh)
            elif not is_vault_unlocked():
                _build_vault_unlock(ctx, refresh)
            else:
                _build_vault_unlocked(ctx, refresh)

    await refresh()


def _build_vault_setup(ctx, refresh_fn) -> None:
    with ui.card().classes("w-full max-w-lg"):
        ui.label("APIキーボルトの設定").classes("text-lg font-semibold mb-2")
        ui.label(
            "APIキーを暗号化して保存するためのマスターパスワードを設定します。"
            " パスワードを忘れた場合はボルトをリセットする必要があります。"
        ).classes("text-sm text-grey-6 mb-4")
        pw1 = ui.input(label="マスターパスワード").props("type=password clearable").classes("w-full")
        pw2 = ui.input(label="パスワードの確認").props("type=password clearable").classes("w-full")

        async def _setup() -> None:
            if not pw1.value:
                ui.notify("パスワードを入力してください", type="negative")
                return
            if pw1.value != pw2.value:
                ui.notify("パスワードが一致しません", type="negative")
                return
            ctx.api_config.setup_vault(pw1.value)
            set_vault_password(pw1.value)
            ui.notify("ボルトを設定しました", type="positive")
            await refresh_fn()

        ui.button("ボルトを設定", on_click=_setup).props("color=primary unelevated").classes("mt-2")


def _build_vault_unlock(ctx, refresh_fn) -> None:
    with ui.card().classes("w-full max-w-lg"):
        ui.label("ボルトのロック解除").classes("text-lg font-semibold mb-2")
        with ui.row().classes("items-center gap-2 mb-3"):
            ui.icon("lock").classes("text-warning text-2xl")
            ui.label("ボルトはロックされています").classes("text-warning font-medium")

        pw_input = ui.input(label="マスターパスワード").props("type=password clearable").classes("w-full")

        async def _unlock() -> None:
            if ctx.api_config.verify_vault_password(pw_input.value):
                set_vault_password(pw_input.value)
                ui.notify("ボルトのロックを解除しました", type="positive")
                await refresh_fn()
            else:
                ui.notify("パスワードが正しくありません", type="negative")

        ui.button("ロック解除", on_click=_unlock).props("color=primary unelevated").classes("mt-2")


def _build_vault_unlocked(ctx, refresh_fn) -> None:
    with ui.card().classes("w-full max-w-lg"):
        with ui.row().classes("items-center justify-between mb-4"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("lock_open").classes("text-positive text-2xl")
                ui.label("ボルトはロック解除されています").classes("text-positive font-medium")
            ui.button(
                "ロック",
                icon="lock",
                on_click=lambda: _lock(refresh_fn),
            ).props("flat color=warning size=sm")

        ui.label(
            "APIキーの設定はエンドポイントカードから行えます。"
        ).classes("text-sm text-grey-6 mb-4")

        ui.separator()
        ui.label("ボルトの管理").classes("text-base font-semibold mt-3 mb-2")
        with ui.row().classes("gap-3"):
            ui.button(
                "パスワードを変更",
                icon="password",
                on_click=lambda: _open_change_password(ctx, refresh_fn),
            ).props("outline color=primary")
            ui.button(
                "ボルトをリセット",
                icon="delete_forever",
                on_click=lambda: _confirm_teardown(ctx, refresh_fn),
            ).props("outline color=negative")


async def _lock(refresh_fn) -> None:
    clear_vault_password()
    ui.notify("ボルトをロックしました", type="info")
    await refresh_fn()




def _open_key_dialog(ep: Endpoint, ctx, refresh_fn) -> None:
    with ui.dialog() as dlg, ui.card().classes("min-w-[360px]"):
        ui.label(f"「{ep.name}」のAPIキー").classes("text-lg font-semibold mb-3")
        key_input = ui.input(
            label="APIキー",
            placeholder="sk-...",
        ).props("type=password clearable").classes("w-full")

        async def _save() -> None:
            key = key_input.value.strip()
            if not key:
                ui.notify("APIキーを入力してください", type="negative")
                return
            vault_pw = get_vault_password()
            if not vault_pw:
                ui.notify("ボルトがロックされています", type="negative")
                return
            ctx.api_config.save_api_key(ep.id, key, vault_pw)
            ui.notify("APIキーを保存しました", type="positive")
            dlg.close()
            await refresh_fn()

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("保存", on_click=_save).props("color=primary unelevated")

    dlg.open()


def _open_change_password(ctx, refresh_fn) -> None:
    with ui.dialog() as dlg, ui.card().classes("min-w-[360px]"):
        ui.label("マスターパスワードの変更").classes("text-lg font-semibold mb-3")
        old_pw = ui.input(label="現在のパスワード").props("type=password clearable").classes("w-full")
        new_pw1 = ui.input(label="新しいパスワード").props("type=password clearable").classes("w-full")
        new_pw2 = ui.input(label="新しいパスワード（確認）").props("type=password clearable").classes("w-full")

        async def _change() -> None:
            if not ctx.api_config.verify_vault_password(old_pw.value):
                ui.notify("現在のパスワードが正しくありません", type="negative")
                return
            if not new_pw1.value:
                ui.notify("新しいパスワードを入力してください", type="negative")
                return
            if new_pw1.value != new_pw2.value:
                ui.notify("パスワードが一致しません", type="negative")
                return
            carry_keys = ctx.api_config._store.vault.load_keys(old_pw.value)
            ctx.api_config.setup_vault(new_pw1.value, carry_keys)
            set_vault_password(new_pw1.value)
            ui.notify("パスワードを変更しました", type="positive")
            dlg.close()
            await refresh_fn()

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("変更", on_click=_change).props("color=primary unelevated")
    dlg.open()


def _confirm_teardown(ctx, refresh_fn) -> None:
    with ui.dialog() as dlg, ui.card():
        ui.label("ボルトをリセットしますか？").classes("text-base font-semibold mb-2")
        ui.label("保存されているすべてのAPIキーが削除されます。この操作は取り消せません。").classes(
            "text-sm text-negative"
        )
        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")

            async def _do() -> None:
                ctx.api_config.teardown_vault()
                clear_vault_password()
                ui.notify("ボルトをリセットしました", type="warning")
                dlg.close()
                await refresh_fn()

            ui.button("リセット", on_click=_do).props("color=negative unelevated")
    dlg.open()


# ══════════════════════════════════════════
# 生成オプション タブ
# ══════════════════════════════════════════

_OMAKASE = "おまかせ"


def _build_options_tab(ctx) -> None:
    """世界観・年齢帯・性別の選択肢を編集するタブを構築する。

    ルール:
    - 先頭の「おまかせ」は固定（編集・削除・移動不可）
    - それ以外の項目は編集ボタンを押した時だけ入力フィールドに切り替える
    - 並び替えはカードの余白部分をドラッグして行う
    """
    from ....core.character_generation.prompts import AGE_OPTIONS, GENDER_OPTIONS, WORLD_OPTIONS

    lists_state: dict[str, list[str]] = ctx.api_config.get_option_lists()

    # 「おまかせ」が先頭になければ補完
    for k in ("world", "age", "gender"):
        if not lists_state[k] or lists_state[k][0] != _OMAKASE:
            lists_state[k] = [_OMAKASE] + [x for x in lists_state[k] if x != _OMAKASE]

    SECTION_DEFS = [
        ("world",  "世界観", "public",  WORLD_OPTIONS),
        ("age",    "年齢帯", "cake",    AGE_OPTIONS),
        ("gender", "性別",   "wc",      GENDER_OPTIONS),
    ]

    ui.label(
        "「おまかせ」は先頭に固定されています。項目はカードの余白をドラッグして並び替えできます。"
    ).classes("text-sm text-grey-6 mb-4")

    sections: dict[str, dict] = {}
    edit_state: dict[str, int | None] = {key: None for key, *_ in SECTION_DEFS}

    # ─ セクション描画ロジック（後で _save_and_render から呼ぶため外出し） ─
    def _render_list(k: str) -> None:
        sections[k]["container"].clear()
        with sections[k]["container"]:
            items = lists_state[k]
            if edit_state[k] is not None and edit_state[k] >= len(items):
                edit_state[k] = None
            if len(items) <= 1:
                ui.label("追加項目はまだありません").classes("text-sm text-grey-5 py-2")
                return

            for i in range(1, len(items)):
                item = items[i]
                editing = edit_state[k] == i

                with ui.card().classes("w-full cursor-grab"):
                    with ui.card_section().classes("py-2 px-3"):
                        if editing:
                            with ui.row().classes("items-center gap-2 w-full"):
                                inp = ui.input(value=item).props("dense outlined autofocus").classes(
                                    "flex-1 text-sm"
                                )
                                ui.button(
                                    icon="check",
                                    on_click=lambda k=k, i=i, inp=inp: _save_edit(k, i, inp),
                                ).props("flat round dense color=primary")
                                ui.button(
                                    icon="close",
                                    on_click=lambda k=k: _cancel_edit(k),
                                ).props("flat round dense")
                        else:
                            with ui.row().classes("items-center gap-2 w-full"):
                                ui.label(item).classes("flex-1 text-sm")
                                ui.button(
                                    icon="edit",
                                    on_click=lambda k=k, i=i: _start_edit(k, i),
                                ).props("flat round dense color=primary")
                                ui.button(
                                    icon="delete_outline",
                                    on_click=lambda k=k, i=i: _delete_item(k, i),
                                ).props("flat round dense color=negative")

    # ─ カード描画 ─
    for key, title, icon_name, default_opts in SECTION_DEFS:
        with ui.card().classes("w-full mb-4"):
            with ui.row().classes("items-center gap-2 mb-3"):
                ui.icon(icon_name).classes("text-primary")
                ui.label(title).classes("text-base font-semibold flex-1")
                ui.button(
                    "デフォルトに戻す",
                    on_click=lambda k=key, d=default_opts: _reset_list(k, d),
                ).props("flat size=sm color=negative")

            with ui.row().classes("items-center gap-2 w-full mb-2"):
                ui.label(_OMAKASE).classes("flex-1 text-sm").style(
                    "padding: 8px 12px; border-radius: 6px; font-style: italic;"
                    " background: var(--cs-surface-soft); color: var(--cs-muted); border: 1px solid var(--cs-border);"
                )
                ui.badge("固定").props("outline color=grey")

            container = ui.column().classes("w-full gap-2")
            _enable_drag_sort(
                container,
                lambda e, k=key: _reorder_option(
                    k, e.args["old_index"], e.args["new_index"]
                ),
            )
            sections[key] = {"container": container}
            _render_list(key)

            # 新規追加エリア
            with ui.row().classes("items-center gap-2 mt-3 w-full"):
                new_input = ui.input(placeholder="新しい項目を入力…").classes("flex-1").props(
                    "dense outlined"
                )

                def _make_add(k: str, inp):
                    def _add() -> None:
                        val = inp.value.strip()
                        if not val:
                            return
                        if val in lists_state[k]:
                            ui.notify("同じ項目がすでに存在します", type="warning")
                            return
                        lists_state[k].append(val)
                        inp.set_value("")
                        _save_and_render(k)
                    return _add

                ui.button(
                    icon="add", on_click=_make_add(key, new_input)
                ).props("color=primary unelevated dense")

    # ─ 共通操作関数 ─

    def _reorder_option(k: str, old_index: int, new_index: int) -> None:
        items = lists_state[k]
        old_idx = old_index + 1
        new_idx = new_index + 1
        if old_idx == new_idx:
            return
        if old_idx < 1 or old_idx >= len(items) or new_idx < 1 or new_idx >= len(items):
            return
        item = items.pop(old_idx)
        items.insert(new_idx, item)
        edit_state[k] = None
        ctx.api_config.save_option_lists(lists_state)
        _notify_order_saved()

    def _start_edit(k: str, idx: int) -> None:
        edit_state[k] = idx
        _render_list(k)

    def _cancel_edit(k: str) -> None:
        edit_state[k] = None
        _render_list(k)

    def _save_edit(k: str, idx: int, inp) -> None:
        if idx >= len(lists_state[k]):
            return
        val = (inp.value or "").strip()
        if not val:
            ui.notify("項目名を入力してください", type="warning")
            return
        if any(j != idx and item == val for j, item in enumerate(lists_state[k])):
            ui.notify("同じ項目がすでに存在します", type="warning")
            return
        lists_state[k][idx] = val
        edit_state[k] = None
        _save_and_render(k)

    def _delete_item(k: str, idx: int) -> None:
        if 1 <= idx < len(lists_state[k]):
            lists_state[k].pop(idx)
            edit_state[k] = None
            _save_and_render(k)

    def _reset_list(k: str, defaults: list[str]) -> None:
        lists_state[k] = list(defaults)
        if not lists_state[k] or lists_state[k][0] != _OMAKASE:
            lists_state[k] = [_OMAKASE] + lists_state[k]
        edit_state[k] = None
        _save_and_render(k)

    def _save_and_render(k: str) -> None:
        ctx.api_config.save_option_lists(lists_state)
        ui.notify("保存しました", type="positive", timeout=1200)
        _render_list(k)


# ══════════════════════════════════════════
# 画像&音声生成 タブ
# ══════════════════════════════════════════

_NO_GEN_SERVER = "__none__"


def _build_media_generation_tab(ctx) -> None:
    sub_tabs = ui.tabs().classes("w-full")
    with sub_tabs:
        tab_gen_server = ui.tab("Wizmy-Gen-Server", icon="hub")
        tab_image_generation = ui.tab("画像生成", icon="image")
        tab_tts = ui.tab("TTS", icon="record_voice_over")

    with ui.tab_panels(sub_tabs, value=tab_gen_server).classes("w-full mt-3"):
        with ui.tab_panel(tab_gen_server):
            _build_gen_server_tab(ctx)
        with ui.tab_panel(tab_image_generation):
            _build_image_generation_tab(ctx)
        with ui.tab_panel(tab_tts):
            _build_tts_endpoints_tab(ctx)


def _build_image_generation_tab(ctx) -> None:
    ui.label("画像生成プロファイル").classes("text-base font-semibold mb-1")
    ui.label(
        "画像生成API、モデル、プロンプト、パラメータを組み合わせて保存します。"
    ).classes("text-sm text-grey-6 mb-3")
    profiles_container = ui.column().classes("w-full gap-3")

    def refresh() -> None:
        config = ctx.api_config.get_image_generation_config()
        endpoints = {endpoint.id: endpoint for endpoint in ctx.api_config.get_gen_server_endpoints()}
        profiles_container.clear()
        with profiles_container:
            if not config.profiles:
                ui.label("画像生成プロファイルはまだ登録されていません。").classes("text-grey-6 py-4")
            for profile in config.profiles:
                _image_generation_profile_card(
                    profile,
                    endpoints,
                    ctx,
                    refresh,
                    is_default=profile.id == config.default_profile_id,
                )

    def reorder(e) -> None:
        profiles = ctx.api_config.get_image_generation_profiles()
        ordered = _moved_order(
            [profile.id for profile in profiles],
            e.args["old_index"],
            e.args["new_index"],
        )
        if ordered is None:
            return
        ctx.api_config.reorder_image_generation_profiles(ordered)
        _notify_order_saved()
        refresh()

    _enable_drag_sort(profiles_container, reorder)
    refresh()

    ui.button(
        "画像生成プロファイルを追加",
        icon="add",
        on_click=lambda: _open_image_generation_profile_dialog(None, ctx, refresh),
    ).props("color=primary unelevated").classes("mt-2")


def _image_generation_profile_card(
    profile: ImageGenerationProfile,
    endpoints: dict[str, GenServerEndpoint],
    ctx,
    refresh_fn,
    *,
    is_default: bool,
) -> None:
    endpoint = endpoints.get(profile.endpoint_id)
    params = clean_image_generation_params(profile.params)
    size = f"{params.get('width')}x{params.get('height')}"
    api_label = IMAGE_PROVIDER_LABELS.get(profile.provider, profile.provider)
    endpoint_label = endpoint.name if endpoint else "API未設定"

    with ui.card().classes("w-full cursor-grab"):
        with ui.card_section():
            with ui.row().classes("items-center gap-3 flex-wrap"):
                with ui.column().classes("flex-1 gap-1"):
                    with ui.row().classes("items-center gap-2 flex-wrap"):
                        ui.label(profile.name or "無題のプロファイル").classes("text-base font-semibold")
                        ui.badge(api_label).props("outline color=primary")
                        if is_default:
                            ui.badge("既定").props("color=primary")
                    ui.label(f"{endpoint_label} / {profile.model_id or 'モデル未設定'}").classes(
                        "text-sm text-grey-6 break-all"
                    )
                    ui.label(
                        f"{size} / steps {params.get('steps')} / CFG {params.get('cfg_scale')} / "
                        f"sampler {params.get('sampler')}"
                    ).classes("text-xs text-grey-6")

                with ui.row().classes("gap-2"):
                    ui.button(
                        icon="star",
                        on_click=lambda p=profile: _set_default_image_profile(p, ctx, refresh_fn),
                    ).props("flat round dense color=primary").tooltip("既定にする")
                    ui.button(
                        icon="content_copy",
                        on_click=lambda p=profile: _duplicate_image_profile(p, ctx, refresh_fn),
                    ).props("flat round dense").tooltip("複製")
                    ui.button(
                        icon="edit",
                        on_click=lambda p=profile: _open_image_generation_profile_dialog(p, ctx, refresh_fn),
                    ).props("flat round dense color=primary").tooltip("編集")
                    ui.button(
                        icon="delete",
                        on_click=lambda p=profile: _confirm_delete_image_profile(p, ctx, refresh_fn),
                    ).props("flat round dense color=negative").tooltip("削除")


def _open_image_generation_profile_dialog(
    profile: ImageGenerationProfile | None,
    ctx,
    refresh_fn,
) -> None:
    is_edit = profile is not None
    endpoints = ctx.api_config.get_gen_server_endpoints()
    endpoint_options = {
        endpoint.id: f"{endpoint.name} ({endpoint.base_url})"
        for endpoint in endpoints
    }
    default_endpoint_id = profile.endpoint_id if profile else (endpoints[0].id if endpoints else "")
    default_params = clean_image_generation_params(profile.params if profile else default_image_generation_params())
    controls: dict[str, object] = {}

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-3xl"):
        ui.label("画像生成プロファイルを編集" if is_edit else "画像生成プロファイルを追加").classes(
            "text-lg font-semibold mb-3"
        )
        name_input = ui.input(
            label="プロファイル名",
            value=profile.name if profile else "",
        ).props("outlined clearable").classes("w-full")
        provider_select = ui.select(
            options=IMAGE_PROVIDER_LABELS,
            value=profile.provider if profile else IMAGE_PROVIDER_WIZMY_GEN_SERVER,
            label="画像生成API",
        ).props("outlined dense").classes("w-full")
        endpoint_select = ui.select(
            options=endpoint_options or {"": "Wizmy-Gen-Server未設定"},
            value=default_endpoint_id if default_endpoint_id in endpoint_options else "",
            label="API接続先",
        ).props("outlined dense").classes("w-full")
        ui.label(
            "外部画像生成APIは今後このタブに追加予定です。"
        ).classes("text-xs text-grey-6")

        with ui.row().classes("w-full items-end gap-2"):
            model_input = ui.input(
                label="モデルID",
                value=profile.model_id if profile else "",
            ).props("outlined dense clearable").classes("flex-1")
            ui.button(
                icon="refresh",
                on_click=lambda: _fetch_image_profile_model_id(endpoint_select, model_input, ctx),
            ).props("flat round").tooltip("モデルIDを取得")

        prompt_input = ui.textarea(
            label="デフォルトプロンプト",
            value=profile.prompt if profile else "",
        ).props("outlined rows=5").classes("w-full")
        negative_input = ui.textarea(
            label="デフォルトネガティブプロンプト",
            value=profile.negative_prompt if profile else "",
        ).props("outlined rows=4").classes("w-full")

        with ui.expansion("詳細パラメータ", icon="tune").props("dense").classes("w-full"):
            with ui.grid(columns=2).classes("w-full gap-3"):
                for key, spec in IMAGE_GENERATION_PARAMETER_FIELDS.items():
                    controls[key] = _build_profile_param_control(key, spec, default_params.get(key))

        def _save() -> None:
            name = (name_input.value or "").strip()
            if not name:
                ui.notify("プロファイル名を入力してください", type="negative")
                return
            params = {
                key: _read_gen_server_default_value(spec, controls[key])
                for key, spec in IMAGE_GENERATION_PARAMETER_FIELDS.items()
            }
            updated = ImageGenerationProfile(
                id=profile.id if profile else "",
                name=name,
                provider=provider_select.value,
                endpoint_id=endpoint_select.value or "",
                model_id=(model_input.value or "").strip(),
                prompt=prompt_input.value or "",
                negative_prompt=negative_input.value or "",
                params=params,
            )
            if is_edit:
                ctx.api_config.update_image_generation_profile(updated)
            else:
                ctx.api_config.create_image_generation_profile(updated)
            ui.notify("画像生成プロファイルを保存しました", type="positive")
            dlg.close()
            refresh_fn()

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("保存", icon="save", on_click=_save).props("color=primary unelevated")

    dlg.open()


def _build_profile_param_control(key: str, spec: dict, value: object):
    label = str(spec.get("label", key))
    if spec.get("type") == "boolean":
        return ui.checkbox(label, value=bool(value)).classes("w-full")
    if spec.get("enum"):
        options = list(spec["enum"])
        return ui.select(
            options=options,
            value=value if value in options else spec.get("default"),
            label=label,
        ).props("outlined dense").classes("w-full")
    if spec.get("type") in {"integer", "number"}:
        return ui.number(
            label=label,
            value=value,
            min=spec.get("minimum"),
            step=spec.get("step"),
        ).props("outlined dense").classes("w-full")
    return ui.input(
        label=label,
        value=value or "",
    ).props("outlined dense clearable").classes("w-full")


async def _fetch_image_profile_model_id(endpoint_select, model_input, ctx) -> None:
    endpoint_id = endpoint_select.value or ""
    if not endpoint_id:
        ui.notify("先にAPI接続先を選択してください。", type="warning")
        return
    await _fetch_gen_server_model_id_from_endpoint(
        endpoint_id,
        GEN_SERVER_MODE_SDXL_IMAGE,
        model_input,
        ctx,
    )


def _set_default_image_profile(profile: ImageGenerationProfile, ctx, refresh_fn) -> None:
    ctx.api_config.set_default_image_generation_profile(profile.id)
    ui.notify("既定の画像生成プロファイルを保存しました", type="positive", timeout=1200)
    refresh_fn()


def _duplicate_image_profile(profile: ImageGenerationProfile, ctx, refresh_fn) -> None:
    copied = ctx.api_config.duplicate_image_generation_profile(profile.id)
    if copied is None:
        ui.notify("プロファイルが見つかりません。", type="negative")
        return
    ui.notify("画像生成プロファイルを複製しました", type="positive")
    refresh_fn()


def _confirm_delete_image_profile(profile: ImageGenerationProfile, ctx, refresh_fn) -> None:
    with ui.dialog() as dlg, ui.card():
        ui.label(f"「{profile.name}」を削除しますか？").classes("font-medium mb-2")
        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")

            def _do_delete() -> None:
                ctx.api_config.delete_image_generation_profile(profile.id)
                ui.notify("画像生成プロファイルを削除しました", type="positive")
                dlg.close()
                refresh_fn()

            ui.button("削除", on_click=_do_delete).props("color=negative unelevated")
    dlg.open()


def _build_gen_server_tab(ctx) -> None:
    _render_gen_server_chunking_settings(ctx)
    assignments_container = ui.column().classes("w-full gap-3 mb-4")
    defaults_container = ui.column().classes("w-full gap-3 mb-4")
    ui.label("サーバー").classes("text-base font-semibold")
    endpoints_container = ui.column().classes("w-full gap-3")

    def render_assignments() -> None:
        config = ctx.api_config.get_gen_server_config()
        endpoints = config.endpoints
        assignments_container.clear()
        with assignments_container:
            with ui.card().classes("w-full"):
                with ui.card_section():
                    ui.label("機能割り当て").classes("text-base font-semibold mb-2")
                    if not endpoints:
                        ui.label("Wizmy-Gen-Serverはまだ登録されていません。").classes(
                            "text-sm text-grey-6"
                        )
                        return

                    options = {_NO_GEN_SERVER: "未設定"}
                    options.update({
                        endpoint.id: f"{endpoint.name} ({endpoint.base_url})"
                        for endpoint in endpoints
                    })
                    with ui.grid(columns=1).classes("w-full gap-3"):
                        for mode in _GEN_SERVER_ASSIGNABLE_MODES:
                            selected = config.mode_assignments.get(mode) or _NO_GEN_SERVER
                            select = ui.select(
                                options=options,
                                value=selected if selected in options else _NO_GEN_SERVER,
                                label=GEN_SERVER_MODE_LABELS.get(mode, mode),
                            ).props("outlined dense").classes("w-full")

                            def _make_change(mode: str, select):
                                def _change(_) -> None:
                                    endpoint_id = "" if select.value == _NO_GEN_SERVER else select.value
                                    ctx.api_config.set_gen_server_mode_assignment(mode, endpoint_id)
                                    ui.notify("割り当てを保存しました", type="positive", timeout=1200)
                                    refresh()

                                return _change

                            select.on_value_change(_make_change(mode, select))

    def render_defaults() -> None:
        config = ctx.api_config.get_gen_server_config()
        defaults_container.clear()
        with defaults_container:
            ui.label("音声生成デフォルト値").classes("text-base font-semibold")
            for mode in _GEN_SERVER_ASSIGNABLE_MODES:
                with ui.expansion(
                    GEN_SERVER_MODE_LABELS.get(mode, mode),
                    icon=_gen_server_mode_icon(mode),
                ).props("dense").classes("w-full"):
                    _render_gen_server_mode_defaults(
                        mode,
                        config.defaults_for_mode(mode),
                        ctx,
                    )

    def refresh() -> None:
        config = ctx.api_config.get_gen_server_config()
        endpoints_container.clear()
        render_assignments()
        render_defaults()
        with endpoints_container:
            if not config.endpoints:
                ui.label("Wizmy-Gen-Serverはまだ登録されていません。").classes("text-grey-6 py-4")
            for endpoint in config.endpoints:
                assigned_modes = [
                    mode
                    for mode, endpoint_id in config.mode_assignments.items()
                    if endpoint_id == endpoint.id
                ]
                _gen_server_endpoint_card(endpoint, assigned_modes, ctx, refresh)

    def reorder(e) -> None:
        endpoints = ctx.api_config.get_gen_server_endpoints()
        ordered = _moved_order(
            [endpoint.id for endpoint in endpoints],
            e.args["old_index"],
            e.args["new_index"],
        )
        if ordered is None:
            return
        ctx.api_config.reorder_gen_server_endpoints(ordered)
        _notify_order_saved()
        refresh()

    _enable_drag_sort(endpoints_container, reorder)
    refresh()

    ui.button(
        "Wizmy-Gen-Serverを追加",
        icon="add",
        on_click=lambda: _open_gen_server_endpoint_dialog(None, ctx, refresh),
    ).props("color=primary unelevated").classes("mt-2")


def _render_gen_server_chunking_settings(ctx) -> None:
    config = ctx.api_config.get_gen_server_config()
    with ui.card().classes("w-full mb-4"):
        with ui.card_section():
            ui.label("Irodori-TTS長文分割").classes("text-base font-semibold mb-2")
            chunking_checkbox = ui.checkbox(
                "Irodori-TTS読み上げをWebUI側で分割",
                value=config.voice_chunking_enabled,
            )
            chunk_min_input = ui.number(
                label="分割最小文字数",
                value=config.voice_chunk_min_chars,
                min=1,
            ).props("outlined dense").classes("w-full max-w-xs")

            def _save() -> None:
                try:
                    chunk_min_chars = max(1, int(chunk_min_input.value or 80))
                except (TypeError, ValueError):
                    chunk_min_chars = 80
                ctx.api_config.set_gen_server_voice_chunking(
                    enabled=bool(chunking_checkbox.value),
                    min_chars=chunk_min_chars,
                )
                ui.notify("Irodori-TTS長文分割設定を保存しました", type="positive")

            with ui.row().classes("justify-end gap-2 mt-3"):
                ui.button("保存", icon="save", on_click=_save).props("color=primary unelevated")


def _gen_server_mode_icon(mode: str) -> str:
    if mode == "sdxl_image":
        return "image"
    if mode == "irodori_voice_design":
        return "record_voice_over"
    if mode == "irodori_voice_clone":
        return "graphic_eq"
    return "tune"


def _render_gen_server_mode_defaults(mode: str, defaults: dict, ctx) -> None:
    fields = GEN_SERVER_DEFAULT_FIELDS.get(mode, {})
    controls: dict[str, object] = {}

    with ui.grid(columns=2).classes("w-full gap-3"):
        for key, spec in fields.items():
            value = defaults.get(key, spec.get("default"))
            label = spec.get("label", key)
            if spec.get("type") == "boolean":
                controls[key] = ui.checkbox(str(label), value=bool(value)).classes("w-full")
            elif spec.get("enum"):
                controls[key] = ui.select(
                    options=list(spec["enum"]),
                    value=value if value in spec["enum"] else spec.get("default"),
                    label=str(label),
                ).props("outlined dense").classes("w-full")
            elif spec.get("type") in {"integer", "number"}:
                controls[key] = ui.number(
                    label=str(label),
                    value=value,
                    min=spec.get("minimum"),
                    step=spec.get("step"),
                ).props("outlined dense").classes("w-full")
            elif spec.get("multiline"):
                controls[key] = ui.textarea(
                    label=str(label),
                    value=value or "",
                ).props("outlined rows=3").classes("w-full col-span-2")
            elif key == "model_id":
                with ui.row().classes("w-full items-end gap-2"):
                    model_input = ui.input(
                        label=str(label),
                        value=value or "",
                    ).props("outlined dense clearable").classes("flex-1")
                    ui.button(
                        icon="refresh",
                        on_click=lambda mode=mode, model_input=model_input: _fetch_gen_server_model_id(
                            mode,
                            model_input,
                            ctx,
                        ),
                    ).props("flat round").tooltip("モデルIDを取得")
                controls[key] = model_input
            else:
                controls[key] = ui.input(
                    label=str(label),
                    value=value or "",
                ).props("outlined dense clearable").classes("w-full")

    def _read_defaults() -> dict:
        return {
            key: _read_gen_server_default_value(spec, controls[key])
            for key, spec in fields.items()
        }

    def _reset_defaults() -> None:
        for key, spec in fields.items():
            default = spec.get("default")
            controls[key].set_value(default if default is not None else "")

    def _save_defaults() -> None:
        ctx.api_config.set_gen_server_mode_defaults(mode, _read_defaults())
        ui.notify("デフォルト値を保存しました", type="positive")

    with ui.row().classes("justify-end gap-2 mt-3"):
        ui.button("リセット", icon="restart_alt", on_click=_reset_defaults).props("flat")
        ui.button("保存", icon="save", on_click=_save_defaults).props("color=primary unelevated")


def _read_gen_server_default_value(spec: dict, control) -> object:
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


async def _fetch_gen_server_model_id(mode: str, model_input, ctx) -> None:
    config = ctx.api_config.get_gen_server_config()
    endpoint_id = config.assigned_endpoint_id(mode)
    if not endpoint_id:
        ui.notify("先にこの機能へWizmy-Gen-Serverを割り当ててください。", type="warning")
        return
    await _fetch_gen_server_model_id_from_endpoint(endpoint_id, mode, model_input, ctx)


async def _fetch_gen_server_model_id_from_endpoint(
    endpoint_id: str,
    mode: str,
    model_input,
    ctx,
) -> None:
    try:
        models = await ctx.api_config.fetch_gen_server_models(endpoint_id, mode)
    except Exception as err:
        ui.notify(f"モデルIDを取得できませんでした: {err}", type="negative")
        return

    if not models:
        ui.notify("この機能で利用できるモデルが見つかりませんでした。", type="warning")
        return

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg"):
        ui.label(f"{GEN_SERVER_MODE_LABELS.get(mode, mode)} のモデルID").classes(
            "text-base font-semibold mb-2"
        )
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


def _gen_server_endpoint_card(
    endpoint: GenServerEndpoint,
    assigned_modes: list[str],
    ctx,
    refresh_fn,
) -> None:
    with ui.card().classes("w-full cursor-grab"):
        with ui.card_section():
            with ui.row().classes("items-center gap-3 flex-wrap"):
                with ui.column().classes("flex-1 gap-1"):
                    ui.label(endpoint.name).classes("text-base font-semibold")
                    ui.label(endpoint.base_url).classes("text-sm text-grey-6 font-mono break-all")
                    with ui.row().classes("gap-2 flex-wrap"):
                        if assigned_modes:
                            for mode in _GEN_SERVER_ASSIGNABLE_MODES:
                                if mode in assigned_modes:
                                    ui.badge(GEN_SERVER_MODE_LABELS.get(mode, mode)).props(
                                        "outline color=primary"
                                    )
                        else:
                            ui.badge("未割り当て").props("outline color=grey")

                with ui.row().classes("gap-2"):
                    status_icon = ui.icon("circle").classes("text-grey-4 text-base")
                    ui.button(
                        icon="wifi_tethering",
                        on_click=lambda ep=endpoint: _test_gen_server_connection(ep, status_icon, ctx),
                    ).props("flat round dense").tooltip("接続テスト")
                    ui.button(
                        icon="edit",
                        on_click=lambda ep=endpoint: _open_gen_server_endpoint_dialog(ep, ctx, refresh_fn),
                    ).props("flat round dense color=primary")
                    ui.button(
                        icon="delete",
                        on_click=lambda ep=endpoint: _confirm_delete_gen_server_endpoint(ep, ctx, refresh_fn),
                    ).props("flat round dense color=negative")


async def _test_gen_server_connection(endpoint: GenServerEndpoint, status_icon: ui.icon, ctx) -> None:
    status_icon.classes("text-grey-4")
    try:
        capabilities = await ctx.api_config.fetch_gen_server_capabilities(endpoint.id)
    except Exception as err:
        status_icon.classes(remove="text-grey-4 text-positive").classes("text-negative")
        ui.notify(f"「{endpoint.name}」に接続できませんでした: {err}", type="negative")
        return

    modes = capabilities.get("modes", []) if capabilities else []
    status_icon.classes(remove="text-grey-4 text-negative").classes("text-positive")
    labels = [
        GEN_SERVER_MODE_LABELS.get(mode, mode)
        for mode in _GEN_SERVER_ASSIGNABLE_MODES
        if mode in modes
    ]
    detail = " / ".join(labels) if labels else "対応機能なし"
    ui.notify(f"「{endpoint.name}」に接続できました: {detail}", type="positive")


def _open_gen_server_endpoint_dialog(endpoint: GenServerEndpoint | None, ctx, refresh_fn) -> None:
    is_edit = endpoint is not None

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg"):
        ui.label("Wizmy-Gen-Serverを編集" if is_edit else "Wizmy-Gen-Serverを追加").classes(
            "text-lg font-semibold mb-3"
        )
        name_input = ui.input(
            label="表示名",
            value=endpoint.name if endpoint else "Wizmy-Gen-Server",
        ).props("outlined").classes("w-full")
        url_input = ui.input(
            label="API URL",
            value=endpoint.base_url if endpoint else "http://127.0.0.1:8008/v1",
            placeholder="http://127.0.0.1:8008/v1",
        ).props("outlined clearable").classes("w-full")
        ui.label("形式: http://host:port または http://host:port/v1").classes(
            "text-xs text-grey-6 mt-1"
        )

        def _save() -> None:
            name = (name_input.value or "").strip()
            base_url = (url_input.value or "").strip()
            if not name or not base_url:
                ui.notify("表示名とURLを入力してください", type="negative")
                return
            try:
                if is_edit:
                    updated = GenServerEndpoint(
                        id=endpoint.id,
                        name=name,
                        base_url=base_url,
                    )
                    ctx.api_config.update_gen_server_endpoint(updated)
                else:
                    ctx.api_config.create_gen_server_endpoint(name, base_url)
            except ValidationError:
                ui.notify(
                    "URLは http://host:port または http://host:port/v1 の形式で入力してください。",
                    type="negative",
                )
                return
            ui.notify("Wizmy-Gen-Serverを保存しました", type="positive")
            dlg.close()
            refresh_fn()

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("保存", icon="save", on_click=_save).props("color=primary unelevated")

    dlg.open()


def _confirm_delete_gen_server_endpoint(endpoint: GenServerEndpoint, ctx, refresh_fn) -> None:
    with ui.dialog() as dlg, ui.card():
        ui.label(f"「{endpoint.name}」を削除しますか？").classes("font-medium mb-2")
        ui.label("このサーバーに割り当てられている機能は未設定になります。").classes(
            "text-sm text-grey-6"
        )
        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")

            def _do_delete() -> None:
                ctx.api_config.delete_gen_server_endpoint(endpoint.id)
                ui.notify("Wizmy-Gen-Serverを削除しました", type="positive")
                dlg.close()
                refresh_fn()

            ui.button("削除", on_click=_do_delete).props("color=negative unelevated")
    dlg.open()


# ══════════════════════════════════════════
# TTS設定 タブ
# ══════════════════════════════════════════

_TTS_PROVIDER_LABELS = {
    TTS_PROVIDER_IRODORI_GRADIO: "Irodori-TTS Gradio / 07dfa74",
    TTS_PROVIDER_IRODORI_SERVER: "Irodori-TTS-Server",
}


def _build_tts_endpoints_tab(ctx) -> None:
    ui.label("Wizmy-Gen-Serverが使えない場合は、一番上のTTS APIを使用します。").classes(
        "text-sm text-grey-6 mb-2"
    )
    endpoints_container = ui.column().classes("w-full gap-3")

    def refresh() -> None:
        endpoints = ctx.api_config.get_tts_endpoints()
        endpoints_container.clear()
        with endpoints_container:
            if not endpoints:
                ui.label("TTS APIはまだ登録されていません。").classes("text-grey-6 py-4")
            for endpoint in endpoints:
                _tts_endpoint_card(
                    endpoint,
                    ctx=ctx,
                    refresh_fn=refresh,
                )

    def reorder(e) -> None:
        endpoints = ctx.api_config.get_tts_endpoints()
        ordered = _moved_order(
            [endpoint.id for endpoint in endpoints],
            e.args["old_index"],
            e.args["new_index"],
        )
        if ordered is None:
            return
        ctx.api_config.reorder_tts_endpoints(ordered)
        _notify_order_saved()
        refresh()

    _enable_drag_sort(endpoints_container, reorder)
    refresh()

    ui.button(
        "TTS APIを追加",
        icon="add",
        on_click=lambda: _open_tts_endpoint_dialog(None, ctx, refresh),
    ).props("color=primary unelevated").classes("mt-2")


def _tts_endpoint_card(endpoint: TTSEndpoint, *, ctx, refresh_fn) -> None:
    with ui.card().classes("w-full cursor-grab"):
        with ui.card_section():
            with ui.row().classes("items-center gap-3 flex-wrap"):
                with ui.column().classes("flex-1 gap-1"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label(endpoint.name).classes("text-base font-semibold")
                        ui.badge(_TTS_PROVIDER_LABELS.get(endpoint.provider, endpoint.provider)).props(
                            "color=purple"
                        )
                    ui.label(endpoint.base_url).classes("text-sm text-grey-6 font-mono break-all")
                with ui.row().classes("gap-2"):
                    ui.button(
                        icon="edit",
                        on_click=lambda ep=endpoint: _open_tts_endpoint_dialog(ep, ctx, refresh_fn),
                    ).props("flat round dense color=primary")
                    ui.button(
                        icon="delete",
                        on_click=lambda ep=endpoint: _confirm_delete_tts_endpoint(ep, ctx, refresh_fn),
                    ).props("flat round dense color=negative")


def _open_tts_endpoint_dialog(endpoint: TTSEndpoint | None, ctx, refresh_fn) -> None:
    is_edit = endpoint is not None
    default_provider = endpoint.provider if endpoint else TTS_PROVIDER_IRODORI_GRADIO
    default_url = endpoint.base_url if endpoint else "http://localhost:7860"

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg"):
        ui.label("TTS APIを編集" if is_edit else "TTS APIを追加").classes(
            "text-lg font-semibold mb-3"
        )
        name_input = ui.input(
            label="表示名",
            value=endpoint.name if endpoint else "Irodori-TTS Gradio",
        ).props("outlined").classes("w-full")
        provider_select = ui.select(
            options=_TTS_PROVIDER_LABELS,
            value=default_provider,
            label="TTS API",
        ).props("outlined").classes("w-full")
        url_input = ui.input(
            label="URL",
            value=default_url,
            placeholder="http://localhost:7860",
        ).props("outlined clearable").classes("w-full")
        ui.label("形式: http://host:port").classes("text-xs text-grey-6 mt-1")

        def _provider_changed() -> None:
            if is_edit:
                return
            provider = provider_select.value
            name_input.set_value(_TTS_PROVIDER_LABELS.get(provider, "TTS API"))
            if provider == TTS_PROVIDER_IRODORI_GRADIO:
                url_input.set_value("http://localhost:7860")
            elif provider == TTS_PROVIDER_IRODORI_SERVER:
                url_input.set_value("http://localhost:8088")

        provider_select.on("update:model-value", lambda _: _provider_changed())

        def _save() -> None:
            name = (name_input.value or "").strip()
            base_url = (url_input.value or "").strip()
            if not name or not base_url:
                ui.notify("表示名とURLを入力してください", type="negative")
                return
            try:
                if is_edit:
                    updated = TTSEndpoint(
                        id=endpoint.id,
                        name=name,
                        provider=provider_select.value,
                        base_url=base_url,
                    )
                    ctx.api_config.update_tts_endpoint(updated)
                else:
                    ctx.api_config.create_tts_endpoint(
                        name,
                        provider_select.value,
                        base_url,
                    )
            except ValidationError:
                ui.notify("URLは http://host:port の形式で入力してください。", type="negative")
                return
            ui.notify("TTS APIを保存しました", type="positive")
            dlg.close()
            refresh_fn()

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("保存", icon="save", on_click=_save).props("color=primary unelevated")

    dlg.open()


def _confirm_delete_tts_endpoint(endpoint: TTSEndpoint, ctx, refresh_fn) -> None:
    with ui.dialog() as dlg, ui.card():
        ui.label(f"「{endpoint.name}」を削除しますか？").classes("font-medium mb-2")
        ui.label("このTTS APIを選択しているキャラクターは、次の利用時にデフォルトへフォールバックします。").classes(
            "text-sm text-grey-6"
        )
        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")

            def _do_delete() -> None:
                ctx.api_config.delete_tts_endpoint(endpoint.id)
                ui.notify("TTS APIを削除しました", type="positive")
                dlg.close()
                refresh_fn()

            ui.button("削除", on_click=_do_delete).props("color=negative unelevated")
    dlg.open()


# ══════════════════════════════════════════
# 外観 タブ
# ══════════════════════════════════════════

def _build_appearance_tab() -> None:
    from nicegui import app as _app

    current_theme = _app.storage.user.get("theme", DEFAULT_THEME)
    selected: dict[str, str] = {"value": current_theme}

    ui.label("テーマ").classes("text-base font-semibold mb-1").style("color: var(--cs-text);")
    ui.label("テーマを変更すると即座に反映されます。設定はブラウザセッションに保存されます。").classes(
        "text-sm mb-4"
    ).style("color: var(--cs-muted);")

    cards: dict[str, ui.element] = {}

    def _apply(theme_id: str) -> None:
        old = selected["value"]
        selected["value"] = theme_id
        _app.storage.user["theme"] = theme_id
        # 旧選択のカードを非選択スタイルに戻す
        if old in cards:
            cards[old].classes(remove="cs-theme-selected")
        # 新選択のカードを選択スタイルに
        if theme_id in cards:
            cards[theme_id].classes("cs-theme-selected")
        # ページにテーマを即座に適用
        ui.run_javascript(apply_theme_js(theme_id))
        # Quasar カラーも更新（次回レンダー時に確実に反映）
        t = THEMES[theme_id]
        ui.colors(
            primary=t["q-primary"],
            secondary=t["q-secondary"],
            positive=t["q-positive"],
            negative=t["q-negative"],
            warning=t["q-warning"],
            info=t["q-info"],
        )

    with ui.element("div").style(
        "display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 14px;"
    ):
        for theme_id, theme in THEMES.items():
            is_selected = theme_id == selected["value"]
            extra_cls = "cs-theme-selected" if is_selected else ""
            card = ui.element("div").classes(f"cs-theme-card {extra_cls}").on(
                "click", lambda tid=theme_id: _apply(tid)
            )
            cards[theme_id] = card
            with card:
                # カラースウォッチ
                with ui.element("div").classes("cs-theme-swatch"):
                    for color_key in ["cs-bg", "cs-surface", "cs-accent", "q-primary"]:
                        ui.element("div").classes("cs-theme-swatch-color").style(
                            f"background-color: {theme[color_key]};"
                        )
                # テーマ名
                with ui.row().classes("items-center gap-2 mb-1"):
                    ui.html(f'<span style="font-size:1.1rem;">{theme["icon"]}</span>')
                    ui.label(theme["label"]).style(
                        "font-weight: 700; font-size: 0.9rem; color: var(--cs-text);"
                    )
                ui.label(theme["desc"]).style(
                    "font-size: 0.75rem; color: var(--cs-muted); margin-bottom: 8px;"
                )
                # ダークテーマバッジ
                if theme["dark"]:
                    ui.badge("ダーク").props("outline").style(
                        "color: var(--cs-muted); border-color: var(--cs-border); font-size: 0.68rem;"
                    )
                # 選択状態テキスト
                if is_selected:
                    ui.html(
                        '<div style="margin-top:8px;font-size:0.72rem;font-weight:600;'
                        'color:var(--cs-accent);">✓ 現在のテーマ</div>'
                    )
