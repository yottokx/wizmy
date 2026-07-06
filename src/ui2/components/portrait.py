"""
立ち絵・カード画像・顔アイコンのヘルパ。

- `ui.image` は q-img ラッパーを生成し position:absolute 系CSSが効かないため、
  素の `<img>` を使う(PoC で確立したパターン)。
- メディアURLは `register_ui2` が登録する `/media/...` 規約URLに変換する。
- 顔フォーカスは `CharacterImageAsset.face_rect / bust_rect`(0-1比率)の
  矩形中心を CSS `object-position` に変換する(立ち絵・カード用)。
- 丸アイコン(アバター)は `face_crop_style` で **face_rect にズーム**した
  background スタイルを使う(旧UI `chat/media.py::cropped_background_style` の
  計算を ui2 に複製。`<img>` の object-fit ではズームできないため div+background)。
"""

from __future__ import annotations

from pathlib import Path

from nicegui import ui

from ...core.character.schemas import CharacterImageAsset, FaceRect
from ...core.media import read_image_size

DEFAULT_OBJECT_POSITION = "center 10%"


def media_url(relative_path: str) -> str | None:
    """data ディレクトリ相対パス(例 characters/{id}/images/x.png)を配信URLへ。"""
    if not relative_path:
        return None
    normalized = relative_path.replace("\\", "/").lstrip("/")
    if ".." in normalized.split("/"):
        return None
    return f"/media/{normalized}"


def raw_img(src: str, classes: str = "") -> ui.element:
    """q-img ラッパー無しの素の `<img>` を生成する。"""
    img = ui.element("img").props(f'src="{src}"')
    if classes:
        img.classes(classes)
    return img


def rect_object_position(rect: FaceRect | None) -> str:
    """face/bust 矩形の中心を `object-position` 値に変換する。

    矩形が未設定(全面 0,0,1,1)・不正の場合は既定値 `center 10%`。
    """
    if rect is None or rect.width <= 0 or rect.height <= 0:
        return DEFAULT_OBJECT_POSITION
    if rect.x == 0.0 and rect.y == 0.0 and rect.width >= 1.0 and rect.height >= 1.0:
        return DEFAULT_OBJECT_POSITION
    center_x = min(max((rect.x + rect.width / 2) * 100, 0.0), 100.0)
    center_y = min(max((rect.y + rect.height / 2) * 100, 0.0), 100.0)
    return f"{center_x:.1f}% {center_y:.1f}%"


def image_object_position(image: CharacterImageAsset | None, kind: str = "face") -> str:
    """画像アセットの face/bust 矩形から `object-position` 値を得る。"""
    if image is None:
        return DEFAULT_OBJECT_POSITION
    rect = image.bust_rect if kind == "bust" else image.face_rect
    return rect_object_position(rect)


def portrait_img(
    image: CharacterImageAsset | None,
    classes: str = "",
    kind: str = "face",
) -> ui.element | None:
    """画像アセットから顔フォーカス済みの素の `<img>` を生成する(URL不明なら None)。"""
    if image is None:
        return None
    url = media_url(image.path)
    if url is None:
        return None
    img = raw_img(url, classes)
    img.style(f"object-position: {image_object_position(image, kind)};")
    return img


# ---------------------------------------------------------------------------
# 顔アイコン(face_rect ズーム。旧 cropped_background_style の ui2 版)
# ---------------------------------------------------------------------------


def _background_position(center: float, rendered_size: float) -> float:
    if rendered_size <= 1.0001:
        return 50.0
    position = (0.5 - center * rendered_size) / (1.0 - rendered_size) * 100
    return min(max(position, 0.0), 100.0)


def _image_dimensions(image: CharacterImageAsset, image_path: Path | None) -> tuple[int, int]:
    if image.width > 0 and image.height > 0:
        return image.width, image.height
    if image_path is not None:
        size = read_image_size(image_path)
        if size is not None:
            return size
    return 1, 1


def rect_crop_style(
    image: CharacterImageAsset | None,
    image_path: Path | None = None,
    *,
    kind: str = "face",
    frame_aspect: float = 1.0,
) -> str:
    """face/bust 矩形にズームした background 系スタイルを返す。

    kind="face" は丸アイコン、kind="bust" は presence 等のバストショット用。
    rect 未設定(全面)の場合は cover+`center 10%` に落とす。
    URL が引けない場合は空文字(呼び出し側でプレースホルダへ)。
    frame_aspect は表示枠の縦横比(height/width)。可変枠は近似値でよい
    (縦位置の寄せ方が少し変わるだけで、クランプされるため破綻しない)。
    """
    if image is None:
        return ""
    url = media_url(image.path)
    if url is None:
        return ""
    base = (
        f'background-image: url("{url}"); '
        "background-repeat: no-repeat; background-color: var(--panel-2);"
    )
    rect = image.bust_rect if kind == "bust" else image.face_rect
    if (
        rect is None
        or rect.width <= 0
        or rect.height <= 0
        or (rect.x == 0.0 and rect.y == 0.0 and rect.width >= 1.0 and rect.height >= 1.0)
    ):
        return base + f" background-size: cover; background-position: {DEFAULT_OBJECT_POSITION};"
    width, height = _image_dimensions(image, image_path)
    image_aspect = width / height if width > 0 and height > 0 else 1.0
    scale = max(
        1.0 / max(rect.width, 0.01),
        image_aspect / max(rect.height * frame_aspect, 0.01),
    )
    scale = min(max(scale * 1.04, 1.0), 8.0)
    rendered_width = scale
    rendered_height = scale * frame_aspect / max(image_aspect, 0.01)
    position_x = _background_position(rect.x + rect.width / 2, rendered_width)
    position_y = _background_position(rect.y + rect.height / 2, rendered_height)
    return (
        base
        + f" background-size: {scale * 100:.1f}% auto;"
        + f" background-position: {position_x:.1f}% {position_y:.1f}%;"
    )


def face_crop_style(
    image: CharacterImageAsset | None,
    image_path: Path | None = None,
    *,
    frame_aspect: float = 1.0,
) -> str:
    """face_rect にズームした background 系スタイル(丸アイコン用)を返す。"""
    return rect_crop_style(image, image_path, kind="face", frame_aspect=frame_aspect)


def face_avatar(
    image: CharacterImageAsset | None,
    classes: str = "avatar",
    *,
    image_path: Path | None = None,
) -> ui.element | None:
    """顔ズーム済みの丸アイコン(div)を生成する(画像が無ければ None)。

    サイズ・角丸・枠線は `.avatar` 系クラス側の CSS に委ねる。
    """
    style = face_crop_style(image, image_path)
    if not style:
        return None
    return ui.element("div").classes(classes).style(style)
