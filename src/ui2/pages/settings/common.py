"""
/settings の共通部品。

- ドラッグ並べ替えスクリプト
- P3 スキンの行・カード・ダイアログヘルパ。
"""

from __future__ import annotations

import html

from nicegui import ui

from ...media_ui import chip_button, p3_button

DIALOG_CARD_STYLE = "background: var(--panel); color: var(--text);"

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
      border: 1px dashed var(--accent);
      border-radius: 6px;
      background: color-mix(in srgb, var(--accent) 10%, transparent);
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


# ---------------------------------------------------------------------------
# P3 スキンの部品
# ---------------------------------------------------------------------------


# 横画面の設定ページ用: 登録中は settings_dialog がモーダルではなくこのコンテナへ描画する
_inline_hosts: list = []


class _InlineSettingsPanel:
    """settings_dialog の戻り値互換(inline 描画時は open/close とも何もしない)。"""

    def open(self) -> None:
        pass

    def close(self) -> None:
        pass


def push_inline_settings_host(container) -> None:
    """以降の settings_dialog を container へ inline 描画させる(pop まで)。"""
    _inline_hosts.append(container)


def pop_inline_settings_host() -> None:
    _inline_hosts.pop()


def settings_dialog(title: str, *, max_width: str = "900px"):
    """設定管理用のダイアログ(P3スキン)。`with settings_dialog(...) as (dlg, body):` で使う。

    横画面の設定ページ(inline ホスト登録中)ではモーダルを作らず右ペインへ描画する。
    """
    if _inline_hosts:
        host = _inline_hosts[-1]
        host.clear()
        with host:
            ui.label(title).classes("serif set-inline-title")
            body = ui.column().classes("w-full gap-3")
        return _InlineSettingsPanel(), body
    dlg = ui.dialog()
    with dlg:
        with ui.card().classes("w-full").style(
            f"{DIALOG_CARD_STYLE} width: min({max_width}, 96vw); max-width: min({max_width}, 96vw);"
        ):
            with ui.row().classes("w-full items-center justify-between gap-2 mb-2"):
                ui.label(title).classes("text-base font-semibold")
                p3_button("閉じる", dlg.close, classes="btn quiet")
            body = ui.column().classes("w-full gap-3").style("max-height: 72vh; overflow-y: auto;")
    return dlg, body


def entry_card(*, sortable: bool = True) -> ui.element:
    """一覧1件分のカード(ドラッグ並べ替え対象)。"""
    card = ui.element("div").style(
        "width: 100%; background: var(--bg-2); border: 1px solid var(--line);"
        " border-radius: 6px; padding: 14px 18px;"
        + (" cursor: grab;" if sortable else "")
    )
    return card


def badge(text: str, *, tone: str = "muted") -> ui.element:
    colors = {
        "muted": "color: var(--muted); border-color: var(--line-2);",
        "accent": "color: var(--accent); border-color: var(--accent);",
        "peri": "color: var(--peri); border-color: var(--peri);",
        "ok": "color: #7fbf8e; border-color: #7fbf8e;",
        "ng": "color: #e08a8a; border-color: #e08a8a;",
    }
    el = ui.element("span").classes("set-badge").style(
        "display: inline-flex; align-items: center; font-size: 11px; letter-spacing: .05em;"
        " padding: 1px 10px; border-radius: 4px; border: 1px solid; white-space: nowrap;"
        + colors.get(tone, colors["muted"])
    )
    with el:
        ui.html(html.escape(text))
    return el


def confirm_dialog(message: str, detail: str, on_confirm, *, confirm_label: str = "削除") -> None:
    with ui.dialog() as dlg, ui.card().style(DIALOG_CARD_STYLE):
        ui.label(message).classes("text-base font-medium mb-2")
        if detail:
            ui.label(detail).classes("note")

        async def _do() -> None:
            await on_confirm()
            dlg.close()

        with ui.row().classes("justify-end gap-2 mt-4 w-full"):
            p3_button("キャンセル", dlg.close, classes="btn quiet")
            p3_button(confirm_label, _do, classes="btn primary").mark("ui2-settings-confirm")
    dlg.open()


__all__ = [
    "DIALOG_CARD_STYLE",
    "badge",
    "chip_button",
    "confirm_dialog",
    "enable_drag_sort",
    "entry_card",
    "install_drag_sort_script",
    "moved_order",
    "notify_order_saved",
    "p3_button",
    "pop_inline_settings_host",
    "push_inline_settings_host",
    "settings_dialog",
    "short_text",
]
