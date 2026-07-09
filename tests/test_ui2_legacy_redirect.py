"""旧 `/v2/...` URL のリダイレクトと旧テーマキー移行のテスト。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.ui2 import theme as theme_mod


async def test_v2_root_redirects_to_home(nicegui_smoke_app) -> None:
    response = await nicegui_smoke_app.user.http_client.get("/v2", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/"


async def test_v2_path_redirects_to_promoted_route(nicegui_smoke_app) -> None:
    response = await nicegui_smoke_app.user.http_client.get(
        "/v2/characters/char-a/chat", follow_redirects=False
    )
    assert response.status_code == 307
    assert response.headers["location"] == "/characters/char-a/chat"


async def test_v2_redirect_preserves_query(nicegui_smoke_app) -> None:
    response = await nicegui_smoke_app.user.http_client.get(
        "/v2/settings?theme=hinata", follow_redirects=False
    )
    assert response.status_code == 307
    assert response.headers["location"] == "/settings?theme=hinata"


async def test_v2_url_open_lands_on_promoted_page(nicegui_smoke_app) -> None:
    """保存済みジョブの result_url 等に残った旧 /v2 URL からページに到達できる。"""
    await nicegui_smoke_app.user.open("/v2")
    await nicegui_smoke_app.user.should_see("最近のセッション")


@pytest.mark.parametrize(
    ("legacy", "expected"),
    [
        ("night-library", "hoshi"),
        ("sage-garden", "hinata"),
        ("lavender-mist", "hinata"),
        ("sand-terracotta", "hinata"),
    ],
)
def test_theme_migrates_from_legacy_key(
    monkeypatch: pytest.MonkeyPatch, legacy: str, expected: str
) -> None:
    store: dict = {"theme": legacy}
    monkeypatch.setattr(theme_mod.app, "storage", SimpleNamespace(user=store))
    assert theme_mod.get_theme() == expected
    assert store[theme_mod.THEME_KEY] == expected


def test_theme_migration_skips_when_ui2_theme_present(monkeypatch: pytest.MonkeyPatch) -> None:
    store: dict = {"theme": "night-library", theme_mod.THEME_KEY: "hinata"}
    monkeypatch.setattr(theme_mod.app, "storage", SimpleNamespace(user=store))
    assert theme_mod.get_theme() == "hinata"
    assert store[theme_mod.THEME_KEY] == "hinata"


def test_theme_defaults_without_legacy_key(monkeypatch: pytest.MonkeyPatch) -> None:
    store: dict = {}
    monkeypatch.setattr(theme_mod.app, "storage", SimpleNamespace(user=store))
    assert theme_mod.get_theme() == theme_mod.DEFAULT_THEME
    assert theme_mod.THEME_KEY not in store
