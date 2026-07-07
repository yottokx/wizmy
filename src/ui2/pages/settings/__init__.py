"""
/v2/settings 設定ページ(Phase 6)。モック settings.html の行リスト骨格準拠。

縦画面: 各行の「開く」が管理ダイアログ(Quasar フォーム+P3スキン)を開く。
横画面: 左=設定項目リスト / 右=設定内容の2ペイン(行クリックで右ペインに inline 描画)。
セクション: 接続 / キャラクター生成 / チャット / 全般。
"""

from __future__ import annotations

import html

from nicegui import ui

from ....app_context import get_context
from ...media_ui import MEDIA_CSS
from ...scaffold import p3_page
from .chat import chat_modes_summary, open_chat_modes_dialog, open_user_personas_dialog, personas_summary
from .common import (
    badge,
    install_drag_sort_script,
    pop_inline_settings_host,
    push_inline_settings_host,
)
from .connection import (
    endpoints_summary,
    open_endpoints_dialog,
    open_profiles_dialog,
    profiles_summary,
)
from .general import general_summary, open_general_dialog
from .generation import open_options_dialog, open_presets_dialog, options_summary, presets_summary
from .media_apis import (
    gen_server_summary,
    image_profiles_summary,
    open_gen_server_dialog,
    open_image_profiles_dialog,
    open_tts_endpoints_dialog,
    tts_endpoints_summary,
)
from .narrator import narrator_summary, open_narrator_dialog
from .vault import open_vault_dialog, vault_summary

_PAGE_CSS = """
.set-wrap { max-width: 880px; margin: 0 auto; padding: 44px 26px 40px; }
.set-wrap h1 { font-size: 26px; letter-spacing: .3em; margin: 0 0 8px; font-weight: 600; }
.set-lead { font-size: 13px; color: var(--muted); margin-bottom: 36px; }

.sec { margin-bottom: 44px; }
.sec h2 {
  font-size: 13px; letter-spacing: .3em; color: var(--peri);
  font-weight: 600; margin: 0 0 14px;
}
.rows {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 18px;
  overflow: hidden;
}
.srow { display: flex; align-items: center; gap: 18px; padding: 16px 22px; }
.srow + .srow { border-top: 1px solid var(--line); }
.srow .t { font-size: 14.5px; font-weight: 600; letter-spacing: .04em; }
.srow .d { font-size: 12px; color: var(--muted); }
.srow .end { margin-left: auto; display: flex; align-items: center; gap: 12px; flex: none; }

/* 右ペイン(縦画面では非表示。開閉はモーダルで行う) */
.set-detail { display: none; }

@media (max-width: 620px) {
  .set-wrap { padding: 28px 16px 30px; }
  .srow { flex-wrap: wrap; row-gap: 8px; }
  .srow .end { margin-left: 0; width: 100%; justify-content: flex-end; }
}

/* ---------- 横画面: 左=設定項目 / 右=設定内容 ---------- */
@media (orientation: landscape) {
  .set-wrap { max-width: 1360px; }
  .set-cols { display: flex; gap: 26px; align-items: flex-start; }
  .set-nav { width: 400px; flex: none; }
  .set-nav .sec { margin-bottom: 26px; }
  .set-nav .rows { background: transparent; border: none; border-radius: 0; overflow: visible; }
  .set-nav .srow { padding: 12px 14px; border-radius: 12px; }
  .set-nav .srow + .srow { border-top: none; }
  .srow-link { cursor: pointer; transition: background .15s; }
  .srow-link:hover { background: var(--panel-2); }
  .srow-link.on { background: color-mix(in srgb, var(--accent) 10%, transparent); }
  .srow-link .end .btn { display: none; }
  .set-inline-title { font-size: 19px; letter-spacing: .14em; margin-bottom: 10px; }
  .set-detail {
    display: block; flex: 1; min-width: 0;
    padding: 0 4px 26px;
    position: sticky; top: 76px;
    max-height: calc(100vh - 100px);
    overflow-y: auto;
  }
}
"""


async def _is_landscape() -> bool:
    """横画面(=2ペイン表示)かどうか。JS が使えない環境ではモーダルにフォールバック。"""
    try:
        return bool(await ui.run_javascript("window.matchMedia('(orientation: landscape)').matches"))
    except Exception:
        return False


@ui.page("/v2/settings")
async def ui2_settings_page() -> None:
    ctx = get_context()
    install_drag_sort_script()

    with p3_page("設定"):
        ui.add_css(_PAGE_CSS + MEDIA_CSS)
        with ui.element("div").classes("set-wrap"):
            with ui.element("h1").classes("serif"):
                ui.html("設定")
            with ui.element("div").classes("set-lead"):
                ui.html("APIキーは暗号化して保管します。接続情報・生成・チャット・表示をここで管理します。")

            rows_registry: list[dict] = []
            link_rows: list[ui.element] = []
            inline_actions: list = []

            def _refresh_rows() -> None:
                for entry in rows_registry:
                    entry["slot"].clear()
                    with entry["slot"]:
                        text, tone = entry["summary"](ctx)
                        badge(text, tone=tone)

            def _row(title: str, desc: str, summary, open_fn, *, marker: str = "") -> None:
                row = ui.element("div").classes("srow srow-link")

                def _render_inline() -> None:
                    for other in link_rows:
                        other.classes(remove="on")
                    row.classes("on")
                    push_inline_settings_host(detail_panel)
                    try:
                        open_fn(ctx, _refresh_rows)
                    finally:
                        pop_inline_settings_host()

                def _open_from_button(e) -> None:
                    # ブラウザでは js_handler が向きを emit する。JS が動かない環境(テスト等)は
                    # args が空になるためモーダルにフォールバックする。
                    if e.args is True:
                        _render_inline()
                    else:
                        open_fn(ctx, _refresh_rows)

                # 行クリックは横画面のみ有効(縦画面は「開く」ボタンのモーダルのまま)
                row.on(
                    "click",
                    lambda: _render_inline(),
                    js_handler=(
                        "(e) => { if (window.matchMedia('(orientation: landscape)').matches) emit(); }"
                    ),
                )
                link_rows.append(row)
                inline_actions.append(_render_inline)
                with row:
                    with ui.element("div"):
                        with ui.element("div").classes("t"):
                            ui.html(html.escape(title))
                        with ui.element("div").classes("d"):
                            ui.html(html.escape(desc))
                    with ui.element("div").classes("end"):
                        slot = ui.element("span")
                        rows_registry.append({"slot": slot, "summary": summary})
                        btn = ui.element("button").classes("btn quiet")
                        with btn:
                            ui.html("開く")
                        btn.on(
                            "click",
                            _open_from_button,
                            js_handler=(
                                "(e) => { e.stopPropagation();"
                                " emit(window.matchMedia('(orientation: landscape)').matches); }"
                            ),
                        )
                        if marker:
                            btn.mark(marker)

            with ui.element("div").classes("set-cols"):
                with ui.element("div").classes("set-nav"):
                    # ---------------- 接続 ----------------
                    with ui.element("section").classes("sec"):
                        with ui.element("h2"):
                            ui.html("接続")
                        with ui.element("div").classes("rows"):
                            _row(
                                "LLMエンドポイント",
                                "OllamaやOpenAI互換APIの接続先とAPIキー",
                                endpoints_summary,
                                open_endpoints_dialog,
                                marker="ui2-settings-endpoints",
                            )
                            _row(
                                "LLMプロファイル",
                                "会話と生成に使うモデルの束(既定・複製・並べ替え)",
                                profiles_summary,
                                open_profiles_dialog,
                                marker="ui2-settings-profiles",
                            )
                            _row(
                                "Wizmy-Gen-Server",
                                "画像・音声生成サーバと機能割り当て・デフォルト値",
                                gen_server_summary,
                                open_gen_server_dialog,
                            )
                            _row(
                                "TTS API",
                                "音声合成サーバとの接続(Gen-Serverが使えない場合の代替)",
                                tts_endpoints_summary,
                                open_tts_endpoints_dialog,
                            )
                            _row(
                                "画像生成プロファイル",
                                "画像生成API・モデル・プロンプト・パラメータの組み合わせ",
                                image_profiles_summary,
                                open_image_profiles_dialog,
                            )
                            _row(
                                "APIキーボルト",
                                "APIキーの暗号化保管(設定・解錠・パスワード変更)",
                                vault_summary,
                                open_vault_dialog,
                                marker="ui2-settings-vault",
                            )

                    # ---------------- キャラクター生成 ----------------
                    with ui.element("section").classes("sec"):
                        with ui.element("h2"):
                            ui.html("キャラクター生成")
                        with ui.element("div").classes("rows"):
                            _row(
                                "生成プリセット",
                                "生成ページで呼び出す世界観・性別・年齢・テーマの組み合わせ",
                                presets_summary,
                                open_presets_dialog,
                                marker="ui2-settings-presets",
                            )
                            _row(
                                "選択肢リスト",
                                "世界観・年齢帯・性別の選択肢(「おまかせ」は先頭固定)",
                                options_summary,
                                open_options_dialog,
                            )

                    # ---------------- チャット ----------------
                    with ui.element("section").classes("sec"):
                        with ui.element("h2"):
                            ui.html("チャット")
                        with ui.element("div").classes("rows"):
                            _row(
                                "チャットモード",
                                "前提・シチュエーションのテンプレート",
                                chat_modes_summary,
                                open_chat_modes_dialog,
                                marker="ui2-settings-chat-modes",
                            )
                            _row(
                                "ユーザーペルソナ",
                                "キャラクターから見た「あなた」の設定(画像・音声込み)",
                                personas_summary,
                                open_user_personas_dialog,
                                marker="ui2-settings-personas",
                            )
                            _row(
                                "ナレーター",
                                "地の文の読み上げに使う声",
                                narrator_summary,
                                open_narrator_dialog,
                            )

                    # ---------------- 全般 ----------------
                    with ui.element("section").classes("sec"):
                        with ui.element("h2"):
                            ui.html("全般")
                        with ui.element("div").classes("rows"):
                            _row(
                                "表示と動作",
                                "テーマ(星あかり/ひなた)とピックアップの選び方",
                                general_summary,
                                open_general_dialog,
                                marker="ui2-settings-general",
                            )

                # ---------------- 右ペイン(横画面のみ表示) ----------------
                detail_panel = ui.element("div").classes("set-detail").mark("ui2-settings-detail")
                with detail_panel:
                    with ui.element("div").classes("note"):
                        ui.html("左の一覧から設定項目を選んでください")

            _refresh_rows()

            async def _auto_open_first() -> None:
                # 横画面では最初の項目を選択済みにしておく(標準的な設定UIの初期状態)
                if inline_actions and await _is_landscape():
                    inline_actions[0]()

            ui.timer(0.15, _auto_open_first, once=True)
