from __future__ import annotations

from nicegui import ui

from ...layout import DEFAULT_THEME, THEMES, apply_theme_js


def build_appearance_tab() -> None:
    from nicegui import app as _app

    current_theme = _app.storage.user.get("theme", DEFAULT_THEME)
    selected: dict[str, str] = {"value": current_theme}

    ui.label("テーマ").classes("text-base font-semibold mb-1").style("color: var(--cs-text);")
    ui.label("テーマを変更すると即座に反映されます。設定はブラウザセッションに保存されます。").classes(
        "text-sm mb-4"
    ).style("color: var(--cs-muted);")

    cards: dict[str, ui.element] = {}

    def _apply(theme_id: str) -> None:
        old = selected["value"]
        selected["value"] = theme_id
        _app.storage.user["theme"] = theme_id
        # 旧選択のカードを非選択スタイルに戻す
        if old in cards:
            cards[old].classes(remove="cs-theme-selected")
        # 新選択のカードを選択スタイルに
        if theme_id in cards:
            cards[theme_id].classes("cs-theme-selected")
        # ページにテーマを即座に適用
        ui.run_javascript(apply_theme_js(theme_id))
        # Quasar カラーも更新（次回レンダー時に確実に反映）
        t = THEMES[theme_id]
        ui.colors(
            primary=t["q-primary"],
            secondary=t["q-secondary"],
            positive=t["q-positive"],
            negative=t["q-negative"],
            warning=t["q-warning"],
            info=t["q-info"],
        )

    with ui.element("div").style(
        "display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 14px;"
    ):
        for theme_id, theme in THEMES.items():
            is_selected = theme_id == selected["value"]
            extra_cls = "cs-theme-selected" if is_selected else ""
            card = ui.element("div").classes(f"cs-theme-card {extra_cls}").on("click", lambda tid=theme_id: _apply(tid))
            cards[theme_id] = card
            with card:
                # カラースウォッチ
                with ui.element("div").classes("cs-theme-swatch"):
                    for color_key in ["cs-bg", "cs-surface", "cs-accent", "q-primary"]:
                        ui.element("div").classes("cs-theme-swatch-color").style(
                            f"background-color: {theme[color_key]};"
                        )
                # テーマ名
                with ui.row().classes("items-center gap-2 mb-1"):
                    ui.html(f'<span style="font-size:1.1rem;">{theme["icon"]}</span>')
                    ui.label(theme["label"]).style("font-weight: 700; font-size: 0.9rem; color: var(--cs-text);")
                ui.label(theme["desc"]).style("font-size: 0.75rem; color: var(--cs-muted); margin-bottom: 8px;")
                # ダークテーマバッジ
                if theme["dark"]:
                    ui.badge("ダーク").props("outline").style(
                        "color: var(--cs-muted); border-color: var(--cs-border); font-size: 0.68rem;"
                    )
                # 選択状態テキスト
                if is_selected:
                    ui.html(
                        '<div style="margin-top:8px;font-size:0.72rem;font-weight:600;'
                        'color:var(--cs-accent);">✓ 現在のテーマ</div>'
                    )
