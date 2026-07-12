"""
P3「With」ページの共通スキャフォールド。

`p3_page()` コンテキストマネージャが以下を提供する:
- 共通CSS(テーマトークン+基本コンポーネント)の注入
- テーマ起動JS(`ui2_theme` の永続値を反映)とテーマ切替ボタン
- ナビゲーション(機能名ラベル+テーマ再着色ロゴ)
- AIジョブバッジ+ジョブドロワー
- sparkle スクリプトの注入
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from nicegui import ui

from ..app_context import get_context
from .components.sparkle import SPARKLE_CSS, install_sparkle_script
from .state import is_vault_unlocked, set_vault_password
from .theme import (
    DEFAULT_THEME,
    THEMES,
    TOKENS_CSS,
    apply_theme_js,
    get_theme,
    set_theme,
    wizmy_logo_svg,
)

# ラベルは機能名(比喩ラベル禁止)。route が None の項目は未実装(後続Phase)。
NAV_ITEMS: list[dict] = [
    {"label": "ホーム", "route": "/"},
    {"label": "キャラクター", "route": "/characters"},
    {"label": "チャット", "route": "/chat"},
    {"label": "グループ", "route": "/groups"},
    {"label": "生成", "route": "/generation"},
    {"label": "設定", "route": "/settings"},
]

# p3.css の共通部(reset / nav / btn / bubble / 小物)+ NiceGUI 共存パッチ
BASE_CSS = """
/* ---------- reset-lite ---------- */
*, *::before, *::after { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
img { display: block; max-width: 100%; }
button, input, select, textarea { font: inherit; color: inherit; }
a { color: inherit; text-decoration: none; }

body {
  background: var(--bg) !important;
  color: var(--text);
  font-family: "Segoe UI", "Yu Gothic UI", "Hiragino Kaku Gothic ProN", "Meiryo", sans-serif;
  font-size: 15px;
  line-height: 1.75;
  letter-spacing: 0.02em;
  -webkit-font-smoothing: antialiased;
}

::selection { background: var(--accent); color: var(--accent-ink); }

/* NiceGUI 既定レイアウトの除去(.nicegui-content は flex column で子が内容幅に縮む) */
.nicegui-content { padding: 0; display: block; }
.q-page { background: var(--bg); }

/* 名前・見出し用。飾りすぎない明朝 */
.serif {
  font-family: "Yu Mincho", "Hiragino Mincho ProN", "MS PMincho", serif;
  font-weight: 600;
  letter-spacing: 0.06em;
}

/* ---------- nav ---------- */
.wz-nav {
  position: sticky;
  top: 0;
  z-index: 50;
  /* chat/group は .nicegui-content を flex column に戻すため、
     NiceGUI 既定の align-items: flex-start で内容幅に縮まないよう明示する */
  width: 100%;
  display: flex;
  align-items: center;
  gap: 28px;
  padding: 10px 26px;
  background: color-mix(in srgb, var(--bg) 86%, transparent);
  backdrop-filter: blur(14px);
  border-bottom: 1px solid var(--line);
}
.wz-logo { display: block; height: 34px; flex: none; cursor: pointer; }
.wz-logo svg { height: 100%; width: auto; display: block; }
/* wizmy.svg の再着色: 緑背景を透過し、主/抜き色をテーマ変数に委ねる */
.wz-logo {
  --wizmy-bg: transparent;
  --wizmy-primary: var(--logo-p);
  --wizmy-accent: var(--logo-a);
}
.wz-logo-fallback { color: var(--logo-p); font-weight: 800; font-size: 18px; }
.wz-nav .links { display: flex; gap: 22px; align-items: center; }
.wz-nav .links a {
  padding: 6px 2px;
  border-bottom: 1px solid transparent;
  font-size: 13.5px;
  letter-spacing: .06em;
  color: var(--muted);
  transition: color .18s, border-color .18s;
  cursor: pointer;
}
.wz-nav .links a:hover { color: var(--text); }
.wz-nav .links a.on { color: var(--text); border-bottom-color: var(--accent); }
.wz-nav .links a.todo { opacity: .4; cursor: default; }
.wz-nav .links a.todo:hover { color: var(--muted); }
.wz-nav .grow { flex: 1; }
.theme-btn {
  border: 1px solid var(--line-2);
  background: transparent;
  color: var(--muted);
  border-radius: 4px;
  padding: 5px 14px;
  font-size: 12.5px;
  cursor: pointer;
  transition: color .18s, border-color .18s;
}
.theme-btn:hover { color: var(--text); border-color: var(--muted); }

/* ---------- buttons ---------- */
.btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--line-2);
  background: transparent;
  color: var(--text);
  border-radius: 4px;
  padding: 9px 22px;
  font-size: 14px;
  cursor: pointer;
  transition: transform .15s, background .18s, border-color .18s, box-shadow .18s;
}
.btn:hover { background: var(--panel-2); border-color: var(--muted); transform: translateY(-1px); }
.btn.primary {
  background: var(--accent);
  border-color: var(--accent);
  color: var(--accent-ink);
  font-weight: 600;
  box-shadow: 0 6px 24px var(--glow);
}
.btn.primary:hover { filter: brightness(1.06); }
.btn.quiet { border-color: transparent; color: var(--muted); padding: 6px 12px; font-size: 13px; }
.btn.quiet:hover { color: var(--text); background: var(--panel-2); }

/* ---------- speech bubble ---------- */
.bubble {
  position: relative;
  background: var(--bubble);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 14px 20px;
  box-shadow: var(--shadow);
}
.bubble.tail-left::before {
  content: "";
  position: absolute;
  left: -9px;
  top: 26px;
  width: 16px;
  height: 16px;
  background: inherit;
  border-left: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  transform: rotate(45deg);
  border-radius: 0 0 0 4px;
}
.bubble.tail-bottom::before {
  content: "";
  position: absolute;
  bottom: -9px;
  left: 42px;
  width: 16px;
  height: 16px;
  background: inherit;
  border-right: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  transform: rotate(45deg);
  border-radius: 0 0 4px 0;
}

/* ---------- 小物 ---------- */
.kicker {
  font-size: 12px;
  letter-spacing: 0.34em;
  text-transform: uppercase;
  color: var(--peri);
  margin-bottom: 10px;
}
.chip {
  display: inline-flex;
  align-items: center;
  padding: 3px 12px;
  border-radius: 4px;
  border: 1px solid var(--line-2);
  color: var(--muted);
  font-size: 12px;
  letter-spacing: 0.04em;
  background: transparent;
  cursor: pointer;
  transition: color .15s, border-color .15s, background .15s;
}
.chip:hover, .chip.on { color: var(--text); border-color: var(--accent); }
.chip.on { background: color-mix(in srgb, var(--accent) 16%, transparent); }

.avatar {
  border-radius: 50%;
  object-fit: cover;
  border: 2px solid var(--line-2);
  background: var(--panel-2);
}

.note {
  font-size: 12px;
  color: var(--muted);
  letter-spacing: 0.03em;
}

/* ---------- AIジョブバッジ+ドロワー ---------- */
.wz-ai-badge {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  border: 1px solid var(--accent);
  background: color-mix(in srgb, var(--accent) 14%, transparent);
  color: var(--accent);
  border-radius: 4px;
  padding: 4px 13px;
  font-size: 12px;
  letter-spacing: 0.06em;
  cursor: pointer;
  transition: background .18s;
}
.wz-ai-badge:hover { background: color-mix(in srgb, var(--accent) 24%, transparent); }
.wz-ai-badge .dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--accent);
  animation: wz-pulse 1.4s ease-in-out infinite;
}
@keyframes wz-pulse {
  0%, 100% { opacity: .35; transform: scale(.8); }
  50%      { opacity: 1; transform: scale(1); }
}
.wz-ai-badge.hidden { display: none; }

/* ボルト未解錠バッジ(横画面のみ。縦画面はメニュー内に表示) */
.wz-vault-badge {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  border: 1px solid var(--peri);
  background: color-mix(in srgb, var(--peri) 14%, transparent);
  color: var(--peri);
  border-radius: 4px;
  padding: 4px 13px;
  font-size: 12px;
  letter-spacing: 0.06em;
  cursor: pointer;
  transition: background .18s;
  white-space: nowrap;
}
.wz-vault-badge:hover { background: color-mix(in srgb, var(--peri) 24%, transparent); }
.wz-vault-badge.hidden { display: none; }
@media (orientation: portrait) {
  .wz-vault-badge { display: none; }
}

.q-drawer { background: var(--panel) !important; color: var(--text) !important; }
.wz-jobs-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 18px;
  border-bottom: 1px solid var(--line);
}
.wz-jobs-head .title { font-size: 13px; letter-spacing: .22em; color: var(--muted); }
.wz-jobs-body { display: flex; flex-direction: column; gap: 10px; padding: 14px; }
.wz-job {
  background: var(--panel-2);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 12px 14px;
}
.wz-job .head { display: flex; align-items: center; gap: 10px; }
.wz-job .name { font-size: 13.5px; font-weight: 600; flex: 1; min-width: 0; }
.wz-job .kind { font-size: 11.5px; color: var(--muted); margin-top: 2px; }
.wz-job .msg { font-size: 12px; color: var(--muted); margin-top: 4px; }
.wz-job .err { font-size: 12px; color: #e08a8a; margin-top: 4px; }
.wz-job .ops { display: flex; gap: 8px; margin-top: 8px; }
.wz-st {
  flex: none;
  font-size: 11px;
  letter-spacing: .05em;
  padding: 2px 10px;
  border-radius: 4px;
  border: 1px solid var(--line-2);
  color: var(--muted);
}
.wz-st.running { color: var(--accent); border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 12%, transparent); }
.wz-st.queued { color: var(--peri); border-color: var(--peri); }
.wz-st.succeeded { color: #8fd0a0; border-color: #8fd0a0; }
.wz-st.failed { color: #e08a8a; border-color: #e08a8a; }

/* ---------- 縦画面ナビ: メニューボタン+ドロップダウン ---------- */
.wz-menu-btn { display: none; }
/* 横幅に収まらない時(改行が起きる状況)は JS が compact を付与し、
   縦画面と同じメニューボタン表示に切り替える */
.wz-nav { flex-wrap: nowrap; }
.wz-nav .links a, .theme-btn { white-space: nowrap; }
.wz-nav.wz-nav-compact .links { display: none; }
.wz-nav.wz-nav-compact .wz-menu-btn { display: inline-flex; align-items: center; }
.wz-nav-menu {
  background: var(--panel) !important;
  color: var(--text) !important;
  border: 1px solid var(--line);
  border-radius: 6px;
  min-width: 190px;
}
.wz-nav-menu .q-item { font-size: 14px; color: var(--muted); letter-spacing: .04em; }
.wz-nav-menu .q-item:hover { color: var(--text); }
.wz-nav-menu .q-item.on { color: var(--text); background: var(--panel-2); }

/* 縦画面ではメニューを常時表示せず、右上のボタンでドロップダウンを開く */
@media (orientation: portrait) {
  .wz-nav .links { display: none; }
  .wz-menu-btn { display: inline-flex; align-items: center; }
}

/* ナビの縦画面対応 */
@media (max-width: 700px) {
  .wz-nav { gap: 10px; padding: 5px 12px; }
  .wz-logo { height: 24px; }
  .wz-nav .links a { padding: 5px 2px; font-size: 12.5px; }
  .theme-btn { white-space: nowrap; padding: 4px 11px; font-size: 11.5px; }
}

/* スマホ: 16px未満の入力はフォーカス時にブラウザが自動ズームするため底上げする */
@media (max-width: 860px) {
  input, textarea, select,
  .q-field__native, .q-field__input { font-size: 16px; }
}

/* スクロールバー(WebKit) */
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-thumb { background: var(--line-2); border-radius: 6px; }
::-webkit-scrollbar-track { background: transparent; }
"""

_JOB_STATUS_TEXT = {
    "queued": "待機中",
    "running": "実行中",
    "succeeded": "完了",
    "failed": "失敗",
    "cancelled": "停止済み",
}


@dataclass
class P3Scaffold:
    """ページ側からスキャフォールドを操作するためのハンドル。"""

    jobs_drawer: ui.right_drawer
    open_jobs: object  # Callable[[], None]


def _quiet_button(text: str, on_click) -> ui.element:
    btn = ui.element("button").classes("btn quiet")
    with btn:
        ui.html(text)
    btn.on("click", on_click)
    return btn


@contextmanager
def p3_page(active: str = "") -> Iterator[P3Scaffold]:
    """P3共通ページを構築する。

    Usage:
        with p3_page("ホーム") as scaffold:
            ...ページ内容...
    """
    theme = get_theme()
    # モック p3.js と同じ ?theme= 上書き(表示のみ・保存はしない。検証用)
    try:
        override = ui.context.client.request.query_params.get("theme", "")
        if override in THEMES:
            theme = override
    except Exception:
        pass

    ui.add_css(TOKENS_CSS + BASE_CSS + SPARKLE_CSS)
    install_sparkle_script()

    t = THEMES.get(theme, THEMES[DEFAULT_THEME])
    ui.colors(primary=t["q-primary"], secondary=t["q-secondary"], negative=t["q-negative"])
    # Quasar の Dark は接続後に確実に適用される ui.dark_mode で切り替える。
    # (body スクリプトの Quasar.Dark.set は初期ロード時に Quasar 未初期化で
    #  空振りすることがあり、ダークテーマでドロップダウン等が黒文字になる)
    dark_mode = ui.dark_mode(t["dark"])
    ui.add_body_html(f"<script>{apply_theme_js(theme)}</script>")
    ui.add_body_html(
        """
<script>
(function () {
  if (window.__wzNavFitInstalled) return;
  window.__wzNavFitInstalled = true;
  function fit() {
    var nav = document.querySelector('.wz-nav');
    if (!nav) return;
    nav.classList.remove('wz-nav-compact');
    if (nav.scrollWidth > nav.clientWidth + 1) nav.classList.add('wz-nav-compact');
  }
  window.addEventListener('resize', fit);
  window.addEventListener('load', fit);
  setInterval(fit, 1000);
  fit();
})();
</script>
"""
    )

    # ---- AIジョブドロワー(P3スキン) ----
    jobs_drawer = (
        ui.right_drawer(value=False, top_corner=True, bottom_corner=True)
        .props("bordered overlay")
        .style("width: min(420px, 92vw); border-left: 1px solid var(--line);")
    )
    jobs_container: ui.element | None = None

    async def _cancel_job(job_id: str) -> None:
        try:
            await get_context().ai_jobs.cancel_job(job_id)
            _refresh_jobs()
        except Exception as exc:
            ui.notify(f"停止に失敗しました: {exc}", type="negative")

    def _refresh_jobs() -> None:
        if jobs_container is None:
            return
        jobs_container.clear()
        try:
            ctx = get_context()
            jobs = ctx.ai_jobs.list_jobs(limit=20)
            character_generation_active = ctx.generation.has_active_jobs()
        except Exception:
            jobs = []
            character_generation_active = False

        with jobs_container:
            if character_generation_active:
                with ui.element("div").classes("wz-job"):
                    with ui.element("div").classes("head"):
                        ui.html("キャラクター生成").classes("name")
                        ui.html("実行中").classes("wz-st running")
                    with ui.element("div").classes("ops"):
                        _quiet_button("生成画面を開く", lambda: ui.navigate.to("/generation"))

            if not jobs and not character_generation_active:
                ui.html("実行中または直近のAIジョブはありません。").classes("note").style(
                    "display:block; padding: 6px 4px;"
                )
                return

            for job in jobs:
                summary = job.summary()
                status = str(summary["status"])
                result_url = str(summary.get("result_url") or "")
                with ui.element("div").classes("wz-job"):
                    with ui.element("div").classes("head"):
                        ui.html(str(summary["label"])).classes("name")
                        ui.html(_JOB_STATUS_TEXT.get(status, status)).classes(f"wz-st {status}")
                    kind = str(summary.get("kind") or "")
                    if kind:
                        ui.html(kind).classes("kind")
                    message = str(summary.get("progress_message") or "")
                    if message:
                        ui.html(message).classes("msg")
                    if summary.get("error_message"):
                        ui.html(str(summary["error_message"])).classes("err")
                    with ui.element("div").classes("ops"):
                        if result_url:
                            _quiet_button("開く", lambda url=result_url: ui.navigate.to(url))
                        if summary.get("can_cancel"):

                            async def _cancel(job_id: str = job.id) -> None:
                                await _cancel_job(job_id)

                            _quiet_button("停止", _cancel)

    def _open_jobs() -> None:
        _refresh_jobs()
        jobs_drawer.show()

    with jobs_drawer:
        with ui.element("div").classes("wz-jobs-head"):
            ui.html("AIジョブ").classes("title")
            _quiet_button("閉じる", lambda: jobs_drawer.hide())
        jobs_container = ui.element("div").classes("wz-jobs-body")

    # ---- ボルト解錠(設定済み・未解錠のときだけナビ/メニューに表示) ----
    def _vault_locked() -> bool:
        try:
            return get_context().api_config.is_vault_setup() and not is_vault_unlocked()
        except Exception:
            return False

    def _open_vault_unlock() -> None:
        with ui.dialog() as dlg, ui.card().classes("w-full max-w-sm").style(
            "background: var(--panel); color: var(--text);"
        ):
            ui.label("APIキーボルトの解錠").classes("text-base font-semibold mb-2")
            pw_input = (
                ui.input(label="ボルトのパスワード")
                .props("type=password outlined dense autofocus")
                .classes("w-full")
                .mark("ui2-vault-unlock-pw")
            )

            def _unlock() -> None:
                password = str(pw_input.value or "")
                if get_context().api_config.verify_vault_password(password):
                    set_vault_password(password)
                    ui.notify("ボルトを解錠しました", type="positive")
                    dlg.close()
                    _sync_vault_badge()
                else:
                    ui.notify("パスワードが違います", type="negative")

            pw_input.on("keydown.enter", _unlock)
            with ui.row().classes("justify-end gap-2 mt-3 w-full"):
                _quiet_button("キャンセル", dlg.close)
                unlock_btn = ui.element("button").classes("btn primary").mark("ui2-vault-unlock")
                with unlock_btn:
                    ui.html("解錠")
                unlock_btn.on("click", _unlock)
        dlg.open()

    # ---- ナビゲーション ----
    def _nav_links() -> None:
        for item in NAV_ITEMS:
            link = ui.element("a")
            with link:
                ui.html(item["label"])
            route = item["route"]
            if route is None:
                link.classes("todo").props('title="実装予定(後続Phase)"')
            else:
                if item["label"] == active:
                    link.classes("on")
                link.on("click", lambda r=route: ui.navigate.to(r))

    with ui.element("nav").classes("wz-nav"):
        logo = ui.html(wizmy_logo_svg(), sanitize=False).classes("wz-logo")
        logo.on("click", lambda: ui.navigate.to("/"))
        with ui.element("div").classes("links"):
            _nav_links()
        ui.element("div").classes("grow")

        vault_badge = ui.element("button").classes("wz-vault-badge hidden").mark("ui2-vault-badge")
        with vault_badge:
            ui.html("🔒 ボルト未解錠")
        vault_badge.on("click", _open_vault_unlock)

        ai_badge = ui.element("button").classes("wz-ai-badge hidden").mark("ui2-ai-jobs-badge")
        with ai_badge:
            ui.element("span").classes("dot")
            ui.html("AI使用中")
        ai_badge.on("click", _open_jobs)

        theme_btn = ui.element("button").classes("theme-btn").mark("ui2-theme-toggle")
        with theme_btn:
            theme_label = ui.html(t["button"])

        def _toggle_theme() -> None:
            new_theme = "hinata" if get_theme() == "hoshi" else "hoshi"
            set_theme(new_theme)
            dark_mode.set_value(THEMES[new_theme]["dark"])
            ui.run_javascript(apply_theme_js(new_theme))
            theme_label.set_content(THEMES[new_theme]["button"])

        theme_btn.on("click", _toggle_theme)

        menu_btn = ui.element("button").classes("theme-btn wz-menu-btn").mark("ui2-nav-menu")
        with menu_btn:
            ui.html("☰")
            with ui.menu().classes("wz-nav-menu"):
                for item in NAV_ITEMS:
                    route = item["route"]
                    if route is None:
                        ui.menu_item(item["label"]).props("disable")
                        continue
                    menu_item = ui.menu_item(
                        item["label"], on_click=lambda r=route: ui.navigate.to(r)
                    )
                    if item["label"] == active:
                        menu_item.classes("on")
                # 縦画面ではボルト解錠導線をメニュー内に出す(未解錠時のみ)
                vault_menu_item = ui.menu_item("🔒 ボルトを解錠", on_click=_open_vault_unlock).mark(
                    "ui2-vault-menu-item"
                )

    # ---- バッジ同期(旧 layout.py と同じ 1秒タイマー) ----
    def _sync_vault_badge() -> None:
        locked = _vault_locked()
        if locked:
            vault_badge.classes(remove="hidden")
        else:
            vault_badge.classes("hidden")
        vault_menu_item.set_visibility(locked)

    def _sync_ai_badge() -> None:
        try:
            ctx = get_context()
            running = ctx.generation.has_active_jobs() or ctx.ai_jobs.has_active_jobs()
            if running:
                ai_badge.classes(remove="hidden")
            else:
                ai_badge.classes("hidden")
            if jobs_drawer.value:
                _refresh_jobs()
            _sync_vault_badge()
        except Exception:
            pass

    _sync_ai_badge()
    ui.timer(1.0, _sync_ai_badge)

    yield P3Scaffold(jobs_drawer=jobs_drawer, open_jobs=_open_jobs)
