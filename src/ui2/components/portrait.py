"""
立ち絵・カード画像のヘルパ。

- `ui.image` は q-img ラッパーを生成し position:absolute 系CSSが効かないため、
  素の `<img>` を使う(PoC で確立したパターン)。
- メディアURLは `register_ui2` が登録する `/media/...` 規約URLに変換する。
- 顔フォーカスは `CharacterImageAsset.face_rect / bust_rect`(0-1比率)の
  矩形中心を CSS `object-position` に変換する。
"""

from __future__ import annotations

from nicegui import ui

from ...core.character.schemas import CharacterImageAsset, FaceRect

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
