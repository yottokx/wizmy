"""キャラクター生成結果の表示コンポーネント。"""

from __future__ import annotations

import difflib
import html as _html
import re as _re
from datetime import datetime

from nicegui import ui

from ...core.character.markdown import extract_character_name_from_markdown

_SECTION_GROUPS: dict[str, list[str]] = {
    "基本情報": ["基本情報"],
    "人物像": ["世界観・舞台", "外見", "性格・内面", "弱点・コンプレックス", "個性・クセ・口癖"],
    "背景設定": ["動機・目標", "過去・背景", "スキル・能力", "人間関係"],
    "会話設定": ["自己紹介台詞", "サンプル台詞"],
}


def _parse_sheet_md(md_text: str) -> tuple[str, dict[str, str]]:
    """Markdownのキャラクターシートをタイトルとセクション辞書に分解する。"""
    title = extract_character_name_from_markdown(md_text, default="")
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in md_text.split('\n'):
        if line.strip() == '---':
            continue
        if line.startswith('## '):
            if current is not None:
                sections[current] = '\n'.join(buf).strip()
            current = line[3:].strip()
            buf = []
        elif line.startswith('# '):
            continue
        elif current is not None:
            buf.append(line)
    if current is not None:
        sections[current] = '\n'.join(buf).strip()
    return title, sections


def show_sheet_placeholder(result_area: ui.element) -> None:
    """空の状態プレースホルダーを実際のシート構造に即した形で表示する。"""
    # 実際の出力テンプレートに基づくグループ・フィールド構成
    _BASIC_FIELDS = ["名前", "年齢", "性別", "職業・役割", "出身・所属"]
    _LEFT_GROUPS = [
        ("人物像", ["世界観・舞台", "外見", "性格・内面", "弱点・コンプレックス", "個性・クセ・口癖"]),
    ]
    _RIGHT_GROUPS = [
        ("背景設定", ["動機・目標", "過去・背景", "スキル・能力"]),
    ]
    _CONV_FIELDS = ["自己紹介台詞", "サンプル台詞"]

    def _dash_row(label: str, min_width: str = "90px") -> str:
        return (
            f'<div style="display:flex;gap:8px;margin-bottom:4px;align-items:baseline;">'
            f'<span class="cs-sheet-field-label" style="min-width:{min_width};margin-top:0;">{label}</span>'
            f'<span class="cs-placeholder-dash">—</span>'
            f'</div>'
        )

    result_area.clear()
    with result_area:
        # キャラクター名ヘッダー相当
        ui.html(
            '<div style="margin-bottom:16px;padding-bottom:12px;border-bottom:2px solid var(--cs-accent-bg);">'
            '<span style="font-size:1.1rem;font-weight:700;color:var(--cs-border);">キャラクター名</span>'
            '</div>'
        )

        # 基本情報（全幅テーブル相当）
        with ui.element("div").style("margin-bottom: 18px;"):
            ui.html('<div class="cs-sheet-section-title">基本情報</div>')
            basic_html = "".join(_dash_row(f, "90px") for f in _BASIC_FIELDS)
            ui.html(f'<div style="padding: 2px 0;">{basic_html}</div>')

        # 人物像 + 背景設定（2カラム）
        with ui.element("div").style("display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px;"):
            for groups in [_LEFT_GROUPS, _RIGHT_GROUPS]:
                with ui.element("div"):
                    for group_name, fields in groups:
                        ui.html(f'<div class="cs-sheet-section-title">{group_name}</div>')
                        for field in fields:
                            ui.html(
                                f'<div style="margin-bottom: 8px;">'
                                f'<div class="cs-sheet-field-label">{field}</div>'
                                f'<span class="cs-placeholder-dash" style="font-size:0.82rem;">—</span>'
                                f'</div>'
                            )

        # 会話設定（全幅・背景あり）
        with ui.element("div").style(
            "background: var(--cs-surface-soft); border: 1px solid var(--cs-border); border-radius: 10px; padding: 14px;"
        ):
            ui.html('<div class="cs-sheet-section-title">会話設定</div>')
            for field in _CONV_FIELDS:
                ui.html(
                    f'<div style="margin-bottom: 8px;">'
                    f'<div class="cs-sheet-field-label">{field}</div>'
                    f'<span class="cs-placeholder-dash" style="font-size:0.82rem;">—</span>'
                    f'</div>'
                )


def render_sheet_result(result_area: ui.element, md_text: str) -> None:
    """生成されたキャラクターシートをセクション別に整形して表示する。"""
    title, sections = _parse_sheet_md(md_text)
    result_area.clear()
    with result_area:
        # キャラクター名ヘッダー
        if title:
            with ui.element("div").style(
                "margin-bottom: 16px; padding-bottom: 12px; border-bottom: 2px solid var(--cs-accent-bg);"
            ):
                ui.label(title).style("font-size: 1.2rem; font-weight: 700; color: var(--cs-text);")

        # 基本情報 (全幅テーブル)
        basic = sections.get("基本情報", "")
        if basic:
            with ui.element("div").style("margin-bottom: 18px;"):
                ui.html('<div class="cs-sheet-section-title">基本情報</div>')
                ui.markdown(basic).classes("prose prose-sm max-w-none")

        # 人物像 + 背景設定 (2カラム)
        with ui.element("div").style("display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px;"):
            for group in ["人物像", "背景設定"]:
                group_data = [(s, sections[s]) for s in _SECTION_GROUPS[group] if s in sections and sections[s]]
                if not group_data:
                    continue
                with ui.element("div"):
                    ui.html(f'<div class="cs-sheet-section-title">{group}</div>')
                    for sec_name, content in group_data:
                        ui.html(f'<div class="cs-sheet-field-label">{sec_name}</div>')
                        ui.markdown(content).classes("prose prose-sm max-w-none")

        # 会話設定 (全幅・背景あり)
        conv_data = [(s, sections[s]) for s in _SECTION_GROUPS["会話設定"] if s in sections and sections[s]]
        if conv_data:
            with ui.element("div").style(
                "background: var(--cs-surface-soft); border: 1px solid var(--cs-border); "
                "border-radius: 10px; padding: 14px;"
            ):
                ui.html('<div class="cs-sheet-section-title">会話設定</div>')
                for sec_name, content in conv_data:
                    ui.html(f'<div class="cs-sheet-field-label">{sec_name}</div>')
                    ui.markdown(content).classes("prose prose-sm max-w-none")


def build_generation_log(result, mode_str: str, sheet_md: str = "", request=None, profile=None) -> str:
    """全候補・モデル情報・ユーザー指示を含む詳細ログテキストを生成する。"""
    _mode_names = {"generate": "新規生成", "modify": "修正", "related": "関連キャラ生成"}
    lines = [
        "=== キャラクター生成 詳細ログ ===",
        f"生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"モード  : {_mode_names.get(mode_str, mode_str)}",
        f"品質    : {result.quality_status}  スコア: {result.quality_score:.2f}",
        f"ツール呼び出し: {result.tool_count} 件",
        "",
    ]

    # ─ 使用モデル ─
    if profile:
        lines += [
            "━" * 60,
            "使用モデル",
            "━" * 60,
            f"プロファイル : {profile.name}",
            f"モデルID     : {profile.model_id}",
        ]
        if profile.reasoning_enabled:
            lines.append("推論モード   : 有効")
        else:
            lines.append(f"Temperature  : {profile.temperature}")
        if getattr(profile, "max_tokens", None):
            lines.append(f"最大トークン : {profile.max_tokens}")
        lines.append("")

    # ─ ユーザー指示 ─
    if request:
        lines += [
            "━" * 60,
            "ユーザー指示",
            "━" * 60,
        ]
        p = request.preferences
        for label, val in [
            ("世界観", p.world),
            ("年齢帯", p.age),
            ("性別", p.gender),
            ("テーマ", p.theme),
            ("追加要望", p.extra),
        ]:
            if val and val != "おまかせ":
                lines.append(f"{label:6s}: {val}")
        if request.modify_request:
            lines.append(f"修正指示: {request.modify_request}")
        if request.base_sheet:
            lines.append("ベースキャラクター: あり（ベースシートは省略）")
        lines.append("")

    # ─ Stage1 詳細 ─
    lines += [
        "━" * 60,
        "Stage 1: ブレインストーミング詳細",
        "━" * 60,
        "",
    ]
    for i, tc in enumerate(result.tool_calls, 1):
        lines.append(f"[{i:02d}] {tc.tool_name}")
        lines.append(f"  結果: {tc.result}")
        if tc.all_options:
            m = _re.search(r'「(.+?)」', tc.result)
            selected = m.group(1) if m else ""
            lines.append(f"  全候補 ({len(tc.all_options)} 件):")
            for j, opt in enumerate(tc.all_options, 1):
                marker = " ◀ 選択" if opt == selected else ""
                lines.append(f"    {j:2d}. {opt}{marker}")
        lines.append("")

    if sheet_md:
        lines += [
            "━" * 60,
            "生成されたシート",
            "━" * 60,
            "",
            sheet_md,
        ]
    return "\n".join(lines)


def build_diff_html(old_text: str, new_text: str) -> str:
    """2つのMarkdownを行単位で比較し、差分をHTML形式で返す。"""
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm="", n=2))
    if not diff:
        return "<p style='color:#6b7280;font-style:italic;padding:8px;'>変更なし</p>"
    parts = [
        "<div style='font-family:monospace;font-size:12px;line-height:1.6;white-space:pre-wrap;word-break:break-all;'>"
    ]
    for line in diff:
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("@@"):
            parts.append(
                f"<div style='color:#6b7280;background:#f3f4f6;"
                f"padding:2px 6px;border-radius:3px;margin:4px 0;'>{_html.escape(line)}</div>"
            )
        elif line.startswith("+"):
            parts.append(
                f"<div style='background:#dcfce7;color:#166534;padding:1px 6px;'>+ {_html.escape(line[1:])}</div>"
            )
        elif line.startswith("-"):
            parts.append(
                f"<div style='background:#fee2e2;color:#991b1b;padding:1px 6px;'>- {_html.escape(line[1:])}</div>"
            )
        else:
            text = line[1:] if line.startswith(" ") else line
            parts.append(f"<div style='color:#9ca3af;padding:1px 6px;'>&nbsp; {_html.escape(text)}</div>")
    parts.append("</div>")
    return "".join(parts)


async def open_modify_approve_dialog(
    char_name: str,
    diff_html: str,
    save_fn,
    save_status_label,
) -> None:
    """修正差分確認ダイアログ。承認で save_fn() を呼び出す。"""
    with ui.dialog() as dlg, ui.card().classes("w-[700px] max-w-[95vw]"):
        with ui.row().classes("items-center gap-2 mb-1"):
            ui.icon("difference").classes("text-primary text-2xl")
            ui.label("修正内容の確認").classes("text-lg font-semibold")
        ui.label(f"「{char_name}」への変更内容を確認してください。 赤字が削除箇所、緑字が追加箇所です。").classes(
            "text-sm text-grey-7 mb-3"
        )

        with ui.scroll_area().style("height:55vh;width:100%"):
            ui.html(diff_html)

        with ui.row().classes("justify-end gap-2 mt-4"):

            async def _reject():
                ui.notify("修正を破棄しました", type="info")
                dlg.close()

            async def _approve():
                dlg.close()
                try:
                    await save_fn()
                    save_status_label.set_text(f"更新済み: {char_name}")
                    save_status_label.classes(remove="hidden")
                    ui.notify(f"「{char_name}」を上書き保存しました", type="positive")
                except Exception as err:
                    ui.notify(f"保存に失敗しました: {err}", type="negative")

            ui.button("破棄", icon="close", on_click=_reject).props("flat color=negative")
            ui.button("承認して上書き", icon="check", on_click=_approve).props("color=primary unelevated")
    dlg.open()
