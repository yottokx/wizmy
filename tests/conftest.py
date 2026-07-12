"""NiceGUI ページスモークテスト用の共通フィクスチャ。"""

from __future__ import annotations

import importlib
import os
import sys
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from nicegui import core, ui
from nicegui.functions.download import download
from nicegui.functions.navigate import Navigate
from nicegui.functions.notify import notify
from nicegui.testing import User
from nicegui.testing.general import nicegui_reset_globals

from src.app_context import AppContext, init_context
from src.config import AppSettings


@dataclass(frozen=True)
class NiceGuiSmokeApp:
    """スモークテストで共有するアプリ状態。"""

    user: User
    context: AppContext
    data_dir: Path


def _reload_page_modules() -> None:
    """NiceGUI の page デコレータをテストごとに登録し直す。"""
    for module_name in list(sys.modules):
        if module_name == "src.ui2.pages" or module_name.startswith("src.ui2.pages."):
            sys.modules.pop(module_name, None)
    importlib.import_module("src.ui2.pages")


@pytest.fixture
async def nicegui_smoke_app(tmp_path: Path) -> AsyncGenerator[NiceGuiSmokeApp, None]:
    """一時ディレクトリを使う AppContext と NiceGUI User を初期化する。"""
    data_dir = tmp_path / "data"
    settings = AppSettings(
        data_dir=data_dir,
        host="127.0.0.1",
        port=0,
        reload=False,
        storage_secret="nicegui-smoke-test-secret",
    )

    with nicegui_reset_globals():
        os.environ["NICEGUI_USER_SIMULATION"] = "true"
        context = init_context(settings)
        await context.startup()
        try:
            _reload_page_modules()
            ui.run(
                host=settings.host,
                port=settings.port,
                title=settings.app_name,
                favicon="✨",
                storage_secret=settings.storage_secret,
                reload=settings.reload,
                dark=None,
            )
            async with core.app.router.lifespan_context(core.app):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(core.app),
                    base_url="http://test",
                ) as client:
                    yield NiceGuiSmokeApp(
                        user=User(client),
                        context=context,
                        data_dir=data_dir,
                    )
        finally:
            await context.shutdown()
            os.environ.pop("NICEGUI_USER_SIMULATION", None)
            ui.navigate = Navigate()
            ui.notify = notify
            ui.download = download
