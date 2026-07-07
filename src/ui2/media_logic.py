"""
メディア編集ページ(Phase 6)の純ロジック。

- プロンプトのタグ分解/結合と「候補から反映」の置き換え規則
  (旧 `character_media_image.py` の _replace_generated_prompt_html 相当を
  タグ提供元(プロファイル由来 / 候補由来)の見える化として再設計)
- ボイスキャプションの整形とシート素材の組み立て
  (旧 `character_media_voice.py` から複製。§1-2 の規則により import しない)
- gen_server パラメータ値の型読み取り(旧 _read_gen_server_param_value 相当)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

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


@dataclass
class PromptTagBox:
    """提供元つきのプロンプトタグ集合。

    - base: プロファイル由来+手入力タグ
    - generated: 「候補から反映」されたタグ(候補を再適用すると丸ごと置き換わる。
      旧UIの _replace_generated_prompt_html と同じ挙動の見える化)
    """

    base: list[str] = field(default_factory=list)
    generated: list[str] = field(default_factory=list)

    @classmethod
    def from_profile(cls, prompt: str) -> "PromptTagBox":
        return cls(base=dedupe_tags(split_prompt_tags(prompt)))

    def add(self, text: str) -> None:
        for tag in split_prompt_tags(text):
            if _tag_key(tag) not in {_tag_key(t) for t in self.base + self.generated}:
                self.base.append(tag)

    def remove(self, tag: str, *, generated: bool) -> None:
        target = self.generated if generated else self.base
        key = _tag_key(tag)
        for item in list(target):
            if _tag_key(item) == key:
                target.remove(item)

    def apply_candidate(self, candidate_prompt: str) -> None:
        """候補プロンプトを反映する(候補由来タグだけを置き換える)。"""
        base_keys = {_tag_key(t) for t in self.base}
        self.generated = [
            tag for tag in dedupe_tags(split_prompt_tags(candidate_prompt)) if _tag_key(tag) not in base_keys
        ]

    def prompt(self) -> str:
        return join_prompt_tags(self.base + self.generated)


def normalize_candidate_tag(value: str) -> str:
    """danbooru タグの `_` を表示用に空白へ(顔文字タグは除外)。旧 _editor_prompt_tag 相当。"""
    if value in {"o_o", "x_x", "u_u"}:
        return value
    return value.replace("_", " ")


def candidate_negative_tags(candidate: object) -> list[str]:
    """プロンプト候補のネガティブタグ一覧を返す。旧 _candidate_negative_tags の複製。"""
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
    """フォーム値をフィールド仕様に従って型変換する(旧 _read_gen_server_param_value の複製)。"""
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
# ボイスキャプション(旧 character_media_voice.py から複製)
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
    """LLM応答メッセージから本文テキストを取り出す(旧 _message_content_text の複製)。"""
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
