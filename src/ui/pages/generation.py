"""
キャラクター生成ページ。

- ヘッダー行: LLMプロファイル選択 + 生成/停止ボタン
- 左パネル: モード別設定フォーム（新規/修正/関連キャラ）
- 右パネル: 進捗ストリーミング + 結果表示
- モバイル: 縦積みレイアウト
"""

from __future__ import annotations

import asyncio

from nicegui import app, ui

from ...app_context import get_context
from ...core.character_generation.prompts import (
    AGE_OPTIONS,
    GENDER_OPTIONS,
    WORLD_OPTIONS,
)
from ...core.character_generation.schemas import (
    GenerationMode,
    GenerationPreferences,
    GenerationRequest,
    ProgressEventType,
)
from ...services.character_generation import GenerationJob, GenerationJobStatus
from ..components.character_picker import open_character_picker
from ..components.generation_result import (
    build_diff_html,
    build_generation_log,
    open_modify_approve_dialog,
    render_sheet_result,
    show_sheet_placeholder,
)
from ..components.progress_stream import ProgressPanel
from ..layout import page_layout
from ..state import (
    get_active_generation_id,
    get_vault_password,
    is_vault_unlocked,
    set_active_generation_id,
    set_vault_password,
)

_GROUP_DISPLAY_ORDER = ["基本情報", "人物像", "背景設定", "会話設定"]


def _profile_options() -> dict[str, str]:
    ctx = get_context()
    profiles = ctx.api_config.get_llm_profiles()
    endpoints = {ep.id: ep for ep in ctx.api_config.get_endpoints()}
    result: dict[str, str] = {}
    for p in profiles:
        ep = endpoints.get(p.endpoint_id)
        ep_name = ep.name if ep else "不明"
        result[p.id] = f"{p.name} [{ep_name} / {p.model_id or '未設定'}]"
    return result


def _default_generation_profile_id(profile_options: dict[str, str]) -> str:
    if not profile_options:
        return ""
    ctx = get_context()
    default_id = ctx.api_config.get_app_llm_config().generation_profile_id
    if default_id in profile_options:
        return default_id
    return next(iter(profile_options))


def _preset_options() -> dict[str, str]:
    ctx = get_context()
    presets = ctx.api_config.get_generation_presets()
    return {p.id: p.name for p in presets}


@ui.page("/legacy")
async def generation_page() -> None:
    ctx = get_context()

    # character_detail から送られた状態を読み取る
    preset_mode: str = app.storage.user.pop("gen_mode", "")
    preset_char_id: str = app.storage.user.pop("gen_char_id", "")
    preset_char = None
    if preset_char_id:
        preset_char = await ctx.characters.get(preset_char_id)

    current_result: dict = {
        "sheet": "",
        "gen_id": None,
        "mode": GenerationMode.NEW,
        "base_char": None,
        "saved_char": None,
        "gen_result": None,
        "request": None,
        "profile": None,
    }
    watching_job_id: dict[str, str] = {"value": ""}
    generation_starting: dict[str, bool] = {"value": False}
    prompted_modify_review: set[str] = set()

    # 右パネルのベースキャラ展開パネル参照（右パネルで作成後にセットされる）
    base_char_panel: dict = {"expansion": None, "container": None}

    def _refresh_base_char(char) -> None:
        """ベースキャラ展開パネルを更新する。"""
        exp = base_char_panel["expansion"]
        cont = base_char_panel["container"]
        if exp is None or cont is None:
            return
        if char:
            exp.classes(remove="hidden")
            exp.set_value(True)
            render_sheet_result(cont, char.raw_markdown)
        else:
            exp.set_value(False)
            exp.classes("hidden")
            cont.clear()

    progress_panel = ProgressPanel()

    with page_layout("キャラクター生成"):
        # ─── ボルト状態行 ───
        @ui.refreshable
        def vault_status_row() -> None:
            if not is_vault_unlocked() and ctx.api_config.is_vault_setup():
                with ui.row().classes("items-center gap-2 mb-2"):
                    ui.icon("lock").classes("text-warning")
                    ui.label("APIキーボルトがロックされています").classes("text-sm text-warning")
                    ui.button(
                        "ロック解除",
                        on_click=lambda: _open_vault_unlock_dialog(ctx, vault_status_row),
                    ).props("flat size=sm color=warning")

        vault_status_row()

        # ─── 設定からカスタム選択肢を読み込む ───
        _opt = ctx.api_config.get_option_lists()
        _world_opts = _opt.get("world", WORLD_OPTIONS)
        _age_opts = _opt.get("age", AGE_OPTIONS)
        _gender_opts = _opt.get("gender", GENDER_OPTIONS)

        # ─── プロファイル + 生成ボタン行 ───
        profile_options = _profile_options()
        if not profile_options:
            with ui.element("div").style(
                "background: var(--cs-accent-bg); border: 1px solid var(--cs-accent-border); "
                "border-radius: 10px; padding: 14px 18px; margin-bottom: 16px;"
            ):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("info").style("color: var(--cs-accent);")
                    ui.label("LLMプロファイルが未設定です。先に設定を行ってください。").classes("text-sm").style(
                        "color: var(--cs-text);"
                    )
                ui.button(
                    "設定ページへ",
                    icon="settings",
                    on_click=lambda: ui.navigate.to("/legacy/settings"),
                ).props("flat size=sm color=primary").style("margin-top: 6px;")
            return

        with (
            ui.row()
            .classes("w-full items-center gap-3 mb-4 flex-wrap")
            .style(
                "background: var(--cs-surface-soft); border: 1px solid var(--cs-border); "
                "border-radius: 10px; padding: 10px 14px;"
            )
        ):
            ui.icon("computer").style("color: var(--cs-muted); font-size: 1.1rem; flex-shrink: 0;")
            ui.label("LLMプロファイル").classes("text-xs font-semibold shrink-0").style("color: var(--cs-muted);")
            default_profile_id = _default_generation_profile_id(profile_options)
            profile_select = (
                ui.select(
                    options=profile_options,
                    value=default_profile_id,
                    label="",
                )
                .props("dense borderless")
                .classes("flex-1 min-w-[200px]")
            )
            job_status_badge = ui.badge("").classes("hidden")
            ui.space()
            stop_btn = ui.button("停止", icon="stop").props("outline size=sm color=negative").classes("hidden")
            generate_btn = (
                ui.button("生成する", icon="auto_awesome")
                .props("color=primary unelevated")
                .style("font-weight: 600; min-width: 110px; border-radius: 8px;")
            )

        # ─── メインレイアウト ───
        with ui.row().classes("w-full gap-4 flex-col lg:flex-row"):
            # ── 左パネル: 設定フォーム ──
            with ui.column().classes("w-full lg:w-80 gap-3"):
                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center gap-2 mb-3"):
                        ui.icon("tune").style("color: var(--cs-accent); font-size: 1rem;")
                        ui.label("生成設定").classes("text-sm font-semibold").style("color: var(--cs-text);")

                    # タブ名定数（文字列比較に使う）
                    TAB_NEW = "新規生成"
                    TAB_MODIFY = "修正"
                    TAB_RELATED = "関連キャラ"

                    mode_tabs = ui.tabs().classes("w-full")
                    with mode_tabs:
                        tab_new = ui.tab(TAB_NEW, icon="add_circle")
                        tab_modify = ui.tab(TAB_MODIFY, icon="edit")
                        tab_related = ui.tab(TAB_RELATED, icon="person_add")

                    def _active_tab_is(tab_obj: ui.tab, name: str) -> bool:
                        """タブ値がオブジェクトの場合も文字列の場合も正しく判定する。"""
                        val = mode_tabs.value
                        return val is tab_obj or val == name

                    with ui.tab_panels(mode_tabs, value=tab_new).classes("w-full"):
                        # ── 新規生成 ──
                        with ui.tab_panel(tab_new):
                            preset_opts = {"": "（プリセット未使用）"} | _preset_options()
                            preset_select_new = ui.select(
                                options=preset_opts,
                                value="",
                                label="生成プリセット",
                            ).classes("w-full")

                            world_select = ui.select(
                                options=_world_opts, value=_world_opts[0] if _world_opts else "おまかせ", label="世界観"
                            ).classes("w-full")
                            gender_select = ui.select(
                                options=_gender_opts,
                                value=_gender_opts[0] if _gender_opts else "おまかせ",
                                label="性別",
                            ).classes("w-full")
                            age_select = ui.select(
                                options=_age_opts, value=_age_opts[0] if _age_opts else "おまかせ", label="年齢帯"
                            ).classes("w-full")
                            theme_input = ui.input(label="テーマ・雰囲気", placeholder="例: 孤独な戦士").classes(
                                "w-full"
                            )
                            extra_input = (
                                ui.textarea(label="その他の要望", placeholder="自由記述")
                                .classes("w-full")
                                .props("rows=3")
                            )

                            # 同じプリセットで on_value_change が再発火したときの上書きを防ぐ
                            _last_preset_dropdown: dict[str, str] = {"id": ""}

                            def _safe_select_value(options: list[str], want: str, fallback: str) -> str:
                                if want in options:
                                    return want
                                if options:
                                    return options[0]
                                return fallback

                            def _apply_preset_to_form(pid: str) -> None:
                                """プリセットの内容をフォームにコピーするのみ（生成APIには紐付けない）。"""
                                if not pid:
                                    return
                                preset = ctx.api_config.get_generation_preset(pid)
                                if not preset:
                                    return
                                w = _safe_select_value(
                                    _world_opts, (preset.world or "").strip() or "おまかせ", "おまかせ"
                                )
                                g = _safe_select_value(
                                    _gender_opts, (preset.gender or "").strip() or "おまかせ", "おまかせ"
                                )
                                a = _safe_select_value(_age_opts, (preset.age or "").strip() or "おまかせ", "おまかせ")
                                world_select.set_value(w)
                                gender_select.set_value(g)
                                age_select.set_value(a)
                                theme_input.set_value(preset.theme or "")
                                extra_input.set_value(preset.extra or "")

                            def _on_preset_value_change(e) -> None:
                                raw = e.value
                                pid = "" if raw is None else (raw if isinstance(raw, str) else str(raw))
                                if pid == _last_preset_dropdown["id"]:
                                    return
                                _last_preset_dropdown["id"] = pid
                                _apply_preset_to_form(pid)

                            preset_select_new.on_value_change(_on_preset_value_change)

                        # ── 修正 ──
                        with ui.tab_panel(tab_modify):
                            modify_base = {"char": None}
                            _m_has = bool(preset_char and preset_mode == "modify")

                            async def _pick_modify_char() -> None:
                                async def _on_select(c) -> None:
                                    modify_base["char"] = c
                                    modify_name_label.set_text(c.name)
                                    modify_name_label.style(
                                        "font-weight: 700; color: var(--cs-accent); font-size: 0.95rem;"
                                    )
                                    _refresh_base_char(c)

                                await open_character_picker(ctx, _on_select)

                            with ui.element("div").style(
                                "background: var(--cs-accent-bg); border: 1px solid var(--cs-accent-border); "
                                "border-radius: 10px; padding: 12px; margin-bottom: 10px;"
                            ):
                                with ui.row().classes("items-center gap-2 w-full"):
                                    ui.icon("person").style("color: var(--cs-accent); font-size: 1.5rem;")
                                    with ui.column().classes("gap-0 flex-1 min-w-0"):
                                        modify_name_label = (
                                            ui.label(preset_char.name if _m_has else "未選択")
                                            .classes("truncate")
                                            .style(
                                                "font-weight: 700; color: var(--cs-accent); font-size: 0.95rem;"
                                                if _m_has
                                                else "color: var(--cs-muted); font-style: italic; font-size: 0.85rem;"
                                            )
                                        )
                                        ui.label("ベースキャラクター").classes("text-xs").style(
                                            "color: var(--cs-muted);"
                                        )
                                    ui.button(
                                        icon="swap_horiz",
                                        on_click=_pick_modify_char,
                                    ).props("flat round dense size=sm").style("color: var(--cs-muted);").tooltip("変更")

                            if _m_has:
                                modify_base["char"] = preset_char

                            modify_request_input = (
                                ui.textarea(
                                    label="修正の要望",
                                    placeholder="例: 職業を魔法使いに変更してほしい",
                                )
                                .classes("w-full")
                                .props("rows=4")
                            )

                        # ── 関連キャラ ──
                        with ui.tab_panel(tab_related):
                            related_base = {"char": None}
                            _r_has = bool(preset_char and preset_mode == "related")

                            async def _pick_related_char() -> None:
                                async def _on_select(c) -> None:
                                    related_base["char"] = c
                                    related_name_label.set_text(c.name)
                                    related_name_label.style(
                                        "font-weight: 700; color: var(--cs-text); font-size: 0.95rem;"
                                    )
                                    _refresh_base_char(c)

                                await open_character_picker(ctx, _on_select)

                            with ui.element("div").style(
                                "background: var(--cs-surface-soft); border: 1px solid var(--cs-border); "
                                "border-radius: 10px; padding: 12px; margin-bottom: 10px;"
                            ):
                                with ui.row().classes("items-center gap-2 w-full"):
                                    ui.icon("group_add").style("color: var(--cs-muted); font-size: 1.5rem;")
                                    with ui.column().classes("gap-0 flex-1 min-w-0"):
                                        related_name_label = (
                                            ui.label(preset_char.name if _r_has else "未選択")
                                            .classes("truncate")
                                            .style(
                                                "font-weight: 700; color: var(--cs-text); font-size: 0.95rem;"
                                                if _r_has
                                                else "color: var(--cs-muted); font-style: italic; font-size: 0.85rem;"
                                            )
                                        )
                                        ui.label("ベースキャラクター").classes("text-xs").style(
                                            "color: var(--cs-muted);"
                                        )
                                    ui.button(
                                        icon="swap_horiz",
                                        on_click=_pick_related_char,
                                    ).props("flat round dense size=sm").style("color: var(--cs-muted);").tooltip("変更")

                            if _r_has:
                                related_base["char"] = preset_char

                            related_name_input = ui.input(label="新キャラクターの名前（任意）").classes("w-full")
                            related_gender_select = ui.select(
                                options=GENDER_OPTIONS, value="おまかせ", label="性別"
                            ).classes("w-full")
                            related_age_select = ui.select(
                                options=AGE_OPTIONS, value="おまかせ", label="年齢帯"
                            ).classes("w-full")
                            related_theme_input = ui.input(label="テーマ・雰囲気").classes("w-full")
                            related_extra_input = ui.textarea(label="その他の要望").classes("w-full").props("rows=3")

            # ── 右パネル: 進捗 + 結果 ──
            with ui.column().classes("flex-1 gap-3 min-w-0"):
                # ベースキャラクター確認パネル（修正/関連キャラ選択時に展開）
                base_char_expansion = (
                    ui.expansion("ベースキャラクター確認", icon="person", value=False)
                    .classes("w-full hidden")
                    .style(
                        "background: var(--cs-surface); border: 1px solid var(--cs-border); "
                        "border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.06);"
                    )
                )
                with base_char_expansion:
                    base_char_content = (
                        ui.element("div").classes("w-full max-h-[480px] overflow-y-auto").style("padding: 4px 0;")
                    )
                base_char_panel["expansion"] = base_char_expansion
                base_char_panel["container"] = base_char_content

                progress_panel.build()

                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center justify-between mb-3 flex-wrap gap-y-1"):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("description").style("color: var(--cs-accent); font-size: 1rem;")
                            ui.label("生成結果").classes("text-sm font-semibold").style("color: var(--cs-text);")
                        with ui.row().classes("gap-1 items-center flex-wrap"):
                            quality_badge = ui.badge("").classes("hidden")
                            result_sheet_btn = (
                                ui.button(
                                    "シートを開く",
                                    icon="person",
                                    on_click=lambda: (
                                        ui.navigate.to(f"/legacy/characters/{current_result['saved_char'].id}")
                                        if current_result.get("saved_char")
                                        else None
                                    ),
                                )
                                .props("flat size=xs color=primary")
                                .classes("hidden")
                            )
                            result_modify_btn = (
                                ui.button(
                                    "修正する",
                                    icon="edit",
                                    on_click=lambda: (
                                        _send_result_to_modify(current_result["saved_char"])
                                        if current_result.get("saved_char")
                                        else None
                                    ),
                                )
                                .props("flat size=xs color=primary")
                                .classes("hidden")
                            )
                            result_related_btn = (
                                ui.button(
                                    "関連キャラ",
                                    icon="person_add",
                                    on_click=lambda: (
                                        _send_result_to_related(current_result["saved_char"])
                                        if current_result.get("saved_char")
                                        else None
                                    ),
                                )
                                .props("flat size=xs color=secondary")
                                .classes("hidden")
                            )
                            log_download_btn = (
                                ui.button(
                                    icon="assignment_late",
                                    on_click=lambda: _download_log(),
                                )
                                .props("flat round dense")
                                .style("color: var(--cs-muted);")
                                .classes("hidden")
                                .tooltip("詳細ログをダウンロード")
                            )
                            download_btn = (
                                ui.button(icon="download", on_click=lambda: _download_sheet())
                                .props("flat round dense")
                                .style("color: var(--cs-muted);")
                                .classes("hidden")
                                .tooltip("シートをダウンロード")
                            )

                    save_status_label = ui.label("").classes("text-xs hidden").style("color: var(--cs-accent);")

                    result_area = ui.element("div").classes("w-full max-h-[640px] overflow-y-auto")
                    show_sheet_placeholder(result_area)

        # ─── タブ切り替え時のベースキャラパネル制御 ───
        def _on_tab_change(e) -> None:
            tab_name = str(e.args) if e.args else ""
            if tab_name == TAB_NEW or tab_name == "":
                _refresh_base_char(None)
            elif tab_name == TAB_MODIFY:
                _refresh_base_char(modify_base.get("char"))
            else:  # RELATED
                _refresh_base_char(related_base.get("char"))

        mode_tabs.on("update:model-value", _on_tab_change)

        # ─── 自動タブ切り替え（character_detail から送られた場合） ───
        # set_value には文字列を渡す（オブジェクトだと以降の比較が混在するため）
        if preset_mode == "modify":
            mode_tabs.set_value(TAB_MODIFY)
            if preset_char:
                _refresh_base_char(preset_char)
        elif preset_mode == "related":
            mode_tabs.set_value(TAB_RELATED)
            if preset_char:
                _refresh_base_char(preset_char)

        # ─── 結果アクション関数 ───

        def _send_result_to_modify(char) -> None:
            """生成結果キャラを修正モードのベースに設定してタブを切り替える。"""
            modify_base["char"] = char
            modify_name_label.set_text(char.name)
            modify_name_label.style("font-weight: 700; color: var(--cs-accent); font-size: 0.95rem;")
            mode_tabs.set_value(TAB_MODIFY)
            _refresh_base_char(char)

        def _send_result_to_related(char) -> None:
            """生成結果キャラを関連キャラモードのベースに設定してタブを切り替える。"""
            related_base["char"] = char
            related_name_label.set_text(char.name)
            related_name_label.style("font-weight: 700; color: var(--cs-text); font-size: 0.95rem;")
            mode_tabs.set_value(TAB_RELATED)
            _refresh_base_char(char)

        def _show_result_actions(char) -> None:
            """生成完了後のアクションボタンを先頭行に表示する。"""
            result_sheet_btn.classes(remove="hidden")
            result_modify_btn.classes(remove="hidden")
            result_related_btn.classes(remove="hidden")

        def _download_log() -> None:
            r = current_result.get("gen_result")
            if not r:
                return
            mode_val = getattr(current_result.get("mode"), "value", "generate")
            log_text = build_generation_log(
                r,
                mode_val,
                current_result.get("sheet", ""),
                current_result.get("request"),
                current_result.get("profile"),
            )
            ui.download(log_text.encode("utf-8"), "generation_log.txt")

        def _sync_job_badge(job: GenerationJob) -> None:
            labels = {
                GenerationJobStatus.QUEUED: "生成待機中",
                GenerationJobStatus.RUNNING: "生成中",
                GenerationJobStatus.COMPLETED: "完了",
                GenerationJobStatus.FAILED: "失敗",
                GenerationJobStatus.CANCELLED: "停止済み",
            }
            colors = {
                GenerationJobStatus.QUEUED: "warning",
                GenerationJobStatus.RUNNING: "primary",
                GenerationJobStatus.COMPLETED: "positive",
                GenerationJobStatus.FAILED: "negative",
                GenerationJobStatus.CANCELLED: "grey",
            }
            job_status_badge.set_text(labels.get(job.status, job.status.value))
            job_status_badge.props(remove="color")
            job_status_badge.props(f"color={colors.get(job.status, 'grey')}")
            job_status_badge.classes(remove="hidden")

        def _sync_job_controls(job: GenerationJob) -> None:
            is_active = job.is_active
            generate_btn.set_enabled(not is_active)
            if is_active:
                stop_btn.classes(remove="hidden")
            else:
                stop_btn.classes("hidden")
            _sync_job_badge(job)

        async def _apply_saved_character(job: GenerationJob) -> None:
            if not job.saved_character_id:
                return
            saved = await ctx.characters.get(job.saved_character_id)
            if not saved:
                return
            current_result["saved_char"] = saved
            label = "更新済み" if job.request.mode == GenerationMode.MODIFY else "保存済み"
            save_status_label.set_text(f"{label}: {saved.name}")
            save_status_label.classes(remove="hidden")
            _show_result_actions(saved)

        async def _ensure_modify_base(job: GenerationJob):
            if job.request.mode != GenerationMode.MODIFY:
                return None
            if current_result.get("base_char"):
                return current_result["base_char"]
            if not job.base_character_id:
                return None
            base = await ctx.characters.get(job.base_character_id)
            current_result["base_char"] = base
            return base

        async def _open_modify_review_if_needed(job: GenerationJob, result) -> None:
            if job.saved_character_id:
                await _apply_saved_character(job)
                return
            if job.id in prompted_modify_review:
                return

            base = await _ensure_modify_base(job)
            if not base:
                ui.notify("修正元キャラクターを復元できないため、承認ダイアログを開けません。", type="warning")
                return

            prompted_modify_review.add(job.id)
            diff_html = build_diff_html(base.raw_markdown, result.sheet_markdown)

            async def _save_approved():
                from ...core.character.schemas import GenerationMeta
                from ...services.character_generation import parse_markdown_to_sheet

                updated = parse_markdown_to_sheet(result.sheet_markdown, base.id)
                updated.tags = list(base.tags)
                updated.is_favorite = base.is_favorite
                updated.created_at = base.created_at
                updated.generation_meta = GenerationMeta(
                    llm_profile_name=job.profile.name,
                    model_id=job.profile.model_id,
                    temperature=job.profile.temperature if not job.profile.reasoning_enabled else None,
                    reasoning_enabled=job.profile.reasoning_enabled,
                    mode=result.mode.value,
                    tool_count=result.tool_count,
                    quality_status=result.quality_status,
                    quality_score=result.quality_score,
                )
                saved = await ctx.characters.save(updated)
                current_result["saved_char"] = saved
                ctx.generation.mark_job_saved(job.id, saved.id, saved.name)
                _show_result_actions(saved)

            await open_modify_approve_dialog(base.name, diff_html, _save_approved, save_status_label)

        def _prepare_job_view(job: GenerationJob) -> None:
            current_result["gen_id"] = job.id
            current_result["sheet"] = ""
            current_result["mode"] = job.request.mode
            current_result["request"] = job.request
            current_result["profile"] = job.profile
            current_result["base_char"] = None
            current_result["saved_char"] = None
            current_result["gen_result"] = None
            if job.profile.id in profile_options:
                profile_select.set_value(job.profile.id)

            quality_badge.classes("hidden")
            download_btn.classes("hidden")
            log_download_btn.classes("hidden")
            result_sheet_btn.classes("hidden")
            result_modify_btn.classes("hidden")
            result_related_btn.classes("hidden")
            save_status_label.classes("hidden")
            if base_char_panel["expansion"]:
                base_char_panel["expansion"].set_value(False)
            progress_panel.reset()
            show_sheet_placeholder(result_area)
            _sync_job_controls(job)

        async def _handle_job_event(job: GenerationJob, event) -> None:
            progress_panel.handle_event(event)
            _sync_job_controls(job)

            if event.type == ProgressEventType.SHEET_READY:
                current_result["sheet"] = event.data
                render_sheet_result(result_area, event.data)

            elif event.type == ProgressEventType.DONE:
                result = event.data
                if result and result.success:
                    color = {"complete": "positive", "partial": "warning", "failed": "negative"}.get(
                        result.quality_status, "grey"
                    )
                    label = {"complete": "品質: 良好", "partial": "品質: 部分的", "failed": "品質: 低"}.get(
                        result.quality_status, ""
                    )
                    quality_badge.props(f"color={color}")
                    quality_badge.set_text(label)
                    quality_badge.classes(remove="hidden")
                    download_btn.classes(remove="hidden")

                    current_result["gen_result"] = result
                    current_result["sheet"] = result.sheet_markdown
                    log_download_btn.classes(remove="hidden")

                    if job.request.mode == GenerationMode.MODIFY:
                        await _open_modify_review_if_needed(job, result)
                    else:
                        await _apply_saved_character(job)
                        if job.save_error_message:
                            ui.notify(f"保存に失敗しました: {job.save_error_message}", type="negative")

            elif event.type == ProgressEventType.ERROR:
                ui.notify(str(event.data), type="negative", timeout=8000)

        async def _attach_to_job(job_id: str) -> None:
            if watching_job_id["value"] == job_id:
                return

            job = ctx.generation.get_job(job_id)
            if not job:
                return

            watching_job_id["value"] = job_id
            set_active_generation_id(job.id)
            _prepare_job_view(job)
            if job.request.mode == GenerationMode.MODIFY:
                await _ensure_modify_base(job)

            try:
                async for event in ctx.generation.stream_events(job.id):
                    await _handle_job_event(job, event)
                    await asyncio.sleep(0)
            except RuntimeError:
                pass
            finally:
                latest = ctx.generation.get_job(job.id)
                if latest:
                    _sync_job_controls(latest)
                if watching_job_id["value"] == job.id:
                    watching_job_id["value"] = ""

        async def _restore_active_job() -> None:
            job_id = get_active_generation_id()
            job = ctx.generation.get_job(job_id) if job_id else None
            if not job:
                job = ctx.generation.get_latest_active_job()
            if job:
                await _attach_to_job(job.id)

        # ─── イベントハンドラ ───

        async def _start_generation() -> None:
            base_character = None
            if _active_tab_is(tab_new, TAB_NEW):
                mode = GenerationMode.NEW
                prefs = GenerationPreferences(
                    world=world_select.value,
                    gender=gender_select.value,
                    age=age_select.value,
                    theme=theme_input.value,
                    extra=extra_input.value,
                )
                request = GenerationRequest(preferences=prefs, mode=mode)

            elif _active_tab_is(tab_modify, TAB_MODIFY):
                base_char = modify_base["char"]
                if not base_char:
                    ui.notify("ベースにするキャラクターを選択してください", type="negative")
                    return
                base_character = base_char
                mode = GenerationMode.MODIFY
                prefs = GenerationPreferences()
                request = GenerationRequest(
                    preferences=prefs,
                    mode=mode,
                    base_sheet=base_char.raw_markdown,
                    modify_request=modify_request_input.value,
                )

            else:  # related
                base_char = related_base["char"]
                if not base_char:
                    ui.notify("ベースにするキャラクターを選択してください", type="negative")
                    return
                base_character = base_char
                mode = GenerationMode.RELATED
                prefs = GenerationPreferences(
                    gender=related_gender_select.value,
                    age=related_age_select.value,
                    theme=related_theme_input.value,
                    extra=related_extra_input.value,
                )
                request = GenerationRequest(
                    preferences=prefs,
                    mode=mode,
                    base_sheet=base_char.raw_markdown,
                    new_char_name=related_name_input.value.strip(),
                )

            profile_id = profile_select.value
            profile = ctx.api_config.get_llm_profile(profile_id)
            if not profile:
                ui.notify("LLMプロファイルが見つかりません", type="negative")
                return
            if not profile.model_id:
                ui.notify(
                    "モデルIDが未設定です。設定画面でLLMプロファイルのモデルを設定してください。",
                    type="negative",
                    timeout=8000,
                )
                return
            endpoint = ctx.api_config.get_endpoint(profile.endpoint_id)
            if not endpoint:
                ui.notify("エンドポイントが見つかりません", type="negative")
                return

            vault_pw = get_vault_password()
            api_key = ctx.api_config.get_api_key(profile.endpoint_id, vault_pw)
            if ctx.api_config.is_api_key_locked(profile.endpoint_id, api_key):
                ui.notify(
                    "このエンドポイントにはAPIキーが設定されています。APIキーボルトをロック解除してください。",
                    type="warning",
                    timeout=8000,
                )
                return

            job = ctx.generation.start_job(
                request,
                profile,
                endpoint,
                api_key,
                base_character_id=base_character.id if base_character else "",
            )
            await _attach_to_job(job.id)

        async def on_generate() -> None:
            if generation_starting["value"]:
                return
            generation_starting["value"] = True
            generate_btn.set_enabled(False)
            try:
                await _start_generation()
            finally:
                generation_starting["value"] = False
                latest = ctx.generation.get_job(str(current_result.get("gen_id") or ""))
                if latest:
                    _sync_job_controls(latest)
                else:
                    generate_btn.set_enabled(True)

        async def on_stop() -> None:
            if current_result["gen_id"]:
                ctx.generation.stop(current_result["gen_id"])

        def _download_sheet() -> None:
            sheet_md = current_result["sheet"]
            if sheet_md:
                ui.download(sheet_md.encode("utf-8"), "character_sheet.md")

        generate_btn.on("click", on_generate)
        stop_btn.on("click", on_stop)
        ui.timer(0.1, _restore_active_job, once=True)


def _open_vault_unlock_dialog(ctx, refresh_fn) -> None:
    with ui.dialog() as dlg, ui.card().classes("min-w-[300px]"):
        ui.label("ボルトのロック解除").classes("text-base font-semibold mb-3")
        pw_input = ui.input("パスワード").props("type=password clearable").classes("w-full")

        async def _do_unlock() -> None:
            if not pw_input.value:
                ui.notify("パスワードを入力してください", type="warning")
                return
            if ctx.api_config.verify_vault_password(pw_input.value):
                set_vault_password(pw_input.value)
                ui.notify("ロックを解除しました", type="positive")
                dlg.close()
                refresh_fn.refresh()
            else:
                ui.notify("パスワードが正しくありません", type="negative")

        pw_input.on("keydown.enter", _do_unlock)
        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("解除", on_click=_do_unlock).props("color=primary unelevated")
    dlg.open()
