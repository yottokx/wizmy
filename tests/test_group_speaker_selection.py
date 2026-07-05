import random

import pytest

from src.core.conversation.speaker_selection import (
    choose_weighted_speaker,
    collect_speaker_weight_entries,
    format_speaker_selection_debug,
    member_from_identifier,
    member_from_llm_choice,
    mentioned_member,
    number_from_weight_value,
    speaker_identifier_from_dict,
    speaker_weight_from_dict,
    speaker_weights_from_llm_output,
    try_parse_json_fragment,
)
from tests.group_chat_test_helpers import make_group_members


def test_member_from_llm_choice_accepts_handle_and_character_name() -> None:
    members = make_group_members()

    assert member_from_llm_choice("次は @Akari が自然です。", members) == members[0]
    assert member_from_llm_choice("ここは湊が返します。", members) == members[1]
    assert member_from_llm_choice("誰でもありません", members) is None


def test_member_from_identifier_accepts_id_handle_and_name() -> None:
    members = make_group_members()

    assert member_from_identifier("member-akari", members) == members[0]
    assert member_from_identifier("@Minato", members) == members[1]
    assert member_from_identifier("灯里", members) == members[0]
    assert member_from_identifier("unknown", members) is None


def test_mentioned_member_uses_first_known_handle() -> None:
    members = make_group_members()

    assert mentioned_member("@Nobody から @Minato に渡す。", members) == members[1]
    assert mentioned_member("メンションなし", members) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Akari", {"member-akari": 2.0, "member-minato": 1.0}),
        ("次は灯里です。", {"member-akari": 2.0, "member-minato": 1.0}),
        ('{"handle":"Minato","weight":3}', {"member-minato": 3.0}),
        (
            '[{"id":"member-akari","score":4},{"handle":"Minato","score":"2"}]',
            {"member-akari": 4.0, "member-minato": 2.0},
        ),
        ("候補: {\"member_id\":\"member-minato\",\"possibility\":5} です", {"member-minato": 5.0}),
        ("本文\n[[\"Akari\", 1.5], [\"Minato\", \"2.5\"]]", {"member-akari": 1.5, "member-minato": 2.5}),
        ("@Akari 70%\n@Minato 30%", {"member-akari": 70.0, "member-minato": 30.0}),
        ("灯里: 1.5\n湊: 2", {"member-akari": 1.5, "member-minato": 2.0}),
        ("誰でもよい", {}),
        ('{"handle":"Unknown","weight":10}', {}),
    ],
)
def test_speaker_weights_from_llm_output_covers_current_patterns(raw: str, expected: dict[str, float]) -> None:
    assert speaker_weights_from_llm_output(raw, make_group_members()) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"handle":"Akari","weight":2}', {"handle": "Akari", "weight": 2}),
        ('```json\n{"handle":"Minato","weight":4}\n```', {"handle": "Minato", "weight": 4}),
        ("前置き {\"member_id\":\"member-akari\",\"score\":3} 後置き", {"member_id": "member-akari", "score": 3}),
        ("json ではない", None),
    ],
)
def test_try_parse_json_fragment_returns_current_parse_result(raw: str, expected) -> None:
    assert try_parse_json_fragment(raw) == expected


def test_collect_speaker_weight_entries_recurses_current_patterns() -> None:
    value = {
        "weights": [
            {"handle": "Akari", "weight": "2.5"},
            {"speaker_id": "member-minato", "chance": 0},
            {"Minato": 3},
        ]
    }

    assert collect_speaker_weight_entries(value) == [
        ("Akari", 2.5),
        ("weight", 2.5),
        ("Minato", 3.0),
    ]


def test_speaker_weight_helpers_keep_current_parsing() -> None:
    assert speaker_identifier_from_dict({"candidate": " Akari "}) == "Akari"
    assert speaker_weight_from_dict({"percent": "70%"}) == 70.0
    assert number_from_weight_value(True) is None
    assert number_from_weight_value("-1") is None
    assert number_from_weight_value("1.5") == 1.5


@pytest.mark.parametrize(
    ("seed", "expected_id"),
    [
        (1, "member-akari"),
        (2, "member-minato"),
    ],
)
def test_choose_weighted_speaker_is_deterministic_with_seeded_rng(
    seed: int,
    expected_id: str,
) -> None:
    members = make_group_members()
    expected_roll = random.Random(seed).random()

    selected, normalized, actual_roll = choose_weighted_speaker(
        {"member-akari": 1.0, "member-minato": 3.0},
        members,
        rng=random.Random(seed),
    )

    assert selected.id == expected_id
    assert [(member.id, weight, percent) for member, weight, percent in normalized] == [
        ("member-akari", 1.0, 25.0),
        ("member-minato", 3.0, 75.0),
    ]
    assert actual_roll == expected_roll


def test_choose_weighted_speaker_uses_equal_weights_when_all_weights_are_zero() -> None:
    members = make_group_members()
    seed = 0
    expected_roll = random.Random(seed).random()

    selected, normalized, roll = choose_weighted_speaker({}, members, rng=random.Random(seed))

    assert selected == members[1]
    assert [(member.id, weight, percent) for member, weight, percent in normalized] == [
        ("member-akari", 1.0, 50.0),
        ("member-minato", 1.0, 50.0),
    ]
    assert roll == expected_roll


def test_format_speaker_selection_debug_keeps_current_text() -> None:
    members = make_group_members()
    selected, normalized, roll = choose_weighted_speaker(
        {"member-akari": 1.0, "member-minato": 3.0},
        members,
        rng=random.Random(1),
    )

    assert format_speaker_selection_debug(" raw ", normalized, selected, roll) == (
        "raw\n"
        "\n"
        "--- 内部抽選 ---\n"
        "乱数: 0.1344\n"
        "発言可能性:\n"
        "- @Akari / 灯里: 1 (25.0%)\n"
        "- @Minato / 湊: 3 (75.0%)\n"
        "選択: @Akari / 灯里"
    )


def test_choose_weighted_speaker_rejects_empty_candidates() -> None:
    with pytest.raises(ValueError, match="発言候補がありません"):
        choose_weighted_speaker({}, [])
