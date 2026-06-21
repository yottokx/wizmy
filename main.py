"""
Wizmy エントリーポイント。

Usage:
    python main.py
    python main.py --port 8080 --host 0.0.0.0
"""

from __future__ import annotations

import argparse

from nicegui import app, ui

from src.app_context import init_context
from src.config import AppSettings, get_settings
from src.ui.pages import (
    character_chat_page,
    character_detail_page,
    characters_page,
    generation_page,
    group_chat_detail_page,
    group_chat_mock_demo_page,
    group_chat_mock_page,
    group_chat_page,
    settings_page,
)
from src.ui.server_noise import (
    install_asyncio_disconnect_handler,
    install_disconnect_noise_filters,
)


def create_app(settings: AppSettings | None = None) -> None:
    if settings is None:
        settings = get_settings()

    install_disconnect_noise_filters()
    ctx = init_context(settings)

    app.on_startup(ctx.startup)
    app.on_startup(install_asyncio_disconnect_handler)
    app.on_shutdown(ctx.shutdown)

    ui.run(
        host=settings.host,
        port=settings.port,
        title=settings.app_name,
        favicon="✨",
        storage_secret=settings.storage_secret,
        reload=settings.reload,
        dark=None,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Wizmy")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    if args.host:
        settings.host = args.host
    if args.port:
        settings.port = args.port
    if args.reload:
        settings.reload = True

    create_app(settings)
