"""グループチャット特性テスト用の架空データ。"""

from __future__ import annotations

from typing import Any

from src.core.character.schemas import CharacterSheet
from src.core.group_chat.schemas import (
    GroupChatRecord,
    GroupMember,
    GroupRelationship,
    GroupUserPersona,
)


def make_group_members() -> list[GroupMember]:
    """プロンプト・話者選択テストで共有する架空メンバーを返す。"""
    return [
        GroupMember(
            id="member-akari",
            source_character_id="character-akari",
            handle="Akari",
            character=CharacterSheet(
                id="character-akari",
                name="灯里",
                age="17",
                gender="女性",
                occupation="資料整理係",
                origin="星見図書館",
                world="遠い星の図書館",
                appearance="青いケープと銀の栞を身につけている。",
                personality="穏やかで観察好き。",
                background="古い星図を守っている。",
                self_intro="灯りを消さずに待っています。",
                sample_dialogues="「この棚、まだ眠っているみたい」",
            ),
            world_entry_type="native",
        ),
        GroupMember(
            id="member-minato",
            source_character_id="character-minato",
            handle="Minato",
            character=CharacterSheet(
                id="character-minato",
                name="湊",
                age="19",
                gender="男性",
                occupation="修理屋",
                origin="時計塔通り",
                world="遠い星の図書館",
                appearance="工具鞄を肩にかけている。",
                personality="軽口を叩くが手元は丁寧。",
                background="壊れた天球儀を直しに来た。",
                self_intro="直せるものなら任せてよ。",
                sample_dialogues="「歯車の声が少しずれてる」",
            ),
            world_entry_type="visitor",
            arrival_reason="天球儀の修理を依頼された。",
        ),
    ]


def make_group_chat() -> GroupChatRecord:
    """固定期待値に使う架空のグループチャットを返す。"""
    members = make_group_members()
    return GroupChatRecord(
        id="group-starlit-library",
        name="星見図書館の夜会",
        world="星が本の背表紙に宿る静かな図書館。",
        completion_profile_id="profile-test",
        members=members,
        user_persona=GroupUserPersona(
            id="persona-sora",
            source_persona_id="persona-source-sora",
            handle="Sora",
            name="空野ソラ",
            display_name="ソラ",
            description="記録係として同行する旅人。",
            world_entry_type="visitor",
            arrival_reason="古い招待状を受け取った。",
        ),
        relationships=[
            GroupRelationship(
                id="rel-akari-minato",
                participant_a_key="member:member-akari",
                participant_b_key="member:member-minato",
                description="古い星図の修復を一緒に進めている。",
            ),
            GroupRelationship(
                id="rel-akari-sora",
                participant_a_key="member:member-akari",
                participant_b_key="user:persona-sora",
                description="灯里はソラを新米の記録係として見守っている。",
            ),
        ],
    )


def make_group_settings() -> dict[str, Any]:
    """参加者とシチュエーションを固定した設定 dict を返す。"""
    return {
        "participant_ids": ["member-akari", "member-minato"],
        "situation": "星見図書館の夜更け。閲覧室に古い星図が広げられている。",
    }


def make_group_messages() -> list[dict[str, Any]]:
    """プロンプト履歴用の架空メッセージ列を返す。"""
    return [
        {
            "role": "user",
            "speaker_id": "persona-sora",
            "speaker_name": "ソラ",
            "handle": "Sora",
            "text": "この星図、昨日と線が違う気がします。",
            "time_label": "21:00",
        },
        {
            "role": "memo",
            "text": "このコメントはプロンプト履歴に入れない。",
            "time_label": "21:01",
        },
        {
            "role": "character",
            "speaker_id": "member-akari",
            "speaker_name": "灯里",
            "handle": "Akari",
            "text": "星図は夜ごとに少しだけ息をするんです。",
            "time_label": "21:02",
        },
        {
            "role": "guest",
            "speaker_id": "guest:巡回司書",
            "speaker_name": "巡回司書【ゲスト】",
            "guest_name": "巡回司書",
            "handle": "",
            "text": "閉館の鐘まで、あと少しですよ。",
            "time_label": "21:03",
        },
        {
            "role": "narration",
            "text": "窓辺の天球儀が、かすかに青く光った。",
            "time_label": "21:04",
        },
    ]


def message_roles_and_contents(messages: list[Any]) -> list[tuple[str, str]]:
    """LangChain メッセージ列を role/content の比較用に変換する。"""
    return [(str(message.type), str(message.content)) for message in messages]
