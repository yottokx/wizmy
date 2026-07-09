"""
/settings — 全般(テーマ / ピックアップの選び方)。

もとはページ内の「動作」「外観」セクションの行内コントロールだったものを、
他の項目と同じ管理ダイアログ(縦画面=モーダル / 横画面=右ペイン)に統合した。
"""

from __future__ import annotations

from nicegui import app, ui

from ...components.pickup import DEFAULT_POLICY, PICKUP_POLICY_KEY, POLICIES
from ...theme import THEMES, get_theme, set_theme
from .common import badge, p3_button, settings_dialog

PICKUP_POLICY_LABELS: dict[str, str] = {
    "mixed": "混成+きまぐれ",
    "favorites": "お気に入り",
    "recent": "最近",
    "daily": "日替わり",
}


def _current_policy() -> str:
    policy = str(app.storage.user.get(PICKUP_POLICY_KEY, DEFAULT_POLICY))
    return policy if policy in POLICIES else DEFAULT_POLICY


def general_summary(ctx) -> tuple[str, str]:
    theme_label = THEMES[get_theme()]["label"]
    policy_label = PICKUP_POLICY_LABELS.get(_current_policy(), _current_policy())
    return f"{theme_label} ・ {policy_label}", "muted"


def open_general_dialog(ctx, on_change) -> None:
    dlg, body = settings_dialog("表示と動作", max_width="620px")
    with body:
        # ---- テーマ ----
        with ui.row().classes("w-full items-center gap-3 flex-wrap"):
            with ui.column().classes("flex-1 gap-0 min-w-0"):
                ui.label("テーマ").classes("text-sm font-semibold")
                ui.label("星あかり(暗)/ ひなた(明)の二相").classes("text-xs").style(
                    "color: var(--muted);"
                )
            badge(THEMES[get_theme()]["label"], tone="accent")

            def _toggle_theme() -> None:
                new_theme = "hinata" if get_theme() == "hoshi" else "hoshi"
                set_theme(new_theme)
                # ナビのボタン表記等も含めて確実に反映するためリロードする
                ui.navigate.reload()

            p3_button("切り替え", _toggle_theme, classes="btn quiet").mark("ui2-settings-theme-toggle")

        # ---- ピックアップの選び方 ----
        with ui.row().classes("w-full items-center gap-3 flex-wrap"):
            with ui.column().classes("flex-1 gap-0 min-w-0"):
                ui.label("ピックアップの選び方").classes("text-sm font-semibold")
                ui.label("キャラクター一覧上段の顔ぶれの選出ポリシー").classes("text-xs").style(
                    "color: var(--muted);"
                )
            policy_select = (
                ui.select(
                    options={key: PICKUP_POLICY_LABELS.get(key, key) for key in POLICIES},
                    value=_current_policy(),
                )
                .props("outlined dense")
                .classes("p3-fd")
                .style("min-width: 200px;")
                .mark("ui2-settings-pickup-policy")
            )

            def _on_policy_change(_) -> None:
                app.storage.user[PICKUP_POLICY_KEY] = str(policy_select.value or DEFAULT_POLICY)
                ui.notify("ピックアップの選び方を保存しました", type="positive", timeout=1200)
                on_change()

            policy_select.on_value_change(_on_policy_change)
    dlg.open()
