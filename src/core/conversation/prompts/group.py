"""グループチャット用プロンプト構築。"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from ...group_chat.schemas import GroupChatRecord, GroupMember, GroupUserPersona
from ..history import format_group_history
from ..sanitize import clean_guest_name, guest_display_name
from .common import character_summary, compact_character_summary


def group_input_mode_for_role(role: str) -> str:
    if role == "character":
        return "character"
    if role == "guest":
        return "guest"
    if role == "narration":
        return "narration"
    if role == "memo":
        return "memo"
    return "user"


def build_group_system_prompt(
    group: GroupChatRecord,
    settings: dict[str, Any],
    active_members: list[GroupMember],
    speaker: GroupMember,
) -> str:
    user = group.user_persona
    active_overview = "\n".join(
        f"- @{member.handle} / {member.character.name}: {compact_character_summary(member.character)}"
        for member in active_members
    )
    return (
        "あなたはグループチャットの参加キャラクターを演じます。\n"
        "指定された次の発言者だけとして発言してください。話者名、ハンドル、引用符、前置き、解説は出力しないでください。\n"
        "特別な理由がない限り、キャラクター発言にメンションは含めないでください。\n\n"
        "発言は通常の1対1チャットと同じくらい短くしてください。1〜3文程度で短く返し、相手が返しやすい余白を残してください。\n\n"
        f"グループ名: {group.name}\n"
        f"世界観:\n{group.world or '未設定'}\n\n"
        f"ユーザー:\n@{user.handle if user else 'User'} / "
        f"{(user.display_name or user.name) if user else 'ユーザー'}\n"
        f"{group_user_persona_context(user)}\n\n"
        f"参加キャラクター:\n{active_overview or 'なし'}\n\n"
        f"{format_group_relationship_section(group, settings)}"
        f"今回の発言者:\n@{speaker.handle} / {speaker.character.name}\n"
        f"{character_summary(speaker.character)}\n\n"
        f"シチュエーション:\n{settings.get('situation', '') or '未設定'}"
    )


def build_group_character_messages(
    group: GroupChatRecord,
    settings: dict[str, Any],
    messages: list[dict[str, Any]],
    speaker: GroupMember,
    *,
    turn_instruction: str = "",
) -> list:
    participant_ids = {str(member_id) for member_id in settings.get("participant_ids", [])}
    active = [member for member in group.members if member.id in participant_ids] or group.members
    instruction = turn_instruction.strip()
    instruction_text = (
        "\n\n次の返答だけに適用するメタ指示です。"
        "この指示を作中で説明せず、返答本文にだけ反映してください。\n"
        f"{instruction}"
        if instruction
        else ""
    )
    return [
        SystemMessage(content=build_group_system_prompt(group, settings, active, speaker)),
        HumanMessage(
            content=(
                f"会話履歴:\n{format_group_history(messages)}\n\n"
                f"次の発言者は @{speaker.handle} / {speaker.character.name} です。"
                "このキャラクターの自然な次の発言を、本文だけで返してください。"
                "通常チャットと同じくらい短く、1〜3文程度で相手が返しやすい余白を残してください。"
                f"{instruction_text}"
            )
        ),
    ]


def build_group_guest_messages(
    group: GroupChatRecord,
    settings: dict[str, Any],
    messages: list[dict[str, Any]],
    guest_name: str,
    *,
    turn_instruction: str = "",
) -> list:
    name = clean_guest_name(guest_name)
    instruction = turn_instruction.strip()
    instruction_text = (
        "\n\n次の返答だけに適用するメタ指示です。"
        "この指示を作中で説明せず、返答本文にだけ反映してください。\n"
        f"{instruction}"
        if instruction
        else ""
    )
    return [
        SystemMessage(
            content=(
                "あなたはグループチャットの一時的なゲスト発言者を演じます。"
                "指定されたゲスト本人の自然な発言本文だけを出力してください。"
                "話者名、ハンドル、引用符、前置き、解説は出力しないでください。"
                "発言は短く、1〜3文程度で場面に自然につながる内容にしてください。"
            )
        ),
        HumanMessage(
            content=(
                f"グループ名: {group.name}\n"
                f"世界観:\n{group.world or '未設定'}\n\n"
                f"シチュエーション:\n{settings.get('situation', '') or '未設定'}\n\n"
                f"参加者:\n{format_group_participant_overview(group, settings)}\n\n"
                f"{format_group_relationship_section(group, settings)}"
                f"会話履歴:\n{format_group_history(messages)}\n\n"
                f"今回のゲスト発言者: {guest_display_name(name)}\n"
                "このゲストの自然な次の発言を、本文だけで返してください。"
                f"{instruction_text}"
            )
        ),
    ]


def build_group_narration_messages(
    group: GroupChatRecord,
    settings: dict[str, Any],
    messages: list[dict[str, Any]],
    *,
    instruction: str = "",
) -> list:
    instruction_line = instruction.strip() or "現在の会話を受けて、次に自然につながる地の文を書く。"
    return [
        SystemMessage(
            content=(
                "あなたはグループチャットの地の文を書くナレーターです。"
                "セリフ、話者名、箇条書き、解説、メタ発言は出力しないでください。"
                "1〜3文で、場面・空気・動きだけを簡潔に描写してください。"
            )
        ),
        HumanMessage(
            content=(
                f"グループ名: {group.name}\n"
                f"世界観:\n{group.world or '未設定'}\n\n"
                f"シチュエーション:\n{settings.get('situation', '') or '未設定'}\n\n"
                f"参加者:\n{format_group_participant_overview(group, settings)}\n\n"
                f"{format_group_relationship_section(group, settings)}"
                f"会話履歴:\n{format_group_history(messages)}\n\n"
                f"指示: {instruction_line}\n"
                "出力は地の文だけ。"
            )
        ),
    ]


def build_group_input_completion_messages(
    group: GroupChatRecord,
    settings: dict[str, Any],
    messages: list[dict[str, Any]],
    left_text: str,
    *,
    input_mode: str,
    speaker: GroupMember | None = None,
    guest_name: str = "",
) -> list:
    target_label, system_instruction, character_context = group_input_target_context(
        group,
        input_mode,
        speaker,
        guest_name=guest_name,
    )
    return [
        SystemMessage(content=system_instruction),
        HumanMessage(
            content=(
                f"現在話そうとしているもの: {target_label}\n"
                f"グループ名: {group.name}\n"
                f"世界観:\n{group.world or '未設定'}\n"
                f"シチュエーション:\n{settings.get('situation', '') or '未設定'}\n\n"
                f"参加者:\n{format_group_participant_overview(group, settings)}\n\n"
                f"{format_group_relationship_section(group, settings)}"
                f"{character_context}"
                f"会話履歴:\n{format_group_history(messages)}\n\n"
                f"未完の文:\n{left_text.rstrip()}\n\n"
                "未完の文の続きを出力してください。前置き、引用符、元の文の繰り返しは禁止です。"
            )
        ),
    ]


def build_group_tailored_input_messages(
    group: GroupChatRecord,
    settings: dict[str, Any],
    messages: list[dict[str, Any]],
    text: str,
    *,
    input_mode: str,
    speaker: GroupMember | None = None,
    guest_name: str = "",
) -> list:
    target_label, system_instruction, character_context = group_input_target_context(
        group,
        input_mode,
        speaker,
        guest_name=guest_name,
        tailor=True,
    )
    return [
        SystemMessage(content=system_instruction),
        HumanMessage(
            content=(
                f"現在の入力ロール: {target_label}\n"
                f"グループ名: {group.name}\n"
                f"世界観:\n{group.world or '未設定'}\n"
                f"シチュエーション:\n{settings.get('situation', '') or '未設定'}\n\n"
                f"参加者:\n{format_group_participant_overview(group, settings)}\n\n"
                f"{format_group_relationship_section(group, settings)}"
                f"{character_context}"
                f"会話履歴:\n{format_group_history(messages)}\n\n"
                f"書き換える文:\n{text.strip()}\n\n"
                "現在の入力ロールに合う自然な本文へ書き換えてください。"
                "出力は書き換え後の本文だけ。前置き、引用符、話者名、解説は禁止です。"
            )
        ),
    ]


def build_group_response_choice_messages(
    group: GroupChatRecord,
    settings: dict[str, Any],
    messages: list[dict[str, Any]],
    left_text: str,
    *,
    input_mode: str,
    speaker: GroupMember | None = None,
    guest_name: str = "",
) -> list:
    target_label, system_instruction, character_context = group_input_target_context(
        group,
        input_mode,
        speaker,
        guest_name=guest_name,
        choices=True,
    )
    prefix = left_text.strip()
    prefix_line = f"各候補は次の書き出しに自然につなげる: {prefix}" if prefix else "各候補は独立した短い返答にする。"
    return [
        SystemMessage(content=system_instruction),
        HumanMessage(
            content=(
                f"現在話そうとしているもの: {target_label}\n"
                f"グループ名: {group.name}\n"
                f"世界観:\n{group.world or '未設定'}\n"
                f"シチュエーション:\n{settings.get('situation', '') or '未設定'}\n\n"
                f"参加者:\n{format_group_participant_overview(group, settings)}\n\n"
                f"{format_group_relationship_section(group, settings)}"
                f"{character_context}"
                f"会話履歴:\n{format_group_history(messages)}\n\n"
                f"{prefix_line}\n"
                "出力は3行だけ。番号や箇条書き記号は付けず、候補本文だけを書いてください。"
            )
        ),
    ]


def group_input_target_context(
    group: GroupChatRecord,
    input_mode: str,
    speaker: GroupMember | None,
    *,
    guest_name: str = "",
    tailor: bool = False,
    choices: bool = False,
) -> tuple[str, str, str]:
    action = "候補を作る" if choices else "書き換える" if tailor else "続きを補完する"
    if input_mode == "narration":
        return (
            "地の文",
            f"あなたはグループチャットの地の文を{action}編集者です。セリフではなく、状況描写として自然な本文だけを短く出力してください。",
            "",
        )
    if input_mode == "memo":
        return (
            "コメント",
            f"あなたはグループチャットログ上に残すコメントを{action}編集者です。会話本文ではなく、作者向けの短いメモとして自然な本文だけを出力してください。",
            "",
        )
    if input_mode == "guest":
        cleaned_guest_name = clean_guest_name(guest_name)
        guest_label = guest_display_name(cleaned_guest_name) if cleaned_guest_name else "ゲスト"
        return (
            f"ゲスト（{guest_label}）",
            f"あなたはゲスト発言を{action}編集者です。指定されたゲスト本人の自然なセリフだけを短く出力してください。",
            f"ゲスト発言者:\n{guest_label}\n\n",
        )
    if input_mode == "character":
        member = speaker or (group.members[0] if group.members else None)
        if member is None:
            return (
                "キャラクター",
                f"あなたはキャラクター発言を{action}編集者です。キャラクター本人の自然なセリフだけを短く出力してください。",
                "",
            )
        return (
            f"キャラクター（{member.character.name} / @{member.handle}）",
            f"あなたはキャラクター発言を{action}編集者です。指定キャラクター本人の自然なセリフだけを短く出力してください。",
            f"対象キャラクター:\n@{member.handle} / {member.character.name}\n{character_summary(member.character)}\n\n",
        )
    user = group.user_persona
    return (
        f"ユーザー（{(user.display_name or user.name) if user else 'ユーザー'}）",
        f"あなたはユーザー発言を{action}編集者です。ユーザー本人の口調として自然につながる本文だけを短く出力してください。",
        f"ユーザー設定:\n@{user.handle if user else 'User'} / {(user.display_name or user.name) if user else 'ユーザー'}\n{group_user_persona_context(user)}\n\n",
    )


def format_group_participant_overview(group: GroupChatRecord, settings: dict[str, Any]) -> str:
    participant_ids = {str(member_id) for member_id in settings.get("participant_ids", [])}
    active = [member for member in group.members if member.id in participant_ids] or group.members
    lines = [
        f"- @{member.handle} / {member.character.name}: {compact_character_summary(member.character)}"
        for member in active
    ]
    if group.user_persona is not None:
        user = group.user_persona
        lines.append(
            f"- @{user.handle} / {user.display_name or user.name or 'ユーザー'}: {group_user_persona_context(user)}"
        )
    return "\n".join(lines) if lines else "なし"


def group_user_persona_context(user: GroupUserPersona | None) -> str:
    if user is None:
        return ""
    lines = [(user.description or "ユーザー").strip()]
    if user.world_entry_type == "visitor" and user.arrival_reason.strip():
        lines.append(f"この世界に来た理由: {user.arrival_reason.strip()}")
    return "\n".join(line for line in lines if line)


def format_group_relationship_section(group: GroupChatRecord, settings: dict[str, Any]) -> str:
    relationships = active_group_relationship_lines(group, settings)
    if not relationships:
        return ""
    return "関係性:\n" + "\n".join(relationships) + "\n\n"


def active_group_relationship_lines(group: GroupChatRecord, settings: dict[str, Any]) -> list[str]:
    active_keys = active_group_participant_keys(group, settings)
    labels = group_participant_labels(group)
    lines: list[str] = []
    for relationship in group.relationships:
        if relationship.participant_a_key not in active_keys:
            continue
        if relationship.participant_b_key not in active_keys:
            continue
        description = relationship.description.strip()
        if not description:
            continue
        left = labels.get(relationship.participant_a_key)
        right = labels.get(relationship.participant_b_key)
        if not left or not right:
            continue
        lines.append(f"- {left} ↔ {right}: {description}")
    return lines


def active_group_participant_keys(group: GroupChatRecord, settings: dict[str, Any]) -> set[str]:
    participant_ids = {str(member_id) for member_id in settings.get("participant_ids", [])}
    active_members = [member for member in group.members if member.id in participant_ids] or group.members
    keys = {f"member:{member.id}" for member in active_members}
    if group.user_persona is not None:
        keys.add(f"user:{group.user_persona.id}")
    return keys


def group_participant_labels(group: GroupChatRecord) -> dict[str, str]:
    labels: dict[str, str] = {}
    for member in group.members:
        name = member.character.name
        handle = member.handle
        label = f"{name} (@{handle})" if handle else name
        labels[f"member:{member.id}"] = label
    if group.user_persona is not None:
        user = group.user_persona
        name = user.display_name or user.name or "ユーザー"
        handle = user.handle
        label = f"{name} (@{handle})" if handle else name
        labels[f"user:{user.id}"] = label
    return labels


def build_group_title_messages(group: GroupChatRecord, messages: list[dict[str, Any]]) -> list:
    return [
        SystemMessage(
            content=(
                "あなたはグループチャット履歴に短いタイトルを付ける編集者です。"
                "出力はタイトル本文だけにしてください。引用符、句点、解説、前置きは禁止です。"
                "12〜24文字程度で、会話の中心が分かる自然な日本語にしてください。"
            )
        ),
        HumanMessage(
            content=(
                f"グループ名: {group.name}\n"
                f"世界観:\n{group.world or '未設定'}\n\n"
                f"{format_group_relationship_section(group, {})}"
                f"会話履歴:\n{format_group_history(messages)}"
            )
        ),
    ]
