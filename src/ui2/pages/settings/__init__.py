"""
/v2/settings 設定ページ(Phase 6)。モック settings.html の行リスト骨格準拠。

各行の「開く」が管理ダイアログ(Quasar フォーム+P3スキン)を開く。
セクション: 接続 / キャラクター生成 / チャット / 動作 / 外観。
"""

from __future__ import annotations

import html

from nicegui import app, ui

from ....app_context import get_context
from ...components.pickup import DEFAULT_POLICY, PICKUP_POLICY_KEY, POLICIES
from ...media_ui import MEDIA_CSS, p3_button
from ...scaffold import p3_page
from ...theme import THEMES, get_theme, set_theme
from .chat import chat_modes_summary, open_chat_modes_dialog, open_user_personas_dialog, personas_summary
from .common import badge, install_drag_sort_script
from .connection import (
    endpoints_summary,
    open_endpoints_dialog,
    open_profiles_dialog,
    profiles_summary,
)
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

_PICKUP_POLICY_LABELS: dict[str, str] = {
    "mixed": "混成+きまぐれ",
    "favorites": "お気に入り",
    "recent": "最近",
    "daily": "日替わり",
}

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

@media (max-width: 620px) {
  .set-wrap { padding: 28px 16px 30px; }
  .srow { flex-wrap: wrap; row-gap: 8px; }
  .srow .end { margin-left: 0; width: 100%; justify-content: flex-end; }
}
"""


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
                ui.html("APIキーは暗号化して保管します。接続情報・生成・チャット・外観をここで管理します。")

            rows_registry: list[dict] = []

            def _refresh_rows() -> None:
                for entry in rows_registry:
                    entry["slot"].clear()
                    with entry["slot"]:
                        text, tone = entry["summary"](ctx)
                        badge(text, tone=tone)

            def _row(title: str, desc: str, summary, open_fn, *, marker: str = "") -> None:
                with ui.element("div").classes("srow"):
                    with ui.element("div"):
                        with ui.element("div").classes("t"):
                            ui.html(html.escape(title))
                        with ui.element("div").classes("d"):
                            ui.html(html.escape(desc))
                    with ui.element("div").classes("end"):
                        slot = ui.element("span")
                        rows_registry.append({"slot": slot, "summary": summary})
                        btn = p3_button("開く", lambda: open_fn(ctx, _refresh_rows), classes="btn quiet")
                        if marker:
                            btn.mark(marker)

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

            # ---------------- 動作 ----------------
            with ui.element("section").classes("sec"):
                with ui.element("h2"):
                    ui.html("動作")
                with ui.element("div").classes("rows"):
                    with ui.element("div").classes("srow"):
                        with ui.element("div"):
                            with ui.element("div").classes("t"):
                                ui.html("ピックアップの選び方")
                            with ui.element("div").classes("d"):
                                ui.html("キャラクター一覧上段の顔ぶれの選出ポリシー")
                        with ui.element("div").classes("end"):
                            policy_value = str(app.storage.user.get(PICKUP_POLICY_KEY, DEFAULT_POLICY))
                            if policy_value not in POLICIES:
                                policy_value = DEFAULT_POLICY
                            policy_select = (
                                ui.select(
                                    options={key: _PICKUP_POLICY_LABELS.get(key, key) for key in POLICIES},
                                    value=policy_value,
                                )
                                .props("outlined dense")
                                .classes("p3-fd")
                                .style("min-width: 200px;")
                                .mark("ui2-settings-pickup-policy")
                            )

                            def _on_policy_change(_) -> None:
                                app.storage.user[PICKUP_POLICY_KEY] = str(policy_select.value or DEFAULT_POLICY)
                                ui.notify("ピックアップの選び方を保存しました", type="positive", timeout=1200)

                            policy_select.on_value_change(_on_policy_change)

            # ---------------- 外観 ----------------
            with ui.element("section").classes("sec"):
                with ui.element("h2"):
                    ui.html("外観")
                with ui.element("div").classes("rows"):
                    with ui.element("div").classes("srow"):
                        with ui.element("div"):
                            with ui.element("div").classes("t"):
                                ui.html("テーマ")
                            with ui.element("div").classes("d"):
                                ui.html("星あかり(暗)/ ひなた(明)の二相")
                        with ui.element("div").classes("end"):
                            theme_slot = ui.element("span")

                            def _render_theme_badge() -> None:
                                theme_slot.clear()
                                with theme_slot:
                                    badge(THEMES[get_theme()]["label"], tone="accent")

                            _render_theme_badge()

                            def _toggle_theme() -> None:
                                new_theme = "hinata" if get_theme() == "hoshi" else "hoshi"
                                set_theme(new_theme)
                                # ナビのボタン表記等も含めて確実に反映するためリロードする
                                ui.navigate.reload()

                            p3_button("切り替え", _toggle_theme, classes="btn quiet").mark(
                                "ui2-settings-theme-toggle"
                            )

            _refresh_rows()
