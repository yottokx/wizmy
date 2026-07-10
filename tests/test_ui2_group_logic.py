"""ui2 グループ純ロジック(group_logic)のテスト。"""

from __future__ import annotations

import unittest

from src.ui2.group_logic import (
    HandleValidation,
    active_members,
    diff_html,
    draft_state_from_group,
    entry_type_label,
    group_participants,
    guide_actor_options,
    imitate_actor_options,
    mention_entries,
    next_speaker_candidate_ids,
    participant_by_speaker_id,
    relationship_key_map_for_group,
    validate_handle_values,
    world_source_options,
)
from tests.group_chat_test_helpers import make_group_chat, make_group_members, make_group_settings


class GroupParticipantsTest(unittest.TestCase):
    def test_group_participants_includes_members_and_persona(self) -> None:
        group = make_group_chat()
        participants = group_participants(group)
        self.assertEqual(3, len(participants))
        self.assertEqual("member:member-akari", participants[0]["key"])
        self.assertEqual("character", participants[0]["kind"])
        self.assertEqual("user:persona-sora", participants[2]["key"])
        self.assertEqual("user", participants[2]["kind"])

    def test_participant_by_speaker_id_resolves_member_and_persona(self) -> None:
        group = make_group_chat()
        participants = group_participants(group)
        member = participant_by_speaker_id(participants, "member-minato")
        self.assertIsNotNone(member)
        self.assertEqual("湊", member["name"])
        persona = participant_by_speaker_id(participants, "persona-sora")
        self.assertIsNotNone(persona)
        self.assertEqual("user", persona["kind"])
        self.assertIsNone(participant_by_speaker_id(participants, "missing"))

    def test_active_members_filters_by_settings(self) -> None:
        group = make_group_chat()
        settings = {"participant_ids": ["member-minato"]}
        active = active_members(group, settings)
        self.assertEqual(["member-minato"], [member.id for member in active])
        self.assertEqual([], active_members(group, None))

    def test_mention_entries_only_active_members_plus_persona(self) -> None:
        group = make_group_chat()
        entries = mention_entries(group, {"participant_ids": ["member-akari"]})
        self.assertEqual(["Akari", "Sora"], [entry["handle"] for entry in entries])
        # settings 無し(セッション未開始)は全員+ペルソナ
        entries = mention_entries(group, None)
        self.assertEqual(["Akari", "Minato", "Sora"], [entry["handle"] for entry in entries])


class NextSpeakerCandidateTest(unittest.TestCase):
    def test_user_mention_narrows_to_mentioned_member(self) -> None:
        members = make_group_members()
        messages = [{"role": "user", "text": "@Minato これ直せる?"}]
        self.assertEqual({"member-minato"}, next_speaker_candidate_ids(messages, members))

    def test_last_character_excluded_from_candidates(self) -> None:
        members = make_group_members()
        messages = [
            {"role": "user", "text": "ねえ"},
            {"role": "character", "speaker_id": "member-akari", "text": "はい"},
        ]
        self.assertEqual({"member-minato"}, next_speaker_candidate_ids(messages, members))

    def test_no_dialog_returns_all_active(self) -> None:
        members = make_group_members()
        messages = [{"role": "narration", "text": "夜が更ける。"}]
        self.assertEqual(
            {"member-akari", "member-minato"},
            next_speaker_candidate_ids(messages, members),
        )

    def test_empty_members_returns_empty(self) -> None:
        self.assertEqual(set(), next_speaker_candidate_ids([], []))


class HandleValidationTest(unittest.TestCase):
    def test_valid_handles(self) -> None:
        members = make_group_members()
        sheets = [member.character for member in members]
        result = validate_handle_values(
            sheets,
            {sheets[0].id: "Akari", sheets[1].id: "Minato"},
            "Sora",
        )
        self.assertTrue(result.ok)
        self.assertEqual(["Akari", "Minato"], result.handles)
        self.assertEqual("Sora", result.user_handle)

    def test_invalid_pattern_rejected(self) -> None:
        sheets = [make_group_members()[0].character]
        result = validate_handle_values(sheets, {sheets[0].id: "あ"}, "Sora")
        self.assertFalse(result.ok)
        self.assertIn("3〜12文字", result.error)

    def test_duplicate_with_reserved_rejected(self) -> None:
        sheets = [make_group_members()[0].character]
        result = validate_handle_values(sheets, {sheets[0].id: "Akari"}, None, reserved={"akari"})
        self.assertFalse(result.ok)
        self.assertIn("重複", result.error)

    def test_user_handle_duplicate_rejected(self) -> None:
        sheets = [make_group_members()[0].character]
        result = validate_handle_values(sheets, {sheets[0].id: "Sora"}, "Sora")
        self.assertFalse(result.ok)

    def test_member_only_validation_skips_user(self) -> None:
        sheets = [make_group_members()[0].character]
        result = validate_handle_values(sheets, {sheets[0].id: "Akari"}, None)
        self.assertEqual(HandleValidation(["Akari"], ""), result)


class OptionBuildersTest(unittest.TestCase):
    def test_world_source_options_only_sheets_with_world(self) -> None:
        members = make_group_members()
        sheets = [member.character for member in members]
        sheets[1].world = ""
        options = world_source_options(sheets)
        self.assertEqual(["new", f"character:{sheets[0].id}"], list(options))

    def test_guide_actor_options_orders_active_join_and_specials(self) -> None:
        group = make_group_chat()
        options = guide_actor_options(group, {"member-akari"})
        keys = list(options)
        self.assertEqual("auto", keys[0])
        self.assertIn("member:member-akari", keys)
        self.assertIn("join:member-minato", keys)
        self.assertEqual(["guest", "narration", "user"], keys[-3:])

    def test_imitate_actor_options_has_no_narration_or_user(self) -> None:
        group = make_group_chat()
        options = imitate_actor_options(group, {"member-akari", "member-minato"})
        self.assertEqual(
            ["member:member-akari", "member:member-minato", "guest"],
            list(options),
        )

    def test_entry_type_labels(self) -> None:
        self.assertEqual("住人", entry_type_label("native"))
        self.assertEqual("来訪者", entry_type_label("visitor"))
        self.assertEqual("世界の土台", entry_type_label("world_source"))
        self.assertEqual("適応", entry_type_label(""))


class RelationshipDraftMappingTest(unittest.TestCase):
    def test_key_map_and_reverse_state(self) -> None:
        group = make_group_chat()
        mapping = relationship_key_map_for_group(group)
        self.assertEqual("member:member-akari", mapping["character:character-akari"])
        self.assertEqual("user:persona-sora", mapping["user"])
        state = draft_state_from_group(group)
        keys = {
            (item["participant_a_key"], item["participant_b_key"])
            for item in state["relationships"]
        }
        self.assertIn(("character:character-akari", "character:character-minato"), keys)
        self.assertIn(("character:character-akari", "user"), keys)


class DiffHtmlTest(unittest.TestCase):
    def test_diff_html_marks_add_and_del(self) -> None:
        html = diff_html("古い行\n共通行", "新しい行\n共通行")
        self.assertIn('class="del"', html)
        self.assertIn('class="add"', html)
        self.assertIn("新しい行", html)

    def test_diff_html_no_change(self) -> None:
        self.assertIn("変更なし", diff_html("同じ", "同じ"))

    def test_diff_html_escapes_markup(self) -> None:
        html = diff_html("", "<script>alert(1)</script>")
        self.assertNotIn("<script>", html)


class GroupSettingsHelperTest(unittest.TestCase):
    def test_helpers_align_with_fixture(self) -> None:
        group = make_group_chat()
        settings = make_group_settings()
        self.assertEqual(2, len(active_members(group, settings)))


if __name__ == "__main__":
    unittest.main()
