"""
生成ページ(グローバル /v2/generation とグループ内生成)で共有するUI部品。

- 状態A/B/C(モック generation.html)の共通CSS
- ForgePanel: 状態B(ベール+章立て+ツールログ+中断)の描画とイベント反映
- render_born: 状態C(誕生)の描画
- シート全文ダイアログ / 修正承認 diff ダイアログ(P3スキン)
- ボルト解錠行 / 実行中ジョブの復帰キー(`ui2_active_generation`)
"""

from __future__ import annotations

import html
from collections.abc import Callable

from nicegui import app, ui

from ..app_context import get_context
from ..core.character_generation.schemas import ProgressEvent, ProgressEventType, ToolCallRecord
from ..ui.state import is_vault_unlocked, set_vault_password
from .components.sparkle import sparkle_field
from .generation_logic import ChapterProgress
from .group_logic import DIFF_CSS, diff_html
from .group_setup import p3_button
from .sheet_logic import classify_body, kanji_number, list_items, parse_sections, table_rows

_DIALOG_CARD_STYLE = "background: var(--panel); color: var(--text);"

_ACTIVE_GENERATION_KEY = "ui2_active_generation"

# モック generation.html の <style> 移植+ツールログ/プレースホルダ/共通フォーム
GENERATION_CSS = (
    """
.gen-wrap { max-width: 1080px; margin: 0 auto; padding: 34px 26px 60px; }

/* ---------- 状態A:問いかけ ---------- */
.ask {
  position: relative;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 26px;
  padding: 54px 60px 44px;
  overflow: hidden;
}
.ask h1 {
  margin: 0 0 8px;
  font-size: 32px;
  letter-spacing: .14em;
  font-weight: 600;
  text-align: center;
}
.ask .sub { text-align: center; color: var(--muted); font-size: 13px; letter-spacing: .1em; margin-bottom: 30px; }
.ask .modes { display: flex; justify-content: center; gap: 8px; margin-bottom: 26px; flex-wrap: wrap; }
.ask .form-box { max-width: 660px; margin: 0 auto; position: relative; z-index: 2; }
.ask .go { text-align: center; margin-top: 26px; }
.ask .go .btn { padding: 12px 44px; font-size: 15px; }

.gen-quiet {
  display: flex; justify-content: center; gap: 10px;
  margin: 16px 0 4px;
  font-size: 13px; color: var(--muted);
  flex-wrap: wrap;
  align-items: center;
}
/* 4つ(プリセット/世界観/性別/年齢帯)が form-box 幅で1行に収まるよう均等割り */
.gen-select { flex: 1 1 0; min-width: 130px; }
.gen-select .q-field__control { background: var(--bg-2) !important; border-radius: 10px; }
/* モデル行はフォーム列(660px)と同じ幅に揃える */
.gen-profile-row { max-width: 660px; margin: 18px auto 0; justify-content: center; }
.gen-profile-row .gen-select { min-width: 0; }

/* Quasar textarea/input の P3 スキン(シートページと同じ .p3-ta) */
.p3-ta { width: 100%; }
.p3-ta .q-field__control { background: var(--bg-2) !important; border-radius: 12px; }
.p3-ta .q-field__control:before { border-color: var(--line-2) !important; }
.p3-ta textarea, .p3-ta input { color: var(--text) !important; line-height: 1.9; }

/* ベースキャラクター行(修正/関連) */
.base-box {
  display: flex; align-items: center; gap: 12px;
  background: var(--bg-2);
  border: 1px solid var(--line-2);
  border-radius: 16px;
  padding: 12px 16px;
  margin-bottom: 14px;
}
.base-box .b-face {
  width: 46px; height: 46px; border-radius: 50%; flex: none;
  border: 2px solid var(--line-2);
  background: var(--panel-2);
  background-size: cover;
  display: grid; place-items: center;
  color: var(--peri); font-family: "Yu Mincho", serif; font-size: 20px;
}
.base-box .b-name { font-size: 15px; font-weight: 600; flex: 1; min-width: 0; }
.base-box .b-name .b-sub { display: block; font-size: 11px; font-weight: 400; color: var(--muted); }

/* ---------- 状態B:生成中(章立て+ブレインストーミングログ) ---------- */
.forge {
  position: relative;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 26px;
  padding: 30px 38px 28px;
  overflow: hidden;
}

.chapters { position: relative; z-index: 2; min-width: 0; }
.chapters .ttl { font-size: 15px; letter-spacing: .18em; color: var(--muted); margin-bottom: 14px; }
/* 章立ては本文を出さず、チェック(done)とカーソル(now)だけの進捗表示 */
.chap { display: flex; gap: 12px; padding: 6px 0; align-items: baseline; }
.chap .no { width: 26px; color: var(--peri); font-family: "Yu Mincho", serif; flex: none; }
.chap .nm { flex: none; font-size: 14px; letter-spacing: .1em; }
.chap .st { font-size: 12.5px; color: var(--muted); min-width: 0; }
.chap.done .st::before { content: "✓"; color: var(--accent); }
.chap.now .nm { color: var(--accent); }
.chap.now .st::after {
  content: "";
  display: inline-block;
  width: 8px; height: 16px;
  background: var(--accent);
  vertical-align: text-bottom;
  animation: gen-blink 1s steps(2) infinite;
}
@keyframes gen-blink { 50% { opacity: 0; } }
.chap.todo { opacity: .4; }

.gen-status { font-size: 12px; color: var(--muted); letter-spacing: .04em; margin-top: 14px; }
.gen-log-cap { font-size: 11px; letter-spacing: .22em; color: var(--muted); margin: 14px 0 6px; }
/* ブレインストーミングログ: 出力行数に依存しない固定高さ(未出力でも枠を出す) */
.gen-log {
  height: 11rem;
  overflow-y: auto;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--bg-2);
  padding: 8px 12px;
  font-size: 12px;
  line-height: 1.8;
  color: var(--muted);
}
.gen-log .mk { margin-right: 6px; }
.gen-log .mk.hit { color: var(--accent); }
.forge .ops { display: flex; gap: 10px; margin-top: 20px; flex-wrap: wrap; }

/* ---------- 状態C:誕生(画像列なしの1カラム) ---------- */
.born {
  position: relative;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 26px;
  padding: 34px 42px 32px;
  overflow: hidden;
}
.born-body { position: relative; z-index: 2; min-width: 0; max-width: 760px; }
.born-body .hello { color: var(--peri); font-size: 12px; letter-spacing: .34em; margin-bottom: 14px; }
.born-body h2 { margin: 0 0 4px; font-size: 34px; letter-spacing: .1em; font-weight: 600; }
.born-body .oc { color: var(--muted); font-size: 13.5px; margin-bottom: 24px; }
.born-body .bubble { max-width: 480px; font-size: 15px; }
.born-body .facts { display: flex; gap: 8px; flex-wrap: wrap; margin: 24px 0 8px; }
.born-body .facts .chip { cursor: default; }
.born-body .save-note { font-size: 12px; color: var(--accent); margin-bottom: 18px; letter-spacing: .04em; }
.born-body .save-note.err { color: #e08a8a; }
.born-ops { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 14px; }

/* シート全文(ダイアログ内の章立て表示) */
.gsheet { max-height: 60vh; overflow-y: auto; width: 100%; }
.gsheet .gsec { position: relative; padding: 14px 0 14px 44px; border-top: 1px solid var(--line); }
.gsheet .gsec:first-of-type { border-top: none; }
.gsheet .gsec .no {
  position: absolute; left: 4px; top: 14px;
  color: var(--peri);
  font-family: "Yu Mincho", serif;
  font-size: 16px;
}
.gsheet .gsec h3 { margin: 0 0 8px; font-size: 13.5px; letter-spacing: .16em; font-weight: 600; }
.gsheet .gsec .bd { font-size: 13.5px; line-height: 1.95; color: var(--text); }
.gsheet .gsec .bd ul { margin: 0; padding-left: 20px; }
.gsheet .gsec .kv { display: grid; grid-template-columns: 110px 1fr; gap: 4px 16px; margin: 0; }
.gsheet .gsec .kv dt { color: var(--muted); font-size: 12px; padding-top: 3px; }
.gsheet .gsec .kv dd { margin: 0; font-size: 13.5px; }
.gsheet .gsec .quote {
  font-family: "Yu Mincho", serif;
  border-left: 2px solid var(--peri);
  padding-left: 14px;
}

/* ボルト解錠の注意行 */
.vault-row {
  display: flex; align-items: center; gap: 12px;
  border: 1px solid var(--line-2);
  border-radius: 14px;
  background: color-mix(in srgb, var(--accent) 8%, transparent);
  padding: 10px 16px;
  margin-bottom: 18px;
  font-size: 13px;
  color: var(--text);
}

/* ============ 縦画面・スマホ ============ */
@media (max-width: 900px) {
  .gen-wrap { padding: 24px 16px 40px; }
  .ask { padding: 36px 20px 32px; }
  .ask h1 { font-size: 23px; }
  .forge, .born { padding: 22px; }
  .born-body h2 { font-size: 26px; }
}
@media (max-width: 560px) {
  /* セレクト4つは 2×2 に */
  .gen-select { min-width: calc(50% - 5px); }
}
"""
    + DIFF_CSS
)

_STATUS_TEXT = {
    ProgressEventType.STARTED: "生成を開始しました。モデルの応答を待っています…",
    ProgressEventType.TOOL_CALLED: "ブレインストーミング中…",
    ProgressEventType.STAGE2_START: "キャラクターシートを執筆中…",
    ProgressEventType.DONE: "✓ 生成完了",
    ProgressEventType.STOPPED: "停止しました",
}


# ---------------------------------------------------------------------------
# 実行中ジョブの復帰キー
# ---------------------------------------------------------------------------


def remember_active_generation(job_id: str, scope: str) -> None:
    """復帰用にジョブIDとページスコープ("global" / "group:{gid}")を保存する。"""
    app.storage.user[_ACTIVE_GENERATION_KEY] = {"id": job_id, "scope": scope}


def recall_active_generation() -> tuple[str, str]:
    entry = app.storage.user.get(_ACTIVE_GENERATION_KEY)
    if not isinstance(entry, dict):
        return "", ""
    return str(entry.get("id") or ""), str(entry.get("scope") or "")


# ---------------------------------------------------------------------------
# 状態B: ForgePanel
# ---------------------------------------------------------------------------


class ForgePanel:
    """章立て(チェックのみ)+ブレインストーミングログ+中断(状態B)。`.forge` セクション内に build する。"""

    def __init__(self, on_stop, on_back) -> None:
        self._progress = ChapterProgress()
        self._on_stop = on_stop
        self._on_back = on_back

    def build(self) -> None:
        sparkle_field(12)
        with ui.element("div").classes("chapters"):
            with ui.element("div").classes("ttl serif"):
                ui.html("生成の進捗")
            self._rows_box = ui.element("div")
            self._status = ui.element("div").classes("gen-status")
            with ui.element("div").classes("gen-log-cap"):
                ui.html("ブレインストーミングログ")
            self._log = ui.element("div").classes("gen-log")
            with ui.element("div").classes("ops"):
                self._stop_btn = p3_button("中断", self._on_stop, classes="btn quiet").mark("ui2-gen-stop")
                self._back_btn = p3_button("入力に戻る", self._on_back, classes="btn quiet")
        self.reset()

    def reset(self) -> None:
        self._progress.reset()
        self._render_rows()
        self._set_status("待機中")
        self._log.clear()
        self._stop_btn.set_visibility(True)
        self._back_btn.set_visibility(False)

    def handle_event(self, event: ProgressEvent) -> None:
        try:
            self._handle_event_inner(event)
        except RuntimeError:
            pass

    def _handle_event_inner(self, event: ProgressEvent) -> None:
        if event.type == ProgressEventType.STARTED:
            self._progress.start()
        elif event.type == ProgressEventType.TOOL_CALLED:
            record: ToolCallRecord = event.data
            self._progress.apply_tool(record.result)
            self._append_log(record)
        elif event.type == ProgressEventType.STAGE1_DONE:
            data = event.data or {}
            self._progress.stage1_done()
            self._set_status(f"ブレインストーミング完了 — ツール {data.get('tool_count', 0)} 件")
            self._render_rows()
            return
        elif event.type == ProgressEventType.STAGE2_START:
            self._progress.start_stage2()
        elif event.type == ProgressEventType.DONE:
            self._progress.finish()
            self._stop_btn.set_visibility(False)
        elif event.type == ProgressEventType.ERROR:
            self._progress.halt()
            self._set_status(f"エラー: {event.data or '不明なエラー'}", error=True)
            self._render_rows()
            self._stop_btn.set_visibility(False)
            self._back_btn.set_visibility(True)
            return
        elif event.type == ProgressEventType.STOPPED:
            self._progress.halt()
            self._stop_btn.set_visibility(False)
            self._back_btn.set_visibility(True)
        if event.type in _STATUS_TEXT:
            self._set_status(_STATUS_TEXT[event.type])
        self._render_rows()

    def _render_rows(self) -> None:
        self._rows_box.clear()
        with self._rows_box:
            for row in self._progress.rows:
                with ui.element("div").classes(f"chap {row.status}"):
                    with ui.element("span").classes("no"):
                        ui.html(kanji_number(row.no))
                    with ui.element("span").classes("nm"):
                        ui.html(html.escape(row.name))
                    # 本文(row.detail)は表示しない — チェック(done)/カーソル(now)は
                    # CSS疑似要素で描画。詳細はブレインストーミングログ側に出る
                    ui.element("span").classes("st")

    def _set_status(self, text: str, *, error: bool = False) -> None:
        self._status.clear()
        with self._status:
            ui.html(html.escape(text))
        self._status.style(f"color: {'#e08a8a' if error else 'var(--muted)'};")

    def _append_log(self, record: ToolCallRecord) -> None:
        marker = "✓" if record.is_resolution else "◆"
        short = record.result[:90] + ("…" if len(record.result) > 90 else "")
        with self._log:
            ui.html(
                f'<div><span class="mk{" hit" if record.is_resolution else ""}">{marker}</span>'
                f"<span>{html.escape(short)}</span></div>"
            )
        ui.run_javascript(
            f"var el = document.getElementById('c{self._log.id}'); if (el) el.scrollTop = el.scrollHeight;"
        )


# ---------------------------------------------------------------------------
# 状態C: 誕生
# ---------------------------------------------------------------------------


def render_born(
    container: ui.element,
    *,
    name: str,
    oc: str,
    intro: str,
    facts: list[str],
    save_note: str = "",
    save_note_error: bool = False,
    build_ops: Callable[[], None],
) -> None:
    """状態C(誕生)を `.born` セクションへ描画する。build_ops でボタン列を差し込む。

    画像は同時生成しないため画像列は置かない(1カラム)。
    """
    container.clear()
    with container:
        sparkle_field(20)
        with ui.element("div").classes("born-body"):
            with ui.element("div").classes("hello"):
                ui.html("生成結果")
            with ui.element("h2").classes("serif").mark("ui2-gen-born-name"):
                ui.html(html.escape(name or "名称未設定"))
            if oc:
                with ui.element("div").classes("oc"):
                    ui.html(html.escape(oc))
            if intro:
                with ui.element("div").classes("bubble tail-left"):
                    ui.html(html.escape(f"「{intro}」"))
            if facts:
                with ui.element("div").classes("facts"):
                    for fact in facts:
                        with ui.element("span").classes("chip"):
                            ui.html(html.escape(fact))
            if save_note:
                with ui.element("div").classes("save-note" + (" err" if save_note_error else "")):
                    ui.html(html.escape(save_note))
            with ui.element("div").classes("born-ops"):
                build_ops()
    ui.run_javascript("window.p3SparkleFill && window.p3SparkleFill();")


# ---------------------------------------------------------------------------
# ダイアログ群
# ---------------------------------------------------------------------------


def render_sheet_sections(markdown: str) -> None:
    """シートMarkdownを章立て(gsheet)で描画する(全文表示・ベース確認用)。"""
    sections = parse_sections(markdown)
    with ui.element("div").classes("gsheet"):
        if not sections:
            ui.html(html.escape(markdown or "(内容がありません)")).classes("note")
        for index, section in enumerate(sections):
            with ui.element("section").classes("gsec"):
                with ui.element("span").classes("no"):
                    ui.html(kanji_number(index + 1))
                with ui.element("h3"):
                    ui.html(html.escape(section.header))
                with ui.element("div").classes("bd"):
                    _render_section_body(section.body)


def _render_section_body(body: str) -> None:
    kind = classify_body(body)
    if kind == "table":
        with ui.element("dl").classes("kv"):
            for key, value in table_rows(body):
                with ui.element("dt"):
                    ui.html(html.escape(key))
                with ui.element("dd"):
                    ui.html(html.escape(value))
    elif kind == "list":
        with ui.element("ul"):
            for item in list_items(body):
                with ui.element("li"):
                    ui.html(html.escape(item))
    elif kind == "quote":
        with ui.element("div").classes("quote"):
            ui.html(html.escape(body.strip()))
    else:
        ui.html(html.escape(body).replace("\n", "<br>"))


def open_sheet_dialog(markdown: str, *, title: str = "生成されたシート") -> None:
    with ui.dialog() as dlg, ui.card().classes("w-full max-w-3xl").style(_DIALOG_CARD_STYLE):
        ui.label(title).classes("text-base font-semibold mb-2")
        render_sheet_sections(markdown)
        with ui.row().classes("justify-end mt-3 w-full"):
            p3_button("閉じる", dlg.close, classes="btn quiet")
    dlg.open()


def open_modify_approve_dialog(
    *,
    name: str,
    old_markdown: str,
    new_markdown: str,
    on_approve: Callable[[], object],
) -> None:
    """修正承認 diff ダイアログ。承認で on_approve()(coroutine 可)を呼ぶ。"""
    with ui.dialog() as dlg, ui.card().classes("w-full max-w-3xl").style(_DIALOG_CARD_STYLE):
        ui.label("修正内容の確認").classes("text-base font-semibold")
        ui.label(f"「{name}」への変更内容を確認してください。緑が追加、赤が削除です。").classes("note")
        ui.html(diff_html(old_markdown, new_markdown), sanitize=False).classes("w-full")

        async def _approve() -> None:
            dlg.close()
            result = on_approve()
            if result is not None:
                await result

        def _reject() -> None:
            ui.notify("修正を破棄しました(生成結果は残っています)", type="info")
            dlg.close()

        with ui.row().classes("justify-end gap-2 mt-4 w-full"):
            p3_button("破棄", _reject, classes="btn quiet")
            p3_button("承認して上書き", _approve, classes="btn primary").mark("ui2-gen-approve")
    dlg.open()


# ---------------------------------------------------------------------------
# ボルト解錠
# ---------------------------------------------------------------------------


def render_vault_row() -> None:
    """ボルトがロック中のとき注意行を出す(解錠で行ごと消える)。"""
    ctx = get_context()

    @ui.refreshable
    def _row() -> None:
        if is_vault_unlocked() or not ctx.api_config.is_vault_setup():
            return
        with ui.element("div").classes("vault-row"):
            ui.html("APIキーボルトがロックされています。キー付きエンドポイントを使うには解錠してください。")
            p3_button("解錠", lambda: _open_unlock_dialog(_row.refresh), classes="btn quiet")

    def _open_unlock_dialog(refresh) -> None:
        with ui.dialog() as dlg, ui.card().classes("min-w-[320px]").style(_DIALOG_CARD_STYLE):
            ui.label("ボルトの解錠").classes("text-base font-semibold mb-2")
            pw_input = ui.input("パスワード").props("type=password clearable outlined dense").classes(
                "w-full p3-ta"
            )

            def _unlock() -> None:
                if not pw_input.value:
                    ui.notify("パスワードを入力してください", type="warning")
                    return
                if ctx.api_config.verify_vault_password(str(pw_input.value)):
                    set_vault_password(str(pw_input.value))
                    ui.notify("解錠しました", type="positive")
                    dlg.close()
                    refresh()
                else:
                    ui.notify("パスワードが正しくありません", type="negative")

            pw_input.on("keydown.enter", _unlock)
            with ui.row().classes("justify-end gap-2 mt-3 w-full"):
                p3_button("キャンセル", dlg.close, classes="btn quiet")
                p3_button("解錠", _unlock, classes="btn primary")
        dlg.open()

    _row()
