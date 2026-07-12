"""
グループ作成/メンバー追加で共有するセットアップUI+LLM補助ラッパ(ui2)。

- 補助LLM呼び出し(ハンドル生成・世界観補完・名前補完・適応・来訪理由・関係性)の
  実行と通知をまとめる。呼ぶ services は `GroupChatAssistService`。
- 適応(ワールドに馴染ませる)は diff プレビュー(`group_logic.diff_html`)で
  承認してから反映する(パリティ: 適応プレビューdiff)。
- 住人ごとの参加設定ダイアログ(ハンドル/参加設定/来訪理由/適応)を
  作成フロー(pages/groups.py)とメンバー追加(pages/group.py)で共用する。
"""

from __future__ import annotations

import html
from collections.abc import Awaitable, Callable
from typing import Any

from nicegui import ui

from ..core.character.markdown import base_character_markdown, sheet_from_markdown_preserving
from ..core.character.schemas import CharacterSheet
from ..core.conversation.group_setup import (
    fallback_handle,
    fallback_persona_handle,
    sanitize_handle,
    unique_handle,
)
from ..services.ai_jobs import AIJobStatus
from ..services.llm_runtime import (
    API_KEY_LOCKED,
    ENDPOINT_NOT_FOUND,
    MODEL_ID_MISSING,
    PROFILE_NOT_FOUND,
    LLMRuntimeError,
)
from .components.busy import BusyController
from .components.portrait import image_object_position, media_url, raw_img
from .group_logic import diff_html
from .state import get_vault_password

_DIALOG_CARD_STYLE = "background: var(--panel); color: var(--text);"

# キャラクターピッカー(chat.py の相手ピッカーと同スキン)。
# `open_character_pick_dialog` を使うページは `ui.add_css(PICKER_CSS)` で読み込む。
PICKER_CSS = """
/* ---------- キャラクターピッカー(全画面オーバーレイ) ---------- */
.pick-dialog > .q-dialog__backdrop { background: transparent; }
.pick-dialog .q-dialog__inner { padding: 0 !important; }
.pick-dialog .picker-sheet {
  width: 100vw; max-width: 100vw !important;
  height: 100vh; max-height: 100vh !important;
  border-radius: 0; box-shadow: none;
  display: flex; align-items: flex-start; justify-content: center;
  background: color-mix(in srgb, var(--bg) 72%, transparent);
  backdrop-filter: blur(10px);
  overflow-y: auto;
  padding: 7vh 20px 40px;
}
.picker-panel { max-width: 880px; width: 100%; }
.picker-head { display: flex; align-items: center; gap: 12px; margin-bottom: 22px; flex-wrap: wrap; }
.picker-head h2 { margin: 0; font-size: 21px; letter-spacing: .2em; font-weight: 600; }
.picker-head .close { margin-left: auto; }
.picker-head .psearch {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 4px;
  padding: 7px 18px;
  color: var(--text);
  font-size: 13px;
  width: 190px;
  outline: none;
}
.picker-head .psearch::placeholder { color: var(--muted); }
.picker-head .psearch:focus { border-color: var(--peri); }
.picker-empty { padding: 26px 4px; }
.pgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 14px; }
.pcard {
  position: relative;
  aspect-ratio: 3 / 4;
  border-radius: 16px;
  overflow: hidden;
  cursor: pointer;
  background: var(--panel);
  border: 1px solid var(--line);
  transition: transform .18s, border-color .18s, box-shadow .18s;
}
.pcard:hover { transform: translateY(-4px); border-color: var(--accent); box-shadow: var(--shadow); }
.pcard img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
.pcard .p-ph {
  position: absolute; inset: 0;
  display: grid; place-items: center;
  color: var(--peri); font-size: 44px; font-family: "Yu Mincho", serif;
  background: var(--panel-2);
}
.pcard .veil { position: absolute; inset: 0; background: linear-gradient(to top, rgba(7,9,26,.9), transparent 52%); }
.pcard .info { position: absolute; left: 12px; right: 12px; bottom: 10px; color: #f4f5ff; }
.pcard .nm { font-size: 13.5px; letter-spacing: .06em; line-height: 1.4; }
.pcard .st { font-size: 10.5px; opacity: .8; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

@media (max-width: 860px) {
  .pick-dialog .picker-sheet { padding: 4vh 14px 30px; }
  .pgrid { grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 10px; }
  .picker-head .psearch { font-size: 16px; }
}
"""

ENTRY_MODE_OPTIONS = {
    "native": "元々この世界の住人だった",
    "visitor": "何らかの理由でこの世界に来た",
}


def p3_button(label: str, on_click, *, classes: str = "btn", title: str = "") -> ui.element:
    btn = ui.element("button").classes(classes)
    if title:
        btn.props(f'title="{html.escape(title)}"')
    with btn:
        ui.html(html.escape(label))
    btn.on("click", on_click)
    return btn


def chip_button(label: str, on_click, *, title: str = "") -> ui.element:
    return p3_button(label, on_click, classes="chip", title=title)


def notify_setup_llm_error(err: LLMRuntimeError) -> None:
    if err.kind == PROFILE_NOT_FOUND:
        ui.notify("補完用LLMプロファイルを選択してください", type="warning")
    elif err.kind == MODEL_ID_MISSING:
        ui.notify("補完用LLMプロファイルのモデルIDが未設定です", type="negative")
    elif err.kind == ENDPOINT_NOT_FOUND:
        ui.notify("補完用LLMプロファイルのエンドポイントが見つかりません", type="negative")
    elif err.kind == API_KEY_LOCKED:
        ui.notify("APIキーボルトをロック解除してください", type="warning", timeout=8000)
    else:
        ui.notify(f"LLMの初期化に失敗しました: {err}", type="negative", timeout=10000)


def profile_options_for_context(ctx) -> dict[str, str]:
    endpoints = {endpoint.id: endpoint for endpoint in ctx.api_config.get_endpoints()}
    options: dict[str, str] = {}
    for profile in ctx.api_config.get_llm_profiles():
        endpoint = endpoints.get(profile.endpoint_id)
        endpoint_name = endpoint.name if endpoint else "不明"
        model = profile.model_id or "未設定"
        options[profile.id] = f"{profile.name} [{endpoint_name} / {model}]"
    return options


def default_profile_id(ctx, options: dict[str, str]) -> str:
    config = ctx.api_config.get_app_llm_config()
    for profile_id in (config.chat_profile_id, config.generation_profile_id):
        if profile_id in options:
            return profile_id
    return next(iter(options), "")


async def run_assist(
    awaitable,
    *,
    failure_message: str,
) -> Any | None:
    """補助LLM結果の共通ハンドリング(成功値 or None)。"""
    try:
        result = await awaitable
    except LLMRuntimeError as err:
        notify_setup_llm_error(err)
        return None
    except Exception as err:  # noqa: BLE001 - UI通知のための包括捕捉
        ui.notify(f"LLMの初期化に失敗しました: {err}", type="negative", timeout=10000)
        return None
    if result.status == AIJobStatus.CANCELLED:
        ui.notify("生成を停止しました", type="info")
        return None
    if result.status != AIJobStatus.SUCCEEDED:
        ui.notify(f"{failure_message}: {result.error_message}", type="negative", timeout=10000)
        return None
    return result.value


# ---------------------------------------------------------------------------
# 補助LLMラッパ
# ---------------------------------------------------------------------------


async def generate_handles_values(
    ctx,
    profile_id: str,
    characters: list[CharacterSheet],
    persona: Any,
    *,
    reserved_handles: set[str] | None = None,
    include_user: bool = True,
    on_job_started: Callable[[str], None] | None = None,
) -> tuple[dict[str, str], str] | None:
    """ハンドル一括生成。戻り値は (character_id→handle, user_handle)。"""
    if not characters:
        ui.notify("キャラクターを選択してください", type="warning")
        return None
    if persona is None:
        ui.notify("ユーザーペルソナを選択してください", type="warning")
        return None
    suggested = await run_assist(
        ctx.group_chat_assist.generate_handles(
            profile_id=profile_id,
            vault_password=get_vault_password(),
            characters=characters,
            persona=persona,
            on_job_started=on_job_started,
        ),
        failure_message="ハンドル生成に失敗しました",
    )
    if suggested is None:
        return None
    suggested = dict(suggested or {})
    used: set[str] = {handle.lower() for handle in (reserved_handles or set())}
    values: dict[str, str] = {}
    for index, sheet in enumerate(characters, start=1):
        candidate = suggested.get(sheet.id) or suggested.get(sheet.name) or fallback_handle(sheet, index)
        handle = unique_handle(sanitize_handle(candidate, fallback_handle(sheet, index)), used)
        used.add(handle.lower())
        values[sheet.id] = handle
    user_handle = ""
    if include_user:
        user_fallback = fallback_persona_handle(persona)
        candidate = suggested.get("user") or suggested.get(getattr(persona, "display_name", "")) or user_fallback
        user_handle = unique_handle(sanitize_handle(candidate, user_fallback), used)
    ui.notify("ハンドルを生成しました", type="positive")
    return values, user_handle


async def enhance_world_text(
    ctx,
    profile_id: str,
    *,
    current_world: str,
    group_name: str,
    characters: list[CharacterSheet],
    persona: Any,
    on_job_started: Callable[[str], None] | None = None,
) -> str:
    if not current_world.strip():
        ui.notify("先に世界観を入力してください", type="warning")
        return ""
    enhanced = await run_assist(
        ctx.group_chat_assist.enhance_world(
            profile_id=profile_id,
            vault_password=get_vault_password(),
            current_world=current_world,
            group_name=group_name,
            characters=characters,
            persona=persona,
            on_job_started=on_job_started,
        ),
        failure_message="世界観補完に失敗しました",
    )
    if enhanced is None:
        return ""
    if not str(enhanced):
        ui.notify("世界観を補完できませんでした", type="warning")
        return ""
    ui.notify("世界観を補完しました", type="positive")
    return str(enhanced)


async def generate_group_name(
    ctx,
    profile_id: str,
    *,
    world: str,
    characters: list[CharacterSheet],
    persona: Any,
    on_job_started: Callable[[str], None] | None = None,
) -> str:
    if not world.strip():
        ui.notify("先にワールドを入力してください", type="warning")
        return ""
    name = await run_assist(
        ctx.group_chat_assist.generate_group_name_from_world(
            profile_id=profile_id,
            vault_password=get_vault_password(),
            world=world,
            characters=characters,
            persona=persona,
            on_job_started=on_job_started,
        ),
        failure_message="グループ名補完に失敗しました",
    )
    if name is None:
        return ""
    if not str(name):
        ui.notify("グループ名を補完できませんでした", type="warning")
        return ""
    ui.notify("グループ名を補完しました", type="positive")
    return str(name)


async def generate_arrival_reason_text(
    ctx,
    profile_id: str,
    *,
    display_name: str,
    world: str,
    summary: str,
    on_job_started: Callable[[str], None] | None = None,
) -> str:
    if not world.strip():
        ui.notify("先にワールドを確定してください", type="warning")
        return ""
    reason = await run_assist(
        ctx.group_chat_assist.generate_arrival_reason(
            profile_id=profile_id,
            vault_password=get_vault_password(),
            display_name=display_name,
            world=world,
            summary=summary,
            on_job_started=on_job_started,
        ),
        failure_message="来訪理由補完に失敗しました",
    )
    if reason is None:
        return ""
    if not str(reason):
        ui.notify("来訪理由を補完できませんでした", type="warning")
        return ""
    ui.notify("来訪理由を補完しました", type="positive")
    return str(reason)


async def enhance_relationship_text(
    ctx,
    profile_id: str,
    *,
    world: str,
    participants: list[dict[str, str]],
    first_key: str,
    second_key: str,
    current_description: str,
    on_job_started: Callable[[str], None] | None = None,
) -> str:
    current = current_description.strip()
    if not current:
        ui.notify("先に関係性を入力してください", type="warning")
        return ""
    if not first_key or not second_key or first_key == second_key:
        ui.notify("異なる2人を選択してください", type="warning")
        return ""
    enhanced = await run_assist(
        ctx.group_chat_assist.enhance_relationship_description(
            profile_id=profile_id,
            vault_password=get_vault_password(),
            world=world,
            participants=participants,
            first_key=first_key,
            second_key=second_key,
            current_description=current,
            on_job_started=on_job_started,
        ),
        failure_message="関係性補完に失敗しました",
    )
    if enhanced is None:
        return ""
    if not str(enhanced):
        ui.notify("関係性を補完できませんでした", type="warning")
        return ""
    ui.notify("関係性を補完しました", type="positive")
    return str(enhanced)


# ---------------------------------------------------------------------------
# 適応(ワールドに馴染ませる)+diff プレビュー
# ---------------------------------------------------------------------------


def open_adaptation_instruction_dialog(
    display_name: str,
    initial_instruction: str,
    run_adaptation: Callable[[str], Awaitable[None]],
) -> None:
    """「ワールドに馴染ませる」の追加指示ダイアログ。"""
    with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg").style(_DIALOG_CARD_STYLE):
        ui.label("ワールドに馴染ませる").classes("text-base font-semibold")
        ui.label(display_name).classes("note")
        instruction_input = (
            ui.textarea(
                label="追加指示（任意）",
                value=initial_instruction,
                placeholder="例: 職業は変えない、口調は元のままにする",
            )
            .props("outlined rows=5")
            .classes("w-full p3-ta")
        )

        async def _run() -> None:
            instruction = str(instruction_input.value or "").strip()
            dlg.close()
            await run_adaptation(instruction)

        with ui.row().classes("justify-end gap-2 mt-4 w-full"):
            p3_button("キャンセル", dlg.close, classes="btn quiet")
            p3_button("実行", _run, classes="btn primary")
    dlg.open()


def open_diff_preview_dialog(
    *,
    title: str,
    description: str,
    old_text: str,
    new_text: str,
    on_approve: Callable[[], Awaitable[None] | None],
    page_client=None,
) -> None:
    """適応前後の差分プレビュー(承認で反映)。"""

    def _build() -> None:
        with ui.dialog() as dlg, ui.card().classes("w-full max-w-3xl").style(_DIALOG_CARD_STYLE):
            ui.label(title).classes("text-base font-semibold")
            ui.label(description).classes("note")
            ui.html(diff_html(old_text, new_text), sanitize=False).classes("w-full")

            async def _approve() -> None:
                dlg.close()
                result = on_approve()
                if result is not None:
                    await result

            with ui.row().classes("justify-end gap-2 mt-4 w-full"):
                p3_button("キャンセル", dlg.close, classes="btn quiet")
                p3_button("反映", _approve, classes="btn primary").mark("ui2-group-diff-approve")
        dlg.open()

    if page_client is not None and not getattr(page_client, "_deleted", False):
        with page_client:
            _build()
    else:
        _build()


async def adapt_character_with_preview(
    ctx,
    profile_id: str,
    *,
    sheet: CharacterSheet,
    world: str,
    instruction: str,
    apply_callback: Callable[[CharacterSheet], None],
    page_client=None,
    on_job_started: Callable[[str], None] | None = None,
) -> None:
    if not world.strip():
        ui.notify("先にワールドを確定してください", type="warning")
        return
    original_markdown = base_character_markdown(sheet)
    updated_markdown = await run_assist(
        ctx.group_chat_assist.adapt_character_to_world(
            profile_id=profile_id,
            vault_password=get_vault_password(),
            sheet=sheet,
            world=world,
            additional_instruction=instruction,
            on_job_started=on_job_started,
        ),
        failure_message="キャラクターシート調整に失敗しました",
    )
    if updated_markdown is None:
        return
    updated_markdown = str(updated_markdown).strip()
    if not updated_markdown:
        ui.notify("キャラクターシートを調整できませんでした", type="warning")
        return

    def _approve() -> None:
        apply_callback(sheet_from_markdown_preserving(sheet, updated_markdown))
        ui.notify("キャラクターシート調整を反映しました", type="positive")

    open_diff_preview_dialog(
        title="キャラクターシート調整の確認",
        description=f"「{sheet.name}」をワールドに馴染む内容へ変更します。",
        old_text=original_markdown,
        new_text=updated_markdown,
        on_approve=_approve,
        page_client=page_client,
    )


async def adapt_user_persona_with_preview(
    ctx,
    profile_id: str,
    *,
    display_name: str,
    description: str,
    world: str,
    instruction: str,
    apply_callback: Callable[[str], None],
    page_client=None,
    on_job_started: Callable[[str], None] | None = None,
) -> None:
    if not world.strip():
        ui.notify("先にワールドを確定してください", type="warning")
        return
    current = (description or "").strip()
    updated = await run_assist(
        ctx.group_chat_assist.adapt_user_persona_to_world(
            profile_id=profile_id,
            vault_password=get_vault_password(),
            display_name=display_name,
            description=description,
            world=world,
            additional_instruction=instruction,
            on_job_started=on_job_started,
        ),
        failure_message="ユーザーペルソナ調整に失敗しました",
    )
    if updated is None:
        return
    updated = str(updated).strip()
    if not updated:
        ui.notify("ユーザーペルソナを調整できませんでした", type="warning")
        return

    def _approve() -> None:
        apply_callback(updated)
        ui.notify("ユーザーペルソナ調整を反映しました", type="positive")

    open_diff_preview_dialog(
        title="ユーザーペルソナ調整の確認",
        description=f"「{display_name}」をワールドに馴染む説明へ変更します。",
        old_text=current,
        new_text=updated,
        on_approve=_approve,
        page_client=page_client,
    )


# ---------------------------------------------------------------------------
# キャラクターピッカー(pcard グリッド)
# ---------------------------------------------------------------------------


def _render_pick_card(candidate: CharacterSheet, on_choose) -> None:
    card = ui.element("div").classes("pcard")
    card.on("click", lambda sheet=candidate: on_choose(sheet))
    with card:
        image = candidate.media.primary_image()
        url = media_url(image.path) if image is not None else None
        if url is not None:
            raw_img(url).props('loading="lazy"').style(
                f"object-position: {image_object_position(image)};"
            )
        else:
            with ui.element("div").classes("p-ph"):
                ui.html(html.escape((candidate.name or "?")[:1]))
        ui.element("div").classes("veil")
        with ui.element("div").classes("info"):
            with ui.element("div").classes("nm serif"):
                ui.html(html.escape(candidate.name))
            with ui.element("div").classes("st"):
                ui.html(html.escape(candidate.world.strip().splitlines()[0] if candidate.world.strip() else ""))


async def open_character_pick_dialog(
    ctx,
    *,
    title: str,
    exclude_ids: set[str],
    on_select: Callable[[CharacterSheet], Awaitable[None] | None],
) -> None:
    sheets = [sheet for sheet in await ctx.characters.list_all() if sheet.id not in exclude_ids]
    state = {"search": "", "favorites": False}
    dlg = ui.dialog().props("maximized").classes("pick-dialog")

    async def _choose(sheet: CharacterSheet) -> None:
        dlg.close()
        result = on_select(sheet)
        if result is not None:
            await result

    with dlg:
        sheet_box = ui.element("div").classes("picker-sheet")
        with sheet_box:
            with ui.element("div").classes("picker-panel"):
                with ui.element("div").classes("picker-head"):
                    with ui.element("h2").classes("serif"):
                        ui.html(html.escape(title))
                    search_input = (
                        ui.element("input")
                        .classes("psearch")
                        .props('placeholder="名前・世界観で検索" type="search"')
                        .mark("ui2-pick-search")
                    )
                    fav_chip = ui.element("button").classes("chip").mark("ui2-pick-fav")
                    with fav_chip:
                        ui.html("★ お気に入り")
                    p3_button("閉じる", dlg.close, classes="btn quiet close")
                grid = ui.element("div").classes("pgrid").mark("ui2-pick-grid")

    def _refresh_grid() -> None:
        grid.clear()
        query = state["search"].strip().lower()
        entries = []
        for candidate in sheets:
            if state["favorites"] and not candidate.is_favorite:
                continue
            if query:
                haystack = " ".join((candidate.name, candidate.occupation, candidate.world)).lower()
                if query not in haystack:
                    continue
            entries.append(candidate)
        with grid:
            for candidate in entries:
                _render_pick_card(candidate, _choose)
            if not entries:
                with ui.element("div").classes("note picker-empty"):
                    ui.html("該当するキャラクターがいません" if sheets else "選択できるキャラクターがいません")

    def _toggle_favorites() -> None:
        state["favorites"] = not state["favorites"]
        if state["favorites"]:
            fav_chip.classes("on")
        else:
            fav_chip.classes(remove="on")
        _refresh_grid()

    def _on_search(e) -> None:
        state["search"] = str(e.args or "")
        _refresh_grid()

    fav_chip.on("click", _toggle_favorites)
    search_input.on(
        "input",
        _on_search,
        js_handler="(e) => emit(e.target.value)",
        throttle=0.3,
        trailing_events=True,
    )
    _refresh_grid()
    sheet_box.on("click.self", dlg.close)
    dlg.open()


# ---------------------------------------------------------------------------
# 住人ごとの参加設定ダイアログ(作成フロー/メンバー追加 共用)
# ---------------------------------------------------------------------------


def open_resident_settings_dialog(
    ctx,
    *,
    state: dict[str, Any],
    key: str,
    display_name: str,
    summary: str,
    sheet: CharacterSheet | None,
    world_getter: Callable[[], str],
    profile_getter: Callable[[], str],
    busy: BusyController,
    on_change: Callable[[], None],
    handle_editable: bool = True,
    is_world_source: bool = False,
) -> None:
    """住人(キャラ or ユーザーペルソナ)の参加設定を編集する。

    state のキー: handle_values / entry_modes / arrival_reasons /
    adaptation_notes / adaptation_instructions / draft_sheets /
    user_description_draft(ユーザーのみ)。
    """
    page_client = ui.context.client
    is_character = sheet is not None

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-xl").style(_DIALOG_CARD_STYLE):
        ui.label(display_name).classes("text-base font-semibold")
        if summary:
            ui.label(summary).classes("note").style(
                "display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;"
            )
        if is_world_source:
            ui.label("この住人の世界を土台にしているため、参加設定は「世界の土台」に固定されます。").classes("note")

        handle_input = None
        if is_character and handle_editable:
            handle_input = (
                ui.input(
                    label="ハンドル（メンション用・3〜12文字の英数字_）",
                    value=str(state["handle_values"].get(sheet.id) or ""),
                )
                .props("outlined dense")
                .classes("w-full p3-ta")
                .mark("ui2-group-resident-handle")
            )

        entry_select = None
        reason_box: ui.element | None = None
        if not is_world_source:
            entry_select = (
                ui.select(
                    options=ENTRY_MODE_OPTIONS,
                    value=state["entry_modes"].get(key, "native")
                    if state["entry_modes"].get(key, "native") in ENTRY_MODE_OPTIONS
                    else "native",
                    label="ワールド参加設定",
                )
                .props("outlined dense")
                .classes("w-full")
            )
            reason_box = ui.element("div").classes("w-full")

        note_label = ui.label("").classes("note")

        reason_input: dict[str, Any] = {"ref": None}

        def _sync_note() -> None:
            note = state["adaptation_notes"].get(key, "")
            note_label.set_text(note or "")
            note_label.set_visibility(bool(note))

        async def _generate_reason() -> None:
            input_ = reason_input["ref"]
            if input_ is None:
                return
            busy.begin("来訪理由を補完しています...")
            try:
                reason = await generate_arrival_reason_text(
                    ctx,
                    profile_getter(),
                    display_name=display_name,
                    world=world_getter(),
                    summary=summary,
                    on_job_started=busy.set_job,
                )
                if reason:
                    input_.set_value(reason)
            finally:
                busy.end()

        async def _adapt() -> None:
            if entry_select is not None and str(entry_select.value or "native") != "native":
                ui.notify("ワールドに馴染ませる改変は「元々この世界の住人だった」設定で使用してください", type="warning")
                return

            async def _run(instruction: str) -> None:
                if instruction:
                    state["adaptation_instructions"][key] = instruction
                else:
                    state["adaptation_instructions"].pop(key, None)
                busy.begin("ワールドに馴染ませています...")
                try:
                    if is_character:
                        base = state["draft_sheets"].get(sheet.id, sheet)

                        def _apply_sheet(updated: CharacterSheet) -> None:
                            state["draft_sheets"][sheet.id] = updated
                            state["adaptation_notes"][key] = "LLM改変を承認済み"
                            _sync_note()
                            on_change()

                        await adapt_character_with_preview(
                            ctx,
                            profile_getter(),
                            sheet=base,
                            world=world_getter(),
                            instruction=instruction,
                            apply_callback=_apply_sheet,
                            page_client=page_client,
                            on_job_started=busy.set_job,
                        )
                    else:

                        def _apply_description(updated: str) -> None:
                            state["user_description_draft"] = updated
                            state["adaptation_notes"][key] = "LLM改変を承認済み"
                            _sync_note()
                            on_change()

                        await adapt_user_persona_with_preview(
                            ctx,
                            profile_getter(),
                            display_name=display_name,
                            description=str(state.get("user_description_draft") or summary or ""),
                            world=world_getter(),
                            instruction=instruction,
                            apply_callback=_apply_description,
                            page_client=page_client,
                            on_job_started=busy.set_job,
                        )
                finally:
                    busy.end()

            open_adaptation_instruction_dialog(
                display_name,
                state["adaptation_instructions"].get(key, ""),
                _run,
            )

        def _render_reason() -> None:
            if reason_box is None or entry_select is None:
                return
            reason_box.clear()
            reason_input["ref"] = None
            mode = str(entry_select.value or "native")
            with reason_box:
                if mode == "visitor":
                    reason_input["ref"] = (
                        ui.textarea(
                            label="この世界に来た理由",
                            value=state["arrival_reasons"].get(key, ""),
                        )
                        .props("outlined rows=3")
                        .classes("w-full p3-ta")
                        .mark("ui2-group-resident-reason")
                    )
                    chip_button("理由を補完", _generate_reason, title="来訪理由をLLMで補完")
                else:
                    p3_button(
                        "ワールドに馴染ませる",
                        _adapt,
                        classes="btn quiet",
                        title="シートをワールドに合わせて最小限改変(差分を確認してから反映)",
                    ).mark("ui2-group-resident-adapt")

        if entry_select is not None:
            entry_select.on_value_change(lambda _: _render_reason())
            _render_reason()
        _sync_note()

        def _save() -> None:
            if handle_input is not None:
                state["handle_values"][sheet.id] = str(handle_input.value or "").strip()
            if entry_select is not None:
                mode = str(entry_select.value or "native")
                state["entry_modes"][key] = mode
                if mode == "visitor":
                    state["adaptation_notes"].pop(key, None)
                input_ = reason_input["ref"]
                if input_ is not None:
                    state["arrival_reasons"][key] = str(input_.value or "").strip()
                elif mode != "visitor":
                    state["arrival_reasons"].pop(key, None)
            dlg.close()
            on_change()

        with ui.row().classes("justify-end gap-2 mt-4 w-full"):
            p3_button("キャンセル", dlg.close, classes="btn quiet")
            p3_button("保存", _save, classes="btn primary").mark("ui2-group-resident-save")
    dlg.open()
