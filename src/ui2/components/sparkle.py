"""
星のまたたき(sparkle)。

モック p3.js の sparkle-field を移植。`.sparkle-field` を position:relative な
コンテナ内に置くと、data-count 個の星がランダム配置されてまたたく。
"""

from __future__ import annotations

from nicegui import ui

# ロゴの星モチーフ(4条スパーク)
STAR_SVG = (
    '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
    '<path d="M12 0 C13.2 6.6 15 9 24 12 C15 15 13.2 17.4 12 24 '
    'C10.8 17.4 9 15 0 12 C9 9 10.8 6.6 12 0 Z"/></svg>'
)

SPARKLE_CSS = """
.sparkle-field { position: absolute; inset: 0; overflow: hidden; pointer-events: none; }
.spk {
  position: absolute;
  width: 10px;
  height: 10px;
  color: var(--star);
  opacity: 0;
  animation: twinkle var(--dur, 4s) ease-in-out var(--delay, 0s) infinite;
}
.spk svg { display: block; width: 100%; height: 100%; fill: currentColor; }
@keyframes twinkle {
  0%, 100% { opacity: 0; transform: scale(0.4) rotate(0deg); }
  50%      { opacity: var(--peak, 0.85); transform: scale(1) rotate(24deg); }
}
:root[data-theme="hinata"] .spk { --peak: 0.4; }
"""

# 未充填の .sparkle-field に星を配置する。動的追加分は window.p3SparkleFill() で再実行可。
SPARKLE_SCRIPT = f"""
<script>
(function () {{
  var STAR = '{STAR_SVG}';
  function fill(field) {{
    if (field.dataset.filled) return;
    field.dataset.filled = "1";
    var n = parseInt(field.getAttribute("data-count") || "14", 10);
    for (var i = 0; i < n; i++) {{
      var s = document.createElement("span");
      s.className = "spk";
      s.innerHTML = STAR;
      var size = 5 + Math.random() * 9;
      s.style.width = size + "px";
      s.style.height = size + "px";
      s.style.left = (Math.random() * 100) + "%";
      s.style.top = (Math.random() * 100) + "%";
      s.style.setProperty("--dur", (3 + Math.random() * 5).toFixed(2) + "s");
      s.style.setProperty("--delay", (Math.random() * 6).toFixed(2) + "s");
      field.appendChild(s);
    }}
  }}
  window.p3SparkleFill = function (root) {{
    (root || document).querySelectorAll(".sparkle-field").forEach(fill);
  }};
  if (document.readyState === "loading") {{
    document.addEventListener("DOMContentLoaded", function () {{ window.p3SparkleFill(); }});
  }} else {{
    window.p3SparkleFill();
  }}
}})();
</script>
"""


def install_sparkle_script() -> None:
    """ページに sparkle 初期化スクリプトを注入する(scaffold が1回呼ぶ)。"""
    ui.add_body_html(SPARKLE_SCRIPT)


def sparkle_field(count: int = 14) -> ui.element:
    """星のまたたきフィールドを配置する(親は position:relative であること)。"""
    return ui.element("div").classes("sparkle-field").props(f'data-count="{count}"')
