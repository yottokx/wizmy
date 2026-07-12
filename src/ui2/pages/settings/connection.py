"""
/settings — 接続(LLMエンドポイント / LLMプロファイル)。

旧 `ui/pages/settings/endpoints.py` / `profiles.py` の機能を P3 スキンで再実装
(接続テスト・APIキー設定/削除・並べ替え・複製・既定の用途)。
"""

from __future__ import annotations

from nicegui import ui

from ....core.llm.schemas import Endpoint, LLMProfile
from ...state import get_vault_password, is_vault_unlocked
from .common import (
    badge,
    chip_button,
    confirm_dialog,
    enable_drag_sort,
    entry_card,
    moved_order,
    notify_order_saved,
    p3_button,
    settings_dialog,
)

_TYPE_LABELS = {"ollama": "Ollama", "openai_compat": "OpenAI互換"}


def open_endpoints_dialog(ctx, on_change) -> None:
    dlg, body = settings_dialog("LLMエンドポイント")
    with body:
        container = ui.column().classes("w-full gap-3")
        with ui.row().classes("w-full"):
            p3_button(
                "エンドポイントを追加", lambda: _open_endpoint_edit(None, ctx, _refresh), classes="btn primary"
            ).mark("ui2-settings-endpoint-add")

    async def _reorder(e) -> None:
        ordered = moved_order(
            [ep.id for ep in ctx.api_config.get_endpoints()],
            e.args["old_index"],
            e.args["new_index"],
        )
        if ordered is None:
            return
        ctx.api_config.reorder_endpoints(ordered)
        notify_order_saved()
        on_change()

    enable_drag_sort(container, _reorder)

    def _refresh() -> None:
        endpoints = ctx.api_config.get_endpoints()
        container.clear()
        with container:
            if not endpoints:
                ui.label("エンドポイントが登録されていません").classes("note")
            for ep in endpoints:
                _endpoint_card(ep, ctx, _refresh)
        on_change()

    def _endpoint_card(ep: Endpoint, ctx, refresh_fn) -> None:
        key_set = ctx.api_config.is_api_key_configured(ep.id) if ep.type == "openai_compat" else False
        with entry_card():
            with ui.row().classes("items-center gap-3 flex-wrap w-full"):
                with ui.column().classes("flex-1 gap-1 min-w-0"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label(ep.name).classes("text-sm font-semibold")
                        badge(_TYPE_LABELS.get(ep.type, ep.type), tone="peri")
                    ui.label(ep.base_url).classes("text-xs font-mono break-all").style("color: var(--muted);")
                    if ep.type == "openai_compat":
                        with ui.row().classes("items-center gap-2"):
                            badge("APIキー設定済" if key_set else "APIキー未設定", tone="ok" if key_set else "muted")
                            if not is_vault_unlocked():
                                ui.label("(ボルトを解錠すると設定できます)").classes("text-xs").style(
                                    "color: var(--muted);"
                                )
                            elif key_set:
                                chip_button("キーを削除", lambda e=ep: _delete_key(e))
                            else:
                                chip_button("キーを設定", lambda e=ep: _open_key_dialog(e))
                with ui.row().classes("gap-2 items-center"):
                    status_label = ui.element("span")
                    chip_button("接続テスト", lambda e=ep, s=status_label: _test_connection(e, s))
                    chip_button("編集", lambda e=ep: _open_endpoint_edit(e, ctx, refresh_fn))
                    chip_button("削除", lambda e=ep: _confirm_delete(e))

        async def _delete_key(ep: Endpoint) -> None:
            ctx.api_config.delete_api_key(ep.id)
            ui.notify(f"「{ep.name}」のAPIキーを削除しました", type="positive")
            refresh_fn()

        def _open_key_dialog(ep: Endpoint) -> None:
            with ui.dialog() as key_dlg, ui.card().classes("min-w-[360px]").style(
                "background: var(--panel); color: var(--text);"
            ):
                ui.label(f"「{ep.name}」のAPIキー").classes("text-base font-semibold mb-2")
                key_input = ui.input(label="APIキー", placeholder="sk-...").props(
                    "type=password clearable outlined dense"
                ).classes("w-full p3-fd")

                async def _save() -> None:
                    key = str(key_input.value or "").strip()
                    if not key:
                        ui.notify("APIキーを入力してください", type="negative")
                        return
                    vault_pw = get_vault_password()
                    if not vault_pw:
                        ui.notify("ボルトがロックされています", type="negative")
                        return
                    ctx.api_config.save_api_key(ep.id, key, vault_pw)
                    ui.notify("APIキーを保存しました", type="positive")
                    key_dlg.close()
                    refresh_fn()

                with ui.row().classes("justify-end gap-2 mt-3 w-full"):
                    p3_button("キャンセル", key_dlg.close, classes="btn quiet")
                    p3_button("保存", _save, classes="btn primary")
            key_dlg.open()

        async def _test_connection(ep: Endpoint, status_label) -> None:
            ok = await ctx.api_config.test_connection(ep.id, get_vault_password())
            status_label.clear()
            with status_label:
                badge("接続OK" if ok else "応答なし", tone="ok" if ok else "ng")
            if ok:
                ui.notify(f"「{ep.name}」に接続できました", type="positive")
            else:
                ui.notify(f"「{ep.name}」に接続できませんでした", type="negative")

        def _confirm_delete(ep: Endpoint) -> None:
            async def _do() -> None:
                ctx.api_config.delete_endpoint(ep.id)
                ui.notify(f"「{ep.name}」を削除しました", type="positive")
                refresh_fn()

            confirm_dialog(
                f"「{ep.name}」を削除しますか?",
                "このエンドポイントを使用するLLMプロファイルも影響を受けます。",
                _do,
            )

    _refresh()
    dlg.open()


def _open_endpoint_edit(ep: Endpoint | None, ctx, refresh_fn) -> None:
    is_edit = ep is not None
    with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg").style(
        "background: var(--panel); color: var(--text);"
    ):
        ui.label("エンドポイントを編集" if is_edit else "エンドポイントを追加").classes(
            "text-base font-semibold mb-2"
        )
        name_input = ui.input(label="表示名", value=ep.name if ep else "").props("outlined dense").classes(
            "w-full p3-fd"
        ).mark("ui2-settings-endpoint-name")
        type_select = (
            ui.select(options=_TYPE_LABELS, value=ep.type if ep else "ollama", label="プロバイダー種別")
            .props("outlined dense")
            .classes("w-full p3-fd")
        )
        url_input = (
            ui.input(
                label="ベースURL",
                value=ep.base_url if ep else "http://localhost:11434",
                placeholder="http://localhost:11434",
            )
            .props("outlined dense clearable")
            .classes("w-full p3-fd")
            .mark("ui2-settings-endpoint-url")
        )

        async def _save() -> None:
            name = str(name_input.value or "").strip()
            url = str(url_input.value or "").strip()
            if not name or not url:
                ui.notify("表示名とURLを入力してください", type="negative")
                return
            if is_edit and ep is not None:
                data = ep.model_dump()
                data.update({"name": name, "type": str(type_select.value or "ollama"), "base_url": url})
                ctx.api_config.update_endpoint(Endpoint(**data))
            else:
                ctx.api_config.create_endpoint(name, str(type_select.value or "ollama"), url)
            ui.notify("保存しました", type="positive")
            dlg.close()
            refresh_fn()

        with ui.row().classes("justify-end gap-2 mt-3 w-full"):
            p3_button("キャンセル", dlg.close, classes="btn quiet")
            p3_button("保存", _save, classes="btn primary").mark("ui2-settings-endpoint-save")
    dlg.open()


# ---------------------------------------------------------------------------
# LLMプロファイル
# ---------------------------------------------------------------------------


def open_profiles_dialog(ctx, on_change) -> None:
    dlg, body = settings_dialog("LLMプロファイル")
    with body:
        container = ui.column().classes("w-full gap-3")
        with ui.row().classes("w-full"):
            p3_button("プロファイルを追加", lambda: _open_profile_edit(None, ctx, _refresh), classes="btn primary")

    async def _reorder(e) -> None:
        ordered = moved_order(
            [profile.id for profile in ctx.api_config.get_llm_profiles()],
            e.args["old_index"],
            e.args["new_index"],
        )
        if ordered is None:
            return
        ctx.api_config.reorder_llm_profiles(ordered)
        notify_order_saved()
        on_change()

    enable_drag_sort(container, _reorder)

    def _refresh() -> None:
        profiles = ctx.api_config.get_llm_profiles()
        endpoints = {ep.id: ep for ep in ctx.api_config.get_endpoints()}
        app_config = ctx.api_config.get_app_llm_config()
        default_ids = {"generation": app_config.generation_profile_id, "chat": app_config.chat_profile_id}
        container.clear()
        with container:
            if not profiles:
                ui.label("LLMプロファイルが登録されていません").classes("note")
            for profile in profiles:
                _profile_card(profile, endpoints.get(profile.endpoint_id), default_ids)
        on_change()

    def _profile_card(profile: LLMProfile, endpoint, default_ids: dict) -> None:
        caps = ctx.api_config.get_llm_parameter_capabilities(profile.endpoint_id)
        with entry_card():
            with ui.row().classes("items-center gap-3 flex-wrap w-full"):
                with ui.column().classes("flex-1 gap-1 min-w-0"):
                    with ui.row().classes("items-center gap-2 flex-wrap"):
                        ui.label(profile.name).classes("text-sm font-semibold")
                        if profile.id == default_ids["generation"]:
                            badge("生成の既定", tone="accent")
                        if profile.id == default_ids["chat"]:
                            badge("チャットの既定", tone="peri")
                        if caps.reasoning and profile.reasoning_enabled:
                            badge("Reasoning")
                    parts = [endpoint.name if endpoint else "不明なエンドポイント"]
                    parts.append(f"モデル: {profile.model_id or '未設定'}")
                    if caps.temperature and not (caps.reasoning and profile.reasoning_enabled):
                        parts.append(f"T={profile.temperature}")
                    ui.label(" / ".join(parts)).classes("text-xs break-all").style("color: var(--muted);")
                with ui.row().classes("gap-2"):
                    chip_button("既定の用途", lambda p=profile: _open_defaults(p, default_ids))
                    chip_button("複製", lambda p=profile: _duplicate(p))
                    chip_button("編集", lambda p=profile: _open_profile_edit(p, ctx, _refresh))
                    chip_button("削除", lambda p=profile: _confirm_delete(p))

    def _open_defaults(profile: LLMProfile, default_ids: dict) -> None:
        with ui.dialog() as d_dlg, ui.card().classes("w-full max-w-sm").style(
            "background: var(--panel); color: var(--text);"
        ):
            ui.label("既定の用途").classes("text-base font-semibold")
            ui.label(profile.name).classes("text-xs").style("color: var(--muted);")
            generation_check = ui.checkbox("キャラクター生成", value=profile.id == default_ids["generation"])
            chat_check = ui.checkbox("チャット", value=profile.id == default_ids["chat"])

            async def _save() -> None:
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
                ui.notify("既定の用途を保存しました", type="positive")
                d_dlg.close()
                _refresh()

            with ui.row().classes("justify-end gap-2 mt-3 w-full"):
                p3_button("キャンセル", d_dlg.close, classes="btn quiet")
                p3_button("保存", _save, classes="btn primary")
        d_dlg.open()

    async def _duplicate(profile: LLMProfile) -> None:
        copy = ctx.api_config.duplicate_llm_profile(profile.id)
        if copy:
            ui.notify(f"「{copy.name}」を作成しました", type="positive")
            _refresh()

    def _confirm_delete(profile: LLMProfile) -> None:
        async def _do() -> None:
            ctx.api_config.delete_llm_profile(profile.id)
            ui.notify("削除しました", type="positive")
            _refresh()

        confirm_dialog(f"「{profile.name}」を削除しますか?", "", _do)

    _refresh()
    dlg.open()


def _open_profile_edit(profile: LLMProfile | None, ctx, refresh_fn) -> None:
    is_edit = profile is not None
    endpoints = ctx.api_config.get_endpoints()
    ep_options = {ep.id: f"{ep.name} ({ep.base_url})" for ep in endpoints}
    if not ep_options:
        ui.notify("先にエンドポイントを登録してください", type="warning")
        return
    first_ep_id = next(iter(ep_options))
    endpoint_by_id = {ep.id: ep for ep in endpoints}

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg").style(
        "background: var(--panel); color: var(--text);"
    ):
        ui.label("LLMプロファイルを編集" if is_edit else "LLMプロファイルを追加").classes(
            "text-base font-semibold mb-2"
        )
        name_input = ui.input(label="プロファイル名", value=profile.name if profile else "").props(
            "outlined dense"
        ).classes("w-full p3-fd")
        ep_select = (
            ui.select(
                options=ep_options,
                value=profile.endpoint_id if profile else first_ep_id,
                label="エンドポイント",
            )
            .props("outlined dense")
            .classes("w-full p3-fd")
        )
        with ui.row().classes("w-full items-end gap-2"):
            model_input = ui.input(label="モデルID", value=profile.model_id if profile else "").props(
                "outlined dense"
            ).classes("flex-1 p3-fd")
            chip_button("モデル一覧", lambda: _fetch_models())

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
            max_tokens_input = (
                ui.number(label="最大トークン数(省略可)", value=profile.max_tokens if profile else None, min=1)
                .props("outlined dense")
                .classes("w-full p3-fd")
            )

        def _set_hidden(element, hidden: bool) -> None:
            if hidden:
                element.classes("hidden")
            else:
                element.classes(remove="hidden")

        def _caps():
            return ctx.api_config.get_llm_parameter_capabilities(ep_select.value or "")

        def _sync_visibility() -> None:
            caps = _caps()
            _set_hidden(reasoning_group, not caps.reasoning)
            _set_hidden(temperature_group, not caps.temperature)
            _set_hidden(max_tokens_group, not caps.max_tokens)
            if not caps.reasoning and reasoning_check.value:
                reasoning_check.set_value(False)
            if not caps.max_tokens and max_tokens_input.value:
                max_tokens_input.set_value(None)
            reasoning_active = bool(reasoning_check.value) and caps.reasoning
            temp_slider.set_enabled(caps.temperature and not reasoning_active)

        reasoning_check.on("update:model-value", lambda _: _sync_visibility())
        ep_select.on_value_change(lambda _: _sync_visibility())
        if (profile is None or endpoint_by_id.get(profile.endpoint_id) is None) and first_ep_id:
            ep_select.set_value(first_ep_id)
        _sync_visibility()

        async def _fetch_models() -> None:
            models = await ctx.api_config.fetch_endpoint_models(ep_select.value, get_vault_password())
            if not models:
                ui.notify(
                    "モデル一覧を取得できませんでした。エンドポイントへの接続を確認してください。",
                    type="warning",
                )
                return
            with ui.dialog() as model_dlg, ui.card().classes("min-w-[320px]").style(
                "background: var(--panel); color: var(--text);"
            ):
                ui.label(f"モデルを選択({len(models)} 件)").classes("text-base font-semibold mb-2")
                with ui.scroll_area().style("height: 50vh; width: 100%"):
                    with ui.list().props("dense separator").classes("w-full"):
                        for m in models:
                            ui.item(
                                m,
                                on_click=lambda m=m: (model_input.set_value(m), model_dlg.close()),
                            ).classes("cursor-pointer")
            model_dlg.open()

        async def _save() -> None:
            name = str(name_input.value or "").strip()
            model = str(model_input.value or "").strip()
            if not name:
                ui.notify("プロファイル名を入力してください", type="negative")
                return
            caps = _caps()
            reasoning_enabled = bool(reasoning_check.value) if caps.reasoning else False
            temperature = (
                float(temp_slider.value) if caps.temperature else (profile.temperature if profile else 0.8)
            )
            max_tokens = int(max_tokens_input.value) if caps.max_tokens and max_tokens_input.value else None
            if is_edit and profile is not None:
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
            refresh_fn()

        with ui.row().classes("justify-end gap-2 mt-3 w-full"):
            p3_button("キャンセル", dlg.close, classes="btn quiet")
            p3_button("保存", _save, classes="btn primary")
    dlg.open()


def endpoints_summary(ctx) -> tuple[str, str]:
    """行のバッジ表示(text, tone)。"""
    endpoints = ctx.api_config.get_endpoints()
    if not endpoints:
        return "未登録", "muted"
    return f"{len(endpoints)}件", "ok"


def profiles_summary(ctx) -> tuple[str, str]:
    profiles = ctx.api_config.get_llm_profiles()
    if not profiles:
        return "未登録", "muted"
    app_config = ctx.api_config.get_app_llm_config()
    default = ctx.api_config.get_llm_profile(app_config.generation_profile_id)
    if default is not None:
        rest = len(profiles) - 1
        return (f"{default.name} ほか {rest}" if rest > 0 else default.name), "ok"
    return f"{len(profiles)}件", "ok"
