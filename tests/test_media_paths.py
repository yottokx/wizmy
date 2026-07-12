from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.core.character.schemas import CharacterImageAsset, CharacterSheet, FaceRect
from src.core.chat.schemas import UserPersona
from src.core.media import read_image_size
from src.services.character import CharacterService
from src.services.group_chat import GroupChatService
from src.services.user_persona import UserPersonaService
from src.storage.api_config_store import ApiConfigStore
from src.storage.character_repository import CharacterRepository
from src.storage.group_chat_repository import GroupChatRepository
from src.ui2.components.portrait import _image_dimensions

UUID_RE = r"[0-9a-f]{32}"


class UploadStub:
    def __init__(self, name: str, content_type: str, data: bytes) -> None:
        self.name = name
        self.content_type = content_type
        self._data = data

    async def save(self, target: Path) -> None:
        target.write_bytes(self._data)


def assert_path_pattern(relative_path: str, pattern: str) -> None:
    assert re.fullmatch(pattern, relative_path), relative_path


def assert_absolute_file(data_dir: Path, path: Path, expected_bytes: bytes, pattern: str) -> str:
    assert path.is_file()
    assert path.read_bytes() == expected_bytes
    relative_path = path.resolve().relative_to(data_dir.resolve()).as_posix()
    assert_path_pattern(relative_path, pattern)
    return relative_path


def service_media_file(service, relative_path: str, expected_bytes: bytes) -> Path:
    path = service.media_path(relative_path)
    assert path is not None
    assert path.read_bytes() == expected_bytes
    return path


def riff_webp(chunk_type: bytes, payload: bytes) -> bytes:
    chunk = chunk_type + len(payload).to_bytes(4, "little") + payload
    if len(payload) % 2:
        chunk += b"\x00"
    riff_size = len(b"WEBP") + len(chunk)
    return b"RIFF" + riff_size.to_bytes(4, "little") + b"WEBP" + chunk


def webp_vp8x(width: int, height: int) -> bytes:
    payload = b"\x00\x00\x00\x00" + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    return riff_webp(b"VP8X", payload)


def webp_vp8l(width: int, height: int) -> bytes:
    bits = (width - 1) | ((height - 1) << 14)
    return riff_webp(b"VP8L", b"\x2f" + bits.to_bytes(4, "little"))


def webp_vp8(width: int, height: int) -> bytes:
    payload = b"\x00\x00\x00\x9d\x01\x2a" + width.to_bytes(2, "little") + height.to_bytes(2, "little")
    return riff_webp(b"VP8 ", payload)


def test_read_image_size_supports_webp_variants(tmp_path: Path) -> None:
    cases = [
        ("vp8x.webp", webp_vp8x(640, 360), (640, 360)),
        ("vp8l.webp", webp_vp8l(321, 123), (321, 123)),
        ("vp8.webp", webp_vp8(1024, 768), (1024, 768)),
    ]
    for filename, data, expected_size in cases:
        path = tmp_path / filename
        path.write_bytes(data)
        assert read_image_size(path) == expected_size

    path = tmp_path / "fallback.webp"
    path.write_bytes(webp_vp8x(512, 288))
    image = CharacterImageAsset(id="image-1", path="fallback.webp")
    assert _image_dimensions(image, path) == (512, 288)


async def test_character_service_media_paths_are_fixed(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    repo = CharacterRepository(tmp_path / "characters.db")
    await repo.initialize()
    service = CharacterService(repo, data_dir)
    await service.save(CharacterSheet(id="character-1", name="テストキャラ"))

    uploaded_image = webp_vp8x(640, 360)
    saved = await service.save_image(
        "character-1",
        UploadStub("portrait.WEBP", "", uploaded_image),
    )
    image = saved.media.primary_image()
    assert image is not None
    assert_path_pattern(image.path, rf"characters/character-1/images/{UUID_RE}\.webp")
    assert image.width == 640
    assert image.height == 360
    uploaded_image_path = service_media_file(service, image.path, uploaded_image)

    saved = await service.update_face_rect(
        "character-1",
        FaceRect(x=-0.5, y=0.8, width=2.0, height=0.5),
        image_width=320,
        image_height=180,
    )
    image = saved.media.primary_image()
    assert image is not None
    assert image.face_rect == FaceRect(x=0.0, y=0.5, width=1.0, height=0.5)
    assert image.width == 320
    assert image.height == 180

    saved = await service.update_bust_rect(
        "character-1",
        FaceRect(x=0.9, y=0.9, width=0.5, height=0.5),
    )
    image = saved.media.primary_image()
    assert image is not None
    assert image.bust_rect == FaceRect(x=0.5, y=0.5, width=0.5, height=0.5)

    saved = await service.save_image_bytes(
        "character-1",
        b"generated-image",
        filename="generated.JPG",
        content_type="",
        width=-10,
        height=64,
    )
    image = saved.media.primary_image()
    assert image is not None
    assert_path_pattern(image.path, rf"characters/character-1/images/{UUID_RE}\.jpg")
    service_media_file(service, image.path, b"generated-image")
    assert image.width == 0
    assert image.height == 64
    assert not uploaded_image_path.exists()

    saved = await service.save_voice(
        "character-1",
        UploadStub("voice.MP3", "", b"uploaded-voice"),
    )
    voice = saved.media.primary_voice()
    assert voice is not None
    assert_path_pattern(voice.path, rf"characters/character-1/voices/{UUID_RE}\.mp3")
    uploaded_voice_path = service_media_file(service, voice.path, b"uploaded-voice")

    saved = await service.save_voice_bytes(
        "character-1",
        b"designed-voice",
        filename="voice.WEBM",
        content_type="",
    )
    voice = saved.media.primary_voice()
    assert voice is not None
    assert_path_pattern(voice.path, rf"characters/character-1/voices/{UUID_RE}\.webm")
    service_media_file(service, voice.path, b"designed-voice")
    assert not uploaded_voice_path.exists()

    image_preview = service.save_image_preview(
        "character-1",
        b"preview-image-1",
        filename="preview.GIF",
        content_type="",
    )
    assert_absolute_file(
        data_dir,
        image_preview,
        b"preview-image-1",
        rf"characters/character-1/images/previews/preview-{UUID_RE}\.gif",
    )
    replaced_image_preview = service.save_image_preview("character-1", b"preview-image-2")
    assert_absolute_file(
        data_dir,
        replaced_image_preview,
        b"preview-image-2",
        rf"characters/character-1/images/previews/preview-{UUID_RE}\.png",
    )
    assert not image_preview.exists()

    tts_preview = service.save_tts_preview("character-1", b"preview-audio")
    assert_absolute_file(
        data_dir,
        tts_preview,
        b"preview-audio",
        rf"characters/character-1/tts/preview-{UUID_RE}\.wav",
    )
    replaced_tts_preview = service.save_tts_preview("character-1", b"preview-audio-2")
    assert_absolute_file(
        data_dir,
        replaced_tts_preview,
        b"preview-audio-2",
        rf"characters/character-1/tts/preview-{UUID_RE}\.wav",
    )
    assert not tts_preview.exists()

    playback = service.save_tts_playback("character-1", b"playback-audio")
    assert_absolute_file(
        data_dir,
        playback,
        b"playback-audio",
        rf"characters/character-1/tts/playback-{UUID_RE}\.wav",
    )
    replaced_playback = service.save_tts_playback("character-1", b"playback-audio-2")
    assert_absolute_file(
        data_dir,
        replaced_playback,
        b"playback-audio-2",
        rf"characters/character-1/tts/playback-{UUID_RE}\.wav",
    )
    assert not playback.exists()

    assert await service.delete("character-1") is True
    assert not (data_dir / "characters" / "character-1").exists()


async def test_group_member_media_paths_are_fixed(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    service = GroupChatService(
        GroupChatRepository(tmp_path / "groups.db"),
        data_dir,
    )
    await service.initialize()
    group = await service.create_group(
        name="テストグループ",
        world="テスト用の世界",
        completion_profile_id="",
        members=[(CharacterSheet(id="character-1", name="メンバー"), "Alice")],
        user_persona=UserPersona(id="persona-1", name="テストユーザー"),
        user_handle="User",
    )
    member_id = group.members[0].id
    member_root_pattern = rf"groups/{re.escape(group.id)}/members/{re.escape(member_id)}"

    saved = await service.save_member_image(
        group.id,
        member_id,
        UploadStub("member.JPEG", "", b"uploaded-member-image"),
    )
    assert saved is not None
    image = saved.character.media.primary_image()
    assert image is not None
    assert_path_pattern(image.path, rf"{member_root_pattern}/images/{UUID_RE}\.jpeg")
    uploaded_image_path = service_media_file(service, image.path, b"uploaded-member-image")

    saved = await service.update_member_face_rect(
        group.id,
        member_id,
        FaceRect(x=-0.5, y=0.25, width=2.0, height=1.0),
        image_width=256,
        image_height=128,
    )
    assert saved is not None
    image = saved.character.media.primary_image()
    assert image is not None
    assert image.face_rect == FaceRect(x=0.0, y=0.25, width=1.0, height=0.75)
    assert image.width == 256
    assert image.height == 128

    saved = await service.update_member_bust_rect(
        group.id,
        member_id,
        FaceRect(x=0.9, y=0.9, width=0.5, height=0.5),
    )
    assert saved is not None
    image = saved.character.media.primary_image()
    assert image is not None
    assert image.bust_rect.x == 0.9
    assert image.bust_rect.y == 0.9
    assert image.bust_rect.width == pytest.approx(0.1)
    assert image.bust_rect.height == pytest.approx(0.1)

    saved = await service.save_member_image_bytes(
        group.id,
        member_id,
        b"generated-member-image",
        filename="generated.PNG",
        content_type="",
    )
    assert saved is not None
    image = saved.character.media.primary_image()
    assert image is not None
    assert_path_pattern(image.path, rf"{member_root_pattern}/images/{UUID_RE}\.png")
    service_media_file(service, image.path, b"generated-member-image")
    assert not uploaded_image_path.exists()

    saved = await service.save_member_voice(
        group.id,
        member_id,
        UploadStub("member.FLAC", "", b"uploaded-member-voice"),
    )
    assert saved is not None
    voice = saved.character.media.primary_voice()
    assert voice is not None
    assert_path_pattern(voice.path, rf"{member_root_pattern}/voices/{UUID_RE}\.flac")
    uploaded_voice_path = service_media_file(service, voice.path, b"uploaded-member-voice")

    saved = await service.save_member_voice_bytes(
        group.id,
        member_id,
        b"designed-member-voice",
        filename="voice.WAV",
        content_type="",
    )
    assert saved is not None
    voice = saved.character.media.primary_voice()
    assert voice is not None
    assert_path_pattern(voice.path, rf"{member_root_pattern}/voices/{UUID_RE}\.wav")
    service_media_file(service, voice.path, b"designed-member-voice")
    assert not uploaded_voice_path.exists()

    image_preview = service.save_member_image_preview(
        group.id,
        member_id,
        b"member-preview-1",
        filename="preview.WEBP",
        content_type="",
    )
    assert_absolute_file(
        data_dir,
        image_preview,
        b"member-preview-1",
        rf"{member_root_pattern}/images/previews/preview-{UUID_RE}\.webp",
    )
    replaced_image_preview = service.save_member_image_preview(group.id, member_id, b"member-preview-2")
    assert_absolute_file(
        data_dir,
        replaced_image_preview,
        b"member-preview-2",
        rf"{member_root_pattern}/images/previews/preview-{UUID_RE}\.png",
    )
    assert not image_preview.exists()

    tts_preview = service.save_member_tts_preview(group.id, member_id, b"member-preview-audio")
    assert_absolute_file(
        data_dir,
        tts_preview,
        b"member-preview-audio",
        rf"{member_root_pattern}/tts/preview-{UUID_RE}\.wav",
    )
    replaced_tts_preview = service.save_member_tts_preview(group.id, member_id, b"member-preview-audio-2")
    assert_absolute_file(
        data_dir,
        replaced_tts_preview,
        b"member-preview-audio-2",
        rf"{member_root_pattern}/tts/preview-{UUID_RE}\.wav",
    )
    assert not tts_preview.exists()

    playback = service.save_member_tts_playback(group.id, member_id, b"member-playback-audio")
    assert_absolute_file(
        data_dir,
        playback,
        b"member-playback-audio",
        rf"{member_root_pattern}/tts/playback-{UUID_RE}\.wav",
    )
    replaced_playback = service.save_member_tts_playback(group.id, member_id, b"member-playback-audio-2")
    assert_absolute_file(
        data_dir,
        replaced_playback,
        b"member-playback-audio-2",
        rf"{member_root_pattern}/tts/playback-{UUID_RE}\.wav",
    )
    assert not playback.exists()

    assert await service.delete_group(group.id) is True
    assert not (data_dir / "groups" / group.id).exists()


async def test_user_persona_service_persona_and_narrator_media_paths_are_fixed(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    service = UserPersonaService(
        ApiConfigStore(tmp_path / "config.json"),
        data_dir,
    )
    persona = service.create_user_persona(
        UserPersona(id="persona-1", name="テストユーザー", description="テスト用ペルソナ")
    )

    saved = await service.save_user_persona_image(
        persona.id,
        UploadStub("persona.WEBP", "", b"uploaded-persona-image"),
    )
    image = saved.media.primary_image()
    assert image is not None
    assert_path_pattern(image.path, rf"user_personas/{persona.id}/images/{UUID_RE}\.webp")
    uploaded_image_path = service_media_file(service, image.path, b"uploaded-persona-image")

    saved = service.update_user_persona_face_rect(
        persona.id,
        FaceRect(x=-0.5, y=0.8, width=2.0, height=0.5),
        image_width=320,
        image_height=180,
    )
    image = saved.media.primary_image()
    assert image is not None
    assert image.face_rect == FaceRect(x=0.0, y=0.5, width=1.0, height=0.5)
    assert image.width == 320
    assert image.height == 180

    saved = await service.save_user_persona_image_bytes(
        persona.id,
        b"generated-persona-image",
        filename="generated.PNG",
        content_type="",
    )
    image = saved.media.primary_image()
    assert image is not None
    assert_path_pattern(image.path, rf"user_personas/{persona.id}/images/{UUID_RE}\.png")
    service_media_file(service, image.path, b"generated-persona-image")
    assert not uploaded_image_path.exists()

    saved = await service.save_user_persona_voice(
        persona.id,
        UploadStub("persona.OGG", "", b"uploaded-persona-voice"),
    )
    voice = saved.media.primary_voice()
    assert voice is not None
    assert_path_pattern(voice.path, rf"user_personas/{persona.id}/voices/{UUID_RE}\.ogg")
    uploaded_voice_path = service_media_file(service, voice.path, b"uploaded-persona-voice")

    saved = await service.save_user_persona_voice_bytes(
        persona.id,
        b"designed-persona-voice",
        filename="voice.M4A",
        content_type="",
    )
    voice = saved.media.primary_voice()
    assert voice is not None
    assert_path_pattern(voice.path, rf"user_personas/{persona.id}/voices/{UUID_RE}\.m4a")
    service_media_file(service, voice.path, b"designed-persona-voice")
    assert not uploaded_voice_path.exists()

    image_preview = service.save_user_persona_image_preview(
        persona.id,
        b"persona-preview-1",
        filename="preview.GIF",
        content_type="",
    )
    assert_absolute_file(
        data_dir,
        image_preview,
        b"persona-preview-1",
        rf"user_personas/{persona.id}/images/previews/preview-{UUID_RE}\.gif",
    )
    replaced_image_preview = service.save_user_persona_image_preview(persona.id, b"persona-preview-2")
    assert_absolute_file(
        data_dir,
        replaced_image_preview,
        b"persona-preview-2",
        rf"user_personas/{persona.id}/images/previews/preview-{UUID_RE}\.png",
    )
    assert not image_preview.exists()

    tts_preview = service.save_user_persona_tts_preview(persona.id, b"persona-preview-audio")
    assert_absolute_file(
        data_dir,
        tts_preview,
        b"persona-preview-audio",
        rf"user_personas/{persona.id}/tts/preview-{UUID_RE}\.wav",
    )
    kept_tts_preview = service.save_user_persona_tts_preview(
        persona.id,
        b"persona-preview-audio-2",
        replace_existing=False,
    )
    assert_absolute_file(
        data_dir,
        kept_tts_preview,
        b"persona-preview-audio-2",
        rf"user_personas/{persona.id}/tts/preview-{UUID_RE}\.wav",
    )
    assert tts_preview.exists()

    playback = service.save_user_persona_tts_playback(persona.id, b"persona-playback-audio")
    assert_absolute_file(
        data_dir,
        playback,
        b"persona-playback-audio",
        rf"user_personas/{persona.id}/tts/playback-{UUID_RE}\.wav",
    )
    replaced_playback = service.save_user_persona_tts_playback(persona.id, b"persona-playback-audio-2")
    assert_absolute_file(
        data_dir,
        replaced_playback,
        b"persona-playback-audio-2",
        rf"user_personas/{persona.id}/tts/playback-{UUID_RE}\.wav",
    )
    assert not playback.exists()

    narrator_voice = await service.save_narrator_voice_bytes(
        b"narrator-voice",
        filename="narrator.MP3",
        content_type="",
    )
    assert_path_pattern(narrator_voice.path, rf"narrator/voices/{UUID_RE}\.mp3")
    narrator_voice_path = service_media_file(service, narrator_voice.path, b"narrator-voice")

    replaced_narrator_voice = await service.save_narrator_voice_bytes(
        b"narrator-voice-2",
        filename="narrator.WAV",
        content_type="",
    )
    assert_path_pattern(replaced_narrator_voice.path, rf"narrator/voices/{UUID_RE}\.wav")
    service_media_file(service, replaced_narrator_voice.path, b"narrator-voice-2")
    assert not narrator_voice_path.exists()

    narrator_preview = service.save_narrator_tts_preview(b"narrator-preview-audio")
    assert_absolute_file(
        data_dir,
        narrator_preview,
        b"narrator-preview-audio",
        rf"narrator/tts/preview-{UUID_RE}\.wav",
    )
    replaced_narrator_preview = service.save_narrator_tts_preview(b"narrator-preview-audio-2")
    assert_absolute_file(
        data_dir,
        replaced_narrator_preview,
        b"narrator-preview-audio-2",
        rf"narrator/tts/preview-{UUID_RE}\.wav",
    )
    assert not narrator_preview.exists()

    narrator_playback = service.save_narrator_tts_playback(b"narrator-playback-audio")
    assert_absolute_file(
        data_dir,
        narrator_playback,
        b"narrator-playback-audio",
        rf"narrator/tts/playback-{UUID_RE}\.wav",
    )
    replaced_narrator_playback = service.save_narrator_tts_playback(b"narrator-playback-audio-2")
    assert_absolute_file(
        data_dir,
        replaced_narrator_playback,
        b"narrator-playback-audio-2",
        rf"narrator/tts/playback-{UUID_RE}\.wav",
    )
    assert not narrator_playback.exists()

    service.delete_user_persona(persona.id)
    assert not (data_dir / "user_personas" / persona.id).exists()
