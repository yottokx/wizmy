import tempfile
import unittest
from pathlib import Path

from src.core.character.schemas import (
    CHARACTER_TTS_API_GEN_SERVER,
    CharacterImageAsset,
    CharacterMedia,
    CharacterSheet,
    CharacterTTSSettings,
    FaceRect,
    GenerationMeta,
)
from src.core.chat.schemas import UserPersona
from src.core.conversation.history import (
    format_group_history,
    group_message,
    group_system_event_message,
    settings_with_participant,
    settings_without_participant,
)
from src.core.conversation.prompts.group import (
    format_group_participant_overview,
    format_group_relationship_section,
)
from src.core.conversation.sanitize import (
    clean_relationship_enhancement,
    guest_display_name,
    guest_name_from_actor_text,
)
from src.core.group_chat.schemas import (
    GroupChatRecord,
    GroupMember,
    GroupRelationship,
    GroupUserPersona,
)
from src.services.group_chat import GroupChatService
from src.storage.group_chat_repository import GroupChatRepository
from src.ui.pages.group_chat import (
    _clean_generated_group_name,
    _format_optional_instruction,
    _group_relationship_enhancement_participants,
    _guest_prefix_completion,
    _limit_relationship_drafts,
    _parse_relationship_draft_response,
    _prepare_group_character_for_world,
    _prepare_group_user_world_settings,
    _relationship_draft_participants,
    _world_source_options_for_characters,
)


class GroupChatServiceTest(unittest.IsolatedAsyncioTestCase):
    def test_world_source_options_include_only_characters_with_world(self) -> None:
        options = _world_source_options_for_characters([
            CharacterSheet(id="character-a", name="世界あり", world="共有する世界"),
            CharacterSheet(id="character-b", name="世界なし", world=""),
            CharacterSheet(id="character-c", name="空白のみ", world="  "),
        ])

        self.assertEqual("完全に新しいワールド", options["new"])
        self.assertIn("character:character-a", options)
        self.assertNotIn("character:character-b", options)
        self.assertNotIn("character:character-c", options)

    def test_prepare_group_character_native_removes_world_and_preserves_metadata(self) -> None:
        original = CharacterSheet(
            id="character-1",
            name="テスト人物",
            world="元の世界",
            raw_markdown=(
                "# テスト人物\n\n"
                "## 世界観・舞台\n"
                "元の世界\n\n"
                "## 性格・内面\n"
                "穏やか。"
            ),
            tags=["tag-a"],
            is_favorite=True,
            generation_meta=GenerationMeta(model_id="model-a"),
        )

        updated, settings = _prepare_group_character_for_world(
            original,
            world="新しいワールド",
            source_character_id="",
            entry_type="native",
            arrival_reason="使われない理由",
            adaptation_note="承認済み",
        )

        self.assertEqual("", updated.world)
        self.assertNotIn("## 世界観・舞台", updated.raw_markdown)
        self.assertNotIn("元の世界", updated.raw_markdown)
        self.assertNotIn("新しいワールド", updated.raw_markdown)
        self.assertNotIn("この世界に来た理由", updated.raw_markdown)
        self.assertEqual(["tag-a"], updated.tags)
        self.assertTrue(updated.is_favorite)
        self.assertEqual("model-a", updated.generation_meta.model_id)
        self.assertEqual("native", settings["world_entry_type"])
        self.assertEqual("", settings["arrival_reason"])

    def test_prepare_group_character_world_source_removes_world(self) -> None:
        original = CharacterSheet(
            id="character-source",
            name="引き継ぎ元",
            world="引き継ぐワールド",
            raw_markdown=(
                "# 引き継ぎ元\n\n"
                "## 世界観・舞台\n"
                "引き継ぐワールド\n\n"
                "## 性格・内面\n"
                "明るい。"
            ),
        )

        updated, settings = _prepare_group_character_for_world(
            original,
            world="引き継ぐワールド",
            source_character_id="character-source",
            entry_type="world_source",
            arrival_reason="",
            adaptation_note="",
        )

        self.assertEqual("", updated.world)
        self.assertNotIn("## 世界観・舞台", updated.raw_markdown)
        self.assertNotIn("引き継ぐワールド", updated.raw_markdown)
        self.assertEqual("world_source", settings["world_entry_type"])

    def test_prepare_group_character_visitor_keeps_world_and_adds_arrival_reason(self) -> None:
        original = CharacterSheet(
            id="character-1",
            name="来訪者",
            world="元の世界",
            raw_markdown=(
                "# 来訪者\n\n"
                "## 世界観・舞台\n"
                "元の世界\n\n"
                "## 性格・内面\n"
                "冷静。"
            ),
        )

        updated, settings = _prepare_group_character_for_world(
            original,
            world="新しいワールド",
            source_character_id="",
            entry_type="visitor",
            arrival_reason="門を抜けて迷い込んだ。",
            adaptation_note="",
        )

        self.assertEqual("元の世界", updated.world)
        self.assertIn("## 世界観・舞台\n元の世界", updated.raw_markdown)
        self.assertIn("## この世界に来た理由\n門を抜けて迷い込んだ。", updated.raw_markdown)
        self.assertEqual("visitor", settings["world_entry_type"])
        self.assertEqual("門を抜けて迷い込んだ。", settings["arrival_reason"])

    def test_prepare_group_user_world_settings_reflects_visitor_reason(self) -> None:
        persona = UserPersona(
            id="persona-1",
            name="ユーザー",
            description="元の説明",
        )

        settings = _prepare_group_user_world_settings(
            persona,
            world="新しいワールド",
            entry_type="visitor",
            arrival_reason="依頼を受けて訪れた。",
            adaptation_note="",
            description_override="調整済みの説明",
        )

        self.assertEqual("visitor", settings["world_entry_type"])
        self.assertEqual("依頼を受けて訪れた。", settings["arrival_reason"])
        self.assertNotIn("元の説明", settings["description"])
        self.assertEqual("調整済みの説明", settings["description"])
        self.assertNotIn("ワールド参加設定", settings["description"])
        self.assertNotIn("この世界に来た理由", settings["description"])
        self.assertNotIn("補足:", settings["description"])

    def test_group_participant_overview_uses_user_arrival_reason_without_mutating_description(self) -> None:
        group = GroupChatRecord(
            id="group-1",
            name="テストグループ",
            user_persona=GroupUserPersona(
                id="persona-1",
                handle="User",
                name="ユーザー",
                description="調整済みの説明",
                world_entry_type="visitor",
                arrival_reason="依頼を受けて訪れた。",
                world_adaptation_note="LLM改変を承認済み",
            ),
        )

        overview = format_group_participant_overview(group, {})

        self.assertIn("調整済みの説明", overview)
        self.assertIn("この世界に来た理由: 依頼を受けて訪れた。", overview)
        self.assertNotIn("ワールド参加設定", overview)
        self.assertNotIn("補足:", overview)
        self.assertEqual("調整済みの説明", group.user_persona.description)

    def test_optional_instruction_is_only_rendered_when_present(self) -> None:
        self.assertEqual("", _format_optional_instruction(""))
        self.assertEqual("追加指示:\n口調は変えない\n\n", _format_optional_instruction("  口調は変えない  "))

    def test_clean_generated_group_name_removes_label_and_json(self) -> None:
        self.assertEqual("薄明図書館の盟友", _clean_generated_group_name("グループ名: 薄明図書館の盟友"))
        self.assertEqual("星屑街の夜会", _clean_generated_group_name('{"name":"星屑街の夜会"}'))

    def test_relationship_draft_participants_use_updated_descriptions(self) -> None:
        participants = _relationship_draft_participants(
            [
                CharacterSheet(
                    id="character-a",
                    name="調整後の名前",
                    personality="調整後の人物像",
                )
            ],
            UserPersona(id="persona-1", name="ユーザー", description="元の説明"),
            {
                "entry_modes": {"character:character-a": "native", "user": "native"},
                "arrival_reasons": {},
                "adaptation_notes": {"character:character-a": "承認済み"},
                "user_description_draft": "調整後のユーザーペルソナ説明",
            },
        )

        self.assertEqual("調整後の名前", participants[0]["name"])
        self.assertIn("調整後の人物像", participants[0]["summary"])
        self.assertEqual("調整後のユーザーペルソナ説明", participants[1]["summary"])

    def test_parse_relationship_draft_response_maps_user_persona(self) -> None:
        participants = [
            {"key": "character:a", "id": "a", "name": "アリス"},
            {"key": "user", "id": "persona-1", "name": "ユーザー"},
        ]

        drafts = _parse_relationship_draft_response(
            '{"relationships":[{"participant_a_key":"アリス","participant_b_key":"ユーザー","description":"協力者"}]}',
            participants,
        )

        self.assertEqual(
            [
                {
                    "id": "",
                    "participant_a_key": "character:a",
                    "participant_b_key": "user",
                    "description": "協力者",
                }
            ],
            drafts,
        )

    def test_limit_relationship_drafts_removes_invalid_pairs_and_caps_degree(self) -> None:
        valid_keys = {
            "character:a",
            "character:b",
            "character:c",
            "character:d",
            "user",
        }
        drafts = [
            {"id": "", "participant_a_key": "character:a", "participant_b_key": "character:a", "description": "自己"},
            {"id": "", "participant_a_key": "character:a", "participant_b_key": "character:b", "description": "A-B"},
            {"id": "", "participant_a_key": "character:b", "participant_b_key": "character:a", "description": "重複"},
            {"id": "", "participant_a_key": "character:a", "participant_b_key": "character:c", "description": "A-C"},
            {"id": "", "participant_a_key": "character:a", "participant_b_key": "character:d", "description": "A-D"},
            {"id": "", "participant_a_key": "character:b", "participant_b_key": "character:c", "description": "B-C"},
            {"id": "", "participant_a_key": "user", "participant_b_key": "character:d", "description": "User-D"},
            {"id": "", "participant_a_key": "character:x", "participant_b_key": "character:c", "description": "不明"},
        ]

        limited = _limit_relationship_drafts(drafts, valid_keys, max_per_participant=2)

        self.assertEqual(
            [
                ("character:a", "character:b", "A-B"),
                ("character:a", "character:c", "A-C"),
                ("character:b", "character:c", "B-C"),
                ("user", "character:d", "User-D"),
            ],
            [
                (item["participant_a_key"], item["participant_b_key"], item["description"])
                for item in limited
            ],
        )
        counts = {key: 0 for key in valid_keys}
        for item in limited:
            counts[item["participant_a_key"]] += 1
            counts[item["participant_b_key"]] += 1
        self.assertLessEqual(max(counts.values()), 2)

    def test_clean_relationship_enhancement_removes_label(self) -> None:
        self.assertEqual(
            "互いに秘密を共有している。",
            clean_relationship_enhancement("関係性: 互いに秘密を共有している。"),
        )

    async def test_create_group_stores_world_settings_and_relationship_drafts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = GroupChatService(GroupChatRepository(Path(tmp_dir) / "wizmy.db"))
            await service.initialize()

            source = CharacterSheet(id="character-source", name="継承元", world="継承ワールド")
            visitor = CharacterSheet(id="character-visitor", name="来訪者", world="元の世界")
            native = CharacterSheet(id="character-native", name="住人", world="別世界")

            group = await service.create_group(
                name="テストグループ",
                world="継承ワールド",
                completion_profile_id="profile-1",
                members=[(source, "Source"), (visitor, "Visitor"), (native, "Native")],
                user_persona=UserPersona(id="persona-1", name="ユーザー", description="元の説明"),
                user_handle="User",
                world_source_type="character",
                world_source_character_id="character-source",
                member_world_settings={
                    "character-source": {"world_entry_type": "world_source"},
                    "character-visitor": {
                        "world_entry_type": "visitor",
                        "arrival_reason": "理由",
                        "world_adaptation_note": "補足",
                    },
                    "character-native": {"world_entry_type": "native"},
                },
                user_world_settings={
                    "world_entry_type": "visitor",
                    "arrival_reason": "ユーザー理由",
                    "description": "元の説明",
                },
                relationships=[
                    GroupRelationship(
                        id="draft-1",
                        participant_a_key="character:character-source",
                        participant_b_key="character:character-visitor",
                        description="最初の関係",
                    ),
                    GroupRelationship(
                        id="draft-2",
                        participant_a_key="character:character-visitor",
                        participant_b_key="character:character-source",
                        description="重複の関係",
                    ),
                    GroupRelationship(
                        id="draft-3",
                        participant_a_key="character:character-source",
                        participant_b_key="character:character-source",
                        description="自己関係",
                    ),
                    GroupRelationship(
                        id="draft-4",
                        participant_a_key="character:character-native",
                        participant_b_key="user",
                        description="ユーザーとの関係",
                    ),
                ],
            )

            reloaded = await service.get(group.id)
            self.assertIsNotNone(reloaded)
            assert reloaded is not None
            self.assertEqual("character", reloaded.world_source_type)
            self.assertEqual("character-source", reloaded.world_source_character_id)

            members_by_source = {member.source_character_id: member for member in reloaded.members}
            self.assertEqual("world_source", members_by_source["character-source"].world_entry_type)
            self.assertEqual("visitor", members_by_source["character-visitor"].world_entry_type)
            self.assertEqual("理由", members_by_source["character-visitor"].arrival_reason)
            self.assertEqual("native", members_by_source["character-native"].world_entry_type)

            self.assertIsNotNone(reloaded.user_persona)
            assert reloaded.user_persona is not None
            self.assertEqual("visitor", reloaded.user_persona.world_entry_type)
            self.assertEqual("ユーザー理由", reloaded.user_persona.arrival_reason)
            self.assertEqual("元の説明", reloaded.user_persona.description)
            self.assertNotIn("ワールド参加設定", reloaded.user_persona.description)
            self.assertNotIn("補足:", reloaded.user_persona.description)

            self.assertEqual(2, len(reloaded.relationships))
            self.assertTrue(all(not item.id.startswith("draft-") for item in reloaded.relationships))
            source_key = f"member:{members_by_source['character-source'].id}"
            visitor_key = f"member:{members_by_source['character-visitor'].id}"
            native_key = f"member:{members_by_source['character-native'].id}"
            user_key = f"user:{reloaded.user_persona.id}"
            pairs = {
                frozenset({item.participant_a_key, item.participant_b_key})
                for item in reloaded.relationships
            }
            self.assertEqual(
                {frozenset({source_key, visitor_key}), frozenset({native_key, user_key})},
                pairs,
            )

    async def test_update_member_character_updates_group_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = GroupChatService(GroupChatRepository(Path(tmp_dir) / "wizmy.db"))
            await service.initialize()

            original = CharacterSheet(
                id="character-1",
                name="元の名前",
                age="17",
                raw_markdown="# 元の名前",
            )
            group = await service.create_group(
                name="テストグループ",
                world="テスト用の世界",
                completion_profile_id="",
                members=[(original, "Alice")],
                user_persona=UserPersona(id="persona-1", name="テストユーザー"),
                user_handle="User",
            )

            updated = original.model_copy(
                update={
                    "name": "新しい名前",
                    "age": "18",
                    "raw_markdown": "# 新しい名前",
                },
                deep=True,
            )
            saved_member = await service.update_member_character(
                group.id,
                group.members[0].id,
                updated,
            )

            self.assertIsNotNone(saved_member)
            reloaded = await service.get(group.id)
            self.assertIsNotNone(reloaded)
            assert reloaded is not None
            member = reloaded.members[0]
            self.assertEqual("Alice", member.handle)
            self.assertEqual("character-1", member.source_character_id)
            self.assertEqual("新しい名前", member.character.name)
            self.assertEqual("18", member.character.age)

    async def test_update_member_character_returns_none_for_missing_member(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = GroupChatService(GroupChatRepository(Path(tmp_dir) / "wizmy.db"))
            await service.initialize()

            result = await service.update_member_character(
                "missing-group",
                "missing-member",
                CharacterSheet(id="character-1", name="名前"),
            )

            self.assertIsNone(result)

    async def test_add_generated_member_adds_native_group_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = GroupChatService(GroupChatRepository(Path(tmp_dir) / "wizmy.db"))
            await service.initialize()

            group = await service.create_group(
                name="テストグループ",
                world="テスト用の世界",
                completion_profile_id="",
                members=[],
                user_persona=UserPersona(id="persona-1", name="テストユーザー"),
                user_handle="User",
            )
            generated = CharacterSheet(
                id="generated-1",
                name="生成キャラ",
                raw_markdown="# 生成キャラ",
            )

            saved_member = await service.add_generated_member(
                group.id,
                generated,
                "GenChar",
            )

            self.assertIsNotNone(saved_member)
            reloaded = await service.get(group.id)
            self.assertIsNotNone(reloaded)
            assert reloaded is not None
            self.assertEqual(1, len(reloaded.members))
            member = reloaded.members[0]
            self.assertEqual("", member.source_character_id)
            self.assertEqual("GenChar", member.handle)
            self.assertEqual("generated-1", member.character.id)
            self.assertEqual("native", member.world_entry_type)
            self.assertEqual("", member.arrival_reason)
            self.assertEqual("", member.world_adaptation_note)

    async def test_generated_related_member_relationships_can_be_saved_for_all_bases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = GroupChatService(GroupChatRepository(Path(tmp_dir) / "wizmy.db"))
            await service.initialize()

            group = await service.create_group(
                name="テストグループ",
                world="テスト用の世界",
                completion_profile_id="",
                members=[
                    (CharacterSheet(id="character-1", name="ベース1"), "BaseOne"),
                    (CharacterSheet(id="character-2", name="ベース2"), "BaseTwo"),
                ],
                user_persona=UserPersona(id="persona-1", name="テストユーザー"),
                user_handle="User",
            )
            generated_member = await service.add_generated_member(
                group.id,
                CharacterSheet(id="generated-1", name="関連キャラ"),
                "Related",
            )
            self.assertIsNotNone(generated_member)
            assert generated_member is not None

            for base in group.members:
                await service.save_relationship(
                    group.id,
                    GroupRelationship(
                        id="",
                        participant_a_key=f"member:{generated_member.id}",
                        participant_b_key=f"member:{base.id}",
                        description=f"{base.character.name}との関係",
                    ),
                )

            reloaded = await service.get(group.id)
            self.assertIsNotNone(reloaded)
            assert reloaded is not None
            pairs = {
                frozenset({item.participant_a_key, item.participant_b_key})
                for item in reloaded.relationships
            }
            self.assertEqual(
                {
                    frozenset({f"member:{generated_member.id}", f"member:{group.members[0].id}"}),
                    frozenset({f"member:{generated_member.id}", f"member:{group.members[1].id}"}),
                },
                pairs,
            )

    async def test_group_member_image_bytes_are_saved_without_deleting_source_media(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir) / "data"
            service = GroupChatService(
                GroupChatRepository(Path(tmp_dir) / "wizmy.db"),
                data_dir,
            )
            await service.initialize()

            source_rel = Path("characters") / "character-1" / "images" / "source.png"
            source_path = data_dir / source_rel
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_bytes(b"source-image")
            original = CharacterSheet(
                id="character-1",
                name="画像テスト",
                media=CharacterMedia(
                    images=[
                        CharacterImageAsset(
                            id="source-image",
                            path=source_rel.as_posix(),
                            content_type="image/png",
                        )
                    ],
                    primary_image_id="source-image",
                ),
            )
            group = await service.create_group(
                name="テストグループ",
                world="テスト用の世界",
                completion_profile_id="",
                members=[(original, "Alice")],
                user_persona=UserPersona(id="persona-1", name="テストユーザー"),
                user_handle="User",
            )
            member_id = group.members[0].id

            saved = await service.save_member_image_bytes(
                group.id,
                member_id,
                b"group-image-1",
                filename="first.png",
                content_type="image/png",
                width=120,
                height=80,
            )

            self.assertIsNotNone(saved)
            assert saved is not None
            image = saved.character.media.primary_image()
            self.assertIsNotNone(image)
            assert image is not None
            self.assertTrue(image.path.startswith(f"groups/{group.id}/members/{member_id}/images/"))
            self.assertEqual(120, image.width)
            self.assertEqual(80, image.height)
            first_path = service.media_path(image.path)
            self.assertIsNotNone(first_path)
            assert first_path is not None
            self.assertEqual(b"group-image-1", first_path.read_bytes())
            self.assertEqual(b"source-image", source_path.read_bytes())

            saved_again = await service.save_member_image_bytes(
                group.id,
                member_id,
                b"group-image-2",
                filename="second.webp",
                content_type="image/webp",
            )

            self.assertIsNotNone(saved_again)
            self.assertFalse(first_path.exists())
            self.assertEqual(b"source-image", source_path.read_bytes())

    async def test_group_member_voice_rect_and_tts_settings_are_saved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir) / "data"
            service = GroupChatService(
                GroupChatRepository(Path(tmp_dir) / "wizmy.db"),
                data_dir,
            )
            await service.initialize()

            group = await service.create_group(
                name="テストグループ",
                world="テスト用の世界",
                completion_profile_id="",
                members=[(CharacterSheet(id="character-1", name="音声テスト"), "Alice")],
                user_persona=UserPersona(id="persona-1", name="テストユーザー"),
                user_handle="User",
            )
            member_id = group.members[0].id
            await service.save_member_image_bytes(group.id, member_id, b"image", width=256, height=128)

            saved_voice = await service.save_member_voice_bytes(
                group.id,
                member_id,
                b"voice-bytes",
                filename="voice.wav",
                content_type="audio/wav",
            )
            self.assertIsNotNone(saved_voice)
            assert saved_voice is not None
            voice = saved_voice.character.media.primary_voice()
            self.assertIsNotNone(voice)
            assert voice is not None
            self.assertTrue(voice.path.startswith(f"groups/{group.id}/members/{member_id}/voices/"))
            voice_path = service.media_path(voice.path)
            self.assertIsNotNone(voice_path)
            assert voice_path is not None
            self.assertEqual(b"voice-bytes", voice_path.read_bytes())

            updated_face = await service.update_member_face_rect(
                group.id,
                member_id,
                FaceRect(x=-0.5, y=0.25, width=2.0, height=1.0),
                image_width=256,
                image_height=128,
            )
            self.assertIsNotNone(updated_face)
            assert updated_face is not None
            image = updated_face.character.media.primary_image()
            self.assertIsNotNone(image)
            assert image is not None
            self.assertEqual(FaceRect(x=0.0, y=0.25, width=1.0, height=0.75), image.face_rect)

            updated_bust = await service.update_member_bust_rect(
                group.id,
                member_id,
                FaceRect(x=0.1, y=0.2, width=0.3, height=0.4),
            )
            self.assertIsNotNone(updated_bust)
            assert updated_bust is not None
            image = updated_bust.character.media.primary_image()
            self.assertIsNotNone(image)
            assert image is not None
            self.assertEqual(FaceRect(x=0.1, y=0.2, width=0.3, height=0.4), image.bust_rect)

            settings = CharacterTTSSettings(
                api_type=CHARACTER_TTS_API_GEN_SERVER,
                voice_caption="穏やかな声",
            )
            updated_tts = await service.update_member_tts_settings(group.id, member_id, settings)
            self.assertIsNotNone(updated_tts)
            assert updated_tts is not None
            self.assertEqual(CHARACTER_TTS_API_GEN_SERVER, updated_tts.character.media.tts.api_type)
            self.assertEqual("穏やかな声", updated_tts.character.media.tts.voice_caption)

            preview = service.save_member_tts_preview(group.id, member_id, b"preview")
            playback = service.save_member_tts_playback(group.id, member_id, b"playback")
            self.assertEqual(b"preview", preview.read_bytes())
            self.assertEqual(b"playback", playback.read_bytes())

    async def test_add_members_stores_world_entry_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = GroupChatService(GroupChatRepository(Path(tmp_dir) / "wizmy.db"))
            await service.initialize()

            group = await service.create_group(
                name="テストグループ",
                world="テスト用の世界",
                completion_profile_id="",
                members=[(CharacterSheet(id="character-1", name="既存キャラクター"), "Alice")],
                user_persona=UserPersona(id="persona-1", name="テストユーザー"),
                user_handle="User",
            )

            saved = await service.add_members(
                group.id,
                [(CharacterSheet(id="character-2", name="追加キャラクター"), "Visitor")],
                member_world_settings={
                    "character-2": {
                        "world_entry_type": "visitor",
                        "arrival_reason": "依頼を受けて来た。",
                        "world_adaptation_note": "来訪理由を設定",
                    }
                },
            )

            self.assertIsNotNone(saved)
            assert saved is not None
            added = saved.members[-1]
            self.assertEqual("character-2", added.source_character_id)
            self.assertEqual("visitor", added.world_entry_type)
            self.assertEqual("依頼を受けて来た。", added.arrival_reason)
            self.assertEqual("来訪理由を設定", added.world_adaptation_note)

            reloaded = await service.get(group.id)
            self.assertIsNotNone(reloaded)
            assert reloaded is not None
            self.assertEqual("visitor", reloaded.members[-1].world_entry_type)

    async def test_update_user_persona_updates_group_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = GroupChatService(GroupChatRepository(Path(tmp_dir) / "wizmy.db"))
            await service.initialize()

            group = await service.create_group(
                name="テストグループ",
                world="テスト用の世界",
                completion_profile_id="",
                members=[
                    (
                        CharacterSheet(id="character-1", name="キャラクター"),
                        "Alice",
                    )
                ],
                user_persona=UserPersona(
                    id="persona-1",
                    name="元の名前",
                    persona_name="元の表示名",
                    description="元の説明",
                ),
                user_handle="User",
            )

            assert group.user_persona is not None
            updated = group.user_persona.model_copy(
                update={
                    "handle": "Reader",
                    "name": "新しい名前",
                    "display_name": "新しい表示名",
                    "description": "新しい説明",
                },
                deep=True,
            )
            saved = await service.update_user_persona(group.id, updated)

            self.assertIsNotNone(saved)
            reloaded = await service.get(group.id)
            self.assertIsNotNone(reloaded)
            assert reloaded is not None
            self.assertIsNotNone(reloaded.user_persona)
            assert reloaded.user_persona is not None
            self.assertEqual("Reader", reloaded.user_persona.handle)
            self.assertEqual("新しい名前", reloaded.user_persona.name)
            self.assertEqual("新しい表示名", reloaded.user_persona.display_name)
            self.assertEqual("新しい説明", reloaded.user_persona.description)
            self.assertEqual("persona-1", reloaded.user_persona.source_persona_id)

    async def test_update_user_persona_returns_none_for_missing_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = GroupChatService(GroupChatRepository(Path(tmp_dir) / "wizmy.db"))
            await service.initialize()

            result = await service.update_user_persona(
                "missing-group",
                GroupUserPersona(id="persona-1", handle="User", name="名前"),
            )

            self.assertIsNone(result)

    async def test_save_relationship_replaces_same_pair_and_deletes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = GroupChatService(GroupChatRepository(Path(tmp_dir) / "wizmy.db"))
            await service.initialize()

            group = await service.create_group(
                name="テストグループ",
                world="テスト用の世界",
                completion_profile_id="",
                members=[
                    (CharacterSheet(id="character-1", name="キャラクター1"), "Alice"),
                    (CharacterSheet(id="character-2", name="キャラクター2"), "Bob"),
                ],
                user_persona=UserPersona(id="persona-1", name="テストユーザー"),
                user_handle="User",
            )
            first_key = f"member:{group.members[0].id}"
            second_key = f"member:{group.members[1].id}"

            saved = await service.save_relationship(
                group.id,
                GroupRelationship(
                    id="",
                    participant_a_key=first_key,
                    participant_b_key=second_key,
                    description="最初の関係",
                ),
            )
            self.assertIsNotNone(saved)
            assert saved is not None
            self.assertEqual(1, len(saved.relationships))
            first_id = saved.relationships[0].id

            replaced = await service.save_relationship(
                group.id,
                GroupRelationship(
                    id="",
                    participant_a_key=second_key,
                    participant_b_key=first_key,
                    description="更新後の関係",
                ),
            )
            self.assertIsNotNone(replaced)
            assert replaced is not None
            self.assertEqual(1, len(replaced.relationships))
            self.assertEqual("更新後の関係", replaced.relationships[0].description)

            deleted = await service.delete_relationship(group.id, replaced.relationships[0].id)
            self.assertIsNotNone(deleted)
            assert deleted is not None
            self.assertEqual([], deleted.relationships)
            self.assertNotEqual("", first_id)

    def test_relationship_section_includes_only_active_pairs(self) -> None:
        group = GroupChatRecord(
            id="group-1",
            name="テストグループ",
            members=[
                GroupMember(
                    id="member-a",
                    handle="Alice",
                    character=CharacterSheet(id="character-a", name="アリス"),
                ),
                GroupMember(
                    id="member-b",
                    handle="Bob",
                    character=CharacterSheet(id="character-b", name="ボブ"),
                ),
                GroupMember(
                    id="member-c",
                    handle="Carol",
                    character=CharacterSheet(id="character-c", name="キャロル"),
                ),
            ],
            user_persona=GroupUserPersona(
                id="persona-1",
                handle="User",
                name="ユーザー",
            ),
            relationships=[
                GroupRelationship(
                    id="relationship-1",
                    participant_a_key="member:member-a",
                    participant_b_key="member:member-b",
                    description="互いに信頼している",
                ),
                GroupRelationship(
                    id="relationship-2",
                    participant_a_key="member:member-a",
                    participant_b_key="member:member-c",
                    description="まだ距離がある",
                ),
                GroupRelationship(
                    id="relationship-3",
                    participant_a_key="member:member-b",
                    participant_b_key="user:persona-1",
                    description="昔からの知り合い",
                ),
            ],
        )

        section = format_group_relationship_section(
            group,
            {"participant_ids": ["member-a", "member-b"]},
        )

        self.assertIn("互いに信頼している", section)
        self.assertIn("昔からの知り合い", section)
        self.assertNotIn("まだ距離がある", section)

    def test_group_relationship_enhancement_participants_use_saved_group_keys(self) -> None:
        group = GroupChatRecord(
            id="group-1",
            name="テストグループ",
            members=[
                GroupMember(
                    id="member-a",
                    handle="Alice",
                    character=CharacterSheet(
                        id="character-a",
                        name="アリス",
                        personality="落ち着いている。",
                    ),
                    world_entry_type="visitor",
                    arrival_reason="依頼で来た。",
                ),
            ],
            user_persona=GroupUserPersona(
                id="persona-1",
                handle="User",
                name="ユーザー",
                description="観察者。",
                world_entry_type="native",
            ),
        )

        participants = _group_relationship_enhancement_participants(group)

        self.assertEqual("member:member-a", participants[0]["key"])
        self.assertEqual("character", participants[0]["kind"])
        self.assertEqual("visitor", participants[0]["world_entry_type"])
        self.assertEqual("依頼で来た。", participants[0]["arrival_reason"])
        self.assertEqual("user:persona-1", participants[1]["key"])
        self.assertEqual("user_persona", participants[1]["kind"])
        self.assertIn("観察者。", participants[1]["summary"])

    def test_system_event_is_included_in_group_history(self) -> None:
        history = format_group_history([
            group_system_event_message("アリスが入場しました"),
        ])

        self.assertIn("システム: アリスが入場しました", history)

    def test_guest_actor_text_accepts_prefix_and_suffix_notation(self) -> None:
        self.assertEqual("酒場のマスター", guest_name_from_actor_text("guest:酒場のマスター"))
        self.assertEqual("酒場のマスター", guest_name_from_actor_text("guest：酒場のマスター"))
        self.assertEqual("酒場のマスター", guest_name_from_actor_text("酒場のマスター【ゲスト】"))
        self.assertEqual("酒場のマスター【ゲスト】", guest_display_name("guest:酒場のマスター"))

    def test_guest_message_is_included_in_group_history(self) -> None:
        history = format_group_history([
            group_message("guest", "実験の話なら、酒場の外で頼むよ。", guest_name="酒場のマスター"),
        ])

        self.assertIn("酒場のマスター【ゲスト】: 実験の話なら、酒場の外で頼むよ。", history)

    def test_guest_prefix_completion_suggests_guest_marker(self) -> None:
        suggestion = _guest_prefix_completion("gue")

        self.assertIsNotNone(suggestion)
        assert suggestion is not None
        self.assertEqual("guest:", suggestion["value"])
        self.assertEqual("guest:", suggestion["label"])
        self.assertIsNone(_guest_prefix_completion("guest:"))
        self.assertIsNone(_guest_prefix_completion("guest:酒場のマスター"))
        self.assertIsNone(_guest_prefix_completion("@guest"))

    def test_participant_settings_helpers_add_and_remove_members(self) -> None:
        settings = {"participant_ids": ["member-a"]}

        added = settings_with_participant(settings, "member-b")
        self.assertEqual(["member-a", "member-b"], added["participant_ids"])
        self.assertEqual(["member-a"], settings["participant_ids"])

        duplicated = settings_with_participant(added, "member-b")
        self.assertEqual(["member-a", "member-b"], duplicated["participant_ids"])

        removed = settings_without_participant(added, "member-a")
        self.assertEqual(["member-b"], removed["participant_ids"])
