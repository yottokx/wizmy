"""
P3「With」テーマ。

- 2相テーマ: hoshi(星あかり・ダーク・既定)/ hinata(ひなた・ライト)
- 保存キーは `app.storage.user["ui2_theme"]`(旧UIの "theme" とは独立)
- トークンはモック `proposal/ui_redesign/proposal3/assets/p3.css` の :root 準拠
"""

from __future__ import annotations

import json

from nicegui import app

from ..config import PROJECT_ROOT

THEME_KEY = "ui2_theme"
DEFAULT_THEME = "hoshi"

THEMES: dict[str, dict] = {
    "hoshi": {
        "label": "星あかり",
        "button": "✦ 星あかり",
        "dark": True,
        "q-primary": "#ffb46b",
        "q-secondary": "#93a0ff",
        "q-negative": "#e08a8a",
    },
    "hinata": {
        "label": "ひなた",
        "button": "☀ ひなた",
        "dark": False,
        "q-primary": "#e07f2e",
        "q-secondary": "#4a55c4",
        "q-negative": "#b86e65",
    },
}

# モック p3.css の :root ブロック(テーマトークン)をそのまま移植
TOKENS_CSS = """
:root,
:root[data-theme="hoshi"] {
  --bg:        #0d1128;
  --bg-2:      #121736;
  --panel:     #171d40;
  --panel-2:   #1c234e;
  --text:      #eceef8;
  --muted:     #98a0c4;
  --line:      rgba(215, 222, 255, 0.10);
  --line-2:    rgba(215, 222, 255, 0.18);
  --accent:    #ffb46b;            /* ともしび(主動作) */
  --accent-ink:#2b1a05;
  --peri:      #93a0ff;            /* 星あかり(補助) */
  --bubble:    #1e2552;
  --bubble-user: #2a2440;
  --shadow:    0 18px 50px rgba(3, 5, 20, 0.55);
  --logo-p:    #dfe4ff;            /* ロゴ主色 */
  --logo-a:    #0d1128;            /* ロゴ抜き色(=背景) */
  --star:      #ffd9a0;
  --glow:      rgba(255, 180, 107, 0.18);
}
:root[data-theme="hinata"] {
  --bg:        #faf5ec;
  --bg-2:      #f3ecdf;
  --panel:     #fffdf8;
  --panel-2:   #f8f2e6;
  --text:      #2b2d42;
  --muted:     #77799a;
  --line:      rgba(38, 42, 96, 0.12);
  --line-2:    rgba(38, 42, 96, 0.22);
  --accent:    #e07f2e;
  --accent-ink:#fff8ef;
  --peri:      #4a55c4;
  --bubble:    #ffffff;
  --bubble-user: #f0e7d8;
  --shadow:    0 14px 40px rgba(90, 70, 30, 0.16);
  --logo-p:    #1a2470;
  --logo-a:    #faf5ec;
  --star:      #e8a24a;
  --glow:      rgba(224, 127, 46, 0.14);
}
"""

_LOGO_PATH = PROJECT_ROOT / "assets" / "wizmy.svg"
_LOGO_SVG_CACHE: str | None = None


def wizmy_logo_svg() -> str:
    """テーマ再着色可能な Wizmy ロゴSVGをインラインで返す。

    SVG 内の CSS 変数(--wizmy-bg/--wizmy-primary/--wizmy-accent)を
    `.wz-logo` のスコープで上書きして再着色する(scaffold の CSS 参照)。
    """
    global _LOGO_SVG_CACHE
    if _LOGO_SVG_CACHE is None:
        try:
            _LOGO_SVG_CACHE = _LOGO_PATH.read_text(encoding="utf-8")
        except OSError:
            _LOGO_SVG_CACHE = '<span class="wz-logo-fallback">Wizmy</span>'
    return _LOGO_SVG_CACHE


def get_theme() -> str:
    try:
        theme = app.storage.user.get(THEME_KEY, DEFAULT_THEME)
    except Exception:
        theme = DEFAULT_THEME
    return theme if theme in THEMES else DEFAULT_THEME


def set_theme(theme: str) -> None:
    if theme in THEMES:
        app.storage.user[THEME_KEY] = theme


def apply_theme_js(theme: str) -> str:
    """テーマを即座に適用する JavaScript を返す(初期注入と切替の両方で使用)。"""
    t = THEMES.get(theme, THEMES[DEFAULT_THEME])
    colors = json.dumps(
        {
            "primary": t["q-primary"],
            "secondary": t["q-secondary"],
            "negative": t["q-negative"],
        }
    )
    dark = "true" if t["dark"] else "false"
    return f"""
(function(){{
  var r = document.documentElement;
  r.setAttribute('data-theme', {json.dumps(theme)});
  var c = {colors};
  for (var k in c) r.style.setProperty('--q-' + k, c[k]);
  try {{ Quasar.Dark.set({dark}); }} catch(e) {{}}
}})();
"""
