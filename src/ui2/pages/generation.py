"""
/generation キャラクター生成(Phase 5)。モック proposal3/generation.html 準拠。

- 入力フォーム+フォーム下のフェーズ進捗(ForgeStrip)。完成したら:
  新規/関連(自動保存済み)→ キャラシへ直行(確認バーを一度だけ表示)、
  修正 → 暫定キャラシ(/generation/review/{job_id})で差分確認
- モード3種(新規/既存キャラを修正/関連キャラを生成)・プリセット・
  カスタム選択肢(設定の option_lists)・LLMプロファイル選択・停止
- シート/一覧からの送出プロトコルは `gen_mode` / `gen_char_id`
- 復帰: 実行中ジョブのみ(`ui2_active_generation` scope "global" →
  無ければ get_latest_active_job)。完了済みジョブは再生しない
"""

from __future__ import annotations

import asyncio
import html

from nicegui import app, ui

from ...app_context import get_context
from ...core.character.schemas import CharacterSheet
from ...core.character_generation.prompts import AGE_OPTIONS, GENDER_OPTIONS, WORLD_OPTIONS
from ...core.character_generation.schemas import (
    GenerationMode,
    GenerationPreferences,
    GenerationRequest,
    ProgressEventType,
)
from ...services.character_generation import GenerationJob
from ..components.portrait import face_crop_style
from ..components.sparkle import sparkle_field
from ..generation_ui import (
    GEN_CONFIRM_KEY,
    GENERATION_CSS,
    ForgeStrip,
    open_sheet_dialog,
    recall_active_generation,
    remember_active_generation,
)
from ..group_setup import (
    PICKER_CSS,
    chip_button,
    default_profile_id,
    open_character_pick_dialog,
    p3_button,
    profile_options_for_context,
)
from ..scaffold import p3_page
from ..state import get_vault_password

_MODE_LABELS: list[tuple[str, str]] = [
    ("new", "新規生成"),
    ("modify", "既存キャラを修正"),
    ("related", "関連キャラを生成"),
]


def _generation_default_profile_id(ctx, options: dict[str, str]) -> str:
    default = ctx.api_config.get_app_llm_config().generation_profile_id
    if default in options:
        return default
    return default_profile_id(ctx, options)


@ui.page("/generation")
async def ui2_generation_page() -> None:
    ctx = get_context()

    # シート/一覧からの送出プロトコル
    preset_mode = str(app.storage.user.pop("gen_mode", "") or "")
    preset_char_id = str(app.storage.user.pop("gen_char_id", "") or "")
    preset_char = await ctx.characters.get(preset_char_id) if preset_char_id else None
    if preset_mode not in {"modify", "related"} or preset_char is None:
        preset_mode = ""

    profile_options = profile_options_for_context(ctx)
    option_lists = ctx.api_config.get_option_lists()
    world_opts = option_lists.get("world", WORLD_OPTIONS)
    gender_opts = option_lists.get("gender", GENDER_OPTIONS)
    age_opts = option_lists.get("age", AGE_OPTIONS)
    preset_options = {"": "プリセットを使わない"} | {
        preset.id: preset.name for preset in ctx.api_config.get_generation_presets()
    }

    with p3_page("生成"):
        ui.add_css(GENERATION_CSS + PICKER_CSS)
        with ui.element("div").classes("gen-wrap"):
            if not profile_options:
                with ui.element("section").classes("ask"):
                    with ui.element("h1").classes("serif"):
                        ui.html("まだ、ことばの糸口がありません。")
                    with ui.element("div").classes("sub"):
                        ui.html("LLMプロファイルが未設定です。先に設定を行ってください。")
                    with ui.element("div").classes("go"):
                        p3_button("設定ページへ", lambda: ui.navigate.to("/settings"))
                return

            ask = ui.element("section").classes("ask")

        # ---------------- 状態 ----------------
        view = {"mode": preset_mode or "new"}
        bases: dict[str, CharacterSheet | None] = {
            "modify": preset_char if preset_mode == "modify" else None,
            "related": preset_char if preset_mode == "related" else None,
        }
        fields: dict[str, object] = {}
        watching = {"id": ""}
        starting = {"flag": False}

        # ---------------- 状態A: 入力 ----------------
        with ask:
            sparkle_field(16)
            with ui.element("h1").classes("serif"):
                ui.html("どんなキャラクターを作りますか。")
            with ui.element("div").classes("sub"):
                ui.html("ひとことで構いません。続きはAIが膨らませます")
            modes_row = ui.element("div").classes("modes")
            form_box = ui.element("div").classes("form-box")
            with ui.element("div").classes("gen-quiet gen-profile-row"):
                with ui.element("label").classes("q-lbl"):
                    ui.html("モデル")
                    profile_select = (
                        ui.select(
                            options=profile_options,
                            value=_generation_default_profile_id(ctx, profile_options),
                        )
                        .props("borderless dense options-dense")
                        .classes("gen-select")
                        .mark("ui2-gen-profile")
                    )
            with ui.element("div").classes("go"):
                start_btn = p3_button("生成する", lambda: _on_generate(), classes="btn primary").mark(
                    "ui2-gen-start"
                )
            strip_box = ui.element("div").classes("gen-strip")
            strip_box.set_visibility(False)

        mode_chips: dict[str, ui.element] = {}
        with modes_row:
            for mode_key, label in _MODE_LABELS:
                chip = chip_button(label, lambda k=mode_key: _set_mode(k))
                chip.mark(f"ui2-gen-mode-{mode_key}")
                mode_chips[mode_key] = chip

        def _sync_mode_chips() -> None:
            for mode_key, chip in mode_chips.items():
                if mode_key == view["mode"]:
                    chip.classes("on")
                else:
                    chip.classes(remove="on")

        def _set_mode(mode_key: str) -> None:
            view["mode"] = mode_key
            _sync_mode_chips()
            _render_form()

        def _render_base_box(kind: str) -> None:
            sheet = bases[kind]
            with ui.element("div").classes("base-box"):
                face = ui.element("div").classes("b-face")
                style = face_crop_style(sheet.media.primary_image()) if sheet is not None else ""
                if style:
                    face.style(style)
                else:
                    with face:
                        ui.html(html.escape((sheet.name if sheet else "?")[:1]))
                with ui.element("div").classes("b-name"):
                    ui.html(
                        html.escape(sheet.name if sheet is not None else "未選択")
                        + '<span class="b-sub">ベースキャラクター</span>'
                    )
                if sheet is not None:
                    chip_button("シートを確認", lambda s=sheet: open_sheet_dialog(s.raw_markdown, title=s.name))
                chip_button("選ぶ" if sheet is None else "変更", lambda: _pick_base(kind)).mark(
                    f"ui2-gen-pick-{kind}"
                )

        async def _pick_base(kind: str) -> None:
            async def _on_select(sheet: CharacterSheet) -> None:
                bases[kind] = sheet
                _render_form()

            await open_character_pick_dialog(
                ctx,
                title="ベースにするキャラクターを選ぶ",
                exclude_ids=set(),
                on_select=_on_select,
            )

        def _quiet_select(label_text: str, options, value) -> ui.select:
            """モック quiet-row のラベル+下線セレクト。"""
            with ui.element("label").classes("q-lbl"):
                ui.html(html.escape(label_text))
                return (
                    ui.select(options=options, value=value)
                    .props("borderless dense options-dense")
                    .classes("gen-select")
                )

        def _render_form() -> None:
            form_box.clear()
            fields.clear()
            mode_key = view["mode"]
            with form_box:
                if mode_key == "new":
                    with ui.element("div").classes("gen-quiet gen-preset-row"):
                        preset_select = _quiet_select("プリセット", preset_options, "")
                    fields["prompt"] = (
                        ui.textarea(placeholder="要望があればどうぞ（任意）")
                        .classes("ask-ta")
                        .props("borderless rows=3 spellcheck=false")
                        .mark("ui2-gen-extra")
                    )
                    with ui.element("div").classes("gen-quiet"):
                        fields["world"] = _quiet_select(
                            "世界観", world_opts, world_opts[0] if world_opts else "おまかせ"
                        )
                        fields["gender"] = _quiet_select(
                            "性別", gender_opts, gender_opts[0] if gender_opts else "おまかせ"
                        )
                        fields["age"] = _quiet_select(
                            "年齢", age_opts, age_opts[0] if age_opts else "おまかせ"
                        )

                    applied = {"id": ""}

                    def _apply_preset(e) -> None:
                        pid = str(e.value or "")
                        if pid == applied["id"]:
                            return
                        applied["id"] = pid
                        if not pid:
                            return
                        preset = ctx.api_config.get_generation_preset(pid)
                        if not preset:
                            return

                        def _safe(options: list[str], want: str) -> str:
                            want = (want or "").strip() or "おまかせ"
                            if want in options:
                                return want
                            return options[0] if options else "おまかせ"

                        fields["world"].set_value(_safe(world_opts, preset.world))
                        fields["gender"].set_value(_safe(gender_opts, preset.gender))
                        fields["age"].set_value(_safe(age_opts, preset.age))
                        combined = "\n".join(
                            part
                            for part in ((preset.theme or "").strip(), (preset.extra or "").strip())
                            if part
                        )
                        fields["prompt"].set_value(combined)

                    preset_select.on_value_change(_apply_preset)

                elif mode_key == "modify":
                    _render_base_box("modify")
                    fields["modify_request"] = (
                        ui.textarea(placeholder="修正の要望（例: 職業を魔法使いに変更してほしい）")
                        .classes("ask-ta")
                        .props("borderless rows=4 spellcheck=false")
                        .mark("ui2-gen-modify-request")
                    )

                else:  # related
                    _render_base_box("related")
                    fields["related_name"] = (
                        ui.input(label="新キャラクターの名前（任意）").classes("p3-ta").props("outlined dense")
                    )
                    fields["prompt"] = (
                        ui.textarea(placeholder="テーマ・雰囲気や要望があればどうぞ（任意）")
                        .classes("ask-ta")
                        .props("borderless rows=3 spellcheck=false")
                    )
                    with ui.element("div").classes("gen-quiet"):
                        fields["gender"] = _quiet_select(
                            "性別", gender_opts, gender_opts[0] if gender_opts else "おまかせ"
                        )
                        fields["age"] = _quiet_select(
                            "年齢", age_opts, age_opts[0] if age_opts else "おまかせ"
                        )

        _sync_mode_chips()
        _render_form()

        # ---------------- 生成進捗(フォーム下) ----------------

        async def _on_stop() -> None:
            if watching["id"]:
                ctx.generation.stop(str(watching["id"]))

        def _hide_strip() -> None:
            strip_box.set_visibility(False)

        forge_strip = ForgeStrip(_on_stop, _hide_strip)
        with strip_box:
            forge_strip.build()

        def _set_running(running: bool) -> None:
            if running:
                start_btn.props("disabled")
            else:
                start_btn.props(remove="disabled")

        # ---------------- ジョブ実行・復帰 ----------------

        async def _prepare_job_view(job: GenerationJob) -> None:
            if job.profile.id in profile_options:
                profile_select.set_value(job.profile.id)
            forge_strip.reset()
            strip_box.set_visibility(True)
            _set_running(True)

        async def _handle_event(job: GenerationJob, event) -> None:
            forge_strip.handle_event(event)
            if event.type == ProgressEventType.DONE:
                result = event.data
                if result and result.success:
                    if job.request.mode == GenerationMode.MODIFY:
                        ui.navigate.to(f"/generation/review/{job.id}")
                    elif job.saved_character_id:
                        # 保存済みキャラのシートへ直行し、確認バーを一度だけ出す
                        app.storage.user[GEN_CONFIRM_KEY] = {
                            "char_id": job.saved_character_id,
                            "job_id": job.id,
                        }
                        ui.navigate.to(f"/characters/{job.saved_character_id}")
                    else:
                        ui.notify(
                            f"保存に失敗しました: {job.save_error_message or '不明なエラー'}",
                            type="negative",
                            timeout=8000,
                        )
                elif result:
                    ui.notify(result.error_message or "生成に失敗しました。", type="negative")
            elif event.type == ProgressEventType.ERROR:
                ui.notify(str(event.data), type="negative", timeout=8000)

        async def _attach_to_job(job_id: str) -> None:
            if watching["id"] == job_id:
                return
            job = ctx.generation.get_job(job_id)
            if not job:
                return
            watching["id"] = job_id
            remember_active_generation(job.id, "global")
            await _prepare_job_view(job)
            try:
                async for event in ctx.generation.stream_events(job.id):
                    await _handle_event(job, event)
                    await asyncio.sleep(0)
            except RuntimeError:
                pass
            finally:
                if watching["id"] == job.id:
                    watching["id"] = ""
                    try:
                        _set_running(False)
                    except RuntimeError:
                        pass

        async def _start_job(request: GenerationRequest, base_character_id: str) -> None:
            profile = ctx.api_config.get_llm_profile(str(profile_select.value or ""))
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
            api_key = ctx.api_config.get_api_key(profile.endpoint_id, get_vault_password())
            if ctx.api_config.is_api_key_locked(profile.endpoint_id, api_key):
                ui.notify(
                    "このエンドポイントにはAPIキーが設定されています。ボルトを解錠してください。",
                    type="warning",
                    timeout=8000,
                )
                return
            job = ctx.generation.start_job(
                request,
                profile,
                endpoint,
                api_key,
                base_character_id=base_character_id,
            )
            await _attach_to_job(job.id)

        async def _start_generation() -> None:
            mode_key = view["mode"]
            base_character: CharacterSheet | None = None
            if mode_key == "new":
                request = GenerationRequest(
                    preferences=GenerationPreferences(
                        world=str(fields["world"].value or "おまかせ"),
                        gender=str(fields["gender"].value or "おまかせ"),
                        age=str(fields["age"].value or "おまかせ"),
                        theme=str(fields["prompt"].value or ""),
                        extra="",
                    ),
                    mode=GenerationMode.NEW,
                )
            elif mode_key == "modify":
                base_character = bases["modify"]
                if base_character is None:
                    ui.notify("ベースにするキャラクターを選択してください", type="negative")
                    return
                request = GenerationRequest(
                    preferences=GenerationPreferences(),
                    mode=GenerationMode.MODIFY,
                    base_sheet=base_character.raw_markdown,
                    modify_request=str(fields["modify_request"].value or ""),
                )
            else:
                base_character = bases["related"]
                if base_character is None:
                    ui.notify("ベースにするキャラクターを選択してください", type="negative")
                    return
                request = GenerationRequest(
                    preferences=GenerationPreferences(
                        gender=str(fields["gender"].value or "おまかせ"),
                        age=str(fields["age"].value or "おまかせ"),
                        theme=str(fields["prompt"].value or ""),
                        extra="",
                    ),
                    mode=GenerationMode.RELATED,
                    base_sheet=base_character.raw_markdown,
                    new_char_name=str(fields["related_name"].value or "").strip(),
                )
            await _start_job(request, base_character.id if base_character else "")

        async def _on_generate() -> None:
            if starting["flag"]:
                return
            starting["flag"] = True
            try:
                await _start_generation()
            finally:
                starting["flag"] = False

        async def _restore_active_job() -> None:
            job_id, scope = recall_active_generation()
            job = None
            if job_id and scope == "global":
                candidate = ctx.generation.get_job(job_id)
                if candidate is not None and candidate.is_active:
                    job = candidate
            if job is None:
                latest = ctx.generation.get_latest_active_job()
                # グループ発として記憶されているジョブは箱庭側で復帰する
                if latest is not None and not (scope.startswith("group:") and latest.id == job_id):
                    job = latest
            if job is not None:
                await _attach_to_job(job.id)

        ui.timer(0.1, _restore_active_job, once=True)
