"""
/v2/settings — APIキーボルト(設定・解錠・ロック・パスワード変更・リセット)。

旧 `ui/pages/settings/vault.py` の機能を P3 スキンで再実装。
"""

from __future__ import annotations

from nicegui import ui

from ....ui.state import clear_vault_password, is_vault_unlocked, set_vault_password
from .common import DIALOG_CARD_STYLE, confirm_dialog, p3_button, settings_dialog


def open_vault_dialog(ctx, on_change) -> None:
    dlg, body = settings_dialog("APIキーボルト", max_width="620px")
    with body:
        container = ui.column().classes("w-full gap-3")

    def _refresh() -> None:
        container.clear()
        with container:
            if not ctx.api_config.is_vault_setup():
                _render_setup()
            elif not is_vault_unlocked():
                _render_unlock()
            else:
                _render_unlocked()
        on_change()

    def _render_setup() -> None:
        ui.label("APIキーボルトの設定").classes("text-sm font-semibold")
        ui.label(
            "APIキーを暗号化して保存するためのマスターパスワードを設定します。"
            "パスワードを忘れた場合はボルトをリセットする必要があります。"
        ).classes("note")
        pw1 = ui.input(label="マスターパスワード").props("type=password clearable outlined dense").classes(
            "w-full p3-fd"
        ).mark("ui2-settings-vault-pw1")
        pw2 = ui.input(label="パスワードの確認").props("type=password clearable outlined dense").classes(
            "w-full p3-fd"
        ).mark("ui2-settings-vault-pw2")

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
            _refresh()

        with ui.row().classes("w-full"):
            p3_button("ボルトを設定", _setup, classes="btn primary").mark("ui2-settings-vault-setup")

    def _render_unlock() -> None:
        ui.label("ボルトはロックされています").classes("text-sm font-semibold")
        pw_input = ui.input(label="マスターパスワード").props(
            "type=password clearable outlined dense"
        ).classes("w-full p3-fd").mark("ui2-settings-vault-unlock-pw")

        async def _unlock() -> None:
            if ctx.api_config.verify_vault_password(pw_input.value):
                set_vault_password(pw_input.value)
                ui.notify("ボルトのロックを解除しました", type="positive")
                _refresh()
            else:
                ui.notify("パスワードが正しくありません", type="negative")

        pw_input.on("keydown.enter", _unlock)
        with ui.row().classes("w-full"):
            p3_button("ロック解除", _unlock, classes="btn primary").mark("ui2-settings-vault-unlock")

    def _render_unlocked() -> None:
        with ui.row().classes("items-center gap-3 w-full"):
            ui.label("ボルトはロック解除されています").classes("text-sm font-semibold flex-1")
            p3_button("ロック", _lock, classes="btn quiet")
        ui.label("APIキーの設定はLLMエンドポイントの一覧から行えます。").classes("note")
        with ui.row().classes("gap-2 mt-2"):
            p3_button("パスワードを変更", _open_change_password)
            p3_button("ボルトをリセット", _confirm_teardown, classes="btn quiet")

    async def _lock() -> None:
        clear_vault_password()
        ui.notify("ボルトをロックしました", type="info")
        _refresh()

    def _open_change_password() -> None:
        with ui.dialog() as pw_dlg, ui.card().classes("min-w-[360px]").style(DIALOG_CARD_STYLE):
            ui.label("マスターパスワードの変更").classes("text-base font-semibold mb-2")
            old_pw = ui.input(label="現在のパスワード").props("type=password clearable outlined dense").classes(
                "w-full p3-fd"
            )
            new_pw1 = ui.input(label="新しいパスワード").props("type=password clearable outlined dense").classes(
                "w-full p3-fd"
            )
            new_pw2 = ui.input(label="新しいパスワード(確認)").props(
                "type=password clearable outlined dense"
            ).classes("w-full p3-fd")

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
                pw_dlg.close()
                _refresh()

            with ui.row().classes("justify-end gap-2 mt-3 w-full"):
                p3_button("キャンセル", pw_dlg.close, classes="btn quiet")
                p3_button("変更", _change, classes="btn primary")
        pw_dlg.open()

    def _confirm_teardown() -> None:
        async def _do() -> None:
            ctx.api_config.teardown_vault()
            clear_vault_password()
            ui.notify("ボルトをリセットしました", type="warning")
            _refresh()

        confirm_dialog(
            "ボルトをリセットしますか?",
            "保存されているすべてのAPIキーが削除されます。この操作は取り消せません。",
            _do,
            confirm_label="リセット",
        )

    _refresh()
    dlg.open()


def vault_summary(ctx) -> tuple[str, str]:
    if not ctx.api_config.is_vault_setup():
        return "未設定", "muted"
    if is_vault_unlocked():
        return "解錠中", "ok"
    return "ロック中", "peri"
