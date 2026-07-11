"""修正生成の暫定キャラシ(差分確認)。

- /generation/review/{job_id}: グローバル生成の修正
- /groups/{group_id}/generation/review/{job_id}: 箱庭生成の「住人を修正」

既存キャラシページとは独立した読み取り専用ビュー。生成ジョブの Markdown から
章立てを描画し、変更のあった章だけインライン diff を埋め込む。
画面下バーの「はい」で上書き保存、「いいえ」で破棄。どちらも元のシートへ遷移する。
ジョブが見つからない(TTL切れ・再起動)場合は生成ページへリダイレクト。
"""

from __future__ import annotations

import html

from fastapi.responses import RedirectResponse
from nicegui import ui

from ...app_context import get_context
from ...core.character.markdown import sheet_from_markdown_preserving
from ...core.character.schemas import GenerationMeta
from ...core.character_generation.schemas import GenerationMode
from ...core.conversation.group_setup import sanitize_group_generated_markdown
from ..generation_ui import GENERATION_CSS, render_section_body
from ..group_logic import diff_html
from ..group_setup import p3_button
from ..scaffold import p3_page
from ..sheet_logic import kanji_number, parse_sections

_PAGE_CSS = """
.review-wrap { max-width: 780px; margin: 0 auto; padding: 34px 26px 120px; }
.review-head h2 {
  margin: 0 0 4px; font-size: 28px; letter-spacing: .12em; font-weight: 600;
}
.review-head .note-line { font-size: 12.5px; color: var(--muted); letter-spacing: .04em; margin-bottom: 8px; }
.review-secs { margin-top: 18px; }
.rsec { position: relative; border-top: 1px solid var(--line); padding: 18px 0 20px 48px; }
.rsec .no {
  position: absolute; left: 4px; top: 20px;
  color: var(--peri); font-family: "Yu Mincho", serif; font-size: 16px;
}
.rsec h3 { margin: 0 0 8px; font-size: 13.5px; letter-spacing: .16em; font-weight: 600; }
.rsec h3 .chg { margin-left: 10px; font-size: 10.5px; color: var(--accent); letter-spacing: .1em; }
.rsec h3 .chg.del { color: #e08a8a; }
.rsec .bd { font-size: 13.5px; line-height: 1.95; }
.rsec .bd ul { margin: 0; padding-left: 20px; }
.rsec .kv { display: grid; grid-template-columns: 110px 1fr; gap: 4px 16px; margin: 0; }
.rsec .kv dt { color: var(--muted); font-size: 12px; padding-top: 3px; }
.rsec .kv dd { margin: 0; font-size: 13.5px; }
.rsec .quote {
  font-family: "Yu Mincho", serif;
  border-left: 2px solid var(--peri);
  padding-left: 14px;
}

/* 画面下の確認バー */
.review-bar {
  position: fixed; left: 0; right: 0; bottom: 0; z-index: 80;
  display: flex; gap: 14px; align-items: center; justify-content: center;
  flex-wrap: wrap;
  padding: 12px 20px;
  background: color-mix(in srgb, var(--bg) 88%, transparent);
  backdrop-filter: blur(12px);
  border-top: 1px solid var(--line-2);
}
.review-bar .msg-t { font-size: 13.5px; letter-spacing: .04em; }
"""


@ui.page("/generation/review/{job_id}")
async def ui2_generation_review_page(job_id: str):
    ctx = get_context()
    job = ctx.generation.get_job(job_id)
    result = job.result if job is not None else None
    if job is not None and job.saved_character_id:
        # 既に承認済み(または別経路で保存済み)なら本物のシートへ
        return RedirectResponse(f"/characters/{job.saved_character_id}", status_code=307)
    if (
        job is None
        or result is None
        or not result.success
        or job.request.mode != GenerationMode.MODIFY
        or not job.base_character_id
    ):
        return RedirectResponse("/generation", status_code=307)
    base = await ctx.characters.get(job.base_character_id)
    if base is None:
        return RedirectResponse("/generation", status_code=307)

    busy = {"flag": False}

    async def _apply() -> None:
        if busy["flag"]:
            return
        busy["flag"] = True
        try:
            updated = sheet_from_markdown_preserving(base, result.sheet_markdown)
            updated.generation_meta = GenerationMeta(
                llm_profile_name=job.profile.name,
                model_id=job.profile.model_id,
                temperature=job.profile.temperature if not job.profile.reasoning_enabled else None,
                reasoning_enabled=job.profile.reasoning_enabled,
                mode=result.mode.value,
                tool_count=result.tool_count,
                quality_status=result.quality_status,
                quality_score=result.quality_score,
            )
            try:
                saved = await ctx.characters.save(updated)
            except Exception as err:
                ui.notify(f"保存に失敗しました: {err}", type="negative")
                return
            ctx.generation.mark_job_saved(job.id, saved.id, saved.name)
            ui.notify(f"「{saved.name}」を上書き保存しました", type="positive")
            ui.navigate.to(f"/characters/{saved.id}")
        finally:
            busy["flag"] = False

    def _discard() -> None:
        if busy["flag"]:
            return
        ui.notify("修正を破棄しました(元のシートのままです)", type="info")
        ui.navigate.to(f"/characters/{base.id}")

    _render_review_page(
        name=base.name,
        old_markdown=base.raw_markdown,
        new_markdown=result.sheet_markdown,
        on_apply=_apply,
        on_discard=_discard,
    )


def _render_review_page(
    *,
    name: str,
    old_markdown: str,
    new_markdown: str,
    on_apply,
    on_discard,
) -> None:
    """章立て+章単位diff+画面下バーを描画する(グローバル/箱庭共通)。"""
    old_sections = parse_sections(old_markdown)
    new_sections = parse_sections(new_markdown)
    old_by_header: dict[str, str] = {}
    for section in old_sections:
        old_by_header.setdefault(section.header, section.body)
    new_headers = {section.header for section in new_sections}
    removed = [section for section in old_sections if section.header not in new_headers]

    with p3_page("生成"):
        ui.add_css(GENERATION_CSS + _PAGE_CSS)
        with ui.element("div").classes("review-wrap"):
            with ui.element("div").classes("review-head"):
                with ui.element("h2").classes("serif").mark("ui2-review-name"):
                    ui.html(html.escape(name))
                with ui.element("div").classes("note-line"):
                    ui.html("修正案の確認 — まだ上書きされていません。変更のある章に差分を表示しています。")
            with ui.element("div").classes("review-secs"):
                for index, section in enumerate(new_sections):
                    with ui.element("section").classes("rsec"):
                        with ui.element("span").classes("no"):
                            ui.html(kanji_number(index + 1))
                        head_html = html.escape(section.header)
                        if section.header not in old_by_header:
                            head_html += '<span class="chg">追加</span>'
                        elif old_by_header[section.header].strip() != section.body.strip():
                            head_html += '<span class="chg">変更</span>'
                        with ui.element("h3"):
                            ui.html(head_html, sanitize=False)
                        with ui.element("div").classes("bd"):
                            old_body = old_by_header.get(section.header)
                            if old_body is None:
                                ui.html(diff_html("", section.body), sanitize=False)
                            elif old_body.strip() != section.body.strip():
                                ui.html(diff_html(old_body, section.body), sanitize=False)
                            else:
                                render_section_body(section.body)
                for offset, section in enumerate(removed):
                    with ui.element("section").classes("rsec"):
                        with ui.element("span").classes("no"):
                            ui.html(kanji_number(len(new_sections) + offset + 1))
                        with ui.element("h3"):
                            ui.html(
                                html.escape(section.header) + '<span class="chg del">削除</span>',
                                sanitize=False,
                            )
                        with ui.element("div").classes("bd"):
                            ui.html(diff_html(section.body, ""), sanitize=False)

        with ui.element("div").classes("review-bar").mark("ui2-review-bar"):
            with ui.element("span").classes("msg-t"):
                ui.html(html.escape(f"この修正を「{name}」に適用しますか?"))
            p3_button("はい(上書き保存)", on_apply, classes="btn primary").mark("ui2-review-apply")
            p3_button("いいえ(破棄)", on_discard, classes="btn quiet").mark("ui2-review-discard")


@ui.page("/groups/{group_id}/generation/review/{job_id}")
async def ui2_group_generation_review_page(group_id: str, job_id: str):
    from .group_generation import (
        _clear_group_sheet_sections,
        _generation_meta,
        _member_base_markdown,
    )

    ctx = get_context()
    group = await ctx.group_chats.get(group_id)
    if group is None:
        return RedirectResponse("/groups", status_code=307)
    job = ctx.generation.get_job(job_id)
    result = job.result if job is not None else None
    if job is not None and job.saved_character_id:
        return RedirectResponse(
            f"/groups/{group_id}/members/{job.saved_character_id}", status_code=307
        )
    if (
        job is None
        or result is None
        or not result.success
        or job.request.mode != GenerationMode.MODIFY
        or not job.base_character_id
    ):
        return RedirectResponse(f"/groups/{group_id}/generation", status_code=307)
    member = next((m for m in group.members if m.id == job.base_character_id), None)
    if member is None:
        return RedirectResponse(f"/groups/{group_id}/generation", status_code=307)

    sanitized = sanitize_group_generated_markdown(result.sheet_markdown)
    busy = {"flag": False}

    async def _apply() -> None:
        if busy["flag"]:
            return
        busy["flag"] = True
        try:
            updated = sheet_from_markdown_preserving(member.character, sanitized)
            _clear_group_sheet_sections(updated, sanitized)
            updated.generation_meta = _generation_meta(job, result)
            try:
                saved = await ctx.group_chats.update_member_character(group.id, member.id, updated)
            except Exception as err:
                ui.notify(f"保存に失敗しました: {err}", type="negative")
                return
            if saved is None:
                ui.notify("グループ内キャラクターが見つかりませんでした", type="negative")
                return
            ctx.generation.mark_job_saved(job.id, saved.id, saved.character.name)
            ui.notify(f"「{saved.character.name}」を上書き保存しました", type="positive")
            ui.navigate.to(f"/groups/{group.id}/members/{saved.id}")
        finally:
            busy["flag"] = False

    def _discard() -> None:
        if busy["flag"]:
            return
        ui.notify("修正を破棄しました(元のシートのままです)", type="info")
        ui.navigate.to(f"/groups/{group.id}/members/{member.id}")

    _render_review_page(
        name=member.character.name,
        old_markdown=_member_base_markdown(member),
        new_markdown=sanitized,
        on_apply=_apply,
        on_discard=_discard,
    )
