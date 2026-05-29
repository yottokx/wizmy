"""
NiceGUI アプリシェル。

レスポンシブレイアウトとナビゲーションドロワーを提供する。
デスクトップ: 常時表示の左ドロワー
スマホ (Tailscale経由): オーバーレイドロワー + ハンバーガーメニュー
"""

from __future__ import annotations

import json
from contextlib import contextmanager

from nicegui import app, ui

from ..app_context import get_context
from ..config import PROJECT_ROOT

NAV_ITEMS = [
    {"label": "キャラクター生成", "icon": "auto_awesome", "path": "/"},
    {"label": "キャラクター一覧", "icon": "people", "path": "/characters"},
    {"label": "設定", "icon": "settings", "path": "/settings"},
]

DEFAULT_THEME = "sage-garden"
_LOGO_PATH = PROJECT_ROOT / "assets" / "wizmy.svg"
_WIZMY_LOGO_SVG_CACHE: str | None = None


def _wizmy_logo_svg() -> str:
    """Return the themeable Wizmy SVG as inline markup."""
    global _WIZMY_LOGO_SVG_CACHE
    if _WIZMY_LOGO_SVG_CACHE is None:
        try:
            svg = _LOGO_PATH.read_text(encoding="utf-8")
            _WIZMY_LOGO_SVG_CACHE = svg.replace("<svg ", '<svg class="cs-logo-svg" ', 1)
        except OSError:
            _WIZMY_LOGO_SVG_CACHE = '<span class="cs-brand-fallback">Wizmy</span>'
    return _WIZMY_LOGO_SVG_CACHE

# テーマ定義
# cs-* : アプリ独自の CSS 変数 / q-* : Quasar のカラー変数
THEMES: dict[str, dict] = {
    "sage-garden": {
        "label": "Sage Garden",
        "desc": "落ち着いた標準テーマ",
        "dark": False,
        "icon": "🌿",
        "cs-bg":           "#f6f4ec",
        "cs-surface":      "#fffdf7",
        "cs-surface-soft": "#f0eee3",
        "cs-border":       "#d8d2c3",
        "cs-text":         "#2f332c",
        "cs-muted":        "#6f7468",
        "cs-accent":       "#5f7f5f",
        "cs-accent-bg":    "#dfe9dc",
        "cs-accent-border":"#b0ccb0",
        "q-primary":       "#5f7f5f",
        "q-secondary":     "#8b7aa8",
        "q-positive":      "#4f8a5b",
        "q-negative":      "#b86e65",
        "q-warning":       "#b9944e",
        "q-info":          "#6f8fa8",
    },
    "lavender-mist": {
        "label": "Lavender Mist",
        "desc": "柔らかく幻想的なテーマ",
        "dark": False,
        "icon": "🪻",
        "cs-bg":           "#f8f6fb",
        "cs-surface":      "#fffefe",
        "cs-surface-soft": "#f1eef7",
        "cs-border":       "#d8d2e6",
        "cs-text":         "#303044",
        "cs-muted":        "#72708a",
        "cs-accent":       "#8b79b7",
        "cs-accent-bg":    "#e9e4f5",
        "cs-accent-border":"#c8b8d8",
        "q-primary":       "#8b79b7",
        "q-secondary":     "#6f8fa8",
        "q-positive":      "#6e9276",
        "q-negative":      "#b98d91",
        "q-warning":       "#b98d4e",
        "q-info":          "#6f8fa8",
    },
    "night-library": {
        "label": "Night Library",
        "desc": "長時間作業向きのダークテーマ",
        "dark": True,
        "icon": "🌙",
        "cs-bg":           "#071017",
        "cs-surface":      "#101b23",
        "cs-surface-soft": "#16232d",
        "cs-border":       "#263743",
        "cs-text":         "#d8dedb",
        "cs-muted":        "#9aa8a6",
        "cs-accent":       "#5ea6a2",
        "cs-accent-bg":    "#183b3d",
        "cs-accent-border":"#2a5a5c",
        "q-primary":       "#5ea6a2",
        "q-secondary":     "#87a68a",
        "q-positive":      "#67b27c",
        "q-negative":      "#c47070",
        "q-warning":       "#c7a66b",
        "q-info":          "#5ea6a2",
    },
    "sand-terracotta": {
        "label": "Sand & Terracotta",
        "desc": "温かく個性的なテーマ",
        "dark": False,
        "icon": "🏺",
        "cs-bg":           "#f5efe3",
        "cs-surface":      "#fff8ec",
        "cs-surface-soft": "#efe4d3",
        "cs-border":       "#d9c6ae",
        "cs-text":         "#352b24",
        "cs-muted":        "#77695e",
        "cs-accent":       "#a9543f",
        "cs-accent-bg":    "#f0d8cf",
        "cs-accent-border":"#d0a898",
        "q-primary":       "#a9543f",
        "q-secondary":     "#66784d",
        "q-positive":      "#6d814d",
        "q-negative":      "#b86e65",
        "q-warning":       "#b98742",
        "q-info":          "#66784d",
    },
}

_GLOBAL_CSS = """
<style>
/* ─── デフォルトテーマ (Sage Garden) ─── */
:root {
  --cs-bg:           #f6f4ec;
  --cs-surface:      #fffdf7;
  --cs-surface-soft: #f0eee3;
  --cs-border:       #d8d2c3;
  --cs-text:         #2f332c;
  --cs-muted:        #6f7468;
  --cs-accent:       #5f7f5f;
  --cs-accent-bg:    #dfe9dc;
  --cs-accent-border:#b0ccb0;
  --cs-negative:     #b86e65;
}
:root[data-theme="lavender-mist"] {
  --cs-bg:           #f8f6fb;
  --cs-surface:      #fffefe;
  --cs-surface-soft: #f1eef7;
  --cs-border:       #d8d2e6;
  --cs-text:         #303044;
  --cs-muted:        #72708a;
  --cs-accent:       #8b79b7;
  --cs-accent-bg:    #e9e4f5;
  --cs-accent-border:#c8b8d8;
  --cs-negative:     #b98d91;
}
:root[data-theme="night-library"] {
  --cs-bg:           #071017;
  --cs-surface:      #101b23;
  --cs-surface-soft: #16232d;
  --cs-border:       #263743;
  --cs-text:         #d8dedb;
  --cs-muted:        #9aa8a6;
  --cs-accent:       #5ea6a2;
  --cs-accent-bg:    #183b3d;
  --cs-accent-border:#2a5a5c;
  --cs-negative:     #c47070;
}
:root[data-theme="sand-terracotta"] {
  --cs-bg:           #f5efe3;
  --cs-surface:      #fff8ec;
  --cs-surface-soft: #efe4d3;
  --cs-border:       #d9c6ae;
  --cs-text:         #352b24;
  --cs-muted:        #77695e;
  --cs-accent:       #a9543f;
  --cs-accent-bg:    #f0d8cf;
  --cs-accent-border:#d0a898;
  --cs-negative:     #b86e65;
}

/* ─── ページ背景 ─── */
body, html, .q-layout, .q-page, .q-page-container,
.q-layout__section--marginal, .q-layout__shadow {
  background-color: var(--cs-bg) !important;
  color: var(--cs-text) !important;
}
.q-expansion-item__container, .q-tab-panels, .q-tab-panel {
  background-color: transparent !important;
}

/* ─── ヘッダー ─── */
.q-header {
  background-color: var(--cs-surface) !important;
  border-bottom: 1px solid var(--cs-border) !important;
  box-shadow: 0 1px 4px rgba(0,0,0,0.07) !important;
  display: flex !important;
  align-items: center !important;
  box-sizing: border-box !important;
  padding-top: 0 !important;
  padding-bottom: 0 !important;
  height: 56px !important;
  min-height: 56px !important;
  overflow: hidden !important;
}
.q-badge.cs-generation-indicator {
  background-color: var(--cs-accent) !important;
  color: #fff !important;
  border: 1px solid var(--cs-accent) !important;
  font-weight: 700 !important;
}
.cs-brand-logo {
  --wizmy-bg: var(--cs-surface);
  --wizmy-primary: var(--cs-accent);
  --wizmy-accent: #fff;
  display: flex;
  align-items: center;
  flex: 0 0 auto;
  height: 56px;
  width: auto;
  min-width: 0;
}
.cs-brand-logo .cs-logo-svg {
  display: block;
  width: auto;
  height: clamp(36px, 5vw, 42px);
}
.cs-brand-logo .cs-brand-fallback {
  color: var(--cs-accent);
  font-size: 1rem;
  font-weight: 800;
  letter-spacing: 0.02em;
}

/* ─── カード ─── */
.q-card {
  background-color: var(--cs-surface) !important;
  border: 1px solid var(--cs-border) !important;
  border-radius: 12px !important;
  box-shadow: 0 2px 8px rgba(0,0,0,0.06) !important;
  transition: box-shadow 0.2s ease !important;
  color: var(--cs-text) !important;
}
.q-card.cursor-pointer:hover {
  box-shadow: 0 4px 16px rgba(0,0,0,0.12) !important;
}

/* ─── ドロワー ─── */
.q-drawer {
  background-color: var(--cs-surface) !important;
  border-right: 1px solid var(--cs-border) !important;
}

/* ─── タブ ─── */
.q-tab--active .q-tab__label,
.q-tab--active .q-icon { color: var(--cs-accent) !important; }
.q-tab__indicator       { background: var(--cs-accent) !important; }
.q-tab__label           { color: var(--cs-muted) !important; }
.q-tab__label:hover     { color: var(--cs-text) !important; }

/* ─── 入力フィールド ─── */
.q-field__control {
  background-color: var(--cs-surface) !important;
  color: var(--cs-text) !important;
}
.q-field--outlined .q-field__control {
  border-color: var(--cs-border) !important;
  border-radius: 8px !important;
  background-color: var(--cs-surface) !important;
}
.q-field--standout .q-field__control,
.q-field--filled .q-field__control {
  background-color: var(--cs-surface-soft) !important;
}
.q-field--borderless .q-field__control {
  background-color: transparent !important;
}
.q-field--outlined .q-field__control:hover {
  border-color: var(--cs-accent) !important;
}
.q-field--outlined.q-field--focused .q-field__control {
  border-color: var(--cs-accent) !important;
}
.q-field__label { color: var(--cs-muted) !important; }
.q-field__native, .q-field__input { color: var(--cs-text) !important; background-color: transparent !important; }
.q-field__marginal { color: var(--cs-muted) !important; }
.q-field__bottom { color: var(--cs-muted) !important; }
.q-item { color: var(--cs-text) !important; }
.q-menu { background-color: var(--cs-surface) !important; border: 1px solid var(--cs-border) !important; }

/* ─── Prose / Markdown ─── */
.prose { color: var(--cs-text) !important; line-height: 1.75; }
.prose h1, .prose h2, .prose h3 { color: var(--cs-text) !important; font-weight: 600 !important; }
.prose h2 {
  font-size: 0.78rem !important;
  text-transform: uppercase !important;
  letter-spacing: 0.08em !important;
  color: var(--cs-accent) !important;
  margin-top: 1.25em !important;
  margin-bottom: 0.5em !important;
  padding-bottom: 0.3em !important;
  border-bottom: 1px solid var(--cs-accent-bg) !important;
}
.prose table  { border-collapse: collapse !important; width: 100% !important; font-size: 0.875rem !important; }
.prose th     { background: var(--cs-bg) !important; color: var(--cs-muted) !important; font-weight: 600 !important; padding: 6px 10px !important; border: 1px solid var(--cs-border) !important; text-align: left !important; }
.prose td     { padding: 6px 10px !important; border: 1px solid var(--cs-border) !important; color: var(--cs-text) !important; }
.prose li, .prose strong, .prose p { color: var(--cs-text) !important; }
.prose p      { margin-bottom: 0.5em !important; }

/* ─── キャラクターシート ─── */
.cs-sheet-section-title {
  font-size: 0.68rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.1em; color: var(--cs-accent);
  margin-bottom: 8px; padding-bottom: 4px;
  border-bottom: 1px solid var(--cs-accent-bg); display: block;
}
.cs-sheet-field-label {
  font-size: 0.72rem; color: var(--cs-muted); font-weight: 600;
  margin-top: 8px; margin-bottom: 2px; display: block;
}
.cs-placeholder-dash { color: var(--cs-border); }

/* ─── メディアアップロード ─── */
.cs-media-upload.q-uploader {
  background: var(--cs-surface-soft) !important;
  border-color: var(--cs-border) !important;
  border-radius: 8px !important;
  color: var(--cs-text) !important;
}
.cs-media-upload .q-uploader__header {
  background: var(--cs-accent) !important;
  color: #fff !important;
}
.cs-media-upload .q-uploader__subtitle,
.cs-media-upload .q-uploader__file {
  color: var(--cs-text) !important;
}
.cs-media-upload .q-uploader__list {
  min-height: 132px !important;
  background: var(--cs-surface-soft) !important;
  color: var(--cs-muted) !important;
}

/* ─── 進捗フェーズステップ ─── */
.cs-phase-step {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 4px 12px; border-radius: 20px; font-size: 0.76rem; font-weight: 500;
  background: var(--cs-surface-soft); color: var(--cs-muted);
  border: 1px solid var(--cs-border);
  transition: all 0.3s ease; white-space: nowrap; user-select: none;
}
.cs-phase-step.cs-phase-active {
  background: var(--cs-accent-bg); color: var(--cs-accent);
  border-color: var(--cs-accent-border); font-weight: 600;
}
.cs-phase-step.cs-phase-done {
  background: var(--cs-accent); color: #fff; border-color: var(--cs-accent);
}

/* ─── ログエリア ─── */
.cs-log-area {
  background: var(--cs-surface-soft); border: 1px solid var(--cs-border); border-radius: 8px;
}
.cs-log-entry {
  padding: 3px 10px; border-bottom: 1px solid var(--cs-border);
  font-size: 0.75rem; line-height: 1.55;
  font-family: ui-monospace, 'Cascadia Code', monospace;
  color: var(--cs-text);
}

/* ─── スクロールバー ─── */
.q-scrollarea__content::-webkit-scrollbar { width: 5px; }
.q-scrollarea__content::-webkit-scrollbar-track { background: transparent; }
.q-scrollarea__content::-webkit-scrollbar-thumb { background: var(--cs-border); border-radius: 3px; }

/* ─── Quasar ユーティリティカラークラスのテーマ対応 ─── */
/* bg-grey-* をテーマの surface 色にマップ */
.bg-grey-1  { background-color: var(--cs-surface-soft) !important; }
.bg-grey-2  { background-color: var(--cs-surface-soft) !important; }
.bg-grey-3  { background-color: var(--cs-border)       !important; }
.bg-grey-4  { background-color: var(--cs-border)       !important; }
/* text-grey-* をテーマの text/muted 色にマップ */
.text-grey-4 { color: var(--cs-border) !important; }
.text-grey-5 { color: var(--cs-muted)  !important; }
.text-grey-6 { color: var(--cs-muted)  !important; }
.text-grey-7 { color: var(--cs-muted)  !important; }
.text-grey-8 { color: var(--cs-text)   !important; }
/* Quasar リスト / アイテム */
.q-list { background-color: transparent !important; }
.q-item { color: var(--cs-text) !important; }
.q-item:hover { background-color: var(--cs-surface-soft) !important; }
.q-item__label { color: var(--cs-text) !important; }
.q-item__label--caption { color: var(--cs-muted) !important; }
.q-item-section { color: var(--cs-text) !important; }
/* Quasar expansion (アコーディオン) */
.q-expansion-item__container > .q-item {
  background-color: var(--cs-surface) !important;
  color: var(--cs-text) !important;
}
/* Quasar セレクト / ドロップダウン */
.q-menu       { background-color: var(--cs-surface) !important; border: 1px solid var(--cs-border) !important; }
.q-menu .q-item { background-color: var(--cs-surface) !important; }
.q-menu .q-item:hover { background-color: var(--cs-surface-soft) !important; }
/* Quasar ダイアログ */
.q-dialog__backdrop { background: rgba(0,0,0,0.5) !important; }
.q-dialog .q-card   { background-color: var(--cs-surface) !important; color: var(--cs-text) !important; }
/* Quasar チップ / バッジ */
.q-chip { background-color: var(--cs-surface-soft) !important; color: var(--cs-text) !important; }
/* Quasar セパレーター */
.q-separator { background-color: var(--cs-border) !important; }
/* Quasar チェックボックス / トグル ラベル */
.q-checkbox__label, .q-toggle__label { color: var(--cs-text) !important; }
/* Quasar コード表示 */
.q-code { background-color: var(--cs-surface-soft) !important; color: var(--cs-text) !important; }
/* Quasar テーブル */
.q-table { color: var(--cs-text) !important; }
.q-table th { background-color: var(--cs-surface-soft) !important; color: var(--cs-muted) !important; border-color: var(--cs-border) !important; }
.q-table td { border-color: var(--cs-border) !important; color: var(--cs-text) !important; }
.q-table--horizontal-separator tbody tr:not(:last-child) td { border-color: var(--cs-border) !important; }
/* Quasar カード内セクション */
.q-card__section { color: var(--cs-text) !important; }
/* インライン label / span テキスト */
label { color: var(--cs-text); }

/* ─── テーマ選択カード ─── */
.cs-theme-card {
  border: 2px solid var(--cs-border); border-radius: 12px;
  padding: 14px; cursor: pointer; transition: all 0.2s ease;
  background: var(--cs-surface);
}
.cs-theme-card:hover { border-color: var(--cs-accent); }
.cs-theme-card.cs-theme-selected { border-color: var(--cs-accent); box-shadow: 0 0 0 3px var(--cs-accent-bg); }
.cs-theme-swatch {
  display: flex; gap: 3px; margin-bottom: 10px; border-radius: 6px; overflow: hidden; height: 24px;
}
.cs-theme-swatch-color { flex: 1; }
</style>
"""


def apply_theme_js(theme_id: str) -> str:
    """指定テーマを即座に適用する JavaScript を返す。"""
    t = THEMES.get(theme_id, THEMES[DEFAULT_THEME])
    colors_json = json.dumps({
        "primary":   t["q-primary"],
        "secondary": t["q-secondary"],
        "positive":  t["q-positive"],
        "negative":  t["q-negative"],
        "warning":   t["q-warning"],
        "info":      t["q-info"],
    })
    dark = "true" if t["dark"] else "false"
    return f"""
(function(){{
  var r = document.documentElement;
  r.setAttribute('data-theme', {json.dumps(theme_id)});
  var c = {colors_json};
  for (var k in c) r.style.setProperty('--q-' + k, c[k]);
  try {{ Quasar.Dark.set({dark}); }} catch(e) {{}}
}})();
"""


@contextmanager
def page_layout(title: str = ""):
    """
    ページ全体のレイアウトを構築するコンテキストマネージャー。

    Usage:
        with page_layout("ページタイトル"):
            # ページのコンテンツ
            ui.label("Hello")
    """
    ui.add_head_html(_GLOBAL_CSS)

    # ユーザーの保存済みテーマを読み取って適用
    try:
        theme_id = app.storage.user.get("theme", DEFAULT_THEME)
    except Exception:
        theme_id = DEFAULT_THEME
    t = THEMES.get(theme_id, THEMES[DEFAULT_THEME])

    # Quasar のカラーシステムをテーマ値で上書き
    ui.colors(
        primary=t["q-primary"],
        secondary=t["q-secondary"],
        positive=t["q-positive"],
        negative=t["q-negative"],
        warning=t["q-warning"],
        info=t["q-info"],
    )
    # data-theme 属性をページロード時に設定
    ui.add_body_html(f"<script>{apply_theme_js(theme_id)}</script>")

    drawer = (
        ui.right_drawer(value=False, top_corner=True, bottom_corner=True)
        .props("bordered overlay")
        .style("width: 230px; background: var(--cs-surface);")
    )

    with ui.header(elevated=False, wrap=False).classes("flex items-center gap-3 px-5").style(
        "background: var(--cs-surface); border-bottom: 1px solid var(--cs-border); "
        "box-shadow: 0 1px 4px rgba(0,0,0,0.07); height: 56px; min-height: 56px; "
        "display: flex; align-items: center; overflow: hidden; padding-top: 0; padding-bottom: 0;"
    ):
        ui.html(_wizmy_logo_svg(), sanitize=False).classes("cs-brand-logo")
        if title:
            ui.label(title).classes("text-sm hidden sm:block ml-1").style("color: var(--cs-muted);")
        generation_indicator = ui.badge("生成中", color=None).classes(
            "hidden ml-2 text-xs cs-generation-indicator"
        )
        ui.space()
        ui.button(icon="menu", on_click=lambda: drawer.toggle()).props(
            "flat round dense"
        ).style("color: var(--cs-muted); align-self: center;")

    with drawer:
        with ui.row().classes("items-center justify-between px-4 py-3 w-full").style(
            "border-bottom: 1px solid var(--cs-border);"
        ):
            ui.label("メニュー").classes("text-sm font-semibold").style("color: var(--cs-muted);")
            ui.button(
                icon="close", on_click=lambda: drawer.hide()
            ).props("flat round dense").style("color: var(--cs-muted);")
        try:
            current_path = ui.context.client.page.path
        except Exception:
            current_path = "/"

        with ui.list().props("dense separator").classes("w-full"):
            for item in NAV_ITEMS:
                is_active = current_path == item["path"]
                item_style = (
                    "background-color: var(--cs-accent-bg); border-left: 3px solid var(--cs-accent);"
                    if is_active else "border-left: 3px solid transparent;"
                )
                with ui.item(on_click=lambda p=item["path"]: ui.navigate.to(p)).classes(
                    "cursor-pointer"
                ).style(item_style):
                    with ui.item_section().props("avatar"):
                        ui.icon(item["icon"]).style(
                            "color: var(--cs-accent);" if is_active else "color: var(--cs-muted);"
                        )
                    with ui.item_section():
                        ui.label(item["label"]).classes(
                            "text-sm font-semibold" if is_active else "text-sm"
                        ).style("color: var(--cs-text);" if is_active else "color: var(--cs-muted);")

    with ui.column().classes("w-full px-4 py-4"):
        def _sync_generation_indicator() -> None:
            try:
                running = get_context().generation.has_active_jobs()
                if running:
                    generation_indicator.classes(remove="hidden")
                else:
                    generation_indicator.classes("hidden")
            except Exception:
                pass

        _sync_generation_indicator()
        ui.timer(1.0, _sync_generation_indicator)
        yield
