"""core/character/markdown.py のセクション操作の回帰テスト。"""

from __future__ import annotations

from src.core.character.markdown import remove_markdown_section, replace_markdown_section

_BASE_MD = """# テストキャラ

## 過去・背景
古い内容

## 性格・内面
穏やか。"""


def test_replace_markdown_section_replaces_body() -> None:
    result = replace_markdown_section(_BASE_MD, "過去・背景", "新しい内容")

    assert "## 過去・背景\n新しい内容" in result
    assert "古い内容" not in result
    assert "## 性格・内面\n穏やか。" in result


def test_replace_markdown_section_appends_missing_section() -> None:
    result = replace_markdown_section(_BASE_MD, "スキル・能力", "- 剣術")

    assert result.endswith("## スキル・能力\n- 剣術")


def test_replace_markdown_section_keeps_backslashes_verbatim() -> None:
    """本文の \\ や \\1 が正規表現の置換記法として解釈されない(クラッシュ・破損の回帰)。"""
    windows_path = replace_markdown_section(_BASE_MD, "過去・背景", r"パスは C:\Users\yotto に保存")
    assert r"パスは C:\Users\yotto に保存" in windows_path

    group_ref = replace_markdown_section(_BASE_MD, "過去・背景", r"価格は \100 です")
    assert r"価格は \100 です" in group_ref


def test_remove_markdown_section_removes_only_target() -> None:
    result = remove_markdown_section(_BASE_MD, "過去・背景")

    assert "過去・背景" not in result
    assert "## 性格・内面" in result
