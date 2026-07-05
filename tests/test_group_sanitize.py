import pytest

from src.core.conversation import history as history_module
from src.core.conversation.history import (
    debug_from_dict,
    group_message,
    last_dialog_message,
    latest_group_message_preview,
    optional_int,
)
from src.core.conversation.sanitize import (
    clean_arrival_reason_response,
    clean_character_markdown_response,
    clean_guest_name,
    clean_persona_description_response,
    clean_relationship_enhancement,
    guest_name_from_actor_text,
    sanitize_group_character_reply,
    sanitize_group_guest_reply,
    sanitize_group_narration,
)
from src.core.conversation.schemas import ChatDebugInfo
from tests.group_chat_test_helpers import make_group_chat


def test_sanitize_group_character_reply_removes_current_prefixes() -> None:
    member = make_group_chat().members[0]

    assert sanitize_group_character_reply("灯里: 「この棚はまだ起きています」", member) == "この棚はまだ起きています"
    assert sanitize_group_character_reply("@Akari: まだ明かりは消しません。", member) == "まだ明かりは消しません。"


def test_sanitize_group_guest_reply_removes_current_prefixes() -> None:
    assert (
        sanitize_group_guest_reply("巡回司書【ゲスト】: 「そろそろ閉館です」", "guest:巡回司書") == "そろそろ閉館です"
    )
    assert sanitize_group_guest_reply("巡回司書: 星図は返却台へ。", "巡回司書") == "星図は返却台へ。"


def test_sanitize_group_narration_removes_current_labels() -> None:
    assert sanitize_group_narration("地の文: 窓の外で星が瞬いた。") == "窓の外で星が瞬いた。"
    assert sanitize_group_narration("```text\nナラティブ: 天球儀が静かに回る。\n```") == "天球儀が静かに回る。"


def test_guest_name_helpers_keep_current_notation() -> None:
    assert clean_guest_name("guest: 巡回司書") == "巡回司書"
    assert clean_guest_name("巡回司書【ゲスト】") == "巡回司書"
    assert guest_name_from_actor_text("guest：巡回司書") == "巡回司書"
    assert guest_name_from_actor_text("巡回司書【ゲスト】") == "巡回司書"
    assert guest_name_from_actor_text("巡回司書") == ""


def test_auxiliary_cleaners_keep_current_labels_and_json_handling() -> None:
    assert (
        clean_character_markdown_response('```json\n{"sheet":"# 灯里\\n星図を読む。"}\n```') == "# 灯里\n星図を読む。"
    )
    assert clean_persona_description_response("説明: 星空を記録する観察者。") == "星空を記録する観察者。"
    assert clean_arrival_reason_response("理由: 星図を届けに来た。") == "星図を届けに来た。"
    assert clean_relationship_enhancement("関係性: 互いに秘密を共有している。") == "互いに秘密を共有している。"


def test_group_message_serializes_member_user_guest_and_debug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group = make_group_chat()
    member = group.members[0]
    user = group.user_persona
    assert user is not None
    monkeypatch.setattr(history_module, "time_label", lambda: "12:34")
    debug = ChatDebugInfo(
        llm_input="入力",
        raw_output="出力",
        reasoning_output="理由",
        input_tokens=1,
        output_tokens=2,
        total_tokens=3,
    )
    speaker_debug = ChatDebugInfo(llm_input="話者入力", raw_output="話者出力")

    assert group_message(
        "character", "星図が揺れています。", member=member, debug=debug, speaker_debug=speaker_debug
    ) == {
        "role": "character",
        "text": "星図が揺れています。",
        "time_label": "12:34",
        "speaker_id": "member-akari",
        "speaker_name": "灯里",
        "handle": "Akari",
        "debug": {
            "llm_input": "入力",
            "raw_output": "出力",
            "reasoning_output": "理由",
            "input_tokens": 1,
            "output_tokens": 2,
            "total_tokens": 3,
        },
        "speaker_debug": {
            "llm_input": "話者入力",
            "raw_output": "話者出力",
            "reasoning_output": "",
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
        },
    }
    assert group_message("user", "記録します。", user=user) == {
        "role": "user",
        "text": "記録します。",
        "time_label": "12:34",
        "speaker_id": "persona-sora",
        "speaker_name": "ソラ",
        "handle": "Sora",
    }
    assert group_message("guest", "閉館です。", guest_name="guest:巡回司書") == {
        "role": "guest",
        "text": "閉館です。",
        "time_label": "12:34",
        "speaker_id": "guest:巡回司書",
        "speaker_name": "巡回司書【ゲスト】",
        "guest_name": "巡回司書",
        "handle": "",
    }


def test_debug_from_dict_and_optional_int_keep_current_fallbacks() -> None:
    debug = debug_from_dict(
        {
            "llm_input": "入力",
            "raw_output": "出力",
            "reasoning_output": "理由",
            "input_tokens": "10",
            "output_tokens": "bad",
            "total_tokens": None,
        }
    )

    assert debug == ChatDebugInfo(
        llm_input="入力",
        raw_output="出力",
        reasoning_output="理由",
        input_tokens=10,
        output_tokens=None,
        total_tokens=None,
    )
    assert debug_from_dict("not dict") is None
    assert optional_int("42") == 42
    assert optional_int("bad") is None


def test_group_message_preview_and_last_dialog_message_keep_current_filters() -> None:
    messages = [
        {"role": "system", "text": "システム通知"},
        {"role": "narration", "text": "天球儀が光った。"},
        {"role": "memo", "text": "メモ"},
        {"role": "guest", "speaker_name": "巡回司書【ゲスト】", "text": "閉館の鐘が鳴ります。"},
    ]

    assert latest_group_message_preview([]) == "まだ発言がありません"
    assert latest_group_message_preview(messages, limit=16) == "巡回司書【ゲスト】: 閉館の鐘…"
    assert last_dialog_message(messages) == messages[-1]
    assert last_dialog_message([{"role": "narration", "text": "静かだった。"}]) is None
