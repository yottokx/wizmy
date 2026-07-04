"""
メディア保存の共通処理。

キャラクター、ユーザーペルソナ、グループメンバー、ナレーターで共通する
画像・音声ファイルの保存と矩形更新を扱う。
"""

from __future__ import annotations

import inspect
import mimetypes
import shutil
import uuid
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, Literal, TypeVar, cast

from ..core.character.schemas import (
    CharacterImageAsset,
    CharacterMedia,
    CharacterVoiceAsset,
    FaceRect,
)

ResultT = TypeVar("ResultT")
SaveMediaOwner = Callable[[], ResultT | Awaitable[ResultT]]
SaveVoiceAssetOwner = Callable[[CharacterVoiceAsset], ResultT | Awaitable[ResultT]]
DeleteMediaFile = Callable[[str], None]
RectAttribute = Literal["face_rect", "bust_rect"]


@dataclass(slots=True)
class MediaOwner(Generic[ResultT]):
    """メディアを持つ対象と、保存・削除時に必要な差分を表す。"""

    relative_root: Path
    media: CharacterMedia
    save: SaveMediaOwner[ResultT]
    save_failed: Callable[[ResultT], bool] | None = None
    delete_new_file: DeleteMediaFile | None = None
    delete_old_file: DeleteMediaFile | None = None


@dataclass(slots=True)
class VoiceAssetOwner(Generic[ResultT]):
    """単一の音声アセットを持つ対象の差分を表す。"""

    relative_root: Path
    current_path: str
    save: SaveVoiceAssetOwner[ResultT]
    delete_new_file: DeleteMediaFile | None = None
    delete_old_file: DeleteMediaFile | None = None


class MediaFileService:
    IMAGE_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
    VOICE_SUFFIXES = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav", ".webm"}

    def __init__(self, data_dir: Path | None = None) -> None:
        self._data_dir = data_dir or Path("data")

    def media_path(self, relative_path: str) -> Path | None:
        if not relative_path:
            return None
        path = (self._data_dir / relative_path).resolve()
        data_root = self._data_dir.resolve()
        if not path.is_relative_to(data_root) or not path.is_file():
            return None
        return path

    async def save_image_upload(self, owner: MediaOwner[ResultT], upload: Any) -> ResultT:
        filename = getattr(upload, "name", "") or ""
        content_type = getattr(upload, "content_type", "") or ""
        self.validate_upload(
            filename,
            content_type,
            content_type_prefix="image/",
            allowed_suffixes=self.IMAGE_SUFFIXES,
            error_message="画像ファイルを選択してください。",
        )

        asset_id = uuid.uuid4().hex
        suffix = self.safe_suffix(filename, content_type, self.IMAGE_SUFFIXES, ".png")
        relative_path = owner.relative_root / "images" / f"{asset_id}{suffix}"
        target = self._data_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        await upload.save(target)

        image = CharacterImageAsset(
            id=asset_id,
            path=relative_path.as_posix(),
            original_name=filename,
            content_type=content_type,
        )
        return await self._replace_primary_image(owner, image)

    async def save_image_bytes(
        self,
        owner: MediaOwner[ResultT],
        image_bytes: bytes,
        *,
        filename: str,
        content_type: str,
        width: int = 0,
        height: int = 0,
    ) -> ResultT:
        self.validate_image_bytes(image_bytes, content_type)

        asset_id = uuid.uuid4().hex
        suffix = self.safe_suffix(filename, content_type, self.IMAGE_SUFFIXES, ".png")
        relative_path = owner.relative_root / "images" / f"{asset_id}{suffix}"
        target = self._data_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(image_bytes)

        image = CharacterImageAsset(
            id=asset_id,
            path=relative_path.as_posix(),
            original_name=filename,
            content_type=content_type,
            width=max(0, int(width or 0)),
            height=max(0, int(height or 0)),
        )
        return await self._replace_primary_image(owner, image)

    async def save_voice_upload(self, owner: MediaOwner[ResultT], upload: Any) -> ResultT:
        filename = getattr(upload, "name", "") or ""
        content_type = getattr(upload, "content_type", "") or ""
        self.validate_upload(
            filename,
            content_type,
            content_type_prefix="audio/",
            allowed_suffixes=self.VOICE_SUFFIXES,
            error_message="音声ファイルを選択してください。",
        )

        asset_id = uuid.uuid4().hex
        suffix = self.safe_suffix(filename, content_type, self.VOICE_SUFFIXES, ".wav")
        relative_path = owner.relative_root / "voices" / f"{asset_id}{suffix}"
        target = self._data_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        await upload.save(target)

        voice = CharacterVoiceAsset(
            id=asset_id,
            path=relative_path.as_posix(),
            original_name=filename,
            content_type=content_type,
        )
        return await self._replace_primary_voice(owner, voice)

    async def save_voice_bytes(
        self,
        owner: MediaOwner[ResultT],
        audio_bytes: bytes,
        *,
        filename: str,
        content_type: str,
    ) -> ResultT:
        self.validate_non_empty(audio_bytes, "音声データが空です。")

        asset_id = uuid.uuid4().hex
        suffix = self.safe_suffix(filename, content_type, self.VOICE_SUFFIXES, ".wav")
        relative_path = owner.relative_root / "voices" / f"{asset_id}{suffix}"
        target = self._data_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(audio_bytes)

        voice = CharacterVoiceAsset(
            id=asset_id,
            path=relative_path.as_posix(),
            original_name=filename,
            content_type=content_type,
        )
        return await self._replace_primary_voice(owner, voice)

    async def save_voice_asset_bytes(
        self,
        owner: VoiceAssetOwner[ResultT],
        audio_bytes: bytes,
        *,
        filename: str,
        content_type: str,
    ) -> CharacterVoiceAsset:
        self.validate_non_empty(audio_bytes, "音声データが空です。")

        asset_id = uuid.uuid4().hex
        suffix = self.safe_suffix(filename, content_type, self.VOICE_SUFFIXES, ".wav")
        relative_path = owner.relative_root / "voices" / f"{asset_id}{suffix}"
        target = self._data_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(audio_bytes)

        voice = CharacterVoiceAsset(
            id=asset_id,
            path=relative_path.as_posix(),
            original_name=filename,
            content_type=content_type,
        )
        try:
            await self._save_voice_asset_owner(owner, voice)
        except Exception:
            self._delete_voice_new_file(owner, voice.path)
            raise
        if owner.current_path:
            self._delete_voice_old_file(owner, owner.current_path)
        return voice

    def save_image_preview(
        self,
        relative_root: Path,
        image_bytes: bytes,
        *,
        filename: str = "generated-image.png",
        content_type: str = "image/png",
        replace_existing: bool = True,
        ignore_delete_errors: bool = False,
        delete_only_files: bool = False,
    ) -> Path:
        self.validate_non_empty(image_bytes, "画像データが空です。")
        suffix = self.safe_suffix(filename, content_type, self.IMAGE_SUFFIXES, ".png")
        return self.save_temp_file(
            relative_root,
            image_bytes,
            directory="images/previews",
            prefix="preview",
            suffix=suffix,
            replace_existing=replace_existing,
            ignore_delete_errors=ignore_delete_errors,
            delete_only_files=delete_only_files,
        )

    def save_tts_preview(
        self,
        relative_root: Path,
        audio_bytes: bytes,
        *,
        replace_existing: bool = True,
        empty_error_message: str = "保存するデータが空です。",
        ignore_delete_errors: bool = False,
        delete_only_files: bool = False,
        replace_glob: str | None = None,
    ) -> Path:
        return self.save_temp_file(
            relative_root,
            audio_bytes,
            directory="tts",
            prefix="preview",
            suffix=".wav",
            replace_existing=replace_existing,
            empty_error_message=empty_error_message,
            ignore_delete_errors=ignore_delete_errors,
            delete_only_files=delete_only_files,
            replace_glob=replace_glob,
        )

    def save_tts_playback(
        self,
        relative_root: Path,
        audio_bytes: bytes,
        *,
        empty_error_message: str = "保存するデータが空です。",
        ignore_delete_errors: bool = False,
        delete_only_files: bool = False,
        replace_glob: str | None = None,
    ) -> Path:
        return self.save_temp_file(
            relative_root,
            audio_bytes,
            directory="tts",
            prefix="playback",
            suffix=".wav",
            replace_existing=True,
            empty_error_message=empty_error_message,
            ignore_delete_errors=ignore_delete_errors,
            delete_only_files=delete_only_files,
            replace_glob=replace_glob,
        )

    def save_temp_file(
        self,
        relative_root: Path,
        data: bytes,
        *,
        directory: str,
        prefix: str,
        suffix: str,
        replace_existing: bool,
        empty_error_message: str = "保存するデータが空です。",
        ignore_delete_errors: bool = False,
        delete_only_files: bool = False,
        replace_glob: str | None = None,
    ) -> Path:
        self.validate_non_empty(data, empty_error_message)

        owner_root = (self._data_dir / relative_root).resolve()
        target_dir = (owner_root / directory).resolve()
        if not target_dir.is_relative_to(owner_root):
            raise ValueError("保存先が不正です。")

        target_dir.mkdir(parents=True, exist_ok=True)
        if replace_existing:
            for old_file in target_dir.glob(replace_glob or f"{prefix}-*"):
                if delete_only_files and not old_file.is_file():
                    continue
                self.delete_file(old_file, ignore_errors=ignore_delete_errors)

        target = target_dir / f"{prefix}-{uuid.uuid4().hex}{suffix}"
        target.write_bytes(data)
        return target

    async def update_primary_image_rect(
        self,
        owner: MediaOwner[ResultT],
        rect: FaceRect,
        *,
        rect_attribute: RectAttribute,
        missing_image_message: str,
        image_width: int = 0,
        image_height: int = 0,
        clamp: Callable[[FaceRect], FaceRect] | None = None,
    ) -> ResultT:
        self._apply_primary_image_rect(
            owner.media,
            rect,
            rect_attribute=rect_attribute,
            missing_image_message=missing_image_message,
            image_width=image_width,
            image_height=image_height,
            clamp=clamp,
        )
        return await self._save_owner(owner)

    def update_primary_image_rect_sync(
        self,
        owner: MediaOwner[ResultT],
        rect: FaceRect,
        *,
        rect_attribute: RectAttribute,
        missing_image_message: str,
        image_width: int = 0,
        image_height: int = 0,
        clamp: Callable[[FaceRect], FaceRect] | None = None,
    ) -> ResultT:
        self._apply_primary_image_rect(
            owner.media,
            rect,
            rect_attribute=rect_attribute,
            missing_image_message=missing_image_message,
            image_width=image_width,
            image_height=image_height,
            clamp=clamp,
        )
        return self._save_owner_sync(owner)

    def delete_owner_files(self, relative_root: Path) -> None:
        parts = relative_root.parts
        root = (self._data_dir / parts[0]).resolve() if parts else self._data_dir.resolve()
        target = (self._data_dir / relative_root).resolve()
        if target.is_relative_to(root):
            shutil.rmtree(target, ignore_errors=True)

    def delete_media_file(
        self,
        relative_path: str,
        *,
        relative_root: Path | None = None,
        ignore_errors: bool = False,
    ) -> None:
        path = self.media_path(relative_path)
        if path is None:
            return
        if relative_root is not None:
            root = (self._data_dir / relative_root).resolve()
            if not path.resolve().is_relative_to(root):
                return
        self.delete_file(path, ignore_errors=ignore_errors)

    @staticmethod
    def delete_file(path: Path, *, ignore_errors: bool = False) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            if not ignore_errors:
                raise

    @staticmethod
    def validate_upload(
        filename: str,
        content_type: str,
        *,
        content_type_prefix: str,
        allowed_suffixes: Collection[str],
        error_message: str,
    ) -> None:
        if content_type and not content_type.startswith(content_type_prefix):
            raise ValueError(error_message)
        if not content_type and Path(filename).suffix.lower() not in allowed_suffixes:
            raise ValueError(error_message)

    @classmethod
    def validate_image_bytes(cls, image_bytes: bytes, content_type: str) -> None:
        cls.validate_non_empty(image_bytes, "画像データが空です。")
        if content_type and not content_type.startswith("image/"):
            raise ValueError("画像データを指定してください。")

    @staticmethod
    def validate_non_empty(data: bytes, error_message: str) -> None:
        if not data:
            raise ValueError(error_message)

    @staticmethod
    def safe_suffix(
        filename: str,
        content_type: str,
        allowed: Collection[str],
        fallback: str,
    ) -> str:
        suffix = Path(filename or "").suffix.lower()
        if suffix in allowed:
            return suffix
        guessed = (mimetypes.guess_extension(content_type) or "").lower()
        if guessed == ".jpe":
            guessed = ".jpg"
        if guessed in allowed:
            return guessed
        return fallback

    @staticmethod
    def clamp_rect(rect: FaceRect) -> FaceRect:
        width = min(max(rect.width, 0.01), 1.0)
        height = min(max(rect.height, 0.01), 1.0)
        x = min(max(rect.x, 0.0), 1.0 - width)
        y = min(max(rect.y, 0.0), 1.0 - height)
        return FaceRect(x=x, y=y, width=width, height=height)

    @staticmethod
    def clamp_rect_from_origin(rect: FaceRect) -> FaceRect:
        x = min(max(float(rect.x), 0.0), 1.0)
        y = min(max(float(rect.y), 0.0), 1.0)
        width = min(max(float(rect.width), 0.0), 1.0 - x)
        height = min(max(float(rect.height), 0.0), 1.0 - y)
        return FaceRect(x=x, y=y, width=width, height=height)

    def _apply_primary_image_rect(
        self,
        media: CharacterMedia,
        rect: FaceRect,
        *,
        rect_attribute: RectAttribute,
        missing_image_message: str,
        image_width: int,
        image_height: int,
        clamp: Callable[[FaceRect], FaceRect] | None,
    ) -> None:
        image = media.primary_image()
        if image is None:
            raise ValueError(missing_image_message)

        setattr(image, rect_attribute, (clamp or self.clamp_rect)(rect))
        if image_width > 0:
            image.width = image_width
        if image_height > 0:
            image.height = image_height
        media.primary_image_id = image.id

    async def _replace_primary_image(
        self,
        owner: MediaOwner[ResultT],
        image: CharacterImageAsset,
    ) -> ResultT:
        old_paths = [current.path for current in owner.media.images]
        owner.media.images = [image]
        owner.media.primary_image_id = image.id
        try:
            saved = await self._save_owner(owner)
        except Exception:
            self._delete_new_file(owner, image.path)
            raise
        if self._save_failed(owner, saved):
            self._delete_new_file(owner, image.path)
            return saved
        for old_path in old_paths:
            self._delete_old_file(owner, old_path)
        return saved

    async def _replace_primary_voice(
        self,
        owner: MediaOwner[ResultT],
        voice: CharacterVoiceAsset,
    ) -> ResultT:
        old_paths = [current.path for current in owner.media.voices]
        owner.media.voices = [voice]
        owner.media.primary_voice_id = voice.id
        try:
            saved = await self._save_owner(owner)
        except Exception:
            self._delete_new_file(owner, voice.path)
            raise
        if self._save_failed(owner, saved):
            self._delete_new_file(owner, voice.path)
            return saved
        for old_path in old_paths:
            self._delete_old_file(owner, old_path)
        return saved

    async def _save_owner(self, owner: MediaOwner[ResultT]) -> ResultT:
        result = owner.save()
        if inspect.isawaitable(result):
            return await cast(Awaitable[ResultT], result)
        return cast(ResultT, result)

    def _save_owner_sync(self, owner: MediaOwner[ResultT]) -> ResultT:
        result = owner.save()
        if inspect.isawaitable(result):
            raise TypeError("同期保存では awaitable を返せません。")
        return cast(ResultT, result)

    async def _save_voice_asset_owner(
        self,
        owner: VoiceAssetOwner[ResultT],
        voice: CharacterVoiceAsset,
    ) -> None:
        result = owner.save(voice)
        if inspect.isawaitable(result):
            await cast(Awaitable[ResultT], result)

    def _delete_new_file(self, owner: MediaOwner[ResultT], relative_path: str) -> None:
        delete_file = owner.delete_new_file or self.delete_media_file
        delete_file(relative_path)

    def _delete_old_file(self, owner: MediaOwner[ResultT], relative_path: str) -> None:
        delete_file = owner.delete_old_file or self.delete_media_file
        delete_file(relative_path)

    def _delete_voice_new_file(
        self,
        owner: VoiceAssetOwner[ResultT],
        relative_path: str,
    ) -> None:
        delete_file = owner.delete_new_file or self.delete_media_file
        delete_file(relative_path)

    def _delete_voice_old_file(
        self,
        owner: VoiceAssetOwner[ResultT],
        relative_path: str,
    ) -> None:
        delete_file = owner.delete_old_file or self.delete_media_file
        delete_file(relative_path)

    @staticmethod
    def _save_failed(owner: MediaOwner[ResultT], result: ResultT) -> bool:
        return owner.save_failed(result) if owner.save_failed is not None else False
