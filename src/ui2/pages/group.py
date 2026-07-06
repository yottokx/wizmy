"""
/v2/groups/{id} 箱庭シェル(グループチャット・Phase 4)。モック proposal3/group.html 準拠。

- 描画は P3、編成は旧 `src/ui/group_chat/controller.py` を踏襲(呼ぶ services は全部既存):
  GroupChatService(グループ/セッションCRUD・メディア)/ GroupChatTurnService(話者選択+ターン)/
  GroupChatAssistService(補完・選択肢・シーン・関係性)/ ai_jobs(実行+リロード復帰)/ TTS
- 3ペイン: 左=セッション+シーン / 中央=ストリーム+コンポーザー / 右=presence
  (立ち絵クロスフェード=components/presence.py)+この世界の住人。
- 話者選択は服の下で `choose_next_speaker`(メンション@優先)。「次の話者候補」灯りは
  その決定的分岐を鏡写しにした group_logic.next_speaker_candidate_ids で点灯する。
- コンポーザーは 1:1 と同構成(ロールチップ+アシストチップ+コマンドパレット。
  Phase 3 のユーザー確定に従い、全Phase完了後にグループと合わせて一括調整)。
  加えて @ メンション補完パレットを持つ。
"""

from __future__ import annotations

import html
import json
from typing import Any

from nicegui import app, ui

from ...app_context import get_context
from ...core.character.schemas import (
    CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3,
    CHARACTER_TTS_API_GEN_SERVER,
    CHARACTER_TTS_API_TTS,
    CharacterSheet,
)
from ...core.conversation.group_setup import fallback_handle
from ...core.conversation.history import (
    group_message,
    group_participant_ids,
    group_system_event_message,
    latest_group_message_preview,
    settings_with_participant,
    settings_without_participant,
)
from ...core.conversation.prompts.common import compact_character_summary
from ...core.conversation.prompts.group import (
    build_group_system_prompt,
    group_input_mode_for_role,
    group_participant_labels,
)
from ...core.conversation.relationship_drafts import next_relationship_draft_id
from ...core.conversation.sanitize import clean_guest_name, guest_display_name
from ...core.conversation.world_adaptation import prepare_group_character_for_world
from ...core.group_chat.schemas import GroupChatRecord, GroupMember, GroupRelationship
from ...core.group_chat.sessions import DEFAULT_GROUP_CHAT_TITLE, GroupChatSessionRecord
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
from ...ui.state import get_vault_password
from ..chat_commands import command_suggestions, parse_command_input, resolve_chat_command
from ..components.busy import BusyController
from ..components.portrait import image_object_position, media_url, raw_img
from ..components.presence import PresenceEntry, PresenceStage
from ..group_logic import (
    DIFF_CSS,
    draft_state_from_group,
    entry_type_label,
    group_participants,
    guide_actor_options,
    imitate_actor_options,
    mention_entries,
    next_speaker_candidate_ids,
    participant_by_speaker_id,
    relationship_key_map_for_group,
    validate_handle_values,
    world_source_chip_label,
)
from ..group_logic import (
    active_members as _active_members_of,
)
from ..group_setup import (
    chip_button,
    enhance_relationship_text,
    generate_handles_values,
    notify_setup_llm_error,
    open_character_pick_dialog,
    open_resident_settings_dialog,
    p3_button,
    profile_options_for_context,
    run_assist,
)
from ..scaffold import p3_page

_DIALOG_CARD_STYLE = "background: var(--panel); color: var(--text);"

# モック group.html の <style> 移植+Phase 3 チャットの P3 追補(パレット・メモ・操作列)
_PAGE_CSS = (
    """
/* 高さは固定値の引き算をしない(HANDOFF f項) */
body { height: 100vh; height: 100dvh; overflow: hidden; }
#app, #q-app, .q-layout, .q-page-container, .q-page { height: 100%; min-height: 0 !important; }
.nicegui-content { height: 100%; display: flex; flex-direction: column; min-height: 0; }
.wz-nav, .gband { flex: none; }

/* ---------- 箱庭バンド ---------- */
.gband {
  position: relative;
  display: flex;
  align-items: center;
  gap: 22px;
  padding: 12px 26px;
  border-bottom: 1px solid var(--line);
  background:
    radial-gradient(ellipse 60% 140% at 85% 0%, color-mix(in srgb, var(--peri) 14%, transparent), transparent 70%),
    var(--bg-2);
  overflow: hidden;
}
.gband .gname { font-size: 19px; letter-spacing: .14em; white-space: nowrap; }
.gband .gworld {
  font-size: 12px;
  color: var(--muted);
  line-height: 1.6;
  max-width: 640px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.gband .chips { margin-left: auto; display: flex; gap: 8px; flex: none; }
.gband .chip { cursor: default; background: color-mix(in srgb, var(--bg) 55%, transparent); }
.gband .chip.manage { cursor: pointer; color: var(--accent); border-color: color-mix(in srgb, var(--accent) 55%, transparent); }
.gband .back {
  flex: none;
  width: 32px; height: 32px;
  display: grid; place-items: center;
  border-radius: 50%;
  border: 1px solid var(--line-2);
  color: var(--muted);
  font-size: 15px;
  cursor: pointer;
  background: transparent;
  transition: color .18s, border-color .18s;
}
.gband .back:hover { color: var(--text); border-color: var(--muted); }

.shell {
  display: grid;
  grid-template-columns: 232px minmax(0, 1fr) 330px;
  flex: 1;
  min-height: 0;
}

/* ---------- 左:このグループのセッション ---------- */
.sessions {
  border-right: 1px solid var(--line);
  padding: 20px 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  overflow-y: auto;
  min-height: 0;
}
.sessions .lbl { font-size: 11px; letter-spacing: .3em; color: var(--muted); padding: 0 8px 8px; }
.sess { position: relative; padding: 10px 12px; border-radius: 12px; cursor: pointer; border: 1px solid transparent; }
.sess:hover { background: var(--panel); }
.sess.on { background: var(--panel); border-color: var(--line-2); }
.sess .t { font-size: 13.5px; font-weight: 600; letter-spacing: .03em; line-height: 1.5; padding-right: 30px; }
.sess .s { font-size: 11.5px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sess .sess-ops {
  position: absolute; top: 8px; right: 8px;
  display: flex; gap: 4px;
  opacity: 0; transition: opacity .18s;
}
.sess:hover .sess-ops { opacity: 1; }
.sess-ops button {
  border: none; background: var(--panel-2); color: var(--muted);
  border-radius: 8px; padding: 2px 8px; font-size: 11px; cursor: pointer;
}
.sess-ops button:hover { color: var(--text); }
.no-sess { padding: 10px 12px; font-size: 12px; color: var(--muted); line-height: 1.7; }
.scene {
  margin-top: auto;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 12px 14px;
}
.scene .lbl2 { font-size: 10.5px; letter-spacing: .26em; color: var(--peri); margin-bottom: 4px; }
.scene .tx {
  font-size: 12.5px; color: var(--muted); line-height: 1.6;
  display: -webkit-box; -webkit-line-clamp: 5; -webkit-box-orient: vertical; overflow: hidden;
}
.scene .edit { font-size: 11.5px; color: var(--accent); margin-top: 6px; cursor: pointer; }

/* ---------- 中央:ストリーム ---------- */
.stream-wrap { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.stream-head {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 26px;
  border-bottom: 1px solid var(--line);
}
.stream-head .t { font-size: 15px; font-weight: 600; letter-spacing: .08em; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.stream-head .w { font-size: 11.5px; color: var(--muted); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.stream-head .sp { flex: 1; }

.stream { flex: 1; min-height: 0; overflow-y: auto; padding: 30px 34px 20px; }
.stream-inner { max-width: 760px; margin: 0 auto; display: flex; flex-direction: column; gap: 26px; }

.narr-wrap { text-align: center; }
.narr {
  color: var(--muted);
  font-size: 13.5px;
  letter-spacing: .08em;
  font-family: "Yu Mincho", "Hiragino Mincho ProN", serif;
}
.narr::before { content: "— "; }
.narr::after { content: " —"; }
.narr-wrap .ops { display: flex; gap: 4px; justify-content: center; margin-top: 6px; opacity: 0; transition: opacity .18s; }
.narr-wrap:hover .ops { opacity: 1; }

.sysmsg { text-align: center; font-size: 11.5px; color: var(--peri); letter-spacing: .18em; }

.memo {
  max-width: 560px; margin: 0 auto; width: fit-content;
  border: 1px dashed var(--line-2); border-radius: 14px;
  padding: 10px 18px;
  color: var(--muted); font-size: 13px; line-height: 1.7;
  white-space: pre-wrap; overflow-wrap: anywhere;
}
.memo .memo-k { font-size: 10.5px; letter-spacing: .24em; color: var(--peri); margin-bottom: 2px; }
.memo .ops { display: flex; gap: 4px; margin-top: 6px; opacity: 0; transition: opacity .18s; }
.memo:hover .ops { opacity: 1; }

.msg { display: flex; gap: 14px; align-items: flex-start; }
.msg .avatar { width: 44px; height: 44px; object-fit: cover; flex: none; cursor: pointer; }
.msg .avatar-ph {
  width: 44px; height: 44px; border-radius: 50%; flex: none;
  display: grid; place-items: center;
  background: var(--panel-2); color: var(--peri);
  font-family: "Yu Mincho", serif; font-size: 17px;
  border: 2px solid var(--line-2);
}
.msg .body { min-width: 0; }
.msg .who { font-size: 12.5px; letter-spacing: .16em; color: var(--peri); margin: 2px 0 6px; }
.msg .who .hd { color: var(--muted); letter-spacing: .04em; font-size: 11px; }
.msg .bubble { padding: 12px 18px; font-size: 15px; border-top-left-radius: 6px; white-space: pre-wrap; overflow-wrap: anywhere; }
.msg .ops { display: flex; gap: 4px; margin-top: 6px; opacity: 0; transition: opacity .18s; align-items: center; }
.msg:hover .ops { opacity: 1; }
.msg.user { flex-direction: row-reverse; }
.msg.user .bubble { background: var(--bubble-user); border-top-left-radius: 18px; border-top-right-radius: 6px; }
.msg.user .who { text-align: right; color: var(--muted); }
.msg.user .ops { justify-content: flex-end; }
.ops .btn.quiet { padding: 2px 10px; font-size: 11.5px; }
.ops .tm { font-size: 11px; color: var(--muted); }

.empty-stream { padding-top: 8vh; text-align: center; }
.empty-stream .hello { color: var(--peri); font-size: 11px; letter-spacing: .34em; margin-bottom: 18px; }

/* ---------- コンポーザー ---------- */
.composer { padding: 14px 34px 20px; border-top: 1px solid var(--line); }
.composer-inner { max-width: 760px; margin: 0 auto; }
.comp-tools { display: flex; gap: 8px; margin-bottom: 10px; align-items: center; }
.comp-row { display: flex; gap: 12px; align-items: flex-end; }
.comp-input { flex: 1; }
.comp-input .q-field__control {
  background: var(--panel);
  border: 1px solid var(--line-2);
  border-radius: 20px;
  padding: 6px 20px;
  min-height: 52px;
  color: var(--text);
}
.comp-input .q-field__control:before, .comp-input .q-field__control:after { display: none; }
.comp-input textarea { color: var(--text) !important; font-size: 15px; line-height: 1.6; }
.comp-send[disabled] { opacity: .5; pointer-events: none; }

/* コマンドパレット(1:1 と同じ P3 トーン) */
.p3-cmd-palette {
  background: var(--panel);
  border: 1px solid var(--line-2);
  border-radius: 14px;
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
  text-align: left; padding: 7px 12px; border-radius: 10px; cursor: pointer;
}
.p3-cmd-option:hover, .p3-cmd-option-active { background: var(--panel-2); }
.p3-cmd-name { font-size: 13px; color: var(--accent); font-weight: 600; flex: none; }
.p3-cmd-desc { font-size: 12px; color: var(--muted); }

/* メンションパレット(@) */
.p3-mention-palette {
  background: var(--panel);
  border: 1px solid var(--line-2);
  border-radius: 14px;
  box-shadow: var(--shadow);
  margin-bottom: 10px;
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 240px;
  overflow-y: auto;
}
.p3-mention-palette.hidden { display: none; }
.p3-mention-option {
  display: flex; gap: 10px; align-items: center;
  border: none; background: none; color: var(--text);
  text-align: left; padding: 6px 12px; border-radius: 10px; cursor: pointer;
}
.p3-mention-option:hover, .p3-mention-option-active { background: var(--panel-2); }
.p3-mention-option.p3-mention-option-hidden { display: none; }
.p3-mention-option img, .p3-mention-option .m-ph {
  width: 30px; height: 30px; border-radius: 50%; object-fit: cover; flex: none;
}
.p3-mention-option .m-ph {
  display: grid; place-items: center;
  background: var(--panel-2); color: var(--peri); font-size: 13px;
}
.p3-mention-name { font-size: 13px; }
.p3-mention-handle { font-size: 11.5px; color: var(--accent); }
.p3-mention-kind { margin-left: auto; font-size: 10.5px; color: var(--muted); letter-spacing: .08em; }

/* 選択肢ダイアログ(/choices) */
.p3-choice-option {
  display: block; width: 100%; text-align: left;
  border: 1px solid var(--line-2); background: var(--panel-2); color: var(--text);
  border-radius: 12px; padding: 10px 14px; cursor: pointer;
  font-size: 13.5px; line-height: 1.6;
}
.p3-choice-option-active { border-color: var(--accent); box-shadow: 0 0 0 2px var(--glow); }

/* ---------- 右:presence+住人 ---------- */
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
  opacity: 0;
  transition: opacity .5s;
  -webkit-mask-image: linear-gradient(to top, transparent 2%, #000 30%);
  mask-image: linear-gradient(to top, transparent 2%, #000 30%);
}
.presence .portrait img.on { opacity: 1; }
.presence .pname {
  position: absolute; left: 20px; bottom: 14px; z-index: 2;
  font-size: 18px; letter-spacing: .12em;
}
.presence .pocc {
  position: absolute; left: 20px; bottom: 2px; z-index: 2;
  font-size: 11px; color: var(--muted); letter-spacing: .04em;
}
.cast { padding: 16px 14px 14px; border-top: 1px solid var(--line); max-height: 55%; overflow-y: auto; flex: none; }
.cast .lbl { font-size: 10.5px; letter-spacing: .3em; color: var(--muted); margin: 0 4px 10px; }
.member {
  position: relative;
  display: flex; align-items: center; gap: 11px;
  padding: 7px 10px;
  border-radius: 12px;
  cursor: pointer;
  border: 1px solid transparent;
  width: 100%;
  background: none;
  color: var(--text);
  text-align: left;
}
.member:hover { background: var(--panel); }
.member.on { background: var(--panel); border-color: var(--line-2); }
.member .avatar { width: 38px; height: 38px; flex: none; }
.member .avatar-ph {
  width: 38px; height: 38px; border-radius: 50%; flex: none;
  display: grid; place-items: center;
  background: var(--panel-2); color: var(--peri); font-size: 15px;
  border: 2px solid var(--line-2);
}
.member .mi { min-width: 0; }
.member .nm { font-size: 13px; letter-spacing: .04em; }
.member .st { font-size: 10.5px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.member .dot { margin-left: auto; width: 7px; height: 7px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 8px var(--glow); flex: none; }
.member .open-btn {
  position: absolute; right: 8px; top: 50%; transform: translateY(-50%);
  opacity: 0; transition: opacity .18s;
  border: 1px solid var(--line-2); background: var(--panel-2); color: var(--muted);
  border-radius: 8px; padding: 2px 9px; font-size: 11px; cursor: pointer;
}
.member:hover .open-btn { opacity: 1; }
.member .open-btn:hover { color: var(--text); }
.tag {
  display: inline-block;
  font-size: 9.5px;
  color: var(--peri);
  border: 1px solid color-mix(in srgb, var(--peri) 45%, transparent);
  border-radius: 6px;
  padding: 0 6px;
  margin-left: 6px;
  vertical-align: 1px;
  letter-spacing: .08em;
}
.member.you { border-top: 1px dashed var(--line-2); border-radius: 0 0 12px 12px; margin-top: 6px; padding-top: 12px; }
.member.you .nm { color: var(--muted); }
.add-row { display: flex; gap: 6px; margin-top: 10px; flex-wrap: wrap; }
.add-row .btn { padding: 5px 12px; font-size: 11.5px; }

/* ダイアログ・メニューのP3スキン */
.q-menu { background: var(--panel); color: var(--text); }
.p3-ta { width: 100%; }
.p3-ta .q-field__control { background: var(--bg-2) !important; border-radius: 12px; }
.p3-ta .q-field__control:before { border-color: var(--line-2) !important; }
.p3-ta textarea, .p3-ta input { color: var(--text) !important; line-height: 1.8; }

/* 関係性(管理ダイアログ) */
.rel-row { border: 1px solid var(--line); border-radius: 12px; padding: 10px 14px; }
.rel-row .pair { font-size: 12.5px; font-weight: 600; letter-spacing: .04em; }
.rel-row .tx { font-size: 12.5px; color: var(--muted); line-height: 1.7; margin-top: 4px; white-space: pre-wrap; }
.rel-head { display: flex; align-items: center; gap: 6px; }
.rel-head .sp { flex: 1; }

/* ピッカー(pcard) */
.pgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 14px; }
.pcard {
  position: relative;
  aspect-ratio: 3 / 4;
  border-radius: 16px;
  overflow: hidden;
  cursor: pointer;
  background: var(--panel);
  border: 1px solid var(--line);
  transition: transform .18s, border-color .18s, box-shadow .18s;
}
.pcard:hover { transform: translateY(-4px); border-color: var(--accent); box-shadow: var(--shadow); }
.pcard img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
.pcard .p-ph {
  position: absolute; inset: 0;
  display: grid; place-items: center;
  color: var(--peri); font-size: 44px; font-family: "Yu Mincho", serif;
  background: var(--panel-2);
}
.pcard .veil { position: absolute; inset: 0; background: linear-gradient(to top, rgba(7,9,26,.9), transparent 52%); }
.pcard .info { position: absolute; left: 12px; right: 12px; bottom: 10px; color: #f4f5ff; }
.pcard .nm { font-size: 13.5px; letter-spacing: .06em; line-height: 1.4; }
.pcard .st { font-size: 10.5px; opacity: .8; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.picks { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.pick {
  display: inline-flex; align-items: center; gap: 8px;
  border: 1px solid var(--line-2);
  border-radius: 999px;
  padding: 4px 14px 4px 5px;
  font-size: 12.5px;
  cursor: pointer;
  background: transparent;
  color: var(--text);
}
.pick:hover { border-color: var(--accent); }
.pick img { width: 28px; height: 28px; border-radius: 50%; object-fit: cover; }
.pick .pick-ph {
  width: 28px; height: 28px; border-radius: 50%;
  display: grid; place-items: center;
  background: var(--panel-2); color: var(--peri); font-size: 13px;
}
.pick .st { color: var(--peri); font-size: 10px; letter-spacing: .08em; }
.pick .x { color: var(--muted); cursor: pointer; margin-left: 2px; }
.pick .x:hover { color: var(--text); }

/* 履歴ボタン・キャストバー(モバイル用) */
.hist-btn { display: none; }
.sess-close { display: none; }
.sessions-backdrop {
  display: none;
  position: fixed;
  top: 55px; left: 0; right: 0; bottom: 0;
  z-index: 69;
  background: color-mix(in srgb, var(--bg) 45%, transparent);
}
.mobile-cast {
  display: none;
  gap: 14px;
  padding: 10px 16px 8px;
  overflow-x: auto;
  border-bottom: 1px solid var(--line);
  -webkit-overflow-scrolling: touch;
}
.mc-item { flex: none; text-align: center; cursor: pointer; background: none; border: none; padding: 0; color: var(--text); }
.mc-item .avatar { width: 44px; height: 44px; }
.mc-item .avatar-ph {
  width: 44px; height: 44px; border-radius: 50%;
  display: grid; place-items: center;
  background: var(--panel-2); color: var(--peri); font-size: 17px;
  border: 2px solid var(--line-2);
}
.mc-item .mc-nm { font-size: 10px; color: var(--muted); margin-top: 2px; max-width: 60px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mc-item.on .avatar { border-color: var(--accent); box-shadow: 0 0 0 2px var(--glow); }
.mc-item.on .mc-nm { color: var(--text); }

/* ============ 中間幅 ============ */
@media (max-width: 1180px) {
  .shell { grid-template-columns: minmax(0, 1fr) 300px; }
  .sessions {
    position: fixed;
    top: 55px; left: 0; bottom: 0;
    width: 272px;
    background: var(--bg-2);
    z-index: 70;
    transform: translateX(-102%);
    transition: transform .25s ease;
    box-shadow: var(--shadow);
    border-right: 1px solid var(--line-2);
  }
  .sessions.open { transform: none; padding-top: 50px; }
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
  .hist-btn { display: inline-flex; }
}

/* ============ 縦画面・スマホ ============ */
@media (max-width: 860px) {
  .gband { padding: 10px 14px; gap: 12px; }
  .gband .gname { font-size: 15px; }
  .gband .gworld { display: none; }
  .gband .chips { overflow-x: auto; }
  .gband .chip { white-space: nowrap; }
  .shell { display: flex; flex-direction: column; }
  .presence {
    position: fixed;
    right: -6vw; bottom: 0;
    width: 84vw; max-width: 430px;
    height: 62dvh;
    border-left: none;
    z-index: 0;
    pointer-events: none;
    opacity: .22;
  }
  .presence .pname, .presence .pocc, .presence .cast { display: none; }
  .stream-wrap { position: relative; z-index: 1; flex: 1; min-height: 0; }
  .mobile-cast { display: flex; }
  .stream-head { padding: 10px 14px; gap: 10px; }
  .stream-head .t { font-size: 13.5px; }
  .stream-head .w { display: none; }
  .stream { padding: 20px 16px 12px; }
  .msg .bubble { font-size: 14.5px; padding: 10px 14px; }
  .msg .avatar, .msg .avatar-ph { width: 38px; height: 38px; }
  .msg .ops, .narr-wrap .ops, .memo .ops { opacity: .75; }
  .composer { padding: 10px 14px 14px; }
  .comp-tools { overflow-x: auto; }
  .comp-tools .chip { white-space: nowrap; }
}

/* ============ 低い画面 ============ */
@media (max-height: 760px) {
  .gband { padding: 8px 26px; }
  .gband .gworld { -webkit-line-clamp: 1; }
  .stream-head { padding: 8px 26px; }
  .stream { padding: 18px 34px 12px; }
  .stream-inner { gap: 18px; }
  .composer { padding: 8px 34px 12px; }
  .comp-tools { margin-bottom: 6px; }
  .comp-input .q-field__control { min-height: 44px; padding: 2px 18px; }
}
"""
    + DIFF_CSS
)

# 入力欄 keydown: メンション補完(↑↓/Enter/Tab/Esc)→ コマンドパレット → Enter送信/Alt+Enter改行
_COMPOSER_KEYDOWN_JS = """
event => {
  const target = event.target;
  const value = target && typeof target.value === 'string' ? target.value : '';
  const mentionPalette = document.querySelector('.p3-mention-palette');
  const cmdPalette = document.querySelector('.p3-cmd-palette');
  const mentionState = input => {
    if (!input || typeof input.value !== 'string') return null;
    const cursor = input.selectionStart ?? input.value.length;
    const before = input.value.slice(0, cursor);
    const at = before.lastIndexOf('@');
    if (at < 0) return null;
    const query = before.slice(at + 1);
    if (!/^[A-Za-z0-9_]*$/.test(query)) return null;
    const previous = at > 0 ? before[at - 1] : '';
    if (/[A-Za-z0-9_@]/.test(previous)) return null;
    return { start: at, end: cursor };
  };
  const mentionOptions = () => mentionPalette
    ? Array.from(mentionPalette.querySelectorAll('.p3-mention-option:not(.p3-mention-option-hidden)'))
    : [];
  const activeIndex = (options, cls) => Math.max(0, options.findIndex(o => o.classList.contains(cls)));
  const setActive = (options, index, cls) => {
    options.forEach((option, optionIndex) => {
      const active = optionIndex === index;
      option.classList.toggle(cls, active);
      option.setAttribute('aria-selected', active ? 'true' : 'false');
      if (active && typeof option.scrollIntoView === 'function') option.scrollIntoView({ block: 'nearest' });
    });
  };
  const insertMention = option => {
    const state = mentionState(target);
    const handle = option && option.dataset ? option.dataset.handle : '';
    if (!state || !handle) return false;
    const replacement = `@${handle} `;
    target.value = target.value.slice(0, state.start) + replacement + target.value.slice(state.end);
    const cursor = state.start + replacement.length;
    target.selectionStart = target.selectionEnd = cursor;
    target.dispatchEvent(new Event('input', { bubbles: true }));
    if (mentionPalette) mentionPalette.classList.add('hidden');
    return true;
  };

  if (mentionPalette && !mentionPalette.classList.contains('hidden')) {
    const options = mentionOptions();
    if (options.length && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
      event.preventDefault();
      const delta = event.key === 'ArrowDown' ? 1 : -1;
      setActive(options, (activeIndex(options, 'p3-mention-option-active') + delta + options.length) % options.length, 'p3-mention-option-active');
      return;
    }
    if (options.length && (event.key === 'Enter' || event.key === 'Tab') && !event.isComposing) {
      event.preventDefault();
      insertMention(options[activeIndex(options, 'p3-mention-option-active')] || options[0]);
      return;
    }
    if (event.key === 'Escape') {
      mentionPalette.classList.add('hidden');
      return;
    }
  }

  const commandMatch = value.match(/^([\\s\\S]*)\\/([A-Za-z]*)$/);
  const cmdOptions = cmdPalette ? Array.from(cmdPalette.querySelectorAll('.p3-cmd-option')) : [];
  if (commandMatch && cmdOptions.length && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
    event.preventDefault();
    const delta = event.key === 'ArrowDown' ? 1 : -1;
    setActive(cmdOptions, (activeIndex(cmdOptions, 'p3-cmd-option-active') + delta + cmdOptions.length) % cmdOptions.length, 'p3-cmd-option-active');
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
  event.preventDefault();
  if (commandMatch && cmdOptions.length) {
    const active = cmdOptions[activeIndex(cmdOptions, 'p3-cmd-option-active')] || cmdOptions[0];
    const command = active && active.dataset ? active.dataset.command : '';
    if (command) {
      target.value = commandMatch[1] + '/' + command;
      target.dispatchEvent(new Event('input', { bubbles: true }));
    }
  }
  if (cmdPalette) cmdPalette.classList.add('hidden');
  emit(target && typeof target.value === 'string' ? target.value : '');
}
"""

# @ メンションパレットの表示同期(input/keyup/click/focus 時)
_MENTION_REFRESH_JS = """
event => {
  const input = event.target;
  const palette = document.querySelector('.p3-mention-palette');
  if (!input || !palette) return;
  const cursor = input.selectionStart ?? input.value.length;
  const before = input.value.slice(0, cursor);
  const at = before.lastIndexOf('@');
  let state = null;
  if (at >= 0) {
    const query = before.slice(at + 1);
    const previous = at > 0 ? before[at - 1] : '';
    if (/^[A-Za-z0-9_]*$/.test(query) && !/[A-Za-z0-9_@]/.test(previous)) {
      state = { query: query.toLowerCase() };
    }
  }
  const options = Array.from(palette.querySelectorAll('.p3-mention-option'));
  const visible = [];
  for (const option of options) {
    const handle = (option.dataset.handle || '').toLowerCase();
    const matched = !!state && (state.query === '' || handle.startsWith(state.query));
    option.classList.toggle('p3-mention-option-hidden', !matched);
    if (matched) visible.push(option);
  }
  if (!state || !visible.length) {
    palette.classList.add('hidden');
    return;
  }
  palette.classList.remove('hidden');
  let active = visible.find(option => option.classList.contains('p3-mention-option-active'));
  if (!active) active = visible[0];
  for (const option of options) {
    option.classList.toggle('p3-mention-option-active', option === active);
  }
}
"""

_MENTION_INSERT_JS = """
event => {
  event.preventDefault();
  const option = event.currentTarget;
  const input = document.querySelector('.comp-input textarea');
  const palette = document.querySelector('.p3-mention-palette');
  if (!option || !input) return;
  const cursor = input.selectionStart ?? input.value.length;
  const before = input.value.slice(0, cursor);
  const at = before.lastIndexOf('@');
  if (at < 0) return;
  const query = before.slice(at + 1);
  if (!/^[A-Za-z0-9_]*$/.test(query)) return;
  const handle = option.dataset.handle || '';
  if (!handle) return;
  const replacement = `@${handle} `;
  input.value = input.value.slice(0, at) + replacement + input.value.slice(cursor);
  const next = at + replacement.length;
  input.selectionStart = input.selectionEnd = next;
  input.dispatchEvent(new Event('input', { bubbles: true }));
  if (palette) palette.classList.add('hidden');
  input.focus();
}
"""

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
      if (active && typeof option.scrollIntoView === 'function') option.scrollIntoView({ block: 'nearest' });
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


def _member_tts_id(group_id: str, member_id: str) -> str:
    return f"group-{group_id}-member-{member_id}"


def _persona_tts_id(persona_id: str) -> str:
    return f"user-persona-{persona_id}"


def _inline_html(text: str) -> str:
    return html.escape(text).replace("\n", "<br>")


def _configured_group_llm(ctx, profile_id: str):
    try:
        return build_configured_llm(ctx.api_config, profile_id, get_vault_password())
    except LLMRuntimeError as err:
        if err.kind == PROFILE_NOT_FOUND:
            ui.notify("LLMプロファイルが見つかりません", type="warning")
        elif err.kind == MODEL_ID_MISSING:
            ui.notify("LLMプロファイルのモデルIDが未設定です", type="negative")
        elif err.kind == ENDPOINT_NOT_FOUND:
            ui.notify("LLMプロファイルのエンドポイントが見つかりません", type="negative")
        elif err.kind == API_KEY_LOCKED:
            ui.notify("APIキーがロックされています。設定画面で解除してください。", type="warning")
        return None


def _avatar_or_placeholder(media, name: str, *, classes: str = "avatar") -> None:
    image = media.primary_image() if media is not None else None
    url = media_url(image.path) if image is not None else None
    if url is not None:
        raw_img(url, classes).style(f"object-position: {image_object_position(image)};")
    else:
        with ui.element("div").classes("avatar-ph"):
            ui.html(html.escape((name or "?")[:1]))


class Ui2GroupChatController:
    """箱庭シェルの編成(旧 GroupChatPageController 踏襲)+P3描画。"""

    def __init__(self, ctx, group: GroupChatRecord, page_client) -> None:
        self.ctx = ctx
        self.group = group
        self.page_client = page_client
        self.participants = group_participants(group)

        self.sessions: list[GroupChatSessionRecord] = []
        self.sessions_by_id: dict[str, GroupChatSessionRecord] = {}
        self.active_session_id: str | None = None
        self.active_title_is_auto = False
        self.title_generation_attempted = False
        self.title = "セッションを開始"
        self.settings: dict[str, Any] | None = None
        self.messages: list[dict[str, Any]] = []

        self.input_mode = "user"
        self.character_speaker: GroupMember | None = None
        self.guest_input_name = ""
        self.sending = False
        self.tts_generating_index: int | None = None

        self.presence = PresenceStage()
        self.busy: BusyController | None = None

        # 描画参照
        self.sess_list: ui.element | None = None
        self.scene_box: ui.element | None = None
        self.head_title: ui.element | None = None
        self.head_sub: ui.element | None = None
        self.stream_inner: ui.element | None = None
        self.input: ui.textarea | None = None
        self.send_btn: ui.element | None = None
        self.role_chip_label: ui.html | None = None
        self.role_menu_box: ui.element | None = None
        self.palette: ui.element | None = None
        self.mention_palette: ui.element | None = None
        self.cast_box: ui.element | None = None
        self.mobile_cast: ui.element | None = None
        self.band_chips: ui.element | None = None

    # ------------------------------------------------------------------
    # 初期化・セッション状態
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        await self.reload_sessions()
        if self.sessions:
            await self.apply_session(self.sessions[0])

    async def reload_sessions(self) -> None:
        self.sessions = await self.ctx.group_chats.list_sessions_for_group(self.group.id)
        self.sessions_by_id = {session.id: session for session in self.sessions}

    async def apply_session(self, session: GroupChatSessionRecord) -> None:
        self.active_session_id = session.id
        self.active_title_is_auto = session.title_is_auto
        self.title_generation_attempted = False
        self.title = session.title or DEFAULT_GROUP_CHAT_TITLE
        self.settings = dict(session.settings or {})
        self.messages = [dict(message) for message in session.messages if isinstance(message, dict)]
        self.input_mode = "user"
        self.character_speaker = None
        self.guest_input_name = ""
        self.sending = False
        self.tts_generating_index = None

    def clear_active_session(self) -> None:
        self.active_session_id = None
        self.active_title_is_auto = False
        self.title_generation_attempted = False
        self.title = "セッションを開始"
        self.settings = None
        self.messages = []
        self.input_mode = "user"
        self.character_speaker = None
        self.guest_input_name = ""
        self.sending = False
        self.tts_generating_index = None

    def apply_group_update(self, group: GroupChatRecord) -> None:
        self.group = group
        self.participants = group_participants(group)
        self.refresh_cast()
        self.refresh_mention_palette()
        self.refresh_band_chips()
        self.refresh_role_menu()

    def active_members(self) -> list[GroupMember]:
        return _active_members_of(self.group, self.settings)

    def _member_by_id(self, member_id: str) -> GroupMember | None:
        return next((member for member in self.group.members if member.id == member_id), None)

    def _manual_character_speaker(self) -> GroupMember | None:
        active = self.active_members()
        if self.character_speaker is not None and self.character_speaker.id in {m.id for m in active}:
            return self.character_speaker
        return active[0] if active else None

    # ------------------------------------------------------------------
    # JSユーティリティ
    # ------------------------------------------------------------------

    def run_page_javascript(self, code: str) -> None:
        self.page_client.run_javascript(code)

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

    def set_input_value(self, value: str) -> None:
        if self.input is not None:
            self.input.set_value(value)

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
    # 描画: シェル
    # ------------------------------------------------------------------

    def render_band(self) -> None:
        with ui.element("div").classes("gband"):
            back = ui.element("button").classes("back").props('title="グループ一覧へ"')
            with back:
                ui.html("←")
            back.on("click", lambda: ui.navigate.to("/v2/groups"))
            with ui.element("span").classes("gname serif").mark("ui2-group-name"):
                ui.html(html.escape(self.group.name))
            with ui.element("span").classes("gworld"):
                ui.html(html.escape(self.group.world))
            self.band_chips = ui.element("span").classes("chips")
        self.refresh_band_chips()

    def refresh_band_chips(self) -> None:
        if self.band_chips is None:
            return
        self.band_chips.clear()
        with self.band_chips:
            with ui.element("span").classes("chip"):
                ui.html(html.escape(world_source_chip_label(self.group)))
            with ui.element("span").classes("chip"):
                ui.html(f"メンバー {len(self.group.members)}人")
            persona = self.group.user_persona
            if persona is not None:
                with ui.element("span").classes("chip"):
                    ui.html(html.escape(f"あなた: {persona.display_name or persona.name or 'ユーザー'}"))
            manage = (
                ui.element("button")
                .classes("chip manage")
                .props('title="世界観・住人・関係を確認/編集"')
                .mark("ui2-group-manage")
            )
            with manage:
                ui.html("管理")
            manage.on("click", self.open_manage_dialog)

    def render_shell(self) -> None:
        with ui.element("div").classes("shell"):
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
                    ui.html("このグループのセッション")
                self.sess_list = ui.element("div").mark("ui2-group-sessions")
                p3_button("+ 新しいセッション", lambda: self.open_new_chat_dialog(), classes="btn quiet").style(
                    "align-self: flex-start;"
                ).mark("ui2-group-new-session")
                self.scene_box = ui.element("div").classes("scene")

            backdrop = ui.element("div").classes("sessions-backdrop")
            backdrop.on(
                "click",
                js_handler="() => document.querySelector('.sessions')?.classList.remove('open')",
            )

            # ---- 中央: ストリーム ----
            with ui.element("main").classes("stream-wrap"):
                with ui.element("div").classes("stream-head"):
                    hist = ui.element("button").classes("btn quiet hist-btn")
                    with hist:
                        ui.html("履歴")
                    hist.on(
                        "click",
                        js_handler="() => document.querySelector('.sessions')?.classList.toggle('open')",
                    )
                    self.head_title = ui.element("span").classes("t serif").mark("ui2-group-chat-title")
                    self.head_sub = ui.element("span").classes("w")
                    ui.element("span").classes("sp")
                    menu_btn = ui.element("button").classes("btn quiet").mark("ui2-group-chat-menu")
                    with menu_btn:
                        ui.html("⋯")
                        with ui.menu().props('anchor="bottom right" self="top right"'):
                            ui.menu_item("新しいセッション", on_click=lambda: self.open_new_chat_dialog())
                            ui.menu_item("タイトル変更", on_click=self.open_rename_current_chat_dialog)
                            ui.menu_item("システムプロンプト", on_click=self.open_system_prompt_dialog)
                            ui.menu_item("セッション削除", on_click=self.confirm_delete_current_chat)

                self.mobile_cast = ui.element("div").classes("mobile-cast")

                with ui.element("div").classes("stream"):
                    self.stream_inner = ui.element("div").classes("stream-inner").mark("ui2-group-stream")

                with ui.element("div").classes("composer"):
                    with ui.element("div").classes("composer-inner"):
                        self.palette = ui.element("div").classes("p3-cmd-palette hidden")
                        self.mention_palette = ui.element("div").classes("p3-mention-palette hidden").props(
                            "role=listbox"
                        )
                        with ui.element("div").classes("comp-tools"):
                            role_chip = ui.element("button").classes("chip").mark("ui2-group-role-chip")
                            with role_chip:
                                self.role_chip_label = ui.html(self._role_chip_text())
                                self.role_menu_box = ui.menu()
                            self.refresh_role_menu()
                            _chip = chip_button
                            _chip("話者を指定", lambda: self._run_chip_command("guide"), title="/guide 次の行動者と指示を指定")
                            _chip("選択肢", lambda: self._run_chip_command("choices"), title="/choices 返答候補を3つ生成")
                            _chip("補完", lambda: self._run_chip_command("fill"), title="/fill 続きを補完")
                            _chip("整える", lambda: self._run_chip_command("tailor"), title="/tailor 現在のロール向けに書き換え")
                            _chip("描写", lambda: self._run_chip_command("describe"), title="/describe 地の文を自動生成")
                        with ui.element("div").classes("comp-row"):
                            self.input = (
                                ui.textarea(placeholder="メッセージを入力（/ でコマンド・@ でメンション）")
                                .props("borderless dense rows=1 autogrow")
                                .classes("comp-input")
                                .mark("ui2-group-input")
                            )
                            self.input.on_value_change(lambda e: self._refresh_command_palette(str(e.value or "")))
                            self.input.on("keydown", self._send_from_enter, js_handler=_COMPOSER_KEYDOWN_JS)
                            for event in ("keyup", "click", "focus"):
                                self.input.on(event, js_handler=_MENTION_REFRESH_JS)
                            self.input.on(
                                "blur",
                                js_handler="event => { setTimeout(() => {"
                                "document.querySelector('.p3-mention-palette')?.classList.add('hidden');"
                                "}, 120); }",
                            )
                            self.send_btn = ui.element("button").classes("btn primary comp-send").mark("ui2-group-send")
                            with self.send_btn:
                                ui.html("送信")
                            self.send_btn.on("click", lambda: self.send_message(True))

            # ---- 右: presence+住人 ----
            with ui.element("aside").classes("presence"):
                with ui.element("div").classes("portrait"):
                    self.presence.render(self._presence_entries())
                with ui.element("div").classes("cast"):
                    with ui.element("div").classes("lbl"):
                        ui.html("この世界の住人")
                    self.cast_box = ui.element("div").classes("members").mark("ui2-group-cast")
                    with ui.element("div").classes("add-row"):
                        p3_button(
                            "+ 既存キャラを適応して迎える",
                            lambda: self.open_add_member_dialog(),
                            classes="btn quiet",
                        ).mark("ui2-group-add-member")
                        p3_button(
                            "+ この世界で生成",
                            lambda: ui.navigate.to(f"/groups/{self.group.id}/generation"),
                            classes="btn quiet",
                            title="グループ内キャラクター生成(旧ページ・Phase 5 で /v2 版に)",
                        )

        self.busy = BusyController()
        self.refresh_mention_palette()
        self.refresh_sessions_pane()
        self.refresh_chat_header()
        self.refresh_scene()
        self.refresh_cast()
        self.refresh_messages(scroll_to_bottom=True)
        self._focus_default_participant()
        ui.timer(0.1, self.restore_active_ai_job, once=True)

    # ------------------------------------------------------------------
    # presence+住人
    # ------------------------------------------------------------------

    def _presence_entries(self) -> list[PresenceEntry]:
        entries: list[PresenceEntry] = []
        for member in self.group.members:
            sub_parts = [part for part in (member.character.occupation, entry_type_label(member.world_entry_type)) if part]
            entries.append(
                PresenceEntry(
                    key=f"member:{member.id}",
                    label=member.character.name,
                    sub=" — ".join(sub_parts),
                    image=member.character.media.primary_image(),
                )
            )
        return entries

    def _focus_default_participant(self) -> None:
        # 最後に発言したキャラ → 先頭メンバー
        target_key = ""
        for message in reversed(self.messages):
            if message.get("role") == "character":
                member = self._member_by_id(str(message.get("speaker_id", "")))
                if member is not None:
                    target_key = f"member:{member.id}"
                    break
        if not target_key and self.group.members:
            target_key = f"member:{self.group.members[0].id}"
        if target_key:
            self.focus_participant(target_key)

    def focus_participant(self, key: str) -> None:
        self.presence.focus(key)
        self.refresh_cast()

    def refresh_cast(self) -> None:
        candidates = next_speaker_candidate_ids(self.messages, self.active_members())
        if self.cast_box is not None:
            self.cast_box.clear()
            with self.cast_box:
                for member in self.group.members:
                    key = f"member:{member.id}"
                    row = ui.element("button").classes("member on" if self.presence.focused_key == key else "member")
                    row.props(f'title="{html.escape(member.world_adaptation_note or member.arrival_reason or "")}"')
                    row.on("click", lambda k=key: self.focus_participant(k))
                    with row:
                        _avatar_or_placeholder(member.character.media, member.character.name)
                        with ui.element("div").classes("mi"):
                            with ui.element("div").classes("nm"):
                                ui.html(html.escape(member.character.name))
                                with ui.element("span").classes("tag"):
                                    ui.html("適応" if member.world_entry_type != "native" else "住人")
                            with ui.element("div").classes("st"):
                                sub = " — ".join(
                                    part
                                    for part in (entry_type_label(member.world_entry_type), member.character.occupation)
                                    if part
                                )
                                ui.html(html.escape(sub))
                        if member.id in candidates:
                            ui.element("span").classes("dot").props('title="次の話者候補"')
                        open_btn = ui.element("span").classes("open-btn").props('title="適応プロフィールを開く"')
                        with open_btn:
                            ui.html("開く")
                        open_btn.on(
                            "click.stop",
                            lambda mid=member.id: ui.navigate.to(f"/v2/groups/{self.group.id}/members/{mid}"),
                        )
                persona = self.group.user_persona
                if persona is not None:
                    you = ui.element("button").classes("member you").props('title="グループペルソナを開く"')
                    you.on("click", lambda: ui.navigate.to(f"/v2/groups/{self.group.id}/persona"))
                    with you:
                        _avatar_or_placeholder(persona.media, persona.display_name or persona.name or "ユーザー")
                        with ui.element("div").classes("mi"):
                            with ui.element("div").classes("nm"):
                                ui.html(html.escape(persona.display_name or persona.name or "ユーザー"))
                                with ui.element("span").classes("tag"):
                                    ui.html("ペルソナ")
                            with ui.element("div").classes("st"):
                                ui.html("あなた — この世界での姿")
        if self.mobile_cast is not None:
            self.mobile_cast.clear()
            with self.mobile_cast:
                for member in self.group.members:
                    key = f"member:{member.id}"
                    item = ui.element("button").classes(
                        "mc-item on" if self.presence.focused_key == key else "mc-item"
                    )
                    item.on("click", lambda k=key: self.focus_participant(k))
                    with item:
                        _avatar_or_placeholder(member.character.media, member.character.name)
                        with ui.element("div").classes("mc-nm"):
                            ui.html(html.escape(member.character.name))

    # ------------------------------------------------------------------
    # 描画: セッション・ヘッダー・シーン
    # ------------------------------------------------------------------

    def refresh_sessions_pane(self) -> None:
        if self.sess_list is None:
            return
        self.sess_list.clear()
        with self.sess_list:
            if not self.sessions:
                with ui.element("div").classes("no-sess"):
                    ui.html("まだセッションがありません。<br>「+ 新しいセッション」から始められます。")
                return
            for session in self.sessions:
                item = ui.element("div").classes("sess on" if session.id == self.active_session_id else "sess")
                item.on("click", lambda sid=session.id: self.select_chat_session(sid))
                with item:
                    with ui.element("div").classes("t"):
                        ui.html(html.escape(session.title or DEFAULT_GROUP_CHAT_TITLE))
                    with ui.element("div").classes("s"):
                        ui.html(html.escape(latest_group_message_preview(session.messages)))
                    with ui.element("div").classes("sess-ops"):
                        rename = ui.element("button").props('title="タイトル変更"')
                        with rename:
                            ui.html("✎")
                        rename.on("click.stop", lambda sid=session.id: self.open_rename_chat_dialog(sid))
                        delete = ui.element("button").props('title="セッション削除"')
                        with delete:
                            ui.html("×")
                        delete.on("click.stop", lambda sid=session.id: self.confirm_delete_chat_session(sid))

    def chat_title(self) -> str:
        return self.title or "セッションを開始"

    def chat_subtitle(self) -> str:
        if self.settings is None:
            return "新しいセッションを開始してください"
        profile = self.ctx.api_config.get_llm_profile(str(self.settings.get("profile_id", "")))
        profile_name = profile.name if profile else "不明なプロファイル"
        names = [member.character.name for member in self.active_members()]
        members = "、".join(names) if names else "参加キャラなし"
        return f"{members} / {profile_name}"

    def refresh_chat_header(self) -> None:
        if self.head_title is not None:
            self.head_title.clear()
            with self.head_title:
                ui.html(html.escape(self.chat_title()))
        if self.head_sub is not None:
            self.head_sub.clear()
            with self.head_sub:
                ui.html(html.escape(self.chat_subtitle()))

    def refresh_scene(self) -> None:
        if self.scene_box is None:
            return
        self.scene_box.clear()
        situation = str((self.settings or {}).get("situation", "") or "").strip()
        if not situation:
            self.scene_box.set_visibility(False)
            return
        self.scene_box.set_visibility(True)
        with self.scene_box:
            with ui.element("div").classes("lbl2"):
                ui.html("シ ー ン")
            with ui.element("div").classes("tx"):
                ui.html(_inline_html(situation))
            edit = ui.element("div").classes("edit")
            with edit:
                ui.html("シーンを編集")
            edit.on("click", self.open_scene_dialog)

    # ------------------------------------------------------------------
    # 描画: メッセージ
    # ------------------------------------------------------------------

    def refresh_messages(self, *, scroll_to_bottom: bool = False) -> None:
        if self.stream_inner is None:
            return
        if not scroll_to_bottom:
            self.run_page_javascript(
                "(() => {"
                "const el = document.querySelector('.stream');"
                "window.__p3GroupScrollTop = el ? el.scrollTop : null;"
                "})();"
            )
        self.stream_inner.clear()
        with self.stream_inner:
            if self.active_session_id is None:
                self._render_empty_state()
            else:
                for index, message in enumerate(self.messages):
                    self._render_message(index, message)
        self.refresh_cast()
        if scroll_to_bottom:
            self.scroll_messages_to_bottom()
        else:
            self.run_page_javascript(
                "setTimeout(() => {"
                "const el = document.querySelector('.stream');"
                "const top = window.__p3GroupScrollTop;"
                "if (el && typeof top === 'number') el.scrollTop = top;"
                "window.__p3GroupScrollTop = null;"
                "}, 0);"
            )

    def _render_empty_state(self) -> None:
        with ui.element("div").classes("empty-stream"):
            with ui.element("div").classes("hello"):
                ui.html("こ の 世 界 の 記 録 は ま だ あ り ま せ ん")
            with ui.element("div").classes("note"):
                ui.html("「+ 新しいセッション」で参加キャラとシチュエーションを決めて始めましょう。")
            with ui.element("div").style("margin-top: 18px;"):
                _btn = p3_button("新しいセッション", lambda: self.open_new_chat_dialog(), classes="btn primary")
                _btn.mark("ui2-group-empty-start")

    def message_tts_playable(self, message: dict[str, Any]) -> bool:
        role = str(message.get("role", ""))
        if not str(message.get("text", "")).strip():
            return False
        if role == "narration":
            return self._narrator_tts_configured()
        if role == "character":
            member = self._member_by_id(str(message.get("speaker_id", "")))
            return member is not None and self._character_tts_configured(member)
        if role == "user":
            persona = self.group.user_persona
            return persona is not None and self._user_persona_tts_configured(persona)
        return False

    def _ops_row(self, index: int, message: dict[str, Any]) -> None:
        role = str(message.get("role", ""))
        with ui.element("div").classes("ops"):
            if self.message_tts_playable(message):
                label = "生成中…" if self.tts_generating_index == index else "音声"
                btn = p3_button(label, lambda i=index: self.play_tts_message(i), classes="btn quiet", title="読み上げ")
                if self.tts_generating_index is not None:
                    btn.props("disabled")
            if role == "character":
                p3_button(
                    "再生成",
                    lambda i=index: self.confirm_or_regenerate_character_message(i),
                    classes="btn quiet",
                    title="この台詞を再生成",
                )
            if role in {"character", "guest", "user", "narration", "memo"}:
                p3_button("編集", lambda i=index: self.open_rewrite_message_dialog(i), classes="btn quiet")
                p3_button(
                    "戻る",
                    lambda i=index: self.confirm_rewind_to_message(i),
                    classes="btn quiet",
                    title="ここまで巻き戻す(以降を削除して入力欄へ)",
                )
            if isinstance(message.get("debug"), dict):
                p3_button(
                    "入出力",
                    lambda d=message["debug"]: self.open_llm_debug_dialog(d),
                    classes="btn quiet",
                    title="LLMデバッグ(入出力・トークン)",
                )
            if isinstance(message.get("speaker_debug"), dict):
                p3_button(
                    "話者ログ",
                    lambda d=message["speaker_debug"]: self.open_llm_debug_dialog(d),
                    classes="btn quiet",
                    title="発言者決定ログ",
                )
            with ui.element("span").classes("tm"):
                ui.html(html.escape(str(message.get("time_label", ""))))

    def _render_message(self, index: int, message: dict[str, Any]) -> None:
        role = str(message.get("role", ""))
        text = str(message.get("text", ""))
        if role == "narration":
            with ui.element("div").classes("narr-wrap"):
                with ui.element("div").classes("narr"):
                    ui.html(_inline_html(text))
                self._ops_row(index, message)
            return
        if role == "memo":
            with ui.element("div").classes("memo"):
                with ui.element("div").classes("memo-k"):
                    ui.html("コメント")
                ui.html(_inline_html(text))
                self._ops_row(index, message)
            return
        if role == "system":
            with ui.element("div").classes("sysmsg"):
                ui.html(_inline_html(text))
            return

        is_user = role == "user"
        with ui.element("div").classes("msg user" if is_user else "msg"):
            speaker_name = str(message.get("speaker_name", "") or "")
            handle = str(message.get("handle", "") or "")
            if not is_user:
                participant = participant_by_speaker_id(self.participants, str(message.get("speaker_id", "")))
                if role == "character" and participant is not None:
                    member = participant.get("member")
                    image = member.character.media.primary_image() if isinstance(member, GroupMember) else None
                    url = media_url(image.path) if image is not None else None
                    if url is not None:
                        img = raw_img(url, "avatar").props(f'title="{html.escape(speaker_name)}"')
                        img.style(f"object-position: {image_object_position(image)};")
                        img.on("click", lambda key=participant["key"]: self.focus_participant(key))
                    else:
                        with ui.element("div").classes("avatar-ph"):
                            ui.html(html.escape((speaker_name or "?")[:1]))
                else:
                    with ui.element("div").classes("avatar-ph"):
                        ui.html(html.escape((speaker_name or "客")[:1]))
            with ui.element("div").classes("body"):
                who = speaker_name or ("あなた" if is_user else "？")
                with ui.element("div").classes("who"):
                    ui.html(html.escape(who))
                    if handle:
                        with ui.element("span").classes("hd"):
                            ui.html(html.escape(f"　@{handle}"))
                with ui.element("div").classes("bubble"):
                    ui.html(_inline_html(text))
                self._ops_row(index, message)

    # ------------------------------------------------------------------
    # ロールチップ・パレット
    # ------------------------------------------------------------------

    def _role_chip_text(self) -> str:
        if self.input_mode == "character":
            speaker = self._manual_character_speaker()
            return f"キャラ: {speaker.character.name}" if speaker else "キャラ: 未選択"
        if self.input_mode == "guest":
            return f"ゲスト: {self.guest_input_name or '未指定'}"
        if self.input_mode == "narration":
            return "ロール: ナラティブ"
        if self.input_mode == "memo":
            return "ロール: コメント"
        return "ロール: ユーザー"

    def refresh_input_mode_chip(self) -> None:
        if self.role_chip_label is not None:
            self.role_chip_label.set_content(html.escape(self._role_chip_text()))

    def refresh_role_menu(self) -> None:
        if self.role_menu_box is None:
            return
        self.role_menu_box.clear()
        with self.role_menu_box:
            ui.menu_item("ユーザー", on_click=lambda: self.set_input_mode("user"))
            for member in self.active_members():
                ui.menu_item(
                    f"キャラ: {member.character.name}",
                    on_click=lambda m=member: self.set_character_input_member(m),
                )
            ui.menu_item("ゲスト…", on_click=lambda: self.open_guest_input_mode_dialog())
            ui.menu_item("ナラティブ", on_click=lambda: self.set_input_mode("narration"))
            ui.menu_item("コメント", on_click=lambda: self.set_input_mode("memo"))

    def set_input_mode(self, mode: str, *, notify_change: bool = False) -> None:
        self.input_mode = mode if mode in {"user", "character", "guest", "narration", "memo"} else "user"
        if self.input_mode != "guest":
            self.guest_input_name = ""
        if self.input_mode != "character":
            self.character_speaker = None
        self.refresh_input_mode_chip()
        if notify_change:
            ui.notify(f"{self._role_chip_text()} にしました", type="info")

    def set_character_input_member(self, member: GroupMember) -> None:
        self.character_speaker = member
        self.input_mode = "character"
        self.refresh_input_mode_chip()

    def set_guest_input_mode(self, guest_name: str) -> None:
        name = clean_guest_name(guest_name)
        if not name:
            ui.notify("ゲスト名を入力してください", type="warning")
            return
        self.guest_input_name = name
        self.input_mode = "guest"
        self.refresh_input_mode_chip()

    def open_guest_input_mode_dialog(self, left_text: str = "") -> None:
        with ui.dialog() as dlg, ui.card().classes("w-full max-w-sm").style(_DIALOG_CARD_STYLE):
            ui.label("ゲスト入力").classes("text-base font-semibold")
            ui.label("その場限りの脇役(酒場のマスター等)として発言/生成します。").classes("note")
            name_input = (
                ui.input(label="ゲスト名", value=self.guest_input_name, placeholder="例: 酒場のマスター")
                .props("outlined dense clearable autofocus")
                .classes("w-full p3-ta")
                .mark("ui2-group-guest-name")
            )

            def _apply() -> None:
                name = clean_guest_name(str(name_input.value or ""))
                if not name:
                    ui.notify("ゲスト名を入力してください", type="warning")
                    return
                self.set_guest_input_mode(name)
                if left_text:
                    self.set_input_value(left_text.rstrip())
                self.focus_chat_input_at_end()
                dlg.close()
                ui.notify(f"{guest_display_name(name)}入力モードにしました", type="info")

            with ui.row().classes("justify-end gap-2 mt-4 w-full"):
                p3_button("キャンセル", dlg.close, classes="btn quiet")
                p3_button("選択", _apply, classes="btn primary").mark("ui2-group-guest-apply")
        dlg.open()

    def refresh_mention_palette(self) -> None:
        if self.mention_palette is None:
            return
        self.mention_palette.clear()
        with self.mention_palette:
            for index, participant in enumerate(mention_entries(self.group, self.settings)):
                handle = str(participant.get("handle") or "")
                option = (
                    ui.element("button")
                    .props(
                        f"type=button data-handle={handle} aria-selected={'true' if index == 0 else 'false'}"
                    )
                    .classes("p3-mention-option")
                )
                option.on("mousedown", js_handler=_MENTION_INSERT_JS)
                with option:
                    media = participant.get("media")
                    image = media.primary_image() if media is not None else None
                    url = media_url(image.path) if image is not None else None
                    if url is not None:
                        raw_img(url).style(f"object-position: {image_object_position(image)};")
                    else:
                        with ui.element("span").classes("m-ph"):
                            ui.html(html.escape(str(participant.get("name") or "?")[:1]))
                    with ui.element("span").classes("p3-mention-name"):
                        ui.html(html.escape(str(participant.get("name") or "")))
                    with ui.element("span").classes("p3-mention-handle"):
                        ui.html(html.escape(f"@{handle}"))
                    with ui.element("span").classes("p3-mention-kind"):
                        ui.html("User" if participant.get("kind") == "user" else "Char")
        self.run_page_javascript("document.querySelector('.p3-mention-palette')?.classList.add('hidden');")

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

    async def _send_from_enter(self, e) -> None:
        if isinstance(e.args, list):
            value = str(e.args[0] or "") if e.args else ""
        else:
            value = str(e.args or "")
        await self.send_message(False, value)

    # ------------------------------------------------------------------
    # 保存・同期・AIジョブ
    # ------------------------------------------------------------------

    async def save_current_session(self, *, refresh_history: bool = True) -> None:
        if self.active_session_id is None or self.settings is None:
            return
        saved = await self.ctx.group_chats.update_session(
            session_id=self.active_session_id,
            group_id=self.group.id,
            title=self.title or DEFAULT_GROUP_CHAT_TITLE,
            title_is_auto=self.active_title_is_auto,
            settings=self.settings,
            messages=self.messages,
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
        settings: dict[str, Any],
        messages: list[dict[str, Any]],
    ) -> None:
        saved = await self.ctx.group_chats.update_session(
            session_id=session_id,
            group_id=self.group.id,
            title=title or DEFAULT_GROUP_CHAT_TITLE,
            title_is_auto=title_is_auto,
            settings=settings,
            messages=messages,
        )
        self.sessions_by_id[saved.id] = saved

    async def _sync_active_session_from_storage(self) -> None:
        if self.active_session_id is None:
            return
        session = await self.ctx.group_chats.get_session(self.active_session_id)
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

    def _active_scope(self) -> str:
        return f"group_chat:{self.active_session_id or 'none'}"

    def _result_url(self) -> str:
        return f"/v2/groups/{self.group.id}"

    async def restore_active_ai_job(self) -> None:
        if self.active_session_id is None:
            return
        job = self.ctx.ai_jobs.latest_active_job(scope=self._active_scope())
        if job is None:
            return
        await self._wait_for_active_group_job(job.id, failure_message="生成に失敗しました")

    async def _wait_for_active_group_job(self, job_id: str, *, failure_message: str) -> bool:
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

    def _assist_scope(self) -> str:
        return f"group_assist:{self.active_session_id or self.group.id}"

    def _assist_metadata(self) -> dict[str, str]:
        return {"group_id": self.group.id, "session_id": self.active_session_id or ""}

    async def _await_assist(self, awaitable, *, failure_message: str):
        self.set_sending(True)
        try:
            result = await awaitable
            if result.status == AIJobStatus.SUCCEEDED:
                return result.value
            if result.status == AIJobStatus.CANCELLED:
                ui.notify("生成を停止しました", type="info")
                return None
            ui.notify(f"{failure_message}: {result.error_message}", type="negative", timeout=10000)
            return None
        except LLMRuntimeError as err:
            notify_setup_llm_error(err)
            return None
        finally:
            self.set_sending(False)

    # ------------------------------------------------------------------
    # セッション操作
    # ------------------------------------------------------------------

    async def select_chat_session(self, session_id: str) -> None:
        if self.sending:
            ui.notify("生成中はセッションを切り替えられません", type="warning")
            return
        session = await self.ctx.group_chats.get_session(session_id)
        if session is None or session.group_id != self.group.id:
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
        self.refresh_mention_palette()
        self.refresh_role_menu()
        self.run_page_javascript("document.querySelector('.sessions')?.classList.remove('open');")

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
                ui.input(label="タイトル", value=session.title or DEFAULT_GROUP_CHAT_TITLE)
                .props("outlined clearable")
                .classes("w-full p3-ta")
                .mark("ui2-group-rename-input")
            )

            async def _save_title() -> None:
                title = (title_input.value or "").strip()
                if not title:
                    ui.notify("タイトルを入力してください", type="warning")
                    return
                saved = await self.ctx.group_chats.rename_session(session_id, title)
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
                p3_button("キャンセル", dlg.close, classes="btn quiet")
                p3_button("保存", _save_title, classes="btn primary").mark("ui2-group-rename-save")
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
            ui.label(session.title or DEFAULT_GROUP_CHAT_TITLE).classes("text-sm font-semibold")

            async def _delete() -> None:
                dlg.close()
                was_active = session_id == self.active_session_id
                await self.ctx.group_chats.delete_session(session_id)
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
                p3_button("キャンセル", dlg.close, classes="btn quiet")
                p3_button("削除", _delete, classes="btn primary").mark("ui2-group-delete-session")
        dlg.open()

    def open_scene_dialog(self) -> None:
        if self.settings is None:
            ui.notify("先にセッションを開始してください", type="warning")
            return
        with ui.dialog() as dlg, ui.card().classes("w-full max-w-xl").style(_DIALOG_CARD_STYLE):
            ui.label("シーンを編集").classes("text-base font-semibold")
            ui.label("以降のターンから反映されます（過去の発言は変わりません）。").classes("note")
            scene_input = (
                ui.textarea(value=str(self.settings.get("situation", "") or ""))
                .props("outlined rows=5 autogrow")
                .classes("w-full p3-ta")
            )

            async def _save_scene() -> None:
                if self.settings is None:
                    dlg.close()
                    return
                self.settings = {**self.settings, "situation": str(scene_input.value or "").strip()}
                dlg.close()
                self.refresh_scene()
                await self.save_current_session()
                ui.notify("シーンを更新しました", type="positive")

            with ui.row().classes("justify-end gap-2 mt-4 w-full"):
                p3_button("キャンセル", dlg.close, classes="btn quiet")
                p3_button("保存", _save_scene, classes="btn primary")
        dlg.open()

    def open_system_prompt_dialog(self) -> None:
        if self.settings is None:
            ui.notify("先にセッションを開始してください", type="warning")
            return
        active = self.active_members()
        if not active:
            ui.notify("参加キャラがいません", type="warning")
            return
        prompt = build_group_system_prompt(self.group, self.settings, active, active[0])
        with ui.dialog() as dlg, ui.card().classes("w-full max-w-4xl").style(_DIALOG_CARD_STYLE):
            with ui.row().classes("items-center justify-between w-full"):
                ui.label("システムプロンプト").classes("text-lg font-semibold")
                p3_button("閉じる", dlg.close, classes="btn quiet")
            with ui.scroll_area().style("height: 62vh; width: 100%;"):
                ui.code(prompt, language="markdown").classes("w-full text-xs")
        dlg.open()

    def open_llm_debug_dialog(self, debug: dict[str, Any]) -> None:
        def _token_label(value) -> str:
            return str(value) if value is not None else "不明"

        token_lines = [
            f"入力: {_token_label(debug.get('input_tokens'))}",
            f"出力: {_token_label(debug.get('output_tokens'))}",
            f"合計: {_token_label(debug.get('total_tokens'))}",
        ]
        with ui.dialog() as dlg, ui.card().classes("w-full max-w-4xl").style(_DIALOG_CARD_STYLE):
            with ui.row().classes("items-center justify-between w-full"):
                ui.label("LLMデバッグ").classes("text-lg font-semibold")
                p3_button("閉じる", dlg.close, classes="btn quiet")
            ui.label(" / ".join(token_lines)).classes("note")
            ui.label("入力").classes("text-sm font-semibold mt-2")
            with ui.scroll_area().style("height: 32vh; width: 100%;"):
                ui.code(str(debug.get("llm_input", "")), language="text").classes("w-full text-xs")
            if debug.get("reasoning_output"):
                ui.label("推論 / Thinking").classes("text-sm font-semibold mt-2")
                with ui.scroll_area().style("height: 22vh; width: 100%;"):
                    ui.code(str(debug.get("reasoning_output", "")), language="text").classes("w-full text-xs")
            ui.label("出力").classes("text-sm font-semibold mt-2")
            with ui.scroll_area().style("height: 22vh; width: 100%;"):
                ui.code(str(debug.get("raw_output", "")), language="text").classes("w-full text-xs")
        dlg.open()

    # ------------------------------------------------------------------
    # メッセージ操作(巻き戻し・書き換え・再生成・TTS)
    # ------------------------------------------------------------------

    async def rewind_to_message(self, index: int) -> None:
        if index < 0 or index >= len(self.messages):
            return
        message = self.messages[index]
        role = str(message.get("role", ""))
        if role not in {"character", "guest", "user", "narration", "memo"}:
            return
        self.messages = self.messages[:index]
        if self.input is not None:
            self.input.set_value(str(message.get("text", "")))
            self.input.enable()
        if role == "guest":
            self.guest_input_name = clean_guest_name(
                str(message.get("guest_name") or message.get("speaker_name") or "")
            )
            self.input_mode = "guest"
        elif role == "character":
            self.character_speaker = self._member_by_id(str(message.get("speaker_id", "")))
            self.input_mode = "character"
        else:
            self.input_mode = group_input_mode_for_role(role)
        self.refresh_input_mode_chip()
        self.set_sending(False)
        self.tts_generating_index = None
        self.refresh_messages()
        await self.save_current_session()

    def confirm_rewind_to_message(self, index: int) -> None:
        if self.sending:
            ui.notify("生成中は戻れません", type="warning")
            return
        if index < 0 or index >= len(self.messages):
            return
        message = self.messages[index]
        if str(message.get("role", "")) not in {"character", "guest", "user", "narration", "memo"}:
            return
        with ui.dialog() as dlg, ui.card().classes("w-full max-w-sm").style(_DIALOG_CARD_STYLE):
            ui.label("この発言まで戻りますか？").classes("text-base font-semibold")
            ui.label("この発言以降の会話を削除し、本文を入力欄に戻します。").classes("note")
            ui.label(str(message.get("text", ""))).classes("text-sm").style(
                "white-space: pre-wrap; overflow-wrap: anywhere;"
            )

            async def _do_rewind() -> None:
                dlg.close()
                await self.rewind_to_message(index)

            with ui.row().classes("justify-end gap-2 mt-4 w-full"):
                p3_button("キャンセル", dlg.close, classes="btn quiet")
                p3_button("OK", _do_rewind, classes="btn primary")
        dlg.open()

    def open_rewrite_message_dialog(self, index: int) -> None:
        if self.sending:
            ui.notify("生成中は書き換えできません", type="warning")
            return
        if index < 0 or index >= len(self.messages):
            return
        message = self.messages[index]
        with ui.dialog() as dlg, ui.card().classes("w-full max-w-xl").style(_DIALOG_CARD_STYLE):
            ui.label("発言を書き換え").classes("text-base font-semibold")
            ui.label("保存しても、この後の会話は削除されません。").classes("note")
            rewrite_input = (
                ui.textarea(value=str(message.get("text", "")), placeholder="書き換え後の本文")
                .props("outlined rows=5 autogrow")
                .classes("w-full p3-ta")
                .mark("ui2-group-rewrite-input")
            )

            async def _save_rewrite() -> None:
                next_text = (rewrite_input.value or "").strip()
                if not next_text:
                    ui.notify("本文を入力してください", type="warning")
                    return
                if index >= len(self.messages):
                    dlg.close()
                    return
                self.messages[index] = {**self.messages[index], "text": next_text}
                dlg.close()
                self.refresh_messages()
                await self.save_current_session()

            with ui.row().classes("justify-end gap-2 mt-4 w-full"):
                p3_button("キャンセル", dlg.close, classes="btn quiet")
                p3_button("保存", _save_rewrite, classes="btn primary").mark("ui2-group-rewrite-save")
        dlg.open()

    async def confirm_or_regenerate_character_message(self, index: int) -> None:
        if self.sending:
            ui.notify("生成中は再生成できません", type="warning")
            return
        if index < 0 or index >= len(self.messages):
            return
        if self.messages[index].get("role") != "character":
            return
        if index == len(self.messages) - 1:
            await self.regenerate_character_message(index)
            return
        with ui.dialog() as dlg, ui.card().classes("w-full max-w-sm").style(_DIALOG_CARD_STYLE):
            ui.label("この台詞から再生成しますか？").classes("text-base font-semibold")
            ui.label("この台詞以降の会話を削除してから、新しい台詞を生成します。").classes("note")
            ui.label(str(self.messages[index].get("text", ""))).classes("text-sm").style(
                "white-space: pre-wrap; overflow-wrap: anywhere;"
            )

            async def _do_regenerate() -> None:
                dlg.close()
                await self.regenerate_character_message(index)

            with ui.row().classes("justify-end gap-2 mt-4 w-full"):
                p3_button("キャンセル", dlg.close, classes="btn quiet")
                p3_button("再生成", _do_regenerate, classes="btn primary")
        dlg.open()

    async def regenerate_character_message(self, index: int) -> None:
        if self.settings is None:
            ui.notify("先に「新しいセッション」を作成してください", type="warning")
            self.open_new_chat_dialog()
            return
        if index < 0 or index >= len(self.messages):
            return
        if self.messages[index].get("role") != "character":
            return
        active = self.active_members()
        if not active:
            ui.notify("参加キャラがいません", type="warning")
            return
        llm = _configured_group_llm(self.ctx, str(self.settings.get("profile_id", "")))
        if llm is None or self.active_session_id is None:
            return

        original_messages = [dict(item) for item in self.messages]
        prior_messages = [dict(item) for item in self.messages[:index]]
        rollback_messages = original_messages if index == len(original_messages) - 1 else prior_messages
        display_speaker = self._member_by_id(str(self.messages[index].get("speaker_id", ""))) or active[0]
        self.messages = prior_messages + [group_message("character", "…", member=display_speaker)]
        self.refresh_messages()
        session_id = self.active_session_id
        title = self.title
        title_is_auto = self.active_title_is_auto
        settings_snapshot = dict(self.settings)
        await self.save_current_session(refresh_history=False)

        async def _runner(job) -> list[dict[str, Any]]:
            try:
                result = await self.ctx.group_chat_turns.run_character_turn(
                    group=self.group,
                    settings=settings_snapshot,
                    messages=prior_messages,
                    llm=llm,
                    active_members=active,
                )
                await self._save_session_messages_snapshot(
                    session_id=session_id,
                    title=title,
                    title_is_auto=title_is_auto,
                    settings=settings_snapshot,
                    messages=result.messages,
                )
                return result.messages
            except Exception:
                await self._save_session_messages_snapshot(
                    session_id=session_id,
                    title=title,
                    title_is_auto=title_is_auto,
                    settings=settings_snapshot,
                    messages=rollback_messages,
                )
                raise

        job = self.ctx.ai_jobs.start_job(
            kind=AIJobKind.LLM_GROUP_CHAT,
            label=f"{self.group.name or 'グループ'}の再生成",
            scope=self._active_scope(),
            metadata={"session_id": session_id, "group_id": self.group.id},
            runner=_runner,
        )
        self.ctx.ai_jobs.set_result_meta(job.id, {"result_url": self._result_url()})
        generated = await self._wait_for_active_group_job(job.id, failure_message="再生成に失敗しました")
        if generated:
            await self.maybe_generate_auto_title(llm)

    # ---- TTS ----

    def _character_tts_configured(self, member: GroupMember) -> bool:
        voice = member.character.media.primary_voice()
        voice_path = self.ctx.group_chats.media_path(voice.path) if voice else None
        return bool(
            voice
            and voice_path
            and self.ctx.tts.has_voice_playback_api(
                member.character.media.tts.api_type,
                member.character.media.tts.endpoint_id,
            )
        )

    def _user_persona_tts_configured(self, persona) -> bool:
        settings = persona.media.tts
        if (
            settings.api_type == CHARACTER_TTS_API_GEN_SERVER
            and settings.gen_server_tts_mode == CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3
        ):
            return (
                bool(settings.voice_caption.strip())
                and self.ctx.tts.resolve_gen_server_voice_design_endpoint(raise_on_missing=False) is not None
            )
        if (
            settings.api_type == CHARACTER_TTS_API_TTS
            and bool(settings.voice_id.strip())
            and self.ctx.tts.supports_voice_registry(settings.endpoint_id)
        ):
            return self.ctx.tts.has_voice_playback_api(settings.api_type, settings.endpoint_id)
        voice = persona.media.primary_voice()
        voice_path = self.ctx.user_personas.media_path(voice.path) if voice else None
        return bool(
            voice and voice_path and self.ctx.tts.has_voice_playback_api(settings.api_type, settings.endpoint_id)
        )

    def _narrator_tts_configured(self, tts_settings=None) -> bool:
        config = self.ctx.user_personas.get_tts_config()
        settings = tts_settings or config.narrator
        if settings.api_type == CHARACTER_TTS_API_GEN_SERVER:
            if settings.gen_server_tts_mode == CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3:
                return (
                    bool(settings.voice_caption.strip())
                    and self.ctx.tts.resolve_gen_server_voice_design_endpoint(raise_on_missing=False) is not None
                )
            return self.ctx.tts.resolve_gen_server_voice_clone_endpoint(raise_on_missing=False) is not None
        if settings.api_type != CHARACTER_TTS_API_TTS:
            return False
        endpoint = self.ctx.api_config.get_tts_endpoint(settings.endpoint_id)
        if endpoint is None:
            return False
        if endpoint.provider == TTS_PROVIDER_IRODORI_SERVER:
            return bool(settings.voice_id.strip()) and self.ctx.tts.supports_voice_registry(settings.endpoint_id)
        voice = config.narrator_voice
        voice_path = self.ctx.user_personas.media_path(voice.path) if voice else None
        return voice is not None and voice_path is not None

    def _voice_design_ready(self, settings) -> bool:
        return (
            settings.api_type == CHARACTER_TTS_API_GEN_SERVER
            and settings.gen_server_tts_mode == CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3
            and bool(settings.voice_caption.strip())
        )

    def _tts_target_for_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        role = str(message.get("role", ""))
        if role == "narration":
            config = self.ctx.user_personas.get_tts_config()
            settings = config.narrator
            if not self._narrator_tts_configured(settings):
                ui.notify("ナレーターTTS設定を確認してください", type="warning")
                return None
            voice = config.narrator_voice
            voice_path = self.ctx.user_personas.media_path(voice.path) if voice else None
            return {
                "target_id": "narrator",
                "settings": settings,
                "voice": voice,
                "voice_path": voice_path,
                "playback_save": self.ctx.user_personas.save_narrator_tts_playback,
            }
        if role == "character":
            member = self._member_by_id(str(message.get("speaker_id", "")))
            if member is None or not self._character_tts_configured(member):
                ui.notify("TTS設定を確認してください", type="warning")
                return None
            voice = member.character.media.primary_voice()
            voice_path = self.ctx.group_chats.media_path(voice.path) if voice else None
            return {
                "target_id": _member_tts_id(self.group.id, member.id),
                "settings": member.character.media.tts,
                "voice": voice,
                "voice_path": voice_path,
                "playback_save": lambda audio, member_id=member.id: self.ctx.group_chats.save_member_tts_playback(
                    self.group.id,
                    member_id,
                    audio,
                ),
            }
        if role == "user":
            persona = self.group.user_persona
            if persona is None or not self._user_persona_tts_configured(persona):
                ui.notify("ユーザーペルソナのTTS設定を確認してください", type="warning")
                return None
            settings = persona.media.tts
            voice = persona.media.primary_voice()
            voice_path = self.ctx.user_personas.media_path(voice.path) if voice else None
            if voice_path is None and not self._voice_design_ready(settings):
                ui.notify("ユーザーペルソナのTTS設定を確認してください", type="warning")
                return None
            persona_id = persona.id
            return {
                "target_id": _persona_tts_id(persona_id),
                "settings": settings,
                "voice": voice,
                "voice_path": voice_path,
                "playback_save": lambda audio, target_id=persona_id: (
                    self.ctx.user_personas.save_user_persona_tts_playback(target_id, audio)
                ),
            }
        return None

    async def play_tts_message(self, index: int) -> None:
        if self.tts_generating_index is not None:
            ui.notify("音声生成中です", type="info")
            return
        if index < 0 or index >= len(self.messages):
            return
        message = self.messages[index]
        role = str(message.get("role", ""))
        if role not in {"character", "user", "narration"}:
            return
        text = str(message.get("text", "")).strip()
        if not text or text in {"…", "..."}:
            ui.notify("読み上げる本文がありません", type="warning")
            return
        target = self._tts_target_for_message(message)
        if target is None:
            return
        settings = target["settings"]
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
            voice = target["voice"]

            def _save_playback(audio: bytes, job) -> dict[str, str]:
                playback_path = target["playback_save"](audio)
                return {
                    "playback_path": str(playback_path),
                    "result_url": self._result_url(),
                }

            job = self.ctx.tts.start_synthesize_job(
                target["target_id"],
                target["voice_path"],
                text,
                endpoint_id=settings.endpoint_id,
                voice_id=settings.voice_id,
                filename=voice.original_name if voice else "",
                content_type=voice.content_type if voice else "",
                api_type=settings.api_type,
                gen_server_tts_mode=settings.gen_server_tts_mode,
                voice_caption=settings.voice_caption,
                gen_server_params=settings.gen_server_params,
                label="グループチャット読み上げ",
                scope=f"group_tts:{self.active_session_id or self.group.id}",
                metadata={"message_index": index, "group_id": self.group.id},
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
        except Exception as err:  # noqa: BLE001 - UI通知のための包括捕捉
            ui.notify(f"読み上げに失敗しました: {err}", type="negative", timeout=10000)
        finally:
            self.tts_generating_index = None
            self.refresh_messages()

    # ------------------------------------------------------------------
    # 投稿・ターン実行
    # ------------------------------------------------------------------

    async def post_command_left_text(self, left_text: str) -> None:
        text = left_text.strip()
        if not text:
            return
        self.clear_input()
        if self.input_mode == "narration":
            self.messages.append(group_message("narration", text))
        elif self.input_mode == "memo":
            self.messages.append(group_message("memo", text))
        elif self.input_mode == "character":
            member = self._manual_character_speaker()
            if member is None:
                ui.notify("参加キャラがいません", type="warning")
                self.set_input_mode("user")
                return
            self.messages.append(group_message("character", text, member=member))
        elif self.input_mode == "guest":
            name = clean_guest_name(self.guest_input_name)
            if not name:
                ui.notify("ゲスト名を入力してください", type="warning")
                self.open_guest_input_mode_dialog(text)
                return
            self.messages.append(group_message("guest", text, guest_name=name))
        else:
            self.messages.append(group_message("user", text, user=self.group.user_persona))
        self.set_input_mode("user")
        self.refresh_messages(scroll_to_bottom=True)
        await self.save_current_session()

    async def append_character_turn(
        self,
        *,
        speaker: GroupMember | None = None,
        turn_instruction: str = "",
    ) -> None:
        if self.settings is None:
            ui.notify("先に「新しいセッション」を作成してください", type="warning")
            self.open_new_chat_dialog()
            return
        active = self.active_members()
        if not active:
            ui.notify("参加キャラがいません", type="warning")
            return
        llm = _configured_group_llm(self.ctx, str(self.settings.get("profile_id", "")))
        if llm is None or self.active_session_id is None:
            return

        prior_messages = [dict(message) for message in self.messages]
        display_speaker = speaker or active[0]
        self.messages.append(group_message("character", "…", member=display_speaker))
        self.refresh_messages(scroll_to_bottom=True)
        session_id = self.active_session_id
        title = self.title
        title_is_auto = self.active_title_is_auto
        settings_snapshot = dict(self.settings)
        await self.save_current_session(refresh_history=False)

        async def _runner(job) -> list[dict[str, Any]]:
            try:
                result = await self.ctx.group_chat_turns.run_character_turn(
                    group=self.group,
                    settings=settings_snapshot,
                    messages=prior_messages,
                    llm=llm,
                    active_members=active,
                    speaker=speaker,
                    turn_instruction=turn_instruction,
                )
                await self._save_session_messages_snapshot(
                    session_id=session_id,
                    title=title,
                    title_is_auto=title_is_auto,
                    settings=settings_snapshot,
                    messages=result.messages,
                )
                return result.messages
            except Exception:
                await self._save_session_messages_snapshot(
                    session_id=session_id,
                    title=title,
                    title_is_auto=title_is_auto,
                    settings=settings_snapshot,
                    messages=prior_messages,
                )
                raise

        job = self.ctx.ai_jobs.start_job(
            kind=AIJobKind.LLM_GROUP_CHAT,
            label=f"{self.group.name or 'グループ'}の発言生成",
            scope=self._active_scope(),
            metadata={"session_id": session_id, "group_id": self.group.id},
            runner=_runner,
        )
        self.ctx.ai_jobs.set_result_meta(job.id, {"result_url": self._result_url()})
        generated = await self._wait_for_active_group_job(job.id, failure_message="グループチャット生成に失敗しました")
        self.set_input_mode("user")
        if generated:
            self._focus_last_character()
            await self.maybe_generate_auto_title(llm)

    def _focus_last_character(self) -> None:
        for message in reversed(self.messages):
            if message.get("role") == "character":
                member = self._member_by_id(str(message.get("speaker_id", "")))
                if member is not None:
                    self.focus_participant(f"member:{member.id}")
                return

    async def append_guided_member_turn(
        self,
        speaker: GroupMember,
        *,
        turn_instruction: str = "",
        membership_action: str = "",
    ) -> None:
        if self.settings is None:
            ui.notify("先に「新しいセッション」を作成してください", type="warning")
            self.open_new_chat_dialog()
            return
        if self.active_session_id is None:
            return

        current_settings = dict(self.settings)
        current_ids = group_participant_ids(current_settings)
        if membership_action == "join":
            if speaker.id in current_ids:
                await self.append_character_turn(speaker=speaker, turn_instruction=turn_instruction)
                return
            generation_settings = settings_with_participant(current_settings, speaker.id)
            final_settings = dict(generation_settings)
            pre_events = [group_system_event_message(f"{speaker.character.name}が入場しました")]
            post_events: list[dict[str, Any]] = []
        elif membership_action == "leave":
            if speaker.id not in current_ids:
                ui.notify("退場させるキャラクターが現在のセッションに参加していません", type="warning")
                return
            if len(current_ids) <= 1:
                ui.notify("参加キャラクターがいなくなるため退場できません", type="warning")
                return
            generation_settings = dict(current_settings)
            final_settings = settings_without_participant(current_settings, speaker.id)
            pre_events = []
            post_events = [group_system_event_message(f"{speaker.character.name}が退場しました")]
        else:
            await self.append_character_turn(speaker=speaker, turn_instruction=turn_instruction)
            return

        llm = _configured_group_llm(self.ctx, str(current_settings.get("profile_id", "")))
        if llm is None:
            return

        original_messages = [dict(message) for message in self.messages]
        original_settings = dict(current_settings)
        prior_messages = [dict(message) for message in self.messages] + [dict(message) for message in pre_events]
        self.messages = prior_messages + [group_message("character", "…", member=speaker)]
        self.settings = dict(generation_settings)
        self.refresh_messages(scroll_to_bottom=True)
        self.refresh_mention_palette()
        self.refresh_role_menu()

        session_id = self.active_session_id
        title = self.title
        title_is_auto = self.active_title_is_auto
        await self.save_current_session(refresh_history=False)

        async def _runner(job) -> list[dict[str, Any]]:
            base_messages = [dict(message) for message in prior_messages]
            try:
                result = await self.ctx.group_chat_turns.run_character_turn(
                    group=self.group,
                    settings=generation_settings,
                    messages=base_messages,
                    llm=llm,
                    active_members=[speaker],
                    speaker=speaker,
                    turn_instruction=turn_instruction,
                )
                messages = result.messages + [dict(message) for message in post_events]
                await self._save_session_messages_snapshot(
                    session_id=session_id,
                    title=title,
                    title_is_auto=title_is_auto,
                    settings=final_settings,
                    messages=messages,
                )
                return messages
            except Exception:
                await self._save_session_messages_snapshot(
                    session_id=session_id,
                    title=title,
                    title_is_auto=title_is_auto,
                    settings=original_settings,
                    messages=original_messages,
                )
                raise

        job = self.ctx.ai_jobs.start_job(
            kind=AIJobKind.LLM_GROUP_CHAT,
            label=f"{self.group.name or 'グループ'}の発言生成",
            scope=self._active_scope(),
            metadata={"session_id": session_id, "group_id": self.group.id},
            runner=_runner,
        )
        self.ctx.ai_jobs.set_result_meta(job.id, {"result_url": self._result_url()})
        generated = await self._wait_for_active_group_job(job.id, failure_message="グループチャット生成に失敗しました")
        self.set_input_mode("user")
        self.refresh_mention_palette()
        self.refresh_role_menu()
        if generated:
            self._focus_last_character()
            await self.maybe_generate_auto_title(llm)

    async def append_guest_turn(self, guest_name: str, *, turn_instruction: str = "") -> None:
        name = clean_guest_name(guest_name)
        if not name:
            ui.notify("ゲスト名を入力してください", type="warning")
            return
        if self.settings is None:
            ui.notify("先に「新しいセッション」を作成してください", type="warning")
            self.open_new_chat_dialog()
            return
        llm = _configured_group_llm(self.ctx, str(self.settings.get("profile_id", "")))
        if llm is None or self.active_session_id is None:
            return

        prior_messages = [dict(message) for message in self.messages]
        self.messages.append(group_message("guest", "…", guest_name=name))
        self.refresh_messages(scroll_to_bottom=True)
        session_id = self.active_session_id
        title = self.title
        title_is_auto = self.active_title_is_auto
        settings_snapshot = dict(self.settings)
        await self.save_current_session(refresh_history=False)

        async def _runner(job) -> list[dict[str, Any]]:
            try:
                result = await self.ctx.group_chat_turns.run_guest_turn(
                    group=self.group,
                    settings=settings_snapshot,
                    messages=prior_messages,
                    llm=llm,
                    guest_name=name,
                    turn_instruction=turn_instruction,
                )
                await self._save_session_messages_snapshot(
                    session_id=session_id,
                    title=title,
                    title_is_auto=title_is_auto,
                    settings=settings_snapshot,
                    messages=result.messages,
                )
                return result.messages
            except Exception:
                await self._save_session_messages_snapshot(
                    session_id=session_id,
                    title=title,
                    title_is_auto=title_is_auto,
                    settings=settings_snapshot,
                    messages=prior_messages,
                )
                raise

        job = self.ctx.ai_jobs.start_job(
            kind=AIJobKind.LLM_GROUP_CHAT,
            label=f"{self.group.name or 'グループ'}のゲスト発言生成",
            scope=self._active_scope(),
            metadata={"session_id": session_id, "group_id": self.group.id},
            runner=_runner,
        )
        self.ctx.ai_jobs.set_result_meta(job.id, {"result_url": self._result_url()})
        generated = await self._wait_for_active_group_job(job.id, failure_message="ゲスト発言生成に失敗しました")
        self.set_input_mode("user")
        if generated:
            await self.maybe_generate_auto_title(llm)

    async def generate_scene(self, *, instruction: str = "") -> None:
        if self.settings is None:
            return
        try:
            llm = self.ctx.group_chat_assist.build_llm(
                str(self.settings.get("profile_id", "")),
                get_vault_password(),
            )
        except LLMRuntimeError as err:
            notify_setup_llm_error(err)
            return
        if self.active_session_id is None:
            return

        prior_messages = [dict(message) for message in self.messages]
        self.messages.append(group_message("narration", "…"))
        self.refresh_messages(scroll_to_bottom=True)
        session_id = self.active_session_id
        title = self.title
        title_is_auto = self.active_title_is_auto
        settings_snapshot = dict(self.settings)
        await self.save_current_session(refresh_history=False)

        async def _runner(job) -> list[dict[str, Any]]:
            try:
                generated = await self.ctx.group_chat_assist.generate_scene_message(
                    llm=llm,
                    group=self.group,
                    settings=settings_snapshot,
                    messages=prior_messages,
                    instruction=instruction,
                )
                messages = prior_messages + [generated]
                await self._save_session_messages_snapshot(
                    session_id=session_id,
                    title=title,
                    title_is_auto=title_is_auto,
                    settings=settings_snapshot,
                    messages=messages,
                )
                return messages
            except Exception:
                await self._save_session_messages_snapshot(
                    session_id=session_id,
                    title=title,
                    title_is_auto=title_is_auto,
                    settings=settings_snapshot,
                    messages=prior_messages,
                )
                raise

        job = self.ctx.ai_jobs.start_job(
            kind=AIJobKind.LLM_NARRATION,
            label="グループ地の文生成",
            scope=self._active_scope(),
            metadata={"session_id": session_id, "group_id": self.group.id},
            runner=_runner,
        )
        self.ctx.ai_jobs.set_result_meta(job.id, {"result_url": self._result_url()})
        await self._wait_for_active_group_job(job.id, failure_message="地の文生成に失敗しました")

    async def run_describe_action(self, left_text: str, *, instruction: str = "") -> None:
        if left_text.strip():
            await self.post_command_left_text(left_text)
        else:
            self.clear_input()
        self.set_input_mode("user")
        self.clear_input()
        try:
            await self.generate_scene(instruction=instruction)
        finally:
            self.clear_input()

    async def maybe_generate_auto_title(self, llm) -> None:
        if self.active_session_id is None or not self.active_title_is_auto:
            return
        if self.title_generation_attempted:
            return
        dialog_turns = [message for message in self.messages if message.get("role") in {"user", "character"}]
        if len(dialog_turns) < 4:
            return
        self.title_generation_attempted = True
        try:
            title = await self.ctx.group_chat_turns.generate_auto_title(
                group=self.group,
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

    # ------------------------------------------------------------------
    # 入力アシスト(補完・整え・選択肢)
    # ------------------------------------------------------------------

    async def fill_input_text(self, left_text: str) -> None:
        if self.settings is None:
            return
        if not left_text.strip():
            ui.notify("補完する文を /fill の左側に入力してください", type="warning")
            return
        completed = await self._await_assist(
            self.ctx.group_chat_assist.complete_input_text(
                profile_id=str(self.settings.get("profile_id", "")),
                vault_password=get_vault_password(),
                group=self.group,
                settings=self.settings,
                messages=self.messages,
                left_text=left_text,
                input_mode=self.input_mode,
                speaker=self._manual_character_speaker(),
                guest_name=self.guest_input_name,
                scope=self._assist_scope(),
                metadata=self._assist_metadata(),
                result_url=self._result_url(),
            ),
            failure_message="補完に失敗しました",
        )
        if completed is None:
            return
        self.set_input_value(str(completed))
        ui.notify("続きを補完しました", type="positive")
        self.focus_chat_input_at_end()

    async def tailor_input_text(self, left_text: str) -> None:
        if self.settings is None:
            return
        if not left_text.strip():
            ui.notify("書き換える文を /tailor の左側に入力してください", type="warning")
            return
        tailored = await self._await_assist(
            self.ctx.group_chat_assist.tailor_input_text(
                profile_id=str(self.settings.get("profile_id", "")),
                vault_password=get_vault_password(),
                group=self.group,
                settings=self.settings,
                messages=self.messages,
                left_text=left_text,
                input_mode=self.input_mode,
                speaker=self._manual_character_speaker(),
                guest_name=self.guest_input_name,
                scope=self._assist_scope(),
                metadata=self._assist_metadata(),
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

    async def show_response_choices(self, left_text: str) -> None:
        if self.settings is None:
            return
        choices = await self._await_assist(
            self.ctx.group_chat_assist.generate_response_choices(
                profile_id=str(self.settings.get("profile_id", "")),
                vault_password=get_vault_password(),
                group=self.group,
                settings=self.settings,
                messages=self.messages,
                left_text=left_text,
                input_mode=self.input_mode,
                speaker=self._manual_character_speaker(),
                guest_name=self.guest_input_name,
                scope=self._assist_scope(),
                metadata=self._assist_metadata(),
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
            ui.label("選ぶとその本文を入力欄に入れます。").classes("note")

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
                p3_button("閉じる", dlg.close, classes="btn quiet p3-choice-close").props(
                    "data-choice-index=close aria-selected=false"
                )
        dlg.open()
        self.run_page_javascript(_CHOICES_KEYBOARD_JS)

    # ------------------------------------------------------------------
    # /guide ・ /imitate ダイアログ
    # ------------------------------------------------------------------

    async def open_guide_next_turn_dialog(self, left_text: str = "") -> None:
        if left_text.strip():
            self.set_input_value(left_text)
        else:
            self.clear_input()
        active_ids = {member.id for member in self.active_members()}
        options = guide_actor_options(self.group, active_ids)

        with ui.dialog() as dlg, ui.card().classes("w-full max-w-xl").style(_DIALOG_CARD_STYLE):
            ui.label("次の行動").classes("text-base font-semibold")
            actor_select = (
                ui.select(options=options, value="auto", label="行動者")
                .props("outlined autofocus")
                .classes("w-full")
                .mark("ui2-group-guide-actor")
            )
            guest_input = (
                ui.input(label="ゲスト名", placeholder="例: 酒場のマスター")
                .props("outlined dense clearable")
                .classes("w-full p3-ta")
            )
            guest_input.set_visibility(False)
            direction_input = (
                ui.textarea(label="指示", placeholder="キャラ・ゲスト・地の文にだけ反映する任意の指示")
                .props("outlined rows=4 autogrow")
                .classes("w-full p3-ta")
            )
            leave_box = ui.element("div").classes("w-full")
            leave_state = {"value": False}

            def _sync_controls() -> None:
                value = str(actor_select.value or "auto")
                guest_input.set_visibility(value == "guest")
                if value == "user":
                    direction_input.set_value("")
                    direction_input.disable()
                else:
                    direction_input.enable()
                leave_box.clear()
                leave_state["value"] = False
                if value.startswith("member:"):
                    with leave_box:
                        checkbox = ui.checkbox("このターンの後に退場させる", value=False)
                        checkbox.on_value_change(lambda e: leave_state.update(value=bool(e.value)))

            actor_select.on_value_change(lambda _: _sync_controls())
            _sync_controls()

            async def _run() -> None:
                value = str(actor_select.value or "auto")
                direction = (direction_input.value or "").strip()
                dlg.close()
                if value == "user":
                    if left_text.strip():
                        await self.post_command_left_text(left_text)
                    else:
                        self.clear_input()
                        self.set_input_mode("user")
                    return
                if value == "narration":
                    await self.run_describe_action(left_text, instruction=direction)
                    return
                if left_text.strip():
                    await self.post_command_left_text(left_text)
                else:
                    self.clear_input()
                if value == "auto":
                    await self.append_character_turn(turn_instruction=direction)
                    return
                if value == "guest":
                    name = clean_guest_name(str(guest_input.value or ""))
                    if not name:
                        ui.notify("ゲスト名を入力してください", type="warning")
                        return
                    await self.append_guest_turn(name, turn_instruction=direction)
                    return
                if value.startswith("join:"):
                    member = self._member_by_id(value.removeprefix("join:"))
                    if member is None:
                        ui.notify("行動者を指定してください", type="warning")
                        return
                    await self.append_guided_member_turn(member, turn_instruction=direction, membership_action="join")
                    return
                member = self._member_by_id(value.removeprefix("member:"))
                if member is None:
                    ui.notify("行動者を指定してください", type="warning")
                    return
                if leave_state["value"]:
                    await self.append_guided_member_turn(member, turn_instruction=direction, membership_action="leave")
                    return
                await self.append_character_turn(speaker=member, turn_instruction=direction)

            with ui.row().classes("justify-end gap-2 mt-4 w-full"):
                p3_button("キャンセル", dlg.close, classes="btn quiet")
                p3_button("実行", _run, classes="btn primary").mark("ui2-group-guide-run")
        dlg.open()

    def open_imitate_character_dialog(self, left_text: str = "") -> None:
        active_ids = {member.id for member in self.active_members()}
        options = imitate_actor_options(self.group, active_ids)
        if not options:
            ui.notify("なりきれるキャラクターがいません", type="warning")
            return

        with ui.dialog() as dlg, ui.card().classes("w-full max-w-xl").style(_DIALOG_CARD_STYLE):
            ui.label("キャラクター入力（なりきり）").classes("text-base font-semibold")
            ui.label("次の投稿を、選んだ発言者の台詞として投稿します。").classes("note")
            actor_select = (
                ui.select(options=options, value=next(iter(options)), label="発言者")
                .props("outlined autofocus")
                .classes("w-full")
                .mark("ui2-group-imitate-actor")
            )
            guest_input = (
                ui.input(label="ゲスト名", placeholder="例: 酒場のマスター")
                .props("outlined dense clearable")
                .classes("w-full p3-ta")
            )
            guest_input.set_visibility(str(actor_select.value or "") == "guest")
            actor_select.on_value_change(
                lambda e: guest_input.set_visibility(str(e.value or "") == "guest")
            )

            async def _apply() -> None:
                value = str(actor_select.value or "")
                if value == "guest":
                    name = clean_guest_name(str(guest_input.value or ""))
                    if not name:
                        ui.notify("ゲスト名を入力してください", type="warning")
                        return
                    self.set_guest_input_mode(name)
                else:
                    member_id = value.removeprefix("member:").removeprefix("join:")
                    member = self._member_by_id(member_id)
                    if member is None:
                        ui.notify("発言者を指定してください", type="warning")
                        return
                    if self.settings is not None and member.id not in group_participant_ids(self.settings):
                        self.settings = settings_with_participant(self.settings, member.id)
                        self.messages.append(group_system_event_message(f"{member.character.name}が入場しました"))
                        self.refresh_messages(scroll_to_bottom=True)
                        await self.save_current_session(refresh_history=False)
                        self.refresh_mention_palette()
                        self.refresh_role_menu()
                        self.refresh_chat_header()
                    self.set_character_input_member(member)
                self.set_input_value(left_text.rstrip())
                self.focus_chat_input_at_end()
                dlg.close()
                ui.notify("入力モードにしました", type="info")

            with ui.row().classes("justify-end gap-2 mt-4 w-full"):
                p3_button("キャンセル", dlg.close, classes="btn quiet")
                p3_button("選択", _apply, classes="btn primary").mark("ui2-group-imitate-apply")
        dlg.open()

    # ------------------------------------------------------------------
    # 送信・コマンド実行
    # ------------------------------------------------------------------

    async def execute_chat_command(self, left_text: str, query: str) -> None:
        command = resolve_chat_command(query)
        if command is None:
            ui.notify("実行するコマンドを選択してください", type="warning")
            return

        left_text = left_text.rstrip()
        if command == "hold":
            if not left_text.strip():
                ui.notify("/hold の左側に投稿する文を入力してください", type="warning")
                return
            self.clear_input()
            await self.post_command_left_text(left_text)
            return
        if command == "guide":
            await self.open_guide_next_turn_dialog(left_text)
            return
        if command == "fill":
            self.set_input_value(left_text)
            await self.fill_input_text(left_text)
            return
        if command == "tailor":
            self.set_input_value(left_text)
            await self.tailor_input_text(left_text)
            return
        if command == "choices":
            self.set_input_value(left_text)
            await self.show_response_choices(left_text)
            return
        if command == "skip":
            if left_text.strip():
                ui.notify("/skip は単独で入力してください", type="warning")
                return
            self.clear_input()
            await self.append_character_turn()
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
            self.open_imitate_character_dialog(left_text)
            return
        if command == "user":
            self.set_input_value(left_text)
            self.set_input_mode("user", notify_change=True)
            return
        if command == "describe":
            await self.run_describe_action(left_text)
            return

    async def send_message(self, allow_skip: bool = False, submitted_text: str | None = None) -> None:
        if self.sending:
            return
        if self.settings is None:
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
            await self.execute_chat_command(left_text, query)
            return

        text = (raw_text or "").strip()
        if not text:
            if not allow_skip:
                ui.notify("メッセージを入力してください", type="warning")
                return
            await self.append_character_turn()
            return

        if self.input_mode in {"narration", "memo", "character", "guest"}:
            await self.post_command_left_text(text)
            return

        self.clear_input()
        self.messages.append(group_message("user", text, user=self.group.user_persona))
        self.set_input_mode("user")
        self.refresh_messages(scroll_to_bottom=True)
        await self.save_current_session(refresh_history=False)
        await self.append_character_turn()

    # ------------------------------------------------------------------
    # 新しいセッション
    # ------------------------------------------------------------------

    async def enhance_situation(
        self,
        profile_id: str,
        participant_ids: list[str],
        current_situation: str,
    ) -> str | None:
        current = current_situation.strip()
        if not current:
            ui.notify("先にシチュエーションを入力してください", type="warning")
            return None
        enhanced = await self._await_assist(
            self.ctx.group_chat_assist.enhance_situation(
                profile_id=profile_id,
                vault_password=get_vault_password(),
                group=self.group,
                participant_ids=participant_ids,
                current_situation=current,
                scope=self._assist_scope(),
                metadata=self._assist_metadata(),
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

    async def start_chat_session(self, settings: dict[str, Any], *, title: str = "") -> None:
        title = title.strip()
        self.settings = settings
        self.title = title or DEFAULT_GROUP_CHAT_TITLE
        self.active_title_is_auto = not title
        self.title_generation_attempted = False
        self.messages = []
        self.input_mode = "user"
        if self.input is not None:
            self.input.set_value("")
        situation = str(settings.get("situation", "") or "").strip()
        if situation:
            self.messages.append(group_message("narration", situation))
        saved = await self.ctx.group_chats.create_session(
            group_id=self.group.id,
            title=self.title,
            title_is_auto=self.active_title_is_auto,
            settings=settings,
            messages=self.messages,
        )
        self.active_session_id = saved.id
        self.sessions_by_id[saved.id] = saved
        await self.reload_sessions()
        self.refresh_input_mode_chip()
        self.refresh_chat_header()
        self.refresh_scene()
        self.refresh_messages(scroll_to_bottom=True)
        self.refresh_sessions_pane()
        self.refresh_mention_palette()
        self.refresh_role_menu()

    def open_new_chat_dialog(self) -> None:
        ctx = self.ctx
        profile_options = profile_options_for_context(ctx)
        default_profile = (
            self.group.completion_profile_id
            if self.group.completion_profile_id in profile_options
            else next(iter(profile_options), "")
        )
        member_checks: dict[str, Any] = {}

        with ui.dialog() as dlg, ui.card().classes("w-full max-w-2xl").style(_DIALOG_CARD_STYLE):
            ui.label("新しいセッション").classes("text-base font-semibold")
            if not profile_options:
                ui.label("LLMプロファイルが登録されていません。設定画面で追加してください。").classes(
                    "text-sm text-negative mt-2"
                )
            profile_select = (
                ui.select(options=profile_options, value=default_profile or None, label="LLMプロファイル")
                .props("outlined dense")
                .classes("w-full mt-3")
            )
            title_input = (
                ui.input(label="タイトル（任意）", placeholder="未入力なら自動タイトル")
                .props("outlined clearable")
                .classes("w-full p3-ta")
            )

            ui.label("参加キャラクター").classes("text-sm font-semibold mt-2")
            with ui.column().classes("w-full gap-1"):
                if not self.group.members:
                    ui.label("参加できるキャラクターがいません").classes("note")
                for member in self.group.members:
                    with ui.row().classes("items-center gap-2 w-full"):
                        _avatar_or_placeholder(member.character.media, member.character.name)
                        with ui.column().classes("gap-0 min-w-0 flex-1"):
                            ui.label(member.character.name).classes("text-sm font-semibold")
                            ui.label(f"@{member.handle}").classes("text-xs").style("color: var(--muted);")
                        member_checks[member.id] = ui.checkbox(value=True)

            with ui.element("div").style("position: relative; width: 100%;"):
                situation_input = (
                    ui.textarea(label="シチュエーション", placeholder="始まりの場面を記入")
                    .props("outlined rows=4")
                    .classes("w-full p3-ta")
                )
                enhance_btn = p3_button(
                    "補完",
                    lambda: _enhance_situation(),
                    classes="btn quiet",
                    title="シチュエーションをLLMで補完",
                )
                enhance_btn.style("position: absolute; right: 6px; top: 2px;")

            async def _enhance_situation() -> None:
                participant_ids = [member_id for member_id, checkbox in member_checks.items() if bool(checkbox.value)]
                situation_input.disable()
                try:
                    enhanced = await self.enhance_situation(
                        str(profile_select.value or ""),
                        participant_ids,
                        str(situation_input.value or ""),
                    )
                    if enhanced is not None:
                        situation_input.set_value(enhanced)
                finally:
                    situation_input.enable()

            async def _start() -> None:
                profile_id = str(profile_select.value or "")
                if not profile_id:
                    ui.notify("LLMプロファイルを選択してください", type="warning")
                    return
                participant_ids = [member_id for member_id, checkbox in member_checks.items() if bool(checkbox.value)]
                if not participant_ids:
                    ui.notify("参加キャラクターを1人以上選択してください", type="warning")
                    return
                title = str(title_input.value or "").strip()
                dlg.close()
                await self.start_chat_session(
                    {
                        "profile_id": profile_id,
                        "participant_ids": participant_ids,
                        "situation": str(situation_input.value or "").strip(),
                    },
                    title=title,
                )

            with ui.row().classes("justify-end gap-2 mt-4 w-full"):
                p3_button("キャンセル", dlg.close, classes="btn quiet")
                p3_button("開始", _start, classes="btn primary").mark("ui2-group-start-session")
        dlg.open()

    # ------------------------------------------------------------------
    # 管理(世界観・関係性・住人)+メンバー追加
    # ------------------------------------------------------------------

    def open_manage_dialog(self) -> None:
        ctx = self.ctx
        with ui.dialog() as dlg, ui.card().classes("w-full max-w-3xl").style(
            _DIALOG_CARD_STYLE + " max-height: 88vh;"
        ):
            with ui.row().classes("items-center justify-between w-full"):
                ui.label(f"{self.group.name} の管理").classes("text-base font-semibold")
                p3_button("閉じる", dlg.close, classes="btn quiet")
            with ui.scroll_area().style("height: min(64vh, 640px); width: 100%;"):
                body = ui.column().classes("w-full gap-4 pr-2")

            def _on_group_updated(saved: GroupChatRecord) -> None:
                self.apply_group_update(saved)
                _render_body()

            def _render_body() -> None:
                body.clear()
                with body:
                    ui.label("ワールド").classes("text-sm font-semibold")
                    ui.label(self.group.world or "未設定").classes("text-sm").style(
                        "white-space: pre-wrap; color: var(--muted); line-height: 1.8;"
                    )

                    with ui.row().classes("items-center justify-between w-full mt-2"):
                        ui.label("関係性").classes("text-sm font-semibold")
                        with ui.row().classes("gap-2"):
                            chip_button("追加", lambda: self._open_relationship_dialog(None, _on_group_updated))
                            chip_button(
                                "LLMで自動設定",
                                lambda: self._generate_group_relationship_drafts(_on_group_updated),
                                title="重要な関係だけをLLMがドラフトし、そのまま保存します",
                            )
                    labels = group_participant_labels(self.group)
                    if not self.group.relationships:
                        ui.label("設定済みの関係性はありません").classes("note")
                    for relationship in self.group.relationships:
                        with ui.element("div").classes("rel-row"):
                            with ui.element("div").classes("rel-head"):
                                left = labels.get(relationship.participant_a_key, "不明な参加者")
                                right = labels.get(relationship.participant_b_key, "不明な参加者")
                                with ui.element("span").classes("pair"):
                                    ui.html(html.escape(f"{left} ↔ {right}"))
                                ui.element("span").classes("sp")
                                chip_button(
                                    "編集",
                                    lambda r=relationship: self._open_relationship_dialog(r, _on_group_updated),
                                )

                                async def _delete_rel(rel_id: str = relationship.id) -> None:
                                    saved = await ctx.group_chats.delete_relationship(self.group.id, rel_id)
                                    if saved is None:
                                        ui.notify("グループが見つかりませんでした", type="warning")
                                        return
                                    ui.notify("関係性を削除しました", type="positive")
                                    _on_group_updated(saved)

                                chip_button("削除", _delete_rel)
                            with ui.element("div").classes("tx"):
                                ui.html(html.escape(relationship.description or "未設定"))

                    ui.label("住人").classes("text-sm font-semibold mt-2")
                    for member in self.group.members:
                        with ui.row().classes("items-center gap-2 w-full"):
                            _avatar_or_placeholder(member.character.media, member.character.name)
                            with ui.column().classes("gap-0 min-w-0 flex-1"):
                                ui.label(f"{member.character.name}（@{member.handle}）").classes(
                                    "text-sm font-semibold"
                                )
                                ui.label(entry_type_label(member.world_entry_type)).classes("text-xs").style(
                                    "color: var(--muted);"
                                )
                            chip_button(
                                "開く",
                                lambda mid=member.id: ui.navigate.to(
                                    f"/v2/groups/{self.group.id}/members/{mid}"
                                ),
                            )
                    persona = self.group.user_persona
                    if persona is not None:
                        with ui.row().classes("items-center gap-2 w-full"):
                            _avatar_or_placeholder(persona.media, persona.display_name or persona.name or "ユーザー")
                            with ui.column().classes("gap-0 min-w-0 flex-1"):
                                ui.label(
                                    f"{persona.display_name or persona.name or 'ユーザー'}（@{persona.handle}）"
                                ).classes("text-sm font-semibold")
                                ui.label("あなた — グループ専用ペルソナ").classes("text-xs").style(
                                    "color: var(--muted);"
                                )
                            chip_button("開く", lambda: ui.navigate.to(f"/v2/groups/{self.group.id}/persona"))
                    with ui.row().classes("gap-2 mt-1"):
                        chip_button("+ 既存キャラを適応して迎える", lambda: (dlg.close(), self.open_add_member_dialog()))
                        chip_button(
                            "+ この世界で生成",
                            lambda: ui.navigate.to(f"/groups/{self.group.id}/generation"),
                            title="グループ内キャラクター生成(旧ページ・Phase 5 で /v2 版に)",
                        )

                    ui.label("危険な操作").classes("text-sm font-semibold mt-2")

                    def _confirm_delete_group() -> None:
                        with ui.dialog() as confirm, ui.card().classes("w-full max-w-md").style(_DIALOG_CARD_STYLE):
                            ui.label(f"「{self.group.name}」を削除しますか？").classes("text-base font-semibold")
                            ui.label("セッション・住人・メディアも削除されます。元に戻せません。").classes("note")

                            async def _delete() -> None:
                                confirm.close()
                                dlg.close()
                                deleted = await ctx.group_chats.delete_group(self.group.id)
                                if deleted:
                                    ui.notify("グループを削除しました", type="positive")
                                    ui.navigate.to("/v2/groups")
                                else:
                                    ui.notify("グループが見つかりませんでした", type="warning")

                            with ui.row().classes("justify-end gap-2 mt-4 w-full"):
                                p3_button("キャンセル", confirm.close, classes="btn quiet")
                                p3_button("削除", _delete, classes="btn primary")
                        confirm.open()

                    p3_button("グループを削除", _confirm_delete_group, classes="btn quiet").style("color: #c98;")

            _render_body()
        dlg.open()

    def _open_relationship_dialog(self, relationship: GroupRelationship | None, on_group_updated) -> None:
        ctx = self.ctx
        options = group_participant_labels(self.group)
        if len(options) < 2:
            ui.notify("関係性を設定できる参加者が足りません", type="warning")
            return
        keys = list(options)
        first_value = relationship.participant_a_key if relationship else keys[0]
        second_value = relationship.participant_b_key if relationship else keys[1]

        with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg").style(_DIALOG_CARD_STYLE):
            ui.label("関係性を編集" if relationship else "関係性を追加").classes("text-base font-semibold")
            first_select = (
                ui.select(options=options, value=first_value if first_value in options else keys[0], label="参加者1")
                .props("outlined dense")
                .classes("w-full")
            )
            second_select = (
                ui.select(options=options, value=second_value if second_value in options else keys[1], label="参加者2")
                .props("outlined dense")
                .classes("w-full")
            )
            description_input = (
                ui.textarea(
                    label="関係性",
                    value=relationship.description if relationship else "",
                    placeholder="例: 幼なじみだが、現在は互いに距離を測っている。",
                )
                .props("outlined rows=5")
                .classes("w-full p3-ta")
                .mark("ui2-group-rel-description")
            )

            async def _enhance() -> None:
                participants = [
                    {
                        "key": f"member:{member.id}",
                        "id": member.id,
                        "name": member.character.name,
                        "summary": compact_character_summary(member.character),
                        "kind": "character",
                    }
                    for member in self.group.members
                ]
                if self.group.user_persona is not None:
                    persona = self.group.user_persona
                    participants.append(
                        {
                            "key": f"user:{persona.id}",
                            "id": persona.id,
                            "name": persona.display_name or persona.name or "ユーザー",
                            "summary": persona.description,
                            "kind": "user_persona",
                        }
                    )
                if self.busy is not None:
                    self.busy.begin("関係性を補完しています...")
                try:
                    enhanced = await enhance_relationship_text(
                        ctx,
                        self.group.completion_profile_id,
                        world=self.group.world,
                        participants=participants,
                        first_key=str(first_select.value or ""),
                        second_key=str(second_select.value or ""),
                        current_description=str(description_input.value or ""),
                        on_job_started=self.busy.set_job if self.busy is not None else None,
                    )
                    if enhanced:
                        description_input.set_value(enhanced)
                finally:
                    if self.busy is not None:
                        self.busy.end()

            chip_button("関係性を補完", _enhance, title="入力内容を核に具体性だけ補う")

            async def _save() -> None:
                first_key = str(first_select.value or "")
                second_key = str(second_select.value or "")
                description = str(description_input.value or "").strip()
                if not first_key or not second_key:
                    ui.notify("参加者を選択してください", type="warning")
                    return
                if first_key == second_key:
                    ui.notify("異なる2人を選択してください", type="warning")
                    return
                if not description:
                    ui.notify("関係性を入力してください", type="warning")
                    return
                saved = await ctx.group_chats.save_relationship(
                    self.group.id,
                    GroupRelationship(
                        id=relationship.id if relationship else "",
                        participant_a_key=first_key,
                        participant_b_key=second_key,
                        description=description,
                    ),
                )
                if saved is None:
                    ui.notify("グループが見つかりませんでした", type="warning")
                    return
                dlg.close()
                ui.notify("関係性を保存しました", type="positive")
                on_group_updated(saved)

            with ui.row().classes("justify-end gap-2 mt-4 w-full"):
                p3_button("キャンセル", dlg.close, classes="btn quiet")
                p3_button("保存", _save, classes="btn primary").mark("ui2-group-rel-save")
        dlg.open()

    async def _generate_group_relationship_drafts(self, on_group_updated) -> None:
        """既存グループの関係性を LLM でドラフト生成し、そのまま保存する。"""
        ctx = self.ctx
        characters = [member.character for member in self.group.members]
        persona = self.group.user_persona
        if len(characters) + (1 if persona is not None else 0) < 2:
            ui.notify("関係性を自動設定できる参加者が足りません", type="warning")
            return
        state = draft_state_from_group(self.group)
        if self.busy is not None:
            self.busy.begin("関係性を自動設定しています...")
        try:
            generated = await run_assist(
                ctx.group_chat_assist.generate_relationship_drafts(
                    profile_id=self.group.completion_profile_id,
                    vault_password=get_vault_password(),
                    characters=characters,
                    persona=persona,
                    world=self.group.world,
                    state=state,
                    on_job_started=self.busy.set_job if self.busy is not None else None,
                ),
                failure_message="関係性自動設定に失敗しました",
            )
        finally:
            if self.busy is not None:
                self.busy.end()
        if generated is None:
            return
        generated = list(generated or [])
        if not generated:
            ui.notify("関係性を自動設定できませんでした", type="warning")
            return
        key_map = relationship_key_map_for_group(self.group)
        saved_group: GroupChatRecord | None = None
        saved_count = 0
        for item in generated:
            item["id"] = next_relationship_draft_id(state)
            first = key_map.get(str(item.get("participant_a_key") or ""))
            second = key_map.get(str(item.get("participant_b_key") or ""))
            description = str(item.get("description") or "").strip()
            if not first or not second or first == second or not description:
                continue
            saved = await ctx.group_chats.save_relationship(
                self.group.id,
                GroupRelationship(
                    id="",
                    participant_a_key=first,
                    participant_b_key=second,
                    description=description,
                ),
            )
            if saved is not None:
                saved_group = saved
                saved_count += 1
        if saved_group is None or saved_count == 0:
            ui.notify("関係性を保存できませんでした", type="warning")
            return
        ui.notify(f"関係性を{saved_count}件追加しました", type="positive")
        on_group_updated(saved_group)

    def open_add_member_dialog(self) -> None:
        """既存キャラをこの世界へ適応して迎える(旧 open_add_group_character_dialog の P3 版)。"""
        ctx = self.ctx
        existing_source_ids = {
            member.source_character_id or member.character.id
            for member in self.group.members
            if member.source_character_id or member.character.id
        }
        existing_handles = {member.handle.lower() for member in self.group.members}
        if self.group.user_persona is not None:
            existing_handles.add(self.group.user_persona.handle.lower())

        selected: dict[str, list[CharacterSheet]] = {"characters": []}
        state: dict[str, Any] = {
            "handle_values": {},
            "entry_modes": {},
            "arrival_reasons": {},
            "adaptation_notes": {},
            "adaptation_instructions": {},
            "draft_sheets": {},
        }
        busy = self.busy or BusyController()

        def _profile_id() -> str:
            return self.group.completion_profile_id

        def _world_text() -> str:
            return (self.group.world or "").strip()

        with ui.dialog() as dlg, ui.card().classes("w-full max-w-2xl").style(_DIALOG_CARD_STYLE):
            ui.label("既存キャラを適応して迎える").classes("text-base font-semibold")
            ui.label(
                "選んだキャラクターはこの世界のグループ内コピーとして保存されます（元は変わりません）。"
                "チップをクリックするとハンドル・参加設定・来訪理由・適応を編集できます。"
            ).classes("note")
            picks_box = ui.element("div").classes("picks w-full").style("margin-top: 10px;")

            def _resident_status(sheet: CharacterSheet) -> str:
                key = f"character:{sheet.id}"
                parts = [entry_type_label(state["entry_modes"].get(key, "native"))]
                if state["adaptation_notes"].get(key):
                    parts.append("適応済")
                return "・".join(parts)

            def _open_settings(sheet: CharacterSheet) -> None:
                display = state["draft_sheets"].get(sheet.id, sheet)
                open_resident_settings_dialog(
                    ctx,
                    state=state,
                    key=f"character:{sheet.id}",
                    display_name=display.name,
                    summary=compact_character_summary(display),
                    sheet=sheet,
                    world_getter=_world_text,
                    profile_getter=_profile_id,
                    busy=busy,
                    on_change=_refresh_picks,
                )

            def _remove(character_id: str) -> None:
                selected["characters"] = [
                    sheet for sheet in selected["characters"] if sheet.id != character_id
                ]
                key = f"character:{character_id}"
                for bucket in ("entry_modes", "arrival_reasons", "adaptation_notes", "adaptation_instructions"):
                    state[bucket].pop(key, None)
                state["handle_values"].pop(character_id, None)
                state["draft_sheets"].pop(character_id, None)
                _refresh_picks()

            async def _open_picker() -> None:
                async def _add(sheet: CharacterSheet) -> None:
                    if sheet.id in existing_source_ids:
                        ui.notify("このキャラクターは既にグループにいます", type="warning")
                        return
                    selected["characters"].append(sheet)
                    state["entry_modes"].setdefault(f"character:{sheet.id}", "native")
                    state["handle_values"].setdefault(
                        sheet.id, fallback_handle(sheet, len(self.group.members) + len(selected["characters"]))
                    )
                    _refresh_picks()

                await open_character_pick_dialog(
                    ctx,
                    title="グループに追加するキャラクターを選択",
                    exclude_ids=existing_source_ids | {sheet.id for sheet in selected["characters"]},
                    on_select=_add,
                )

            async def _generate_all_handles() -> None:
                busy.begin("ハンドルを生成しています...")
                try:
                    generated = await generate_handles_values(
                        ctx,
                        _profile_id(),
                        [state["draft_sheets"].get(sheet.id, sheet) for sheet in selected["characters"]],
                        self.group.user_persona,
                        reserved_handles=existing_handles,
                        include_user=False,
                        on_job_started=busy.set_job,
                    )
                    if generated is None:
                        return
                    values, _ = generated
                    state["handle_values"].update(values)
                    _refresh_picks()
                finally:
                    busy.end()

            def _refresh_picks() -> None:
                picks_box.clear()
                with picks_box:
                    for sheet in selected["characters"]:
                        display = state["draft_sheets"].get(sheet.id, sheet)
                        pick = ui.element("button").classes("pick").props(
                            f'title="クリックで参加設定を編集: '
                            f'@{html.escape(str(state["handle_values"].get(sheet.id) or ""))}"'
                        )
                        pick.on("click", lambda s=sheet: _open_settings(s))
                        with pick:
                            image = sheet.media.primary_image()
                            url = media_url(image.path) if image is not None else None
                            if url is not None:
                                raw_img(url).style(f"object-position: {image_object_position(image)};")
                            else:
                                with ui.element("span").classes("pick-ph"):
                                    ui.html(html.escape((display.name or "?")[:1]))
                            ui.html(html.escape(display.name))
                            with ui.element("span").classes("st"):
                                ui.html(html.escape(_resident_status(sheet)))
                            x = ui.element("span").classes("x").props('title="はずす"')
                            with x:
                                ui.html("×")
                            x.on("click.stop", lambda cid=sheet.id: _remove(cid))
                    chip_button("+ キャラクターを選択", _open_picker).mark("ui2-group-add-pick")
                    if selected["characters"]:
                        chip_button("ハンドルを一括生成", _generate_all_handles)

            async def _add_members() -> None:
                if not selected["characters"]:
                    ui.notify("キャラクターを選択してください", type="warning")
                    return
                validation = validate_handle_values(
                    selected["characters"],
                    state["handle_values"],
                    None,
                    reserved=existing_handles,
                )
                if not validation.ok:
                    ui.notify(validation.error, type="warning")
                    return
                prepared_members: list[tuple[CharacterSheet, str]] = []
                member_world_settings: dict[str, dict[str, str]] = {}
                for sheet, handle in zip(selected["characters"], validation.handles, strict=True):
                    key = f"character:{sheet.id}"
                    entry_type = state["entry_modes"].get(key, "native")
                    if entry_type == "visitor" and not state["arrival_reasons"].get(key, "").strip():
                        ui.notify(f"{sheet.name} の来訪理由を入力してください", type="warning")
                        return
                    source_sheet = state["draft_sheets"].get(sheet.id, sheet) if entry_type == "native" else sheet
                    prepared_sheet, settings = prepare_group_character_for_world(
                        source_sheet,
                        world=_world_text(),
                        source_character_id="",
                        entry_type=entry_type,
                        arrival_reason=state["arrival_reasons"].get(key, ""),
                        adaptation_note=state["adaptation_notes"].get(key, "") if entry_type == "native" else "",
                    )
                    prepared_members.append((prepared_sheet, handle))
                    member_world_settings[prepared_sheet.id] = settings
                saved = await ctx.group_chats.add_members(
                    self.group.id,
                    prepared_members,
                    member_world_settings=member_world_settings,
                )
                if saved is None:
                    ui.notify("グループが見つかりませんでした", type="warning")
                    return
                dlg.close()
                ui.notify("キャラクターを追加しました", type="positive")
                self.apply_group_update(saved)
                # presence は再構築が必要なためページを開き直す
                ui.navigate.to(self._result_url())

            _refresh_picks()
            with ui.row().classes("justify-end gap-2 mt-4 w-full"):
                p3_button("キャンセル", dlg.close, classes="btn quiet")
                p3_button("追加", _add_members, classes="btn primary").mark("ui2-group-add-save")
        dlg.open()


@ui.page("/v2/groups/{group_id}")
async def ui2_group_page(group_id: str) -> None:
    ctx = get_context()
    group = await ctx.group_chats.get(group_id)

    if group is None:
        with p3_page("グループ"):
            with ui.element("div").style("max-width: 640px; margin: 0 auto; padding: 60px 26px;"):
                ui.label("指定されたグループは存在しません。").classes("note").style("font-size: 14px;")
                with ui.element("div").style("margin-top: 18px;"):
                    p3_button("グループ一覧へ", lambda: ui.navigate.to("/v2/groups"))
        return

    controller = Ui2GroupChatController(ctx, group, ui.context.client)
    await controller.initialize()

    with p3_page("グループ"):
        ui.add_css(_PAGE_CSS)
        controller.render_band()
        controller.render_shell()
