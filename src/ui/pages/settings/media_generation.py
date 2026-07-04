from __future__ import annotations

from pydantic import ValidationError

from nicegui import ui

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
from ....core.tts.schemas import (
    TTS_PROVIDER_IRODORI_GRADIO,
    TTS_PROVIDER_IRODORI_SERVER,
    TTSEndpoint,
)
from .common import (
    TTS_PROVIDER_LABELS,
    build_profile_param_control,
    enable_drag_sort,
    fetch_gen_server_model_id_from_endpoint,
    moved_order,
    notify_order_saved,
    read_gen_server_default_value,
)


GEN_SERVER_ASSIGNABLE_MODES = tuple(mode for mode in GEN_SERVER_MODES if mode != GEN_SERVER_MODE_SDXL_IMAGE)

NO_GEN_SERVER = "__none__"


def build_media_generation_tab(ctx) -> None:
    sub_tabs = ui.tabs().classes("w-full")
    with sub_tabs:
        tab_gen_server = ui.tab("Wizmy-Gen-Server", icon="hub")
        tab_image_generation = ui.tab("画像生成", icon="image")
        tab_tts = ui.tab("TTS", icon="record_voice_over")

    with ui.tab_panels(sub_tabs, value=tab_gen_server).classes("w-full mt-3"):
        with ui.tab_panel(tab_gen_server):
            build_gen_server_tab(ctx)
        with ui.tab_panel(tab_image_generation):
            build_image_generation_tab(ctx)
        with ui.tab_panel(tab_tts):
            build_tts_endpoints_tab(ctx)


def build_image_generation_tab(ctx) -> None:
    ui.label("画像生成プロファイル").classes("text-base font-semibold mb-1")
    ui.label("画像生成API、モデル、プロンプト、パラメータを組み合わせて保存します。").classes(
        "text-sm text-grey-6 mb-3"
    )
    profiles_container = ui.column().classes("w-full gap-3")

    def refresh() -> None:
        config = ctx.api_config.get_image_generation_config()
        endpoints = {endpoint.id: endpoint for endpoint in ctx.api_config.get_gen_server_endpoints()}
        profiles_container.clear()
        with profiles_container:
            if not config.profiles:
                ui.label("画像生成プロファイルはまだ登録されていません。").classes("text-grey-6 py-4")
            for profile in config.profiles:
                image_generation_profile_card(
                    profile,
                    endpoints,
                    ctx,
                    refresh,
                    is_default=profile.id == config.default_profile_id,
                )

    def reorder(e) -> None:
        profiles = ctx.api_config.get_image_generation_profiles()
        ordered = moved_order(
            [profile.id for profile in profiles],
            e.args["old_index"],
            e.args["new_index"],
        )
        if ordered is None:
            return
        ctx.api_config.reorder_image_generation_profiles(ordered)
        notify_order_saved()
        refresh()

    enable_drag_sort(profiles_container, reorder)
    refresh()

    ui.button(
        "画像生成プロファイルを追加",
        icon="add",
        on_click=lambda: open_image_generation_profile_dialog(None, ctx, refresh),
    ).props("color=primary unelevated").classes("mt-2")


def image_generation_profile_card(
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
                        on_click=lambda p=profile: set_default_image_profile(p, ctx, refresh_fn),
                    ).props("flat round dense color=primary").tooltip("既定にする")
                    ui.button(
                        icon="content_copy",
                        on_click=lambda p=profile: duplicate_image_profile(p, ctx, refresh_fn),
                    ).props("flat round dense").tooltip("複製")
                    ui.button(
                        icon="edit",
                        on_click=lambda p=profile: open_image_generation_profile_dialog(p, ctx, refresh_fn),
                    ).props("flat round dense color=primary").tooltip("編集")
                    ui.button(
                        icon="delete",
                        on_click=lambda p=profile: confirm_delete_image_profile(p, ctx, refresh_fn),
                    ).props("flat round dense color=negative").tooltip("削除")


def open_image_generation_profile_dialog(
    profile: ImageGenerationProfile | None,
    ctx,
    refresh_fn,
) -> None:
    is_edit = profile is not None
    endpoints = ctx.api_config.get_gen_server_endpoints()
    endpoint_options = {endpoint.id: f"{endpoint.name} ({endpoint.base_url})" for endpoint in endpoints}
    default_endpoint_id = profile.endpoint_id if profile else (endpoints[0].id if endpoints else "")
    default_params = clean_image_generation_params(profile.params if profile else default_image_generation_params())
    controls: dict[str, object] = {}

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-3xl"):
        ui.label("画像生成プロファイルを編集" if is_edit else "画像生成プロファイルを追加").classes(
            "text-lg font-semibold mb-3"
        )
        name_input = (
            ui.input(
                label="プロファイル名",
                value=profile.name if profile else "",
            )
            .props("outlined clearable")
            .classes("w-full")
        )
        provider_select = (
            ui.select(
                options=IMAGE_PROVIDER_LABELS,
                value=profile.provider if profile else IMAGE_PROVIDER_WIZMY_GEN_SERVER,
                label="画像生成API",
            )
            .props("outlined dense")
            .classes("w-full")
        )
        endpoint_select = (
            ui.select(
                options=endpoint_options or {"": "Wizmy-Gen-Server未設定"},
                value=default_endpoint_id if default_endpoint_id in endpoint_options else "",
                label="API接続先",
            )
            .props("outlined dense")
            .classes("w-full")
        )
        ui.label("外部画像生成APIは今後このタブに追加予定です。").classes("text-xs text-grey-6")

        with ui.row().classes("w-full items-end gap-2"):
            model_input = (
                ui.input(
                    label="モデルID",
                    value=profile.model_id if profile else "",
                )
                .props("outlined dense clearable")
                .classes("flex-1")
            )
            ui.button(
                icon="refresh",
                on_click=lambda: fetch_image_profile_model_id(endpoint_select, model_input, ctx),
            ).props("flat round").tooltip("モデルIDを取得")

        prompt_input = (
            ui.textarea(
                label="デフォルトプロンプト",
                value=profile.prompt if profile else "",
            )
            .props("outlined rows=5")
            .classes("w-full")
        )
        negative_input = (
            ui.textarea(
                label="デフォルトネガティブプロンプト",
                value=profile.negative_prompt if profile else "",
            )
            .props("outlined rows=4")
            .classes("w-full")
        )

        with ui.expansion("詳細パラメータ", icon="tune").props("dense").classes("w-full"):
            with ui.grid(columns=2).classes("w-full gap-3"):
                for key, spec in IMAGE_GENERATION_PARAMETER_FIELDS.items():
                    controls[key] = build_profile_param_control(key, spec, default_params.get(key))

        def _save() -> None:
            name = (name_input.value or "").strip()
            if not name:
                ui.notify("プロファイル名を入力してください", type="negative")
                return
            params = {
                key: read_gen_server_default_value(spec, controls[key])
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


async def fetch_image_profile_model_id(endpoint_select, model_input, ctx) -> None:
    endpoint_id = endpoint_select.value or ""
    if not endpoint_id:
        ui.notify("先にAPI接続先を選択してください。", type="warning")
        return
    await fetch_gen_server_model_id_from_endpoint(
        endpoint_id,
        GEN_SERVER_MODE_SDXL_IMAGE,
        model_input,
        ctx,
    )


def set_default_image_profile(profile: ImageGenerationProfile, ctx, refresh_fn) -> None:
    ctx.api_config.set_default_image_generation_profile(profile.id)
    ui.notify("既定の画像生成プロファイルを保存しました", type="positive", timeout=1200)
    refresh_fn()


def duplicate_image_profile(profile: ImageGenerationProfile, ctx, refresh_fn) -> None:
    copied = ctx.api_config.duplicate_image_generation_profile(profile.id)
    if copied is None:
        ui.notify("プロファイルが見つかりません。", type="negative")
        return
    ui.notify("画像生成プロファイルを複製しました", type="positive")
    refresh_fn()


def confirm_delete_image_profile(profile: ImageGenerationProfile, ctx, refresh_fn) -> None:
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


def build_gen_server_tab(ctx) -> None:
    render_gen_server_chunking_settings(ctx)
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
                        ui.label("Wizmy-Gen-Serverはまだ登録されていません。").classes("text-sm text-grey-6")
                        return

                    options = {NO_GEN_SERVER: "未設定"}
                    options.update({endpoint.id: f"{endpoint.name} ({endpoint.base_url})" for endpoint in endpoints})
                    with ui.grid(columns=1).classes("w-full gap-3"):
                        for mode in GEN_SERVER_ASSIGNABLE_MODES:
                            selected = config.mode_assignments.get(mode) or NO_GEN_SERVER
                            select = (
                                ui.select(
                                    options=options,
                                    value=selected if selected in options else NO_GEN_SERVER,
                                    label=GEN_SERVER_MODE_LABELS.get(mode, mode),
                                )
                                .props("outlined dense")
                                .classes("w-full")
                            )

                            def _make_change(mode: str, select):
                                def _change(_) -> None:
                                    endpoint_id = "" if select.value == NO_GEN_SERVER else select.value
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
            for mode in GEN_SERVER_ASSIGNABLE_MODES:
                with (
                    ui.expansion(
                        GEN_SERVER_MODE_LABELS.get(mode, mode),
                        icon=gen_server_mode_icon(mode),
                    )
                    .props("dense")
                    .classes("w-full")
                ):
                    render_gen_server_mode_defaults(
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
                    mode for mode, endpoint_id in config.mode_assignments.items() if endpoint_id == endpoint.id
                ]
                gen_server_endpoint_card(endpoint, assigned_modes, ctx, refresh)

    def reorder(e) -> None:
        endpoints = ctx.api_config.get_gen_server_endpoints()
        ordered = moved_order(
            [endpoint.id for endpoint in endpoints],
            e.args["old_index"],
            e.args["new_index"],
        )
        if ordered is None:
            return
        ctx.api_config.reorder_gen_server_endpoints(ordered)
        notify_order_saved()
        refresh()

    enable_drag_sort(endpoints_container, reorder)
    refresh()

    ui.button(
        "Wizmy-Gen-Serverを追加",
        icon="add",
        on_click=lambda: open_gen_server_endpoint_dialog(None, ctx, refresh),
    ).props("color=primary unelevated").classes("mt-2")


def render_gen_server_chunking_settings(ctx) -> None:
    config = ctx.api_config.get_gen_server_config()
    with ui.card().classes("w-full mb-4"):
        with ui.card_section():
            ui.label("Irodori-TTS長文分割").classes("text-base font-semibold mb-2")
            chunking_checkbox = ui.checkbox(
                "Irodori-TTS読み上げをWebUI側で分割",
                value=config.voice_chunking_enabled,
            )
            chunk_min_input = (
                ui.number(
                    label="分割最小文字数",
                    value=config.voice_chunk_min_chars,
                    min=1,
                )
                .props("outlined dense")
                .classes("w-full max-w-xs")
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

            with ui.row().classes("justify-end gap-2 mt-3"):
                ui.button("保存", icon="save", on_click=_save).props("color=primary unelevated")


def gen_server_mode_icon(mode: str) -> str:
    if mode == "sdxl_image":
        return "image"
    if mode == "irodori_voice_design":
        return "record_voice_over"
    if mode == "irodori_voice_clone":
        return "graphic_eq"
    return "tune"


def render_gen_server_mode_defaults(mode: str, defaults: dict, ctx) -> None:
    fields = GEN_SERVER_DEFAULT_FIELDS.get(mode, {})
    controls: dict[str, object] = {}

    with ui.grid(columns=2).classes("w-full gap-3"):
        for key, spec in fields.items():
            value = defaults.get(key, spec.get("default"))
            label = spec.get("label", key)
            if spec.get("type") == "boolean":
                controls[key] = ui.checkbox(str(label), value=bool(value)).classes("w-full")
            elif spec.get("enum"):
                controls[key] = (
                    ui.select(
                        options=list(spec["enum"]),
                        value=value if value in spec["enum"] else spec.get("default"),
                        label=str(label),
                    )
                    .props("outlined dense")
                    .classes("w-full")
                )
            elif spec.get("type") in {"integer", "number"}:
                controls[key] = (
                    ui.number(
                        label=str(label),
                        value=value,
                        min=spec.get("minimum"),
                        step=spec.get("step"),
                    )
                    .props("outlined dense")
                    .classes("w-full")
                )
            elif spec.get("multiline"):
                controls[key] = (
                    ui.textarea(
                        label=str(label),
                        value=value or "",
                    )
                    .props("outlined rows=3")
                    .classes("w-full col-span-2")
                )
            elif key == "model_id":
                with ui.row().classes("w-full items-end gap-2"):
                    model_input = (
                        ui.input(
                            label=str(label),
                            value=value or "",
                        )
                        .props("outlined dense clearable")
                        .classes("flex-1")
                    )
                    ui.button(
                        icon="refresh",
                        on_click=lambda mode=mode, model_input=model_input: fetch_gen_server_model_id(
                            mode,
                            model_input,
                            ctx,
                        ),
                    ).props("flat round").tooltip("モデルIDを取得")
                controls[key] = model_input
            else:
                controls[key] = (
                    ui.input(
                        label=str(label),
                        value=value or "",
                    )
                    .props("outlined dense clearable")
                    .classes("w-full")
                )

    def _read_defaults() -> dict:
        return {key: read_gen_server_default_value(spec, controls[key]) for key, spec in fields.items()}

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


async def fetch_gen_server_model_id(mode: str, model_input, ctx) -> None:
    config = ctx.api_config.get_gen_server_config()
    endpoint_id = config.assigned_endpoint_id(mode)
    if not endpoint_id:
        ui.notify("先にこの機能へWizmy-Gen-Serverを割り当ててください。", type="warning")
        return
    await fetch_gen_server_model_id_from_endpoint(endpoint_id, mode, model_input, ctx)


def gen_server_endpoint_card(
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
                            for mode in GEN_SERVER_ASSIGNABLE_MODES:
                                if mode in assigned_modes:
                                    ui.badge(GEN_SERVER_MODE_LABELS.get(mode, mode)).props("outline color=primary")
                        else:
                            ui.badge("未割り当て").props("outline color=grey")

                with ui.row().classes("gap-2"):
                    status_icon = ui.icon("circle").classes("text-grey-4 text-base")
                    ui.button(
                        icon="wifi_tethering",
                        on_click=lambda ep=endpoint: test_gen_server_connection(ep, status_icon, ctx),
                    ).props("flat round dense").tooltip("接続テスト")
                    ui.button(
                        icon="edit",
                        on_click=lambda ep=endpoint: open_gen_server_endpoint_dialog(ep, ctx, refresh_fn),
                    ).props("flat round dense color=primary")
                    ui.button(
                        icon="delete",
                        on_click=lambda ep=endpoint: confirm_delete_gen_server_endpoint(ep, ctx, refresh_fn),
                    ).props("flat round dense color=negative")


async def test_gen_server_connection(endpoint: GenServerEndpoint, status_icon: ui.icon, ctx) -> None:
    status_icon.classes("text-grey-4")
    try:
        capabilities = await ctx.api_config.fetch_gen_server_capabilities(endpoint.id)
    except Exception as err:
        status_icon.classes(remove="text-grey-4 text-positive").classes("text-negative")
        ui.notify(f"「{endpoint.name}」に接続できませんでした: {err}", type="negative")
        return

    modes = capabilities.get("modes", []) if capabilities else []
    status_icon.classes(remove="text-grey-4 text-negative").classes("text-positive")
    labels = [GEN_SERVER_MODE_LABELS.get(mode, mode) for mode in GEN_SERVER_ASSIGNABLE_MODES if mode in modes]
    detail = " / ".join(labels) if labels else "対応機能なし"
    ui.notify(f"「{endpoint.name}」に接続できました: {detail}", type="positive")


def open_gen_server_endpoint_dialog(endpoint: GenServerEndpoint | None, ctx, refresh_fn) -> None:
    is_edit = endpoint is not None

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg"):
        ui.label("Wizmy-Gen-Serverを編集" if is_edit else "Wizmy-Gen-Serverを追加").classes(
            "text-lg font-semibold mb-3"
        )
        name_input = (
            ui.input(
                label="表示名",
                value=endpoint.name if endpoint else "Wizmy-Gen-Server",
            )
            .props("outlined")
            .classes("w-full")
        )
        url_input = (
            ui.input(
                label="API URL",
                value=endpoint.base_url if endpoint else "http://127.0.0.1:8008/v1",
                placeholder="http://127.0.0.1:8008/v1",
            )
            .props("outlined clearable")
            .classes("w-full")
        )
        ui.label("形式: http://host:port または http://host:port/v1").classes("text-xs text-grey-6 mt-1")

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


def confirm_delete_gen_server_endpoint(endpoint: GenServerEndpoint, ctx, refresh_fn) -> None:
    with ui.dialog() as dlg, ui.card():
        ui.label(f"「{endpoint.name}」を削除しますか？").classes("font-medium mb-2")
        ui.label("このサーバーに割り当てられている機能は未設定になります。").classes("text-sm text-grey-6")
        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")

            def _do_delete() -> None:
                ctx.api_config.delete_gen_server_endpoint(endpoint.id)
                ui.notify("Wizmy-Gen-Serverを削除しました", type="positive")
                dlg.close()
                refresh_fn()

            ui.button("削除", on_click=_do_delete).props("color=negative unelevated")
    dlg.open()


def build_tts_endpoints_tab(ctx) -> None:
    ui.label("Wizmy-Gen-Serverが使えない場合は、一番上のTTS APIを使用します。").classes("text-sm text-grey-6 mb-2")
    narrator_container = ui.column().classes("w-full")
    endpoints_container = ui.column().classes("w-full gap-3")

    def refresh_narrator() -> None:
        narrator_container.clear()
        with narrator_container:
            from .narrator import render_narrator_tts_settings

            render_narrator_tts_settings(ctx, refresh_narrator)

    def refresh() -> None:
        refresh_narrator()
        endpoints = ctx.api_config.get_tts_endpoints()
        endpoints_container.clear()
        with endpoints_container:
            if not endpoints:
                ui.label("TTS APIはまだ登録されていません。").classes("text-grey-6 py-4")
            for endpoint in endpoints:
                tts_endpoint_card(
                    endpoint,
                    ctx=ctx,
                    refresh_fn=refresh,
                )

    def reorder(e) -> None:
        endpoints = ctx.api_config.get_tts_endpoints()
        ordered = moved_order(
            [endpoint.id for endpoint in endpoints],
            e.args["old_index"],
            e.args["new_index"],
        )
        if ordered is None:
            return
        ctx.api_config.reorder_tts_endpoints(ordered)
        notify_order_saved()
        refresh()

    enable_drag_sort(endpoints_container, reorder)
    refresh()

    ui.button(
        "TTS APIを追加",
        icon="add",
        on_click=lambda: open_tts_endpoint_dialog(None, ctx, refresh),
    ).props("color=primary unelevated").classes("mt-2")


def tts_endpoint_card(endpoint: TTSEndpoint, *, ctx, refresh_fn) -> None:
    with ui.card().classes("w-full cursor-grab"):
        with ui.card_section():
            with ui.row().classes("items-center gap-3 flex-wrap"):
                with ui.column().classes("flex-1 gap-1"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label(endpoint.name).classes("text-base font-semibold")
                        ui.badge(TTS_PROVIDER_LABELS.get(endpoint.provider, endpoint.provider)).props("color=purple")
                    ui.label(endpoint.base_url).classes("text-sm text-grey-6 font-mono break-all")
                with ui.row().classes("gap-2"):
                    ui.button(
                        icon="edit",
                        on_click=lambda ep=endpoint: open_tts_endpoint_dialog(ep, ctx, refresh_fn),
                    ).props("flat round dense color=primary")
                    ui.button(
                        icon="delete",
                        on_click=lambda ep=endpoint: confirm_delete_tts_endpoint(ep, ctx, refresh_fn),
                    ).props("flat round dense color=negative")


def open_tts_endpoint_dialog(endpoint: TTSEndpoint | None, ctx, refresh_fn) -> None:
    is_edit = endpoint is not None
    default_provider = endpoint.provider if endpoint else TTS_PROVIDER_IRODORI_GRADIO
    default_url = endpoint.base_url if endpoint else "http://localhost:7860"

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg"):
        ui.label("TTS APIを編集" if is_edit else "TTS APIを追加").classes("text-lg font-semibold mb-3")
        name_input = (
            ui.input(
                label="表示名",
                value=endpoint.name if endpoint else "Irodori-TTS Gradio",
            )
            .props("outlined")
            .classes("w-full")
        )
        provider_select = (
            ui.select(
                options=TTS_PROVIDER_LABELS,
                value=default_provider,
                label="TTS API",
            )
            .props("outlined")
            .classes("w-full")
        )
        url_input = (
            ui.input(
                label="URL",
                value=default_url,
                placeholder="http://localhost:7860",
            )
            .props("outlined clearable")
            .classes("w-full")
        )
        ui.label("形式: http://host:port").classes("text-xs text-grey-6 mt-1")

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


def confirm_delete_tts_endpoint(endpoint: TTSEndpoint, ctx, refresh_fn) -> None:
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
