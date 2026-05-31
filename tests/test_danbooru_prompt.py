from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from typing import Any

from src.core.character.schemas import CharacterSheet
from src.core.danbooru_prompt import DanbooruPromptGenerator, DanbooruTagDictionary


class FakeLLM:
    def __init__(
        self,
        policy: dict[str, Any],
        proposal: dict[str, Any],
        anchor_policy: dict[str, Any] | None = None,
    ) -> None:
        self.anchor_policy = anchor_policy or {}
        self.policy = policy
        self.proposal = proposal
        self.calls: list[tuple[str, str]] = []

    async def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        self.calls.append((system_prompt, user_prompt))
        if len(self.calls) == 1:
            return self.anchor_policy
        return self.policy if len(self.calls) == 2 else self.proposal


class DanbooruPromptTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.csv_path = Path(self.tmp.name) / "tags.csv"
        _write_sample_csv(self.csv_path)
        self.dictionary = DanbooruTagDictionary.from_csv(self.csv_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    async def test_llm_flow_filters_identity_noise_and_lower_body_tags(self) -> None:
        llm = FakeLLM(
            policy={
                "include_categories": ["服装/トップス", "服装/ヘッドウェア"],
                "search_terms": ["military", "jacket", "shirt", "glasses"],
                "avoid_terms": ["boots", "bikini", "alternate"],
                "style_directions": ["標準衣装", "個性強め"],
                "freeform_feature_hints": ["keeps emotional distance"],
            },
            proposal={
                "candidates": [
                    {
                        "label": "標準衣装",
                        "variant_tags": [
                            "military_uniform",
                            "black_jacket",
                            "glasses",
                            "jitome",
                            "light_blush",
                            ":d",
                            "boots",
                            "cat_ears",
                            "alternate_hairstyle",
                            "silver_hair",
                            "unknown_tag",
                        ],
                        "freeform_tags": ["keeps emotional distance", "quiet tactical gaze"],
                    }
                ]
            },
        )
        sheet = CharacterSheet(
            id="test",
            name="Test Soldier",
            age="36",
            gender="女性",
            occupation="soldier",
            origin="ordinary human",
            world="military base",
            appearance="dark skin, black hair, blunt bangs, ponytail, blue eyes, jitome, tall soldier",
            raw_markdown="ordinary human soldier with dark skin, black hair, blunt bangs, ponytail and blue eyes",
        )

        result = await DanbooruPromptGenerator(self.dictionary, llm).generate_with_debug(sheet)

        self.assertEqual(len(llm.calls), 3)
        self.assertIn("タグ辞書ガイド", llm.calls[0][1])
        self.assertIn("タグ辞書ガイド", llm.calls[1][1])
        self.assertIn("小カテゴリのタグ一覧", llm.calls[2][1])
        self.assertIn("髪・目・顔・表情に使いやすい正規タグ", llm.calls[2][1])
        self.assertIn("表情カテゴリもCSV由来の正規タグ", llm.calls[2][1])
        self.assertIn("全候補で絶対に変えない外見アンカー", llm.calls[2][1])
        self.assertIn("全候補で必ず入れる自由特徴アンカー", llm.calls[2][1])
        self.assertIn("freeform_tags", llm.calls[2][1])
        self.assertIn("large_categories", llm.calls[1][1])
        self.assertIn("glasses", llm.calls[2][1])
        self.assertIn("jitome", llm.calls[2][1])
        self.assertIn("表情/目元の表情", llm.calls[2][1])

        candidate = result.candidates[0]
        self.assertTrue(candidate.prompt.startswith("1girl, solo"))
        self.assertIn("military", candidate.fixed_tags)
        self.assertIn("dark_skin", candidate.fixed_tags)
        self.assertIn("black_hair", candidate.fixed_tags)
        self.assertIn("blunt_bangs", candidate.fixed_tags)
        self.assertIn("ponytail", candidate.fixed_tags)
        self.assertIn("blue_eyes", candidate.fixed_tags)
        self.assertIn("jitome", candidate.fixed_tags)
        self.assertIn("military_uniform", candidate.variant_tags)
        self.assertIn("black_jacket", candidate.variant_tags)
        self.assertIn("glasses", candidate.variant_tags)
        self.assertIn("light_blush", candidate.variant_tags)
        self.assertIn("loli", candidate.negative_tags)
        self.assertEqual(candidate.negative_prompt, "loli")
        self.assertIn("dark skin", candidate.prompt)
        self.assertIn("black hair", candidate.prompt)
        self.assertIn("blue eyes", candidate.prompt)
        self.assertIn("keeps emotional distance", candidate.freeform_tags)
        self.assertIn("quiet tactical gaze", candidate.freeform_tags)
        self.assertIn("keeps emotional distance", candidate.prompt)
        self.assertIn(":d", candidate.dropped_tags)
        self.assertIn("boots", candidate.dropped_tags)
        self.assertIn("cat_ears", candidate.dropped_tags)
        self.assertIn("alternate_hairstyle", candidate.dropped_tags)
        self.assertIn("silver_hair", candidate.dropped_tags)
        self.assertIn("unknown_tag", candidate.dropped_tags)
        self.assertIn("military_uniform", result.candidate_pool["服装/トップス"])
        self.assertNotIn("boots", result.candidate_pool.get("服装/ボトムス", []))

    async def test_duplicate_candidates_get_safe_difference_tag(self) -> None:
        llm = FakeLLM(
            policy={
                "include_categories": ["服装/トップス"],
                "search_terms": ["jacket", "shirt"],
                "avoid_terms": [],
                "style_directions": ["標準衣装", "日常寄り"],
            },
            proposal={
                "candidates": [
                    {"label": "案1", "variant_tags": ["black_jacket"]},
                    {"label": "案2", "variant_tags": ["black_jacket"]},
                ]
            },
        )
        sheet = CharacterSheet(
            id="test",
            name="Casual Character",
            age="24",
            gender="女性",
            origin="ordinary human",
            appearance="black hair, blue eyes",
            raw_markdown="ordinary human with black hair and blue eyes",
        )

        result = await DanbooruPromptGenerator(self.dictionary, llm).generate_with_debug(
            sheet,
            count=2,
        )

        self.assertEqual(len(result.candidates), 2)
        self.assertNotEqual(result.candidates[0].prompt, result.candidates[1].prompt)
        self.assertTrue(any("重複候補" in warning for warning in result.candidates[1].warnings))

    async def test_japanese_appearance_anchors_are_kept_in_all_candidates(self) -> None:
        llm = FakeLLM(
            anchor_policy={
                "required_tags": ["pale_skin"],
                "required_tag_terms": [
                    "pale skin",
                    "robe",
                    "belt pouch",
                    "skin",
                    "shoulder",
                    "leather",
                    "large",
                ],
                "freeform_feature_hints": ["dusty clothes", "leather book bag on shoulder"],
            },
            policy={
                "include_categories": ["服装/トップス", "アクセサリー(髪以外に付けるもの)"],
                "search_terms": ["robe", "pouch"],
                "avoid_terms": [],
                "style_directions": ["標準衣装", "個性強め", "日常寄り"],
                "freeform_feature_hints": ["argumentative scholar expression"],
            },
            proposal={
                "candidates": [
                    {"label": "標準衣装", "variant_tags": ["glasses"], "freeform_tags": ["confident smile"]},
                    {"label": "個性強め", "variant_tags": ["choker"], "freeform_tags": ["forbidden spell aura"]},
                    {"label": "日常寄り", "variant_tags": ["round_eyewear"], "freeform_tags": ["lonely gaze"]},
                ]
            },
        )
        sheet = CharacterSheet(
            id="lilith",
            name="リリス・クロノス",
            age="21歳",
            gender="女性",
            occupation="古代語を解読する若き言語学者",
            origin="砂に埋もれた古代図書館の地下階",
            world="古代魔法文明が崩壊した後の廃墟世界。",
            appearance=(
                "日光に当たっていないため、肌は青白い。身に纏っている長いローブは"
                "砂埃で常に薄汚れているが、肩には使い込まれた革製の巨大な書物袋をかけている。"
            ),
            raw_markdown="",
        )

        result = await DanbooruPromptGenerator(self.dictionary, llm).generate_with_debug(
            sheet,
            count=3,
        )

        self.assertIn("pale_skin", result.fixed_tags)
        self.assertIn("robe", result.fixed_tags)
        self.assertIn("belt_pouch", result.fixed_tags)
        self.assertNotIn("dark_skin", result.fixed_tags)
        self.assertNotIn("colored_skin", result.fixed_tags)
        self.assertNotIn("off_shoulder", result.fixed_tags)
        self.assertNotIn("shoulder_armor", result.fixed_tags)
        self.assertNotIn("leather_jacket", result.fixed_tags)
        self.assertNotIn("large_pectorals", result.fixed_tags)
        self.assertIn("dusty clothes", result.freeform_anchor_tags)
        self.assertIn("adult", result.freeform_anchor_tags)
        self.assertIn("leather book bag on shoulder", result.freeform_anchor_tags)
        self.assertEqual(result.negative_tags, ["loli"])
        for candidate in result.candidates:
            self.assertIn("pale skin", candidate.prompt)
            self.assertIn("robe", candidate.prompt)
            self.assertIn("belt pouch", candidate.prompt)
            self.assertIn("adult", candidate.prompt)
            self.assertEqual(candidate.negative_tags, ["loli"])
            self.assertIn("dusty clothes", candidate.prompt)
            self.assertIn("leather book bag on shoulder", candidate.prompt)
        self.assertFalse(any("pale_skin" in candidate.dropped_tags for candidate in result.candidates))

    def test_small_categories_are_passed_in_full_and_large_are_summarized(self) -> None:
        guide = self.dictionary.build_llm_tag_guide()
        small = {item["category"]: item for item in guide["small_categories"]}  # type: ignore[index]
        large = {item["category"]: item for item in guide["large_categories"]}  # type: ignore[index]

        self.assertIn("目/目の色", small)
        self.assertIn("blue_eyes", small["目/目の色"]["tags"])
        self.assertIn("服装/トップス", large)
        self.assertIn("representative_tags", large["服装/トップス"])
        self.assertIn("frequent_tokens", large["服装/トップス"])
        self.assertIn("表情/目元の表情", small)
        self.assertIn("jitome", small["表情/目元の表情"]["tags"])
        self.assertIn("表情/口元の表情", small)
        self.assertNotIn(":d", small["表情/口元の表情"]["tags"])

    async def test_known_expression_freeform_is_promoted_to_variant_tag(self) -> None:
        llm = FakeLLM(
            policy={
                "include_categories": ["表情/全体"],
                "search_terms": ["smile"],
                "avoid_terms": [],
                "style_directions": ["標準衣装"],
            },
            proposal={
                "candidates": [
                    {"label": "案1", "variant_tags": ["glasses"], "freeform_tags": ["smile", "calm mood"]}
                ]
            },
        )
        sheet = CharacterSheet(
            id="test",
            name="Expression Test",
            age="24",
            gender="女性",
            origin="ordinary human",
            appearance="black hair, blue eyes",
            raw_markdown="ordinary human with black hair and blue eyes",
        )

        result = await DanbooruPromptGenerator(self.dictionary, llm).generate_with_debug(sheet)

        candidate = result.candidates[0]
        self.assertIn("smile", candidate.variant_tags)
        self.assertNotIn("smile", candidate.freeform_tags)
        self.assertIn("calm mood", candidate.freeform_tags)


def _write_sample_csv(path: Path) -> None:
    rows = [
        ("military", "世界観/ジャンル;職業/役割/キャラ属性", "high", ""),
        ("soldier", "職業/役割/キャラ属性", "high", ""),
        ("mature_female", "年齢/世代", "high", ""),
        ("black_hair", "髪/髪の色", "high", ""),
        ("silver_hair", "髪/髪の色", "high", ""),
        ("blunt_bangs", "髪/前髪のスタイル", "high", ""),
        ("ponytail", "髪/髪の結び方/編み方", "high", ""),
        ("blue_eyes", "目/目の色", "high", ""),
        ("jitome", "表情/目元の表情", "high", ""),
        ("light_blush", "表情/頬/顔色", "medium", ""),
        ("smile", "表情/全体", "high", ""),
        (":d", "表情/口元の表情", "high", ""),
        ("dark_skin", "肌の色", "high", ""),
        ("colored_skin", "肌の色", "high", ""),
        ("off_shoulder", "服装/トップス", "high", ""),
        ("shoulder_armor", "服装/トップス", "high", ""),
        ("leather_jacket", "服装/トップス", "high", ""),
        ("large_pectorals", "体形", "high", ""),
        ("pale_skin", "肌の色", "high", ""),
        ("cat_ears", "種族/身体特徴", "high", ""),
        ("alternate_hairstyle", "髪/その他ヘアスタイルに関する事柄", "high", ""),
        ("glasses", "アクセサリー(髪以外に付けるもの)", "high", ""),
        ("choker", "アクセサリー(髪以外に付けるもの)", "high", ""),
        ("beret", "服装/ヘッドウェア", "high", ""),
        ("robe", "服装/トップス", "high", ""),
        ("belt_pouch", "アクセサリー(髪以外に付けるもの)", "high", ""),
        ("round_eyewear", "アクセサリー(髪以外に付けるもの)", "high", ""),
        ("military_uniform", "服装/トップス;服装/ボトムス;職業/役割/キャラ属性", "high", ""),
        ("black_jacket", "服装/トップス", "high", ""),
        ("white_shirt", "服装/トップス", "high", ""),
        ("boots", "服装/ボトムス", "high", ""),
        ("black_skirt", "服装/ボトムス", "high", ""),
    ]
    rows.extend((f"sample_{i}_jacket", "服装/トップス", "high", "") for i in range(90))
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["tag", "categories", "confidence", "note"])
        writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
