"""
/settings — キャラクター生成(生成プリセット / 選択肢リスト)。

旧 `ui/pages/settings/presets.py` の機能を P3 スキンで再実装。
選択肢リストは「おまかせ」先頭固定・並べ替え・編集・デフォルト復元をそのまま踏襲。
"""

from __future__ import annotations

import uuid

from nicegui import ui

from ....core.character_generation.prompts import AGE_OPTIONS, GENDER_OPTIONS, WORLD_OPTIONS
from ....core.llm.schemas import GenerationPreset
from .common import (
    DIALOG_CARD_STYLE,
    chip_button,
    confirm_dialog,
    enable_drag_sort,
    entry_card,
    moved_order,
    notify_order_saved,
    p3_button,
    settings_dialog,
)

_OMAKASE = "おまかせ"


# ---------------------------------------------------------------------------
# 生成プリセット
# ---------------------------------------------------------------------------


def open_presets_dialog(ctx, on_change) -> None:
    dlg, body = settings_dialog("生成プリセット")
    with body:
        container = ui.column().classes("w-full gap-3")
        with ui.row().classes("w-full"):
            p3_button("プリセットを追加", lambda: _open_preset_edit(None, ctx, _refresh), classes="btn primary")

    async def _reorder(e) -> None:
        ordered = moved_order(
            [preset.id for preset in ctx.api_config.get_generation_presets()],
            e.args["old_index"],
            e.args["new_index"],
        )
        if ordered is None:
            return
        ctx.api_config.reorder_generation_presets(ordered)
        notify_order_saved()
        on_change()

    enable_drag_sort(container, _reorder)

    def _refresh() -> None:
        presets = ctx.api_config.get_generation_presets()
        container.clear()
        with container:
            if not presets:
                ui.label("生成プリセットが登録されていません").classes("note")
            for preset in presets:
                _preset_card(preset)
        on_change()

    def _preset_card(preset) -> None:
        with entry_card():
            with ui.row().classes("items-center gap-3 w-full"):
                with ui.column().classes("flex-1 gap-1 min-w-0"):
                    ui.label(preset.name).classes("text-sm font-semibold")
                    parts = []
                    if preset.world and preset.world != _OMAKASE:
                        parts.append(f"世界観: {preset.world}")
                    if preset.gender and preset.gender != _OMAKASE:
                        parts.append(f"性別: {preset.gender}")
                    if preset.age and preset.age != _OMAKASE:
                        parts.append(f"年齢: {preset.age}")
                    if preset.theme:
                        parts.append(f"テーマ: {preset.theme}")
                    ui.label(" / ".join(parts) if parts else "(指定なし)").classes("text-xs").style(
                        "color: var(--muted);"
                    )
                with ui.row().classes("gap-2"):
                    chip_button("編集", lambda p=preset: _open_preset_edit(p, ctx, _refresh))
                    chip_button("削除", lambda p=preset: _confirm_delete(p))

    def _confirm_delete(preset) -> None:
        async def _do() -> None:
            ctx.api_config.delete_generation_preset(preset.id)
            ui.notify("削除しました", type="positive")
            _refresh()

        confirm_dialog(f"「{preset.name}」を削除しますか?", "", _do)

    _refresh()
    dlg.open()


def _open_preset_edit(preset, ctx, refresh_fn) -> None:
    is_edit = preset is not None
    option_lists = ctx.api_config.get_option_lists()
    world_options = option_lists.get("world") or list(WORLD_OPTIONS)
    gender_options = option_lists.get("gender") or list(GENDER_OPTIONS)
    age_options = option_lists.get("age") or list(AGE_OPTIONS)

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg").style(DIALOG_CARD_STYLE):
        ui.label("生成プリセットを編集" if is_edit else "生成プリセットを追加").classes(
            "text-base font-semibold mb-2"
        )
        name_input = ui.input(label="プリセット名", value=preset.name if preset else "").props(
            "outlined dense"
        ).classes("w-full p3-fd")
        world_select = (
            ui.select(options=world_options, value=preset.world if preset else _OMAKASE, label="世界観")
            .props("outlined dense")
            .classes("w-full p3-fd")
        )
        gender_select = (
            ui.select(options=gender_options, value=preset.gender if preset else _OMAKASE, label="性別")
            .props("outlined dense")
            .classes("w-full p3-fd")
        )
        age_select = (
            ui.select(options=age_options, value=preset.age if preset else _OMAKASE, label="年齢帯")
            .props("outlined dense")
            .classes("w-full p3-fd")
        )
        theme_input = ui.input(label="テーマ・雰囲気", value=preset.theme if preset else "").props(
            "outlined dense"
        ).classes("w-full p3-fd")
        extra_input = ui.textarea(label="その他の要望", value=preset.extra if preset else "").props(
            "outlined rows=3"
        ).classes("w-full p3-fd")

        async def _save() -> None:
            name = str(name_input.value or "").strip()
            if not name:
                ui.notify("プリセット名を入力してください", type="negative")
                return
            updated = GenerationPreset(
                id=preset.id if is_edit else str(uuid.uuid4())[:8],
                name=name,
                world=world_select.value,
                gender=gender_select.value,
                age=age_select.value,
                theme=theme_input.value,
                extra=extra_input.value,
            )
            if is_edit:
                ctx.api_config.update_generation_preset(updated)
            else:
                ctx.api_config.create_generation_preset(updated)
            ui.notify("保存しました", type="positive")
            dlg.close()
            refresh_fn()

        with ui.row().classes("justify-end gap-2 mt-3 w-full"):
            p3_button("キャンセル", dlg.close, classes="btn quiet")
            p3_button("保存", _save, classes="btn primary")
    dlg.open()


# ---------------------------------------------------------------------------
# 選択肢リスト(世界観・年齢帯・性別)
# ---------------------------------------------------------------------------

_SECTION_DEFS = (
    ("world", "世界観", WORLD_OPTIONS),
    ("age", "年齢帯", AGE_OPTIONS),
    ("gender", "性別", GENDER_OPTIONS),
)


def open_options_dialog(ctx, on_change) -> None:
    lists_state: dict[str, list[str]] = ctx.api_config.get_option_lists()
    for key, *_ in _SECTION_DEFS:
        if not lists_state[key] or lists_state[key][0] != _OMAKASE:
            lists_state[key] = [_OMAKASE] + [x for x in lists_state[key] if x != _OMAKASE]

    edit_state: dict[str, int | None] = {key: None for key, *_ in _SECTION_DEFS}
    sections: dict[str, ui.element] = {}

    dlg, body = settings_dialog("生成オプション(選択肢リスト)")
    with body:
        ui.label(
            "「おまかせ」は先頭に固定されています。項目はカードの余白をドラッグして並び替えできます。"
        ).classes("note")

        for key, title, default_opts in _SECTION_DEFS:
            with ui.column().classes("w-full gap-2"):
                with ui.row().classes("items-center gap-2 w-full"):
                    ui.label(title).classes("text-sm font-semibold flex-1")
                    chip_button("デフォルトに戻す", lambda k=key, d=default_opts: _reset_list(k, list(d)))
                with ui.row().classes("items-center gap-2 w-full"):
                    ui.label(_OMAKASE).classes("flex-1 text-sm").style(
                        "padding: 8px 12px; border-radius: 6px; font-style: italic;"
                        " background: var(--bg-2); color: var(--muted); border: 1px solid var(--line);"
                    )
                    ui.label("固定").classes("text-xs").style("color: var(--muted);")
                container = ui.column().classes("w-full gap-2")
                sections[key] = container
                enable_drag_sort(
                    container,
                    lambda e, k=key: _reorder_option(k, e.args["old_index"], e.args["new_index"]),
                )
                with ui.row().classes("items-center gap-2 w-full"):
                    new_input = ui.input(placeholder="新しい項目を入力…").props("outlined dense").classes(
                        "flex-1 p3-fd"
                    )

                    def _make_add(k: str, inp):
                        def _add() -> None:
                            val = str(inp.value or "").strip()
                            if not val:
                                return
                            if val in lists_state[k]:
                                ui.notify("同じ項目がすでに存在します", type="warning")
                                return
                            lists_state[k].append(val)
                            inp.set_value("")
                            _save_and_render(k)

                        return _add

                    chip_button("追加", _make_add(key, new_input))

    def _render_list(k: str) -> None:
        sections[k].clear()
        with sections[k]:
            items = lists_state[k]
            if edit_state[k] is not None and edit_state[k] >= len(items):
                edit_state[k] = None
            if len(items) <= 1:
                ui.label("追加項目はまだありません").classes("note")
                return
            for i in range(1, len(items)):
                item = items[i]
                editing = edit_state[k] == i
                with entry_card():
                    if editing:
                        with ui.row().classes("items-center gap-2 w-full"):
                            inp = ui.input(value=item).props("dense outlined autofocus").classes(
                                "flex-1 p3-fd text-sm"
                            )
                            chip_button("保存", lambda k=k, i=i, inp=inp: _save_edit(k, i, inp))
                            chip_button("取消", lambda k=k: _cancel_edit(k))
                    else:
                        with ui.row().classes("items-center gap-2 w-full"):
                            ui.label(item).classes("flex-1 text-sm")
                            chip_button("編集", lambda k=k, i=i: _start_edit(k, i))
                            chip_button("削除", lambda k=k, i=i: _delete_item(k, i))

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
        notify_order_saved()

    def _start_edit(k: str, idx: int) -> None:
        edit_state[k] = idx
        _render_list(k)

    def _cancel_edit(k: str) -> None:
        edit_state[k] = None
        _render_list(k)

    def _save_edit(k: str, idx: int, inp) -> None:
        if idx >= len(lists_state[k]):
            return
        val = str(inp.value or "").strip()
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
        on_change()

    for key, *_ in _SECTION_DEFS:
        _render_list(key)
    dlg.open()


def presets_summary(ctx) -> tuple[str, str]:
    presets = ctx.api_config.get_generation_presets()
    if not presets:
        return "未登録", "muted"
    return f"{len(presets)}件", "ok"


def options_summary(ctx) -> tuple[str, str]:
    lists_state = ctx.api_config.get_option_lists()
    total = sum(max(0, len(items) - 1) for items in lists_state.values())
    return f"追加 {total}件", "ok" if total else "muted"
