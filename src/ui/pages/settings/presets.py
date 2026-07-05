from __future__ import annotations

import uuid

from nicegui import ui

from .common import enable_drag_sort, moved_order, notify_order_saved


async def build_presets_tab(ctx) -> None:
    from ....core.character_generation.prompts import AGE_OPTIONS, GENDER_OPTIONS, WORLD_OPTIONS

    presets_container = ui.column().classes("w-full gap-3")

    async def reorder(e) -> None:
        args = e.args
        ordered = moved_order(
            [preset.id for preset in ctx.api_config.get_generation_presets()],
            args["old_index"],
            args["new_index"],
        )
        if ordered is None:
            return
        ctx.api_config.reorder_generation_presets(ordered)
        notify_order_saved()

    enable_drag_sort(presets_container, reorder)

    async def refresh() -> None:
        presets = ctx.api_config.get_generation_presets()
        presets_container.clear()
        with presets_container:
            if not presets:
                ui.label("生成プリセットが登録されていません").classes("text-grey-6 py-4")
            for p in presets:
                preset_card(p, ctx, refresh)

    await refresh()

    def _open_new() -> None:
        open_preset_dialog(None, ctx, refresh, WORLD_OPTIONS, GENDER_OPTIONS, AGE_OPTIONS)

    ui.button("プリセットを追加", icon="add", on_click=_open_new).props("color=primary unelevated").classes("mt-2")


def preset_card(preset, ctx, refresh_fn) -> None:
    from ....core.character_generation.prompts import AGE_OPTIONS, GENDER_OPTIONS, WORLD_OPTIONS

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
                        on_click=lambda p=preset: open_preset_dialog(
                            p, ctx, refresh_fn, WORLD_OPTIONS, GENDER_OPTIONS, AGE_OPTIONS
                        ),
                    ).props("flat round dense color=primary")
                    ui.button(
                        icon="delete",
                        on_click=lambda p=preset: confirm_delete_preset(p, ctx, refresh_fn),
                    ).props("flat round dense color=negative")


def open_preset_dialog(preset, ctx, refresh_fn, WORLD_OPTIONS, GENDER_OPTIONS, AGE_OPTIONS) -> None:
    is_edit = preset is not None

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg"):
        ui.label("生成プリセットを編集" if is_edit else "生成プリセットを追加").classes("text-lg font-semibold mb-3")
        name_input = ui.input(label="プリセット名", value=preset.name if preset else "").classes("w-full")
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
        extra_input = (
            ui.textarea(
                label="その他の要望",
                value=preset.extra if preset else "",
            )
            .classes("w-full")
            .props("rows=3")
        )

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


def confirm_delete_preset(preset, ctx, refresh_fn) -> None:
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


_OMAKASE = "おまかせ"


def build_options_tab(ctx) -> None:
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
        ("world", "世界観", "public", WORLD_OPTIONS),
        ("age", "年齢帯", "cake", AGE_OPTIONS),
        ("gender", "性別", "wc", GENDER_OPTIONS),
    ]

    ui.label("「おまかせ」は先頭に固定されています。項目はカードの余白をドラッグして並び替えできます。").classes(
        "text-sm text-grey-6 mb-4"
    )

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
                                inp = ui.input(value=item).props("dense outlined autofocus").classes("flex-1 text-sm")
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
            enable_drag_sort(
                container,
                lambda e, k=key: _reorder_option(k, e.args["old_index"], e.args["new_index"]),
            )
            sections[key] = {"container": container}
            _render_list(key)

            # 新規追加エリア
            with ui.row().classes("items-center gap-2 mt-3 w-full"):
                new_input = ui.input(placeholder="新しい項目を入力…").classes("flex-1").props("dense outlined")

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

                ui.button(icon="add", on_click=_make_add(key, new_input)).props("color=primary unelevated dense")

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
