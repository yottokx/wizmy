"""presence(いま話している住人)の立ち絵クロスフェード+名前スロット。

モック group.html の `.presence .portrait img.on`(opacity 遷移)を Python 側の
focus 切替で駆動する。1:1(単独立ち絵)では不要だったため Phase 4 で新設
(HANDOFF 申し送り: 1:1/グループ共用想定のコンポーネント)。

表示は 1:1 チャットの立ち絵と同じ(cover+bust 矩形基準の position。
ユーザー確定 2026-07-07、バストズーム案から差し戻し)。div+background で描く。
CSS(.portrait / .pname / .pocc / .pt.on の opacity 遷移)はページ側で定義する。
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path

from nicegui import ui

from ...core.character.schemas import CharacterImageAsset
from .portrait import image_object_position, media_url


@dataclass(frozen=True)
class PresenceEntry:
    key: str
    label: str
    sub: str
    image: CharacterImageAsset | None
    image_path: Path | None = None


class PresenceStage:
    """立ち絵の重ね置き+クロスフェード。`render()` 後に `focus(key)` で切替。"""

    def __init__(self) -> None:
        self._images: dict[str, ui.element] = {}
        self._entries: dict[str, PresenceEntry] = {}
        self._name: ui.element | None = None
        self._sub: ui.element | None = None
        self.focused_key = ""

    def render(self, entries: list[PresenceEntry]) -> None:
        """現在のコンテナ(.portrait 相当)に全立ち絵と名前スロットを積む。"""
        self._images.clear()
        self._entries = {entry.key: entry for entry in entries}
        for entry in entries:
            url = media_url(entry.image.path) if entry.image is not None else None
            if url is None:
                continue
            # 1:1 チャットの img(object-fit: cover + bust 基準 object-position)と同じ見え方
            style = (
                f'background-image: url("{url}"); background-repeat: no-repeat;'
                " background-size: cover;"
                f" background-position: {image_object_position(entry.image, 'bust')};"
            )
            self._images[entry.key] = ui.element("div").classes("pt").style(style)
        self._name = ui.element("div").classes("pname serif")
        self._sub = ui.element("div").classes("pocc")

    def focus(self, key: str) -> None:
        entry = self._entries.get(key)
        if entry is None:
            return
        self.focused_key = key
        for entry_key, img in self._images.items():
            if entry_key == key:
                img.classes("on")
            else:
                img.classes(remove="on")
        if self._name is not None:
            self._name.clear()
            with self._name:
                ui.html(html.escape(entry.label))
        if self._sub is not None:
            self._sub.clear()
            with self._sub:
                ui.html(html.escape(entry.sub))
