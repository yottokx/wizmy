"""LLMとタグ辞書を使ってDanbooruタグプロンプト候補を作る。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from ..character.schemas import CharacterSheet
from .tag_dictionary import (
    LOWER_BODY_CATEGORY,
    DanbooruTagDictionary,
    TagRecord,
    normalize_tag,
)

FIXED_ALLOWED_TAGS = {
    "1boy",
    "1girl",
    "1other",
    "solo",
}
AGE_TAGS = {
    "baby",
    "loli",
    "shota",
    "child",
    "mature_female",
    "mature_male",
    "old",
    "old_woman",
}
WORLD_TAG_KEYWORDS = {
    "military": ("military", "軍", "兵士", "戦争", "部隊"),
    "fantasy": ("fantasy", "ファンタジー", "魔法", "魔術", "冒険者"),
    "ancient_egyptian": ("ancient egyptian", "ancient_egyptian", "エジプト"),
    "cyberpunk": ("cyberpunk", "サイバーパンク", "電脳", "義体"),
    "post-apocalypse": ("post-apocalypse", "post apocalypse", "終末", "荒廃"),
    "steampunk": ("steampunk", "スチームパンク", "蒸気"),
    "medieval": ("medieval", "中世", "騎士", "王国"),
}
IDENTITY_CATEGORIES = {
    "年齢/世代",
    "種族/身体特徴",
    "肌の色",
    "体形",
}
HAIR_COLOR_CATEGORY = "髪/髪の色"
EYE_COLOR_CATEGORY = "目/目の色"
OCCUPATION_CATEGORY = "職業/役割/キャラ属性"
EXPRESSION_CATEGORIES = [
    "表情/全体",
    "表情/口元の表情",
    "表情/目元の表情",
    "表情/頬/顔色",
    "表情/涙/汗/反応",
    "表情/その他",
]
VISUAL_DETAIL_CATEGORIES = [
    "髪/髪の長さ",
    HAIR_COLOR_CATEGORY,
    "髪/前髪のスタイル",
    "髪/髪の結び方/編み方",
    "髪/髪質(ストレート・ウェーブ等)",
    "髪/その他ヘアスタイルに関する事柄",
    "髪/上記に該当しないもの",
    "髪/ヘアアクセサリー",
    "ヘアアクセサリー",
    EYE_COLOR_CATEGORY,
    "目/瞳孔の形",
    "目/その他",
    *EXPRESSION_CATEGORIES,
    "その他の顔の特徴/メイク",
    "その他の顔の特徴/髭",
    "その他の顔の特徴/その他",
]


class DanbooruPromptLLM(Protocol):
    """JSONを返すLLM呼び出し口。"""

    async def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """system/userプロンプトを受け取り、JSONオブジェクトを返す。"""


class LangChainDanbooruPromptLLM:
    """LangChainのChatModelをDanbooruPromptLLMとして使うアダプタ。"""

    def __init__(self, llm: Any) -> None:
        self._llm = llm

    async def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        from langchain_core.messages import HumanMessage, SystemMessage

        response = await self._llm.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
        )
        return parse_json_object(_message_text(response))


@dataclass(frozen=True)
class DanbooruPromptCandidate:
    prompt: str
    fixed_tags: list[str]
    variant_tags: list[str]
    negative_tags: list[str] = field(default_factory=list)
    negative_prompt: str = ""
    freeform_anchor_tags: list[str] = field(default_factory=list)
    freeform_tags: list[str] = field(default_factory=list)
    dropped_tags: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    label: str = ""


@dataclass(frozen=True)
class DanbooruPromptDebugResult:
    candidates: list[DanbooruPromptCandidate]
    fixed_tags: list[str]
    appearance_anchor_tags: list[str]
    freeform_anchor_tags: list[str]
    negative_tags: list[str]
    anchor_policy: dict[str, Any]
    search_policy: dict[str, Any]
    candidate_pool: dict[str, list[str]]
    tag_guide: dict[str, object]


class DanbooruPromptGenerator:
    """タグ辞書をLLMに見せ、候補プール抽出と最終検証を行う。"""

    def __init__(
        self,
        tag_dictionary: DanbooruTagDictionary,
        llm: DanbooruPromptLLM,
    ) -> None:
        self.tag_dictionary = tag_dictionary
        self.llm = llm

    async def generate_with_debug(
        self,
        sheet: CharacterSheet,
        *,
        count: int = 3,
        seed: int | None = None,
    ) -> DanbooruPromptDebugResult:
        count = max(1, min(8, int(count)))
        person_tag = _infer_person_tag(sheet)
        appearance_anchor_tags = self._appearance_anchor_tags(sheet)
        fixed_tags = _dedupe_tags([*self._fixed_tags(sheet), *appearance_anchor_tags])
        age_style_anchor_tags, _ = _sanitize_freeform_tags(
            _age_style_anchor_tags(sheet),
            known_tags=set(fixed_tags),
            limit=2,
        )
        negative_tags = _age_negative_tags(sheet, person_tag)
        tag_guide = self.tag_dictionary.build_llm_tag_guide()

        anchor_policy = await self.llm.complete_json(
            ANCHOR_SYSTEM_PROMPT,
            self._build_anchor_prompt(sheet, fixed_tags, tag_guide),
        )
        anchor_policy = _normalize_anchor_policy(anchor_policy)
        appearance_anchor_tags = _dedupe_tags(
            [
                *appearance_anchor_tags,
                *self._anchor_tags_from_policy(anchor_policy),
            ]
        )
        fixed_tags = _dedupe_tags([*fixed_tags, *appearance_anchor_tags])
        policy_freeform_anchor_tags, _ = _sanitize_freeform_tags(
            anchor_policy.get("freeform_feature_hints"),
            known_tags=set(fixed_tags),
            limit=8,
        )
        freeform_anchor_tags = _dedupe_freeform_tags(
            [
                *age_style_anchor_tags,
                *policy_freeform_anchor_tags,
            ]
        )

        search_policy = await self.llm.complete_json(
            SEARCH_POLICY_SYSTEM_PROMPT,
            self._build_search_policy_prompt(
                sheet,
                fixed_tags,
                freeform_anchor_tags,
                tag_guide,
                count,
                seed,
            ),
        )
        search_policy = _normalize_policy(search_policy)
        appearance_anchor_tags = _dedupe_tags(
            [
                *appearance_anchor_tags,
                *self._anchor_tags_from_policy(search_policy),
            ]
        )
        fixed_tags = _dedupe_tags([*fixed_tags, *appearance_anchor_tags])
        search_policy_hints = search_policy.get("freeform_feature_hints", [])

        candidate_pool = self.tag_dictionary.select_candidate_pool(search_policy)
        proposal = await self.llm.complete_json(
            CANDIDATE_SYSTEM_PROMPT,
            self._build_candidate_prompt(
                sheet,
                fixed_tags,
                search_policy,
                candidate_pool,
                tag_guide,
                self._visual_detail_guide(),
                appearance_anchor_tags,
                freeform_anchor_tags,
                search_policy_hints,
                count,
                seed,
            ),
        )

        candidates = self._validate_candidates(
            proposal,
            fixed_tags=fixed_tags,
            freeform_anchor_tags=freeform_anchor_tags,
            candidate_pool=candidate_pool,
            negative_tags=negative_tags,
            count=count,
        )
        return DanbooruPromptDebugResult(
            candidates=candidates,
            fixed_tags=fixed_tags,
            appearance_anchor_tags=appearance_anchor_tags,
            freeform_anchor_tags=freeform_anchor_tags,
            negative_tags=negative_tags,
            anchor_policy=anchor_policy,
            search_policy=search_policy,
            candidate_pool=candidate_pool,
            tag_guide=tag_guide,
        )

    async def generate_danbooru_prompt_candidates(
        self,
        sheet: CharacterSheet,
        *,
        count: int = 3,
        seed: int | None = None,
    ) -> list[DanbooruPromptCandidate]:
        result = await self.generate_with_debug(sheet, count=count, seed=seed)
        return result.candidates

    def _fixed_tags(self, sheet: CharacterSheet) -> list[str]:
        text = _sheet_text(sheet)
        person_tag = _infer_person_tag(sheet)
        fixed = [person_tag, "solo"]

        fixed.extend(_infer_age_tags(sheet, person_tag))
        fixed.extend(self._infer_world_tags(text))
        fixed.extend(self.tag_dictionary.match_tags([OCCUPATION_CATEGORY], _identity_text(sheet), limit=3))
        fixed.extend(self._infer_species_and_body_features(sheet))
        fixed.extend(self._infer_skin_tags(sheet))
        fixed.extend(self.tag_dictionary.match_tags(["体形"], sheet.appearance, limit=2))
        fixed.extend(self.tag_dictionary.match_tags(["髪/髪の長さ", HAIR_COLOR_CATEGORY], sheet.appearance, limit=3))
        fixed.extend(self.tag_dictionary.match_tags([EYE_COLOR_CATEGORY, "目/瞳孔の形"], sheet.appearance, limit=3))
        return _dedupe_tags(fixed)

    def _infer_world_tags(self, text: str) -> list[str]:
        normalized = _normalize_text(text)
        tags: list[str] = []
        for tag, keywords in WORLD_TAG_KEYWORDS.items():
            if not self._is_known_or_fixed(tag):
                continue
            if any(_normalize_text(keyword) in normalized for keyword in keywords):
                tags.append(tag)
        return tags

    def _infer_species_and_body_features(self, sheet: CharacterSheet) -> list[str]:
        text = f"{sheet.origin}\n{sheet.world}\n{sheet.appearance}\n{sheet.raw_markdown}"
        if _looks_like_plain_human(text):
            return []
        return self.tag_dictionary.match_tags(["種族/身体特徴"], text, limit=6)

    def _infer_skin_tags(self, sheet: CharacterSheet) -> list[str]:
        text = sheet.appearance or sheet.raw_markdown
        matches = self.tag_dictionary.match_tags(["肌の色"], text, limit=3)
        if not matches:
            return []
        if _looks_like_plain_human(_sheet_text(sheet)):
            return _dedupe_tags([tag for tag in matches if tag in {"pale_skin", "tan", "dark_skin"}])
        return _dedupe_tags(matches)

    def _build_anchor_prompt(
        self,
        sheet: CharacterSheet,
        fixed_tags: list[str],
        tag_guide: dict[str, object],
    ) -> str:
        return f"""\
## キャラクターシート
{_sheet_text(sheet)}

## すでに固定されているタグ
{json.dumps(fixed_tags, ensure_ascii=False)}

## タグ辞書ガイド
{json.dumps(tag_guide, ensure_ascii=False, indent=2)}

## 依頼
- キャラクターシートに明記された「全候補で絶対に変えてはいけない外見・持ち物・服の状態・肌色・髪・目・顔・表情」のアンカーだけを抽出してください。
- CSVタグで表せそうなものは required_tags または required_tag_terms に入れてください。
- required_tag_terms は日本語表現を英語のDanbooru風検索語へ翻訳してください。タグが曖昧なときは複数の短い検索語を入れてください。
- CSVタグで表しにくいが全候補で残すべきものは freeform_feature_hints に入れてください。
- 表情や雰囲気は、この段階では「全候補共通で固定すべきもの」だけ入れてください。候補ごとの差分表情は入れないでください。
- 出力はJSONのみです。

## JSON形式
{{
  "required_tags": ["pale_skin"],
  "required_tag_terms": ["robe", "pouch", "messy hair"],
  "freeform_feature_hints": ["dusty clothes", "large leather book bag on shoulder"],
  "reason": "短い理由"
}}
"""

    def _build_search_policy_prompt(
        self,
        sheet: CharacterSheet,
        fixed_tags: list[str],
        freeform_anchor_tags: list[str],
        tag_guide: dict[str, object],
        count: int,
        seed: int | None,
    ) -> str:
        return f"""\
## キャラクターシート
{_sheet_text(sheet)}

## コードが固定したタグ
{json.dumps(fixed_tags, ensure_ascii=False)}

## すでに固定済みの自由特徴アンカー
{json.dumps(freeform_anchor_tags, ensure_ascii=False)}

## タグ辞書ガイド
{json.dumps(tag_guide, ensure_ascii=False, indent=2)}

## 依頼
- キャラ崩壊を避けるため、服装・アクセサリー・髪飾り・表情を中心に候補プール検索方針を作ってください。
- キャラクターシートに明記された外見、持ち物、服の状態、肌色、髪、目、顔の特徴は必須アンカーとして抽出してください。
- 必須アンカーのうちCSVタグで表せそうなものは required_tags または required_tag_terms に入れてください。
- required_tag_terms は日本語キャラクターシートから英語のDanbooru風検索語へ翻訳してください。例: 青白い肌 -> pale skin、ローブ -> robe、書物袋/革袋 -> belt pouch または pouch。
- CSVタグで表しにくい必須アンカーは freeform_feature_hints に入れてください。
- 髪・目・顔・表情はキャラの性格を反映する重要領域として、検索語や方針に含めてください。
- 表情カテゴリもCSVに分類済みなので、タグで表せそうな表情・目つき・口元・頬/顔色・涙/汗/反応は検索語やinclude_categoriesに含めてください。
- 一部の目や顔の関係タグは「目」や「その他の顔の特徴」ではなく「表情」配下に分類されています。
- 小カテゴリはタグ一覧を直接見てよいです。
- 大カテゴリは代表タグと頻出トークンを見て、検索語を選んでください。
- 正規タグにしにくいが画像に反映したいキャラクターシートの重要特徴や表情のニュアンスだけを freeform_feature_hints に入れてください。
- ボトムス、履き物、下半身、下着、過度な露出、版権固有衣装、alternate系は避けてください。
- 出力はJSONのみです。
- 候補数: {count}
- seed: {"" if seed is None else seed}

## JSON形式
{{
  "include_categories": ["服装/トップス", "服装/ヘッドウェア", "アクセサリー(髪以外に付けるもの)", "表情/全体", "表情/目元の表情"],
  "search_terms": ["shirt", "jacket", "gloves", "smile", "gaze"],
  "required_tags": ["pale_skin"],
  "required_tag_terms": ["robe", "belt pouch"],
  "avoid_terms": ["boots", "bikini", "alternate"],
  "style_directions": ["標準衣装", "個性強め", "日常寄り"],
  "freeform_feature_hints": ["dusty clothes", "leather book bag on shoulder", "quiet analytical gaze"],
  "reason": "短い理由"
}}
"""

    def _build_candidate_prompt(
        self,
        sheet: CharacterSheet,
        fixed_tags: list[str],
        search_policy: dict[str, Any],
        candidate_pool: dict[str, list[str]],
        tag_guide: dict[str, object],
        visual_detail_guide: list[dict[str, object]],
        appearance_anchor_tags: list[str],
        freeform_anchor_tags: list[str],
        search_policy_hints: list[str],
        count: int,
        seed: int | None,
    ) -> str:
        small_categories = tag_guide.get("small_categories", [])
        return f"""\
## キャラクターシート
{_sheet_text(sheet)}

## 必ず維持する固定タグ
{json.dumps(fixed_tags, ensure_ascii=False)}

## 全候補で絶対に変えない外見アンカー
{json.dumps(appearance_anchor_tags, ensure_ascii=False)}

## 全候補で必ず入れる自由特徴アンカー
{json.dumps(freeform_anchor_tags, ensure_ascii=False)}

## 検索方針
{json.dumps(search_policy, ensure_ascii=False, indent=2)}

## 今回使ってよい大量カテゴリ由来の候補タグ
{json.dumps(candidate_pool, ensure_ascii=False, indent=2)}

## 小カテゴリのタグ一覧
{json.dumps(small_categories, ensure_ascii=False, indent=2)}

## 髪・目・顔・表情に使いやすい正規タグ
{json.dumps(visual_detail_guide, ensure_ascii=False, indent=2)}

## 正規タグで表しにくい重要特徴・表情のヒント
{json.dumps(search_policy_hints, ensure_ascii=False, indent=2)}

## 依頼
- 固定タグは変更しないでください。
- 全候補で絶対に変えない外見アンカーは、標準衣装・個性強め・日常寄りの全案に必ず残してください。
- 全候補で必ず入れる自由特徴アンカーは、標準衣装・個性強め・日常寄りの全案に必ず残る前提です。candidate別のfreeform_tagsで置き換えないでください。
- 候補ごとに、胸上コーデ、髪・目・顔・アクセサリー中心で個性を出してください。
- 髪は長さ、髪色、前髪、結び方、髪質、その他の髪特徴、ヘアアクセサリーをできるだけ細かく検討してください。
- 目は目色、瞳孔、目つき、まつげ、隈、視線の印象などを検討してください。
- 顔はメイク、眉、赤面、ほくろ、傷、そばかす、口元などを検討してください。
- 表情カテゴリもCSV由来の正規タグとしてvariant_tagsで使ってください。
- 目つきや顔の関係タグの一部は表情カテゴリへ分類されています。「目/その他」や「その他の顔の特徴」だけでなく表情カテゴリも確認してください。
- 性格が出る表情や雰囲気は、まず表情カテゴリの正規タグで表してください。
- freeform_tagsには、正規タグで表しきれない候補ごとの表情・雰囲気ニュアンスだけを1案あたり0〜2個入れてください。全候補共通にしたい外見・設定特徴は自由特徴アンカー側にあります。
- 種族、年齢、肌色、体形、髪色、目色はキャラクターシートと固定タグに反しないでください。
- 服装タグは1案あたり2〜5個までを目安にしてください。
- 正規タグでは表しにくいキャラクターシートの重要特徴も freeform_tags に入れてください。
- freeform_tags はDanbooru正規タグでなくて構いませんが、画像生成プロンプトとして自然な短い英語または日本語のフレーズにしてください。
- 候補同士が完全に同じタグ列にならないようにしてください。
- variant_tags はCSVにありそうなDanbooruタグのみを使ってください。
- 出力はJSONのみです。
- 候補数: {count}
- seed: {"" if seed is None else seed}

## JSON形式
{{
  "candidates": [
    {{
      "label": "標準衣装",
      "variant_tags": ["black_jacket", "collared_shirt", "glasses", "smile"],
      "freeform_tags": ["quiet analytical mood"],
      "note": "短い理由"
    }}
  ]
}}
"""

    def _validate_candidates(
        self,
        proposal: dict[str, Any],
        *,
        fixed_tags: list[str],
        freeform_anchor_tags: list[str],
        candidate_pool: dict[str, list[str]],
        negative_tags: list[str],
        count: int,
    ) -> list[DanbooruPromptCandidate]:
        raw_candidates = proposal.get("candidates")
        if not isinstance(raw_candidates, list):
            raw_candidates = []

        fixed_set = set(fixed_tags)
        seen_prompts: set[str] = set()
        candidates: list[DanbooruPromptCandidate] = []
        for index, raw in enumerate(raw_candidates[:count], start=1):
            if not isinstance(raw, Mapping):
                continue
            label = str(raw.get("label") or f"候補{index}")
            known_freeform_tags = self._known_tags_from_freeform(raw.get("freeform_tags"))
            raw_tags = (
                _flatten_tags(raw.get("fixed_tags")) + _flatten_tags(raw.get("variant_tags")) + known_freeform_tags
            )
            variant_tags, dropped_tags, warnings = self._sanitize_variant_tags(raw_tags, fixed_set)
            variant_tags = _dedupe_tags(variant_tags)
            freeform_tags, freeform_warnings = _sanitize_freeform_tags(
                raw.get("freeform_tags"),
                known_tags=set(fixed_tags)
                | set(variant_tags)
                | {normalize_tag(tag) for tag in freeform_anchor_tags}
                | set(known_freeform_tags),
            )
            warnings.extend(freeform_warnings)
            prompt_tags = _dedupe_tags([*fixed_tags, *variant_tags])
            prompt = _join_prompt_parts(prompt_tags, freeform_anchor_tags, freeform_tags)
            negative_prompt = _join_prompt_tags(negative_tags)
            if prompt in seen_prompts:
                extra = self._find_safe_difference_tag(candidate_pool, set(prompt_tags))
                if extra:
                    variant_tags.append(extra)
                    prompt_tags.append(extra)
                    prompt = _join_prompt_parts(prompt_tags, freeform_anchor_tags, freeform_tags)
                    warnings.append(f"重複候補を避けるため {extra} を追加しました。")
                else:
                    warnings.append("候補同士の完全一致を解消できませんでした。")
            seen_prompts.add(prompt)
            candidates.append(
                DanbooruPromptCandidate(
                    prompt=prompt,
                    fixed_tags=list(fixed_tags),
                    variant_tags=variant_tags,
                    negative_tags=list(negative_tags),
                    negative_prompt=negative_prompt,
                    freeform_anchor_tags=freeform_anchor_tags,
                    freeform_tags=freeform_tags,
                    dropped_tags=dropped_tags,
                    warnings=warnings,
                    label=label,
                )
            )

        return candidates

    def _known_tags_from_freeform(self, value: object) -> list[str]:
        tags: list[str] = []
        for raw_tag in _flatten_freeform_tags(value):
            normalized = normalize_tag(_clean_freeform_tag(raw_tag))
            if normalized and self.tag_dictionary.has_tag(normalized):
                tags.append(normalized)
        return tags

    def _sanitize_variant_tags(
        self,
        raw_tags: list[str],
        fixed_set: set[str],
    ) -> tuple[list[str], list[str], list[str]]:
        variant_tags: list[str] = []
        dropped_tags: list[str] = []
        warnings: list[str] = []
        fixed_hair_colors = self._fixed_category_tags(fixed_set, HAIR_COLOR_CATEGORY)
        fixed_eye_colors = self._fixed_category_tags(fixed_set, EYE_COLOR_CATEGORY)

        for raw_tag in raw_tags:
            tag = normalize_tag(raw_tag)
            if not tag or tag in fixed_set:
                continue

            record = self.tag_dictionary.get(tag)
            if record is None and tag not in FIXED_ALLOWED_TAGS:
                dropped_tags.append(tag)
                warnings.append(f"CSVにないタグを除外しました: {tag}")
                continue
            if record is None:
                continue
            reason = self._drop_reason(record, fixed_set, fixed_hair_colors, fixed_eye_colors)
            if reason:
                dropped_tags.append(tag)
                warnings.append(f"{reason}: {tag}")
                continue
            variant_tags.append(tag)

        return variant_tags, dropped_tags, warnings

    def _drop_reason(
        self,
        record: TagRecord,
        fixed_set: set[str],
        fixed_hair_colors: set[str],
        fixed_eye_colors: set[str],
    ) -> str:
        if self.tag_dictionary.is_noise_tag(record.tag):
            return "ノイズタグを除外しました"
        if self.tag_dictionary.is_emoticon_tag(record.tag):
            return "顔文字タグを除外しました"
        if self.tag_dictionary.should_exclude_from_prompt(record):
            if LOWER_BODY_CATEGORY in record.categories:
                return "下半身・履き物寄りのタグを除外しました"
            return "不向きな服装タグを除外しました"
        if IDENTITY_CATEGORIES & set(record.categories) and record.tag not in fixed_set:
            if "肌の色" in record.categories:
                fixed_skin_tags = self._fixed_category_tags(fixed_set, "肌の色")
                if not fixed_skin_tags:
                    return ""
            return "固定アイデンティティを変えるタグを除外しました"
        if (
            OCCUPATION_CATEGORY in record.categories
            and record.tag not in fixed_set
            and not any(category.startswith("服装") for category in record.categories)
        ):
            return "職業・属性を変えるタグを除外しました"
        if fixed_hair_colors and HAIR_COLOR_CATEGORY in record.categories and record.tag not in fixed_hair_colors:
            return "髪色を変えるタグを除外しました"
        if fixed_eye_colors and EYE_COLOR_CATEGORY in record.categories and record.tag not in fixed_eye_colors:
            return "目色を変えるタグを除外しました"
        return ""

    def _fixed_category_tags(self, fixed_set: set[str], category: str) -> set[str]:
        result: set[str] = set()
        for tag in fixed_set:
            record = self.tag_dictionary.get(tag)
            if record and category in record.categories:
                result.add(tag)
        return result

    def _find_safe_difference_tag(
        self,
        candidate_pool: dict[str, list[str]],
        used_tags: set[str],
    ) -> str:
        for tags in candidate_pool.values():
            for tag in tags:
                if tag in used_tags:
                    continue
                record = self.tag_dictionary.get(tag)
                if record and not self._drop_reason(record, used_tags, set(), set()):
                    return tag
        return ""

    def _is_known_or_fixed(self, tag: str) -> bool:
        return self.tag_dictionary.has_tag(tag) or tag in FIXED_ALLOWED_TAGS or tag in AGE_TAGS

    def _appearance_anchor_tags(self, sheet: CharacterSheet) -> list[str]:
        """キャラクターシートに明記された外見特徴を全候補共通の固定タグにする。"""
        text = "\n".join(
            [
                sheet.appearance,
                sheet.raw_markdown,
            ]
        )
        tags = self.tag_dictionary.match_tags(
            [
                "髪/髪の長さ",
                HAIR_COLOR_CATEGORY,
                "髪/前髪のスタイル",
                "髪/髪の結び方/編み方",
                "髪/髪質(ストレート・ウェーブ等)",
                "髪/その他ヘアスタイルに関する事柄",
                "髪/ヘアアクセサリー",
                EYE_COLOR_CATEGORY,
                "目/瞳孔の形",
                "目/その他",
                *EXPRESSION_CATEGORIES,
                "その他の顔の特徴/メイク",
                "その他の顔の特徴/髭",
                "その他の顔の特徴/その他",
            ],
            text,
            limit=16,
        )
        return _dedupe_tags(tags)

    def _anchor_tags_from_policy(self, policy: dict[str, Any]) -> list[str]:
        tags: list[str] = []
        for tag in policy.get("required_tags", []):
            normalized = normalize_tag(tag)
            if self.tag_dictionary.has_tag(normalized):
                tags.append(normalized)
        tags.extend(
            self.tag_dictionary.resolve_anchor_tags(
                policy.get("required_tag_terms", []),
                per_term_limit=2,
                total_limit=16,
            )
        )
        return _dedupe_tags(tags)

    def _visual_detail_guide(self, *, limit_per_category: int = 140) -> list[dict[str, object]]:
        guide: list[dict[str, object]] = []
        for category in VISUAL_DETAIL_CATEGORIES:
            records = [
                record
                for record in self.tag_dictionary.category_records(category)
                if not self.tag_dictionary.is_noise_tag(record.tag)
                and not self.tag_dictionary.should_exclude_from_prompt(record)
            ]
            if not records:
                continue
            guide.append(
                {
                    "category": category,
                    "count": len(records),
                    "tags": [record.tag for record in records[:limit_per_category]],
                }
            )
        return guide


async def generate_danbooru_prompt_candidates(
    sheet: CharacterSheet,
    *,
    tag_dictionary: DanbooruTagDictionary,
    llm: DanbooruPromptLLM,
    count: int = 3,
    seed: int | None = None,
) -> list[DanbooruPromptCandidate]:
    """テストUIや将来の本体組み込みから使う候補生成API。"""
    generator = DanbooruPromptGenerator(tag_dictionary, llm)
    return await generator.generate_danbooru_prompt_candidates(sheet, count=count, seed=seed)


ANCHOR_SYSTEM_PROMPT = """\
あなたはキャラクター外見の不変アンカー抽出器です。
キャラクターシートに明記された、全プロンプト候補で必ず維持すべき外見・持ち物・服の状態だけをJSONで返してください。
説明文やMarkdownは出力しないでください。
"""

SEARCH_POLICY_SYSTEM_PROMPT = """\
あなたはDanbooruタグ辞書を使う画像生成プロンプト設計者です。
キャラクターシートを壊さず、タグ辞書内にありそうな服装・アクセサリー候補を探すための検索方針だけをJSONで返してください。
説明文やMarkdownは出力しないでください。
"""

CANDIDATE_SYSTEM_PROMPT = """\
あなたはDanbooruタグプロンプト候補を作るアシスタントです。
固定タグを維持し、提示された候補タグからキャラに合う胸上コーデ案を作ってください。
出力はJSONのみです。
"""


def parse_json_object(text: str) -> dict[str, Any]:
    stripped = _strip_code_fence(text.strip())
    try:
        value = json.loads(stripped)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", stripped):
        try:
            value, _ = decoder.raw_decode(stripped[match.start() :])
        except json.JSONDecodeError:
            continue
        return value if isinstance(value, dict) else {}
    return {}


def _strip_code_fence(text: str) -> str:
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    return match.group(1) if match else text


def _message_text(message: object) -> str:
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
    return str(content)


def _normalize_policy(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "include_categories": _list_of_strings(policy.get("include_categories")),
        "search_terms": _list_of_strings(policy.get("search_terms")),
        "required_tags": _list_of_strings(policy.get("required_tags")),
        "required_tag_terms": _list_of_strings(policy.get("required_tag_terms")),
        "avoid_terms": _list_of_strings(policy.get("avoid_terms")),
        "style_directions": _list_of_strings(policy.get("style_directions")),
        "freeform_feature_hints": _list_of_strings(policy.get("freeform_feature_hints")),
        "reason": str(policy.get("reason") or ""),
    }


def _normalize_anchor_policy(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "required_tags": _list_of_strings(policy.get("required_tags")),
        "required_tag_terms": _list_of_strings(policy.get("required_tag_terms")),
        "freeform_feature_hints": _list_of_strings(policy.get("freeform_feature_hints")),
        "reason": str(policy.get("reason") or ""),
    }


def _list_of_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _flatten_tags(value: object) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[,、\s]+", value) if part.strip()]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_flatten_tags(item))
        return result
    return []


def _sanitize_freeform_tags(
    value: object,
    *,
    known_tags: set[str],
    limit: int = 3,
) -> tuple[list[str], list[str]]:
    tags: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for raw_tag in _flatten_freeform_tags(value):
        cleaned = _clean_freeform_tag(raw_tag)
        if not cleaned:
            continue
        normalized = normalize_tag(cleaned)
        if normalized in known_tags or normalized in seen:
            continue
        if len(cleaned) > 80:
            cleaned = cleaned[:80].rstrip()
            warnings.append(f"自由タグを80文字に丸めました: {cleaned}")
        tags.append(cleaned)
        seen.add(normalized)
        if len(tags) >= limit:
            break
    return tags, warnings


def _age_style_anchor_tags(sheet: CharacterSheet) -> list[str]:
    age = _extract_age_number(sheet.age)
    if age is None:
        return []
    if 15 <= age < 20:
        return ["young adult"]
    if 20 <= age < 35:
        return ["adult"]
    return []


def _age_negative_tags(sheet: CharacterSheet, person_tag: str) -> list[str]:
    age = _extract_age_number(sheet.age)
    if age is None or age < 15:
        return []
    if person_tag == "1boy":
        return ["shota"]
    if person_tag == "1girl":
        return ["loli"]
    return ["loli", "shota"]


def _flatten_freeform_tags(value: object) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[,、\n]+", value) if part.strip()]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_flatten_freeform_tags(item))
        return result
    return []


def _clean_freeform_tag(value: str) -> str:
    cleaned = value.strip().strip('"').strip("'")
    cleaned = re.sub(r"[\r\n,]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _dedupe_freeform_tags(tags: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        cleaned = _clean_freeform_tag(tag)
        normalized = normalize_tag(cleaned)
        if not cleaned or normalized in seen:
            continue
        result.append(cleaned)
        seen.add(normalized)
    return result


def _dedupe_tags(tags: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        normalized = normalize_tag(tag)
        if not normalized or normalized in seen:
            continue
        result.append(normalized)
        seen.add(normalized)
    return result


def _join_prompt_parts(
    tag_parts: list[str],
    freeform_anchor_tags: list[str],
    freeform_tags: list[str],
) -> str:
    parts = [
        *(_format_prompt_tag(tag) for tag in tag_parts),
        *freeform_anchor_tags,
        *freeform_tags,
    ]
    return ", ".join(part for part in parts if part)


def _join_prompt_tags(tags: list[str]) -> str:
    return ", ".join(_format_prompt_tag(tag) for tag in tags if tag)


def _format_prompt_tag(tag: str) -> str:
    normalized = normalize_tag(tag)
    if normalized in {"o_o", "x_x", "u_u"}:
        return normalized
    return normalized.replace("_", " ")


def _sheet_text(sheet: CharacterSheet) -> str:
    fields = [
        sheet.raw_markdown,
        sheet.name,
        sheet.age,
        sheet.gender,
        sheet.occupation,
        sheet.origin,
        sheet.world,
        sheet.appearance,
        sheet.personality,
        sheet.motivation,
        sheet.weakness,
        sheet.background,
        sheet.skills,
        sheet.quirks,
        sheet.story_hooks,
        sheet.self_intro,
    ]
    return "\n".join(str(field) for field in fields if str(field).strip())


def _identity_text(sheet: CharacterSheet) -> str:
    return "\n".join(
        [
            sheet.occupation,
            sheet.world,
            sheet.background,
            sheet.skills,
            sheet.raw_markdown,
        ]
    )


def _infer_person_tag(sheet: CharacterSheet) -> str:
    gender = _normalize_text(sheet.gender)
    if any(word in gender for word in ("中性", "ノンバイナリー", "不明", "other", "nonbinary")):
        return "1other"
    if any(word in gender for word in ("女性", "女", "girl", "female", "woman")):
        return "1girl"
    if any(word in gender for word in ("男性", "男", "boy", "male", "man")):
        return "1boy"
    return "1other"


def _infer_age_tags(sheet: CharacterSheet, person_tag: str) -> list[str]:
    text = f"{sheet.age}\n{sheet.raw_markdown}"
    age = _extract_age_number(sheet.age)
    if _contains_any_text_marker(text, ("baby", "赤ちゃん", "乳児")) or (age is not None and age <= 2):
        return ["baby"]
    if _contains_any_text_marker(text, ("幼児", "子供", "child")) or (age is not None and age <= 12):
        if person_tag == "1girl":
            return ["loli"]
        if person_tag == "1boy":
            return ["shota"]
        return ["child"]
    if _contains_any_text_marker(text, ("老人", "老年", "高齢", "old")) or (age is not None and age >= 65):
        return ["old_woman"] if person_tag == "1girl" else ["old"]
    if _contains_mature_marker(text) or (age is not None and age >= 35):
        if person_tag == "1girl":
            return ["mature_female"]
        if person_tag == "1boy":
            return ["mature_male"]
    return []


def _extract_age_number(value: str) -> int | None:
    match = re.search(r"\d+", value)
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def _looks_like_plain_human(text: str) -> bool:
    nonhuman_markers = (
        "elf",
        "demon",
        "angel",
        "android",
        "robot",
        "oni",
        "vampire",
        "monster",
        "cat ears",
        "cat_ears",
        "fox ears",
        "fox_ears",
        "tail",
        "wings",
        "horns",
        "エルフ",
        "悪魔",
        "天使",
        "アンドロイド",
        "鬼",
        "吸血鬼",
        "獣耳",
        "尻尾",
        "翼",
        "角",
    )
    if any(_contains_nonhuman_marker(text, marker) for marker in nonhuman_markers):
        return False
    return _contains_any_text_marker(text, ("human", "人間", "普通の人間"))


def _normalize_text(text: str) -> str:
    return str(text).lower().replace("_", " ")


def _contains_any_text_marker(text: str, markers: tuple[str, ...]) -> bool:
    return any(_contains_text_marker(text, marker) for marker in markers)


def _contains_text_marker(text: str, marker: str) -> bool:
    normalized_text = _normalize_text(text)
    normalized_marker = _normalize_text(marker)
    if not normalized_marker:
        return False
    if re.fullmatch(r"[a-z0-9][a-z0-9\s_-]*", normalized_marker):
        parts = [re.escape(part) for part in re.split(r"[\s_-]+", normalized_marker) if part]
        if not parts:
            return False
        pattern = r"(?<![a-z0-9])" + r"[\s_-]+".join(parts) + r"(?![a-z0-9])"
        return re.search(pattern, normalized_text) is not None
    return normalized_marker in normalized_text


def _contains_mature_marker(text: str) -> bool:
    normalized = _normalize_text(text)
    if _contains_text_marker(normalized, "mature") or "成熟" in normalized:
        return True
    for match in re.finditer("大人", normalized):
        if normalized.startswith(("大人し", "大人気", "大人数"), match.start()):
            continue
        return True
    return False


def _contains_nonhuman_marker(text: str, marker: str) -> bool:
    normalized_marker = _normalize_text(marker)
    if normalized_marker == "角":
        return _contains_horn_marker(text)
    return _contains_text_marker(text, marker)


def _contains_horn_marker(text: str) -> bool:
    normalized = _normalize_text(text)
    false_prefixes = {"三", "四", "五", "六", "七", "八", "九", "十", "多", "方", "口", "広", "直"}
    false_suffixes = {"度", "形", "材", "地", "落", "部"}
    for match in re.finditer("角", normalized):
        previous_char = normalized[match.start() - 1 : match.start()]
        next_char = normalized[match.end() : match.end() + 1]
        if previous_char in false_prefixes or next_char in false_suffixes:
            continue
        return True
    return False
