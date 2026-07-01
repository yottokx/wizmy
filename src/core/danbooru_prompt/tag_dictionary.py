"""DanbooruタグCSVを検索しやすい辞書へ変換する。"""

from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


LOWER_BODY_CATEGORY = "服装/ボトムス"
SMALL_CATEGORY_LIMIT = 80

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_NOISE_PATTERNS = (
    re.compile(r"^alternate_"),
    re.compile(r"^official_alternate_"),
)
_EMOTICON_TAGS = {
    "o_o",
    "x_x",
    "u_u",
    "._.",
    "emoticon",
}
_EMOTICON_MARK_RE = re.compile(r"[:;=^@+<>]")
_FORBIDDEN_TERMS = {
    "panties",
    "underwear",
    "lingerie",
    "bra",
    "bikini",
    "swimsuit",
    "footwear",
    "shoes",
    "boots",
    "socks",
    "thighhighs",
    "pantyhose",
    "kneehighs",
    "garter",
    "legwear",
}
_UPPER_BODY_EXCEPTION_TERMS = {
    "dress",
    "uniform",
    "serafuku",
    "suit",
    "kimono",
    "clothes",
    "armor",
    "bodysuit",
    "leotard",
    "robe",
    "coat",
}
_GENERIC_TOKENS = {
    "a",
    "an",
    "and",
    "body",
    "clothes",
    "color",
    "female",
    "girl",
    "hair",
    "male",
    "man",
    "of",
    "on",
    "the",
    "with",
    "woman",
}


@dataclass(frozen=True)
class TagRecord:
    """CSVの1行を検索用の付加情報つきで保持する。"""

    tag: str
    categories: tuple[str, ...]
    confidence: str = ""
    note: str = ""
    tokens: tuple[str, ...] = ()

    @classmethod
    def from_csv_row(cls, row: dict[str, str]) -> "TagRecord":
        tag = (row.get("tag") or "").strip()
        categories = tuple(
            part.strip()
            for part in (row.get("categories") or "").split(";")
            if part.strip()
        )
        return cls(
            tag=tag,
            categories=categories,
            confidence=(row.get("confidence") or "").strip().lower(),
            note=(row.get("note") or "").strip(),
            tokens=tokenize_tag(tag),
        )


class DanbooruTagDictionary:
    """タグ一覧をカテゴリ別・トークン別に検索する辞書。"""

    def __init__(self, records: Iterable[TagRecord]) -> None:
        self.records = [record for record in records if record.tag and record.categories]
        self._by_tag = {record.tag: record for record in self.records}
        self._by_category: dict[str, list[TagRecord]] = defaultdict(list)
        for record in self.records:
            for category in record.categories:
                self._by_category[category].append(record)

    @classmethod
    def from_csv(cls, path: str | Path) -> "DanbooruTagDictionary":
        records: list[TagRecord] = []
        with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                record = TagRecord.from_csv_row(row)
                if record.tag:
                    records.append(record)
        return cls(records)

    def has_tag(self, tag: str) -> bool:
        return normalize_tag(tag) in self._by_tag

    def get(self, tag: str) -> TagRecord | None:
        return self._by_tag.get(normalize_tag(tag))

    def category_names(self) -> list[str]:
        return sorted(self._by_category)

    def category_records(self, category: str) -> list[TagRecord]:
        return list(self._by_category.get(category, []))

    def build_llm_tag_guide(
        self,
        *,
        small_category_limit: int = SMALL_CATEGORY_LIMIT,
        representative_limit: int = 24,
        token_limit: int = 24,
    ) -> dict[str, object]:
        """LLMへ渡すための小カテゴリ全件と大カテゴリ要約を作る。"""
        small_categories: list[dict[str, object]] = []
        large_categories: list[dict[str, object]] = []

        for category in self.category_names():
            usable = [
                record
                for record in self._by_category[category]
                if not self.is_noise_tag(record.tag)
                and not self.is_emoticon_tag(record.tag)
            ]
            if len(usable) <= small_category_limit:
                small_categories.append({
                    "category": category,
                    "count": len(usable),
                    "tags": [record.tag for record in usable],
                })
                continue

            representatives = self._representative_records(usable, representative_limit)
            large_categories.append({
                "category": category,
                "count": len(usable),
                "representative_tags": [record.tag for record in representatives],
                "frequent_tokens": self._frequent_tokens(usable, token_limit),
                "excluded_examples": [
                    record.tag
                    for record in usable
                    if self.should_exclude_from_prompt(record)
                ][: representative_limit // 2],
            })

        return {
            "small_category_limit": small_category_limit,
            "small_categories": small_categories,
            "large_categories": large_categories,
        }

    def select_candidate_pool(
        self,
        policy: dict[str, object],
        *,
        max_per_category: int = 80,
        small_category_limit: int = SMALL_CATEGORY_LIMIT,
    ) -> dict[str, list[str]]:
        """LLMの検索方針を使って大量カテゴリから候補タグを抽出する。"""
        include_categories = _string_list(policy.get("include_categories"))
        search_terms = _token_set(_string_list(policy.get("search_terms")))
        avoid_terms = _token_set(_string_list(policy.get("avoid_terms")))
        style_terms = _token_set(_string_list(policy.get("style_directions")))
        terms = search_terms | style_terms

        selected: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
        for index, record in enumerate(self.records):
            if len(self._category_bucket(record)) <= small_category_limit:
                continue
            if self.should_exclude_from_prompt(record):
                continue
            if avoid_terms and self._record_matches_terms(record, avoid_terms):
                continue

            score = self._candidate_score(record, include_categories, terms)
            if score <= 0:
                continue
            for category in record.categories:
                if len(self._by_category.get(category, [])) > small_category_limit:
                    selected[category].append((score, -index, record.tag))

        result: dict[str, list[str]] = {}
        for category, scored in selected.items():
            ordered = sorted(scored, reverse=True)
            result[category] = [tag for _, _, tag in ordered[:max_per_category]]
        return result

    def match_tags(
        self,
        categories: Iterable[str],
        text: str,
        *,
        limit: int = 6,
        allow_lower_body: bool = False,
    ) -> list[str]:
        """キャラクターシートの文字列からカテゴリ内のタグを単純照合する。"""
        haystack = _normalize_search_text(text)
        scored: list[tuple[int, int, str]] = []
        seen: set[str] = set()
        for category in categories:
            for index, record in enumerate(self._by_category.get(category, [])):
                if record.tag in seen or self.should_exclude_from_prompt(record):
                    continue
                if not allow_lower_body and self.is_lower_body_only(record):
                    continue
                score = _text_match_score(record, haystack)
                if score <= 0:
                    continue
                if record.confidence == "high":
                    score += 1
                scored.append((score, -index, record.tag))
                seen.add(record.tag)
        return [tag for _, _, tag in sorted(scored, reverse=True)[:limit]]

    def search_tags_by_terms(
        self,
        terms: Iterable[str],
        *,
        limit: int = 24,
    ) -> list[str]:
        """LLMが出した検索語から、辞書全体のタグを機械的に探す。"""
        raw_terms = _string_list(list(terms))
        search_tokens = _token_set(raw_terms) - _GENERIC_TOKENS
        if not search_tokens:
            return []

        scored: list[tuple[int, int, str]] = []
        seen: set[str] = set()
        for index, record in enumerate(self.records):
            if record.tag in seen or self.should_exclude_from_prompt(record):
                continue
            record_token_set = record_terms(record)
            matched = record_token_set & search_tokens
            if not matched:
                continue

            score = len(matched) * 5
            normalized_tag = normalize_tag(record.tag)
            if normalized_tag in search_tokens:
                score += 12
            if set(record.tokens) and set(record.tokens).issubset(search_tokens):
                score += 8
            if record.confidence == "high":
                score += 1
            elif record.confidence == "low":
                score -= 2
            scored.append((score, -index, record.tag))
            seen.add(record.tag)

        return [tag for _, _, tag in sorted(scored, reverse=True)[:limit]]

    def resolve_anchor_tags(
        self,
        terms: Iterable[str],
        *,
        per_term_limit: int = 2,
        total_limit: int = 16,
    ) -> list[str]:
        """不変アンカー用に、検索語ごとへ保守的にタグを割り当てる。"""
        resolved: list[str] = []
        seen: set[str] = set()
        for term in _string_list(list(terms)):
            for tag in self._resolve_one_anchor_term(term, per_term_limit=per_term_limit):
                if tag in seen:
                    continue
                resolved.append(tag)
                seen.add(tag)
                if len(resolved) >= total_limit:
                    return resolved
        return resolved

    def _resolve_one_anchor_term(self, term: str, *, per_term_limit: int) -> list[str]:
        normalized = normalize_tag(term)
        exact = self._by_tag.get(normalized)
        if exact and not self.should_exclude_from_prompt(exact):
            return [exact.tag]

        tokens = tuple(token for token in tokenize_tag(term) if token not in _GENERIC_TOKENS)
        if not tokens:
            return []

        scored: list[tuple[int, int, str]] = []
        token_set = set(tokens)
        for index, record in enumerate(self.records):
            if self.should_exclude_from_prompt(record):
                continue
            record_token_set = set(record.tokens)
            if not token_set.issubset(record_token_set):
                continue

            score = 0
            if len(token_set) > 1:
                score += 20
            elif len(record.tokens) == 1:
                score += 8
            elif tokens[0] in {"robe", "pouch", "glasses", "cape", "hood", "hat"}:
                score += 4
            else:
                continue

            extra_tokens = max(0, len(record.tokens) - len(token_set))
            score -= extra_tokens * 3
            if record.confidence == "high":
                score += 2
            elif record.confidence == "low":
                score -= 3
            scored.append((score, -index, record.tag))

        return [tag for _, _, tag in sorted(scored, reverse=True)[:per_term_limit]]

    def is_noise_tag(self, tag: str) -> bool:
        normalized = normalize_tag(tag)
        return any(pattern.search(normalized) for pattern in _NOISE_PATTERNS)

    def is_emoticon_tag(self, tag: str) -> bool:
        normalized = normalize_tag(tag)
        if normalized in _EMOTICON_TAGS:
            return True
        if len(normalized) > 12:
            return False
        return bool(_EMOTICON_MARK_RE.search(normalized))

    def is_lower_body_only(self, record: TagRecord) -> bool:
        if LOWER_BODY_CATEGORY not in record.categories:
            return False
        if any(term in record.tokens for term in _UPPER_BODY_EXCEPTION_TERMS):
            return False
        return True

    def should_exclude_from_prompt(self, record: TagRecord) -> bool:
        if self.is_noise_tag(record.tag):
            return True
        if self.is_emoticon_tag(record.tag):
            return True
        if self.is_specific_named_outfit(record.tag):
            return True
        if self.is_lower_body_only(record):
            return True
        if any(term in record.tokens for term in _FORBIDDEN_TERMS):
            return True
        return False

    def is_specific_named_outfit(self, tag: str) -> bool:
        normalized = normalize_tag(tag)
        if not any(key in normalized for key in ("uniform", "outfit", "costume")):
            return False
        if re.search(r"[!'():]", normalized):
            return normalized not in {"pom_pom_(clothes)"}
        return len(tokenize_tag(normalized)) >= 6

    def _candidate_score(
        self,
        record: TagRecord,
        include_categories: list[str],
        terms: set[str],
    ) -> int:
        score = 0
        if include_categories:
            for category in record.categories:
                if _category_matches(category, include_categories):
                    score += 4
        if terms:
            matched = record_terms(record) & terms
            score += len(matched) * 5
        if record.confidence == "high":
            score += 1
        elif record.confidence == "low":
            score -= 2
        return score

    def _record_matches_terms(self, record: TagRecord, terms: set[str]) -> bool:
        return bool(record_terms(record) & terms)

    def _category_bucket(self, record: TagRecord) -> list[TagRecord]:
        largest = max(record.categories, key=lambda category: len(self._by_category.get(category, [])))
        return self._by_category.get(largest, [])

    def _representative_records(self, records: list[TagRecord], limit: int) -> list[TagRecord]:
        return sorted(
            records,
            key=lambda record: (
                0 if record.confidence == "high" else 1,
                self.should_exclude_from_prompt(record),
                len(record.tokens),
                record.tag,
            ),
        )[:limit]

    def _frequent_tokens(self, records: list[TagRecord], limit: int) -> list[str]:
        counter: Counter[str] = Counter()
        for record in records:
            for token in record.tokens:
                if token not in _GENERIC_TOKENS and len(token) >= 3:
                    counter[token] += 1
        return [token for token, _ in counter.most_common(limit)]


def normalize_tag(tag: str) -> str:
    return tag.strip().lower().replace(" ", "_")


def tokenize_tag(tag: str) -> tuple[str, ...]:
    normalized = normalize_tag(tag)
    return tuple(_TOKEN_RE.findall(normalized))


def record_terms(record: TagRecord) -> set[str]:
    terms = set(record.tokens)
    terms.add(normalize_tag(record.tag))
    return terms


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _token_set(values: Iterable[str]) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        normalized = normalize_tag(value)
        tokens.add(normalized)
        tokens.update(tokenize_tag(normalized))
    return tokens


def _normalize_search_text(text: str) -> str:
    normalized = normalize_tag(text)
    normalized = re.sub(r"[^a-z0-9_\u3040-\u30ff\u3400-\u9fff]+", "_", normalized)
    return f"_{normalized}_"


def _text_match_score(record: TagRecord, haystack: str) -> int:
    tag_phrase = normalize_tag(record.tag)
    space_phrase = tag_phrase.replace("_", " ")
    if f"_{tag_phrase}_" in haystack or normalize_tag(space_phrase) in haystack:
        return 8

    useful_tokens = [token for token in record.tokens if token not in _GENERIC_TOKENS]
    if not useful_tokens:
        return 0

    matched = [
        token
        for token in useful_tokens
        if f"_{token}_" in haystack or token in haystack
    ]
    if len(useful_tokens) == 1:
        return 4 if matched else 0
    if len(matched) >= min(2, len(useful_tokens)):
        return len(matched)
    return 0


def _category_matches(category: str, candidates: list[str]) -> bool:
    normalized = normalize_tag(category)
    for candidate in candidates:
        if not candidate:
            continue
        candidate_normalized = normalize_tag(candidate)
        if candidate_normalized == normalized:
            return True
        if candidate_normalized in normalized or normalized in candidate_normalized:
            return True
    return False
