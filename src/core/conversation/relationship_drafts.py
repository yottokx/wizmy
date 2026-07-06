"""グループチャット関係性ドラフトの変換処理。"""

from __future__ import annotations

import re
from typing import Any

from ..character.schemas import CharacterSheet
from ..group_chat.schemas import GroupMember
from .json_utils import try_parse_json, try_parse_json_fragment
from .prompts.common import compact_character_summary


def parse_group_generation_relationship_drafts(
    raw: str,
    base_members: list[GroupMember],
) -> dict[str, str]:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()
    parsed = try_parse_json(text)
    if parsed is None:
        return {}

    result: dict[str, str] = {}
    member_by_id = {member.id: member for member in base_members}
    member_by_name = {member.character.name: member for member in base_members}
    member_by_handle = {member.handle: member for member in base_members}

    candidates = parsed.get("relationships") if isinstance(parsed, dict) else parsed
    if not isinstance(candidates, list):
        return {}
    for item in candidates:
        if not isinstance(item, dict):
            continue
        key = str(item.get("member_id") or item.get("id") or item.get("handle") or item.get("name") or "").strip()
        description = str(item.get("description") or item.get("relationship") or "").strip()
        if not key or not description:
            continue
        member = member_by_id.get(key) or member_by_handle.get(key) or member_by_name.get(key)
        if member is not None:
            result[member.id] = description
    return result


def relationship_draft_participants(
    characters: list[CharacterSheet],
    persona: Any,
    state: dict[str, Any],
) -> list[dict[str, str]]:
    participants = [
        {
            "key": f"character:{sheet.id}",
            "id": sheet.id,
            "name": sheet.name,
            "summary": compact_character_summary(sheet),
            "kind": "character",
            "world_entry_type": state.get("entry_modes", {}).get(f"character:{sheet.id}", "native"),
            "arrival_reason": state.get("arrival_reasons", {}).get(f"character:{sheet.id}", ""),
            "adaptation_note": state.get("adaptation_notes", {}).get(f"character:{sheet.id}", ""),
        }
        for sheet in characters
    ]
    if persona is not None:
        participants.append(
            {
                "key": "user",
                "id": str(getattr(persona, "id", "") or "user"),
                "name": str(getattr(persona, "display_name", "") or getattr(persona, "name", "") or "ユーザー"),
                "summary": str(state.get("user_description_draft") or getattr(persona, "description", "") or ""),
                "kind": "user_persona",
                "world_entry_type": state.get("entry_modes", {}).get("user", "native"),
                "arrival_reason": state.get("arrival_reasons", {}).get("user", ""),
                "adaptation_note": state.get("adaptation_notes", {}).get("user", ""),
            }
        )
    return participants


def parse_relationship_draft_response(
    raw: str,
    participants: list[dict[str, str]],
) -> list[dict[str, str]]:
    parsed = try_parse_json_fragment(raw)
    if parsed is None:
        return []
    items = parsed.get("relationships") if isinstance(parsed, dict) else parsed
    if not isinstance(items, list):
        return []

    key_by_identifier: dict[str, str] = {}
    for item in participants:
        key = item["key"]
        key_by_identifier[key] = key
        key_by_identifier[item["id"]] = key
        key_by_identifier[item["name"]] = key

    drafts: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        first = relationship_key_from_item(
            item,
            key_by_identifier,
            (
                "participant_a_key",
                "a_key",
                "character_a_key",
                "participant_a",
                "a",
                "character_a_id",
                "character_a",
                "from",
            ),
        )
        second = relationship_key_from_item(
            item,
            key_by_identifier,
            (
                "participant_b_key",
                "b_key",
                "character_b_key",
                "participant_b",
                "b",
                "character_b_id",
                "character_b",
                "to",
            ),
        )
        description = str(
            item.get("description") or item.get("relationship") or item.get("relation") or item.get("summary") or ""
        ).strip()
        if first and second and description:
            drafts.append(
                {
                    "id": "",
                    "participant_a_key": first,
                    "participant_b_key": second,
                    "description": description,
                }
            )
    return drafts


def relationship_key_from_item(
    item: dict[str, Any],
    key_by_identifier: dict[str, str],
    candidate_keys: tuple[str, ...],
) -> str:
    for key in candidate_keys:
        value = item.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text in key_by_identifier:
            return key_by_identifier[text]
    return ""


def limit_relationship_drafts(
    drafts: list[dict[str, str]],
    valid_keys: set[str],
    *,
    existing: list[dict[str, str]] | None = None,
    max_per_participant: int = 2,
) -> list[dict[str, str]]:
    counts: dict[str, int] = {key: 0 for key in valid_keys}
    seen_pairs: set[frozenset[str]] = set()
    for item in existing or []:
        first = str(item.get("participant_a_key") or "")
        second = str(item.get("participant_b_key") or "")
        if first not in valid_keys or second not in valid_keys or first == second:
            continue
        seen_pairs.add(frozenset({first, second}))
        counts[first] = counts.get(first, 0) + 1
        counts[second] = counts.get(second, 0) + 1

    result: list[dict[str, str]] = []
    for item in drafts:
        first = str(item.get("participant_a_key") or "")
        second = str(item.get("participant_b_key") or "")
        description = str(item.get("description") or "").strip()
        if first not in valid_keys or second not in valid_keys or first == second or not description:
            continue
        pair_key = frozenset({first, second})
        if pair_key in seen_pairs:
            continue
        if counts.get(first, 0) >= max_per_participant or counts.get(second, 0) >= max_per_participant:
            continue
        seen_pairs.add(pair_key)
        counts[first] = counts.get(first, 0) + 1
        counts[second] = counts.get(second, 0) + 1
        result.append(
            {
                "id": str(item.get("id") or ""),
                "participant_a_key": first,
                "participant_b_key": second,
                "description": description,
            }
        )
    return result


def merge_relationship_drafts(
    state: dict[str, Any],
    relationships: list[dict[str, str]],
) -> None:
    for relationship in relationships:
        upsert_relationship_draft(state, relationship)


def upsert_relationship_draft(state: dict[str, Any], relationship: dict[str, str]) -> None:
    pair_key = frozenset(
        {
            relationship["participant_a_key"],
            relationship["participant_b_key"],
        }
    )
    relationship_id = str(relationship["id"])
    next_items: list[dict[str, str]] = []
    inserted = False
    for item in state.get("relationships", []):
        item_id = str(item.get("id") or "")
        item_pair = frozenset(
            {
                str(item.get("participant_a_key") or ""),
                str(item.get("participant_b_key") or ""),
            }
        )
        if item_id == relationship_id:
            next_items.append(relationship)
            inserted = True
        elif item_pair == pair_key:
            continue
        else:
            next_items.append(item)
    if not inserted:
        next_items.append(relationship)
    state["relationships"] = next_items


def next_relationship_draft_id(state: dict[str, Any]) -> str:
    state["relationship_sequence"] = int(state.get("relationship_sequence", 0)) + 1
    return f"draft-{state['relationship_sequence']}"
