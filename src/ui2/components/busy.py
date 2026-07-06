"""LLM補助実行中のビジーダイアログ(キャンセル対応)。

旧 dialogs_group.py の busy_dialog パターンの P3 版。`begin()` → 補助ジョブが
開始されたら `set_job(job_id)`(キャンセル可能に)→ 完了時に `end()`。
"""

from __future__ import annotations

from nicegui import ui

from ...app_context import get_context


class BusyController:
    def __init__(self) -> None:
        self._active = False
        self._job_id = ""
        with (
            ui.dialog().props("persistent") as dialog,
            ui.card()
            .classes("items-center gap-3 px-6 py-5")
            .style("min-width: min(320px, 86vw); background: var(--panel); color: var(--text);"),
        ):
            ui.spinner(size="lg")
            self._label = ui.label("処理中です").classes("text-sm font-semibold text-center")
            self._cancel_btn = ui.button("キャンセル", on_click=self._cancel).props("outline color=negative")
            self._cancel_btn.disable()
        self._dialog = dialog

    def begin(self, label: str) -> None:
        self._active = True
        self._job_id = ""
        self._label.set_text(label)
        self._cancel_btn.disable()
        self._dialog.open()

    def set_job(self, job_id: str) -> None:
        if not self._active:
            return
        self._job_id = job_id
        self._cancel_btn.enable()

    def end(self) -> None:
        self._active = False
        self._job_id = ""
        self._cancel_btn.disable()
        self._dialog.close()

    async def _cancel(self) -> None:
        if not self._job_id:
            return
        self._label.set_text("停止要求中...")
        self._cancel_btn.disable()
        await get_context().ai_jobs.cancel_job(self._job_id)
