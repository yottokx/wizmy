"""
メディア編集ページ(Phase 6)の純ロジック。

- プロンプトエディタ(色分けテキストボックス)のHTML変換と
  「候補から反映」の置き換え規則
- ボイスキャプションの整形とシート素材の組み立て
- gen_server パラメータ値の型読み取り
"""

from __future__ import annotations

import html as html_module
import re

from ..core.character.schemas import CharacterSheet

# ---------------------------------------------------------------------------
# プロンプトのタグ箱
# ---------------------------------------------------------------------------


def split_prompt_tags(text: str) -> list[str]:
    """プロンプト文字列をタグ(カンマ/改行区切り)に分解する。"""
    parts = re.split(r"[,\n]", str(text or ""))
    return [part.strip() for part in parts if part.strip()]


def join_prompt_tags(tags: list[str]) -> str:
    return ", ".join(tag.strip() for tag in tags if tag.strip())


def _tag_key(value: str) -> str:
    return re.sub(r"\s+", "_", value.strip().lower())


def dedupe_tags(tags: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        cleaned = tag.strip()
        key = _tag_key(cleaned)
        if not cleaned or key in seen:
            continue
        result.append(cleaned)
        seen.add(key)
    return result


# ---------------------------------------------------------------------------
# プロンプトエディタ(色分けテキストボックス)のHTML変換
# 候補由来の部分は <span data-wizmy-generated-prompt> で色分けされ、
# 候補を再適用するとその部分だけが置き換わる
# ---------------------------------------------------------------------------

_GENERATED_PROMPT_RE = re.compile(
    r"<(?:span|strong)\b(?=[^>]*(?:data-wizmy-generated-prompt|wizmy-generated-prompt))[^>]*>"
    r".*?</(?:span|strong)>\s*",
    re.IGNORECASE | re.DOTALL,
)

_GENERATED_NEGATIVE_PROMPT_RE = re.compile(
    r"<(?:span|strong)\b(?=[^>]*(?:data-wizmy-generated-negative-prompt|wizmy-generated-negative-prompt))[^>]*>"
    r".*?</(?:span|strong)>\s*",
    re.IGNORECASE | re.DOTALL,
)


def prompt_text_to_editor_html(value: str) -> str:
    lines = str(value or "").splitlines()
    if not lines:
        return ""
    return "<br>".join(html_module.escape(line) for line in lines)


def editor_html_to_prompt(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(?:p|div|li|h[1-6])>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html_module.unescape(text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return " ".join(lines).strip()


def _replace_generated_editor_html(
    current_html: str,
    generated_prompt: str,
    *,
    marker: str,
    css_class: str,
    pattern: re.Pattern[str],
) -> str:
    body = pattern.sub("", str(current_html or ""), count=1).lstrip()
    has_existing_prompt = bool(editor_html_to_prompt(body))
    generated_text = generated_prompt.strip()
    if not generated_text:
        return body
    if has_existing_prompt:
        generated_text = f"{generated_text}, "
    generated_html = f'<span {marker}="1" class="{css_class}">{prompt_text_to_editor_html(generated_text)}</span>'
    return f"{generated_html}{body}"


def replace_generated_prompt_html(current_html: str, generated_prompt: str) -> str:
    return _replace_generated_editor_html(
        current_html,
        generated_prompt,
        marker="data-wizmy-generated-prompt",
        css_class="wizmy-generated-prompt",
        pattern=_GENERATED_PROMPT_RE,
    )


def replace_generated_negative_prompt_html(current_html: str, generated_prompt: str) -> str:
    return _replace_generated_editor_html(
        current_html,
        generated_prompt,
        marker="data-wizmy-generated-negative-prompt",
        css_class="wizmy-generated-negative-prompt",
        pattern=_GENERATED_NEGATIVE_PROMPT_RE,
    )


def normalize_candidate_tag(value: str) -> str:
    """danbooru タグの `_` を表示用に空白へ(顔文字タグは除外)。旧 _editor_prompt_tag 相当。"""
    if value in {"o_o", "x_x", "u_u"}:
        return value
    return value.replace("_", " ")


def candidate_negative_tags(candidate: object) -> list[str]:
    """プロンプト候補のネガティブタグ一覧を返す。"""
    tags: list[str] = []
    negative_prompt = str(getattr(candidate, "negative_prompt", "") or "")
    tags.extend(part.strip() for part in negative_prompt.split(",") if part.strip())
    negative_tags = getattr(candidate, "negative_tags", []) or []
    if isinstance(negative_tags, list):
        tags.extend(normalize_candidate_tag(str(tag).strip()) for tag in negative_tags if str(tag).strip())
    return dedupe_tags(tags)


# ---------------------------------------------------------------------------
# gen_server パラメータ値の読み取り
# ---------------------------------------------------------------------------


def read_param_value(spec: dict, value: object) -> object:
    """フォーム値をフィールド仕様に従って型変換する。"""
    if spec.get("nullable") and (value is None or value == ""):
        return None

    default = spec.get("default")
    field_type = spec.get("type")
    if field_type == "boolean":
        return bool(value)
    if field_type == "integer":
        if value is None or value == "":
            return default
        return int(value)
    if field_type == "number":
        if value is None or value == "":
            return default
        return float(value)
    if field_type == "string":
        if spec.get("nullable") and not str(value or "").strip():
            return None
        return value or ""
    return value


def generated_image_size_label(image: object) -> str:
    width = int(getattr(image, "width", 0) or 0)
    height = int(getattr(image, "height", 0) or 0)
    if width > 0 and height > 0:
        return f"{width} × {height}"
    return ""


# ---------------------------------------------------------------------------
# ボイスキャプション
# ---------------------------------------------------------------------------

_VOICE_CAPTION_LABEL_RE = re.compile(
    r"^(?:voice\s*design\s*)?(?:caption|キャプション|ボイスキャプション|音声キャプション)\s*[:：]\s*",
    re.IGNORECASE,
)

_VOICE_IMAGE_SECTION_RE = re.compile(r"(?ms)^## 声のイメージ\s*\n.*?(?=^## |\Z)")


def clean_voice_caption(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^```(?:\w+)?\s*|\s*```$", "", text).strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    caption = lines[0].lstrip("-・* ").strip()
    caption = _VOICE_CAPTION_LABEL_RE.sub("", caption).strip()
    return caption.strip("「」『』\"'")


def voice_caption_sheet_source(sheet: CharacterSheet) -> str:
    """キャプション生成に渡すシート素材(「声のイメージ」章は除外)。"""
    raw_markdown = _VOICE_IMAGE_SECTION_RE.sub("", sheet.raw_markdown or "").strip()
    if raw_markdown:
        return raw_markdown

    sections: list[str] = [f"# {sheet.name or 'キャラクター'}"]
    basic_rows = [
        ("名前", sheet.name),
        ("年齢", sheet.age),
        ("性別", sheet.gender),
        ("職業・役割", sheet.occupation),
        ("出身・所属", sheet.origin),
    ]
    basic = "\n".join(f"- {label}: {value}" for label, value in basic_rows if str(value or "").strip())
    if basic:
        sections.append(f"## 基本情報\n{basic}")

    for label, value in [
        ("世界観・舞台", sheet.world),
        ("外見", sheet.appearance),
        ("性格・内面", sheet.personality),
        ("動機・目標", sheet.motivation),
        ("弱点・コンプレックス", sheet.weakness),
        ("過去・背景", sheet.background),
        ("スキル・能力", sheet.skills),
        ("個性・クセ・口癖", sheet.quirks),
        ("自己紹介台詞", sheet.self_intro),
        ("サンプル台詞", sheet.sample_dialogues),
    ]:
        text = str(value or "").strip()
        if text:
            sections.append(f"## {label}\n{text}")

    if sheet.relationships:
        relationships = "\n".join(
            f"- {rel.name}: {rel.description}".strip() for rel in sheet.relationships if (rel.name or rel.description)
        )
        if relationships:
            sections.append(f"## 人間関係\n{relationships}")

    return "\n\n".join(sections).strip()


def message_content_text(message: object) -> str:
    """LLM応答メッセージから本文テキストを取り出す。"""
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text:
                    parts.append(str(text))
        return "\n".join(parts)
    return str(content or "")
