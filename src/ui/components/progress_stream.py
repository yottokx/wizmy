"""
生成進捗表示コンポーネント。

ツール呼び出しのログとフェーズ進捗をリアルタイムで表示する。
"""

from __future__ import annotations

import html as _html

from nicegui import ui

from ...core.character_generation.schemas import ProgressEvent, ProgressEventType, ToolCallRecord
from ...core.character_generation.prompts import PHASE_LABELS, PHASE_KEYWORDS

_PHASE_LETTERS: dict[str, str] = {
    "A: 世界観・基本":   "A",
    "B: 外見・性格":     "B",
    "C: 背景・スキル":   "C",
    "D: 人間関係・名前": "D",
}


def _classify_phase(text: str) -> str | None:
    for phase, keywords in PHASE_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return phase
    return None


class ProgressPanel:
    """生成進捗パネル。"""

    def __init__(self) -> None:
        self._tool_rows: list[dict] = []
        self._stage1_done = False
        self._stage2_active = False
        self._error: str | None = None
        self._container: ui.element | None = None
        self._phase_steps: dict[str, ui.element] = {}

    def build(self) -> None:
        with ui.card().classes("w-full"):
            with ui.row().classes("items-center gap-2 mb-3"):
                ui.icon("psychology").style("color: var(--cs-accent); font-size: 1.1rem;")
                ui.label("生成進捗").classes("text-sm font-semibold").style("color: var(--cs-text);")

            # フェーズステップ表示
            self._phase_row = ui.row().classes("gap-2 flex-wrap mb-3")
            with self._phase_row:
                for label in PHASE_LABELS:
                    letter = _PHASE_LETTERS.get(label, "?")
                    step = ui.element("div").classes("cs-phase-step")
                    with step:
                        ui.html(
                            f'<span style="font-size:0.65rem;opacity:0.7;">{letter}</span>'
                            f'<span>{label[3:]}</span>'
                        )
                    self._phase_steps[label] = step

            # ステータスラベル
            self._status_label = (
                ui.label("待機中 ─ 生成ボタンを押してください")
                .classes("text-xs")
                .style("color: var(--cs-muted);")
            )

            # ツールログ
            self._tool_log = ui.scroll_area().classes("w-full cs-log-area").style("height: 9rem;")
            with self._tool_log:
                self._tool_list = ui.column().classes("w-full gap-0 py-1")
                with self._tool_list:
                    _placeholder_entries = [
                        ("◆", "世界観の候補を選択中..."),
                        ("◆", "舞台・場所の候補を選択中..."),
                        ("◆", "職業・役割の候補を選択中..."),
                    ]
                    for marker, text in _placeholder_entries:
                        ui.html(
                            f'<div class="cs-log-entry" style="color: var(--cs-border);">'
                            f'<span style="color: var(--cs-border); margin-right:5px;">{marker}</span>'
                            f'<span>{text}</span>'
                            f'</div>'
                        )

            # Stage2 スピナー
            with ui.row().classes("items-center gap-2 mt-2"):
                self._stage2_spinner = (
                    ui.spinner("dots").classes("hidden").style("color: var(--cs-accent);")
                )
                self._stage2_label = (
                    ui.label("").classes("text-xs").style("color: var(--cs-muted);")
                )

    def handle_event(self, event: ProgressEvent) -> None:
        try:
            self._handle_event_inner(event)
        except RuntimeError:
            pass

    def _handle_event_inner(self, event: ProgressEvent) -> None:
        if event.type == ProgressEventType.STARTED:
            self._status_label.set_text("生成を開始しました。モデルの応答を待っています...")
            self._status_label.style("color: var(--cs-muted);")

        elif event.type == ProgressEventType.TOOL_CALLED:
            tc: ToolCallRecord = event.data
            self._status_label.set_text("ブレインストーミング中...")
            self._status_label.style("color: var(--cs-muted);")
            self._add_tool_log(tc)
            self._update_phase_step(tc.result)

        elif event.type == ProgressEventType.STAGE1_DONE:
            data = event.data or {}
            count = data.get("tool_count", 0)
            self._status_label.set_text(f"ブレインストーミング完了 — ツール {count} 件")
            self._status_label.style("color: var(--cs-accent);")

        elif event.type == ProgressEventType.STAGE2_START:
            self._stage2_spinner.classes(remove="hidden")
            self._stage2_label.set_text("シートを組み立て中...")
            self._status_label.set_text("キャラクターシートを執筆中...")
            self._status_label.style("color: var(--cs-muted);")

        elif event.type == ProgressEventType.DONE:
            self._stage2_spinner.classes("hidden")
            self._stage2_label.set_text("")
            self._status_label.set_text("✓  生成完了")
            self._status_label.style("color: var(--cs-accent); font-weight: 600;")

        elif event.type == ProgressEventType.ERROR:
            self._stage2_spinner.classes("hidden")
            error_msg = str(event.data or "不明なエラー")
            self._status_label.set_text(f"エラー: {error_msg}")
            self._status_label.style("color: var(--cs-negative);")

        elif event.type == ProgressEventType.STOPPED:
            self._stage2_spinner.classes("hidden")
            self._status_label.set_text("停止しました")
            self._status_label.style("color: var(--cs-muted);")

    def _update_phase_step(self, result_text: str) -> None:
        phase = _classify_phase(result_text)
        if not phase:
            return
        step = self._phase_steps.get(phase)
        if not step:
            return
        step.classes(remove="cs-phase-active")
        step.classes("cs-phase-done")

    def _add_tool_log(self, tc: ToolCallRecord) -> None:
        marker = "✓" if tc.is_resolution else "◆"
        marker_color = "var(--cs-accent)" if tc.is_resolution else "var(--cs-muted)"
        short = tc.result[:90] + "…" if len(tc.result) > 90 else tc.result
        escaped = _html.escape(short)
        with self._tool_list:
            ui.html(
                f'<div class="cs-log-entry">'
                f'<span style="color:{marker_color}; margin-right:5px;">{marker}</span>'
                f'<span style="color:var(--cs-text);">{escaped}</span>'
                f'</div>'
            )
        # コンテンツ末尾へ即座にスクロール（duration=0）
        self._tool_log.run_method("setScrollPosition", "vertical", 999999, 0)

    def reset(self) -> None:
        self._tool_list.clear()
        self._status_label.set_text("待機中 ─ 生成ボタンを押してください")
        self._status_label.style("color: var(--cs-muted);")
        self._stage2_spinner.classes("hidden")
        self._stage2_label.set_text("")
        for step in self._phase_steps.values():
            step.classes(remove="cs-phase-active cs-phase-done")
