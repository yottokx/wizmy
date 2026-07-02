import pytest

from src.ui.pages import group_chat as group_chat_module
from src.ui.pages.group_chat import (
    _choose_weighted_speaker,
    _member_from_identifier,
    _member_from_llm_choice,
    _mentioned_member,
    _speaker_weights_from_llm_output,
    _try_parse_json_fragment,
)

from tests.group_chat_test_helpers import make_group_members


def test_member_from_llm_choice_accepts_handle_and_character_name() -> None:
    members = make_group_members()

    assert _member_from_llm_choice("次は @Akari が自然です。", members) == members[0]
    assert _member_from_llm_choice("ここは湊が返します。", members) == members[1]
    assert _member_from_llm_choice("誰でもありません", members) is None


def test_member_from_identifier_accepts_id_handle_and_name() -> None:
    members = make_group_members()

    assert _member_from_identifier("member-akari", members) == members[0]
    assert _member_from_identifier("@Minato", members) == members[1]
    assert _member_from_identifier("灯里", members) == members[0]
    assert _member_from_identifier("unknown", members) is None


def test_mentioned_member_uses_first_known_handle() -> None:
    members = make_group_members()

    assert _mentioned_member("@Nobody から @Minato に渡す。", members) == members[1]
    assert _mentioned_member("メンションなし", members) is None


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
    assert _speaker_weights_from_llm_output(raw, make_group_members()) == expected


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
    assert _try_parse_json_fragment(raw) == expected


@pytest.mark.parametrize(
    ("roll", "expected_id"),
    [
        (0.1, "member-akari"),
        (0.9, "member-minato"),
    ],
)
def test_choose_weighted_speaker_is_deterministic_with_monkeypatched_random(
    monkeypatch: pytest.MonkeyPatch,
    roll: float,
    expected_id: str,
) -> None:
    members = make_group_members()
    monkeypatch.setattr(group_chat_module.random, "random", lambda: roll)

    selected, normalized, actual_roll = _choose_weighted_speaker(
        {"member-akari": 1.0, "member-minato": 3.0},
        members,
    )

    assert selected.id == expected_id
    assert [(member.id, weight, percent) for member, weight, percent in normalized] == [
        ("member-akari", 1.0, 25.0),
        ("member-minato", 3.0, 75.0),
    ]
    assert actual_roll == roll


def test_choose_weighted_speaker_uses_equal_weights_when_all_weights_are_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    members = make_group_members()
    monkeypatch.setattr(group_chat_module.random, "random", lambda: 0.75)

    selected, normalized, roll = _choose_weighted_speaker({}, members)

    assert selected == members[1]
    assert [(member.id, weight, percent) for member, weight, percent in normalized] == [
        ("member-akari", 1.0, 50.0),
        ("member-minato", 1.0, 50.0),
    ]
    assert roll == 0.75


def test_choose_weighted_speaker_rejects_empty_candidates() -> None:
    with pytest.raises(ValueError, match="発言候補がありません"):
        _choose_weighted_speaker({}, [])
