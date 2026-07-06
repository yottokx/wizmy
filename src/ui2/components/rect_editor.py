"""
顔範囲/バストショット範囲の編集ダイアログ(P3スキン)。

旧 `ui/components/character_media_image.py` の rect ダイアログと同じ
`ui.interactive_image` + マウスドラッグ方式を ui2 用に再実装する
(依存規則により旧UIからは import しない)。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from nicegui import ui
from nicegui.events import MouseEventArguments

from ...core.character.schemas import CharacterImageAsset, FaceRect
from ...core.media import read_image_size

RECT_KINDS: dict[str, dict[str, str]] = {
    "face": {
        "title": "顔範囲を設定",
        "tooltip": "ドラッグで顔範囲を指定",
        "too_small": "顔範囲が小さすぎます",
        "saved": "顔範囲を保存しました",
        "color": "#ffb46b",
    },
    "bust": {
        "title": "バストショット範囲を設定",
        "tooltip": "ドラッグでバストショット範囲を指定",
        "too_small": "バストショット範囲が小さすぎます",
        "saved": "バストショット範囲を保存しました",
        "color": "#93a0ff",
    },
}


def _image_size(image: CharacterImageAsset, image_path: Path | None) -> tuple[int, int] | None:
    if image.width > 0 and image.height > 0:
        return image.width, image.height
    if image_path is not None:
        return read_image_size(image_path)
    return None


def _frame_style(size: tuple[int, int] | None) -> str:
    max_height = "calc(100vh - 220px)"
    base = f"margin-left: auto; margin-right: auto; max-height: {max_height};"
    if size is None:
        return f"{base} aspect-ratio: 1 / 1; width: min(100%, {max_height});"
    width, height = size
    return f"{base} aspect-ratio: {width} / {height}; width: min(100%, calc({max_height} * {width} / {height}));"


def _rect_from_points(start: tuple[float, float], end: tuple[float, float], width: int, height: int) -> FaceRect:
    left = min(start[0], end[0])
    top = min(start[1], end[1])
    right = max(start[0], end[0])
    bottom = max(start[1], end[1])
    return FaceRect(
        x=left / width,
        y=top / height,
        width=(right - left) / width,
        height=(bottom - top) / height,
    )


def _rect_overlay(rect: FaceRect, width: int, height: int, color: str) -> str:
    if width <= 0 or height <= 0:
        return ""
    x = rect.x * width
    y = rect.y * height
    w = rect.width * width
    h = rect.height * height
    if w <= 0 or h <= 0:
        return ""
    stroke = max(2.0, min(width, height) * 0.006)
    handle = stroke * 2.5
    return f"""
        <rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}"
              fill="{color}" fill-opacity="0.15" stroke="{color}"
              stroke-width="{stroke:.2f}" vector-effect="non-scaling-stroke" />
        <circle cx="{x:.2f}" cy="{y:.2f}" r="{handle:.2f}" fill="{color}" />
        <circle cx="{x + w:.2f}" cy="{y:.2f}" r="{handle:.2f}" fill="{color}" />
        <circle cx="{x:.2f}" cy="{y + h:.2f}" r="{handle:.2f}" fill="{color}" />
        <circle cx="{x + w:.2f}" cy="{y + h:.2f}" r="{handle:.2f}" fill="{color}" />
    """


def open_rect_dialog(
    *,
    image: CharacterImageAsset,
    image_path: Path,
    kind: str,
    on_save: Callable[[FaceRect, int, int], Awaitable[None]],
) -> None:
    """rect 編集ダイアログを開く。on_save(rect, width, height) が保存を担う。"""
    spec = RECT_KINDS[kind]
    color = spec["color"]
    rect = image.bust_rect if kind == "bust" else image.face_rect
    size = _image_size(image, image_path)
    state: dict[str, Any] = {
        "width": size[0] if size else image.width,
        "height": size[1] if size else image.height,
        "start": None,
        "dragging": False,
        "draft": rect.model_copy(),
    }

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-3xl").style(
        "background: var(--panel); color: var(--text);"
    ):
        with ui.row().classes("items-center justify-between w-full mb-2"):
            ui.label(spec["title"]).classes("text-base font-semibold")
            close_btn = ui.element("button").classes("btn quiet")
            with close_btn:
                ui.html("×")
            close_btn.on("click", dlg.close)

        editor = (
            ui.interactive_image(
                image_path,
                content=_rect_overlay(state["draft"], state["width"], state["height"], color),
                size=size,
                events=["mousedown", "mousemove", "mouseup", "mouseleave"],
                sanitize=False,
            )
            .classes("rounded-md overflow-hidden cursor-crosshair")
            .style(_frame_style(size))
        )
        editor.tooltip(spec["tooltip"])

        def _on_loaded(e) -> None:
            args = e.args or {}
            state["width"] = int(args.get("width") or image.width or 0)
            state["height"] = int(args.get("height") or image.height or 0)
            if state["width"] > 0 and state["height"] > 0:
                editor.style(_frame_style((state["width"], state["height"])))
            editor.set_content(_rect_overlay(state["draft"], state["width"], state["height"], color))

        async def _on_mouse(e: MouseEventArguments) -> None:
            width = int(state["width"] or 0)
            height = int(state["height"] or 0)
            if width <= 0 or height <= 0:
                return
            x = min(max(float(e.image_x), 0.0), float(width))
            y = min(max(float(e.image_y), 0.0), float(height))

            if e.type == "mousedown" and e.button == 0:
                state["start"] = (x, y)
                state["dragging"] = True
                state["draft"] = _rect_from_points((x, y), (x, y), width, height)
            elif e.type == "mousemove" and state["dragging"]:
                if state["start"] is None:
                    return
                state["draft"] = _rect_from_points(state["start"], (x, y), width, height)
            elif e.type == "mouseup" and state["dragging"]:
                state["dragging"] = False
                start = state["start"]
                state["start"] = None
                if start is None:
                    return
                state["draft"] = _rect_from_points(start, (x, y), width, height)
            elif e.type == "mouseleave" and state["dragging"]:
                state["dragging"] = False
                state["start"] = None
            else:
                return
            editor.set_content(_rect_overlay(state["draft"], width, height, color))

        async def _save() -> None:
            width = int(state["width"] or 0)
            height = int(state["height"] or 0)
            draft: FaceRect = state["draft"]
            if width <= 0 or height <= 0:
                ui.notify("画像サイズを取得できませんでした", type="warning")
                return
            if draft.width < 0.02 or draft.height < 0.02:
                ui.notify(spec["too_small"], type="warning")
                return
            await on_save(draft, width, height)
            ui.notify(spec["saved"], type="positive")
            dlg.close()

        def _reset() -> None:
            state["draft"] = FaceRect()
            editor.set_content(_rect_overlay(state["draft"], state["width"], state["height"], color))

        editor.on("loaded", _on_loaded)
        editor.on_mouse(_on_mouse)

        with ui.row().classes("justify-end gap-2 mt-3 w-full"):
            for label, action, primary in (
                ("リセット", _reset, False),
                ("キャンセル", dlg.close, False),
                ("保存", _save, True),
            ):
                btn = ui.element("button").classes("btn primary" if primary else "btn quiet")
                with btn:
                    ui.html(label)
                btn.on("click", action)

    dlg.open()
