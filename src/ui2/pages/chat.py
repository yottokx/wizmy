"""
/characters/{id}/chat 1:1チャット(Phase 3)。モック proposal3/chat.html 準拠。

- 描画は P3。呼ぶものは全部既存 services:
  ChatService(セッションCRUD)/ ChatTurnService(ターン・ナレーション・自動タイトル)/
  ChatAssistService(補完・整え・選択肢・シーン強化)/ ai_jobs(実行+リロード復帰)/
  TTSService(読み上げ)
- ターン実行はトークンストリーミング無し: placeholder(「…」)→ AIJob →
  完了後に再描画+スナップショット保存。復帰は latest_active_job(scope) → wait
- スラッシュコマンドは `ui2/chat_commands.py`
- 相手ピッカー = list_recent の character_id 集計(chat_logic.build_partner_entries)
- セッション0件 = 初対面の空状態(自己紹介+はじめかた)。既定設定が揃っていれば
  入力からそのまま話し始められる(クイック開始)。無理なら新規セッションダイアログへ
- /chat はナビ用の入口: 最後に話した相手のチャットへリダイレクト
"""

from __future__ import annotations

import html
import json
from dataclasses import replace

from fastapi.responses import RedirectResponse
from nicegui import app, ui

from ...app_context import get_context
from ...core.character.schemas import (
    CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3,
    CHARACTER_TTS_API_GEN_SERVER,
    CHARACTER_TTS_API_TTS,
    CharacterSheet,
)
from ...core.chat.schemas import ChatMode, UserPersona
from ...core.chat.sessions import DEFAULT_CHAT_TITLE, ChatSessionRecord
from ...core.chat.templates import TemplateError
from ...core.conversation.history import (
    chat_message_from_dict,
    chat_message_to_dict,
    chat_settings_from_dict,
    chat_settings_to_dict,
    latest_message_preview,
)
from ...core.conversation.prompts.solo import build_system_prompt
from ...core.conversation.schemas import ChatMessagePreview, ChatSessionSettings, time_label
from ...core.conversation.solo import (
    USER_PERSONA_SOURCE_CHARACTER,
    USER_PERSONA_SOURCE_PERSONA,
    input_mode_for_speaker,
    message_target_label,
    render_mode_for_sheet,
    user_persona_tts_id,
)
from ...core.tts.schemas import TTS_PROVIDER_IRODORI_SERVER
from ...services.ai_jobs import AIJobKind, AIJobStatus
from ...services.llm_runtime import (
    API_KEY_LOCKED,
    ENDPOINT_NOT_FOUND,
    MODEL_ID_MISSING,
    PROFILE_NOT_FOUND,
    LLMRuntimeError,
    build_configured_llm,
)
from ...services.tts import TTSServiceError
from ..chat_commands import (
    command_suggestions,
    input_mode_label,
    parse_command_input,
    resolve_chat_command,
)
from ..chat_logic import (
    PartnerEntry,
    build_partner_entries,
    filter_partner_entries,
    user_persona_from_character_sheet,
)
from ..components.composer import COMPOSER_CSS, install_composer_gestures, render_swipe_menu
from ..components.portrait import face_avatar, image_object_position, media_url, raw_img
from ..group_setup import PICKER_CSS, open_character_pick_dialog
from ..scaffold import p3_page
from ..state import get_vault_password

# モック chat.html の <style> 移植+P3コンポーザー/パレット/メモ/操作列の追補
_PAGE_CSS = """
/* 高さは固定値の引き算をしない(HANDOFF f項): body縦フレックス+min-height:0 */
body { height: 100vh; height: 100dvh; overflow: hidden; }
/* スマホでの欄外パン・引っ張りスクロールを抑止 */
html, body { overscroll-behavior: none; }
#app, #q-app, .q-layout, .q-page-container, .q-page { height: 100%; min-height: 0 !important; }
.nicegui-content {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: stretch; /* NiceGUI 既定 flex-start だと子が内容幅に縮む */
  gap: 0;               /* NiceGUI 既定 gap の無駄な余白を除去 */
  min-height: 0;
  overflow-x: hidden;
}
.wz-nav, .gband { flex: none; }
/* バンド(行1・左〜中)を取り込んだ2行グリッド。presence はナビ直下から全高 */
.shell {
  position: relative;
  display: grid;
  grid-template-columns: 250px minmax(0, 1fr) 330px;
  grid-template-rows: auto minmax(0, 1fr);
  flex: 1;
  min-height: 0;
}
.shell .gband { grid-column: 1 / 3; grid-row: 1; z-index: 1; }
.shell .sessions { grid-column: 1; grid-row: 2; }
.shell .stream-wrap { grid-column: 2; grid-row: 2; }
.shell .presence { grid-column: 3; grid-row: 1 / 3; }

/* ---------- ヘッダバンド(1行目セッション/2行目キャラ名) ---------- */
.gband {
  position: relative;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 7px 26px;
  border-bottom: 1px solid var(--line);
  background:
    radial-gradient(ellipse 60% 140% at 85% 0%, color-mix(in srgb, var(--peri) 14%, transparent), transparent 70%),
    var(--bg-2);
  overflow: hidden;
}
/* キャラ変更ボタン(顔アイコン) */
.pa-btn {
  flex: none;
  width: 34px; height: 34px;
  border-radius: 50%;
  border: 2px solid var(--line-2);
  padding: 0;
  overflow: hidden;
  background: var(--panel-2);
  cursor: pointer;
  transition: border-color .18s, box-shadow .18s;
}
.pa-btn:hover { border-color: var(--accent); box-shadow: 0 0 0 2px var(--glow); }
.pa-btn .avatar { width: 100%; height: 100%; border: none; }
.pa-btn .pa-ph {
  width: 100%; height: 100%;
  display: grid; place-items: center;
  background: var(--panel-2); color: var(--peri);
  font-family: "Yu Mincho", serif; font-size: 15px;
}
/* タイトル列。余白はすべてこの列がもらう(スペーサーを置くと幅を取り合って
   余白があるのにタイトルが省略される) */
.gband .ttl {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0;
  flex: 1;
  min-width: 0;
}
.gband .gname {
  max-width: 100%;
  font-size: 11px;
  letter-spacing: .14em;
  color: var(--muted);
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sess-trigger {
  display: inline-flex;
  align-items: baseline;
  gap: 7px;
  background: none; border: none; padding: 0;
  max-width: 100%;
  min-width: 0;
  cursor: default;
  color: var(--text);
  text-align: left;
}
.sess-trigger .st {
  font-size: 15px;
  font-weight: 600;
  letter-spacing: .06em;
  line-height: 1.45;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}
.sess-trigger .w { font-size: 11.5px; color: var(--muted); white-space: nowrap; flex: none; }
.sess-trigger .caret { display: none; color: var(--muted); font-size: 10px; flex: none; }

/* ---------- 左:セッション ---------- */
.sessions {
  border-right: 1px solid var(--line);
  padding: 16px 14px 20px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  overflow-y: auto;
  min-height: 0;
}
.sessions .lbl { font-size: 11px; letter-spacing: .3em; color: var(--muted); padding: 0 8px 8px; }
.sess { position: relative; padding: 10px 12px; cursor: pointer; border-left: 2px solid transparent; }
.sess:hover { background: var(--panel); }
.sess.on { background: var(--panel); border-left-color: var(--accent); }
.sess .t { font-size: 13.5px; font-weight: 600; letter-spacing: .03em; line-height: 1.5; }
.sess .s { font-size: 11.5px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.no-sess { padding: 10px 12px; font-size: 12px; color: var(--muted); line-height: 1.7; }
.scene {
  margin-top: auto;
  border-top: 1px solid var(--line);
  padding: 14px 6px 4px;
}
.scene .lbl2 { font-size: 10.5px; letter-spacing: .26em; color: var(--peri); margin-bottom: 4px; }
.scene .tx {
  font-size: 12.5px; color: var(--muted); line-height: 1.6;
  display: -webkit-box; -webkit-line-clamp: 5; -webkit-box-orient: vertical; overflow: hidden;
}
.scene .edit { font-size: 11.5px; color: var(--accent); margin-top: 6px; cursor: pointer; }

/* ---------- 中央:ストリーム ---------- */
.stream-wrap { display: flex; flex-direction: column; min-width: 0; min-height: 0; }

.stream { flex: 1; min-height: 0; overflow-y: auto; padding: 30px 34px 20px; }
.stream-inner { max-width: 760px; margin: 0 auto; display: flex; flex-direction: column; gap: 14px; }
/* 台本方式: 吹き出しの代わりに要素間をヘアラインで区切る(地の文・コメント含む) */
.stream-inner > * + * { border-top: 1px solid var(--line); padding-top: 20px; }
/* 横画面は余白のみで区切る(ヘアラインは縦画面・スマホのみ) */
@media (orientation: landscape) {
  .stream-inner > * + * { border-top: none; }
}

.narr-wrap { text-align: center; }
.narr {
  color: var(--muted);
  font-size: 13.5px;
  letter-spacing: .08em;
  font-family: "Yu Mincho", "Hiragino Mincho ProN", serif;
}
.narr-wrap .ops { display: flex; gap: 4px; justify-content: flex-end; margin-top: 0; margin-bottom: -12px; opacity: 0; transition: opacity .18s; }
.narr-wrap:hover .ops { opacity: 1; }

.memo {
  max-width: 560px; width: fit-content;
  margin: 0 auto;
  border: 1px solid var(--line-2);
  border-left: 3px solid var(--peri);
  padding: 10px 18px 8px;
  color: var(--muted); font-size: 13px; line-height: 1.7; text-align: left;
  white-space: pre-wrap; overflow-wrap: anywhere;
}
.memo .ops { display: flex; gap: 4px; justify-content: flex-end; margin-top: 4px; opacity: 0; transition: opacity .18s; }
.memo:hover .ops { opacity: 1; }

.msg { display: flex; gap: 14px; align-items: flex-start; }
.msg .avatar { width: 44px; height: 44px; object-fit: cover; flex: none; }
.msg .body { min-width: 0; flex: 1; }
.msg.user .body { flex: 0 1 auto; }
.msg .who { font-size: 12.5px; letter-spacing: .16em; color: var(--peri); margin: 2px 0 4px; }
.msg .bubble {
  background: none; border: none; box-shadow: none; border-radius: 0;
  padding: 0; font-size: 15px; white-space: pre-wrap; overflow-wrap: anywhere;
}
.msg .bubble::before { display: none; }
.msg .ops { display: flex; flex-wrap: wrap; gap: 4px; justify-content: flex-end; margin-top: 0; margin-bottom: -12px; opacity: 0; transition: opacity .18s; align-items: center; }
.msg:hover .ops { opacity: 1; }
.msg.user { flex-direction: row-reverse; }
.msg.user .bubble { background: none; border-radius: 0; text-align: left; }
.msg.user .who { text-align: right; color: var(--muted); }
.ops .btn.quiet { padding: 2px 10px; font-size: 11.5px; line-height: 1.4; white-space: nowrap; }
.ops .btn.quiet:hover {
  background: none; transform: none;
  text-decoration: underline; text-underline-offset: 3px;
}
.ops .tm { font-size: 11px; color: var(--muted); }

/* 初対面(セッション0件)の空状態 */
.fresh { padding-top: 6vh; text-align: center; }
.fresh .hello { color: var(--peri); font-size: 11px; letter-spacing: .34em; margin-bottom: 18px; }
.fresh .bubble {
  display: inline-block; max-width: 520px; text-align: left; font-size: 15px;
  background: none; border: none; box-shadow: none; border-radius: 0; padding: 0;
  font-family: "Yu Mincho", "Hiragino Mincho ProN", serif; line-height: 2;
}
.fresh .bubble::before { display: none; }
.fresh .starters { display: flex; gap: 8px; justify-content: center; margin-top: 26px; flex-wrap: wrap; }

/* ---------- コンポーザー ---------- */
.composer { padding: 7px 34px 18px; border-top: 1px solid var(--line); }
.composer-inner { max-width: 760px; margin: 0 auto; }
/* 入力ボックス(ロール埋め込み)とスワイプメニューは components/composer.py の COMPOSER_CSS */
.comp-send[disabled] { opacity: .5; pointer-events: none; }

/* コマンドパレット(入力末尾の / で開く。モック未着手のため P3 トーンで新設) */
.p3-cmd-palette {
  background: var(--panel);
  border: 1px solid var(--line-2);
  border-radius: 6px;
  box-shadow: var(--shadow);
  margin-bottom: 10px;
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 240px;
  overflow-y: auto;
}
.p3-cmd-palette.hidden { display: none; }
.p3-cmd-option {
  display: flex; gap: 12px; align-items: baseline;
  border: none; background: none; color: var(--text);
  text-align: left; padding: 7px 12px; border-radius: 4px; cursor: pointer;
}
.p3-cmd-option:hover, .p3-cmd-option-active { background: var(--panel-2); }
.p3-cmd-name { font-size: 13px; color: var(--accent); font-weight: 600; flex: none; }
.p3-cmd-desc { font-size: 12px; color: var(--muted); }

/* 選択肢ダイアログ(/choices) */
.p3-choice-option {
  display: block; width: 100%; text-align: left;
  border: 1px solid var(--line-2); background: var(--panel-2); color: var(--text);
  border-radius: 4px; padding: 10px 14px; cursor: pointer;
  font-size: 13.5px; line-height: 1.6;
}
.p3-choice-option-active { border-color: var(--accent); box-shadow: 0 0 0 2px var(--glow); }

/* ---------- 右:いま話している子 ---------- */
.presence {
  position: relative;
  border-left: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
}
.presence .portrait { position: relative; flex: 1; min-height: 90px; }
.presence .portrait img {
  position: absolute; inset: 0;
  width: 100%; height: 100%;
  object-fit: cover;
  -webkit-mask-image: linear-gradient(to top, transparent 2%, #000 30%);
  mask-image: linear-gradient(to top, transparent 2%, #000 30%);
}
.presence .pmeta { position: absolute; left: 20px; right: 16px; bottom: 8px; z-index: 2; }
.presence .pname-row { display: flex; align-items: baseline; gap: 12px; min-width: 0; }
.presence .pname { font-size: 19px; letter-spacing: .14em; }
.presence .pocc { font-size: 11px; color: var(--muted); letter-spacing: .04em; }
.presence .sheet-btn {
  border: none; background: none; padding: 0; flex: none;
  font-size: 11.5px; color: var(--muted); cursor: pointer;
  opacity: 0; transition: opacity .18s, color .15s;
}
.presence .pmeta:hover .sheet-btn { opacity: 1; }
.presence .sheet-btn:hover { color: var(--text); text-decoration: underline; text-underline-offset: 3px; }

/* ---------- 相手ピッカー(オーバーレイ) ----------
   パネル・検索・pcard のスキンは group_setup.PICKER_CSS と共用 */
.picker {
  position: fixed; inset: 0; z-index: 90;
  display: none;
  align-items: flex-start; justify-content: center;
  background: color-mix(in srgb, var(--bg) 72%, transparent);
  backdrop-filter: blur(10px);
  overflow-y: auto;
  padding: 7vh 20px 40px;
}
.picker.open { display: flex; }
.pcard.on { border-color: var(--accent); box-shadow: 0 0 0 2px var(--glow); }

/* セッションドロワー(中間幅以下) */
.sess-close { display: none; }
.sessions-backdrop {
  display: none;
  position: fixed;
  top: 55px; left: 0; right: 0; bottom: 0;
  z-index: 69;
  background: color-mix(in srgb, var(--bg) 45%, transparent);
}

/* ダイアログ・メニューのP3スキン */
.q-menu { background: var(--panel); color: var(--text); }
.p3-ta { width: 100%; }
.p3-ta .q-field__control { background: var(--bg-2) !important; border-radius: 6px; }
.p3-ta .q-field__control:before { border-color: var(--line-2) !important; }
.p3-ta textarea, .p3-ta input { color: var(--text) !important; line-height: 1.8; }

/* ============ 中間幅 ============ */
@media (max-width: 1180px) {
  .shell { grid-template-columns: minmax(0, 1fr) 300px; }
  /* sessions は fixed でグリッドから抜けるため配置を詰め直す */
  .shell .gband { grid-column: 1 / 2; }
  .shell .stream-wrap { grid-column: 1; }
  .shell .presence { grid-column: 2; grid-row: 1 / 3; }
  /* セッションタイトル自体がドロワーのトリガになる */
  .sess-trigger { cursor: pointer; }
  .sess-trigger .caret { display: inline; }
  .sess-trigger:hover .st, .sess-trigger:hover .caret { color: var(--accent); }
  .sessions {
    position: fixed;
    top: 55px; left: 0; bottom: 0;
    width: 280px;
    background: var(--bg-2);
    z-index: 70;
    transform: translateX(-102%);
    transition: transform .25s ease;
    box-shadow: var(--shadow);
    border-right: 1px solid var(--line-2);
  }
  .sessions.open { transform: none; }
  .sessions.open { padding-top: 50px; }
  .sess-close {
    display: grid; place-items: center;
    position: absolute; top: 10px; right: 10px;
    width: 32px; height: 32px;
    border-radius: 50%;
    border: 1px solid var(--line-2);
    background: var(--panel-2);
    color: var(--muted);
    cursor: pointer;
    font-size: 15px;
    z-index: 2;
  }
  .sess-close:hover { color: var(--text); }
  .sessions.open + .sessions-backdrop { display: block; }
}

/* ============ 縦画面・スマホ ============ */
@media (max-width: 860px) {
  /* バンドは文字とパディングを縮小 */
  .gband { padding: 6px 10px; gap: 8px; min-width: 0; max-width: 100vw; }
  .pa-btn { width: 30px; height: 30px; }
  .sess-trigger .st { font-size: 13.5px; line-height: 1.35; }
  .sess-trigger .w { display: none; }
  .gband .gname { font-size: 10.5px; letter-spacing: .12em; line-height: 1.35; }
  .shell { display: flex; flex-direction: column; }
  /* 背景画像はヘッダを除いたクライアント領域(.shell)全体にはめ込む */
  .presence {
    position: absolute;
    inset: 0;
    width: auto; max-width: none; height: auto;
    border-left: none;
    z-index: 0;
    pointer-events: none;
    opacity: .2;
  }
  .presence .pmeta { display: none; }
  .stream-wrap { position: relative; z-index: 1; flex: 1; min-height: 0; }
  .stream { padding: 12px 12px 8px; overflow-x: hidden; }
  .stream-inner { gap: 14px; }
  .stream-inner > * + * { padding-top: 14px; }
  .msg { gap: 10px; }
  .msg .bubble { font-size: 14.5px; }
  .msg .avatar { width: 34px; height: 34px; }
  .msg .who { margin: 0 0 4px; }
  .msg .ops, .narr-wrap .ops, .memo .ops { opacity: .75; gap: 2px; }
  .msg .ops, .narr-wrap .ops { margin-bottom: 0; }
  .ops .btn.quiet { font-size: 11px; padding: 1px 8px; }
  .composer { padding: 8px 10px 10px; }
  .picker { padding: 4vh 14px 30px; }
  .pgrid { grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 10px; }
}

/* ============ 低い画面(ノートPC・ウィンドウ縮小時) ============ */
@media (max-height: 760px) {
  .gband { padding: 6px 26px; }
  .stream { padding: 18px 34px 12px; }
  .stream-inner { gap: 12px; }
  .composer { padding: 8px 34px 12px; }
  .comp-input .q-field__control { min-height: 30px; }
}
"""

# 入力欄の keydown: Enter送信 / Alt+Enter改行 / パレットの ↑↓ 選択+Enter確定
# (旧 chat/components.py の JS を P3 クラス名に合わせて移植)
_COMPOSER_KEYDOWN_JS = """
event => {
  const target = event.target;
  const value = target && typeof target.value === 'string' ? target.value : '';
  const commandMatch = value.match(/^([\\s\\S]*)\\/([A-Za-z]*)$/);
  const palette = document.querySelector('.p3-cmd-palette');
  const options = palette ? Array.from(palette.querySelectorAll('.p3-cmd-option')) : [];
  const activeIndex = () => Math.max(0, options.findIndex(option => option.classList.contains('p3-cmd-option-active')));
  const setActive = index => {
    options.forEach((option, optionIndex) => {
      const active = optionIndex === index;
      option.classList.toggle('p3-cmd-option-active', active);
      option.setAttribute('aria-selected', active ? 'true' : 'false');
      if (active && typeof option.scrollIntoView === 'function') {
        option.scrollIntoView({ block: 'nearest' });
      }
    });
  };
  if (commandMatch && options.length && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
    event.preventDefault();
    const delta = event.key === 'ArrowDown' ? 1 : -1;
    const next = (activeIndex() + delta + options.length) % options.length;
    setActive(next);
    return;
  }
  if (event.key !== 'Enter' || event.isComposing) return;
  if (event.altKey) {
    event.preventDefault();
    if (target && typeof target.value === 'string') {
      const start = target.selectionStart ?? target.value.length;
      const end = target.selectionEnd ?? target.value.length;
      target.value = target.value.slice(0, start) + '\\n' + target.value.slice(end);
      target.selectionStart = target.selectionEnd = start + 1;
      target.dispatchEvent(new Event('input', { bubbles: true }));
    }
    return;
  }
  if (event.shiftKey) return;
  // スマホ(coarse pointer)では改行キーで投稿しない(送信はボタンのみ)
  if (window.matchMedia('(pointer: coarse)').matches) return;
  event.preventDefault();
  if (commandMatch && options.length) {
    const active = options[activeIndex()] || options[0];
    const command = active && active.dataset ? active.dataset.command : '';
    if (command) {
      target.value = commandMatch[1] + '/' + command;
      target.dispatchEvent(new Event('input', { bubbles: true }));
    }
  }
  if (palette) {
    palette.classList.add('hidden');
  }
  emit(target && typeof target.value === 'string' ? target.value : '');
}
"""

# 選択肢ダイアログの ↑↓/Enter ナビゲーション(旧 controller の JS を P3 クラス名で移植)
_CHOICES_KEYBOARD_JS = """
setTimeout(() => {
  const root = document.querySelector('.p3-choice-dialog');
  if (!root) return;
  const options = Array.from(root.querySelectorAll('.p3-choice-option, .p3-choice-close'));
  if (!options.length) return;
  const activeIndex = () => Math.max(0, options.findIndex(option => option.classList.contains('p3-choice-option-active')));
  const setActive = index => {
    options.forEach((option, optionIndex) => {
      const active = optionIndex === index;
      option.classList.toggle('p3-choice-option-active', active);
      option.setAttribute('aria-selected', active ? 'true' : 'false');
      if (active && typeof option.scrollIntoView === 'function') {
        option.scrollIntoView({ block: 'nearest' });
      }
    });
  };
  setActive(0);
  if (window.__p3ChoiceKeydown) {
    document.removeEventListener('keydown', window.__p3ChoiceKeydown, true);
  }
  window.__p3ChoiceKeydown = event => {
    if (!document.body.contains(root)) {
      document.removeEventListener('keydown', window.__p3ChoiceKeydown, true);
      window.__p3ChoiceKeydown = null;
      return;
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const delta = event.key === 'ArrowDown' ? 1 : -1;
      setActive((activeIndex() + delta + options.length) % options.length);
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      (options[activeIndex()] || options[0]).click();
    }
  };
  document.addEventListener('keydown', window.__p3ChoiceKeydown, true);
}, 0);
"""

_PERSONA_SELECT_PREFIX = "persona:"
_CHARACTER_SELECT_PREFIX = "character:"

_DIALOG_CARD_STYLE = "background: var(--panel); color: var(--text);"


def _p3_button(label: str, on_click, *, classes: str = "btn", title: str = "") -> ui.element:
    btn = ui.element("button").classes(classes)
    if title:
        btn.props(f'title="{html.escape(title)}"')
    with btn:
        ui.html(html.escape(label))
    btn.on("click", on_click)
    return btn


def _chip_button(label: str, on_click, *, title: str = "") -> ui.element:
    btn = ui.element("button").classes("chip")
    if title:
        btn.props(f'title="{html.escape(title)}"')
    with btn:
        ui.html(html.escape(label))
    btn.on("click", on_click)
    return btn


def _inline_html(text: str) -> str:
    return html.escape(text).replace("\n", "<br>")


# ---- LLMプロファイル系ヘルパ(旧 controller 下部の関数群を ui2 用に再実装) ----


def profile_options_for_context(ctx) -> dict[str, str]:
    profiles = ctx.api_config.get_llm_profiles()
    endpoints = {ep.id: ep for ep in ctx.api_config.get_endpoints()}
    options: dict[str, str] = {}
    for profile in profiles:
        endpoint = endpoints.get(profile.endpoint_id)
        endpoint_name = endpoint.name if endpoint else "不明"
        model = profile.model_id or "未設定"
        options[profile.id] = f"{profile.name} [{endpoint_name} / {model}]"
    return options


def profile_is_startable(ctx, profile_id: str) -> bool:
    profile = ctx.api_config.get_llm_profile(profile_id)
    if profile is None or not profile.model_id:
        return False
    return ctx.api_config.get_endpoint(profile.endpoint_id) is not None


def validate_profile_for_start(ctx, profile_id: str) -> bool:
    profile = ctx.api_config.get_llm_profile(profile_id)
    if profile is None:
        ui.notify("LLMプロファイルが見つかりません", type="negative")
        return False
    if not profile.model_id:
        ui.notify("モデルIDが未設定です。設定画面でLLMプロファイルのモデルを設定してください。", type="negative")
        return False
    if ctx.api_config.get_endpoint(profile.endpoint_id) is None:
        ui.notify("エンドポイントが見つかりません", type="negative")
        return False
    return True


def configured_llm_for_profile(ctx, profile_id: str):
    try:
        return build_configured_llm(ctx.api_config, profile_id, get_vault_password())
    except LLMRuntimeError as err:
        if err.kind == PROFILE_NOT_FOUND:
            ui.notify("LLMプロファイルが見つかりません", type="negative")
        elif err.kind == MODEL_ID_MISSING:
            ui.notify("モデルIDが未設定です。設定画面でLLMプロファイルのモデルを設定してください。", type="negative")
        elif err.kind == ENDPOINT_NOT_FOUND:
            ui.notify("エンドポイントが見つかりません", type="negative")
        elif err.kind == API_KEY_LOCKED:
            ui.notify(
                "このエンドポイントにはAPIキーが設定されています。APIキーボルトをロック解除してください。",
                type="warning",
                timeout=8000,
            )
        return None


def default_profile_id(ctx, profile_options: dict[str, str]) -> str:
    if not profile_options:
        return ""
    app_config = ctx.api_config.get_app_llm_config()
    for candidate in (app_config.chat_profile_id, app_config.generation_profile_id):
        if candidate in profile_options:
            return candidate
    return next(iter(profile_options))


def default_chat_mode_id(mode_options: dict[str, str]) -> str:
    if not mode_options:
        return ""
    for preferred in ("smalltalk", "roleplay", "summon"):
        if preferred in mode_options:
            return preferred
    return next(iter(mode_options))


def default_user_persona_id(persona_options: dict[str, str]) -> str:
    if not persona_options:
        return ""
    return next(iter(persona_options))


class Ui2ChatController:
    """1:1チャットページの編成(旧 ChatPageController 踏襲)+P3描画。"""

    def __init__(self, ctx, sheet: CharacterSheet, page_client, partners: list[PartnerEntry]) -> None:
        self.ctx = ctx
        self.sheet = sheet
        self.page_client = page_client
        self.partners = partners
        self.image = sheet.media.primary_image()
        self.voice = sheet.media.primary_voice()
        self.voice_path = ctx.characters.media_path(self.voice.path) if self.voice else None
        self.tts_configured = bool(
            self.voice
            and self.voice_path
            and ctx.tts.has_voice_playback_api(sheet.media.tts.api_type, sheet.media.tts.endpoint_id)
        )
        self.user_persona: UserPersona | None = None
        self.user_persona_character: CharacterSheet | None = None
        self.user_voice = None
        self.user_voice_path = None
        self.user_tts_configured = False

        self.sessions: list[ChatSessionRecord] = []
        self.sessions_by_id: dict[str, ChatSessionRecord] = {}
        self.active_session_id: str | None = None
        self.active_title_is_auto = False
        self.title_generation_attempted = False

        self.title = "チャットを開始"
        self.settings: ChatSessionSettings | None = None
        self.messages: list[ChatMessagePreview] = []
        self.sending = False
        self.tts_generating_index: int | None = None
        self.input_mode = "user"

        # 描画参照
        self.sess_list: ui.element | None = None
        self.scene_box: ui.element | None = None
        self.head_title: ui.element | None = None
        self.head_world: ui.element | None = None
        self.stream_inner: ui.element | None = None
        self.input: ui.textarea | None = None
        self.send_btn: ui.element | None = None
        self.role_chip: ui.element | None = None
        self.role_chip_label: ui.html | None = None
        self.role_menu_box: ui.menu | None = None
        self.palette: ui.element | None = None
        self.picker: ui.element | None = None

    # ------------------------------------------------------------------
    # 初期化・状態
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        await self.reload_sessions()
        if self.sessions:
            await self.apply_session(self.sessions[0])

    async def reload_sessions(self) -> None:
        self.sessions = await self.ctx.chats.list_for_character(self.sheet.id)
        self.sessions_by_id = {session.id: session for session in self.sessions}

    async def apply_session(self, session: ChatSessionRecord) -> None:
        self.active_session_id = session.id
        self.active_title_is_auto = session.title_is_auto
        self.title_generation_attempted = False
        self.title = session.title or DEFAULT_CHAT_TITLE
        self.settings = chat_settings_from_dict(session.settings)
        self.messages = [chat_message_from_dict(message) for message in session.messages]
        await self.refresh_user_persona_media()
        self.input_mode = "user"
        self.sending = False
        self.tts_generating_index = None

    def clear_active_session(self) -> None:
        self.active_session_id = None
        self.active_title_is_auto = False
        self.title_generation_attempted = False
        self.title = "チャットを開始"
        self.settings = None
        self.messages = []
        self.clear_user_persona_media()
        self.input_mode = "user"
        self.sending = False
        self.tts_generating_index = None

    def clear_user_persona_media(self) -> None:
        self.user_persona = None
        self.user_persona_character = None
        self.user_voice = None
        self.user_voice_path = None
        self.user_tts_configured = False

    async def refresh_user_persona_media(self) -> None:
        settings = self.settings
        if settings is None or not settings.user_persona_id:
            self.clear_user_persona_media()
            return
        if settings.user_persona_source == USER_PERSONA_SOURCE_CHARACTER:
            character = await self.ctx.characters.get(settings.user_persona_id)
            if character is None:
                self.clear_user_persona_media()
                return
            self.user_persona = None
            self.user_persona_character = character
            self.user_voice = character.media.primary_voice()
            self.user_voice_path = self.ctx.characters.media_path(self.user_voice.path) if self.user_voice else None
            self.user_tts_configured = self._user_media_tts_configured(character.media.tts)
            return
        persona = self.ctx.user_personas.get_user_persona(settings.user_persona_id)
        if persona is None:
            self.clear_user_persona_media()
            return
        self.user_persona = persona
        self.user_persona_character = None
        self.user_voice = persona.media.primary_voice()
        self.user_voice_path = self.ctx.user_personas.media_path(self.user_voice.path) if self.user_voice else None
        self.user_tts_configured = self._user_media_tts_configured(persona.media.tts)

    def _user_media_tts_configured(self, tts_settings) -> bool:
        voice_design_ready = (
            tts_settings.api_type == CHARACTER_TTS_API_GEN_SERVER
            and tts_settings.gen_server_tts_mode == CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3
            and bool(tts_settings.voice_caption.strip())
        )
        voice_registry_ready = (
            tts_settings.api_type == CHARACTER_TTS_API_TTS
            and bool(tts_settings.voice_id.strip())
            and self.ctx.tts.supports_voice_registry(tts_settings.endpoint_id)
        )
        return bool(
            self.ctx.tts.has_voice_playback_api(tts_settings.api_type, tts_settings.endpoint_id)
            and (self.user_voice_path is not None or voice_design_ready or voice_registry_ready)
        )

    def _narrator_tts_configured(self, tts_settings=None) -> bool:
        config = self.ctx.user_personas.get_tts_config()
        settings = tts_settings or config.narrator
        narrator_voice_path = (
            self.ctx.user_personas.media_path(config.narrator_voice.path) if config.narrator_voice is not None else None
        )
        if settings.api_type == CHARACTER_TTS_API_GEN_SERVER:
            if settings.gen_server_tts_mode == CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3:
                return bool(
                    settings.voice_caption.strip()
                    and self.ctx.tts.resolve_gen_server_voice_design_endpoint(raise_on_missing=False) is not None
                )
            return bool(
                narrator_voice_path is not None
                and self.ctx.tts.resolve_gen_server_voice_clone_endpoint(raise_on_missing=False) is not None
            )
        if settings.api_type != CHARACTER_TTS_API_TTS:
            return False
        endpoint = self.ctx.api_config.get_tts_endpoint(settings.endpoint_id)
        if endpoint is None:
            return False
        if endpoint.provider == TTS_PROVIDER_IRODORI_SERVER:
            return bool(settings.voice_id.strip())
        return narrator_voice_path is not None

    def _user_voice_design_ready(self) -> bool:
        if self.user_persona_character is not None:
            settings = self.user_persona_character.media.tts
        elif self.user_persona is not None:
            settings = self.user_persona.media.tts
        else:
            return False
        return (
            settings.api_type == CHARACTER_TTS_API_GEN_SERVER
            and settings.gen_server_tts_mode == CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3
            and bool(settings.voice_caption.strip())
        )

    def tts_playable_speakers(self) -> set[str]:
        speakers: set[str] = set()
        if self.tts_configured:
            speakers.add("character")
        if self.user_tts_configured:
            speakers.add("user")
        if self._narrator_tts_configured():
            speakers.add("narration")
        return speakers

    def _face_avatar(self) -> ui.element | None:
        """相手の顔ズーム済み丸アイコン(face_rect ズーム。無ければ None)。"""
        if self.image is None:
            return None
        path = self.ctx.characters.media_path(self.image.path)
        return face_avatar(self.image, "avatar", image_path=path)

    # ------------------------------------------------------------------
    # JSユーティリティ
    # ------------------------------------------------------------------

    def run_page_javascript(self, code: str) -> None:
        self.page_client.run_javascript(code)

    def focus_chat_input_at_end(self) -> None:
        self.run_page_javascript(
            "setTimeout(() => {"
            "const el = document.querySelector('.comp-input textarea');"
            "if (!el) return;"
            "el.focus();"
            "const end = el.value.length;"
            "if (typeof el.setSelectionRange === 'function') el.setSelectionRange(end, end);"
            "}, 0);"
        )

    def set_mobile_sessions(self, open_: bool) -> None:
        action = "add" if open_ else "remove"
        self.run_page_javascript(f"document.querySelector('.sessions')?.classList.{action}('open');")

    def scroll_messages_to_bottom(self) -> None:
        self.run_page_javascript(
            "(() => {"
            "const scroll = () => {"
            "const el = document.querySelector('.stream');"
            "if (el) el.scrollTop = el.scrollHeight;"
            "};"
            "setTimeout(scroll, 0);"
            "setTimeout(scroll, 50);"
            "})();"
        )

    def clear_input(self) -> None:
        self.set_input_value("")
        self.run_page_javascript(
            "(() => {"
            "const clear = () => {"
            "const el = document.querySelector('.comp-input textarea');"
            "if (!el) return;"
            "el.value = '';"
            "el.dispatchEvent(new Event('input', { bubbles: true }));"
            "};"
            "clear();"
            "setTimeout(clear, 0);"
            "setTimeout(clear, 50);"
            "setTimeout(clear, 150);"
            "})();"
        )

    def set_input_value(self, value: str) -> None:
        if self.input is not None:
            self.input.set_value(value)

    # ------------------------------------------------------------------
    # 描画
    # ------------------------------------------------------------------

    def render_shell(self) -> None:
        with ui.element("div").classes("shell"):
            # ---- バンド(行1・左〜中): キャラ変更+セッション/キャラ名の2段タイトル ----
            with ui.element("div").classes("gband"):
                partner_btn = (
                    ui.element("button")
                    .classes("pa-btn")
                    .props('title="相手を変更"')
                    .mark("ui2-chat-partner-change")
                )
                with partner_btn:
                    if self._face_avatar() is None:
                        with ui.element("div").classes("pa-ph"):
                            ui.html(html.escape((self.sheet.name or "?")[:1]))
                partner_btn.on("click", self.open_picker)
                with ui.element("div").classes("ttl"):
                    trigger = ui.element("button").classes("sess-trigger").props('title="セッション一覧"')
                    with trigger:
                        self.head_title = ui.element("span").classes("st serif").mark("ui2-chat-title")
                        self.head_world = ui.element("span").classes("w")
                        with ui.element("span").classes("caret"):
                            ui.html("▾")
                    trigger.on(
                        "click",
                        js_handler="() => { if (window.matchMedia('(max-width: 1180px)').matches) "
                        "document.querySelector('.sessions')?.classList.toggle('open'); }",
                    )
                    with ui.element("span").classes("gname serif"):
                        ui.html(html.escape(self.sheet.name))
                menu_btn = ui.element("button").classes("btn quiet").mark("ui2-chat-menu")
                with menu_btn:
                    ui.html("⋯")
                    with ui.menu().props('anchor="bottom right" self="top right"'):
                        ui.menu_item("新しいセッション", on_click=lambda: self.open_new_chat_dialog())
                        ui.menu_item("タイトル変更", on_click=self.open_rename_current_chat_dialog)
                        ui.menu_item("システムプロンプト", on_click=self.open_system_prompt_dialog)
                        ui.menu_item("セッション削除", on_click=self.confirm_delete_current_chat)

            # ---- 左: セッション ----
            with ui.element("aside").classes("sessions"):
                close_btn = ui.element("button").classes("sess-close").props('title="履歴を閉じる"')
                with close_btn:
                    ui.html("×")
                close_btn.on(
                    "click",
                    js_handler="() => document.querySelector('.sessions')?.classList.remove('open')",
                )
                with ui.element("div").classes("lbl"):
                    ui.html("セッション")
                self.sess_list = ui.element("div").mark("ui2-chat-sessions")
                _p3_button("+ 新しいセッション", lambda: self.open_new_chat_dialog(), classes="btn quiet").style(
                    "align-self: flex-start;"
                ).mark("ui2-chat-new-session")
                self.scene_box = ui.element("div").classes("scene")

            # ドロワー時のバックドロップ(.sessions の隣接要素であること。タップで閉じる)
            backdrop = ui.element("div").classes("sessions-backdrop")
            backdrop.on(
                "click",
                js_handler="() => document.querySelector('.sessions')?.classList.remove('open')",
            )

            # ---- 中央: ストリーム ----
            with ui.element("main").classes("stream-wrap"):
                with ui.element("div").classes("stream"):
                    self.stream_inner = ui.element("div").classes("stream-inner").mark("ui2-chat-stream")

                # ---- コンポーザー ----
                with ui.element("div").classes("composer"):
                    with ui.element("div").classes("composer-inner"):
                        self.palette = ui.element("div").classes("p3-cmd-palette hidden")
                        render_swipe_menu(self._run_chip_command)
                        with ui.element("div").classes("comp-row"):
                            with ui.element("div").classes("comp-box"):
                                self.role_chip = (
                                    ui.element("button")
                                    .classes(f"comp-role role-{self.input_mode}")
                                    .mark("ui2-chat-role-chip")
                                )
                                with self.role_chip:
                                    self.role_chip_label = ui.html(html.escape(self._role_label(self.input_mode)))
                                    self.role_menu_box = ui.menu().classes("wz-nav-menu")
                                self.refresh_role_menu()
                                self.input = (
                                    ui.textarea(placeholder="メッセージを入力")
                                    .props("borderless dense rows=1 autogrow")
                                    .classes("comp-input")
                                    .mark("ui2-chat-input")
                                )
                                self.input.on_value_change(
                                    lambda e: self._refresh_command_palette(str(e.value or ""))
                                )
                                self.input.on("keydown", self._send_from_enter, js_handler=_COMPOSER_KEYDOWN_JS)
                            self.send_btn = (
                                ui.element("button")
                                .classes("btn primary comp-send")
                                .props('title="送信(長押しで誘導)" aria-label="送信"')
                                .mark("ui2-chat-send")
                            )
                            with self.send_btn:
                                ui.html("送信")
                            install_composer_gestures(
                                self.input,
                                self.send_btn,
                                lambda: self.send_message(True),
                                self._guide_from_long_tap,
                            )

            # ---- 右: いま話している子 ----
            with ui.element("aside").classes("presence"):
                with ui.element("div").classes("portrait"):
                    url = media_url(self.image.path) if self.image is not None else None
                    if url is not None:
                        raw_img(url).style(
                            f"object-position: {image_object_position(self.image, 'bust')};"
                        )
                    with ui.element("div").classes("pmeta"):
                        with ui.element("div").classes("pname-row"):
                            with ui.element("div").classes("pname serif"):
                                ui.html(html.escape(self.sheet.name))
                            sheet_btn = (
                                ui.element("button")
                                .classes("sheet-btn")
                                .props('title="キャラクターシートを開く"')
                            )
                            with sheet_btn:
                                ui.html("シートを開く")
                            sheet_btn.on("click", lambda: ui.navigate.to(f"/characters/{self.sheet.id}"))
                        with ui.element("div").classes("pocc"):
                            ui.html(html.escape(self.sheet.occupation))

        self._render_picker()
        self.refresh_sessions_pane()
        self.refresh_chat_header()
        self.refresh_scene()
        self.refresh_messages(scroll_to_bottom=True)
        ui.timer(0.1, self.restore_active_ai_job, once=True)

    def _render_partner_card(self, entry: PartnerEntry) -> None:
        card = ui.element("div").classes("pcard on" if entry.sheet.id == self.sheet.id else "pcard")
        card.on(
            "click",
            lambda cid=entry.sheet.id: ui.navigate.to(f"/characters/{cid}/chat"),
        )
        with card:
            image = entry.sheet.media.primary_image()
            url = media_url(image.path) if image is not None else None
            if url is not None:
                raw_img(url).props('loading="lazy"').style(
                    f"object-position: {image_object_position(image)};"
                )
            else:
                with ui.element("div").classes("p-ph"):
                    ui.html(html.escape((entry.sheet.name or "?")[:1]))
            ui.element("div").classes("veil")
            with ui.element("div").classes("info"):
                with ui.element("div").classes("nm serif"):
                    ui.html(html.escape(entry.sheet.name))
                with ui.element("div").classes("st"):
                    ui.html(html.escape(entry.last_label))

    def _render_picker(self) -> None:
        state = {"search": "", "favorites": False}
        self.picker = ui.element("div").classes("picker")
        with self.picker:
            with ui.element("div").classes("picker-panel"):
                with ui.element("div").classes("picker-head"):
                    with ui.element("h2").classes("serif"):
                        ui.html("誰と話しますか")
                    with ui.element("span").classes("note"):
                        ui.html("最近話した順")
                    search_input = (
                        ui.element("input")
                        .classes("psearch")
                        .props('placeholder="名前・世界観で検索" type="search"')
                        .mark("ui2-chat-picker-search")
                    )
                    fav_chip = ui.element("button").classes("chip").mark("ui2-chat-picker-fav")
                    with fav_chip:
                        ui.html("★ お気に入り")
                    _p3_button("閉じる", self.close_picker, classes="btn quiet close")
                grid = ui.element("div").classes("pgrid").mark("ui2-chat-picker-grid")

        def _refresh_grid() -> None:
            grid.clear()
            entries = filter_partner_entries(self.partners, state["search"], state["favorites"])
            with grid:
                for entry in entries:
                    self._render_partner_card(entry)
                if not entries:
                    with ui.element("div").classes("note picker-empty"):
                        ui.html("該当するキャラクターがいません")

        def _toggle_favorites() -> None:
            state["favorites"] = not state["favorites"]
            if state["favorites"]:
                fav_chip.classes("on")
            else:
                fav_chip.classes(remove="on")
            _refresh_grid()

        def _on_search(e) -> None:
            state["search"] = str(e.args or "")
            _refresh_grid()

        fav_chip.on("click", _toggle_favorites)
        search_input.on(
            "input",
            _on_search,
            js_handler="(e) => emit(e.target.value)",
            throttle=0.3,
            trailing_events=True,
        )
        _refresh_grid()
        self.picker.on("click.self", self.close_picker)

    def open_picker(self) -> None:
        if self.picker is not None:
            self.picker.classes("open")

    def close_picker(self) -> None:
        if self.picker is not None:
            self.picker.classes(remove="open")

    def refresh_sessions_pane(self) -> None:
        if self.sess_list is None:
            return
        self.sess_list.clear()
        with self.sess_list:
            if not self.sessions:
                with ui.element("div").classes("no-sess"):
                    ui.html("まだセッションがありません。<br>下の入力から、そのまま話しかけられます。")
                return
            for session in self.sessions:
                item = ui.element("div").classes("sess on" if session.id == self.active_session_id else "sess")
                item.on("click", lambda sid=session.id: self.select_chat_session(sid))
                with item:
                    with ui.element("div").classes("t"):
                        ui.html(html.escape(session.title or DEFAULT_CHAT_TITLE))
                    with ui.element("div").classes("s"):
                        ui.html(html.escape(latest_message_preview(session.messages)))

    def refresh_scene(self) -> None:
        if self.scene_box is None:
            return
        self.scene_box.clear()
        settings = self.settings
        if settings is None or not settings.situation.strip():
            self.scene_box.set_visibility(False)
            return
        self.scene_box.set_visibility(True)
        with self.scene_box:
            with ui.element("div").classes("lbl2"):
                ui.html("シーン")
            with ui.element("div").classes("tx"):
                ui.html(_inline_html(settings.situation.strip()))
            edit = ui.element("div").classes("edit")
            with edit:
                ui.html("シーンを編集")
            edit.on("click", self.open_scene_dialog)

    def chat_title(self) -> str:
        return self.title or "チャットを開始"

    def chat_world_label(self) -> str:
        if self.settings is None:
            return self.sheet.world.strip().splitlines()[0] if self.sheet.world.strip() else ""
        profile = self.ctx.api_config.get_llm_profile(self.settings.profile_id)
        profile_name = profile.name if profile else "不明なプロファイル"
        return f"{self.settings.chat_mode_name} / {profile_name}"

    def refresh_chat_header(self) -> None:
        if self.head_title is not None:
            self.head_title.clear()
            with self.head_title:
                ui.html(html.escape(self.chat_title()))
        if self.head_world is not None:
            self.head_world.clear()
            with self.head_world:
                ui.html(html.escape(self.chat_world_label()))

    def refresh_messages(self, *, scroll_to_bottom: bool = False) -> None:
        if self.stream_inner is None:
            return
        if not scroll_to_bottom:
            self.run_page_javascript(
                "(() => {"
                "const el = document.querySelector('.stream');"
                "window.__p3ChatScrollTop = el ? el.scrollTop : null;"
                "})();"
            )
        self.stream_inner.clear()
        with self.stream_inner:
            if self.active_session_id is None:
                self._render_fresh_state()
            else:
                for index, message in enumerate(self.messages):
                    self._render_message(index, message)
        if scroll_to_bottom:
            self.scroll_messages_to_bottom()
        else:
            self.run_page_javascript(
                "setTimeout(() => {"
                "const el = document.querySelector('.stream');"
                "const top = window.__p3ChatScrollTop;"
                "if (el && typeof top === 'number') el.scrollTop = top;"
                "window.__p3ChatScrollTop = null;"
                "}, 0);"
            )

    def _render_fresh_state(self) -> None:
        intro = " ".join(self.sheet.self_intro.split())
        while intro.startswith("「") and intro.endswith("」"):
            intro = intro[1:-1].strip()
        with ui.element("div").classes("fresh"):
            with ui.element("div").classes("hello"):
                ui.html("はじめまして")
            if intro:
                with ui.element("div").classes("bubble tail-left"):
                    ui.html(_inline_html(f"「{intro}」"))
            with ui.element("div").classes("starters"):
                _chip_button("あいさつを返す", lambda: self.focus_chat_input_at_end())
                _chip_button("シーンを設定して始める", lambda: self.open_new_chat_dialog())
                _chip_button("シートを見る", lambda: ui.navigate.to(f"/characters/{self.sheet.id}"))

    def _ops_row(self, index: int, message: ChatMessagePreview) -> None:
        playable = self.tts_playable_speakers()
        with ui.element("div").classes("ops"):
            if message.speaker in playable and message.text.strip():
                label = "生成中…" if self.tts_generating_index == index else "音声"
                btn = _p3_button(
                    label,
                    lambda i=index: self.play_tts_message(i),
                    classes="btn quiet",
                    title="読み上げ",
                )
                if self.tts_generating_index is not None:
                    btn.props("disabled")
            if message.speaker == "character":
                _p3_button(
                    "再生成",
                    lambda i=index: self.confirm_or_regenerate_character_message(i),
                    classes="btn quiet",
                    title="この台詞を再生成",
                )
            _p3_button(
                "編集",
                lambda i=index: self.open_rewrite_message_dialog(i),
                classes="btn quiet",
                title="この内容を書き換え",
            )
            _p3_button(
                "戻る",
                lambda i=index: self.confirm_rewind_to_message(i),
                classes="btn quiet",
                title="ここまで巻き戻す(以降を削除して入力欄へ)",
            )
            if message.speaker == "character" and message.debug is not None:
                _p3_button(
                    "入出力",
                    lambda d=message.debug: self.open_llm_debug_dialog(d),
                    classes="btn quiet",
                    title="LLMデバッグ(入出力・トークン)",
                )
            with ui.element("span").classes("tm"):
                ui.html(html.escape(message.time_label))

    def _render_message(self, index: int, message: ChatMessagePreview) -> None:
        if message.speaker == "narration":
            with ui.element("div").classes("narr-wrap"):
                with ui.element("div").classes("narr"):
                    ui.html(_inline_html(message.text))
                self._ops_row(index, message)
            return
        if message.speaker == "memo":
            with ui.element("div").classes("memo-wrap"), ui.element("div").classes("memo"):
                ui.html(_inline_html(message.text))
                self._ops_row(index, message)
            return

        is_user = message.speaker == "user"
        with ui.element("div").classes("msg user" if is_user else "msg"):
            if not is_user:
                self._face_avatar()
            with ui.element("div").classes("body"):
                who = (
                    (self.settings.user_persona_name if self.settings is not None else "") or "あなた"
                    if is_user
                    else self.sheet.name
                )
                with ui.element("div").classes("who"):
                    ui.html(html.escape(who))
                with ui.element("div").classes("bubble"):
                    ui.html(_inline_html(message.text))
                self._ops_row(index, message)

    def _role_label(self, mode: str) -> str:
        """ロール表示名。ユーザー/キャラクターは実名(ペルソナ名・キャラ名)を出す。"""
        if mode == "user":
            return (self.settings.user_persona_name if self.settings is not None else "") or "ユーザー"
        if mode == "character":
            return self.sheet.name
        return input_mode_label(mode)

    def refresh_input_mode_chip(self) -> None:
        if self.role_chip_label is not None:
            self.role_chip_label.set_content(html.escape(self._role_label(self.input_mode)))
        if self.role_chip is not None:
            self.role_chip.classes(remove="role-user role-character role-narration role-memo")
            self.role_chip.classes(f"role-{self.input_mode}")
        self.refresh_role_menu()

    def refresh_role_menu(self) -> None:
        if self.role_menu_box is None:
            return
        self.role_menu_box.clear()
        with self.role_menu_box:
            for mode in ("user", "character", "narration", "memo"):
                ui.menu_item(
                    self._role_label(mode),
                    on_click=lambda m=mode: self.set_input_mode(m, notify_change=False),
                )

    def set_input_mode(self, mode: str, *, notify_change: bool = False) -> None:
        self.input_mode = mode if mode in {"character", "narration", "memo"} else "user"
        self.refresh_input_mode_chip()
        if notify_change:
            ui.notify(f"{self._role_label(self.input_mode)}入力モードにしました", type="info")

    def set_sending(self, sending: bool) -> None:
        self.sending = sending
        if self.send_btn is not None:
            if sending:
                self.send_btn.props("disabled")
            else:
                self.send_btn.props(remove="disabled")
        if self.input is not None:
            self.input.disable() if sending else self.input.enable()

    # ------------------------------------------------------------------
    # コマンドパレット
    # ------------------------------------------------------------------

    def _refresh_command_palette(self, value: str) -> None:
        if self.palette is None:
            return
        self.palette.clear()
        parsed = parse_command_input(value)
        if parsed is None:
            self.palette.classes("hidden")
            return
        _, query = parsed
        suggestions = command_suggestions(query)
        self.palette.classes(remove="hidden")
        with self.palette:
            if not suggestions:
                with ui.element("div").classes("note").style("padding: 6px 12px;"):
                    ui.html("該当するコマンドがありません")
                return
            for index, command in enumerate(suggestions):
                classes = "p3-cmd-option p3-cmd-option-active" if index == 0 else "p3-cmd-option"
                option = (
                    ui.element("button")
                    .props(
                        f"type=button data-command={command.name} "
                        f"aria-selected={'true' if index == 0 else 'false'}"
                    )
                    .classes(classes)
                )
                with option:
                    with ui.element("span").classes("p3-cmd-name"):
                        ui.html(f"/{command.name}")
                    with ui.element("span").classes("p3-cmd-desc"):
                        ui.html(html.escape(command.description))
                option.on("click", lambda name=command.name: self._apply_command_suggestion(name))

    async def _apply_command_suggestion(self, command: str) -> None:
        if self.input is None or self.palette is None:
            return
        parsed = parse_command_input(str(self.input.value or ""))
        left_text = parsed[0] if parsed is not None else ""
        self.palette.clear()
        self.palette.classes("hidden")
        await self.send_message(False, f"{left_text}/{command}")

    async def _run_chip_command(self, command: str) -> None:
        if self.input is None:
            return
        current_text = str(self.input.value or "")
        parsed = parse_command_input(current_text)
        left_text = parsed[0] if parsed is not None else current_text
        if self.palette is not None:
            self.palette.clear()
            self.palette.classes("hidden")
        submitted = f"{left_text.rstrip()}/{command}" if left_text.strip() else f"/{command}"
        await self.send_message(False, submitted)

    async def _guide_from_long_tap(self, e) -> None:
        """送信ボタンのロングタップ: 入力値を指示にして /guide を送る。"""
        value = str(e.args[0] or "") if isinstance(e.args, list) and e.args else str(e.args or "")
        parsed = parse_command_input(value)
        left_text = parsed[0] if parsed is not None else value
        submitted = f"{left_text.rstrip()}/guide" if left_text.strip() else "/guide"
        await self.send_message(False, submitted)

    async def _send_from_enter(self, e) -> None:
        if isinstance(e.args, list):
            value = str(e.args[0] or "") if e.args else ""
        else:
            value = str(e.args or "")
        await self.send_message(False, value)

    # ------------------------------------------------------------------
    # セッションの保存・同期・AIジョブ(旧 controller 踏襲)
    # ------------------------------------------------------------------

    async def save_current_session(self, *, refresh_history: bool = True) -> None:
        if self.active_session_id is None or self.settings is None:
            return
        saved = await self.ctx.chats.update_session(
            session_id=self.active_session_id,
            character_id=self.sheet.id,
            title=self.title or DEFAULT_CHAT_TITLE,
            title_is_auto=self.active_title_is_auto,
            settings=chat_settings_to_dict(self.settings),
            messages=[chat_message_to_dict(message) for message in self.messages],
        )
        self.sessions_by_id[saved.id] = saved
        if refresh_history:
            await self.reload_sessions()
            self.refresh_sessions_pane()

    async def _save_session_messages_snapshot(
        self,
        *,
        session_id: str,
        title: str,
        title_is_auto: bool,
        settings: ChatSessionSettings,
        messages: list[ChatMessagePreview],
    ) -> None:
        saved = await self.ctx.chats.update_session(
            session_id=session_id,
            character_id=self.sheet.id,
            title=title or DEFAULT_CHAT_TITLE,
            title_is_auto=title_is_auto,
            settings=chat_settings_to_dict(settings),
            messages=[chat_message_to_dict(message) for message in messages],
        )
        self.sessions_by_id[saved.id] = saved

    async def _sync_active_session_from_storage(self) -> None:
        if self.active_session_id is None:
            return
        session = await self.ctx.chats.get(self.active_session_id)
        if session is None:
            return
        self.sessions_by_id[session.id] = session
        await self.apply_session(session)
        self.refresh_input_mode_chip()
        self.refresh_chat_header()
        self.refresh_scene()
        self.refresh_messages(scroll_to_bottom=True)
        await self.reload_sessions()
        self.refresh_sessions_pane()

    def _active_chat_scope(self) -> str:
        return f"chat:{self.active_session_id or 'none'}"

    def _result_url(self) -> str:
        return f"/characters/{self.sheet.id}/chat"

    async def restore_active_ai_job(self) -> None:
        if self.active_session_id is None:
            return
        job = self.ctx.ai_jobs.latest_active_job(scope=self._active_chat_scope())
        if job is None:
            return
        await self._wait_for_active_chat_job(job.id, failure_message="生成に失敗しました")

    async def _wait_for_active_chat_job(self, job_id: str, *, failure_message: str) -> bool:
        self.set_sending(True)
        try:
            job = await self.ctx.ai_jobs.wait(job_id)
            if job.status == AIJobStatus.SUCCEEDED:
                await self._sync_active_session_from_storage()
                return True
            if job.status == AIJobStatus.CANCELLED:
                ui.notify("生成を停止しました", type="info")
                await self._sync_active_session_from_storage()
                return False
            ui.notify(f"{failure_message}: {job.error_message}", type="negative", timeout=10000)
            await self._sync_active_session_from_storage()
            return False
        finally:
            self.set_sending(False)

    def _solo_assist_scope(self) -> str:
        return f"assist:{self.active_session_id or self.sheet.id}"

    def _solo_assist_metadata(self) -> dict[str, str]:
        return {"character_id": self.sheet.id, "session_id": self.active_session_id or ""}

    async def _await_llm_assist_result(self, result_awaitable, *, failure_message: str):
        self.set_sending(True)
        try:
            result = await result_awaitable
            if result.status == AIJobStatus.SUCCEEDED:
                return result.value
            if result.status == AIJobStatus.CANCELLED:
                ui.notify("生成を停止しました", type="info")
                return None
            ui.notify(f"{failure_message}: {result.error_message}", type="negative", timeout=10000)
            return None
        finally:
            self.set_sending(False)

    def configured_llm(self, settings: ChatSessionSettings):
        return configured_llm_for_profile(self.ctx, settings.profile_id)

    # ------------------------------------------------------------------
    # セッション操作
    # ------------------------------------------------------------------

    async def select_chat_session(self, session_id: str) -> None:
        if self.sending:
            ui.notify("生成中はセッションを切り替えられません", type="warning")
            return
        session = await self.ctx.chats.get(session_id)
        if session is None or session.character_id != self.sheet.id:
            ui.notify("セッションが見つかりません", type="warning")
            await self.reload_sessions()
            self.refresh_sessions_pane()
            return
        self.sessions_by_id[session.id] = session
        await self.apply_session(session)
        self.refresh_input_mode_chip()
        self.refresh_chat_header()
        self.refresh_scene()
        self.refresh_messages(scroll_to_bottom=True)
        self.refresh_sessions_pane()
        self.set_mobile_sessions(False)

    def open_rename_current_chat_dialog(self) -> None:
        if self.active_session_id is None:
            ui.notify("先にセッションを開始してください", type="warning")
            return
        self.open_rename_chat_dialog(self.active_session_id)

    def confirm_delete_current_chat(self) -> None:
        if self.active_session_id is None:
            ui.notify("削除するセッションがありません", type="warning")
            return
        self.confirm_delete_chat_session(self.active_session_id)

    def open_rename_chat_dialog(self, session_id: str) -> None:
        session = self.sessions_by_id.get(session_id)
        if session is None:
            ui.notify("セッションが見つかりません", type="warning")
            return
        with ui.dialog() as dlg, ui.card().classes("w-full max-w-md").style(_DIALOG_CARD_STYLE):
            ui.label("タイトル変更").classes("text-base font-semibold")
            title_input = (
                ui.input(label="タイトル", value=session.title or DEFAULT_CHAT_TITLE)
                .props("outlined clearable")
                .classes("w-full p3-ta")
                .mark("ui2-chat-rename-input")
            )

            async def _save_title() -> None:
                title = (title_input.value or "").strip()
                if not title:
                    ui.notify("タイトルを入力してください", type="warning")
                    return
                saved = await self.ctx.chats.rename_session(session_id, title)
                if saved is None:
                    dlg.close()
                    ui.notify("セッションが見つかりません", type="warning")
                    await self.reload_sessions()
                    self.refresh_sessions_pane()
                    return
                self.sessions_by_id[saved.id] = saved
                if saved.id == self.active_session_id:
                    self.title = saved.title
                    self.active_title_is_auto = False
                    self.refresh_chat_header()
                await self.reload_sessions()
                self.refresh_sessions_pane()
                dlg.close()

            with ui.row().classes("justify-end gap-2 mt-4 w-full"):
                _p3_button("キャンセル", dlg.close, classes="btn quiet")
                _p3_button("保存", _save_title, classes="btn primary").mark("ui2-chat-rename-save")
        dlg.open()

    def confirm_delete_chat_session(self, session_id: str) -> None:
        if self.sending:
            ui.notify("生成中は削除できません", type="warning")
            return
        session = self.sessions_by_id.get(session_id)
        if session is None:
            ui.notify("セッションが見つかりません", type="warning")
            return
        with ui.dialog() as dlg, ui.card().classes("w-full max-w-sm").style(_DIALOG_CARD_STYLE):
            ui.label("セッションを削除しますか？").classes("text-base font-semibold")
            ui.label("この操作は元に戻せません。").classes("note")
            ui.label(session.title or DEFAULT_CHAT_TITLE).classes("text-sm font-semibold")

            async def _delete() -> None:
                dlg.close()
                was_active = session_id == self.active_session_id
                await self.ctx.chats.delete_session(session_id)
                await self.reload_sessions()
                if was_active:
                    if self.sessions:
                        await self.apply_session(self.sessions[0])
                    else:
                        self.clear_active_session()
                    self.refresh_input_mode_chip()
                    self.refresh_chat_header()
                    self.refresh_scene()
                    self.refresh_messages(scroll_to_bottom=True)
                self.refresh_sessions_pane()

            with ui.row().classes("justify-end gap-2 mt-4 w-full"):
                _p3_button("キャンセル", dlg.close, classes="btn quiet")
                _p3_button("削除", _delete, classes="btn primary").mark("ui2-chat-delete-confirm")
        dlg.open()

    def open_scene_dialog(self) -> None:
        settings = self.settings
        if settings is None:
            ui.notify("先にセッションを開始してください", type="warning")
            return
        with ui.dialog() as dlg, ui.card().classes("w-full max-w-xl").style(_DIALOG_CARD_STYLE):
            ui.label("シーンを編集").classes("text-base font-semibold")
            ui.label("以降のターンから反映されます(過去の発言は変わりません)。").classes("note")
            scene_input = (
                ui.textarea(value=settings.situation)
                .props("outlined rows=5 autogrow")
                .classes("w-full p3-ta")
            )

            async def _save_scene() -> None:
                if self.settings is None:
                    dlg.close()
                    return
                self.settings = replace(self.settings, situation=str(scene_input.value or "").strip())
                dlg.close()
                self.refresh_scene()
                await self.save_current_session()
                ui.notify("シーンを更新しました", type="positive")

            with ui.row().classes("justify-end gap-2 mt-4 w-full"):
                _p3_button("キャンセル", dlg.close, classes="btn quiet")
                _p3_button("保存", _save_scene, classes="btn primary")
        dlg.open()

    def open_system_prompt_dialog(self) -> None:
        settings = self.settings
        if settings is None:
            ui.notify("先にセッションを開始してください", type="warning")
            return
        prompt = build_system_prompt(self.sheet, settings)
        with ui.dialog() as dlg, ui.card().classes("w-full max-w-4xl").style(_DIALOG_CARD_STYLE):
            with ui.row().classes("items-center justify-between w-full"):
                ui.label("システムプロンプト").classes("text-lg font-semibold")
                _p3_button("閉じる", dlg.close, classes="btn quiet")
            with ui.scroll_area().style("height: 62vh; width: 100%;"):
                ui.code(prompt, language="text").classes("w-full text-xs")
        dlg.open()

    def open_llm_debug_dialog(self, debug) -> None:
        def _token_label(value: int | None) -> str:
            return str(value) if value is not None else "不明"

        token_lines = [
            f"入力: {_token_label(debug.input_tokens)}",
            f"出力: {_token_label(debug.output_tokens)}",
            f"合計: {_token_label(debug.total_tokens)}",
        ]
        with ui.dialog() as dlg, ui.card().classes("w-full max-w-4xl").style(_DIALOG_CARD_STYLE):
            with ui.row().classes("items-center justify-between w-full"):
                ui.label("LLMデバッグ").classes("text-lg font-semibold")
                _p3_button("閉じる", dlg.close, classes="btn quiet")
            ui.label(" / ".join(token_lines)).classes("note")
            ui.label("入力").classes("text-sm font-semibold mt-2")
            with ui.scroll_area().style("height: 32vh; width: 100%;"):
                ui.code(debug.llm_input, language="text").classes("w-full text-xs")
            if debug.reasoning_output:
                ui.label("推論 / Thinking").classes("text-sm font-semibold mt-2")
                with ui.scroll_area().style("height: 22vh; width: 100%;"):
                    ui.code(debug.reasoning_output, language="text").classes("w-full text-xs")
            ui.label("出力").classes("text-sm font-semibold mt-2")
            with ui.scroll_area().style("height: 22vh; width: 100%;"):
                ui.code(debug.raw_output, language="text").classes("w-full text-xs")
        dlg.open()

    # ------------------------------------------------------------------
    # メッセージ操作(巻き戻し・書き換え・再生成・TTS)
    # ------------------------------------------------------------------

    async def rewind_to_message(self, index: int) -> None:
        if self.sending:
            ui.notify("生成中は戻れません", type="warning")
            return
        if index < 0 or index >= len(self.messages):
            return
        message = self.messages[index]
        if message.speaker not in {"character", "user", "narration", "memo"}:
            return
        self.messages = self.messages[:index]
        if self.input is not None:
            self.input.set_value(message.text)
            self.input.enable()
        self.set_input_mode(input_mode_for_speaker(message.speaker))
        self.set_sending(False)
        self.refresh_messages()
        await self.save_current_session()

    def confirm_rewind_to_message(self, index: int) -> None:
        if self.sending:
            ui.notify("生成中は戻れません", type="warning")
            return
        if index < 0 or index >= len(self.messages):
            return
        message = self.messages[index]
        if message.speaker not in {"character", "user", "narration", "memo"}:
            return
        target_label = message_target_label(message.speaker)
        with ui.dialog() as dlg, ui.card().classes("w-full max-w-sm").style(_DIALOG_CARD_STYLE):
            ui.label(f"この{target_label}まで戻りますか？").classes("text-base font-semibold")
            ui.label(f"この{target_label}以降の会話を削除し、本文を入力欄に戻します。").classes("note")
            ui.label(message.text).classes("text-sm").style("white-space: pre-wrap; overflow-wrap: anywhere;")

            async def _do_rewind() -> None:
                dlg.close()
                await self.rewind_to_message(index)

            with ui.row().classes("justify-end gap-2 mt-4 w-full"):
                _p3_button("キャンセル", dlg.close, classes="btn quiet")
                _p3_button("OK", _do_rewind, classes="btn primary")
        dlg.open()

    def open_rewrite_message_dialog(self, index: int) -> None:
        if self.sending:
            ui.notify("生成中は書き換えできません", type="warning")
            return
        if index < 0 or index >= len(self.messages):
            return
        message = self.messages[index]
        speaker_label = {
            "character": "キャラクターの台詞",
            "user": "ユーザーの発言",
            "narration": "地の文",
            "memo": "コメント",
        }.get(message.speaker, "メッセージ")
        with ui.dialog() as dlg, ui.card().classes("w-full max-w-xl").style(_DIALOG_CARD_STYLE):
            ui.label(f"{speaker_label}を書き換え").classes("text-base font-semibold")
            ui.label("保存しても、この後の会話は削除されません。").classes("note")
            rewrite_input = (
                ui.textarea(value=message.text, placeholder="書き換え後の本文")
                .props("outlined rows=5 autogrow")
                .classes("w-full p3-ta")
                .mark("ui2-chat-rewrite-input")
            )

            async def _save_rewrite() -> None:
                next_text = (rewrite_input.value or "").strip()
                if not next_text:
                    ui.notify("本文を入力してください", type="warning")
                    return
                if index >= len(self.messages):
                    dlg.close()
                    return
                current = self.messages[index]
                self.messages[index] = ChatMessagePreview(
                    current.speaker,
                    next_text,
                    current.time_label,
                    current.debug,
                )
                dlg.close()
                self.refresh_messages()
                await self.save_current_session()

            with ui.row().classes("justify-end gap-2 mt-4 w-full"):
                _p3_button("キャンセル", dlg.close, classes="btn quiet")
                _p3_button("保存", _save_rewrite, classes="btn primary").mark("ui2-chat-rewrite-save")
        dlg.open()

    async def maybe_generate_auto_title(self, llm, settings: ChatSessionSettings) -> None:
        if self.active_session_id is None or not self.active_title_is_auto:
            return
        if self.title_generation_attempted:
            return
        character_turns = sum(1 for message in self.messages if message.speaker == "character")
        if character_turns < 3:
            return
        self.title_generation_attempted = True
        try:
            title = await self.ctx.chat_turns.generate_auto_title(
                sheet=self.sheet,
                settings=settings,
                messages=self.messages,
                llm=llm,
            )
        except Exception:
            return
        if not title:
            return
        self.title = title
        self.active_title_is_auto = False
        self.refresh_chat_header()
        await self.save_current_session()

    async def play_tts_message(self, index: int) -> None:
        if self.tts_generating_index is not None:
            ui.notify("音声生成中です", type="info")
            return
        if index < 0 or index >= len(self.messages):
            return
        message = self.messages[index]
        if message.speaker not in {"character", "user", "narration"}:
            return
        text = message.text.strip()
        if not text or text in {"…", "..."}:
            ui.notify("読み上げる本文がありません", type="warning")
            return

        if message.speaker == "narration":
            config = self.ctx.user_personas.get_tts_config()
            settings = config.narrator
            if not self._narrator_tts_configured(settings):
                ui.notify("ナレーターTTS設定を確認してください", type="warning")
                return
            target_id = "narrator"
            voice = config.narrator_voice
            voice_path = self.ctx.user_personas.media_path(voice.path) if voice else None
            playback_save = self.ctx.user_personas.save_narrator_tts_playback
        elif message.speaker == "character":
            if not self.tts_configured or self.voice is None or self.voice_path is None:
                ui.notify("TTS設定を確認してください", type="warning")
                return
            target_id = self.sheet.id
            settings = self.sheet.media.tts
            voice = self.voice
            voice_path = self.voice_path
            playback_save = lambda audio: self.ctx.characters.save_tts_playback(self.sheet.id, audio)
        else:
            if (
                self.settings is not None
                and self.settings.user_persona_source == USER_PERSONA_SOURCE_CHARACTER
            ):
                if (
                    not self.user_tts_configured
                    or self.user_persona_character is None
                    or (self.user_voice_path is None and not self._user_voice_design_ready())
                ):
                    ui.notify("ユーザー役のTTS設定を確認してください", type="warning")
                    return
                user_character_id = self.user_persona_character.id
                target_id = user_character_id
                settings = self.user_persona_character.media.tts
                voice = self.user_voice
                voice_path = self.user_voice_path
                playback_save = lambda audio, character_id=user_character_id: self.ctx.characters.save_tts_playback(
                    character_id,
                    audio,
                )
            else:
                if (
                    not self.user_tts_configured
                    or self.user_persona is None
                    or (self.user_voice_path is None and not self._user_voice_design_ready())
                ):
                    ui.notify("ユーザーペルソナのTTS設定を確認してください", type="warning")
                    return
                user_persona_id = self.user_persona.id
                target_id = user_persona_tts_id(user_persona_id)
                settings = self.user_persona.media.tts
                voice = self.user_voice
                voice_path = self.user_voice_path
                playback_save = lambda audio, persona_id=user_persona_id: (
                    self.ctx.user_personas.save_user_persona_tts_playback(persona_id, audio)
                )

        if (
            settings.api_type == CHARACTER_TTS_API_GEN_SERVER
            and settings.gen_server_tts_mode == CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3
            and not settings.voice_caption.strip()
        ):
            ui.notify("VoiceDesign v3モードのキャプションを設定してください", type="warning")
            return
        self.tts_generating_index = index
        self.refresh_messages()
        try:

            def _save_playback(audio: bytes, job) -> dict[str, str]:
                playback_path = playback_save(audio)
                return {
                    "playback_path": str(playback_path),
                    "result_url": self._result_url(),
                }

            job = self.ctx.tts.start_synthesize_job(
                target_id,
                voice_path,
                text,
                endpoint_id=settings.endpoint_id,
                voice_id=settings.voice_id,
                filename=voice.original_name if voice else "",
                content_type=voice.content_type if voice else "",
                api_type=settings.api_type,
                gen_server_tts_mode=settings.gen_server_tts_mode,
                voice_caption=settings.voice_caption,
                gen_server_params=settings.gen_server_params,
                label="チャット読み上げ",
                scope=f"tts:{self.active_session_id or 'none'}",
                metadata={"message_index": index, "character_id": self.sheet.id},
                result_handler=_save_playback,
            )
            finished = await self.ctx.ai_jobs.wait(job.id)
            if finished.status == AIJobStatus.CANCELLED:
                ui.notify("読み上げを停止しました", type="info")
                return
            if finished.status != AIJobStatus.SUCCEEDED:
                ui.notify(f"読み上げに失敗しました: {finished.error_message}", type="negative", timeout=10000)
                return
            playback_path = finished.result_meta.get("playback_path")
            if not playback_path:
                ui.notify("読み上げ音声を取得できませんでした", type="negative")
                return
            audio_url = app.add_static_file(local_file=playback_path, max_cache_age=0)
            self.run_page_javascript(
                f"(() => {{const audio = new Audio({json.dumps(audio_url)});audio.play().catch(() => {{}});}})();"
            )
        except TTSServiceError as err:
            ui.notify(f"読み上げに失敗しました: {err}", type="negative", timeout=10000)
        except Exception as err:
            ui.notify(f"読み上げに失敗しました: {err}", type="negative", timeout=10000)
        finally:
            self.tts_generating_index = None
            self.refresh_messages()

    # ------------------------------------------------------------------
    # 投稿・ターン実行
    # ------------------------------------------------------------------

    async def post_narration(self, text: str) -> None:
        self.messages.append(ChatMessagePreview("narration", text, time_label()))
        self.refresh_messages(scroll_to_bottom=True)
        await self.save_current_session()

    async def post_memo(self, text: str) -> None:
        self.messages.append(ChatMessagePreview("memo", text, time_label()))
        self.refresh_messages(scroll_to_bottom=True)
        await self.save_current_session()

    async def post_character_input(self, text: str) -> None:
        self.messages.append(ChatMessagePreview("character", text, time_label()))
        self.refresh_messages(scroll_to_bottom=True)
        await self.save_current_session()

    async def post_hold_user_text(self, left_text: str) -> None:
        self.clear_input()
        self.messages.append(ChatMessagePreview("user", left_text.strip(), time_label()))
        self.refresh_messages(scroll_to_bottom=True)
        self.set_input_mode("user")
        await self.save_current_session()

    async def append_character_turn(
        self,
        settings: ChatSessionSettings,
        *,
        llm=None,
        turn_instruction: str = "",
        empty_reply: str = "……少し考え込んでしまった。",
    ) -> None:
        llm = llm or self.configured_llm(settings)
        if llm is None:
            return
        if self.active_session_id is None:
            return

        prior_messages = list(self.messages)
        placeholder = ChatMessagePreview("character", "…", time_label())
        self.messages.append(placeholder)
        self.refresh_messages(scroll_to_bottom=True)
        session_id = self.active_session_id
        title = self.title
        title_is_auto = self.active_title_is_auto
        await self.save_current_session(refresh_history=False)

        async def _runner(job) -> list[ChatMessagePreview]:
            try:
                result = await self.ctx.chat_turns.run_character_turn(
                    sheet=self.sheet,
                    settings=settings,
                    messages=prior_messages,
                    llm=llm,
                    turn_instruction=turn_instruction,
                    empty_reply=empty_reply,
                )
                await self._save_session_messages_snapshot(
                    session_id=session_id,
                    title=title,
                    title_is_auto=title_is_auto,
                    settings=settings,
                    messages=result.messages,
                )
                return result.messages
            except Exception:
                await self._save_session_messages_snapshot(
                    session_id=session_id,
                    title=title,
                    title_is_auto=title_is_auto,
                    settings=settings,
                    messages=prior_messages,
                )
                raise

        job = self.ctx.ai_jobs.start_job(
            kind=AIJobKind.LLM_CHAT,
            label=f"{self.sheet.name or 'キャラクター'}の返答生成",
            scope=self._active_chat_scope(),
            metadata={"session_id": session_id, "character_id": self.sheet.id},
            runner=_runner,
        )
        self.ctx.ai_jobs.set_result_meta(job.id, {"result_url": self._result_url()})
        generated_successfully = await self._wait_for_active_chat_job(
            job.id,
            failure_message="チャット送信に失敗しました",
        )
        if generated_successfully:
            await self.maybe_generate_auto_title(llm, settings)

    async def send_user_turn(self, text: str) -> None:
        settings = self.settings
        if self.active_session_id is None or settings is None:
            ui.notify("先に「新しいセッション」を作成してください", type="warning")
            self.open_new_chat_dialog()
            return
        llm = self.configured_llm(settings)
        if llm is None:
            return
        self.clear_input()
        self.messages.append(ChatMessagePreview("user", text, time_label()))
        await self.append_character_turn(settings, llm=llm)

    async def generate_scene(self, settings: ChatSessionSettings, *, instruction: str = "") -> None:
        llm = self.configured_llm(settings)
        if llm is None:
            return
        if self.active_session_id is None:
            return

        prior_messages = list(self.messages)
        self.messages.append(ChatMessagePreview("narration", "…", time_label()))
        self.refresh_messages(scroll_to_bottom=True)
        session_id = self.active_session_id
        title = self.title
        title_is_auto = self.active_title_is_auto
        await self.save_current_session(refresh_history=False)

        async def _runner(job) -> list[ChatMessagePreview]:
            try:
                result = await self.ctx.chat_turns.run_narration_turn(
                    sheet=self.sheet,
                    settings=settings,
                    messages=prior_messages,
                    llm=llm,
                    instruction=instruction,
                )
                await self._save_session_messages_snapshot(
                    session_id=session_id,
                    title=title,
                    title_is_auto=title_is_auto,
                    settings=settings,
                    messages=result.messages,
                )
                return result.messages
            except Exception:
                await self._save_session_messages_snapshot(
                    session_id=session_id,
                    title=title,
                    title_is_auto=title_is_auto,
                    settings=settings,
                    messages=prior_messages,
                )
                raise

        job = self.ctx.ai_jobs.start_job(
            kind=AIJobKind.LLM_NARRATION,
            label="地の文生成",
            scope=self._active_chat_scope(),
            metadata={"session_id": session_id, "character_id": self.sheet.id},
            runner=_runner,
        )
        self.ctx.ai_jobs.set_result_meta(job.id, {"result_url": self._result_url()})
        await self._wait_for_active_chat_job(job.id, failure_message="地の文生成に失敗しました")

    async def regenerate_character_message(self, index: int) -> None:
        if self.sending:
            ui.notify("生成中は再生成できません", type="warning")
            return
        settings = self.settings
        if settings is None:
            ui.notify("先に「新しいセッション」を作成してください", type="warning")
            self.open_new_chat_dialog()
            return
        if index < 0 or index >= len(self.messages):
            return
        if self.messages[index].speaker != "character":
            return
        llm = self.configured_llm(settings)
        if llm is None:
            return
        if self.active_session_id is None:
            return

        original_messages = list(self.messages)
        prior_messages = self.messages[:index]
        was_latest = index == len(original_messages) - 1
        self.messages = prior_messages + [ChatMessagePreview("character", "…", time_label())]
        self.refresh_messages()
        session_id = self.active_session_id
        title = self.title
        title_is_auto = self.active_title_is_auto
        await self.save_current_session(refresh_history=False)

        async def _runner(job) -> list[ChatMessagePreview]:
            try:
                result = await self.ctx.chat_turns.run_character_turn(
                    sheet=self.sheet,
                    settings=settings,
                    messages=prior_messages,
                    llm=llm,
                    empty_reply="……ごめん、うまく言葉にできなかった。",
                    first_turn_empty_reply="こんにちは。少し話そう。",
                )
                await self._save_session_messages_snapshot(
                    session_id=session_id,
                    title=title,
                    title_is_auto=title_is_auto,
                    settings=settings,
                    messages=result.messages,
                )
                return result.messages
            except Exception:
                await self._save_session_messages_snapshot(
                    session_id=session_id,
                    title=title,
                    title_is_auto=title_is_auto,
                    settings=settings,
                    messages=original_messages if was_latest else prior_messages,
                )
                raise

        job = self.ctx.ai_jobs.start_job(
            kind=AIJobKind.LLM_CHAT,
            label=f"{self.sheet.name or 'キャラクター'}の再生成",
            scope=self._active_chat_scope(),
            metadata={"session_id": session_id, "character_id": self.sheet.id},
            runner=_runner,
        )
        self.ctx.ai_jobs.set_result_meta(job.id, {"result_url": self._result_url()})
        generated_successfully = await self._wait_for_active_chat_job(
            job.id,
            failure_message="再生成に失敗しました",
        )
        if generated_successfully:
            await self.maybe_generate_auto_title(llm, settings)

    async def confirm_or_regenerate_character_message(self, index: int) -> None:
        if self.sending:
            ui.notify("生成中は再生成できません", type="warning")
            return
        if index < 0 or index >= len(self.messages):
            return
        if self.messages[index].speaker != "character":
            return
        if index == len(self.messages) - 1:
            await self.regenerate_character_message(index)
            return
        with ui.dialog() as dlg, ui.card().classes("w-full max-w-sm").style(_DIALOG_CARD_STYLE):
            ui.label("この台詞から再生成しますか？").classes("text-base font-semibold")
            ui.label("この台詞以降の会話を削除してから、新しい台詞を生成します。").classes("note")
            ui.label(self.messages[index].text).classes("text-sm").style(
                "white-space: pre-wrap; overflow-wrap: anywhere;"
            )

            async def _do_regenerate() -> None:
                dlg.close()
                await self.regenerate_character_message(index)

            with ui.row().classes("justify-end gap-2 mt-4 w-full"):
                _p3_button("キャンセル", dlg.close, classes="btn quiet")
                _p3_button("再生成", _do_regenerate, classes="btn primary")
        dlg.open()

    # ------------------------------------------------------------------
    # 入力アシスト(補完・整え・選択肢・誘導・描写)
    # ------------------------------------------------------------------

    async def run_describe_action(
        self,
        settings: ChatSessionSettings,
        left_text: str,
        *,
        instruction: str = "",
    ) -> None:
        if left_text.strip():
            await self.post_command_left_text(left_text)
        else:
            self.clear_input()
        self.set_input_mode("user")
        self.clear_input()
        try:
            await self.generate_scene(settings, instruction=instruction)
        finally:
            self.clear_input()

    async def fill_user_text(self, settings: ChatSessionSettings, left_text: str) -> None:
        if not left_text.strip():
            ui.notify("補完する文を /fill の左側に入力してください", type="warning")
            return
        llm = self.configured_llm(settings)
        if llm is None:
            return
        completed = await self._await_llm_assist_result(
            self.ctx.chat_assist.complete_input_text(
                llm=llm,
                sheet=self.sheet,
                settings=settings,
                messages=self.messages,
                left_text=left_text,
                input_mode=self.input_mode,
                scope=self._solo_assist_scope(),
                metadata=self._solo_assist_metadata(),
                result_url=self._result_url(),
            ),
            failure_message="補完に失敗しました",
        )
        if completed is None:
            return
        self.set_input_value(str(completed))
        ui.notify("続きを補完しました", type="positive")
        self.focus_chat_input_at_end()

    async def tailor_input_text(self, settings: ChatSessionSettings, left_text: str) -> None:
        if not left_text.strip():
            ui.notify("書き換える文を /tailor の左側に入力してください", type="warning")
            return
        llm = self.configured_llm(settings)
        if llm is None:
            return
        tailored = await self._await_llm_assist_result(
            self.ctx.chat_assist.tailor_input_text(
                llm=llm,
                sheet=self.sheet,
                settings=settings,
                messages=self.messages,
                left_text=left_text,
                input_mode=self.input_mode,
                scope=self._solo_assist_scope(),
                metadata=self._solo_assist_metadata(),
                result_url=self._result_url(),
            ),
            failure_message="書き換えに失敗しました",
        )
        if tailored is None:
            return
        if not tailored:
            ui.notify("書き換え結果が空でした", type="warning")
            return
        self.set_input_value(str(tailored))
        ui.notify("現在のロール向けに書き換えました", type="positive")
        self.focus_chat_input_at_end()

    async def show_response_choices(self, settings: ChatSessionSettings, left_text: str) -> None:
        llm = self.configured_llm(settings)
        if llm is None:
            return
        input_mode = self.input_mode
        choices = await self._await_llm_assist_result(
            self.ctx.chat_assist.generate_response_choices(
                llm=llm,
                sheet=self.sheet,
                settings=settings,
                messages=self.messages,
                left_text=left_text,
                input_mode=input_mode,
                scope=self._solo_assist_scope(),
                metadata=self._solo_assist_metadata(),
                result_url=self._result_url(),
            ),
            failure_message="選択肢生成に失敗しました",
        )
        if choices is None:
            return
        choices = list(choices or [])
        if not choices:
            ui.notify("選択肢を生成できませんでした", type="warning")
            return

        with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg p3-choice-dialog").style(_DIALOG_CARD_STYLE):
            ui.label("応答を選択").classes("text-base font-semibold")
            target_label = message_target_label(input_mode)
            ui.label(f"選ぶとその{target_label}を入力欄に入れます。").classes("note")

            def _choose(choice: str) -> None:
                dlg.close()
                self.set_input_value(choice)
                self.focus_chat_input_at_end()

            with ui.column().classes("w-full gap-2 mt-2"):
                for index, choice in enumerate(choices[:3]):
                    classes = "p3-choice-option"
                    if index == 0:
                        classes += " p3-choice-option-active"
                    option = (
                        ui.element("button")
                        .props(
                            f"type=button data-choice-index={index} "
                            f"aria-selected={'true' if index == 0 else 'false'}"
                        )
                        .classes(classes)
                    )
                    with option:
                        ui.html(_inline_html(choice))
                    option.on("click", lambda c=choice: _choose(c))
            with ui.row().classes("justify-end mt-2 w-full"):
                _p3_button("閉じる", dlg.close, classes="btn quiet p3-choice-close").props(
                    "data-choice-index=close aria-selected=false"
                )
        dlg.open()
        self.run_page_javascript(_CHOICES_KEYBOARD_JS)

    async def post_command_left_text(self, left_text: str) -> None:
        text = left_text.strip()
        if not text:
            return
        self.clear_input()
        if self.input_mode == "narration":
            self.messages.append(ChatMessagePreview("narration", text, time_label()))
            self.set_input_mode("user")
        elif self.input_mode == "character":
            self.messages.append(ChatMessagePreview("character", text, time_label()))
            self.set_input_mode("user")
        elif self.input_mode == "memo":
            self.messages.append(ChatMessagePreview("memo", text, time_label()))
            self.set_input_mode("user")
        else:
            self.messages.append(ChatMessagePreview("user", text, time_label()))
        self.refresh_messages(scroll_to_bottom=True)
        await self.save_current_session()

    async def open_guide_next_turn_dialog(self, settings: ChatSessionSettings, left_text: str = "") -> None:
        if left_text.strip():
            self.set_input_value(left_text)
        else:
            self.clear_input()

        target_options = {
            "character": "キャラ",
            "narration": "地の文",
            "user": "ユーザー",
        }

        with ui.dialog() as dlg, ui.card().classes("w-full max-w-xl").style(_DIALOG_CARD_STYLE):
            ui.label("次の行動").classes("text-base font-semibold")
            target_select = (
                ui.select(options=target_options, value="character", label="行動者")
                .props("outlined autofocus")
                .classes("w-full")
            )
            direction_input = (
                ui.textarea(label="指示", placeholder="キャラまたは地の文にだけ反映する任意の指示")
                .props("outlined rows=4 autogrow")
                .classes("w-full p3-ta")
            )

            def _sync_direction_input() -> None:
                if target_select.value == "user":
                    direction_input.set_value("")
                    direction_input.disable()
                    return
                direction_input.enable()

            target_select.on_value_change(lambda _: _sync_direction_input())

            async def _run_directed_turn() -> None:
                direction = (direction_input.value or "").strip()
                target = target_select.value or "character"
                dlg.close()
                if target == "user":
                    if left_text.strip():
                        await self.post_hold_user_text(left_text)
                    else:
                        self.clear_input()
                        self.set_input_mode("user")
                    return
                if target == "narration":
                    await self.run_describe_action(settings, left_text, instruction=direction)
                    return
                if not direction:
                    await self.send_message(True, left_text)
                    return
                if left_text.strip():
                    await self.post_command_left_text(left_text)
                else:
                    self.clear_input()
                await self.append_character_turn(settings, turn_instruction=direction)

            with ui.row().classes("justify-end gap-2 mt-4 w-full"):
                _p3_button("キャンセル", dlg.close, classes="btn quiet")
                _p3_button("実行", _run_directed_turn, classes="btn primary")
        dlg.open()

    async def execute_chat_command(self, settings: ChatSessionSettings, left_text: str, query: str) -> None:
        command = resolve_chat_command(query)
        if command is None:
            ui.notify("実行するコマンドを選択してください", type="warning")
            return

        left_text = left_text.rstrip()
        if command == "hold":
            if not left_text.strip():
                ui.notify("/hold の左側に投稿する文を入力してください", type="warning")
                return
            await self.post_hold_user_text(left_text)
            return
        if command == "guide":
            await self.open_guide_next_turn_dialog(settings, left_text)
            return
        if command == "fill":
            self.set_input_value(left_text)
            await self.fill_user_text(settings, left_text)
            return
        if command == "tailor":
            self.set_input_value(left_text)
            await self.tailor_input_text(settings, left_text)
            return
        if command == "choices":
            self.set_input_value(left_text)
            await self.show_response_choices(settings, left_text)
            return
        if command == "skip":
            if left_text.strip():
                ui.notify("/skip は単独で入力してください", type="warning")
                return
            self.clear_input()
            await self.append_character_turn(settings)
            return
        if command == "narrate":
            self.set_input_value(left_text)
            self.set_input_mode("narration", notify_change=True)
            return
        if command == "memo":
            self.set_input_value(left_text)
            self.set_input_mode("memo", notify_change=True)
            return
        if command == "imitate":
            self.set_input_value(left_text)
            self.set_input_mode("character", notify_change=True)
            return
        if command == "user":
            self.set_input_value(left_text)
            self.set_input_mode("user", notify_change=True)
            return
        if command == "describe":
            await self.run_describe_action(settings, left_text)
            return

    async def send_message(
        self,
        allow_skip: bool = False,
        submitted_text: str | None = None,
    ) -> None:
        if self.sending:
            return
        settings = self.settings
        if settings is None:
            if await self.quick_start_session():
                settings = self.settings
            if settings is None:
                ui.notify("先に「新しいセッション」を作成してください", type="warning")
                self.open_new_chat_dialog()
                return

        raw_text = (
            submitted_text
            if submitted_text is not None
            else (self.input.value if self.input is not None else "")
        )
        parsed_command = parse_command_input(raw_text or "", allow_empty_query=False)
        if parsed_command is not None:
            left_text, query = parsed_command
            await self.execute_chat_command(settings, left_text, query)
            return

        text = (raw_text or "").strip()
        if not text:
            if not allow_skip:
                ui.notify("メッセージを入力してください", type="warning")
                return
            await self.append_character_turn(settings)
            return

        if self.input_mode == "narration":
            self.clear_input()
            await self.post_narration(text)
            self.set_input_mode("user")
            return
        if self.input_mode == "memo":
            self.clear_input()
            await self.post_memo(text)
            self.set_input_mode("user")
            return
        if self.input_mode == "character":
            self.clear_input()
            await self.post_character_input(text)
            self.set_input_mode("user")
            return
        await self.send_user_turn(text)

    # ------------------------------------------------------------------
    # セッション開始(ダイアログ+クイック開始)
    # ------------------------------------------------------------------

    async def quick_start_session(self) -> bool:
        """既定のプロファイル・モード・ペルソナが揃っていれば黙ってセッションを作る。

        (モックの「下の入力から、そのまま話しかけられます」を成立させるための
        クイック開始。揃っていなければ False を返し、呼び出し側がダイアログへ誘導)
        """
        ctx = self.ctx
        profile_options = profile_options_for_context(ctx)
        profile_id = default_profile_id(ctx, profile_options)
        if not profile_id or not profile_is_startable(ctx, profile_id):
            return False
        mode_options = {mode.id: mode.name for mode in ctx.api_config.get_chat_modes()}
        mode_id = default_chat_mode_id(mode_options)
        mode = ctx.api_config.get_chat_mode(mode_id) if mode_id else None
        if mode is None:
            return False
        personas = ctx.user_personas.get_user_personas()
        persona = personas[0] if personas else None
        if persona is None or not persona.description.strip():
            return False
        try:
            premise, situation = render_mode_for_sheet(mode, self.sheet, persona)
        except TemplateError:
            return False
        if not situation.strip():
            return False
        settings = ChatSessionSettings(
            profile_id=profile_id,
            chat_mode_id=mode.id,
            chat_mode_name=mode.name,
            chat_premise=premise,
            situation=situation.strip(),
            user_persona_id=persona.id,
            user_persona_name=persona.name,
            user_persona_description=persona.description.strip(),
            user_persona_source=USER_PERSONA_SOURCE_PERSONA,
        )
        await self.start_chat_session(settings, "")
        return True

    async def start_chat_session(self, settings: ChatSessionSettings, title: str = "") -> None:
        title = title.strip()
        title_is_auto = not title
        self.settings = settings
        self.title = title or DEFAULT_CHAT_TITLE
        self.messages = []
        self.input_mode = "user"
        await self.refresh_user_persona_media()
        self.active_title_is_auto = title_is_auto
        self.title_generation_attempted = False
        if self.input is not None:
            self.input.set_value("")
        if settings.situation.strip():
            self.messages.append(ChatMessagePreview("narration", settings.situation.strip(), time_label()))
        saved = await self.ctx.chats.create_session(
            character_id=self.sheet.id,
            title=self.title,
            title_is_auto=title_is_auto,
            settings=chat_settings_to_dict(settings),
            messages=[chat_message_to_dict(message) for message in self.messages],
        )
        self.active_session_id = saved.id
        self.sessions_by_id[saved.id] = saved
        await self.reload_sessions()
        self.refresh_input_mode_chip()
        self.refresh_chat_header()
        self.refresh_scene()
        self.refresh_messages(scroll_to_bottom=True)
        self.refresh_sessions_pane()

    async def enhance_situation(
        self,
        profile_id: str,
        mode: ChatMode,
        persona: UserPersona,
        premise: str,
        current_situation: str,
    ) -> str | None:
        llm = configured_llm_for_profile(self.ctx, profile_id)
        if llm is None:
            return None
        enhanced = await self._await_llm_assist_result(
            self.ctx.chat_assist.enhance_situation(
                llm=llm,
                sheet=self.sheet,
                mode=mode,
                persona=persona,
                premise=premise,
                current_situation=current_situation,
                scope=self._solo_assist_scope(),
                metadata=self._solo_assist_metadata(),
                result_url=self._result_url(),
            ),
            failure_message="シチュエーション補完に失敗しました",
        )
        if enhanced is None:
            return None
        if not enhanced:
            ui.notify("シチュエーションを補完できませんでした", type="warning")
            return None
        ui.notify("シチュエーションを補完しました", type="positive")
        return str(enhanced)

    async def _pick_character_persona(self, on_select) -> None:
        await open_character_pick_dialog(
            self.ctx,
            title="ユーザー役にするキャラクターを選択",
            exclude_ids=set(),
            on_select=on_select,
        )

    def open_new_chat_dialog(self) -> None:
        ctx = self.ctx
        profile_options = profile_options_for_context(ctx)
        chat_modes = ctx.api_config.get_chat_modes()
        mode_options = {mode.id: mode.name for mode in chat_modes}
        user_personas = ctx.user_personas.get_user_personas()
        persona_options = {persona.id: persona.display_name for persona in user_personas}

        with ui.dialog() as dlg, ui.card().classes("w-full max-w-2xl").style(_DIALOG_CARD_STYLE):
            ui.label("新しいセッション").classes("text-base font-semibold")

            if not profile_options:
                ui.label("LLMプロファイルが登録されていません。設定画面で追加してください。").classes(
                    "text-sm text-negative mt-3"
                )
            if not mode_options:
                ui.label("チャットモードが登録されていません。設定画面で追加してください。").classes(
                    "text-sm text-negative mt-3"
                )
            if not persona_options:
                ui.label(
                    "ユーザーペルソナが登録されていません。キャラクターシートもユーザー役として選択できます。"
                ).classes("text-sm text-negative mt-3")

            profile_select = (
                ui.select(
                    options=profile_options,
                    value=default_profile_id(ctx, profile_options),
                    label="LLMプロファイル",
                )
                .props("outlined")
                .classes("w-full mt-3")
            )
            title_input = (
                ui.input(label="タイトル（任意）", placeholder="未入力なら自動タイトル")
                .props("outlined clearable")
                .classes("w-full")
            )
            mode_select = (
                ui.select(
                    options=mode_options,
                    value=default_chat_mode_id(mode_options),
                    label="チャットモード",
                )
                .props("outlined")
                .classes("w-full")
            )

            persona_select_options = {
                f"{_PERSONA_SELECT_PREFIX}{persona_id}": label for persona_id, label in persona_options.items()
            }
            selected_character_persona: dict[str, CharacterSheet | None] = {"value": None}
            default_pid = default_user_persona_id(persona_options)
            default_persona_value = f"{_PERSONA_SELECT_PREFIX}{default_pid}" if default_pid else None

            async def _pick_character_persona() -> None:
                async def _on_select(character: CharacterSheet) -> None:
                    selected_character_persona["value"] = character
                    value = f"{_CHARACTER_SELECT_PREFIX}{character.id}"
                    persona_select.set_options(
                        {
                            **persona_select_options,
                            value: f"{character.name}（キャラクターシート）",
                        },
                        value=value,
                    )
                    _sync_situation_default(force=True)
                    _refresh_preview()

                await self._pick_character_persona(_on_select)

            with ui.row().classes("w-full items-end gap-2"):
                persona_select = (
                    ui.select(
                        options=persona_select_options,
                        value=default_persona_value,
                        label="ユーザーペルソナ",
                    )
                    .props("outlined")
                    .classes("flex-1 min-w-0")
                )
                _p3_button(
                    "シートから選ぶ",
                    _pick_character_persona,
                    classes="btn quiet",
                    title="キャラクターシートをユーザー役にする",
                )

            def _selected_mode() -> ChatMode | None:
                mode_id = mode_select.value or ""
                return ctx.api_config.get_chat_mode(mode_id) if mode_id else None

            def _selected_persona_source_and_id() -> tuple[str, str]:
                selected = str(persona_select.value or "")
                if selected.startswith(_CHARACTER_SELECT_PREFIX):
                    return USER_PERSONA_SOURCE_CHARACTER, selected[len(_CHARACTER_SELECT_PREFIX):]
                if selected.startswith(_PERSONA_SELECT_PREFIX):
                    return USER_PERSONA_SOURCE_PERSONA, selected[len(_PERSONA_SELECT_PREFIX):]
                if selected in persona_options:
                    return USER_PERSONA_SOURCE_PERSONA, selected
                return "", ""

            def _selected_persona() -> UserPersona | None:
                source, persona_id = _selected_persona_source_and_id()
                if not persona_id:
                    return None
                if source == USER_PERSONA_SOURCE_CHARACTER:
                    character = selected_character_persona["value"]
                    if character is None or character.id != persona_id:
                        return None
                    return user_persona_from_character_sheet(character)
                return ctx.user_personas.get_user_persona(persona_id)

            def _render_selected_mode() -> tuple[str, str]:
                mode = _selected_mode()
                persona = _selected_persona()
                if mode is None or persona is None:
                    return "", ""
                return render_mode_for_sheet(mode, self.sheet, persona)

            def _initial_situation() -> str:
                try:
                    return _render_selected_mode()[1]
                except TemplateError:
                    return ""

            situation_default = {"value": _initial_situation()}
            with ui.element("div").style("position: relative; width: 100%;"):
                situation_input = (
                    ui.textarea(
                        label="シチュエーション",
                        value=situation_default["value"],
                        placeholder="話したい状況や、特筆したいことを記入",
                    )
                    .props("outlined rows=3")
                    .classes("w-full p3-ta")
                )
                enhance_button = _p3_button(
                    "補完",
                    lambda: _enhance_situation(),
                    classes="btn quiet",
                    title="シチュエーションをLLMで補完",
                )
                enhance_button.style("position: absolute; right: 6px; top: 2px;")

            preview_container = ui.column().classes("w-full gap-1")

            def _sync_situation_default(*, force: bool = False) -> None:
                try:
                    next_default = _render_selected_mode()[1]
                except TemplateError:
                    return
                current = (situation_input.value or "").strip()
                previous = situation_default["value"].strip()
                if force or not current or current == previous:
                    situation_input.set_value(next_default)
                situation_default["value"] = next_default

            def _refresh_preview() -> None:
                preview_container.clear()
                mode = _selected_mode()
                persona = _selected_persona()
                with preview_container:
                    if mode is None or persona is None:
                        return
                    try:
                        premise, _ = render_mode_for_sheet(mode, self.sheet, persona)
                    except TemplateError as err:
                        ui.label(f"テンプレートエラー: {err}").classes("text-sm text-negative")
                        return
                    with ui.expansion("前提 / ユーザー設定", icon="tune").props("dense").classes("w-full"):
                        ui.label("前提").classes("text-xs font-semibold").style("color: var(--muted);")
                        ui.label(premise or "（未設定）").classes("text-sm").style(
                            "white-space: pre-wrap; overflow-wrap: anywhere;"
                        )
                        ui.label("ユーザー設定").classes("text-xs font-semibold mt-2").style(
                            "color: var(--muted);"
                        )
                        ui.label(persona.description or "（未設定）").classes("text-sm").style(
                            "white-space: pre-wrap; overflow-wrap: anywhere;"
                        )

            mode_select.on_value_change(lambda _: (_sync_situation_default(force=True), _refresh_preview()))
            persona_select.on_value_change(lambda _: (_sync_situation_default(), _refresh_preview()))
            _refresh_preview()

            async def _enhance_situation() -> None:
                profile_id = profile_select.value or ""
                if not profile_id:
                    ui.notify("LLMプロファイルを選択してください", type="warning")
                    return
                mode = _selected_mode()
                persona = _selected_persona()
                if mode is None:
                    ui.notify("チャットモードを選択してください", type="warning")
                    return
                if persona is None:
                    ui.notify("ユーザー役を選択してください", type="warning")
                    return
                if not persona.description.strip():
                    ui.notify("ユーザー役の設定を入力してください", type="warning")
                    return
                try:
                    premise, rendered_situation = render_mode_for_sheet(mode, self.sheet, persona)
                except TemplateError as err:
                    ui.notify(f"チャットモードのテンプレートを確認してください: {err}", type="negative", timeout=8000)
                    return
                current_situation = (situation_input.value or "").strip() or rendered_situation
                situation_input.disable()
                try:
                    enhanced = await self.enhance_situation(profile_id, mode, persona, premise, current_situation)
                    if enhanced is not None:
                        situation_input.set_value(enhanced)
                finally:
                    situation_input.enable()

            async def _start_chat() -> None:
                profile_id = profile_select.value or ""
                if not profile_id:
                    ui.notify("LLMプロファイルを選択してください", type="warning")
                    return
                if not validate_profile_for_start(ctx, profile_id):
                    return
                mode = _selected_mode()
                if mode is None:
                    ui.notify("チャットモードを選択してください", type="warning")
                    return
                persona = _selected_persona()
                if persona is None:
                    ui.notify("ユーザー役を選択してください", type="warning")
                    return
                if not persona.description.strip():
                    ui.notify("ユーザー役の設定を入力してください", type="warning")
                    return
                try:
                    premise, rendered_situation = render_mode_for_sheet(mode, self.sheet, persona)
                except TemplateError as err:
                    ui.notify(f"チャットモードのテンプレートを確認してください: {err}", type="negative", timeout=8000)
                    return
                situation = (situation_input.value or rendered_situation).strip()
                if not situation:
                    ui.notify("シチュエーションを入力してください", type="warning")
                    return
                settings = ChatSessionSettings(
                    profile_id=profile_id,
                    chat_mode_id=mode.id,
                    chat_mode_name=mode.name,
                    chat_premise=premise,
                    situation=situation,
                    user_persona_id=persona.id,
                    user_persona_name=persona.name,
                    user_persona_description=persona.description.strip(),
                    user_persona_source=_selected_persona_source_and_id()[0] or USER_PERSONA_SOURCE_PERSONA,
                )
                dlg.close()
                await self.start_chat_session(settings, (title_input.value or "").strip())

            with ui.row().classes("justify-end gap-2 mt-4 w-full"):
                _p3_button("キャンセル", dlg.close, classes="btn quiet")
                _p3_button("開始", _start_chat, classes="btn primary").mark("ui2-chat-start")
        dlg.open()


@ui.page("/characters/{character_id}/chat")
async def ui2_chat_page(character_id: str) -> None:
    ctx = get_context()
    sheet = await ctx.characters.get(character_id)

    if sheet is None:
        with p3_page("チャット"):
            with ui.element("div").style("max-width: 640px; margin: 0 auto; padding: 60px 26px;"):
                ui.label("指定されたキャラクターは存在しません。").classes("note").style("font-size: 14px;")
                with ui.element("div").style("margin-top: 18px;"):
                    _p3_button("キャラクター一覧へ", lambda: ui.navigate.to("/characters"))
        return

    all_sheets = await ctx.characters.list_all()
    recent_sessions = await ctx.chats.list_recent(500)
    partners = build_partner_entries(all_sheets, recent_sessions)

    controller = Ui2ChatController(ctx, sheet, ui.context.client, partners)
    await controller.initialize()

    with p3_page("チャット"):
        ui.add_css(_PAGE_CSS + PICKER_CSS + COMPOSER_CSS)
        controller.render_shell()


@ui.page("/chat")
async def ui2_chat_entry_page():
    """ナビ「チャット」の入口: 最後に話した(実在する)相手のチャットへリダイレクト。"""
    ctx = get_context()
    sheets = await ctx.characters.list_all()
    recent = await ctx.chats.list_recent(500)
    # build_partner_entries は「話した相手(新しい順)→未会話」の並びで、
    # 削除済みキャラのセッションはシート突き合わせで自然に除外される。
    partners = build_partner_entries(sheets, recent)
    partner_id = partners[0].sheet.id if partners else ""
    target = f"/characters/{partner_id}/chat" if partner_id else "/characters"
    return RedirectResponse(target)
