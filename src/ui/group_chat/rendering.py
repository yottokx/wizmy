"""グループチャット UI の描画ヘルパー。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from nicegui import ui

from ...core.character.schemas import CharacterMedia
from ...core.conversation.history import debug_from_dict
from ...core.conversation.prompts.group import group_participant_labels
from ...core.group_chat.schemas import (
    GroupChatRecord,
    GroupMember,
    GroupRelationship,
    GroupUserPersona,
)
from ..chat import components as chat_components
from ..chat.media import cropped_background_style


def participant_media_style(ctx, participant: dict[str, Any], *, rect_kind: str) -> str:
    media = participant.get("media")
    if not isinstance(media, CharacterMedia):
        return ""
    image = media.primary_image()
    if image is None:
        return ""
    if participant.get("kind") == "user":
        image_path = ctx.api_config.media_path(image.path)
    else:
        image_path = ctx.group_chats.media_path(image.path)
    rect = image.bust_rect if rect_kind == "bust" else image.face_rect
    return cropped_background_style(image, image_path, rect, 1.0) if image_path else ""


def render_participant_face(ctx, participant: dict[str, Any], *, large: bool = False) -> None:
    classes = "cs-group-face"
    if large:
        classes += " cs-group-face-large"
    style = participant_media_style(ctx, participant, rect_kind="face")
    with ui.element("div").classes(classes).style(style):
        if not style:
            ui.icon("person").classes("text-sm")


def render_group_user_menu_face(ctx, persona: GroupUserPersona | None) -> None:
    if persona is None:
        with ui.element("div").classes("cs-group-face"):
            ui.icon("person").classes("text-sm")
        return
    participant = {
        "kind": "user",
        "media": persona.media,
    }
    render_participant_face(ctx, participant)


def render_section_head(icon: str, title: str) -> None:
    with ui.element("div").classes("cs-group-section-head"):
        ui.icon(icon)
        ui.label(title).classes("cs-group-section-title")


def render_group_card(
    ctx,
    group: GroupChatRecord,
    refresh_groups: Callable[[], Awaitable[None]],
) -> None:
    from .dialogs_group import open_delete_group_dialog

    with ui.element("div").classes("cs-group-card"):
        with ui.element("div").classes("cs-group-card-title-row"):
            ui.label(group.name).classes("cs-group-card-title")
            ui.label(time_label(group.updated_at)).classes("cs-group-card-meta")
        ui.label(group.world or "世界観は未設定です").classes("cs-group-card-world")
        with ui.row().classes("items-center justify-between gap-2"):
            with ui.element("div").classes("cs-group-avatar-stack"):
                for member in group.members[:4]:
                    render_face(ctx, member.character.media, "character")
                if group.user_persona is not None:
                    render_face(ctx, group.user_persona.media, "persona")
            with ui.row().classes("items-center gap-1"):
                ui.button(
                    "開く",
                    icon="open_in_new",
                    on_click=lambda group_id=group.id: ui.navigate.to(f"/groups/{group_id}"),
                ).props("flat color=primary dense")
                ui.button(
                    icon="delete",
                    on_click=lambda: open_delete_group_dialog(ctx, group, refresh_groups),
                ).props("flat round dense color=negative").tooltip("グループ削除")
        ui.label(f"{len(group.members)}人 + @{group.user_persona.handle if group.user_persona else 'User'}").classes(
            "text-xs text-grey-6"
        )


def group_input_mode_icon(mode: str) -> str:
    return {
        "character": "theater_comedy",
        "guest": "person_add",
        "narration": "auto_stories",
        "memo": "sticky_note_2",
        "user": "person",
    }.get(mode, "person")


def group_message_target_label(role: str) -> str:
    if role == "character":
        return "キャラクターの台詞"
    if role == "guest":
        return "ゲストの台詞"
    if role == "narration":
        return "地の文"
    if role == "memo":
        return "コメント"
    return "発言"


def render_group_chat_message(
    ctx,
    message: dict[str, Any],
    participants: list[dict[str, Any]],
    *,
    index: int,
    rewind_message=None,
    rewrite_message=None,
    regenerate_message=None,
    play_tts_message=None,
    tts_playable: bool = False,
    tts_generating: bool = False,
) -> None:
    role = str(message.get("role", ""))
    text = str(message.get("text", ""))
    speaker_name = str(message.get("speaker_name", ""))
    handle = str(message.get("handle", ""))

    if role == "narration":
        with ui.element("div").classes("cs-chat-message-row cs-chat-message-row-narration"):
            with ui.element("div").classes("cs-chat-bubble"):
                ui.label(text).classes("cs-chat-message-text")
                render_group_message_meta(
                    message,
                    index=index,
                    rewind_message=rewind_message,
                    rewrite_message=rewrite_message,
                    play_tts_message=play_tts_message,
                    tts_playable=tts_playable,
                    tts_generating=tts_generating,
                )
        return
    if role == "memo":
        with ui.element("div").classes("cs-chat-message-row cs-chat-message-row-memo"):
            with ui.element("div").classes("cs-chat-bubble"):
                ui.label("コメント").classes("cs-chat-message-kind")
                ui.label(text).classes("cs-chat-message-text")
                render_group_message_meta(
                    message,
                    index=index,
                    rewind_message=rewind_message,
                    rewrite_message=rewrite_message,
                )
        return
    if role == "system":
        with ui.element("div").classes("cs-chat-message-row cs-chat-message-row-narration cs-group-system-message"):
            with ui.element("div").classes("cs-chat-bubble"):
                ui.label("システム").classes("cs-chat-message-kind")
                ui.label(text).classes("cs-chat-message-text")
                render_group_message_meta(
                    message,
                    index=index,
                    rewind_message=rewind_message,
                    rewrite_message=rewrite_message,
                )
        return

    row_class = "cs-chat-message-row-user" if role == "user" else "cs-chat-message-row-character"
    with ui.element("div").classes(f"cs-chat-message-row {row_class}"):
        participant = participant_by_speaker_id(participants, str(message.get("speaker_id", "")))
        if role == "character" and participant is not None:
            render_participant_face(ctx, participant)
        elif role == "guest":
            render_group_guest_face()
        with ui.element("div").classes("cs-chat-bubble"):
            if speaker_name or handle:
                speaker_label = speaker_name
                if handle:
                    speaker_label = f"{speaker_label} / @{handle}" if speaker_label else f"@{handle}"
                ui.label(speaker_label).classes("cs-group-speaker")
            ui.label(text).classes("cs-chat-message-text")
            render_group_message_meta(
                message,
                index=index,
                rewind_message=rewind_message,
                rewrite_message=rewrite_message,
                regenerate_message=regenerate_message,
                play_tts_message=play_tts_message,
                tts_playable=tts_playable,
                tts_generating=tts_generating,
            )
        if role == "user" and participant is not None:
            render_participant_face(ctx, participant)
        elif role == "user":
            ui.element("div").classes("cs-group-face")


def render_group_message_meta(
    message: dict[str, Any],
    *,
    index: int,
    rewind_message=None,
    rewrite_message=None,
    regenerate_message=None,
    play_tts_message=None,
    tts_playable: bool = False,
    tts_generating: bool = False,
) -> None:
    role = str(message.get("role", ""))
    text = str(message.get("text", ""))
    with ui.element("div").classes("cs-chat-message-meta"):
        with ui.element("div").classes("cs-chat-message-actions"):
            if tts_playable and play_tts_message is not None and text.strip():
                play_tip = {
                    "character": "この台詞を読み上げ",
                    "narration": "この地の文を読み上げ",
                }.get(role, "この発言を読み上げ")
                play_btn = (
                    ui.button(
                        icon="play_arrow",
                        on_click=lambda i=index: play_tts_message(i),
                    )
                    .props("flat round dense size=sm")
                    .classes("cs-chat-message-action")
                    .tooltip(play_tip)
                )
                if tts_generating:
                    play_btn.props("loading")
                    play_btn.disable()
            if role == "character" and regenerate_message is not None:
                ui.button(
                    icon="refresh",
                    on_click=lambda i=index: regenerate_message(i),
                ).props("flat round dense size=sm").classes("cs-chat-message-action").tooltip("この台詞を再生成")
            debug = debug_from_dict(message.get("debug"))
            if debug is not None:
                ui.button(
                    icon="bug_report",
                    on_click=lambda d=debug: chat_components.open_llm_debug_dialog(d),
                ).props("flat round dense size=sm").classes("cs-chat-message-action").tooltip("LLM入出力")
            speaker_debug = debug_from_dict(message.get("speaker_debug"))
            if speaker_debug is not None:
                ui.button(
                    icon="manage_search",
                    on_click=lambda d=speaker_debug: chat_components.open_llm_debug_dialog(d),
                ).props("flat round dense size=sm").classes("cs-chat-message-action").tooltip("発言者決定ログ")
            if role in {"character", "guest", "user", "narration", "memo"} and rewrite_message is not None:
                ui.button(
                    icon="edit",
                    on_click=lambda i=index: rewrite_message(i),
                ).props("flat round dense size=sm").classes("cs-chat-message-action").tooltip("この内容を書き換え")
            if role in {"character", "guest", "user", "narration", "memo"} and rewind_message is not None:
                rewind_tip = {
                    "character": "この台詞まで戻る",
                    "guest": "この台詞まで戻る",
                    "narration": "この地の文まで戻る",
                    "memo": "このコメントまで戻る",
                }.get(role, "この発言まで戻る")
                ui.button(
                    icon="undo",
                    on_click=lambda i=index: rewind_message(i),
                ).props("flat round dense size=sm").classes("cs-chat-message-action").tooltip(rewind_tip)
        ui.label(str(message.get("time_label", ""))).classes("cs-chat-message-time")


def participant_by_speaker_id(
    participants: list[dict[str, Any]],
    speaker_id: str,
) -> dict[str, Any] | None:
    for participant in participants:
        if participant.get("kind") == "character":
            member = participant.get("member")
            if isinstance(member, GroupMember) and member.id == speaker_id:
                return participant
        if participant.get("kind") == "user":
            persona = participant.get("persona")
            if isinstance(persona, GroupUserPersona) and persona.id == speaker_id:
                return participant
    return None


def render_group_profile_panel(
    ctx,
    group: GroupChatRecord,
    participants: list[dict[str, Any]],
    current: dict[str, Any] | None,
    *,
    selected_key: str,
    active_tab: str,
    select_profile: Callable[[str], None],
    select_tab: Callable[[str], None],
    on_group_updated: Callable[[GroupChatRecord], None] | None = None,
    compact: bool = False,
) -> None:
    from .dialogs_group import open_add_group_character_dialog

    if current is None:
        with ui.element("div").classes("cs-group-profile-shell"):
            ui.label("メンバーがいません").classes("cs-group-profile-summary")
        return

    classes = "cs-group-profile-shell"
    if compact:
        classes += " cs-group-profile-compact"

    with ui.element("div").classes(classes):
        with ui.element("div").classes("cs-group-profile-switch"):
            profile_classes = "cs-group-profile-switch-item"
            if active_tab == "profile":
                profile_classes += " cs-group-profile-switch-item-active"
            profile_tab = ui.element("button").props("type=button").classes(profile_classes)
            profile_tab.on("click", lambda _: select_tab("profile"))
            with profile_tab:
                ui.icon("groups").classes("text-sm")
                ui.label("プロフィール")
            world_classes = "cs-group-profile-switch-item"
            if active_tab == "world":
                world_classes += " cs-group-profile-switch-item-active"
            world_tab = ui.element("button").props("type=button").classes(world_classes)
            world_tab.on("click", lambda _: select_tab("world"))
            with world_tab:
                ui.icon("menu_book").classes("text-sm")
                ui.label("ワールド")

        if active_tab == "world":
            render_group_world_panel(ctx, group, on_group_updated)
            return

        style = participant_media_style(ctx, current, rect_kind="bust")
        with ui.element("div").classes("cs-group-portrait").style(style):
            if not style:
                with ui.element("div").classes("cs-group-portrait-placeholder"):
                    ui.icon("person").classes("text-4xl")

        with ui.element("div").classes("cs-group-face-strip"):
            for participant in participants:
                button_classes = "cs-group-avatar-button"
                if participant["key"] == selected_key:
                    button_classes += " cs-group-avatar-selected"
                button = ui.element("button").props("type=button").classes(button_classes)
                button.on("click", lambda _, key=participant["key"]: select_profile(key))
                with button:
                    render_participant_face(ctx, participant, large=True)

        ui.label(current["name"]).classes("cs-group-profile-name")
        with ui.element("div").classes("cs-group-handle"):
            ui.icon("alternate_email").classes("text-sm")
            ui.label(current["handle"])
        with ui.element("div").classes("cs-group-profile-actions"):
            current_member = current.get("member")
            if isinstance(current_member, GroupMember):
                ui.button(
                    "キャラクターシートを開く",
                    icon="description",
                    on_click=lambda member_id=current_member.id: ui.navigate.to(
                        f"/groups/{group.id}/members/{member_id}"
                    ),
                ).props("outline dense").classes("cs-group-profile-action")
            elif current.get("kind") == "user" and group.user_persona is not None:
                ui.button(
                    "ユーザーペルソナを開く",
                    icon="badge",
                    on_click=lambda: ui.navigate.to(f"/groups/{group.id}/persona"),
                ).props("outline dense").classes("cs-group-profile-action")
            ui.button(
                "キャラクターを追加",
                icon="person_add",
                on_click=lambda: open_add_group_character_dialog(ctx, group),
            ).props("outline dense").classes("cs-group-profile-action")
            ui.button(
                "キャラクター生成",
                icon="auto_awesome",
                on_click=lambda: ui.navigate.to(f"/groups/{group.id}/generation"),
            ).props("outline dense").classes("cs-group-profile-action")

        with ui.element("div").classes("cs-group-profile-card"):
            is_user_profile = current.get("kind") == "user"
            ui.label("ユーザーペルソナ概要" if is_user_profile else "キャラクター概要").classes(
                "cs-group-profile-card-title"
            )
            with ui.element("div").classes("cs-group-profile-grid"):
                for label, value in participant_profile_rows(current):
                    ui.label(label).classes("cs-group-profile-label")
                    ui.label(value or "未設定").classes("cs-group-profile-value")
            ui.label("説明" if is_user_profile else "人物像").classes("cs-group-profile-card-title")
            ui.label(participant_profile_text(current)).classes("cs-group-profile-summary")


def render_group_world_panel(
    ctx,
    group: GroupChatRecord,
    on_group_updated: Callable[[GroupChatRecord], None] | None = None,
) -> None:
    from .dialogs_adaptation import open_group_relationship_dialog

    with ui.element("div").classes("cs-group-profile-card"):
        ui.label("ワールド").classes("cs-group-profile-card-title")
        ui.label(group.world or "未設定").classes("cs-group-profile-summary")

    with ui.element("div").classes("cs-group-profile-card"):
        with ui.row().classes("items-center justify-between gap-2"):
            ui.label("関係性").classes("cs-group-profile-card-title")
            ui.button(
                "追加",
                icon="add",
                on_click=lambda: open_group_relationship_dialog(
                    ctx,
                    group,
                    None,
                    on_group_updated,
                ),
            ).props("outline dense").classes("cs-group-profile-action")

        participants = group_participants(group)
        if len(participants) < 2:
            ui.label("関係性を設定できる参加者が足りません").classes("cs-group-profile-summary")
            return

        labels = group_participant_labels(group)
        with ui.element("div").classes("cs-group-relationship-list"):
            if not group.relationships:
                ui.label("設定済みの関係性はありません").classes("cs-group-profile-summary")
            for relationship in group.relationships:
                render_group_relationship_row(
                    ctx,
                    group,
                    relationship,
                    labels,
                    on_group_updated,
                )


def render_group_relationship_row(
    ctx,
    group: GroupChatRecord,
    relationship: GroupRelationship,
    labels: dict[str, str],
    on_group_updated: Callable[[GroupChatRecord], None] | None,
) -> None:
    from .dialogs_adaptation import delete_group_relationship, open_group_relationship_dialog

    left = labels.get(relationship.participant_a_key, "不明な参加者")
    right = labels.get(relationship.participant_b_key, "不明な参加者")
    with ui.element("div").classes("cs-group-relationship-row"):
        with ui.element("div").classes("cs-group-relationship-head"):
            ui.label(f"{left} ↔ {right}").classes("cs-group-relationship-pair")
            with ui.row().classes("items-center gap-1 shrink-0"):
                ui.button(
                    icon="edit",
                    on_click=lambda: open_group_relationship_dialog(
                        ctx,
                        group,
                        relationship,
                        on_group_updated,
                    ),
                ).props("flat round dense size=sm").tooltip("編集")
                ui.button(
                    icon="delete",
                    on_click=lambda: delete_group_relationship(
                        ctx,
                        group,
                        relationship.id,
                        on_group_updated,
                    ),
                ).props("flat round dense size=sm color=negative").tooltip("削除")
        ui.label(relationship.description or "未設定").classes("cs-group-relationship-text")


def group_participants(group: GroupChatRecord) -> list[dict[str, Any]]:
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


def render_group_member_menu_face(ctx, member: GroupMember) -> None:
    participant = {
        "kind": "character",
        "media": member.character.media,
    }
    render_participant_face(ctx, participant)


def render_group_guest_face() -> None:
    with ui.element("div").classes("cs-group-face cs-group-face-guest"):
        ui.icon(group_input_mode_icon("guest")).classes("text-sm")


def render_group_role_icon(mode: str) -> None:
    with ui.element("div").classes("cs-group-select-role-icon"):
        ui.icon(group_input_mode_icon(mode)).classes("text-sm")


def participant_profile_rows(participant: dict[str, Any]) -> list[tuple[str, str]]:
    if participant.get("kind") == "user":
        persona: GroupUserPersona | None = participant.get("persona")
        return [
            ("区分", "ユーザー"),
            ("表示名", persona.display_name if persona else ""),
            ("名前", persona.name if persona else ""),
            ("ハンドル", f"@{participant['handle']}"),
        ]

    member: GroupMember | None = participant.get("member")
    sheet = member.character if member else None
    return [
        ("年齢", sheet.age if sheet else ""),
        ("性別", sheet.gender if sheet else ""),
        ("職業・役割", sheet.occupation if sheet else ""),
        ("出身・所属", sheet.origin if sheet else ""),
    ]


def participant_profile_text(participant: dict[str, Any]) -> str:
    if participant.get("kind") == "user":
        persona: GroupUserPersona | None = participant.get("persona")
        return (persona.description if persona else "") or "未設定"

    member: GroupMember | None = participant.get("member")
    if member is None:
        return "未設定"
    sheet = member.character
    values = [
        sheet.personality,
        sheet.motivation,
        sheet.background,
        sheet.self_intro,
        sheet.sample_dialogues,
    ]
    return "\n".join(value for value in values if value).strip() or "未設定"


def render_recent_group(group: GroupChatRecord) -> None:
    with ui.element("div").classes("cs-group-recent-item"):
        with ui.element("div").classes("cs-group-recent-title-row"):
            ui.label(group.name).classes("cs-group-recent-title")
            ui.label(time_label(group.updated_at)).classes("cs-group-recent-time")
        ui.label("最近のチャットはまだありません").classes("cs-group-recent-preview")


def render_face(ctx, media: CharacterMedia, source: str) -> None:
    image = media.primary_image()
    if source == "persona":
        image_path = ctx.api_config.media_path(image.path) if image else None
    else:
        image_path = ctx.group_chats.media_path(image.path) if image else None
    style = cropped_background_style(image, image_path, image.face_rect, 1.0) if image and image_path else ""
    with ui.element("div").classes("cs-group-face").style(style):
        if not style:
            ui.icon("person").classes("text-sm")


def time_label(value: datetime) -> str:
    now = datetime.now()
    if value.date() == now.date():
        return value.strftime("%H:%M")
    if value.year == now.year:
        return f"{value.month}/{value.day}"
    return value.strftime("%Y/%m/%d")
