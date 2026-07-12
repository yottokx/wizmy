"""
チャット/グループチャット共用のコンポーザー部品(ロール埋め込み・スマホ操作)。

- COMPOSER_CSS: ロール埋め込み入力ボックス+上スワイプメニューのスキン
- render_swipe_menu: 上スワイプで開くアクションメニュー(/choices /fill /tailor)
- 上スワイプ検出・送信ボタンロングタップ(/guide)の JS
"""

from __future__ import annotations

import html
from collections.abc import Awaitable, Callable

from nicegui import ui

COMPOSER_CSS = """
/* ロール埋め込み入力ボックス */
.comp-row { display: flex; gap: 12px; align-items: flex-end; }
/* ラベルは「送信」だが、ロングタップ(/guide)での文字選択・コールアウトは抑止する */
.comp-send {
  flex: none;
  padding: 9px 10px;
  font-size: 13.5px;
  letter-spacing: 0;
  user-select: none;
  -webkit-user-select: none;
  -webkit-touch-callout: none;
  touch-action: manipulation;
}
.comp-box {
  flex: 1; min-width: 0;
  background: transparent;
  border: none;
  border-bottom: 1px solid var(--line-2);
  border-radius: 0;
  padding: 3px 4px 2px;
  transition: border-color .18s;
}
.comp-box:focus-within { border-bottom-color: var(--accent); }
.comp-role {
  display: inline-flex; align-items: center;
  background: none; border: none; padding: 0;
  font-size: 11px; letter-spacing: .18em; color: var(--peri);
  cursor: pointer;
  transition: color .15s;
}
.comp-role:hover { filter: brightness(1.2); }

/* ロール種別の色分け(埋め込み表示のみ。ユーザーは基本色 --peri のまま) */
.comp-role.role-character { color: var(--accent); }
.comp-role.role-guest { color: #7fbf8e; }
.comp-role.role-narration { color: var(--star); }
.comp-role.role-memo { color: var(--muted); }
.comp-input { width: 100%; }
.comp-input .q-field__control {
  background: transparent;
  border: none;
  border-radius: 0;
  padding: 0;
  min-height: 24px;
  color: var(--text);
}
.comp-input .q-field__control:before, .comp-input .q-field__control:after { display: none; }
.comp-input textarea { color: var(--text) !important; font-size: 15px; line-height: 1.6; }

/* 上スワイプメニュー */
.p3-swipe-menu {
  background: var(--panel);
  border: 1px solid var(--line-2);
  border-radius: 6px;
  box-shadow: var(--shadow);
  margin-bottom: 10px;
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.p3-swipe-menu.hidden { display: none; }
.p3-swipe-option {
  display: flex; gap: 12px; align-items: baseline;
  border: none; background: none; color: var(--text);
  text-align: left; padding: 9px 12px; border-radius: 4px; cursor: pointer;
}
.p3-swipe-option:hover { background: var(--panel-2); }
.p3-swipe-option .cmd { font-size: 13px; color: var(--accent); font-weight: 600; flex: none; }
.p3-swipe-option .lbl { font-size: 12.5px; color: var(--muted); }

/* スマホ: 16px未満の入力はフォーカス時にブラウザが自動ズームして
   ページ全体がパン可能になるため、入力欄は16pxにする。
   送信ボタンはコンパクトにして入力欄の横幅を確保する */
@media (max-width: 860px) {
  .comp-input textarea { font-size: 16px; }
  .comp-row { gap: 8px; }
  .comp-box { padding: 2px 2px 2px; }
  .comp-send { padding: 8px 9px; font-size: 13px; }
}
"""

_SWIPE_ACTIONS: tuple[tuple[str, str], ...] = (
    ("choices", "選択肢を生成"),
    ("fill", "続きを補完"),
    ("tailor", "書き直す"),
)

# 入力欄の上スワイプ検出(touchstart で始点記録 → touchend で判定してメニューを開く)
INPUT_SWIPE_TOUCHSTART_JS = """
event => {
  const touch = event.touches && event.touches[0];
  if (!touch) return;
  window.__p3ComposerSwipeStart = {
    x: touch.clientX,
    y: touch.clientY,
    time: Date.now(),
  };
}
"""

INPUT_SWIPE_TOUCHEND_JS = """
event => {
  const start = window.__p3ComposerSwipeStart;
  const touch = event.changedTouches && event.changedTouches[0];
  window.__p3ComposerSwipeStart = null;
  if (!start || !touch) return;
  const dx = touch.clientX - start.x;
  const dy = touch.clientY - start.y;
  const elapsed = Date.now() - start.time;
  const isSwipeUp = dy < -42 && Math.abs(dy) > Math.abs(dx) * 1.15 && elapsed < 900;
  if (!isSwipeUp) return;
  const menu = document.querySelector('.p3-swipe-menu');
  if (!menu) return;
  event.preventDefault();
  document.querySelector('.p3-cmd-palette')?.classList.add('hidden');
  document.querySelector('.p3-mention-palette')?.classList.add('hidden');
  menu.classList.remove('hidden');
  if (!window.__p3SwipeDismiss) {
    window.__p3SwipeDismiss = dismissEvent => {
      const currentMenu = document.querySelector('.p3-swipe-menu');
      if (!currentMenu || currentMenu.classList.contains('hidden')) return;
      const target = dismissEvent.target;
      if (target && typeof target.closest === 'function' && target.closest('.p3-swipe-menu')) return;
      currentMenu.classList.add('hidden');
    };
    document.addEventListener('click', window.__p3SwipeDismiss, true);
    document.addEventListener('touchstart', window.__p3SwipeDismiss, true);
  }
}
"""

# 送信ボタンのロングタップ(650ms)で /guide。クリック抑止フラグで誤送信を防ぐ
SEND_LONGTAP_CLICK_JS = """
event => {
  if (window.__p3SendLongTapSuppressClick) {
    window.__p3SendLongTapSuppressClick = false;
    event.preventDefault();
    event.stopPropagation();
    return;
  }
  emit();
}
"""

SEND_LONGTAP_TOUCHSTART_JS = """
event => {
  const touch = event.touches && event.touches[0];
  if (!touch) return;
  clearTimeout(window.__p3SendLongTapTimer);
  window.__p3SendLongTapStart = {
    x: touch.clientX,
    y: touch.clientY,
  };
  window.__p3SendLongTapTriggered = false;
  window.__p3SendLongTapTimer = setTimeout(() => {
    window.__p3SendLongTapTriggered = true;
    window.__p3SendLongTapSuppressClick = true;
    setTimeout(() => {
      window.__p3SendLongTapSuppressClick = false;
    }, 1200);
    const input = document.querySelector('.comp-input textarea');
    emit(input && typeof input.value === 'string' ? input.value : '');
  }, 650);
}
"""

SEND_LONGTAP_TOUCHMOVE_JS = """
event => {
  const start = window.__p3SendLongTapStart;
  const touch = event.touches && event.touches[0];
  if (!start || !touch) return;
  const dx = touch.clientX - start.x;
  const dy = touch.clientY - start.y;
  if (Math.hypot(dx, dy) > 14) {
    clearTimeout(window.__p3SendLongTapTimer);
  }
}
"""

SEND_LONGTAP_TOUCHEND_JS = """
event => {
  clearTimeout(window.__p3SendLongTapTimer);
  window.__p3SendLongTapStart = null;
  if (window.__p3SendLongTapTriggered) {
    event.preventDefault();
  }
}
"""

SEND_LONGTAP_TOUCHCANCEL_JS = """
event => {
  clearTimeout(window.__p3SendLongTapTimer);
  window.__p3SendLongTapStart = null;
  window.__p3SendLongTapTriggered = false;
}
"""


def render_swipe_menu(run_command: Callable[[str], Awaitable[None]]) -> ui.element:
    """上スワイプで開くアクションメニューを構築する(初期状態は非表示)。"""
    menu = ui.element("div").classes("p3-swipe-menu hidden")

    def _handler(command: str):
        async def _run() -> None:
            menu.classes("hidden")
            await run_command(command)

        return _run

    with menu:
        for command, label in _SWIPE_ACTIONS:
            option = (
                ui.element("button")
                .classes("p3-swipe-option")
                .props(f"type=button data-swipe-command={command}")
            )
            option.on("click", _handler(command))
            with option:
                with ui.element("span").classes("cmd"):
                    ui.html(f"/{command}")
                with ui.element("span").classes("lbl"):
                    ui.html(html.escape(label))
    return menu


def install_composer_gestures(input_box: ui.element, send_btn: ui.element, on_send, on_guide) -> None:
    """入力欄の上スワイプと送信ボタンのロングタップ(/guide)を配線する。

    on_send: クリック時に呼ぶ(引数なし)。
    on_guide: ロングタップ時に呼ぶ(e.args = クライアント側の入力値)。
    """
    input_box.on("touchstart", js_handler=INPUT_SWIPE_TOUCHSTART_JS)
    input_box.on("touchend", js_handler=INPUT_SWIPE_TOUCHEND_JS)
    send_btn.on("click", on_send, js_handler=SEND_LONGTAP_CLICK_JS)
    send_btn.on("touchstart", on_guide, js_handler=SEND_LONGTAP_TOUCHSTART_JS)
    send_btn.on("touchmove", js_handler=SEND_LONGTAP_TOUCHMOVE_JS)
    send_btn.on("touchend", js_handler=SEND_LONGTAP_TOUCHEND_JS)
    send_btn.on("touchcancel", js_handler=SEND_LONGTAP_TOUCHCANCEL_JS)
