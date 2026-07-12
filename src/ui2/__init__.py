"""
新UI「P3: With」の並行実装パッケージ。

- 正式ルート(`/`・`/characters` 等)を提供する。
- 旧 `/v2/...` URL は正式ルートへリダイレクトされる(pages/legacy_redirect.py)。
- 依存規則: ui2 → services / core / storage のみ。
"""

from __future__ import annotations

from nicegui import app

from ..config import AppSettings

_MEDIA_ROOTS = ("characters", "groups", "user_personas", "narrator")


def register_ui2(settings: AppSettings) -> None:
    """P3 ページ群とメディア配信URLを登録する(main.py から1回だけ呼ぶ)。

    data ルート全体は公開しない(characters.db / config.json を含むため)。
    """
    for name in _MEDIA_ROOTS:
        directory = settings.data_dir / name
        directory.mkdir(parents=True, exist_ok=True)
        app.add_media_files(f"/media/{name}", directory)

    from . import pages  # noqa: F401  (@ui.page デコレータの登録)
