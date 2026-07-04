"""グループチャット UI の描画ヘルパー。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

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
from ..chat.commands import command_suggestions, parse_command_input
from ..chat.media import cropped_background_style
from .common import HANDLE_RE

if TYPE_CHECKING:
    from .controller import GroupChatPageController


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


_GROUP_MENTION_REFRESH_JS = r"""
event => {
  const input = event.target;
  const palette = document.querySelector('.cs-group-mention-palette');
  const wrapper = input && typeof input.closest === 'function'
    ? input.closest('.cs-chat-composer-input-wrap')
    : null;
  const value = input && typeof input.value === 'string' ? input.value : '';
  if (wrapper) {
    wrapper.classList.toggle('cs-chat-composer-input-has-text', value.length > 0);
  }
  if (!input || !palette) return;
  const mentionState = target => {
    const cursor = target.selectionStart ?? target.value.length;
    const before = target.value.slice(0, cursor);
    const at = before.lastIndexOf('@');
    if (at < 0) return null;
    const query = before.slice(at + 1);
    if (!/^[A-Za-z0-9_]*$/.test(query)) return null;
    const previous = at > 0 ? before[at - 1] : '';
    if (/[A-Za-z0-9_@]/.test(previous)) return null;
    return { start: at, end: cursor, query: query.toLowerCase() };
  };
  const state = mentionState(input);
  const options = Array.from(palette.querySelectorAll('.cs-group-mention-option'));
  const visible = [];
  for (const option of options) {
    const handle = (option.dataset.handle || '').toLowerCase();
    const matched = !!state && (state.query === '' || handle.startsWith(state.query));
    option.classList.toggle('cs-group-mention-option-hidden', !matched);
    if (matched) visible.push(option);
  }
  if (!state || !visible.length) {
    palette.classList.add('cs-group-mention-palette-hidden');
    return;
  }
  palette.classList.remove('cs-group-mention-palette-hidden');
  let active = visible.find(option => option.classList.contains('cs-group-mention-option-active'));
  if (!active) active = visible[0];
  for (const option of options) {
    const isActive = option === active;
    option.classList.toggle('cs-group-mention-option-active', isActive);
    option.setAttribute('aria-selected', isActive ? 'true' : 'false');
  }
}
"""

_GROUP_MENTION_INSERT_JS = r"""
event => {
  event.preventDefault();
  const option = event.currentTarget;
  const input = document.querySelector('.cs-chat-composer-input textarea');
  const palette = document.querySelector('.cs-group-mention-palette');
  if (!option || !input) return;
  const mentionState = target => {
    const cursor = target.selectionStart ?? target.value.length;
    const before = target.value.slice(0, cursor);
    const at = before.lastIndexOf('@');
    if (at < 0) return null;
    const query = before.slice(at + 1);
    if (!/^[A-Za-z0-9_]*$/.test(query)) return null;
    const previous = at > 0 ? before[at - 1] : '';
    if (/[A-Za-z0-9_@]/.test(previous)) return null;
    return { start: at, end: cursor };
  };
  const state = mentionState(input);
  const handle = option.dataset.handle || '';
  if (!state || !handle) return;
  const replacement = `@${handle} `;
  input.value = input.value.slice(0, state.start) + replacement + input.value.slice(state.end);
  const cursor = state.start + replacement.length;
  input.selectionStart = input.selectionEnd = cursor;
  input.dispatchEvent(new Event('input', { bubbles: true }));
  if (palette) palette.classList.add('cs-group-mention-palette-hidden');
  input.focus();
}
"""

_GROUP_CHAT_INPUT_KEYDOWN_JS = r"""
event => {
  const target = event.target;
  const mentionPalette = document.querySelector('.cs-group-mention-palette');
  const commandPalette = document.querySelector('.cs-chat-command-palette');
  const value = target && typeof target.value === 'string' ? target.value : '';
  const mentionState = input => {
    if (!input || typeof input.value !== 'string') return null;
    const cursor = input.selectionStart ?? input.value.length;
    const before = input.value.slice(0, cursor);
    const at = before.lastIndexOf('@');
    if (at < 0) return null;
    const query = before.slice(at + 1);
    if (!/^[A-Za-z0-9_]*$/.test(query)) return null;
    const previous = at > 0 ? before[at - 1] : '';
    if (/[A-Za-z0-9_@]/.test(previous)) return null;
    return { start: at, end: cursor };
  };
  const mentionOptions = () => mentionPalette
    ? Array.from(mentionPalette.querySelectorAll(
        '.cs-group-mention-option:not(.cs-group-mention-option-hidden)'
      ))
    : [];
  const commandMatch = value.match(/^([\s\S]*)\/([A-Za-z]*)$/);
  const commandOptions = commandPalette
    ? Array.from(commandPalette.querySelectorAll('.cs-chat-command-option'))
    : [];
  const activeIndex = options => Math.max(
    0,
    options.findIndex(option =>
      option.classList.contains('cs-group-mention-option-active')
      || option.classList.contains('cs-chat-command-option-active')
    ),
  );
  const setActive = (options, index, activeClass) => {
    options.forEach((option, optionIndex) => {
      const active = optionIndex === index;
      option.classList.toggle(activeClass, active);
      option.setAttribute('aria-selected', active ? 'true' : 'false');
      if (active && typeof option.scrollIntoView === 'function') {
        option.scrollIntoView({ block: 'nearest' });
      }
    });
  };
  const insertOption = option => {
    const state = mentionState(target);
    const handle = option && option.dataset ? option.dataset.handle : '';
    if (!state || !handle || !target || typeof target.value !== 'string') return false;
    const replacement = `@${handle} `;
    target.value = target.value.slice(0, state.start) + replacement + target.value.slice(state.end);
    const cursor = state.start + replacement.length;
    target.selectionStart = target.selectionEnd = cursor;
    target.dispatchEvent(new Event('input', { bubbles: true }));
    if (mentionPalette) mentionPalette.classList.add('cs-group-mention-palette-hidden');
    return true;
  };

  if (mentionPalette && !mentionPalette.classList.contains('cs-group-mention-palette-hidden')) {
    const options = mentionOptions();
    if (options.length && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
      event.preventDefault();
      const delta = event.key === 'ArrowDown' ? 1 : -1;
      setActive(options, (activeIndex(options) + delta + options.length) % options.length, 'cs-group-mention-option-active');
      return;
    }
    if (options.length && (event.key === 'Enter' || event.key === 'Tab') && !event.isComposing) {
      event.preventDefault();
      insertOption(options[activeIndex(options)] || options[0]);
      return;
    }
    if (event.key === 'Escape') {
      mentionPalette.classList.add('cs-group-mention-palette-hidden');
      return;
    }
  }

  if (
    commandMatch
    && commandPalette
    && !commandPalette.classList.contains('cs-chat-command-palette-hidden')
    && commandOptions.length
  ) {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const delta = event.key === 'ArrowDown' ? 1 : -1;
      setActive(
        commandOptions,
        (activeIndex(commandOptions) + delta + commandOptions.length) % commandOptions.length,
        'cs-chat-command-option-active',
      );
      return;
    }
    if (event.key === 'Enter' && !event.isComposing && !event.shiftKey && !event.altKey) {
      event.preventDefault();
      const active = commandOptions[activeIndex(commandOptions)] || commandOptions[0];
      const command = active && active.dataset ? active.dataset.command : '';
      if (command) {
        target.value = commandMatch[1] + '/' + command;
        target.dispatchEvent(new Event('input', { bubbles: true }));
      }
      commandPalette.classList.add('cs-chat-command-palette-hidden');
      emit(target && typeof target.value === 'string' ? target.value : '');
      return;
    }
    if (event.key === 'Escape') {
      commandPalette.classList.add('cs-chat-command-palette-hidden');
      return;
    }
  }

  if (event.key !== 'Enter' || event.isComposing || event.shiftKey || event.altKey) return;
  event.preventDefault();
  emit(target && typeof target.value === 'string' ? target.value : '');
}
"""


def render_shell(controller: "GroupChatPageController") -> None:
    with ui.element("div").classes("cs-chat-shell cs-group-chat-shell"):
        ui.element("div").classes("cs-chat-mobile-backdrop").on("click", lambda: controller.set_mobile_sidebar(False))

        with ui.element("aside").classes("cs-chat-mobile-sidebar cs-chat-panel"):
            with (
                ui.row()
                .classes("items-center justify-between px-3 py-2")
                .style("border-bottom: 1px solid var(--cs-border);")
            ):
                ui.label("グループ").classes("text-sm font-semibold")
                ui.button(icon="close", on_click=lambda: controller.set_mobile_sidebar(False)).props("flat round dense")
            with ui.element("div").classes("cs-chat-scroll"):
                mobile_profile = ui.element("div")
                controller.profile_containers.append((mobile_profile, True))
                controller.render_history_section()

        with ui.element("aside").classes("cs-chat-profile-pane cs-chat-panel"):
            profile = ui.element("div")
            controller.profile_containers.append((profile, False))

        with ui.element("aside").classes("cs-chat-side-pane cs-chat-panel"):
            with ui.element("div").classes("cs-chat-scroll"):
                side_profile = ui.element("div")
                controller.profile_containers.append((side_profile, True))
                controller.render_history_section()

        with ui.element("aside").classes("cs-chat-history-pane cs-chat-panel"):
            controller.render_history_section()

        with ui.element("section").classes("cs-chat-main cs-chat-panel"):
            controller.render_chat_main()

    controller.refresh_profiles()
    controller.scroll_messages_to_bottom()
    ui.timer(0.1, controller.restore_active_ai_job, once=True)


def refresh_profiles(controller: "GroupChatPageController") -> None:
    current = controller.current_participant()
    for container, compact in controller.profile_containers:
        container.clear()
        with container:
            render_group_profile_panel(
                controller.ctx,
                controller.group,
                controller.participants,
                current,
                selected_key=controller.selected["key"],
                active_tab=controller.selected["tab"],
                select_profile=controller.select_profile,
                select_tab=controller.select_tab,
                on_group_updated=controller.apply_group_update,
                compact=compact,
            )


def render_mention_options(controller: "GroupChatPageController") -> None:
    for index, participant in enumerate(controller.mention_participants()):
        handle = str(participant.get("handle") or "").strip()
        if not HANDLE_RE.match(handle):
            continue
        name = str(participant.get("name") or "メンバー")
        selected = "true" if index == 0 else "false"
        with (
            ui.element("button")
            .props(f"type=button data-handle={handle} aria-selected={selected}")
            .classes("cs-group-mention-option")
            .on(
                "mousedown",
                js_handler=_GROUP_MENTION_INSERT_JS,
            )
        ):
            render_participant_face(controller.ctx, participant)
            with ui.element("div").classes("cs-group-mention-info"):
                ui.label(name).classes("cs-group-mention-name")
                ui.label(f"@{handle}").classes("cs-group-mention-handle")
            kind = "User" if participant.get("kind") == "user" else "Char"
            ui.label(kind).classes("cs-group-mention-kind")


def refresh_mention_palette(controller: "GroupChatPageController") -> None:
    if controller.mention_palette is None:
        return
    controller.mention_palette.clear()
    with controller.mention_palette:
        controller.render_mention_options()
    controller.page_client.run_javascript(
        "document.querySelector('.cs-group-mention-palette')?.classList.add('cs-group-mention-palette-hidden');"
    )


def refresh_command_palette(controller: "GroupChatPageController", value: str) -> None:
    if controller.command_palette is None:
        return
    controller.command_palette.clear()
    parsed = parse_command_input(value)
    if parsed is None:
        controller.command_palette.classes("cs-chat-command-palette-hidden")
        return
    _, query = parsed
    suggestions = command_suggestions(query)
    controller.command_palette.classes(remove="cs-chat-command-palette-hidden")
    if not suggestions:
        with controller.command_palette:
            ui.label("該当するコマンドがありません").classes("text-xs text-grey-6")
        return
    with controller.command_palette:
        for index, command in enumerate(suggestions):
            classes = "cs-chat-command-option"
            if index == 0:
                classes += " cs-chat-command-option-active"
            with (
                ui.element("button")
                .props(f"type=button data-command={command.name} aria-selected={'true' if index == 0 else 'false'}")
                .classes(classes)
                .on(
                    "click",
                    controller._command_click_handler(command.name),
                )
            ):
                ui.label(f"/{command.name}").classes("cs-chat-command-name")
                ui.label(command.description).classes("cs-chat-command-desc")


def render_history_section(controller: "GroupChatPageController") -> None:
    with ui.element("div").classes("cs-chat-history-section") as section:
        controller.history_sections.append(section)
        controller.render_history()


def render_history(controller: "GroupChatPageController") -> None:
    with ui.element("div").classes("cs-chat-history-head"):
        ui.icon("history").style("color: var(--cs-accent);")
        ui.label("チャット履歴").classes("cs-chat-history-title")
        ui.space()
        ui.button(icon="add", on_click=controller.open_new_chat_dialog).props("flat round dense").tooltip(
            "新しいチャット"
        )
    with ui.element("div").classes("cs-chat-scroll"):
        with ui.element("div").classes("cs-chat-thread-list"):
            if not controller.threads:
                ui.label("保存済みチャットはまだありません").classes("cs-chat-history-empty")
                return
            for thread in controller.threads:
                classes = "cs-chat-thread"
                if thread.active:
                    classes += " cs-chat-thread-active"
                with ui.element("div").classes(classes):
                    with (
                        ui.element("button")
                        .props("type=button")
                        .classes("cs-chat-thread-open")
                        .on("click", controller._select_thread_handler(thread.id))
                    ):
                        with ui.element("div").classes("cs-chat-thread-title-row"):
                            ui.label(thread.title).classes("cs-chat-thread-title")
                            ui.label(thread.time_label).classes("cs-chat-thread-time")
                        ui.label(thread.preview).classes("cs-chat-thread-preview")
                    with ui.element("div").classes("cs-chat-thread-actions"):
                        ui.button(
                            icon="edit",
                            on_click=lambda thread_id=thread.id: controller.open_rename_chat_dialog(thread_id),
                        ).props("flat round dense size=sm").classes("cs-chat-thread-action").tooltip("タイトル変更")
                        ui.button(
                            icon="delete",
                            on_click=lambda thread_id=thread.id: controller.confirm_delete_chat_session(thread_id),
                        ).props("flat round dense size=sm color=negative").classes("cs-chat-thread-action").tooltip(
                            "チャット削除"
                        )


def refresh_history(controller: "GroupChatPageController") -> None:
    for section in list(controller.history_sections):
        section.clear()
        with section:
            controller.render_history()


def render_chat_main(controller: "GroupChatPageController") -> None:
    with ui.element("div").classes("cs-chat-main-head"):
        ui.button(icon="menu", on_click=lambda: controller.set_mobile_sidebar(True)).props("flat round dense").classes(
            "cs-chat-mobile-toggle"
        )
        with ui.column().classes("gap-0 cs-chat-main-title"):
            controller.title_label = ui.label(controller.chat_title()).classes("text-base font-bold")
            controller.subtitle_label = ui.label(controller.chat_subtitle()).classes("text-xs text-grey-6")
        chat_components.render_chat_header_menu(
            open_new_chat_dialog=controller.open_new_chat_dialog,
            open_system_prompt=controller.open_system_prompt_dialog,
            open_rename_current_chat=controller.open_rename_current_chat_dialog,
            confirm_delete_current_chat=controller.confirm_delete_current_chat,
        )

    with ui.element("div").classes("cs-chat-messages") as messages_container:
        controller.messages_container = messages_container
        controller.render_messages()

    with ui.element("div").classes("cs-chat-composer-shell"):
        with ui.element("div").classes("cs-chat-command-palette cs-chat-command-palette-hidden") as command_palette:
            controller.command_palette = command_palette

        with (
            ui.element("div")
            .classes("cs-group-mention-palette cs-group-mention-palette-hidden")
            .props("role=listbox") as mention_palette
        ):
            controller.mention_palette = mention_palette
            controller.render_mention_options()

        swipe_action_menu = ui.element("div").classes("cs-chat-swipe-action-menu cs-chat-swipe-action-menu-hidden")

        async def _apply_swipe_action(command: str) -> None:
            current_text = str(controller.input_box.value or "") if controller.input_box is not None else ""
            parsed = parse_command_input(current_text)
            left_text = parsed[0] if parsed is not None else current_text
            if controller.command_palette is not None:
                controller.command_palette.clear()
                controller.command_palette.classes("cs-chat-command-palette-hidden")
            if controller.mention_palette is not None:
                controller.mention_palette.classes("cs-group-mention-palette-hidden")
            swipe_action_menu.classes("cs-chat-swipe-action-menu-hidden")
            await controller.send_message(False, f"{left_text.rstrip()}/{command}")

        def _swipe_action_click_handler(command: str):
            async def _handler(_) -> None:
                await _apply_swipe_action(command)

            return _handler

        with swipe_action_menu:
            for command, label, icon in (
                ("choices", "選択肢を生成", "format_list_bulleted"),
                ("fill", "続きを補完", "auto_fix_high"),
                ("tailor", "書き直す", "edit_note"),
            ):
                with (
                    ui.element("button")
                    .props(f"type=button data-swipe-command={command}")
                    .classes("cs-chat-swipe-action-option")
                    .on("click", _swipe_action_click_handler(command))
                ):
                    ui.icon(icon).classes("cs-chat-swipe-action-icon")
                    ui.label(f"/{command}").classes("cs-chat-swipe-action-command")
                    ui.label(label).classes("cs-chat-swipe-action-label")

        with ui.element("div").classes("cs-chat-composer"):
            controller.render_input_role_selector()
            with ui.element("div").classes("cs-chat-composer-input-wrap"):
                controller.input_box = (
                    ui.textarea(placeholder="メッセージを入力")
                    .props("outlined dense rows=1 autogrow")
                    .classes("cs-chat-composer-input")
                )
                voice_input_btn = (
                    ui.button(icon="mic")
                    .props("round flat dense aria-label=音声入力")
                    .classes("cs-chat-voice-input")
                    .tooltip("音声入力")
                )
                voice_input_btn.on(
                    "click",
                    js_handler=chat_components.VOICE_INPUT_CLICK_JS,
                )

                async def _send_from_enter(e) -> None:
                    if isinstance(e.args, list):
                        value = str(e.args[0] or "") if e.args else ""
                    else:
                        value = str(e.args or "")
                    await controller.send_message(False, value)

                controller.input_box.on_value_change(lambda e: controller.refresh_command_palette(str(e.value or "")))
                controller.input_box.on("input", js_handler=_GROUP_MENTION_REFRESH_JS)
                controller.input_box.on("keyup", js_handler=_GROUP_MENTION_REFRESH_JS)
                controller.input_box.on("click", js_handler=_GROUP_MENTION_REFRESH_JS)
                controller.input_box.on("focus", js_handler=_GROUP_MENTION_REFRESH_JS)
                controller.input_box.on(
                    "touchstart",
                    js_handler="""
event => {
  const touch = event.touches && event.touches[0];
  if (!touch) return;
  window.__csComposerSwipeStart = {
x: touch.clientX,
y: touch.clientY,
time: Date.now(),
  };
}
""",
                )
                controller.input_box.on(
                    "touchend",
                    js_handler="""
event => {
  const start = window.__csComposerSwipeStart;
  const touch = event.changedTouches && event.changedTouches[0];
  window.__csComposerSwipeStart = null;
  if (!start || !touch) return;
  const dx = touch.clientX - start.x;
  const dy = touch.clientY - start.y;
  const elapsed = Date.now() - start.time;
  const isSwipeUp = dy < -42 && Math.abs(dy) > Math.abs(dx) * 1.15 && elapsed < 900;
  if (!isSwipeUp) return;
  const menu = document.querySelector('.cs-chat-swipe-action-menu');
  const commandPalette = document.querySelector('.cs-chat-command-palette');
  const mentionPalette = document.querySelector('.cs-group-mention-palette');
  if (!menu) return;
  event.preventDefault();
  if (commandPalette) commandPalette.classList.add('cs-chat-command-palette-hidden');
  if (mentionPalette) mentionPalette.classList.add('cs-group-mention-palette-hidden');
  menu.classList.remove('cs-chat-swipe-action-menu-hidden');
  if (!window.__csSwipeActionDismiss) {
window.__csSwipeActionDismiss = dismissEvent => {
  const currentMenu = document.querySelector('.cs-chat-swipe-action-menu');
  if (!currentMenu || currentMenu.classList.contains('cs-chat-swipe-action-menu-hidden')) return;
  const target = dismissEvent.target;
  if (target && typeof target.closest === 'function' && target.closest('.cs-chat-swipe-action-menu')) return;
  currentMenu.classList.add('cs-chat-swipe-action-menu-hidden');
};
document.addEventListener('click', window.__csSwipeActionDismiss, true);
document.addEventListener('touchstart', window.__csSwipeActionDismiss, true);
  }
}
""",
                )
                controller.input_box.on(
                    "blur",
                    js_handler="""
event => {
  setTimeout(() => {
document.querySelector('.cs-group-mention-palette')
  ?.classList.add('cs-group-mention-palette-hidden');
  }, 120);
}
""",
                )
                controller.input_box.on(
                    "keydown",
                    _send_from_enter,
                    js_handler=_GROUP_CHAT_INPUT_KEYDOWN_JS,
                )

            async def _send_from_button(_) -> None:
                await controller.send_message(True)

            async def _guide_from_long_tap(e) -> None:
                if isinstance(e.args, list):
                    value = str(e.args[0] or "") if e.args else ""
                else:
                    value = str(e.args or "")
                parsed = parse_command_input(value)
                left_text = parsed[0] if parsed is not None else value
                await controller.send_message(False, f"{left_text.rstrip()}/guide")

            controller.send_button = ui.button(icon="send").props("round color=primary unelevated")
            controller.send_button.on(
                "click",
                _send_from_button,
                js_handler="""
event => {
  if (window.__csSendLongTapSuppressClick) {
window.__csSendLongTapSuppressClick = false;
event.preventDefault();
event.stopPropagation();
return;
  }
  emit();
}
""",
            )
            controller.send_button.on(
                "touchstart",
                _guide_from_long_tap,
                js_handler="""
event => {
  const touch = event.touches && event.touches[0];
  if (!touch) return;
  clearTimeout(window.__csSendLongTapTimer);
  window.__csSendLongTapStart = {
x: touch.clientX,
y: touch.clientY,
  };
  window.__csSendLongTapTriggered = false;
  window.__csSendLongTapTimer = setTimeout(() => {
window.__csSendLongTapTriggered = true;
window.__csSendLongTapSuppressClick = true;
setTimeout(() => {
  window.__csSendLongTapSuppressClick = false;
}, 1200);
const input = document.querySelector('.cs-chat-composer-input textarea');
emit(input && typeof input.value === 'string' ? input.value : '');
  }, 650);
}
""",
            )
            controller.send_button.on(
                "touchmove",
                js_handler="""
event => {
  const start = window.__csSendLongTapStart;
  const touch = event.touches && event.touches[0];
  if (!start || !touch) return;
  const dx = touch.clientX - start.x;
  const dy = touch.clientY - start.y;
  if (Math.hypot(dx, dy) > 14) {
clearTimeout(window.__csSendLongTapTimer);
  }
}
""",
            )
            controller.send_button.on(
                "touchend",
                js_handler="""
event => {
  clearTimeout(window.__csSendLongTapTimer);
  window.__csSendLongTapStart = null;
  if (window.__csSendLongTapTriggered) {
event.preventDefault();
  }
}
""",
            )
            controller.send_button.on(
                "touchcancel",
                js_handler="""
event => {
  clearTimeout(window.__csSendLongTapTimer);
  window.__csSendLongTapStart = null;
  window.__csSendLongTapTriggered = false;
}
""",
            )
    controller.refresh_input_mode_indicator()


def render_input_role_selector(controller: "GroupChatPageController") -> None:
    with ui.button().props("flat dense unelevated aria-label=入力ロールを変更").classes("cs-chat-mode-icon"):
        controller.input_mode_icon = ui.element("div").classes("cs-chat-mode-icon-display")
        with controller.input_mode_icon:
            ui.icon(group_input_mode_icon(controller.input_mode))
        with ui.menu().classes("cs-chat-mode-menu"):
            with (
                ui.element("button")
                .props("type=button")
                .classes("cs-group-menu-option")
                .on(
                    "click",
                    lambda _: controller.set_input_mode("user"),
                )
            ):
                render_group_user_menu_face(controller.ctx, controller.group.user_persona)
                ui.label("ユーザー").classes("cs-group-menu-option-label")
                ui.element("span")
            with ui.element("button").props("type=button").classes("cs-group-menu-parent"):
                render_group_role_icon("character")
                ui.label("キャラクター").classes("cs-group-menu-option-label")
                ui.icon("chevron_right").classes("text-grey-6")
                with (
                    ui.menu()
                    .props('anchor="top end" self="top start"')
                    .classes("cs-chat-mode-menu cs-group-character-submenu")
                ):
                    active = controller.active_members()
                    if not active:
                        ui.label("参加キャラがいません").classes("text-xs text-grey-6 px-3 py-2")
                    for member in active:
                        with (
                            ui.element("button")
                            .props("type=button")
                            .classes("cs-group-menu-option")
                            .on(
                                "click",
                                lambda _, member=member: controller.set_character_input_member(member),
                            )
                        ):
                            render_group_member_menu_face(controller.ctx, member)
                            ui.label(f"{member.character.name} / @{member.handle}").classes(
                                "cs-group-menu-option-label"
                            )
                            ui.element("span")
                    with (
                        ui.element("button")
                        .props("type=button")
                        .classes("cs-group-menu-option")
                        .on(
                            "click",
                            lambda _: controller.open_guest_input_mode_dialog(),
                        )
                    ):
                        render_group_role_icon("guest")
                        ui.label("ゲスト").classes("cs-group-menu-option-label")
                        ui.element("span")
            with (
                ui.element("button")
                .props("type=button")
                .classes("cs-group-menu-option")
                .on(
                    "click",
                    lambda _: controller.set_input_mode("narration"),
                )
            ):
                render_group_role_icon("narration")
                ui.label("ナラティブ").classes("cs-group-menu-option-label")
                ui.element("span")
            with (
                ui.element("button")
                .props("type=button")
                .classes("cs-group-menu-option")
                .on(
                    "click",
                    lambda _: controller.set_input_mode("memo"),
                )
            ):
                render_group_role_icon("memo")
                ui.label("コメント").classes("cs-group-menu-option-label")
                ui.element("span")


def refresh_input_mode_indicator(controller: "GroupChatPageController") -> None:
    if controller.input_mode_icon is None:
        return
    controller.input_mode_icon.clear()
    with controller.input_mode_icon:
        ui.icon(group_input_mode_icon(controller.input_mode))


def refresh_chat_header(controller: "GroupChatPageController") -> None:
    if controller.title_label is not None:
        controller.title_label.set_text(controller.chat_title())
    if controller.subtitle_label is not None:
        controller.subtitle_label.set_text(controller.chat_subtitle())


def render_messages(controller: "GroupChatPageController") -> None:
    if not controller.messages:
        with ui.element("div").classes("cs-group-chat-empty"):
            ui.label("チャットはまだありません")
        return
    for index, message in enumerate(controller.messages):
        render_group_chat_message(
            controller.ctx,
            message,
            controller.participants,
            index=index,
            rewind_message=controller.confirm_rewind_to_message,
            rewrite_message=controller.open_rewrite_message_dialog,
            regenerate_message=controller.confirm_or_regenerate_character_message,
            play_tts_message=controller.play_tts_message,
            tts_playable=controller.message_tts_playable(message),
            tts_generating=controller.tts_generating_index == index,
        )


def refresh_messages(controller: "GroupChatPageController", *, scroll_to_bottom: bool = False) -> None:
    if controller.messages_container is None:
        return
    controller.messages_container.clear()
    with controller.messages_container:
        controller.render_messages()
    if scroll_to_bottom:
        controller.scroll_messages_to_bottom()
