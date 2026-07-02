"""グループチャットの次話者選択ロジック。"""

from __future__ import annotations

import json
import random
import re
from typing import Any

from ..group_chat.schemas import GroupMember


def mentioned_member(text: str, members: list[GroupMember]) -> GroupMember | None:
    handles = re.findall(r"@([A-Za-z0-9_]{3,12})", text or "")
    if not handles:
        return None
    by_handle = {member.handle.lower(): member for member in members}
    for handle in handles:
        member = by_handle.get(handle.lower())
        if member is not None:
            return member
    return None


def member_from_llm_choice(raw: str, members: list[GroupMember]) -> GroupMember | None:
    text = (raw or "").strip()
    if not text:
        return None
    lowered = text.lower()
    for member in members:
        if re.search(rf"@?{re.escape(member.handle.lower())}\b", lowered):
            return member
    for member in members:
        if member.character.name and member.character.name in text:
            return member
    return None


def speaker_weights_from_llm_output(raw: str, members: list[GroupMember]) -> dict[str, float]:
    weights: dict[str, float] = {}
    parsed = try_parse_json_fragment(raw)
    if parsed is not None:
        for identifier, weight in collect_speaker_weight_entries(parsed):
            member = member_from_identifier(identifier, members)
            if member is not None and weight > 0:
                weights[member.id] = max(weights.get(member.id, 0.0), weight)
    if weights:
        return weights

    for line in (raw or "").splitlines():
        member = member_from_llm_choice(line, members)
        if member is None:
            continue
        scrubbed = line
        for candidate in members:
            scrubbed = re.sub(rf"@?{re.escape(candidate.handle)}\b", "", scrubbed, flags=re.IGNORECASE)
            if candidate.character.name:
                scrubbed = scrubbed.replace(candidate.character.name, "")
        numbers = re.findall(r"(?<![A-Za-z0-9_])(\d+(?:\.\d+)?)\s*%?", scrubbed)
        if numbers:
            weights[member.id] = max(weights.get(member.id, 0.0), float(numbers[-1]))
    if weights:
        return weights

    selected = member_from_llm_choice(raw, members)
    if selected is not None:
        return {member.id: 2.0 if member.id == selected.id else 1.0 for member in members}
    return {}


def try_parse_json_fragment(raw: str) -> Any | None:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()
    parsed = _try_parse_json(text)
    if parsed is not None:
        return parsed
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        return value
    return None


def collect_speaker_weight_entries(value: Any) -> list[tuple[str, float]]:
    entries: list[tuple[str, float]] = []
    if isinstance(value, dict):
        identifier = speaker_identifier_from_dict(value)
        weight = speaker_weight_from_dict(value)
        if identifier and weight is not None:
            entries.append((identifier, weight))
        for key, item in value.items():
            direct = number_from_weight_value(item)
            if direct is not None:
                entries.append((str(key), direct))
            elif isinstance(item, (dict, list)):
                entries.extend(collect_speaker_weight_entries(item))
        return entries
    if isinstance(value, list):
        if len(value) >= 2 and not isinstance(value[0], (dict, list)):
            weight = number_from_weight_value(value[1])
            if weight is not None:
                entries.append((str(value[0]), weight))
            return entries
        for item in value:
            if isinstance(item, (dict, list)):
                entries.extend(collect_speaker_weight_entries(item))
            elif isinstance(item, tuple) and len(item) >= 2:
                weight = number_from_weight_value(item[1])
                if weight is not None:
                    entries.append((str(item[0]), weight))
        return entries
    return entries


def speaker_identifier_from_dict(value: dict[Any, Any]) -> str:
    for key in ("handle", "id", "member_id", "speaker_id", "name", "character", "candidate"):
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            return item.strip()
    return ""


def speaker_weight_from_dict(value: dict[Any, Any]) -> float | None:
    for key in ("weight", "ratio", "probability", "possibility", "score", "percent", "chance"):
        number = number_from_weight_value(value.get(key))
        if number is not None:
            return number
    return None


def number_from_weight_value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        number = float(value)
    elif isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value)
        if not match:
            return None
        number = float(match.group(0))
    else:
        return None
    if number <= 0 or number == float("inf") or number == float("-inf") or number != number:
        return None
    return number


def member_from_identifier(identifier: str, members: list[GroupMember]) -> GroupMember | None:
    text = (identifier or "").strip()
    if not text:
        return None
    normalized = text.lstrip("@").lower()
    for member in members:
        if normalized in {
            member.id.lower(),
            member.handle.lower(),
            member.character.name.lower(),
        }:
            return member
    return member_from_llm_choice(text, members)


def choose_weighted_speaker(
    weights: dict[str, float],
    candidates: list[GroupMember],
    rng: random.Random | None = None,
) -> tuple[GroupMember, list[tuple[GroupMember, float, float]], float]:
    if not candidates:
        raise ValueError("発言候補がありません")
    weighted = [(member, max(0.0, float(weights.get(member.id, 0.0)))) for member in candidates]
    total = sum(weight for _, weight in weighted)
    if total <= 0:
        weighted = [(member, 1.0) for member in candidates]
        total = float(len(candidates))

    roll = rng.random() if rng is not None else random.random()
    threshold = roll * total
    current = 0.0
    selected = weighted[-1][0]
    for member, weight in weighted:
        current += weight
        if threshold <= current:
            selected = member
            break
    normalized = [(member, weight, (weight / total) * 100 if total > 0 else 0.0) for member, weight in weighted]
    return selected, normalized, roll


def format_speaker_selection_debug(
    raw: str,
    weights: list[tuple[GroupMember, float, float]],
    selected: GroupMember,
    roll: float,
) -> str:
    lines = [(raw or "").strip() or "（空の応答）", "", "--- 内部抽選 ---"]
    lines.append(f"乱数: {roll:.4f}")
    lines.append("発言可能性:")
    for member, weight, percent in weights:
        lines.append(f"- @{member.handle} / {member.character.name}: {weight:g} ({percent:.1f}%)")
    lines.append(f"選択: @{selected.handle} / {selected.character.name}")
    return "\n".join(lines)


def _try_parse_json(text: str) -> Any | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None
