import asyncio

from src.core.character.schemas import CharacterSheet, FaceRect
from src.core.chat.schemas import ChatMode, UserPersona
from src.core.conversation.history import chat_settings_from_dict, chat_settings_to_dict
from src.core.conversation.schemas import ChatSessionSettings
from src.core.conversation.solo import (
    USER_PERSONA_SOURCE_CHARACTER,
    USER_PERSONA_SOURCE_PERSONA,
    render_mode_for_sheet,
)
from src.services.user_persona import UserPersonaService
from src.storage.api_config_store import ApiConfigStore
from src.ui2.chat_logic import user_persona_from_character_sheet


def test_user_persona_display_name_falls_back_to_name() -> None:
    persona = UserPersona(
        id="persona-1",
        name="会話内の名前",
        description="設定",
    )

    assert persona.display_name == "会話内の名前"


def test_user_persona_display_name_uses_persona_name() -> None:
    persona = UserPersona(
        id="persona-1",
        name="会話内の名前",
        persona_name="表示用のペルソナ名",
        description="設定",
    )

    assert persona.display_name == "表示用のペルソナ名"


def test_chat_mode_uses_persona_name_field_for_conversation_name() -> None:
    mode = ChatMode(
        id="mode-1",
        name="テスト",
        premise_template="{{ user_persona_name }}が会話する。",
        situation_template="{{ user_persona_name }}が出会う。",
    )
    sheet = CharacterSheet(id="character-1", name="テストキャラ")
    persona = UserPersona(
        id="persona-1",
        name="会話内の名前",
        persona_name="表示用のペルソナ名",
        description="設定",
    )

    premise, situation = render_mode_for_sheet(mode, sheet, persona)

    assert "会話内の名前" in premise
    assert "会話内の名前" in situation
    assert "表示用のペルソナ名" not in premise
    assert "表示用のペルソナ名" not in situation


def test_user_persona_keeps_default_empty_media() -> None:
    persona = UserPersona(
        id="persona-1",
        name="会話内の名前",
        description="設定",
    )

    assert persona.media.primary_image() is None
    assert persona.media.primary_voice() is None


def test_user_persona_image_bytes_are_saved(tmp_path) -> None:
    store = ApiConfigStore(tmp_path / "config.json")
    service = UserPersonaService(store, tmp_path)
    persona = service.create_user_persona(
        UserPersona(
            id="persona-1",
            name="会話内の名前",
            description="設定",
        )
    )

    saved = asyncio.run(
        service.save_user_persona_image_bytes(
            persona.id,
            b"image-bytes",
            filename="persona.png",
            content_type="image/png",
            width=128,
            height=128,
        )
    )

    image = saved.media.primary_image()
    assert image is not None
    assert image.width == 128
    assert image.height == 128
    assert image.path.startswith("user_personas/persona-1/images/")
    assert service.media_path(image.path).read_bytes() == b"image-bytes"


def test_user_persona_face_rect_is_clamped_and_saved(tmp_path) -> None:
    store = ApiConfigStore(tmp_path / "config.json")
    service = UserPersonaService(store, tmp_path)
    persona = service.create_user_persona(
        UserPersona(
            id="persona-1",
            name="会話内の名前",
            description="設定",
        )
    )
    asyncio.run(
        service.save_user_persona_image_bytes(
            persona.id,
            b"image-bytes",
            filename="persona.png",
            content_type="image/png",
        )
    )

    saved = service.update_user_persona_face_rect(
        persona.id,
        FaceRect(x=-0.5, y=0.8, width=2.0, height=0.5),
        image_width=256,
        image_height=128,
    )

    image = saved.media.primary_image()
    assert image is not None
    assert image.face_rect == FaceRect(x=0.0, y=0.5, width=1.0, height=0.5)
    assert image.width == 256
    assert image.height == 128
    loaded = service.get_user_persona(persona.id)
    assert loaded is not None
    loaded_image = loaded.media.primary_image()
    assert loaded_image is not None
    assert loaded_image.face_rect == image.face_rect


def test_character_sheet_can_be_used_as_user_persona() -> None:
    sheet = CharacterSheet(
        id="character-user-1",
        name="ユーザー役キャラ",
        raw_markdown="# ユーザー役キャラ\n\n## 性格・内面\n落ち着いて話す。",
    )

    persona = user_persona_from_character_sheet(sheet)

    assert persona.id == sheet.id
    assert persona.name == "ユーザー役キャラ"
    assert "落ち着いて話す" in persona.description
    assert persona.media is sheet.media


def test_chat_settings_keep_user_persona_source() -> None:
    settings = ChatSessionSettings(
        profile_id="profile-1",
        chat_mode_id="mode-1",
        chat_mode_name="テストモード",
        chat_premise="テスト前提",
        situation="",
        user_persona_id="character-user-1",
        user_persona_name="ユーザー役キャラ",
        user_persona_description="設定",
        user_persona_source=USER_PERSONA_SOURCE_CHARACTER,
    )

    loaded = chat_settings_from_dict(chat_settings_to_dict(settings))

    assert loaded.user_persona_source == USER_PERSONA_SOURCE_CHARACTER
    assert chat_settings_from_dict({}).user_persona_source == USER_PERSONA_SOURCE_PERSONA
