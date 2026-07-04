from __future__ import annotations

from nicegui import ui

from ....core.gen_server.schemas import GEN_SERVER_MODE_LABELS
from ....core.tts.options import TTS_PROVIDER_LABELS as TTS_PROVIDER_LABELS


_SORTABLE_FILTER = "button, input, textarea, select, .q-btn, .q-field, .q-checkbox, .q-slider, .q-menu, [role=button]"


def moved_order(ids: list[str], old_index: int, new_index: int) -> list[str] | None:
    if old_index == new_index:
        return None
    if old_index < 0 or old_index >= len(ids) or new_index < 0 or new_index >= len(ids):
        return None
    moved = ids.pop(old_index)
    ids.insert(new_index, moved)
    return ids


def notify_order_saved() -> None:
    ui.notify("並び順を保存しました", type="positive", timeout=1200)


def install_drag_sort_script() -> None:
    ui.add_body_html(f"""
<script>
(() => {{
  if (window.charagenSetupSortable) return;

  const interactiveSelector = {_SORTABLE_FILTER!r};
  const pending = new Set();

  const style = document.createElement('style');
  style.textContent = `
    .charagen-sortable-item {{ cursor: grab; touch-action: none; }}
    .charagen-sortable-item.charagen-dragging {{
      cursor: grabbing;
      box-shadow: 0 18px 36px rgba(0, 0, 0, .22);
      opacity: .96;
      pointer-events: none;
      transform: scale(1.01);
      z-index: 10000;
    }}
    .charagen-sortable-placeholder {{
      min-height: 72px;
      border: 1px dashed var(--cs-accent);
      border-radius: 4px;
      background: var(--cs-accent-bg);
      box-sizing: border-box;
    }}
    body.charagen-sort-active,
    body.charagen-sort-active * {{
      cursor: grabbing !important;
    }}
  `;
  document.head.appendChild(style);

  const isInteractive = target =>
    target instanceof Element && Boolean(target.closest(interactiveSelector));

  const directChildOf = (container, target) => {{
    let node = target;
    while (node && node.parentElement !== container) node = node.parentElement;
    return node && node.parentElement === container ? node : null;
  }};

  const sortableChildren = container =>
    [...container.children].filter(child => !child.classList.contains('charagen-sortable-placeholder'));

  const itemAfter = (container, y) => {{
    const siblings = sortableChildren(container);
    return siblings.reduce((closest, child) => {{
      const box = child.getBoundingClientRect();
      const offset = y - box.top - box.height / 2;
      if (offset < 0 && offset > closest.offset) {{
        return {{ offset, element: child }};
      }}
      return closest;
    }}, {{ offset: Number.NEGATIVE_INFINITY, element: null }}).element;
  }};

  const setup = id => {{
    const container = document.getElementById(id);
    if (!container) {{
      pending.add(id);
      return;
    }}
    pending.delete(id);
    if (container.dataset.charagenSortable === '1') return;
    container.dataset.charagenSortable = '1';

    let dragged = null;
    let placeholder = null;
    let oldIndex = -1;
    let startY = 0;
    let active = false;
    let pointerId = null;
    let offsetX = 0;
    let offsetY = 0;
    let previousUserSelect = '';
    let previousStyle = {{}};

    const refreshItems = () => {{
      [...container.children].forEach(child => {{
        if (child.classList.contains('charagen-sortable-placeholder')) return;
        child.draggable = false;
        child.classList.add('charagen-sortable-item');
      }});
    }};
    refreshItems();
    new MutationObserver(refreshItems).observe(container, {{ childList: true }});

    container.addEventListener('pointerdown', event => {{
      if (isInteractive(event.target)) return;
      const item = directChildOf(container, event.target);
      if (!item) return;
      dragged = item;
      oldIndex = sortableChildren(container).indexOf(item);
      startY = event.clientY;
      active = false;
      pointerId = event.pointerId;
      item.setPointerCapture?.(event.pointerId);
    }}, true);

    const startFloating = event => {{
      const rect = dragged.getBoundingClientRect();
      offsetX = event.clientX - rect.left;
      offsetY = event.clientY - rect.top;
      previousUserSelect = document.body.style.userSelect;
      previousStyle = {{
        position: dragged.style.position,
        left: dragged.style.left,
        top: dragged.style.top,
        width: dragged.style.width,
        margin: dragged.style.margin,
        transition: dragged.style.transition,
      }};

      placeholder = document.createElement('div');
      placeholder.className = 'charagen-sortable-placeholder';
      placeholder.style.height = `${{rect.height}}px`;
      container.insertBefore(placeholder, dragged);

      Object.assign(dragged.style, {{
        position: 'fixed',
        left: `${{rect.left}}px`,
        top: `${{rect.top}}px`,
        width: `${{rect.width}}px`,
        margin: '0',
        transition: 'none',
      }});
      document.body.appendChild(dragged);
      document.body.style.userSelect = 'none';
      document.body.classList.add('charagen-sort-active');
      dragged.classList.add('charagen-dragging');
      active = true;
    }};

    const moveFloating = event => {{
      dragged.style.left = `${{event.clientX - offsetX}}px`;
      dragged.style.top = `${{event.clientY - offsetY}}px`;
      const after = itemAfter(container, event.clientY);
      if (after) container.insertBefore(placeholder, after);
      else container.appendChild(placeholder);
    }};

    window.addEventListener('pointermove', event => {{
      if (!dragged) return;
      if (!active) {{
        if (Math.abs(event.clientY - startY) < 6) return;
        startFloating(event);
      }}
      event.preventDefault();
      moveFloating(event);
    }}, true);

    const finishDrag = () => {{
      if (!dragged) return;
      const newIndex = placeholder ? [...container.children].indexOf(placeholder) : oldIndex;
      try {{ dragged.releasePointerCapture?.(pointerId); }} catch {{}}
      if (placeholder) {{
        container.insertBefore(dragged, placeholder);
        placeholder.remove();
      }}
      dragged.classList.remove('charagen-dragging');
      document.body.classList.remove('charagen-sort-active');
      document.body.style.userSelect = previousUserSelect;
      Object.assign(dragged.style, previousStyle);
      if (active && oldIndex >= 0 && newIndex >= 0 && oldIndex !== newIndex) {{
        container.dispatchEvent(new CustomEvent('charagen-sortable-end', {{
          detail: {{ old_index: oldIndex, new_index: newIndex }},
          bubbles: true,
        }}));
      }}
      dragged = null;
      placeholder = null;
      oldIndex = -1;
      startY = 0;
      active = false;
      pointerId = null;
      offsetX = 0;
      offsetY = 0;
      previousStyle = {{}};
    }};

    window.addEventListener('pointerup', finishDrag, true);
    window.addEventListener('pointercancel', finishDrag, true);
  }};

  new MutationObserver(() => {{
    [...pending].forEach(setup);
  }}).observe(document.body, {{ childList: true, subtree: true }});

  window.charagenSetupSortable = setup;
}})();
</script>
""")


def enable_drag_sort(container, handler) -> None:
    container.on(
        "charagen-sortable-end",
        handler,
        js_handler="event => emit(event.detail)",
    )
    ui.timer(
        0.1,
        lambda c=container: ui.run_javascript(
            f"window.charagenSetupSortable && window.charagenSetupSortable('{c.html_id}')"
        ),
        once=True,
    )


def short_text(text: str, limit: int = 180) -> str:
    normalized = (text or "").strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "..."


def build_profile_param_control(key: str, spec: dict, value: object):
    label = str(spec.get("label", key))
    if spec.get("type") == "boolean":
        return ui.checkbox(label, value=bool(value)).classes("w-full")
    if spec.get("enum"):
        options = list(spec["enum"])
        return (
            ui.select(
                options=options,
                value=value if value in options else spec.get("default"),
                label=label,
            )
            .props("outlined dense")
            .classes("w-full")
        )
    if spec.get("type") in {"integer", "number"}:
        return (
            ui.number(
                label=label,
                value=value,
                min=spec.get("minimum"),
                step=spec.get("step"),
            )
            .props("outlined dense")
            .classes("w-full")
        )
    if spec.get("multiline"):
        return (
            ui.textarea(
                label=label,
                value=value or "",
            )
            .props("outlined rows=3")
            .classes("w-full col-span-2")
        )
    return (
        ui.input(
            label=label,
            value=value or "",
        )
        .props("outlined dense clearable")
        .classes("w-full")
    )


def read_gen_server_default_value(spec: dict, control) -> object:
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


async def fetch_gen_server_model_id_from_endpoint(
    endpoint_id: str,
    mode: str,
    model_input,
    ctx,
) -> None:
    try:
        models = await ctx.api_config.fetch_gen_server_models(endpoint_id, mode)
    except Exception as err:
        ui.notify(f"モデルIDを取得できませんでした: {err}", type="negative")
        return

    if not models:
        ui.notify("この機能で利用できるモデルが見つかりませんでした。", type="warning")
        return

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg"):
        ui.label(f"{GEN_SERVER_MODE_LABELS.get(mode, mode)} のモデルID").classes("text-base font-semibold mb-2")
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
