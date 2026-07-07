"""
/v2/settings — 画像・音声生成のAPI(Wizmy-Gen-Server / TTS API / 画像生成プロファイル)。

旧 `ui/pages/settings/media_generation.py` の機能を P3 スキンで再実装
(機能割り当て・モード別デフォルト値・長文分割・接続テスト・並べ替え・複製・既定)。
"""

from __future__ import annotations

from nicegui import ui
from pydantic import ValidationError

from ....core.gen_server.schemas import (
    GEN_SERVER_DEFAULT_FIELDS,
    GEN_SERVER_MODE_LABELS,
    GEN_SERVER_MODE_SDXL_IMAGE,
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
from ....core.tts.options import TTS_PROVIDER_LABELS
from ....core.tts.schemas import (
    TTS_PROVIDER_IRODORI_GRADIO,
    TTS_PROVIDER_IRODORI_SERVER,
    TTSEndpoint,
)
from ...media_logic import read_param_value
from ...media_ui import build_param_control, open_model_id_picker
from .common import (
    DIALOG_CARD_STYLE,
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

GEN_SERVER_ASSIGNABLE_MODES = tuple(mode for mode in GEN_SERVER_MODES if mode != GEN_SERVER_MODE_SDXL_IMAGE)

_NO_GEN_SERVER = "__none__"


# ---------------------------------------------------------------------------
# Wizmy-Gen-Server(サーバー+機能割り当て+デフォルト値+長文分割)
# ---------------------------------------------------------------------------


def open_gen_server_dialog(ctx, on_change) -> None:
    dlg, body = settings_dialog("Wizmy-Gen-Server")
    with body:
        assignments_container = ui.column().classes("w-full gap-2")
        defaults_container = ui.column().classes("w-full gap-2")
        chunking_container = ui.column().classes("w-full gap-2")
        ui.label("サーバー").classes("text-sm font-semibold mt-2")
        servers_container = ui.column().classes("w-full gap-3")
        with ui.row().classes("w-full"):
            p3_button(
                "Wizmy-Gen-Serverを追加",
                lambda: _open_gen_server_edit(None, ctx, _refresh),
                classes="btn primary",
            )

    def _reorder(e) -> None:
        ordered = moved_order(
            [endpoint.id for endpoint in ctx.api_config.get_gen_server_endpoints()],
            e.args["old_index"],
            e.args["new_index"],
        )
        if ordered is None:
            return
        ctx.api_config.reorder_gen_server_endpoints(ordered)
        notify_order_saved()
        _refresh()

    enable_drag_sort(servers_container, _reorder)

    def _render_assignments() -> None:
        config = ctx.api_config.get_gen_server_config()
        assignments_container.clear()
        with assignments_container:
            ui.label("機能割り当て").classes("text-sm font-semibold")
            if not config.endpoints:
                ui.label("Wizmy-Gen-Serverはまだ登録されていません。").classes("note")
                return
            options = {_NO_GEN_SERVER: "未設定"}
            options.update({ep.id: f"{ep.name} ({ep.base_url})" for ep in config.endpoints})
            for mode in GEN_SERVER_ASSIGNABLE_MODES:
                selected = config.mode_assignments.get(mode) or _NO_GEN_SERVER
                select = (
                    ui.select(
                        options=options,
                        value=selected if selected in options else _NO_GEN_SERVER,
                        label=GEN_SERVER_MODE_LABELS.get(mode, mode),
                    )
                    .props("outlined dense")
                    .classes("w-full p3-fd")
                )

                def _make_change(mode: str, select):
                    def _change(_) -> None:
                        endpoint_id = "" if select.value == _NO_GEN_SERVER else select.value
                        ctx.api_config.set_gen_server_mode_assignment(mode, endpoint_id)
                        ui.notify("割り当てを保存しました", type="positive", timeout=1200)
                        _refresh()

                    return _change

                select.on_value_change(_make_change(mode, select))

    def _render_defaults() -> None:
        config = ctx.api_config.get_gen_server_config()
        defaults_container.clear()
        with defaults_container:
            ui.label("音声生成デフォルト値").classes("text-sm font-semibold mt-2")
            for mode in GEN_SERVER_ASSIGNABLE_MODES:
                with ui.expansion(GEN_SERVER_MODE_LABELS.get(mode, mode)).props("dense").classes("w-full"):
                    _render_mode_defaults(mode, config.defaults_for_mode(mode))

    def _render_mode_defaults(mode: str, defaults: dict) -> None:
        fields = GEN_SERVER_DEFAULT_FIELDS.get(mode, {})
        controls: dict[str, object] = {}
        with ui.grid(columns=2).classes("w-full gap-3"):
            for key, spec in fields.items():
                value = defaults.get(key, spec.get("default"))
                if key == "model_id":
                    with ui.row().classes("w-full col-span-2 items-end gap-2"):
                        model_input = (
                            ui.input(label=str(spec.get("label", key)), value=value or "")
                            .props("outlined dense clearable")
                            .classes("flex-1 p3-fd")
                        )
                        controls[key] = model_input

                        async def _fetch(mode=mode, model_input=model_input) -> None:
                            endpoint_id = ctx.api_config.get_gen_server_config().assigned_endpoint_id(mode)
                            await open_model_id_picker(ctx, endpoint_id, mode, model_input)

                        chip_button("取得", _fetch)
                else:
                    controls[key] = build_param_control(key, spec, value)

        def _reset() -> None:
            for key, spec in fields.items():
                default = spec.get("default")
                controls[key].set_value(default if default is not None else "")

        def _save() -> None:
            values = {key: read_param_value(spec, controls[key].value) for key, spec in fields.items()}
            ctx.api_config.set_gen_server_mode_defaults(mode, values)
            ui.notify("デフォルト値を保存しました", type="positive")

        with ui.row().classes("justify-end gap-2 mt-2 w-full"):
            p3_button("リセット", _reset, classes="btn quiet")
            p3_button("保存", _save, classes="btn primary")

    def _render_chunking() -> None:
        config = ctx.api_config.get_gen_server_config()
        chunking_container.clear()
        with chunking_container:
            ui.label("Irodori-TTS長文分割").classes("text-sm font-semibold mt-2")
            chunking_checkbox = ui.checkbox(
                "Irodori-TTS読み上げをWebUI側で分割",
                value=config.voice_chunking_enabled,
            )
            chunk_min_input = (
                ui.number(label="分割最小文字数", value=config.voice_chunk_min_chars, min=1)
                .props("outlined dense")
                .classes("w-full max-w-xs p3-fd")
            )

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

            with ui.row().classes("justify-end w-full"):
                p3_button("分割設定を保存", _save, classes="btn quiet")

    def _refresh() -> None:
        config = ctx.api_config.get_gen_server_config()
        _render_assignments()
        _render_defaults()
        _render_chunking()
        servers_container.clear()
        with servers_container:
            if not config.endpoints:
                ui.label("Wizmy-Gen-Serverはまだ登録されていません。").classes("note")
            for endpoint in config.endpoints:
                assigned = [m for m, eid in config.mode_assignments.items() if eid == endpoint.id]
                _server_card(endpoint, assigned)
        on_change()

    def _server_card(endpoint: GenServerEndpoint, assigned_modes: list[str]) -> None:
        with entry_card():
            with ui.row().classes("items-center gap-3 flex-wrap w-full"):
                with ui.column().classes("flex-1 gap-1 min-w-0"):
                    ui.label(endpoint.name).classes("text-sm font-semibold")
                    ui.label(endpoint.base_url).classes("text-xs font-mono break-all").style(
                        "color: var(--muted);"
                    )
                    with ui.row().classes("gap-2 flex-wrap"):
                        if assigned_modes:
                            for mode in GEN_SERVER_ASSIGNABLE_MODES:
                                if mode in assigned_modes:
                                    badge(GEN_SERVER_MODE_LABELS.get(mode, mode), tone="peri")
                        else:
                            badge("未割り当て")
                with ui.row().classes("gap-2 items-center"):
                    status_label = ui.element("span")
                    chip_button("接続テスト", lambda ep=endpoint, s=status_label: _test(ep, s))
                    chip_button("編集", lambda ep=endpoint: _open_gen_server_edit(ep, ctx, _refresh))
                    chip_button("削除", lambda ep=endpoint: _confirm_delete(ep))

    async def _test(endpoint: GenServerEndpoint, status_label) -> None:
        try:
            capabilities = await ctx.api_config.fetch_gen_server_capabilities(endpoint.id)
        except Exception as err:  # noqa: BLE001 - UI通知のための包括捕捉
            status_label.clear()
            with status_label:
                badge("応答なし", tone="ng")
            ui.notify(f"「{endpoint.name}」に接続できませんでした: {err}", type="negative")
            return
        modes = capabilities.get("modes", []) if capabilities else []
        labels = [GEN_SERVER_MODE_LABELS.get(m, m) for m in GEN_SERVER_ASSIGNABLE_MODES if m in modes]
        status_label.clear()
        with status_label:
            badge("接続OK", tone="ok")
        ui.notify(
            f"「{endpoint.name}」に接続できました: {' / '.join(labels) if labels else '対応機能なし'}",
            type="positive",
        )

    def _confirm_delete(endpoint: GenServerEndpoint) -> None:
        async def _do() -> None:
            ctx.api_config.delete_gen_server_endpoint(endpoint.id)
            ui.notify("Wizmy-Gen-Serverを削除しました", type="positive")
            _refresh()

        confirm_dialog(
            f"「{endpoint.name}」を削除しますか?",
            "このサーバーに割り当てられている機能は未設定になります。",
            _do,
        )

    _refresh()
    dlg.open()


def _open_gen_server_edit(endpoint: GenServerEndpoint | None, ctx, refresh_fn) -> None:
    is_edit = endpoint is not None
    with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg").style(DIALOG_CARD_STYLE):
        ui.label("Wizmy-Gen-Serverを編集" if is_edit else "Wizmy-Gen-Serverを追加").classes(
            "text-base font-semibold mb-2"
        )
        name_input = ui.input(
            label="表示名", value=endpoint.name if endpoint else "Wizmy-Gen-Server"
        ).props("outlined dense").classes("w-full p3-fd")
        url_input = (
            ui.input(
                label="API URL",
                value=endpoint.base_url if endpoint else "http://127.0.0.1:8008/v1",
                placeholder="http://127.0.0.1:8008/v1",
            )
            .props("outlined dense clearable")
            .classes("w-full p3-fd")
        )
        ui.label("形式: http://host:port または http://host:port/v1").classes("text-xs").style(
            "color: var(--muted);"
        )

        def _save() -> None:
            name = str(name_input.value or "").strip()
            base_url = str(url_input.value or "").strip()
            if not name or not base_url:
                ui.notify("表示名とURLを入力してください", type="negative")
                return
            try:
                if is_edit and endpoint is not None:
                    ctx.api_config.update_gen_server_endpoint(
                        GenServerEndpoint(id=endpoint.id, name=name, base_url=base_url)
                    )
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

        with ui.row().classes("justify-end gap-2 mt-3 w-full"):
            p3_button("キャンセル", dlg.close, classes="btn quiet")
            p3_button("保存", _save, classes="btn primary")
    dlg.open()


# ---------------------------------------------------------------------------
# TTS API
# ---------------------------------------------------------------------------


def open_tts_endpoints_dialog(ctx, on_change) -> None:
    dlg, body = settings_dialog("TTS API")
    with body:
        ui.label("Wizmy-Gen-Serverが使えない場合は、一番上のTTS APIを使用します。").classes("note")
        container = ui.column().classes("w-full gap-3")
        with ui.row().classes("w-full"):
            p3_button("TTS APIを追加", lambda: _open_tts_edit(None, ctx, _refresh), classes="btn primary")

    def _reorder(e) -> None:
        ordered = moved_order(
            [endpoint.id for endpoint in ctx.api_config.get_tts_endpoints()],
            e.args["old_index"],
            e.args["new_index"],
        )
        if ordered is None:
            return
        ctx.api_config.reorder_tts_endpoints(ordered)
        notify_order_saved()
        _refresh()

    enable_drag_sort(container, _reorder)

    def _refresh() -> None:
        endpoints = ctx.api_config.get_tts_endpoints()
        container.clear()
        with container:
            if not endpoints:
                ui.label("TTS APIはまだ登録されていません。").classes("note")
            for endpoint in endpoints:
                _tts_card(endpoint)
        on_change()

    def _tts_card(endpoint: TTSEndpoint) -> None:
        with entry_card():
            with ui.row().classes("items-center gap-3 flex-wrap w-full"):
                with ui.column().classes("flex-1 gap-1 min-w-0"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label(endpoint.name).classes("text-sm font-semibold")
                        badge(TTS_PROVIDER_LABELS.get(endpoint.provider, endpoint.provider), tone="peri")
                    ui.label(endpoint.base_url).classes("text-xs font-mono break-all").style(
                        "color: var(--muted);"
                    )
                with ui.row().classes("gap-2"):
                    chip_button("編集", lambda ep=endpoint: _open_tts_edit(ep, ctx, _refresh))
                    chip_button("削除", lambda ep=endpoint: _confirm_delete(ep))

    def _confirm_delete(endpoint: TTSEndpoint) -> None:
        async def _do() -> None:
            ctx.api_config.delete_tts_endpoint(endpoint.id)
            ui.notify("TTS APIを削除しました", type="positive")
            _refresh()

        confirm_dialog(
            f"「{endpoint.name}」を削除しますか?",
            "このTTS APIを選択しているキャラクターは、次の利用時にデフォルトへフォールバックします。",
            _do,
        )

    _refresh()
    dlg.open()


def _open_tts_edit(endpoint: TTSEndpoint | None, ctx, refresh_fn) -> None:
    is_edit = endpoint is not None
    with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg").style(DIALOG_CARD_STYLE):
        ui.label("TTS APIを編集" if is_edit else "TTS APIを追加").classes("text-base font-semibold mb-2")
        name_input = ui.input(
            label="表示名", value=endpoint.name if endpoint else "Irodori-TTS Gradio"
        ).props("outlined dense").classes("w-full p3-fd")
        provider_select = (
            ui.select(
                options=TTS_PROVIDER_LABELS,
                value=endpoint.provider if endpoint else TTS_PROVIDER_IRODORI_GRADIO,
                label="TTS API",
            )
            .props("outlined dense")
            .classes("w-full p3-fd")
        )
        url_input = (
            ui.input(
                label="URL",
                value=endpoint.base_url if endpoint else "http://localhost:7860",
                placeholder="http://localhost:7860",
            )
            .props("outlined dense clearable")
            .classes("w-full p3-fd")
        )
        ui.label("形式: http://host:port").classes("text-xs").style("color: var(--muted);")

        def _provider_changed() -> None:
            if is_edit:
                return
            provider = provider_select.value
            name_input.set_value(TTS_PROVIDER_LABELS.get(provider, "TTS API"))
            if provider == TTS_PROVIDER_IRODORI_GRADIO:
                url_input.set_value("http://localhost:7860")
            elif provider == TTS_PROVIDER_IRODORI_SERVER:
                url_input.set_value("http://localhost:8088")

        provider_select.on("update:model-value", lambda _: _provider_changed())

        def _save() -> None:
            name = str(name_input.value or "").strip()
            base_url = str(url_input.value or "").strip()
            if not name or not base_url:
                ui.notify("表示名とURLを入力してください", type="negative")
                return
            try:
                if is_edit and endpoint is not None:
                    ctx.api_config.update_tts_endpoint(
                        TTSEndpoint(
                            id=endpoint.id,
                            name=name,
                            provider=provider_select.value,
                            base_url=base_url,
                        )
                    )
                else:
                    ctx.api_config.create_tts_endpoint(name, provider_select.value, base_url)
            except ValidationError:
                ui.notify("URLは http://host:port の形式で入力してください。", type="negative")
                return
            ui.notify("TTS APIを保存しました", type="positive")
            dlg.close()
            refresh_fn()

        with ui.row().classes("justify-end gap-2 mt-3 w-full"):
            p3_button("キャンセル", dlg.close, classes="btn quiet")
            p3_button("保存", _save, classes="btn primary")
    dlg.open()


# ---------------------------------------------------------------------------
# 画像生成プロファイル
# ---------------------------------------------------------------------------


def open_image_profiles_dialog(ctx, on_change) -> None:
    dlg, body = settings_dialog("画像生成プロファイル")
    with body:
        ui.label("画像生成API、モデル、プロンプト、パラメータを組み合わせて保存します。").classes("note")
        container = ui.column().classes("w-full gap-3")
        with ui.row().classes("w-full"):
            p3_button(
                "画像生成プロファイルを追加",
                lambda: _open_image_profile_edit(None, ctx, _refresh),
                classes="btn primary",
            )

    def _reorder(e) -> None:
        ordered = moved_order(
            [profile.id for profile in ctx.api_config.get_image_generation_profiles()],
            e.args["old_index"],
            e.args["new_index"],
        )
        if ordered is None:
            return
        ctx.api_config.reorder_image_generation_profiles(ordered)
        notify_order_saved()
        _refresh()

    enable_drag_sort(container, _reorder)

    def _refresh() -> None:
        config = ctx.api_config.get_image_generation_config()
        endpoints = {ep.id: ep for ep in ctx.api_config.get_gen_server_endpoints()}
        container.clear()
        with container:
            if not config.profiles:
                ui.label("画像生成プロファイルはまだ登録されていません。").classes("note")
            for profile in config.profiles:
                _profile_card(profile, endpoints, is_default=profile.id == config.default_profile_id)
        on_change()

    def _profile_card(profile: ImageGenerationProfile, endpoints: dict, *, is_default: bool) -> None:
        endpoint = endpoints.get(profile.endpoint_id)
        params = clean_image_generation_params(profile.params)
        with entry_card():
            with ui.row().classes("items-center gap-3 flex-wrap w-full"):
                with ui.column().classes("flex-1 gap-1 min-w-0"):
                    with ui.row().classes("items-center gap-2 flex-wrap"):
                        ui.label(profile.name or "無題のプロファイル").classes("text-sm font-semibold")
                        badge(IMAGE_PROVIDER_LABELS.get(profile.provider, profile.provider), tone="peri")
                        if is_default:
                            badge("既定", tone="accent")
                    ui.label(
                        f"{endpoint.name if endpoint else 'API未設定'} / {profile.model_id or 'モデル未設定'}"
                    ).classes("text-xs break-all").style("color: var(--muted);")
                    ui.label(
                        f"{params.get('width')}x{params.get('height')} / steps {params.get('steps')} / "
                        f"CFG {params.get('cfg_scale')} / sampler {params.get('sampler')}"
                    ).classes("text-xs").style("color: var(--muted);")
                with ui.row().classes("gap-2"):
                    chip_button("既定にする", lambda p=profile: _set_default(p))
                    chip_button("複製", lambda p=profile: _duplicate(p))
                    chip_button("編集", lambda p=profile: _open_image_profile_edit(p, ctx, _refresh))
                    chip_button("削除", lambda p=profile: _confirm_delete(p))

    def _set_default(profile: ImageGenerationProfile) -> None:
        ctx.api_config.set_default_image_generation_profile(profile.id)
        ui.notify("既定の画像生成プロファイルを保存しました", type="positive", timeout=1200)
        _refresh()

    def _duplicate(profile: ImageGenerationProfile) -> None:
        copied = ctx.api_config.duplicate_image_generation_profile(profile.id)
        if copied is None:
            ui.notify("プロファイルが見つかりません。", type="negative")
            return
        ui.notify("画像生成プロファイルを複製しました", type="positive")
        _refresh()

    def _confirm_delete(profile: ImageGenerationProfile) -> None:
        async def _do() -> None:
            ctx.api_config.delete_image_generation_profile(profile.id)
            ui.notify("画像生成プロファイルを削除しました", type="positive")
            _refresh()

        confirm_dialog(f"「{profile.name}」を削除しますか?", "", _do)

    _refresh()
    dlg.open()


def _open_image_profile_edit(profile: ImageGenerationProfile | None, ctx, refresh_fn) -> None:
    is_edit = profile is not None
    endpoints = ctx.api_config.get_gen_server_endpoints()
    endpoint_options = {ep.id: f"{ep.name} ({ep.base_url})" for ep in endpoints}
    default_endpoint_id = profile.endpoint_id if profile else (endpoints[0].id if endpoints else "")
    default_params = clean_image_generation_params(profile.params if profile else default_image_generation_params())
    controls: dict[str, object] = {}

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-3xl").style(DIALOG_CARD_STYLE):
        ui.label("画像生成プロファイルを編集" if is_edit else "画像生成プロファイルを追加").classes(
            "text-base font-semibold mb-2"
        )
        with ui.column().classes("w-full gap-3").style("max-height: 70vh; overflow-y: auto;"):
            name_input = ui.input(label="プロファイル名", value=profile.name if profile else "").props(
                "outlined dense clearable"
            ).classes("w-full p3-fd")
            provider_select = (
                ui.select(
                    options=IMAGE_PROVIDER_LABELS,
                    value=profile.provider if profile else IMAGE_PROVIDER_WIZMY_GEN_SERVER,
                    label="画像生成API",
                )
                .props("outlined dense")
                .classes("w-full p3-fd")
            )
            endpoint_select = (
                ui.select(
                    options=endpoint_options or {"": "Wizmy-Gen-Server未設定"},
                    value=default_endpoint_id if default_endpoint_id in endpoint_options else "",
                    label="API接続先",
                )
                .props("outlined dense")
                .classes("w-full p3-fd")
            )
            with ui.row().classes("w-full items-end gap-2"):
                model_input = ui.input(label="モデルID", value=profile.model_id if profile else "").props(
                    "outlined dense clearable"
                ).classes("flex-1 p3-fd")

                async def _fetch_model() -> None:
                    endpoint_id = endpoint_select.value or ""
                    if not endpoint_id:
                        ui.notify("先にAPI接続先を選択してください。", type="warning")
                        return
                    await open_model_id_picker(ctx, endpoint_id, GEN_SERVER_MODE_SDXL_IMAGE, model_input)

                chip_button("取得", _fetch_model)

            prompt_input = ui.textarea(
                label="デフォルトプロンプト", value=profile.prompt if profile else ""
            ).props("outlined rows=4").classes("w-full p3-fd")
            negative_input = ui.textarea(
                label="デフォルトネガティブプロンプト", value=profile.negative_prompt if profile else ""
            ).props("outlined rows=3").classes("w-full p3-fd")

            with ui.expansion("詳細パラメータ").props("dense").classes("w-full"):
                with ui.grid(columns=2).classes("w-full gap-3"):
                    for key, spec in IMAGE_GENERATION_PARAMETER_FIELDS.items():
                        controls[key] = build_param_control(key, spec, default_params.get(key))

        def _save() -> None:
            name = str(name_input.value or "").strip()
            if not name:
                ui.notify("プロファイル名を入力してください", type="negative")
                return
            params = {
                key: read_param_value(spec, controls[key].value)
                for key, spec in IMAGE_GENERATION_PARAMETER_FIELDS.items()
            }
            updated = ImageGenerationProfile(
                id=profile.id if profile else "",
                name=name,
                provider=provider_select.value,
                endpoint_id=endpoint_select.value or "",
                model_id=str(model_input.value or "").strip(),
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

        with ui.row().classes("justify-end gap-2 mt-3 w-full"):
            p3_button("キャンセル", dlg.close, classes="btn quiet")
            p3_button("保存", _save, classes="btn primary")
    dlg.open()


# ---------------------------------------------------------------------------
# 行のバッジ表示
# ---------------------------------------------------------------------------


def gen_server_summary(ctx) -> tuple[str, str]:
    config = ctx.api_config.get_gen_server_config()
    if not config.endpoints:
        return "未登録", "muted"
    assigned = sum(1 for mode in GEN_SERVER_ASSIGNABLE_MODES if config.mode_assignments.get(mode))
    return f"{len(config.endpoints)}台 / 割り当て{assigned}", "ok"


def tts_endpoints_summary(ctx) -> tuple[str, str]:
    endpoints = ctx.api_config.get_tts_endpoints()
    if not endpoints:
        return "未登録", "muted"
    return f"{len(endpoints)}件", "ok"


def image_profiles_summary(ctx) -> tuple[str, str]:
    config = ctx.api_config.get_image_generation_config()
    if not config.profiles:
        return "未登録", "muted"
    default = ctx.api_config.get_image_generation_profile(config.default_profile_id)
    if default is not None:
        rest = len(config.profiles) - 1
        return (f"{default.name} ほか {rest}" if rest > 0 else default.name or "無題"), "ok"
    return f"{len(config.profiles)}件", "ok"
