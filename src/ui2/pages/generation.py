"""
/v2/generation キャラクター生成(Phase 5)。モック proposal3/generation.html 準拠。

- 状態A(入力)→ 状態B(生成中: ベール+章立て+ツールログ)→ 状態C(誕生)が
  同じ場所で遷移する(モックの注記どおり)
- モード3種(新規/既存キャラを修正/関連キャラを生成)・プリセット・
  カスタム選択肢(設定の option_lists)・LLMプロファイル選択・停止・復帰
- 新規/関連はサービス側で自動保存(旧UIと同じ)。修正は承認 diff で上書き
- シート/一覧からの送出プロトコル `gen_mode` / `gen_char_id` を旧UIと共有
- 復帰: `ui2_active_generation`(scope "global")→ get_job、
  無ければ get_latest_active_job(旧UI発のジョブも拾う)
"""

from __future__ import annotations

import asyncio
import html

from nicegui import app, ui

from ...app_context import get_context
from ...core.character.markdown import parse_markdown_to_sheet, sheet_from_markdown_preserving
from ...core.character.schemas import CharacterSheet, GenerationMeta
from ...core.character_generation.prompts import AGE_OPTIONS, GENDER_OPTIONS, WORLD_OPTIONS
from ...core.character_generation.schemas import (
    GenerationMode,
    GenerationPreferences,
    GenerationRequest,
    ProgressEventType,
)
from ...services.character_generation import GenerationJob
from ...ui.state import get_vault_password
from ..components.portrait import face_crop_style
from ..components.sparkle import sparkle_field
from ..generation_logic import build_generation_log, fact_chips
from ..generation_ui import (
    GENERATION_CSS,
    ForgePanel,
    open_modify_approve_dialog,
    open_sheet_dialog,
    recall_active_generation,
    remember_active_generation,
    render_born,
    render_vault_row,
)
from ..group_setup import (
    chip_button,
    default_profile_id,
    open_character_pick_dialog,
    p3_button,
    profile_options_for_context,
)
from ..scaffold import p3_page
from ..sheet_logic import strip_outer_quotes

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


@ui.page("/v2/generation")
async def ui2_generation_page() -> None:
    ctx = get_context()

    # シート/一覧からの送出プロトコル(旧UIと共有)
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
        ui.add_css(GENERATION_CSS)
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

            render_vault_row()

            ask = ui.element("section").classes("ask")
            forge = ui.element("section").classes("forge")
            born = ui.element("section").classes("born")
            forge.set_visibility(False)
            born.set_visibility(False)

        # ---------------- 状態 ----------------
        view = {"mode": preset_mode or "new"}
        bases: dict[str, CharacterSheet | None] = {
            "modify": preset_char if preset_mode == "modify" else None,
            "related": preset_char if preset_mode == "related" else None,
        }
        fields: dict[str, object] = {}
        current: dict = {
            "job_id": "",
            "request": None,
            "profile": None,
            "base_char": None,
            "result": None,
            "sheet": "",
            "saved": None,
        }
        watching = {"id": ""}
        starting = {"flag": False}
        prompted_review: set[str] = set()

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
                ui.html("モデル").classes("note")
                profile_select = (
                    ui.select(
                        options=profile_options,
                        value=_generation_default_profile_id(ctx, profile_options),
                    )
                    .props("outlined dense options-dense")
                    .classes("gen-select")
                    .mark("ui2-gen-profile")
                )
            with ui.element("div").classes("go"):
                p3_button("生成する", lambda: _on_generate(), classes="btn primary").mark("ui2-gen-start")

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

        def _render_form() -> None:
            form_box.clear()
            fields.clear()
            mode_key = view["mode"]
            with form_box:
                if mode_key == "new":
                    fields["theme"] = (
                        ui.textarea(
                            placeholder="例）雨の日にだけ現れる、古書店の番人。ことばより先に、しおりを差し出してくる。"
                        )
                        .classes("p3-ta")
                        .props("outlined rows=3 spellcheck=false")
                        .mark("ui2-gen-theme")
                    )
                    with ui.element("div").classes("gen-quiet"):
                        preset_select = (
                            ui.select(options=preset_options, value="", label="プリセット")
                            .props("outlined dense options-dense")
                            .classes("gen-select")
                        )
                        fields["world"] = (
                            ui.select(
                                options=world_opts,
                                value=world_opts[0] if world_opts else "おまかせ",
                                label="世界観",
                            )
                            .props("outlined dense options-dense")
                            .classes("gen-select")
                        )
                        fields["gender"] = (
                            ui.select(
                                options=gender_opts,
                                value=gender_opts[0] if gender_opts else "おまかせ",
                                label="性別",
                            )
                            .props("outlined dense options-dense")
                            .classes("gen-select")
                        )
                        fields["age"] = (
                            ui.select(
                                options=age_opts,
                                value=age_opts[0] if age_opts else "おまかせ",
                                label="年齢帯",
                            )
                            .props("outlined dense options-dense")
                            .classes("gen-select")
                        )
                    fields["extra"] = (
                        ui.textarea(label="その他の要望（任意）")
                        .classes("p3-ta")
                        .props("outlined rows=2 spellcheck=false")
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
                        fields["theme"].set_value(preset.theme or "")
                        fields["extra"].set_value(preset.extra or "")

                    preset_select.on_value_change(_apply_preset)

                elif mode_key == "modify":
                    _render_base_box("modify")
                    fields["modify_request"] = (
                        ui.textarea(
                            label="修正の要望",
                            placeholder="例: 職業を魔法使いに変更してほしい",
                        )
                        .classes("p3-ta")
                        .props("outlined rows=4 spellcheck=false")
                        .mark("ui2-gen-modify-request")
                    )

                else:  # related
                    _render_base_box("related")
                    fields["related_name"] = (
                        ui.input(label="新キャラクターの名前（任意）").classes("p3-ta").props("outlined dense")
                    )
                    with ui.element("div").classes("gen-quiet"):
                        fields["gender"] = (
                            ui.select(options=gender_opts, value=gender_opts[0] if gender_opts else "おまかせ", label="性別")
                            .props("outlined dense options-dense")
                            .classes("gen-select")
                        )
                        fields["age"] = (
                            ui.select(options=age_opts, value=age_opts[0] if age_opts else "おまかせ", label="年齢帯")
                            .props("outlined dense options-dense")
                            .classes("gen-select")
                        )
                    fields["theme"] = (
                        ui.input(label="テーマ・雰囲気（任意）").classes("p3-ta").props("outlined dense")
                    )
                    fields["extra"] = (
                        ui.textarea(label="その他の要望（任意）")
                        .classes("p3-ta")
                        .props("outlined rows=2 spellcheck=false")
                    )

        _sync_mode_chips()
        _render_form()

        # ---------------- 状態B: 生成中 ----------------

        async def _on_stop() -> None:
            if current["job_id"]:
                ctx.generation.stop(str(current["job_id"]))

        def _back_to_ask() -> None:
            forge.set_visibility(False)
            born.set_visibility(False)
            ask.set_visibility(True)

        forge_panel = ForgePanel(_on_stop, _back_to_ask)
        with forge:
            forge_panel.build()

        # ---------------- 状態C: 誕生 ----------------

        def _restart_with(mode_key: str, sheet: CharacterSheet) -> None:
            bases[mode_key] = sheet
            _set_mode(mode_key)
            _back_to_ask()

        def _download_sheet() -> None:
            sheet_md = str(current.get("sheet") or "")
            if sheet_md:
                ui.download(sheet_md.encode("utf-8"), "character_sheet.md")

        def _download_log() -> None:
            result = current.get("result")
            if not result:
                return
            mode_value = getattr(getattr(current.get("request"), "mode", None), "value", "generate")
            ui.download(
                build_generation_log(
                    result,
                    mode_value,
                    str(current.get("sheet") or ""),
                    current.get("request"),
                    current.get("profile"),
                ).encode("utf-8"),
                "generation_log.txt",
            )

        async def _retake() -> None:
            request = current.get("request")
            if request is None:
                return
            base_char = current.get("base_char")
            await _start_job(request, base_char.id if base_char else "")

        def _render_born_result(job: GenerationJob, result) -> None:
            sheet_md = str(current.get("sheet") or result.sheet_markdown)
            saved: CharacterSheet | None = current.get("saved")
            # 未保存(修正の承認前・保存失敗)でも生成Markdownから表示情報を組み立てる
            display = saved if saved is not None else parse_markdown_to_sheet(sheet_md, "preview")
            name = display.name
            oc = display.occupation
            if display.age:
                oc = f"{oc} ・ {display.age}" if oc else display.age
            intro = strip_outer_quotes(display.self_intro)
            facts = fact_chips(
                world=display.world,
                occupation=display.occupation,
                age=display.age,
                voice_image=display.voice_image,
                quality_status=result.quality_status,
            )
            is_modify = job.request.mode == GenerationMode.MODIFY
            save_note = ""
            save_note_error = False
            if is_modify:
                save_note = f"更新済み: {saved.name}" if saved is not None else "まだ上書きしていません(差分を確認して上書きできます)"
            elif saved is not None:
                save_note = f"保存済み: {saved.name}"
            elif job.save_error_message:
                save_note = f"保存に失敗しました: {job.save_error_message}"
                save_note_error = True

            def _ops() -> None:
                saved_now: CharacterSheet | None = current.get("saved")
                if is_modify and saved_now is None:
                    p3_button(
                        "差分を確認して上書き",
                        lambda: _open_modify_review(job, result, force=True),
                        classes="btn primary",
                    ).mark("ui2-gen-open-diff")
                if saved_now is not None:
                    p3_button(
                        "シートを開く",
                        lambda: ui.navigate.to(f"/v2/characters/{saved_now.id}"),
                        classes="btn primary",
                    ).mark("ui2-gen-open-sheet")
                    p3_button(
                        "チャットをはじめる",
                        lambda: ui.navigate.to(f"/v2/characters/{saved_now.id}/chat"),
                    )
                    p3_button("修正して続ける", lambda: _restart_with("modify", saved_now), classes="btn quiet")
                    p3_button("知りあいを生成", lambda: _restart_with("related", saved_now), classes="btn quiet")
                p3_button("リテイク", _retake, classes="btn quiet", title="同じ指示でもう一度生成する")
                p3_button("全文を表示", lambda: open_sheet_dialog(sheet_md), classes="btn quiet").mark(
                    "ui2-gen-full-sheet"
                )
                p3_button("書き出し(.md)", _download_sheet, classes="btn quiet")
                p3_button("詳細ログ", _download_log, classes="btn quiet")
                p3_button("新しく作る", lambda: _back_to_ask(), classes="btn quiet")

            render_born(
                born,
                name=name,
                oc=oc,
                intro=intro,
                facts=facts,
                save_note=save_note,
                save_note_error=save_note_error,
                build_ops=_ops,
            )
            forge.set_visibility(False)
            born.set_visibility(True)

        # ---------------- 修正承認 diff ----------------

        async def _ensure_modify_base(job: GenerationJob) -> CharacterSheet | None:
            base = current.get("base_char")
            if isinstance(base, CharacterSheet):
                return base
            if not job.base_character_id:
                return None
            base = await ctx.characters.get(job.base_character_id)
            current["base_char"] = base
            return base

        async def _open_modify_review(job: GenerationJob, result, *, force: bool = False) -> None:
            if current.get("saved") is not None:
                return
            if not force and job.id in prompted_review:
                return
            base = await _ensure_modify_base(job)
            if base is None:
                ui.notify("修正元キャラクターを復元できないため、承認ダイアログを開けません。", type="warning")
                return
            prompted_review.add(job.id)

            async def _save_approved() -> None:
                updated = sheet_from_markdown_preserving(base, result.sheet_markdown)
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
                try:
                    saved = await ctx.characters.save(updated)
                except Exception as err:
                    ui.notify(f"保存に失敗しました: {err}", type="negative")
                    return
                current["saved"] = saved
                ctx.generation.mark_job_saved(job.id, saved.id, saved.name)
                ui.notify(f"「{saved.name}」を上書き保存しました", type="positive")
                _render_born_result(job, result)

            open_modify_approve_dialog(
                name=base.name,
                old_markdown=base.raw_markdown,
                new_markdown=result.sheet_markdown,
                on_approve=_save_approved,
            )

        # ---------------- ジョブ実行・復帰 ----------------

        async def _prepare_job_view(job: GenerationJob) -> None:
            current.update(
                {
                    "job_id": job.id,
                    "request": job.request,
                    "profile": job.profile,
                    "base_char": None,
                    "result": None,
                    "sheet": "",
                    "saved": None,
                }
            )
            if job.profile.id in profile_options:
                profile_select.set_value(job.profile.id)
            forge_panel.reset()
            if job.base_character_id:
                current["base_char"] = await ctx.characters.get(job.base_character_id)
            ask.set_visibility(False)
            born.set_visibility(False)
            forge.set_visibility(True)

        async def _handle_event(job: GenerationJob, event) -> None:
            forge_panel.handle_event(event)
            if event.type == ProgressEventType.SHEET_READY:
                current["sheet"] = str(event.data or "")
            elif event.type == ProgressEventType.DONE:
                result = event.data
                if result and result.success:
                    current["result"] = result
                    current["sheet"] = result.sheet_markdown
                    if job.request.mode == GenerationMode.MODIFY:
                        if job.saved_character_id:
                            current["saved"] = await ctx.characters.get(job.saved_character_id)
                        _render_born_result(job, result)
                        if current.get("saved") is None:
                            await _open_modify_review(job, result)
                    else:
                        if job.saved_character_id:
                            current["saved"] = await ctx.characters.get(job.saved_character_id)
                        elif job.save_error_message:
                            ui.notify(f"保存に失敗しました: {job.save_error_message}", type="negative")
                        _render_born_result(job, result)
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
                        theme=str(fields["theme"].value or ""),
                        extra=str(fields["extra"].value or ""),
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
                        theme=str(fields["theme"].value or ""),
                        extra=str(fields["extra"].value or ""),
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
                job = ctx.generation.get_job(job_id)
            if job is None:
                latest = ctx.generation.get_latest_active_job()
                # グループ発として記憶されているジョブは箱庭側で復帰する
                if latest is not None and not (scope.startswith("group:") and latest.id == job_id):
                    job = latest
            if job is not None:
                await _attach_to_job(job.id)

        ui.timer(0.1, _restore_active_job, once=True)
