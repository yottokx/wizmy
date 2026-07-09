"""旧 `/v2/...` URL の救済リダイレクト。

ブックマークや保存済みジョブの result_url に残った `/v2` 系 URL を
正式ルートへ転送する。`{path:path}` は `/v2` 単独にはマッチしないため
ルート用のページを別に置く。
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import RedirectResponse
from nicegui import ui


@ui.page("/v2")
def v2_root_redirect() -> RedirectResponse:
    return RedirectResponse("/")


@ui.page("/v2/{path:path}")
def v2_path_redirect(path: str, request: Request) -> RedirectResponse:
    query = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(f"/{path}{query}")
