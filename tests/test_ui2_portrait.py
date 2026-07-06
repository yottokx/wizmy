"""ui2 portrait ヘルパ(メディアURL変換・顔フォーカス)のテスト。"""

from __future__ import annotations

from src.core.character.schemas import CharacterImageAsset, FaceRect
from src.ui2.components.portrait import (
    DEFAULT_OBJECT_POSITION,
    image_object_position,
    media_url,
    rect_object_position,
)


class TestMediaUrl:
    def test_character_image_path(self) -> None:
        assert media_url("characters/abc/images/x.png") == "/media/characters/abc/images/x.png"

    def test_backslash_normalized(self) -> None:
        assert media_url("groups\\g1\\members\\m1\\y.png") == "/media/groups/g1/members/m1/y.png"

    def test_empty_returns_none(self) -> None:
        assert media_url("") is None

    def test_parent_traversal_rejected(self) -> None:
        assert media_url("characters/../config.json") is None

    def test_leading_slash_stripped(self) -> None:
        assert media_url("/characters/abc/images/x.png") == "/media/characters/abc/images/x.png"


class TestRectObjectPosition:
    def test_default_rect_falls_back(self) -> None:
        assert rect_object_position(FaceRect()) == DEFAULT_OBJECT_POSITION

    def test_none_falls_back(self) -> None:
        assert rect_object_position(None) == DEFAULT_OBJECT_POSITION

    def test_zero_size_falls_back(self) -> None:
        assert rect_object_position(FaceRect(x=0.2, y=0.2, width=0.0, height=0.0)) == DEFAULT_OBJECT_POSITION

    def test_center_of_rect(self) -> None:
        rect = FaceRect(x=0.2, y=0.1, width=0.4, height=0.2)
        assert rect_object_position(rect) == "40.0% 20.0%"

    def test_clamped_to_bounds(self) -> None:
        rect = FaceRect(x=0.9, y=0.9, width=0.4, height=0.4)
        assert rect_object_position(rect) == "100.0% 100.0%"


class TestImageObjectPosition:
    def test_face_rect_used_by_default(self) -> None:
        image = CharacterImageAsset(
            path="characters/abc/images/x.png",
            face_rect=FaceRect(x=0.4, y=0.0, width=0.2, height=0.2),
            bust_rect=FaceRect(x=0.0, y=0.0, width=0.5, height=0.5),
        )
        assert image_object_position(image) == "50.0% 10.0%"

    def test_bust_rect_when_requested(self) -> None:
        image = CharacterImageAsset(
            path="characters/abc/images/x.png",
            bust_rect=FaceRect(x=0.0, y=0.0, width=0.5, height=0.5),
        )
        assert image_object_position(image, kind="bust") == "25.0% 25.0%"

    def test_none_image_falls_back(self) -> None:
        assert image_object_position(None) == DEFAULT_OBJECT_POSITION
