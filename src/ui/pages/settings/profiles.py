from __future__ import annotations

from nicegui import ui

from ....core.llm.schemas import LLMProfile
from ...state import get_vault_password
from .common import enable_drag_sort, moved_order, notify_order_saved


async def build_profiles_tab(ctx) -> None:
    profiles_container = ui.column().classes("w-full gap-3")
    app_config = ctx.api_config.get_app_llm_config()
    default_ids = {
        "generation": app_config.generation_profile_id,
        "chat": app_config.chat_profile_id,
    }

    async def reorder(e) -> None:
        args = e.args
        ordered = moved_order(
            [profile.id for profile in ctx.api_config.get_llm_profiles()],
            args["old_index"],
            args["new_index"],
        )
        if ordered is None:
            return
        ctx.api_config.reorder_llm_profiles(ordered)
        notify_order_saved()

    enable_drag_sort(profiles_container, reorder)

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
                profile_card(p, ep, ctx, refresh, default_ids)

    await refresh()

    ui.button(
        "プロファイルを追加",
        icon="add",
        on_click=lambda: open_profile_dialog(None, ctx, refresh),
    ).props("color=primary unelevated").classes("mt-2")


def profile_card(
    profile: LLMProfile,
    endpoint,
    ctx,
    refresh_fn,
    default_ids: dict,
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
                        on_click=lambda p=profile: open_default_profile_dialog(p, ctx, refresh_fn, default_ids),
                    ).props("flat round dense color=amber").tooltip("生成/チャットの既定を選択")
                    ui.button(
                        icon="content_copy",
                        on_click=lambda p=profile: dup_profile(p, ctx, refresh_fn),
                    ).props("flat round dense").tooltip("複製")
                    ui.button(
                        icon="edit",
                        on_click=lambda p=profile: open_profile_dialog(p, ctx, refresh_fn),
                    ).props("flat round dense color=primary")
                    ui.button(
                        icon="delete",
                        on_click=lambda p=profile: confirm_delete_profile(p, ctx, refresh_fn),
                    ).props("flat round dense color=negative")


def open_default_profile_dialog(
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


async def dup_profile(profile: LLMProfile, ctx, refresh_fn) -> None:
    copy = ctx.api_config.duplicate_llm_profile(profile.id)
    if copy:
        await refresh_fn()
        ui.notify(f"「{copy.name}」を作成しました", type="positive")


def open_profile_dialog(profile: LLMProfile | None, ctx, refresh_fn) -> None:
    is_edit = profile is not None
    endpoints = ctx.api_config.get_endpoints()
    endpoint_by_id = {ep.id: ep for ep in endpoints}
    ep_options: dict[str, str] = {ep.id: f"{ep.name} ({ep.base_url})" for ep in endpoints}
    if not ep_options:
        ui.notify("先にエンドポイントを登録してください", type="warning")
        return
    first_ep_id = next(iter(ep_options))

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg"):
        ui.label("LLMプロファイルを編集" if is_edit else "LLMプロファイルを追加").classes("text-lg font-semibold mb-3")
        name_input = ui.input(label="プロファイル名", value=profile.name if profile else "").classes("w-full")
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
            fetch_btn = (
                ui.button(
                    icon="refresh",
                    on_click=lambda: fetch_and_fill_model(ep_select, model_input, fetch_btn, ctx),
                )
                .props("flat round")
                .tooltip("モデル一覧を取得")
            )

        with ui.column().classes("w-full gap-1") as reasoning_group:
            reasoning_check = ui.checkbox(
                "Reasoning モード",
                value=profile.reasoning_enabled if profile else False,
            )

        with ui.column().classes("w-full gap-1") as temperature_group:
            temp_label = ui.label(f"Temperature: {profile.temperature if profile else 0.8}").classes("text-sm")
            temp_slider = ui.slider(
                min=0.0,
                max=2.0,
                step=0.05,
                value=profile.temperature if profile else 0.8,
                on_change=lambda e: temp_label.set_text(f"Temperature: {e.value:.2f}"),
            ).classes("w-full")

        with ui.column().classes("w-full gap-1") as max_tokens_group:
            max_tokens_input = ui.number(
                label="最大トークン数（省略可）",
                value=profile.max_tokens if profile else None,
                min=1,
                max=100000,
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
            ui.button("保存", on_click=lambda: _save_profile(dlg)).props("color=primary unelevated")

    async def _save_profile(dlg) -> None:
        name = name_input.value.strip()
        model = model_input.value.strip()
        if not name:
            ui.notify("プロファイル名を入力してください", type="negative")
            return
        caps = _selected_capabilities()
        reasoning_enabled = bool(reasoning_check.value) if caps.reasoning else False
        temperature = float(temp_slider.value) if caps.temperature else (profile.temperature if profile else 0.8)
        max_tokens = int(max_tokens_input.value) if caps.max_tokens and max_tokens_input.value else None
        if is_edit:
            updated = profile.model_copy(
                update={
                    "name": name,
                    "endpoint_id": ep_select.value,
                    "model_id": model,
                    "temperature": temperature,
                    "reasoning_enabled": reasoning_enabled,
                    "max_tokens": max_tokens,
                }
            )
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


async def fetch_and_fill_model(ep_select, model_input, fetch_btn, ctx) -> None:
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
                    ui.item(m, on_click=lambda m=m: select_model(m, model_dlg, model_input)).classes(
                        "cursor-pointer hover:bg-grey-2"
                    )
    model_dlg.open()


def select_model(model: str, dlg, model_input) -> None:
    model_input.set_value(model)
    dlg.close()


def confirm_delete_profile(profile: LLMProfile, ctx, refresh_fn) -> None:
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
