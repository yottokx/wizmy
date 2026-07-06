"""
/v2 仮ページ(Phase 0: scaffold 検証用)。

ナビ・ロゴ再着色・テーマ切替の永続・ジョブドロワー開閉・sparkle・
メディアURL+顔フォーカスの動作確認を目的とする。Phase 1 でホームに置き換える。
"""

from __future__ import annotations

from nicegui import ui

from ...app_context import get_context
from ..components.portrait import image_object_position, media_url, raw_img
from ..components.sparkle import sparkle_field
from ..scaffold import p3_page

_PAGE_CSS = """
.p0-hero { position: relative; padding: 9vh 6vw 40px; overflow: hidden; }
.p0-hero h1 { margin: 14px 0 6px; font-size: 38px; line-height: 1.3; letter-spacing: .08em; }
.p0-hero .occ { color: var(--muted); font-size: 13.5px; letter-spacing: .1em; margin-bottom: 24px; }
.p0-hero .bubble { max-width: 480px; font-size: 15px; }
.p0-actions { display: flex; gap: 12px; margin-top: 28px; flex-wrap: wrap; }
.p0-cast { padding: 0 6vw 60px; }
.p0-cast .lbl { font-size: 12px; letter-spacing: .28em; color: var(--muted); margin-bottom: 14px; }
.p0-cast .row { display: flex; gap: 16px; align-items: flex-end; flex-wrap: wrap; }
.p0-cast figure { margin: 0; text-align: center; }
.p0-cast img.avatar { width: 72px; height: 72px; }
.p0-cast figcaption { font-size: 12px; color: var(--muted); margin-top: 6px; letter-spacing: .06em; }
"""


@ui.page("/v2")
async def ui2_home_page() -> None:
    with p3_page("ホーム") as scaffold:
        ui.add_css(_PAGE_CSS)

        with ui.element("section").classes("p0-hero"):
            sparkle_field(22)
            ui.html("UI2 — PHASE 0 SCAFFOLD").classes("kicker")
            ui.html("ここから、新しい Wizmy が始まります。").classes("serif").style(
                "font-size:38px; line-height:1.3; letter-spacing:.08em; display:block; margin:14px 0 6px;"
            )
            ui.html("この画面は scaffold 検証用の仮ページです。Phase 1 でホームに置き換わります。").classes("occ")
            with ui.element("div").classes("bubble tail-left"):
                ui.html(
                    "ナビ・ロゴの再着色・テーマ切替(保存されます)・"
                    "AIジョブドロワー・星のまたたきが、ここで確認できます。"
                )
            with ui.element("div").classes("p0-actions"):
                open_btn = ui.element("button").classes("btn primary").mark("ui2-open-jobs")
                with open_btn:
                    ui.html("ジョブドロワーを開く")
                open_btn.on("click", scaffold.open_jobs)
                legacy_btn = ui.element("button").classes("btn")
                with legacy_btn:
                    ui.html("従来のUIへ")
                legacy_btn.on("click", lambda: ui.navigate.to("/characters"))

        # メディアURL変換+顔フォーカス(face_rect → object-position)の実配線確認
        with ui.element("section").classes("p0-cast"):
            ui.html("MEDIA / PORTRAIT CHECK").classes("lbl")
            with ui.element("div").classes("row"):
                sheets = await get_context().characters.list_all()
                shown = 0
                for sheet in sheets:
                    image = sheet.media.primary_image()
                    if image is None:
                        continue
                    url = media_url(image.path)
                    if url is None:
                        continue
                    with ui.element("figure"):
                        img = raw_img(url, "avatar")
                        img.style(f"object-position: {image_object_position(image)};")
                        with ui.element("figcaption"):
                            ui.html(sheet.name)
                    shown += 1
                    if shown >= 4:
                        break
                if shown == 0:
                    ui.html("画像付きキャラクターがまだいません。").classes("note")
