from __future__ import annotations

from nicegui import ui

from ...state import clear_vault_password, is_vault_unlocked, set_vault_password


async def build_vault_tab(ctx) -> None:
    vault_container = ui.column().classes("w-full gap-4")

    async def refresh() -> None:
        vault_container.clear()
        with vault_container:
            if not ctx.api_config.is_vault_setup():
                build_vault_setup(ctx, refresh)
            elif not is_vault_unlocked():
                build_vault_unlock(ctx, refresh)
            else:
                build_vault_unlocked(ctx, refresh)

    await refresh()


def build_vault_setup(ctx, refresh_fn) -> None:
    with ui.card().classes("w-full max-w-lg"):
        ui.label("APIキーボルトの設定").classes("text-lg font-semibold mb-2")
        ui.label(
            "APIキーを暗号化して保存するためのマスターパスワードを設定します。"
            " パスワードを忘れた場合はボルトをリセットする必要があります。"
        ).classes("text-sm text-grey-6 mb-4")
        pw1 = ui.input(label="マスターパスワード").props("type=password clearable").classes("w-full")
        pw2 = ui.input(label="パスワードの確認").props("type=password clearable").classes("w-full")

        async def _setup() -> None:
            if not pw1.value:
                ui.notify("パスワードを入力してください", type="negative")
                return
            if pw1.value != pw2.value:
                ui.notify("パスワードが一致しません", type="negative")
                return
            ctx.api_config.setup_vault(pw1.value)
            set_vault_password(pw1.value)
            ui.notify("ボルトを設定しました", type="positive")
            await refresh_fn()

        ui.button("ボルトを設定", on_click=_setup).props("color=primary unelevated").classes("mt-2")


def build_vault_unlock(ctx, refresh_fn) -> None:
    with ui.card().classes("w-full max-w-lg"):
        ui.label("ボルトのロック解除").classes("text-lg font-semibold mb-2")
        with ui.row().classes("items-center gap-2 mb-3"):
            ui.icon("lock").classes("text-warning text-2xl")
            ui.label("ボルトはロックされています").classes("text-warning font-medium")

        pw_input = ui.input(label="マスターパスワード").props("type=password clearable").classes("w-full")

        async def _unlock() -> None:
            if ctx.api_config.verify_vault_password(pw_input.value):
                set_vault_password(pw_input.value)
                ui.notify("ボルトのロックを解除しました", type="positive")
                await refresh_fn()
            else:
                ui.notify("パスワードが正しくありません", type="negative")

        ui.button("ロック解除", on_click=_unlock).props("color=primary unelevated").classes("mt-2")


def build_vault_unlocked(ctx, refresh_fn) -> None:
    with ui.card().classes("w-full max-w-lg"):
        with ui.row().classes("items-center justify-between mb-4"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("lock_open").classes("text-positive text-2xl")
                ui.label("ボルトはロック解除されています").classes("text-positive font-medium")
            ui.button(
                "ロック",
                icon="lock",
                on_click=lambda: _lock(refresh_fn),
            ).props("flat color=warning size=sm")

        ui.label("APIキーの設定はエンドポイントカードから行えます。").classes("text-sm text-grey-6 mb-4")

        ui.separator()
        ui.label("ボルトの管理").classes("text-base font-semibold mt-3 mb-2")
        with ui.row().classes("gap-3"):
            ui.button(
                "パスワードを変更",
                icon="password",
                on_click=lambda: open_change_password(ctx, refresh_fn),
            ).props("outline color=primary")
            ui.button(
                "ボルトをリセット",
                icon="delete_forever",
                on_click=lambda: confirm_teardown(ctx, refresh_fn),
            ).props("outline color=negative")


async def _lock(refresh_fn) -> None:
    clear_vault_password()
    ui.notify("ボルトをロックしました", type="info")
    await refresh_fn()


def open_change_password(ctx, refresh_fn) -> None:
    with ui.dialog() as dlg, ui.card().classes("min-w-[360px]"):
        ui.label("マスターパスワードの変更").classes("text-lg font-semibold mb-3")
        old_pw = ui.input(label="現在のパスワード").props("type=password clearable").classes("w-full")
        new_pw1 = ui.input(label="新しいパスワード").props("type=password clearable").classes("w-full")
        new_pw2 = ui.input(label="新しいパスワード（確認）").props("type=password clearable").classes("w-full")

        async def _change() -> None:
            if not ctx.api_config.verify_vault_password(old_pw.value):
                ui.notify("現在のパスワードが正しくありません", type="negative")
                return
            if not new_pw1.value:
                ui.notify("新しいパスワードを入力してください", type="negative")
                return
            if new_pw1.value != new_pw2.value:
                ui.notify("パスワードが一致しません", type="negative")
                return
            carry_keys = ctx.api_config._store.vault.load_keys(old_pw.value)
            ctx.api_config.setup_vault(new_pw1.value, carry_keys)
            set_vault_password(new_pw1.value)
            ui.notify("パスワードを変更しました", type="positive")
            dlg.close()
            await refresh_fn()

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("変更", on_click=_change).props("color=primary unelevated")
    dlg.open()


def confirm_teardown(ctx, refresh_fn) -> None:
    with ui.dialog() as dlg, ui.card():
        ui.label("ボルトをリセットしますか？").classes("text-base font-semibold mb-2")
        ui.label("保存されているすべてのAPIキーが削除されます。この操作は取り消せません。").classes(
            "text-sm text-negative"
        )
        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")

            async def _do() -> None:
                ctx.api_config.teardown_vault()
                clear_vault_password()
                ui.notify("ボルトをリセットしました", type="warning")
                dlg.close()
                await refresh_fn()

            ui.button("リセット", on_click=_do).props("color=negative unelevated")
    dlg.open()
