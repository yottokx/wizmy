"""キャラクターメディア画像 UI。"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

from nicegui import ui
from nicegui.events import MouseEventArguments

from ...core.character.schemas import CharacterImageAsset, FaceRect
from ...core.gen_server.schemas import GEN_SERVER_MODE_SDXL_IMAGE
from ...core.image_generation.schemas import (
    IMAGE_GENERATION_PARAMETER_FIELDS,
    ImageGenerationProfile,
    image_generation_profile_values,
)
from ...services.ai_jobs import AIJobStatus
from ...services.danbooru_prompt import DanbooruPromptServiceError
from ...services.image_generation import ImageGenerationError
from ..state import get_vault_password


_GENERATED_PROMPT_RE = re.compile(
    r"<(?:span|strong)\b(?=[^>]*(?:data-wizmy-generated-prompt|wizmy-generated-prompt))[^>]*>"
    r".*?</(?:span|strong)>\s*",
    re.IGNORECASE | re.DOTALL,
)

_GENERATED_NEGATIVE_PROMPT_RE = re.compile(
    r"<(?:span|strong)\b(?=[^>]*(?:data-wizmy-generated-negative-prompt|wizmy-generated-negative-prompt))[^>]*>"
    r".*?</(?:span|strong)>\s*",
    re.IGNORECASE | re.DOTALL,
)


def _open_image_generation_dialog(
    sheet,
    ctx,
    character_id: str,
    refresh_fn,
    actions,
) -> None:
    profiles = ctx.api_config.get_image_generation_profiles()
    if not profiles:
        ui.notify("設定で画像生成プロファイルを追加してください。", type="warning")
        return

    config = ctx.api_config.get_image_generation_config()
    selected_profile = ctx.api_config.get_image_generation_profile(config.default_profile_id) or profiles[0]
    llm_profiles = ctx.api_config.get_llm_profiles()
    app_llm_config = ctx.api_config.get_app_llm_config()
    selected_llm_profile = ctx.api_config.get_llm_profile(app_llm_config.generation_profile_id) or (
        llm_profiles[0] if llm_profiles else None
    )
    fields = {
        "model_id": {"label": "モデルID", "type": "string", "default": ""},
        **IMAGE_GENERATION_PARAMETER_FIELDS,
    }
    controls: dict[str, object] = {}
    generated: list[dict[str, object]] = []
    prompt_candidates: list[object] = []

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-6xl").style("width: min(1100px, 96vw);"):
        with ui.row().classes("w-full items-center justify-between gap-2"):
            ui.label("画像生成").classes("text-base font-semibold")
            ui.space()
            status = ui.label("").classes("text-xs text-grey-6")
            ui.button(icon="close", on_click=dlg.close).props("flat round dense")

        with ui.row().classes("w-full gap-4 items-start flex-col xl:flex-row"):
            with ui.column().classes("w-full xl:w-[440px] gap-3 shrink-0"):
                profile_options = {profile.id: profile.name or "無題のプロファイル" for profile in profiles}
                with ui.row().classes("w-full items-end gap-2"):
                    profile_select = (
                        ui.select(
                            options=profile_options,
                            value=selected_profile.id,
                            label="画像生成プロファイル",
                        )
                        .props("outlined dense")
                        .classes("flex-1 min-w-0")
                    )
                    generate_btn = ui.button("生成", icon="auto_awesome").props("color=primary unelevated")

                llm_profile_options = {
                    profile.id: f"{profile.name} / {profile.model_id or 'モデル未設定'}" for profile in llm_profiles
                }
                with ui.row().classes("w-full items-end gap-2"):
                    llm_profile_select = (
                        ui.select(
                            options=llm_profile_options,
                            value=selected_llm_profile.id if selected_llm_profile else None,
                            label="LLMプロファイル",
                        )
                        .props("outlined dense")
                        .classes("flex-1 min-w-0")
                    )
                    prompt_generate_btn = ui.button(
                        "プロンプト生成",
                        icon="auto_awesome",
                    ).props("color=secondary unelevated")
                    prompt_spinner = ui.spinner(size="sm").classes("hidden")
                prompt_candidate_container = ui.row().classes("w-full gap-2 hidden")
                prompt_status = ui.label("").classes("text-xs text-grey-6")

                ui.label("プロンプト").classes("text-xs text-grey-7")
                prompt_input = ui.editor(
                    value=_prompt_text_to_editor_html(selected_profile.prompt),
                    placeholder="画像生成プロンプト",
                ).classes("w-full cs-image-prompt-editor")
                controls["prompt"] = prompt_input

                ui.label("ネガティブプロンプト").classes("text-xs text-grey-7")
                negative_input = ui.editor(
                    value=_prompt_text_to_editor_html(selected_profile.negative_prompt),
                    placeholder="除外したい要素",
                ).classes("w-full cs-image-prompt-editor cs-image-negative-prompt-editor")
                controls["negative_prompt"] = negative_input

                with ui.expansion("詳細パラメータ", icon="tune").props("dense").classes("w-full"):
                    with ui.grid(columns=2).classes("w-full gap-3"):
                        initial_values = image_generation_profile_values(selected_profile)
                        for key, spec in fields.items():
                            value = initial_values.get(key, spec.get("default"))
                            label = str(spec.get("label", key))
                            if key == "model_id":
                                with ui.row().classes("w-full col-span-2 items-end gap-2"):
                                    model_input = (
                                        ui.input(
                                            label=label,
                                            value=value or "",
                                        )
                                        .props("outlined dense clearable")
                                        .classes("flex-1")
                                    )
                                    ui.button(
                                        icon="refresh",
                                        on_click=lambda: _fetch_character_image_model_id(
                                            profile_select.value or "",
                                            model_input,
                                            ctx,
                                        ),
                                    ).props("flat round").tooltip("モデルIDを取得")
                                controls[key] = model_input
                            elif spec.get("type") == "boolean":
                                controls[key] = ui.checkbox(label, value=bool(value)).classes("w-full")
                            elif spec.get("enum"):
                                options = list(spec["enum"])
                                controls[key] = (
                                    ui.select(
                                        options=options,
                                        value=value if value in options else spec.get("default"),
                                        label=label,
                                    )
                                    .props("outlined dense")
                                    .classes("w-full")
                                )
                            elif spec.get("type") in {"integer", "number"}:
                                controls[key] = (
                                    ui.number(
                                        label=label,
                                        value=value,
                                        min=spec.get("minimum"),
                                        step=spec.get("step"),
                                    )
                                    .props("outlined dense")
                                    .classes("w-full")
                                )
                            elif spec.get("multiline"):
                                controls[key] = (
                                    ui.textarea(
                                        label=label,
                                        value=value or "",
                                    )
                                    .props("outlined rows=3")
                                    .classes("w-full col-span-2")
                                )
                            else:
                                controls[key] = (
                                    ui.input(
                                        label=label,
                                        value=value or "",
                                    )
                                    .props("outlined dense clearable")
                                    .classes("w-full")
                                )

                def _apply_profile(profile: ImageGenerationProfile) -> None:
                    values = image_generation_profile_values(profile)
                    prompt_input.set_value(_prompt_text_to_editor_html(str(values.get("prompt") or "")))
                    negative_input.set_value(_prompt_text_to_editor_html(str(values.get("negative_prompt") or "")))
                    for key, spec in fields.items():
                        if key in controls:
                            controls[key].set_value(values.get(key, spec.get("default")))

                def _on_profile_change() -> None:
                    profile = ctx.api_config.get_image_generation_profile(profile_select.value or "")
                    if profile is not None:
                        _apply_profile(profile)

                profile_select.on_value_change(lambda _: _on_profile_change())

            with ui.column().classes("w-full xl:flex-1 min-w-0 gap-2"):
                with ui.row().classes("w-full items-center gap-2"):
                    ui.label("生成候補").classes("text-sm font-semibold")
                    ui.space()
                    candidate_count = ui.label("0件").classes("text-xs text-grey-6")
                candidate_tabs = (
                    ui.tabs()
                    .props("dense no-caps active-color=primary indicator-color=primary align=left")
                    .classes("w-full hidden")
                )
                preview_container = ui.column().classes("w-full")

        def _read_params() -> dict[str, object]:
            params: dict[str, object] = {}
            for key, spec in {
                "prompt": {"type": "string", "default": ""},
                "negative_prompt": {"type": "string", "default": ""},
                **fields,
            }.items():
                if key not in controls:
                    continue
                if key in {"prompt", "negative_prompt"}:
                    params[key] = _editor_html_to_prompt(str(getattr(controls[key], "value", "") or ""))
                else:
                    params[key] = _read_gen_server_param_value(spec, controls[key])
            return params

        def _render_prompt_candidate_buttons() -> None:
            prompt_candidate_container.clear()
            if not prompt_candidates:
                prompt_candidate_container.classes("hidden")
                return
            prompt_candidate_container.classes(remove="hidden")
            with prompt_candidate_container:
                for index, candidate in enumerate(prompt_candidates, start=1):
                    label = getattr(candidate, "label", "") or f"候補 {index}"
                    button = (
                        ui.button(
                            label,
                            on_click=lambda candidate=candidate: _apply_prompt_candidate(candidate),
                        )
                        .props("outline color=secondary no-caps")
                        .classes("min-w-[110px]")
                    )
                    button.tooltip(getattr(candidate, "prompt", ""))

        def _apply_prompt_candidate(candidate: object) -> None:
            prompt = str(getattr(candidate, "prompt", "") or "").strip()
            if not prompt:
                return
            prompt_input.set_value(_replace_generated_prompt_html(str(prompt_input.value or ""), prompt))
            negative_prompt = ", ".join(_candidate_negative_tags(candidate))
            negative_input.set_value(
                _replace_generated_negative_prompt_html(str(negative_input.value or ""), negative_prompt)
            )

        async def _generate_prompt_candidates() -> None:
            llm_profile_id = str(llm_profile_select.value or "")
            if not llm_profile_id:
                ui.notify("LLMプロファイルを選択してください。", type="warning")
                return

            prompt_generate_btn.disable()
            prompt_spinner.classes(remove="hidden")
            prompt_status.set_text("プロンプト生成中...")
            prompt_candidates.clear()
            _render_prompt_candidate_buttons()
            try:
                job = ctx.danbooru_prompt.start_generate_candidates_job(
                    sheet,
                    llm_profile_id=llm_profile_id,
                    vault_password=get_vault_password(),
                    count=3,
                    label=f"{sheet.name or 'キャラクター'}のプロンプト候補生成",
                    scope=f"{actions.scope_prefix}:prompt",
                    metadata=dict(actions.metadata),
                )
                ctx.ai_jobs.set_result_meta(job.id, {"result_url": actions.result_url})
                finished = await ctx.ai_jobs.wait(job.id)
                if finished.status == AIJobStatus.CANCELLED:
                    prompt_status.set_text("")
                    ui.notify("プロンプト生成を停止しました", type="info")
                    return
                if finished.status != AIJobStatus.SUCCEEDED:
                    raise DanbooruPromptServiceError(finished.error_message or "プロンプト生成に失敗しました。")
                candidates = finished.result or []
                prompt_candidates.extend(candidates)
                _render_prompt_candidate_buttons()
                prompt_status.set_text("")
                ui.notify("プロンプト候補を生成しました", type="positive")
            except DanbooruPromptServiceError as err:
                prompt_status.set_text("")
                ui.notify(str(err), type="negative", timeout=10000)
            except Exception as err:
                prompt_status.set_text("")
                ui.notify(f"プロンプト生成に失敗しました: {err}", type="negative", timeout=10000)
            finally:
                prompt_spinner.classes("hidden")
                prompt_generate_btn.enable()

        def _render_generated() -> None:
            candidate_tabs.clear()
            preview_container.clear()
            candidate_count.set_text(f"{len(generated)}件")
            with preview_container:
                if not generated:
                    candidate_tabs.classes("hidden")
                    with (
                        ui.element("div")
                        .classes("w-full rounded-md border border-dashed flex items-center justify-center")
                        .style("min-height: 360px; background: var(--cs-surface-soft); border-color: var(--cs-border);")
                    ):
                        ui.label("生成するとここに画像が表示されます").classes("text-sm text-grey-6")
                    return

            candidate_tabs.classes(remove="hidden")
            selected_tab = f"candidate-{len(generated)}"
            with candidate_tabs:
                for index, item in enumerate(generated, start=1):
                    image = item["image"]
                    size_label = _generated_image_size_label(image)
                    label = f"候補 {index}"
                    if size_label:
                        label = f"{label} / {size_label}"
                    ui.tab(f"candidate-{index}", label=label)
            candidate_tabs.set_value(selected_tab)

            with preview_container:
                with (
                    ui.tab_panels(candidate_tabs, value=selected_tab, animated=False)
                    .classes("w-full")
                    .style("background: transparent;")
                ):
                    for index, item in enumerate(generated, start=1):
                        with ui.tab_panel(f"candidate-{index}").classes("p-0"):
                            _render_generated_image_panel(item, index)

        def _render_generated_image_panel(item: dict[str, object], index: int) -> None:
            image = item["image"]
            image_path = item["path"]
            size_label = _generated_image_size_label(image)
            with (
                ui.element("div")
                .classes("w-full rounded-md border p-2")
                .style("background: var(--cs-surface); border-color: var(--cs-border);")
            ):
                with ui.row().classes("w-full items-center gap-2"):
                    label = f"候補 {index}"
                    if size_label:
                        label = f"{label} / {size_label}"
                    ui.label(label).classes("text-sm font-semibold")
                    ui.space()
                    ui.button(
                        "この画像を保存",
                        icon="save",
                        on_click=lambda image=image, index=index: _save_image(image, index),
                    ).props("outline color=primary")
                ui.image(image_path).props("fit=contain").classes("w-full rounded-md").style(
                    "height: min(72vh, 760px); min-height: 360px; background: var(--cs-surface-soft);"
                )

        async def _generate() -> None:
            generate_btn.disable()
            status.set_text("生成中...")
            try:

                def _save_previews(images: list[object], job) -> dict[str, object]:
                    if actions.save_image_preview is None:
                        raise RuntimeError("画像プレビューの保存処理が設定されていません。")
                    items: list[dict[str, object]] = []
                    for image in images:
                        preview_path = actions.save_image_preview(
                            image.data,
                            filename=image.filename,
                            content_type=image.content_type,
                            replace_existing=False,
                        )
                        items.append(
                            {
                                "image": image,
                                "path": preview_path,
                            }
                        )
                    generated.extend(items)
                    return {
                        "result_url": actions.result_url,
                        "preview_paths": [str(item["path"]) for item in items],
                        "image_count": len(items),
                    }

                job = ctx.image_generation.start_sdxl_job(
                    profile_id=profile_select.value or "",
                    gen_server_params=_read_params(),
                    label=f"{sheet.name or 'キャラクター'}の画像生成",
                    scope=f"{actions.scope_prefix}:image",
                    metadata=dict(actions.metadata),
                    result_handler=_save_previews,
                )
                finished = await ctx.ai_jobs.wait(job.id)
                if finished.status == AIJobStatus.CANCELLED:
                    status.set_text("")
                    ui.notify("画像生成を停止しました", type="info")
                    return
                if finished.status != AIJobStatus.SUCCEEDED:
                    raise ImageGenerationError(finished.error_message or "画像生成に失敗しました。")
                _render_generated()
                status.set_text("")
                ui.notify("画像を生成しました", type="positive")
            except ImageGenerationError as err:
                status.set_text("")
                ui.notify(f"画像生成に失敗しました: {err}", type="negative", timeout=10000)
            except Exception as err:
                status.set_text("")
                ui.notify(f"画像生成に失敗しました: {err}", type="negative", timeout=10000)
            finally:
                generate_btn.enable()

        async def _save_image(image: object, index: int) -> None:
            if not image:
                ui.notify("先に画像を生成してください。", type="warning")
                return
            try:
                if actions.save_image_bytes is None:
                    raise RuntimeError("画像の保存処理が設定されていません。")
                saved = await actions.save_image_bytes(
                    image.data,
                    filename=_generated_image_filename(image, index),
                    content_type=image.content_type,
                    width=image.width,
                    height=image.height,
                )
                sheet.media = saved.media
                ui.notify("生成画像をキャラ画像に保存しました", type="positive")
                dlg.close()
                refresh_fn()
            except Exception as err:
                ui.notify(f"画像の保存に失敗しました: {err}", type="negative")

        prompt_generate_btn.on("click", _generate_prompt_candidates)
        generate_btn.on("click", _generate)
        _render_generated()

    dlg.open()


def _read_gen_server_param_value(spec: dict, control) -> object:
    value = control.value
    if spec.get("nullable") and (value is None or value == ""):
        return None

    default = spec.get("default")
    field_type = spec.get("type")
    if field_type == "boolean":
        return bool(value)
    if field_type == "integer":
        if value is None or value == "":
            return default
        return int(value)
    if field_type == "number":
        if value is None or value == "":
            return default
        return float(value)
    if field_type == "string":
        if spec.get("nullable") and not str(value or "").strip():
            return None
        return value or ""
    return value


def _prompt_text_to_editor_html(value: str) -> str:
    lines = str(value or "").splitlines()
    if not lines:
        return ""
    return "<br>".join(html.escape(line) for line in lines)


def _replace_generated_prompt_html(current_html: str, generated_prompt: str) -> str:
    return _replace_generated_editor_html(
        current_html,
        generated_prompt,
        marker="data-wizmy-generated-prompt",
        css_class="wizmy-generated-prompt",
        pattern=_GENERATED_PROMPT_RE,
    )


def _replace_generated_negative_prompt_html(current_html: str, generated_prompt: str) -> str:
    return _replace_generated_editor_html(
        current_html,
        generated_prompt,
        marker="data-wizmy-generated-negative-prompt",
        css_class="wizmy-generated-negative-prompt",
        pattern=_GENERATED_NEGATIVE_PROMPT_RE,
    )


def _replace_generated_editor_html(
    current_html: str,
    generated_prompt: str,
    *,
    marker: str,
    css_class: str,
    pattern: re.Pattern[str],
) -> str:
    body = pattern.sub("", str(current_html or ""), count=1).lstrip()
    has_existing_prompt = bool(_editor_html_to_prompt(body))
    generated_text = generated_prompt.strip()
    if not generated_text:
        return body
    if has_existing_prompt:
        generated_text = f"{generated_text}, "
    generated_html = f'<span {marker}="1" class="{css_class}">{_prompt_text_to_editor_html(generated_text)}</span>'
    return f"{generated_html}{body}"


def _remove_generated_prompt_html(value: str) -> str:
    return _GENERATED_PROMPT_RE.sub("", str(value or ""), count=1)


def _editor_html_to_prompt(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(?:p|div|li|h[1-6])>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return " ".join(lines).strip()


def _candidate_negative_tags(candidate: object) -> list[str]:
    tags: list[str] = []
    negative_prompt = str(getattr(candidate, "negative_prompt", "") or "")
    tags.extend(part.strip() for part in negative_prompt.split(",") if part.strip())
    negative_tags = getattr(candidate, "negative_tags", []) or []
    if isinstance(negative_tags, list):
        tags.extend(_editor_prompt_tag(str(tag).strip()) for tag in negative_tags if str(tag).strip())
    return _dedupe_prompt_parts(tags)


def _dedupe_prompt_parts(parts: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for part in parts:
        cleaned = part.strip()
        key = _prompt_part_key(cleaned)
        if not cleaned or key in seen:
            continue
        result.append(cleaned)
        seen.add(key)
    return result


def _prompt_part_key(value: str) -> str:
    return re.sub(r"\s+", "_", value.strip().lower())


def _editor_prompt_tag(value: str) -> str:
    if value in {"o_o", "x_x", "u_u"}:
        return value
    return value.replace("_", " ")


async def _fetch_character_image_model_id(profile_id: str, model_input, ctx) -> None:
    profile = ctx.api_config.get_image_generation_profile(profile_id)
    if profile is None:
        ui.notify("画像生成プロファイルを選択してください。", type="warning")
        return
    if not profile.endpoint_id:
        ui.notify("画像生成プロファイルのAPI接続先を設定してください。", type="warning")
        return
    try:
        models = await ctx.api_config.fetch_gen_server_models(
            profile.endpoint_id,
            GEN_SERVER_MODE_SDXL_IMAGE,
        )
    except Exception as err:
        ui.notify(f"モデルIDを取得できませんでした: {err}", type="negative")
        return

    if not models:
        ui.notify("SDXL画像生成で利用できるモデルが見つかりませんでした。", type="warning")
        return

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg"):
        ui.label("SDXL画像生成のモデルID").classes("text-base font-semibold mb-2")
        with ui.scroll_area().style("max-height: 50vh; width: 100%"):
            with ui.list().props("dense separator").classes("w-full"):
                for model in models:
                    model_id = str(model.get("id") or "")
                    display_name = str(model.get("display_name") or model_id)

                    def _select(model_id: str = model_id) -> None:
                        model_input.set_value(model_id)
                        dlg.close()

                    with ui.item(on_click=_select).classes("cursor-pointer"):
                        with ui.item_section():
                            ui.label(display_name).classes("text-sm font-medium")
                            ui.label(model_id).classes("text-xs text-grey-6 font-mono break-all")

    dlg.open()


def _generated_image_size_label(image: object) -> str:
    width = int(getattr(image, "width", 0) or 0)
    height = int(getattr(image, "height", 0) or 0)
    if width > 0 and height > 0:
        return f"{width}x{height}"
    return ""


def _generated_image_filename(image: object, index: int) -> str:
    suffix = Path(str(getattr(image, "filename", ""))).suffix or ".png"
    return f"generated-image-{index}{suffix}"


def _image_size(image: CharacterImageAsset, image_path: Path | None = None) -> tuple[int, int] | None:
    if image.width > 0 and image.height > 0:
        return image.width, image.height
    if image_path is not None:
        return _read_image_size(image_path)
    return None


def _image_frame_style(size: tuple[int, int] | None) -> str:
    max_height = "calc(100vh - 220px)"
    base = f"margin-left: auto; margin-right: auto; max-height: {max_height};"
    if size is None:
        return f"{base} aspect-ratio: 1 / 1; width: min(100%, {max_height});"
    width, height = size
    return f"{base} aspect-ratio: {width} / {height}; width: min(100%, calc({max_height} * {width} / {height}));"


def _read_image_size(path: Path) -> tuple[int, int] | None:
    try:
        with path.open("rb") as f:
            head = f.read(32)
            if head.startswith(b"\x89PNG\r\n\x1a\n") and len(head) >= 24:
                return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
            if head[:6] in (b"GIF87a", b"GIF89a") and len(head) >= 10:
                return int.from_bytes(head[6:8], "little"), int.from_bytes(head[8:10], "little")
            if head.startswith(b"\xff\xd8"):
                f.seek(2)
                return _read_jpeg_size(f)
    except OSError:
        return None
    return None


def _read_jpeg_size(f) -> tuple[int, int] | None:
    while True:
        marker_start = f.read(1)
        if not marker_start:
            return None
        if marker_start != b"\xff":
            continue
        marker = f.read(1)
        while marker == b"\xff":
            marker = f.read(1)
        if not marker or marker in (b"\xd8", b"\xd9"):
            continue
        length_bytes = f.read(2)
        if len(length_bytes) != 2:
            return None
        length = int.from_bytes(length_bytes, "big")
        if marker[0] in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            data = f.read(5)
            if len(data) != 5:
                return None
            return int.from_bytes(data[3:5], "big"), int.from_bytes(data[1:3], "big")
        f.seek(max(length - 2, 0), 1)


def _render_image_editor(
    sheet,
    ctx,
    character_id: str,
    image: CharacterImageAsset,
    image_path,
    refresh_fn,
    actions,
) -> None:
    size = _image_size(image, image_path)
    ui.interactive_image(
        image_path,
        size=size,
        events=[],
        sanitize=False,
    ).classes("rounded-md overflow-hidden border bg-grey-2").style(_image_frame_style(size))

    with ui.row().classes("gap-2 mt-2 flex-wrap"):
        ui.button(
            "顔範囲を設定",
            icon="crop_free",
            on_click=lambda: _open_face_rect_dialog(
                sheet,
                ctx,
                character_id,
                image,
                image_path,
                refresh_fn,
                actions,
            ),
        ).props("flat color=primary")
        ui.button(
            "バストショット範囲を設定",
            icon="crop_portrait",
            on_click=lambda: _open_bust_rect_dialog(
                sheet,
                ctx,
                character_id,
                image,
                image_path,
                refresh_fn,
                actions,
            ),
        ).props("flat color=secondary")


def _open_face_rect_dialog(
    sheet,
    ctx,
    character_id: str,
    image: CharacterImageAsset,
    image_path,
    refresh_fn,
    actions,
) -> None:
    _open_image_rect_dialog(
        sheet,
        ctx,
        character_id,
        image,
        image_path,
        refresh_fn,
        rect_kind="face",
        rect=image.face_rect,
        title="顔範囲を設定",
        tooltip="ドラッグで顔範囲を指定",
        too_small_message="顔範囲が小さすぎます",
        saved_message="顔範囲を保存しました",
        color="#6E9572",
        actions=actions,
    )


def _open_bust_rect_dialog(
    sheet,
    ctx,
    character_id: str,
    image: CharacterImageAsset,
    image_path,
    refresh_fn,
    actions,
) -> None:
    _open_image_rect_dialog(
        sheet,
        ctx,
        character_id,
        image,
        image_path,
        refresh_fn,
        rect_kind="bust",
        rect=image.bust_rect,
        title="バストショット範囲を設定",
        tooltip="ドラッグでバストショット範囲を指定",
        too_small_message="バストショット範囲が小さすぎます",
        saved_message="バストショット範囲を保存しました",
        color="#3A7CA5",
        actions=actions,
    )


def _open_image_rect_dialog(
    sheet,
    ctx,
    character_id: str,
    image: CharacterImageAsset,
    image_path,
    refresh_fn,
    *,
    rect_kind: str,
    rect: FaceRect,
    title: str,
    tooltip: str,
    too_small_message: str,
    saved_message: str,
    color: str,
    actions,
) -> None:
    size = _image_size(image, image_path)
    state: dict[str, Any] = {
        "width": size[0] if size else image.width,
        "height": size[1] if size else image.height,
        "start": None,
        "dragging": False,
        "draft": rect.model_copy(),
    }

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-3xl"):
        with ui.row().classes("items-center justify-between w-full mb-2"):
            ui.label(title).classes("text-base font-semibold")
            ui.button(icon="close", on_click=dlg.close).props("flat round dense")

        editor = (
            ui.interactive_image(
                image_path,
                content=_rect_overlay(state["draft"], state["width"], state["height"], color),
                size=size,
                events=["mousedown", "mousemove", "mouseup", "mouseleave"],
                sanitize=False,
            )
            .classes("rounded-md overflow-hidden border bg-grey-2 cursor-crosshair")
            .style(_image_frame_style(size))
        )
        editor.tooltip(tooltip)

        def _on_loaded(e) -> None:
            args = e.args or {}
            state["width"] = int(args.get("width") or image.width or 0)
            state["height"] = int(args.get("height") or image.height or 0)
            if state["width"] > 0 and state["height"] > 0:
                image.width = state["width"]
                image.height = state["height"]
                editor.style(_image_frame_style((state["width"], state["height"])))
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
                editor.set_content(_rect_overlay(state["draft"], width, height, color))
                return

            if e.type == "mousemove" and state["dragging"]:
                start = state["start"]
                if start is None:
                    return
                state["draft"] = _rect_from_points(start, (x, y), width, height)
                editor.set_content(_rect_overlay(state["draft"], width, height, color))
                return

            if e.type == "mouseup" and state["dragging"]:
                state["dragging"] = False
                start = state["start"]
                state["start"] = None
                if start is None:
                    return
                state["draft"] = _rect_from_points(start, (x, y), width, height)
                editor.set_content(_rect_overlay(state["draft"], width, height, color))
                return

            if e.type == "mouseleave" and state["dragging"]:
                state["dragging"] = False
                state["start"] = None
                editor.set_content(_rect_overlay(state["draft"], width, height, color))

        async def _save() -> None:
            width = int(state["width"] or 0)
            height = int(state["height"] or 0)
            rect = state["draft"]
            if width <= 0 or height <= 0:
                ui.notify("画像サイズを取得できませんでした", type="warning")
                return
            if rect.width < 0.02 or rect.height < 0.02:
                ui.notify(too_small_message, type="warning")
                return
            if rect_kind == "face":
                if actions.update_face_rect is None:
                    raise RuntimeError("顔範囲の保存処理が設定されていません。")
                saved = await actions.update_face_rect(
                    rect,
                    image_width=width,
                    image_height=height,
                )
            elif rect_kind == "bust":
                if actions.update_bust_rect is None:
                    raise RuntimeError("バストショット範囲の保存処理が設定されていません。")
                saved = await actions.update_bust_rect(
                    rect,
                    image_width=width,
                    image_height=height,
                )
            else:
                ui.notify("未対応の範囲種別です", type="negative")
                return
            sheet.media = saved.media
            ui.notify(saved_message, type="positive")
            dlg.close()
            refresh_fn()

        def _reset() -> None:
            state["draft"] = FaceRect()
            editor.set_content(_rect_overlay(state["draft"], state["width"], state["height"], color))

        editor.on("loaded", _on_loaded)
        editor.on_mouse(_on_mouse)

        with ui.row().classes("justify-end gap-2 mt-3"):
            ui.button("リセット", icon="restart_alt", on_click=_reset).props("flat")
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("保存", icon="save", on_click=_save).props("color=primary unelevated")

    dlg.open()


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
