"""
グループ(箱庭)の純ロジック。

参加者の整形・ハンドル検証・次の話者候補の推定・適応差分HTMLなど、
描画から切り離してテストできる関数を持つ。
旧UI `src/ui/group_chat/` の同等ロジックの ui2 版(依存規則により複製・整理)。
"""

from __future__ import annotations

import difflib
import html as _html
import re
from dataclasses import dataclass
from typing import Any

from ..core.character.schemas import CharacterSheet
from ..core.conversation.speaker_selection import mentioned_member
from ..core.group_chat.schemas import GroupChatRecord, GroupMember, GroupUserPersona

HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{3,12}$")

# world_entry_type の表示ラベル(モックの「漂着/越境/定住」は例示。実スキーマは3値+空)
ENTRY_TYPE_LABELS = {
    "native": "住人",
    "visitor": "来訪者",
    "world_source": "世界の土台",
}


def entry_type_label(value: str) -> str:
    return ENTRY_TYPE_LABELS.get(value, "適応")


def group_participants(group: GroupChatRecord) -> list[dict[str, Any]]:
    """メンバー+ユーザーペルソナを共通形式の participant dict 列にする。"""
    participants: list[dict[str, Any]] = []
    for member in group.members:
        participants.append(
            {
                "key": f"member:{member.id}",
                "kind": "character",
                "name": member.character.name,
                "handle": member.handle,
                "member": member,
                "media": member.character.media,
            }
        )
    if group.user_persona is not None:
        participants.append(
            {
                "key": f"user:{group.user_persona.id}",
                "kind": "user",
                "name": group.user_persona.display_name or group.user_persona.name or "ユーザー",
                "handle": group.user_persona.handle,
                "persona": group.user_persona,
                "media": group.user_persona.media,
            }
        )
    return participants


def participant_by_speaker_id(
    participants: list[dict[str, Any]],
    speaker_id: str,
) -> dict[str, Any] | None:
    for participant in participants:
        member = participant.get("member")
        if isinstance(member, GroupMember) and member.id == speaker_id:
            return participant
        persona = participant.get("persona")
        if isinstance(persona, GroupUserPersona) and persona.id == speaker_id:
            return participant
    return None


def active_member_ids(settings: dict[str, Any] | None) -> set[str]:
    if settings is None:
        return set()
    return {str(member_id) for member_id in settings.get("participant_ids", [])}


def active_members(group: GroupChatRecord, settings: dict[str, Any] | None) -> list[GroupMember]:
    ids = active_member_ids(settings)
    return [member for member in group.members if member.id in ids]


def mention_entries(
    group: GroupChatRecord,
    settings: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """メンション補完(@)の候補。キャラは参加中のみ、ペルソナは常に含む。"""
    ids = active_member_ids(settings) if settings is not None else None
    entries: list[dict[str, Any]] = []
    for participant in group_participants(group):
        if participant["kind"] == "character" and ids is not None:
            member = participant.get("member")
            if not isinstance(member, GroupMember) or member.id not in ids:
                continue
        handle = str(participant.get("handle") or "").strip()
        if not HANDLE_RE.fullmatch(handle):
            continue
        entries.append(participant)
    return entries


def next_speaker_candidate_ids(
    messages: list[dict[str, Any]],
    members: list[GroupMember],
) -> set[str]:
    """「次の話者候補」灯り用の決定的な候補推定。

    `GroupChatTurnService.choose_next_speaker` の決定的分岐(メンション/直前話者除外)
    のみを鏡写しにする。LLM抽選に入るケースは候補全員を返す。
    """
    if not members:
        return set()
    last: dict[str, Any] | None = None
    for message in reversed(messages):
        if message.get("role") in {"user", "character", "guest"}:
            last = message
            break
    if last is not None and last.get("role") == "user":
        mentioned = mentioned_member(str(last.get("text", "")), members)
        if mentioned is not None:
            return {mentioned.id}
        return {member.id for member in members}
    if last is not None and last.get("role") == "character":
        previous_id = str(last.get("speaker_id", ""))
        others = {member.id for member in members if member.id != previous_id}
        if others:
            return others
        return {members[0].id}
    return {member.id for member in members}


@dataclass(frozen=True)
class HandleValidation:
    """ハンドル検証の結果。error が空なら成功。"""

    handles: list[str]
    user_handle: str
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def validate_handle_values(
    characters: list[CharacterSheet],
    handle_values: dict[str, str],
    user_handle: str | None = None,
    *,
    reserved: set[str] | None = None,
) -> HandleValidation:
    """キャラ+(任意で)ユーザーのハンドルを検証する(3〜12英数字_・重複禁止)。"""
    handles: list[str] = []
    seen: set[str] = {handle.lower() for handle in (reserved or set())}
    for sheet in characters:
        handle = str(handle_values.get(sheet.id) or "").strip()
        if not HANDLE_RE.fullmatch(handle):
            return HandleValidation([], "", f"{sheet.name} のハンドルは3〜12文字の英数字または_で入力してください")
        if handle.lower() in seen:
            return HandleValidation([], "", "ハンドルが重複しています")
        seen.add(handle.lower())
        handles.append(handle)
    if user_handle is None:
        return HandleValidation(handles, "")
    user = str(user_handle or "").strip()
    if not HANDLE_RE.fullmatch(user):
        return HandleValidation([], "", "ユーザーのハンドルは3〜12文字の英数字または_で入力してください")
    if user.lower() in seen:
        return HandleValidation([], "", "ハンドルが重複しています")
    return HandleValidation(handles, user)


def world_source_options(characters: list[CharacterSheet]) -> dict[str, str]:
    """作成フロー「世界を決める」の引き継ぎ元候補(世界観を持つ選択キャラのみ)。"""
    options = {"new": "新しく生成する"}
    for sheet in characters:
        if sheet.world.strip():
            options[f"character:{sheet.id}"] = f"{sheet.name} の世界を土台にする"
    return options


def guide_actor_options(group: GroupChatRecord, active_ids: set[str]) -> dict[str, str]:
    """/guide の行動者セレクト候補(参加中→未参加(入場)→ゲスト/地の文/ユーザー)。"""
    options: dict[str, str] = {"auto": "キャラクター（自動）"}
    for member in group.members:
        if member.id in active_ids:
            options[f"member:{member.id}"] = f"{member.character.name} / @{member.handle}"
    for member in group.members:
        if member.id not in active_ids:
            options[f"join:{member.id}"] = f"{member.character.name} / @{member.handle}（未参加 → 入場）"
    options["guest"] = "ゲスト（名前を指定）"
    options["narration"] = "地の文"
    options["user"] = "ユーザー"
    return options


def imitate_actor_options(group: GroupChatRecord, active_ids: set[str]) -> dict[str, str]:
    """/imitate(なりきり)の発言者セレクト候補。未参加は選択時に入場する。"""
    options: dict[str, str] = {}
    for member in group.members:
        if member.id in active_ids:
            options[f"member:{member.id}"] = f"{member.character.name} / @{member.handle}"
    for member in group.members:
        if member.id not in active_ids:
            options[f"join:{member.id}"] = f"{member.character.name} / @{member.handle}（未参加 → 入場）"
    options["guest"] = "ゲスト（名前を指定）"
    return options


# ---------------------------------------------------------------------------
# 適応プレビュー差分(旧 group_diff_html 相当の新実装。配色は P3 テーマ変数)
# ---------------------------------------------------------------------------

DIFF_CSS = """
.p3-diff {
  font-family: Consolas, "Courier New", monospace;
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-all;
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 10px 12px;
  background: var(--bg-2);
  max-height: 46vh;
  overflow-y: auto;
}
.p3-diff .hunk {
  color: var(--muted);
  background: var(--panel-2);
  border-radius: 6px;
  padding: 2px 8px;
  margin: 6px 0;
}
.p3-diff .add { background: color-mix(in srgb, #7ec98f 16%, transparent); color: var(--text); padding: 1px 8px; }
.p3-diff .del { background: color-mix(in srgb, #e08a8a 14%, transparent); color: var(--muted); padding: 1px 8px; text-decoration: line-through; }
.p3-diff .ctx { color: var(--muted); padding: 1px 8px; }
"""


def diff_html(old_text: str, new_text: str) -> str:
    """適応前後の unified diff を P3 トーンのHTMLにする。"""
    diff = list(difflib.unified_diff(old_text.splitlines(), new_text.splitlines(), lineterm="", n=2))
    if not diff:
        return '<div class="p3-diff"><div class="ctx">変更なし</div></div>'
    parts = ['<div class="p3-diff">']
    for line in diff:
        if line.startswith(("---", "+++")):
            continue
        if line.startswith("@@"):
            parts.append(f'<div class="hunk">{_html.escape(line)}</div>')
        elif line.startswith("+"):
            parts.append(f'<div class="add">+ {_html.escape(line[1:])}</div>')
        elif line.startswith("-"):
            parts.append(f'<div class="del">- {_html.escape(line[1:])}</div>')
        else:
            text = line[1:] if line.startswith(" ") else line
            parts.append(f'<div class="ctx">&nbsp; {_html.escape(text)}</div>')
    parts.append("</div>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# 既存グループ向け関係性ドラフト(participant key の変換)
# ---------------------------------------------------------------------------


def relationship_key_map_for_group(group: GroupChatRecord) -> dict[str, str]:
    """ドラフト生成(character:/user キー)→ グループ保存(member:/user: キー)の変換表。"""
    mapping: dict[str, str] = {}
    for member in group.members:
        mapping[f"character:{member.character.id}"] = f"member:{member.id}"
    if group.user_persona is not None:
        mapping["user"] = f"user:{group.user_persona.id}"
    return mapping


def draft_state_from_group(group: GroupChatRecord) -> dict[str, Any]:
    """既存の関係性をドラフト生成の入力 state(character:/user キー)へ逆変換する。"""
    reverse = {value: key for key, value in relationship_key_map_for_group(group).items()}
    relationships = []
    for relationship in group.relationships:
        first = reverse.get(relationship.participant_a_key)
        second = reverse.get(relationship.participant_b_key)
        if first is None or second is None:
            continue
        relationships.append(
            {
                "id": relationship.id,
                "participant_a_key": first,
                "participant_b_key": second,
                "description": relationship.description,
            }
        )
    return {"relationships": relationships, "relationship_sequence": 0}
