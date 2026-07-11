"""
生成ページ(グローバル /generation とグループ内生成)で共有するUI部品。

- 状態A/B/C(モック generation.html)の共通CSS
- ForgePanel: 状態B(ベール+章立て+ツールログ+中断)の描画とイベント反映
- render_born: 状態C(誕生)の描画
- シート全文ダイアログ / 修正承認 diff ダイアログ(P3スキン)
- 実行中ジョブの復帰キー(`ui2_active_generation`)
"""

from __future__ import annotations

import html
from collections.abc import Callable

from nicegui import app, ui

from ..core.character_generation.schemas import ProgressEvent, ProgressEventType, ToolCallRecord
from .components.sparkle import sparkle_field
from .generation_logic import ChapterProgress
from .group_logic import DIFF_CSS, diff_html
from .group_setup import p3_button
from .sheet_logic import classify_body, kanji_number, list_items, parse_sections, table_rows

_DIALOG_CARD_STYLE = "background: var(--panel); color: var(--text);"

_ACTIVE_GENERATION_KEY = "ui2_active_generation"

# 生成→キャラシ遷移時の確認バー受け渡しキー(pop で一度だけ表示)
GEN_CONFIRM_KEY = "ui2_gen_confirm"

# モック generation.html の <style> 移植+ツールログ/プレースホルダ/共通フォーム
GENERATION_CSS = (
    """
.gen-wrap { max-width: 780px; margin: 0 auto; padding: 34px 26px 60px; }

/* ---------- 状態A:問いかけ ---------- */
.ask {
  position: relative;
  padding: 44px 0 24px;
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

/* 控えめセレクト行(モック状態Aの quiet-row: ラベル+下線のみ) */
.gen-quiet {
  display: flex; justify-content: center; gap: 22px;
  margin: 22px 0 4px;
  font-size: 13px; color: var(--muted);
  flex-wrap: wrap;
  align-items: center;
}
.gen-quiet .q-lbl { display: flex; gap: 8px; align-items: center; }
.gen-select { width: auto; min-width: 110px; }
.gen-select .q-field__control {
  background: transparent !important;
  border: none;
  border-bottom: 1px solid var(--line-2);
  border-radius: 0;
  min-height: 30px;
  padding: 0 4px;
}
.gen-select .q-field__control:before, .gen-select .q-field__control:after { display: none; }
.gen-select .q-field__native { color: var(--text); font-size: 13px; min-height: 0; padding: 2px 0; }
.gen-select .q-field__append { color: var(--muted); }
/* モデル行も同じ quiet トーン */
.gen-profile-row { margin: 16px auto 0; justify-content: center; }
.gen-profile-row .gen-select { min-width: 220px; max-width: 340px; }
/* プリセットは独立した先頭行 */
.gen-preset-row { margin: 0 0 14px; }
.gen-preset-row .gen-select { min-width: 180px; max-width: 320px; }

/* 状態Aの中央テキストエリア(モック .ask textarea 相当) */
.ask-ta { display: block; width: 100%; }
.ask-ta .q-field__control {
  background: transparent !important;
  border: 1px solid var(--line-2);
  border-radius: 0;
  padding: 10px 18px;
  min-height: 110px;
  transition: border-color .18s;
}
.ask-ta .q-field__control:before, .ask-ta .q-field__control:after { display: none; }
.ask-ta .q-field__control:focus-within { border-color: var(--accent); }
.ask-ta textarea { color: var(--text) !important; font-size: 15px; line-height: 1.9; }

/* Quasar textarea/input の P3 スキン(シートページと同じ .p3-ta) */
.p3-ta { width: 100%; }
.p3-ta .q-field__control { background: transparent !important; border-radius: 0; }
.p3-ta .q-field__control:before { border-color: var(--line-2) !important; }
.p3-ta textarea, .p3-ta input { color: var(--text) !important; line-height: 1.9; }

/* ベースキャラクター行(修正/関連) */
.base-box {
  display: flex; align-items: center; gap: 12px;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  padding: 12px 4px;
  margin-bottom: 16px;
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
  padding: 34px 0 20px;
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
.gen-log-cap {
  display: inline-flex; align-items: center; gap: 7px;
  border: none; background: none; padding: 0; cursor: pointer;
  font-size: 11px; letter-spacing: .22em; color: var(--muted); margin: 14px 0 6px;
  transition: color .15s;
}
.gen-log-cap:hover { color: var(--text); }
.gen-log-cap .caret { display: inline-block; font-size: 9px; transition: transform .2s; }
.gen-log-cap.closed .caret { transform: rotate(-90deg); }
/* ブレインストーミングログ: 出力行数に依存しない固定高さ(未出力でも枠を出す) */
.gen-log {
  height: 11rem;
  overflow-y: auto;
  border: 1px solid var(--line);
  background: var(--bg-2);
  padding: 8px 12px;
  font-size: 12px;
  line-height: 1.8;
  color: var(--muted);
}
.gen-log.closed { display: none; }
.gen-log .mk { margin-right: 6px; }
.gen-log .mk.hit { color: var(--accent); }
.forge .ops { display: flex; gap: 10px; margin-top: 20px; flex-wrap: wrap; }

/* ---------- 状態C:誕生(画像列なしの1カラム) ---------- */
.born {
  position: relative;
  padding: 34px 0 24px;
  overflow: hidden;
}
.born-body { position: relative; z-index: 2; min-width: 0; max-width: 760px; }
.born-body .hello { color: var(--peri); font-size: 12px; letter-spacing: .34em; margin-bottom: 14px; }
.born-body h2 { margin: 0 0 4px; font-size: 34px; letter-spacing: .1em; font-weight: 600; }
.born-body .oc { color: var(--muted); font-size: 13.5px; margin-bottom: 24px; }
.born-body .bubble {
  max-width: 520px; font-size: 15px;
  background: none; border: none; box-shadow: none; border-radius: 0; padding: 0;
  font-family: "Yu Mincho", "Hiragino Mincho ProN", serif; line-height: 2;
}
.born-body .bubble::before { display: none; }
.born-body .facts { display: flex; gap: 8px; flex-wrap: wrap; margin: 24px 0 8px; }
.born-body .facts .chip { cursor: default; }
.born-body .save-note { font-size: 12px; color: var(--accent); margin-bottom: 18px; letter-spacing: .04em; }
.born-body .save-note.err { color: #e08a8a; }
.born-ops { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 14px; }

/* フォーム下のフェーズ進捗(カード無し・ヘアラインで区切る) */
.gen-strip {
  max-width: 660px;
  margin: 30px auto 0;
  position: relative; z-index: 2;
  border-top: 1px solid var(--line);
  padding-top: 18px;
}
.strip-phases { display: flex; gap: 6px 20px; flex-wrap: wrap; align-items: baseline; }
.sph { display: inline-flex; gap: 7px; align-items: baseline; font-size: 12.5px; letter-spacing: .06em; color: var(--muted); }
.sph .nm { white-space: nowrap; }
.sph .no { font-family: "Yu Mincho", serif; color: var(--peri); font-size: 13px; }
.sph.todo { opacity: .38; }
.sph.now .nm { color: var(--accent); }
.sph.now .nm::after {
  content: "";
  display: inline-block;
  width: 7px; height: 13px;
  background: var(--accent);
  vertical-align: text-bottom;
  margin-left: 5px;
  animation: gen-blink 1s steps(2) infinite;
}
.sph.done .nm::after { content: " ✓"; color: var(--accent); font-size: 11px; }
.gen-strip .ops { display: flex; gap: 10px; margin-top: 14px; }

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

/* ============ 縦画面・スマホ ============ */
@media (max-width: 900px) {
  .gen-wrap { padding: 24px 16px 40px; }
  .ask { padding: 26px 0 18px; }
  .ask h1 { font-size: 23px; }
  .forge, .born { padding: 20px 0 14px; }
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
        self._log_open = False

    def build(self) -> None:
        sparkle_field(12)
        with ui.element("div").classes("chapters"):
            with ui.element("div").classes("ttl serif"):
                ui.html("生成の進捗")
            self._rows_box = ui.element("div")
            self._status = ui.element("div").classes("gen-status")
            self._log_cap = ui.element("button").classes("gen-log-cap closed")
            with self._log_cap:
                ui.html('<span class="caret">▾</span><span>ブレインストーミングログ</span>')
            self._log_cap.on("click", self._toggle_log)
            self._log = ui.element("div").classes("gen-log closed")
            with ui.element("div").classes("ops"):
                self._stop_btn = p3_button("中断", self._on_stop, classes="btn quiet").mark("ui2-gen-stop")
                self._back_btn = p3_button("入力に戻る", self._on_back, classes="btn quiet")
        self.reset()

    def _set_log_open(self, is_open: bool) -> None:
        self._log_open = is_open
        if is_open:
            self._log_cap.classes(remove="closed")
            self._log.classes(remove="closed")
        else:
            self._log_cap.classes("closed")
            self._log.classes("closed")

    def _toggle_log(self) -> None:
        self._set_log_open(not self._log_open)

    def reset(self) -> None:
        self._progress.reset()
        self._render_rows()
        self._set_status("待機中")
        self._log.clear()
        self._set_log_open(False)
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


class ForgeStrip(ForgePanel):
    """フォーム直下に置く水平のフェーズ進捗。イベント処理は ForgePanel を共有する。"""

    def build(self) -> None:
        self._rows_box = ui.element("div").classes("strip-phases")
        self._status = ui.element("div").classes("gen-status")
        self._log_cap = ui.element("button").classes("gen-log-cap closed")
        with self._log_cap:
            ui.html('<span class="caret">▾</span><span>ブレインストーミングログ</span>')
        self._log_cap.on("click", self._toggle_log)
        self._log = ui.element("div").classes("gen-log closed")
        with ui.element("div").classes("ops"):
            self._stop_btn = p3_button("中断", self._on_stop, classes="btn quiet").mark("ui2-gen-stop")
            self._back_btn = p3_button("閉じる", self._on_back, classes="btn quiet")
        self.reset()

    def _render_rows(self) -> None:
        self._rows_box.clear()
        with self._rows_box:
            for row in self._progress.rows:
                with ui.element("span").classes(f"sph {row.status}"):
                    with ui.element("span").classes("no"):
                        ui.html(kanji_number(row.no))
                    with ui.element("span").classes("nm"):
                        ui.html(html.escape(row.name))


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
                    render_section_body(section.body)


def render_section_body(body: str) -> None:
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


