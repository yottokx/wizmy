"""グループチャット一覧とグループ作成 UI。"""

from __future__ import annotations

import difflib
import html as _html
import json
import random
import re
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from nicegui import app, ui

from ...app_context import get_context
from ...core.character.schemas import (
    CHARACTER_GEN_SERVER_TTS_MODE_VOICE_DESIGN_V3,
    CHARACTER_TTS_API_GEN_SERVER,
    CHARACTER_TTS_API_TTS,
    CharacterMedia,
    CharacterSheet,
)
from ...core.group_chat.schemas import (
    GroupChatRecord,
    GroupMember,
    GroupRelationship,
    GroupUserPersona,
)
from ...core.group_chat.sessions import DEFAULT_GROUP_CHAT_TITLE, GroupChatSessionRecord
from ...core.llm.factory import create_llm
from ...core.tts.schemas import TTS_PROVIDER_IRODORI_SERVER
from ...services.ai_jobs import AIJobKind, AIJobStatus
from ...services.character_generation import parse_markdown_to_sheet
from ...services.tts import TTSServiceError
from ..chat import components as chat_components
from ..chat.commands import (
    clean_short_llm_text,
    command_suggestions,
    merge_completion,
    parse_command_input,
    parse_response_choices,
    resolve_chat_command,
)
from ..chat.media import cropped_background_style
from ..chat.models import ChatDebugInfo, ChatThreadPreview, time_label
from ..chat.prompts import (
    build_debug_info,
    character_summary,
    format_llm_input,
    message_content_to_text,
    sanitize_character_reply,
    sanitize_chat_title,
)
from ..chat.style import CHAT_CSS
from ..components.character_picker import open_character_picker
from ..layout import page_layout
from ..state import get_vault_password


GROUP_CHAT_CSS = """
<style>
.cs-group-page {
  width: min(1180px, 100%);
  margin: 0 auto;
}
.cs-group-page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}
.cs-group-page-title {
  font-size: 1.35rem;
  font-weight: 800;
  line-height: 1.2;
}
.cs-group-page-subtitle {
  margin-top: 4px;
  font-size: 0.86rem;
  color: var(--cs-muted);
}
.cs-group-home-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(280px, 0.75fr);
  gap: 16px;
  align-items: start;
}
.cs-group-section-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  color: var(--cs-muted);
}
.cs-group-section-head .q-icon {
  color: var(--cs-accent);
}
.cs-group-section-title {
  font-size: 0.78rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.cs-group-card-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.cs-group-card,
.cs-group-recent-item {
  display: grid;
  gap: 10px;
  min-width: 0;
  padding: 14px;
  border: 1px solid var(--cs-border);
  border-radius: 8px;
  background: var(--cs-surface);
  color: var(--cs-text);
  box-shadow: 0 1px 5px rgba(0,0,0,0.05);
}
.cs-group-card-title-row,
.cs-group-recent-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
}
.cs-group-card-title,
.cs-group-recent-title {
  min-width: 0;
  font-size: 1rem;
  font-weight: 800;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cs-group-card-meta,
.cs-group-recent-time {
  flex: 0 0 auto;
  font-size: 0.72rem;
  color: var(--cs-muted);
}
.cs-group-card-world,
.cs-group-recent-preview {
  font-size: 0.82rem;
  line-height: 1.55;
  color: var(--cs-muted);
  overflow-wrap: anywhere;
}
.cs-group-avatar-stack {
  display: flex;
  align-items: center;
  min-height: 34px;
}
.cs-group-avatar-stack .cs-group-face {
  margin-right: -7px;
}
.cs-group-face {
  width: 36px;
  height: 36px;
  flex: 0 0 36px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--cs-border);
  border-radius: 999px;
  background: var(--cs-surface-soft);
  color: var(--cs-muted);
  font-size: 0.72rem;
  font-weight: 800;
  overflow: hidden;
}
.cs-group-selected-list {
  display: grid;
  gap: 8px;
  width: 100%;
  max-height: min(420px, 44vh);
  overflow-y: auto;
  overflow-x: hidden;
  padding: 8px;
  border: 1px solid var(--cs-border);
  border-radius: 8px;
  background: var(--cs-surface-soft);
  box-sizing: border-box;
}
.cs-group-selected-row {
  display: grid;
  grid-template-columns: 48px minmax(0, 1fr) minmax(150px, 180px) 32px;
  gap: 10px;
  align-items: center;
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  padding: 9px;
  border: 1px solid var(--cs-border);
  border-radius: 8px;
  background: var(--cs-surface);
}
.cs-group-selected-row .q-field {
  min-width: 0;
}
.cs-group-selected-face {
  width: 48px;
  height: 48px;
  border: 1px solid var(--cs-border);
  border-radius: 8px;
  background: var(--cs-surface-soft);
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--cs-muted);
  font-weight: 800;
}
.cs-group-selected-info {
  min-width: 0;
  overflow: hidden;
}
.cs-group-selected-name {
  min-width: 0;
  font-size: 0.9rem;
  font-weight: 800;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cs-group-selected-meta {
  min-width: 0;
  font-size: 0.76rem;
  color: var(--cs-muted);
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow-wrap: anywhere;
  line-height: 1.35;
}
.cs-group-modal-section {
  display: grid;
  gap: 8px;
}
.cs-group-modal-actions,
.cs-group-persona-row {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  width: 100%;
}
.cs-group-modal-actions {
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
}
.cs-group-persona-row .q-field {
  min-width: 0;
}
.cs-group-note {
  font-size: 0.76rem;
  line-height: 1.5;
  color: var(--cs-muted);
}
.cs-group-world-field {
  position: relative;
  width: 100%;
}
.cs-group-world-field .q-field__control {
  padding-right: 44px;
}
.cs-group-world-enhance {
  position: absolute;
  top: 10px;
  right: 10px;
  z-index: 2;
  width: 32px !important;
  height: 32px !important;
  min-height: 32px !important;
  color: var(--cs-muted) !important;
  background: color-mix(in srgb, var(--cs-surface) 80%, transparent) !important;
  border: 1px solid transparent !important;
}
.cs-group-world-enhance:hover {
  color: var(--cs-accent) !important;
  background: var(--cs-accent-bg) !important;
  border-color: var(--cs-accent-border) !important;
}
.cs-group-chat-shell {
  grid-template-columns: minmax(250px, 300px) minmax(250px, 320px) minmax(380px, 1fr);
}
.cs-group-profile-shell {
  min-height: 100%;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 10px;
  background: var(--cs-surface);
  color: var(--cs-text);
}
.cs-group-profile-switch {
  display: grid;
  grid-template-columns: 1fr 1fr;
  border: 1px solid var(--cs-border);
  border-radius: 8px 8px 0 0;
  overflow: hidden;
  background: var(--cs-surface-soft);
}
.cs-group-profile-switch-item {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-height: 40px;
  border: 0;
  background: transparent;
  color: var(--cs-muted);
  font-size: 0.83rem;
  font-weight: 800;
  cursor: pointer;
}
.cs-group-profile-switch-item-active {
  color: var(--cs-accent);
  background: var(--cs-accent-bg);
  border-bottom: 2px solid var(--cs-accent);
}
.cs-group-portrait {
  position: relative;
  width: 100%;
  aspect-ratio: 4 / 5;
  min-height: 0;
  border: 1px solid var(--cs-border);
  border-radius: 8px;
  overflow: hidden;
  background-color: var(--cs-surface-soft);
  background-size: cover;
  background-position: center;
}
.cs-group-profile-compact .cs-group-portrait {
  aspect-ratio: 16 / 10;
}
.cs-group-portrait-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--cs-muted);
}
.cs-group-face-strip {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-top: -2px;
  flex-wrap: wrap;
}
.cs-group-avatar-button {
  padding: 0;
  border: 0;
  background: transparent;
  cursor: pointer;
}
.cs-group-avatar-button .cs-group-face {
  border-color: var(--cs-border);
  box-shadow: 0 0 0 2px var(--cs-surface);
  transition: border-color 0.12s ease, box-shadow 0.12s ease, transform 0.12s ease;
}
.cs-group-avatar-button:hover .cs-group-face,
.cs-group-avatar-button.cs-group-avatar-selected .cs-group-face {
  border-color: var(--cs-accent);
  box-shadow: 0 0 0 3px var(--cs-accent-bg);
  transform: translateY(-1px);
}
.cs-group-face-large {
  width: 42px;
  height: 42px;
  flex-basis: 42px;
}
.cs-group-profile-name {
  text-align: center;
  font-size: 1.16rem;
  font-weight: 900;
  line-height: 1.35;
  overflow-wrap: anywhere;
}
.cs-group-handle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  width: fit-content;
  max-width: 100%;
  margin: 0 auto;
  padding: 3px 8px;
  border: 1px solid var(--cs-accent-border);
  border-radius: 999px;
  background: var(--cs-accent-bg);
  color: var(--cs-accent);
  font-size: 0.75rem;
  font-weight: 800;
}
.cs-group-profile-add {
  width: fit-content;
  margin: 0 auto;
  border-color: var(--cs-accent-border) !important;
  color: var(--cs-accent) !important;
}
.cs-group-profile-actions {
  display: flex;
  justify-content: center;
  gap: 8px;
  flex-wrap: wrap;
}
.cs-group-profile-action {
  width: fit-content;
  border-color: var(--cs-accent-border) !important;
  color: var(--cs-accent) !important;
}
.cs-group-profile-card {
  display: grid;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--cs-border);
  border-radius: 8px;
  background: var(--cs-surface-soft);
}
.cs-group-profile-card-title {
  color: var(--cs-accent);
  font-size: 0.78rem;
  font-weight: 800;
  letter-spacing: 0.02em;
}
.cs-group-relationship-list {
  display: grid;
  gap: 8px;
}
.cs-group-relationship-row {
  display: grid;
  gap: 5px;
  min-width: 0;
  padding: 9px;
  border: 1px solid var(--cs-border);
  border-radius: 8px;
  background: var(--cs-surface);
}
.cs-group-relationship-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}
.cs-group-relationship-pair {
  min-width: 0;
  color: var(--cs-text);
  font-size: 0.8rem;
  font-weight: 800;
  overflow-wrap: anywhere;
}
.cs-group-relationship-text {
  color: var(--cs-text);
  font-size: 0.8rem;
  line-height: 1.55;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.cs-group-profile-grid {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 7px 14px;
}
.cs-group-profile-label {
  color: var(--cs-muted);
  font-size: 0.76rem;
  font-weight: 700;
}
.cs-group-profile-value,
.cs-group-profile-summary {
  color: var(--cs-text);
  overflow-wrap: anywhere;
}
.cs-group-profile-value {
  font-size: 0.8rem;
}
.cs-group-profile-summary {
  color: var(--cs-text);
  font-size: 0.82rem;
  line-height: 1.62;
  white-space: pre-wrap;
}
.cs-group-speaker {
  font-size: 0.74rem;
  font-weight: 800;
  color: var(--cs-accent);
}
.cs-group-mention-palette {
  position: absolute;
  left: 56px;
  right: 64px;
  bottom: calc(100% - 4px);
  z-index: 17;
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: min(42vh, 320px);
  overflow: auto;
  padding: 6px;
  border: 1px solid var(--cs-border);
  border-radius: 8px;
  background: var(--cs-surface);
  background: color-mix(in srgb, var(--cs-surface) 90%, transparent);
  box-shadow: 0 10px 28px rgba(0,0,0,0.18);
  backdrop-filter: blur(12px);
}
.cs-group-mention-palette-hidden,
.cs-group-mention-option-hidden {
  display: none !important;
}
.cs-group-mention-option {
  width: 100%;
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr) auto;
  align-items: center;
  gap: 9px;
  padding: 7px 9px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--cs-text);
  text-align: left;
  cursor: pointer;
}
.cs-group-mention-option:hover,
.cs-group-mention-option-active {
  background: var(--cs-accent-bg);
  background: color-mix(in srgb, var(--cs-accent-bg) 76%, transparent);
}
.cs-group-mention-option .cs-group-face {
  width: 30px;
  height: 30px;
  flex-basis: 30px;
}
.cs-group-mention-info {
  min-width: 0;
  display: grid;
  gap: 1px;
}
.cs-group-mention-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.82rem;
  font-weight: 800;
}
.cs-group-mention-handle {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.75rem;
  color: var(--cs-accent);
  font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
}
.cs-group-mention-kind {
  justify-self: end;
  font-size: 0.7rem;
  color: var(--cs-muted);
}
.cs-group-select-trigger {
  width: 100%;
  min-height: 44px;
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr) 20px;
  align-items: center;
  gap: 9px;
  padding: 6px 10px;
  border: 1px solid var(--cs-border);
  border-radius: 8px;
  background: var(--cs-surface);
  color: var(--cs-text);
  text-align: left;
  cursor: pointer;
}
.cs-group-select-trigger:hover,
.cs-group-menu-parent:hover,
.cs-group-menu-option:hover {
  background: var(--cs-accent-bg);
  background: color-mix(in srgb, var(--cs-accent-bg) 72%, transparent);
}
.cs-group-select-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.9rem;
  font-weight: 700;
}
.cs-group-select-hint {
  color: var(--cs-muted);
  font-size: 0.72rem;
  font-weight: 600;
}
.cs-group-select-trigger .cs-group-face,
.cs-group-menu-option .cs-group-face,
.cs-group-menu-parent .cs-group-face {
  width: 30px;
  height: 30px;
  flex-basis: 30px;
}
.cs-group-select-role-icon {
  width: 30px;
  height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: var(--cs-muted-bg);
  color: var(--cs-accent);
}
.cs-group-select-menu {
  min-width: 280px;
}
.cs-group-menu-option,
.cs-group-menu-parent {
  width: 100%;
  min-height: 40px;
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr) 18px;
  align-items: center;
  gap: 9px;
  padding: 6px 10px;
  border: 0;
  background: transparent;
  color: var(--cs-text);
  text-align: left;
  cursor: pointer;
}
.cs-group-menu-parent {
  grid-template-columns: 34px minmax(0, 1fr) 18px;
}
.cs-group-menu-option-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.84rem;
  font-weight: 700;
}
.cs-group-character-submenu {
  min-width: 260px;
}
.cs-chat-message-row .cs-group-face {
  width: 56px;
  height: 56px;
  flex-basis: 56px;
}
.cs-chat-message-row .cs-group-face .q-icon {
  font-size: 1.45rem;
}
.cs-group-face-guest {
  background: var(--cs-accent-bg);
  border-color: var(--cs-accent-border);
  color: var(--cs-accent);
}
.cs-group-message-row-user .cs-chat-bubble {
  background: var(--cs-accent);
  border-color: var(--cs-accent);
  color: #fff;
}
.cs-group-message-row-user .cs-group-speaker,
.cs-group-message-row-user .cs-chat-message-time {
  color: rgba(255,255,255,0.78);
}
.cs-group-guide-actor-row {
  width: 100%;
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr);
  gap: 8px;
  align-items: start;
}
.cs-group-guide-actor-icon {
  min-width: 40px !important;
  width: 40px;
  height: 40px;
  padding: 0 !important;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--cs-border);
  border-radius: 8px;
  background: var(--cs-surface-soft);
  color: var(--cs-muted);
}
.cs-group-guide-actor-icon:hover {
  background: var(--cs-accent-bg);
  color: var(--cs-accent);
}
.cs-group-guide-actor-icon .q-btn__content {
  width: 100%;
  height: 100%;
}
.cs-group-guide-actor-icon-content {
  width: 100%;
  height: 100%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.cs-group-guide-actor-icon .cs-group-face {
  width: 30px;
  height: 30px;
  flex-basis: 30px;
}
.cs-group-guide-actor-wrap {
  position: relative;
  min-width: 0;
  width: 100%;
}
.cs-group-guide-actor-wrap .q-field {
  width: 100%;
}
.cs-group-guide-suggestions {
  position: fixed;
  z-index: 7000;
  left: var(--cs-guide-suggestion-left, 0px);
  top: var(--cs-guide-suggestion-top, 0px);
  width: var(--cs-guide-suggestion-width, min(560px, calc(100vw - 32px)));
  display: grid;
  gap: 2px;
  max-height: min(220px, calc(100vh - var(--cs-guide-suggestion-top, 0px) - 16px));
  overflow-y: auto;
  overflow-x: hidden;
  padding: 6px;
  border: 1px solid var(--cs-border);
  border-radius: 8px;
  background: var(--cs-surface);
  box-shadow: 0 14px 32px rgba(0,0,0,0.18);
  box-sizing: border-box;
}
.cs-group-guide-suggestion {
  width: 100%;
  min-height: 36px;
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  padding: 5px 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--cs-text);
  text-align: left;
  cursor: pointer;
}
.cs-group-guide-suggestion:hover {
  background: var(--cs-accent-bg);
  background: color-mix(in srgb, var(--cs-accent-bg) 76%, transparent);
}
.cs-group-guide-suggestion-active {
  background: var(--cs-accent-bg);
  background: color-mix(in srgb, var(--cs-accent-bg) 76%, transparent);
  outline: 1px solid var(--cs-accent-border);
}
.cs-group-guide-suggestion-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.84rem;
  font-weight: 700;
}
.cs-group-guide-suggestion-state {
  color: var(--cs-muted);
  font-size: 0.72rem;
  font-weight: 700;
  white-space: nowrap;
}
.cs-group-system-message .cs-chat-bubble {
  border-style: dashed;
  background: color-mix(in srgb, var(--cs-muted-bg) 70%, transparent);
}
.cs-group-chat-empty {
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--cs-muted);
  text-align: center;
}
.cs-group-empty {
  display: grid;
  place-items: center;
  min-height: 180px;
  padding: 24px;
  border: 1px dashed var(--cs-border);
  border-radius: 8px;
  color: var(--cs-muted);
  text-align: center;
}
@media (max-width: 1023px) {
  .cs-group-home-grid,
  .cs-group-card-grid {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 1279px) and (min-width: 768px) {
  .cs-group-chat-shell {
    grid-template-columns: minmax(280px, 340px) minmax(0, 1fr);
  }
}
@media (max-width: 767px) {
  .cs-group-page-head,
  .cs-group-modal-actions,
  .cs-group-persona-row {
    flex-direction: column;
    align-items: stretch;
  }
  .cs-group-selected-row {
    grid-template-columns: 48px minmax(0, 1fr) 32px;
  }
  .cs-group-selected-row .q-field {
    grid-column: 1 / -1;
  }
  .cs-group-mention-palette {
    left: 12px;
    right: 56px;
  }
}
</style>
"""

_GROUP_MENTION_REFRESH_JS = r"""
event => {
  const input = event.target;
  const palette = document.querySelector('.cs-group-mention-palette');
  const wrapper = input && typeof input.closest === 'function'
    ? input.closest('.cs-chat-composer-input-wrap')
    : null;
  const value = input && typeof input.value === 'string' ? input.value : '';
  if (wrapper) {
    wrapper.classList.toggle('cs-chat-composer-input-has-text', value.length > 0);
  }
  if (!input || !palette) return;
  const mentionState = target => {
    const cursor = target.selectionStart ?? target.value.length;
    const before = target.value.slice(0, cursor);
    const at = before.lastIndexOf('@');
    if (at < 0) return null;
    const query = before.slice(at + 1);
    if (!/^[A-Za-z0-9_]*$/.test(query)) return null;
    const previous = at > 0 ? before[at - 1] : '';
    if (/[A-Za-z0-9_@]/.test(previous)) return null;
    return { start: at, end: cursor, query: query.toLowerCase() };
  };
  const state = mentionState(input);
  const options = Array.from(palette.querySelectorAll('.cs-group-mention-option'));
  const visible = [];
  for (const option of options) {
    const handle = (option.dataset.handle || '').toLowerCase();
    const matched = !!state && (state.query === '' || handle.startsWith(state.query));
    option.classList.toggle('cs-group-mention-option-hidden', !matched);
    if (matched) visible.push(option);
  }
  if (!state || !visible.length) {
    palette.classList.add('cs-group-mention-palette-hidden');
    return;
  }
  palette.classList.remove('cs-group-mention-palette-hidden');
  let active = visible.find(option => option.classList.contains('cs-group-mention-option-active'));
  if (!active) active = visible[0];
  for (const option of options) {
    const isActive = option === active;
    option.classList.toggle('cs-group-mention-option-active', isActive);
    option.setAttribute('aria-selected', isActive ? 'true' : 'false');
  }
}
"""

_GROUP_MENTION_INSERT_JS = r"""
event => {
  event.preventDefault();
  const option = event.currentTarget;
  const input = document.querySelector('.cs-chat-composer-input textarea');
  const palette = document.querySelector('.cs-group-mention-palette');
  if (!option || !input) return;
  const mentionState = target => {
    const cursor = target.selectionStart ?? target.value.length;
    const before = target.value.slice(0, cursor);
    const at = before.lastIndexOf('@');
    if (at < 0) return null;
    const query = before.slice(at + 1);
    if (!/^[A-Za-z0-9_]*$/.test(query)) return null;
    const previous = at > 0 ? before[at - 1] : '';
    if (/[A-Za-z0-9_@]/.test(previous)) return null;
    return { start: at, end: cursor };
  };
  const state = mentionState(input);
  const handle = option.dataset.handle || '';
  if (!state || !handle) return;
  const replacement = `@${handle} `;
  input.value = input.value.slice(0, state.start) + replacement + input.value.slice(state.end);
  const cursor = state.start + replacement.length;
  input.selectionStart = input.selectionEnd = cursor;
  input.dispatchEvent(new Event('input', { bubbles: true }));
  if (palette) palette.classList.add('cs-group-mention-palette-hidden');
  input.focus();
}
"""

_GROUP_CHAT_INPUT_KEYDOWN_JS = r"""
event => {
  const target = event.target;
  const mentionPalette = document.querySelector('.cs-group-mention-palette');
  const commandPalette = document.querySelector('.cs-chat-command-palette');
  const value = target && typeof target.value === 'string' ? target.value : '';
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
    ? Array.from(mentionPalette.querySelectorAll(
        '.cs-group-mention-option:not(.cs-group-mention-option-hidden)'
      ))
    : [];
  const commandMatch = value.match(/^([\s\S]*)\/([A-Za-z]*)$/);
  const commandOptions = commandPalette
    ? Array.from(commandPalette.querySelectorAll('.cs-chat-command-option'))
    : [];
  const activeIndex = options => Math.max(
    0,
    options.findIndex(option =>
      option.classList.contains('cs-group-mention-option-active')
      || option.classList.contains('cs-chat-command-option-active')
    ),
  );
  const setActive = (options, index, activeClass) => {
    options.forEach((option, optionIndex) => {
      const active = optionIndex === index;
      option.classList.toggle(activeClass, active);
      option.setAttribute('aria-selected', active ? 'true' : 'false');
      if (active && typeof option.scrollIntoView === 'function') {
        option.scrollIntoView({ block: 'nearest' });
      }
    });
  };
  const insertOption = option => {
    const state = mentionState(target);
    const handle = option && option.dataset ? option.dataset.handle : '';
    if (!state || !handle || !target || typeof target.value !== 'string') return false;
    const replacement = `@${handle} `;
    target.value = target.value.slice(0, state.start) + replacement + target.value.slice(state.end);
    const cursor = state.start + replacement.length;
    target.selectionStart = target.selectionEnd = cursor;
    target.dispatchEvent(new Event('input', { bubbles: true }));
    if (mentionPalette) mentionPalette.classList.add('cs-group-mention-palette-hidden');
    return true;
  };

  if (mentionPalette && !mentionPalette.classList.contains('cs-group-mention-palette-hidden')) {
    const options = mentionOptions();
    if (options.length && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
      event.preventDefault();
      const delta = event.key === 'ArrowDown' ? 1 : -1;
      setActive(options, (activeIndex(options) + delta + options.length) % options.length, 'cs-group-mention-option-active');
      return;
    }
    if (options.length && (event.key === 'Enter' || event.key === 'Tab') && !event.isComposing) {
      event.preventDefault();
      insertOption(options[activeIndex(options)] || options[0]);
      return;
    }
    if (event.key === 'Escape') {
      mentionPalette.classList.add('cs-group-mention-palette-hidden');
      return;
    }
  }

  if (
    commandMatch
    && commandPalette
    && !commandPalette.classList.contains('cs-chat-command-palette-hidden')
    && commandOptions.length
  ) {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const delta = event.key === 'ArrowDown' ? 1 : -1;
      setActive(
        commandOptions,
        (activeIndex(commandOptions) + delta + commandOptions.length) % commandOptions.length,
        'cs-chat-command-option-active',
      );
      return;
    }
    if (event.key === 'Enter' && !event.isComposing && !event.shiftKey && !event.altKey) {
      event.preventDefault();
      const active = commandOptions[activeIndex(commandOptions)] || commandOptions[0];
      const command = active && active.dataset ? active.dataset.command : '';
      if (command) {
        target.value = commandMatch[1] + '/' + command;
        target.dispatchEvent(new Event('input', { bubbles: true }));
      }
      commandPalette.classList.add('cs-chat-command-palette-hidden');
      emit(target && typeof target.value === 'string' ? target.value : '');
      return;
    }
    if (event.key === 'Escape') {
      commandPalette.classList.add('cs-chat-command-palette-hidden');
      return;
    }
  }

  if (event.key !== 'Enter' || event.isComposing || event.shiftKey || event.altKey) return;
  event.preventDefault();
  emit(target && typeof target.value === 'string' ? target.value : '');
}
"""

_HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{3,12}$")


@ui.page("/groups")
async def group_chat_page() -> None:
    ctx = get_context()

    with page_layout("グループチャット"):
        ui.add_head_html(GROUP_CHAT_CSS)
        with ui.element("div").classes("cs-group-page"):
            with ui.element("div").classes("cs-group-page-head"):
                with ui.element("div"):
                    ui.label("グループチャット").classes("cs-group-page-title")
                    ui.label("グループ一覧と最近のチャットを確認できます。").classes(
                        "cs-group-page-subtitle"
                    )
                ui.button(
                    "新しいグループ",
                    icon="group_add",
                    on_click=lambda: open_new_group_dialog(ctx, refresh_groups),
                ).props("color=primary unelevated").style(
                    "border-radius: 8px; font-weight: 700;"
                )

            with ui.element("div").classes("cs-group-home-grid"):
                groups_container = ui.element("section")
                recent_container = ui.element("section")

            async def refresh_groups() -> None:
                groups = await ctx.group_chats.list_all()
                groups_container.clear()
                recent_container.clear()
                with groups_container:
                    _render_section_head("groups", "グループ一覧")
                    with ui.element("div").classes("cs-group-card-grid"):
                        if not groups:
                            with ui.element("div").classes("cs-group-empty"):
                                ui.label("グループはまだありません")
                        else:
                            for group in groups:
                                _render_group_card(ctx, group, refresh_groups)
                with recent_container:
                    _render_section_head("forum", "最近のチャット")
                    with ui.element("div").classes("grid gap-2"):
                        if not groups:
                            with ui.element("div").classes("cs-group-empty"):
                                ui.label("最近のチャットはまだありません")
                        else:
                            for group in groups[:5]:
                                _render_recent_group(group)

            await refresh_groups()


@ui.page("/groups/{group_id}")
async def group_chat_detail_page(group_id: str) -> None:
    ctx = get_context()
    group = await ctx.group_chats.get(group_id)
    if group is None:
        with page_layout("グループが見つかりません"):
            ui.label("指定されたグループは存在しません。").classes("text-grey-6")
            ui.button("一覧に戻る", on_click=lambda: ui.navigate.to("/groups")).props(
                "flat color=primary"
            )
        return

    with page_layout(group.name):
        ui.add_head_html(CHAT_CSS)
        ui.add_head_html(GROUP_CHAT_CSS)
        controller = GroupChatPageController(ctx, group, ui.context.client)
        await controller.initialize()
        controller.render_shell()


@ui.page("/groups/{group_id}/members/{member_id}")
async def group_member_detail_page(group_id: str, member_id: str) -> None:
    ctx = get_context()
    group = await ctx.group_chats.get(group_id)
    if group is None:
        with page_layout("グループが見つかりません"):
            ui.label("指定されたグループは存在しません。").classes("text-grey-6")
            ui.button("一覧に戻る", on_click=lambda: ui.navigate.to("/groups")).props(
                "flat color=primary"
            )
        return

    member = next((item for item in group.members if item.id == member_id), None)
    if member is None:
        with page_layout("メンバーが見つかりません"):
            ui.label("指定されたメンバーはこのグループに存在しません。").classes("text-grey-6")
            ui.button(
                "グループに戻る",
                on_click=lambda: ui.navigate.to(f"/groups/{group.id}"),
            ).props("flat color=primary")
        return

    sheet = member.character

    with page_layout(sheet.name):
        ui.add_head_html(GROUP_CHAT_CSS)
        with ui.row().classes("items-center gap-2 mb-4 flex-wrap"):
            ui.button(
                icon="arrow_back",
                on_click=lambda: ui.navigate.to(f"/groups/{group.id}"),
            ).props("flat round")
            title_label = ui.label(sheet.name).classes("text-2xl font-bold flex-1")
            ui.badge("グループ内コピー").props("outline color=primary")
            ui.button(
                icon="download",
                on_click=lambda: ui.download(sheet.raw_markdown.encode("utf-8"), f"{sheet.name}.md"),
            ).props("flat round").tooltip("Markdownをダウンロード")
            ui.button(
                icon="content_copy",
                on_click=lambda: _copy_to_clipboard(),
            ).props("flat round").tooltip("Markdownをコピー")

        basic_container = ui.element("div").classes("w-full")
        edit_mode = {"active": False}
        view_mode = {"raw": False}
        edit_area: dict[str, Any] = {"ref": None}

        def _render_basic_info() -> None:
            basic_container.clear()
            with basic_container:
                with ui.card().classes("w-full mb-4"):
                    with ui.row().classes("gap-6 flex-wrap"):
                        for label, value in [
                            ("グループ", group.name),
                            ("ハンドル", f"@{member.handle}"),
                            *sheet.to_display_dict().items(),
                        ]:
                            if value:
                                with ui.column().classes("gap-0"):
                                    ui.label(label).classes("text-xs text-grey-6")
                                    ui.label(value).classes("text-sm font-medium")

                    if sheet.tags:
                        with ui.row().classes("gap-2 mt-3 flex-wrap"):
                            for tag in sheet.tags:
                                ui.badge(tag).props("outline color=primary")

        _render_basic_info()

        with ui.row().classes("w-full items-start gap-4 flex-col lg:flex-row"):
            with ui.column().classes("w-full lg:flex-1 min-w-0"):
                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center justify-between mb-2"):
                        ui.label("キャラクターシート").classes("text-base font-semibold")
                        with ui.row().classes("gap-1"):
                            toggle_raw_btn = ui.button("Markdown表示", on_click=lambda: _toggle_raw()).props(
                                "flat size=sm"
                            )
                            edit_btn = ui.button("編集", icon="edit", on_click=lambda: _enter_edit()).props(
                                "flat size=sm color=primary"
                            )
                            save_edit_btn = ui.button("保存", icon="save", on_click=lambda: _save_edit()).props(
                                "unelevated size=sm color=primary"
                            ).classes("hidden")
                            cancel_edit_btn = ui.button("キャンセル", on_click=lambda: _cancel_edit()).props(
                                "flat size=sm"
                            ).classes("hidden")

                    sheet_container = ui.element("div").classes("w-full")
                    with sheet_container:
                        ui.markdown(sheet.raw_markdown).classes("prose prose-sm max-w-none")

        def _toggle_raw() -> None:
            if edit_mode["active"]:
                return
            view_mode["raw"] = not view_mode["raw"]
            sheet_container.clear()
            with sheet_container:
                if view_mode["raw"]:
                    ui.code(sheet.raw_markdown, language="markdown").classes("w-full text-xs")
                    toggle_raw_btn.set_text("レンダリング表示")
                else:
                    ui.markdown(sheet.raw_markdown).classes("prose prose-sm max-w-none")
                    toggle_raw_btn.set_text("Markdown表示")

        def _enter_edit() -> None:
            edit_mode["active"] = True
            sheet_container.clear()
            with sheet_container:
                ta = ui.textarea(value=sheet.raw_markdown).classes("w-full font-mono text-sm").props(
                    "rows=30 outlined"
                )
                edit_area["ref"] = ta
                with ui.row().classes("justify-end gap-2 mt-2"):
                    ui.button("キャンセル", on_click=lambda: _cancel_edit()).props("flat size=sm")
                    ui.button("保存", icon="save", on_click=lambda: _save_edit()).props(
                        "unelevated size=sm color=primary"
                    )
            toggle_raw_btn.classes("hidden")
            edit_btn.classes("hidden")
            save_edit_btn.classes(remove="hidden")
            cancel_edit_btn.classes(remove="hidden")

        async def _save_edit() -> None:
            nonlocal member, sheet

            ta = edit_area["ref"]
            if ta is None:
                return
            new_md = str(ta.value or "").strip()
            if not new_md:
                ui.notify("シートが空です", type="warning")
                return

            updated = parse_markdown_to_sheet(new_md, sheet.id)
            updated.tags = sheet.tags
            updated.media = sheet.media
            updated.is_favorite = sheet.is_favorite
            updated.generation_meta = sheet.generation_meta
            updated.created_at = sheet.created_at
            saved_member = await ctx.group_chats.update_member_character(group.id, member.id, updated)
            if saved_member is None:
                ui.notify("グループ内キャラクターが見つかりませんでした", type="warning")
                return

            member = saved_member
            sheet = saved_member.character
            title_label.set_text(sheet.name)
            _render_basic_info()
            ui.notify(f"「{sheet.name}」を保存しました", type="positive")
            _cancel_edit()

        def _cancel_edit() -> None:
            edit_mode["active"] = False
            sheet_container.clear()
            with sheet_container:
                if view_mode["raw"]:
                    ui.code(sheet.raw_markdown, language="markdown").classes("w-full text-xs")
                else:
                    ui.markdown(sheet.raw_markdown).classes("prose prose-sm max-w-none")
            toggle_raw_btn.classes(remove="hidden")
            edit_btn.classes(remove="hidden")
            save_edit_btn.classes("hidden")
            cancel_edit_btn.classes("hidden")

        def _copy_to_clipboard() -> None:
            ui.run_javascript(f"navigator.clipboard.writeText({repr(sheet.raw_markdown)})")
            ui.notify("コピーしました", type="positive")


@ui.page("/groups/{group_id}/persona")
async def group_persona_detail_page(group_id: str) -> None:
    ctx = get_context()
    group = await ctx.group_chats.get(group_id)
    if group is None:
        with page_layout("グループが見つかりません"):
            ui.label("指定されたグループは存在しません。").classes("text-grey-6")
            ui.button("一覧に戻る", on_click=lambda: ui.navigate.to("/groups")).props(
                "flat color=primary"
            )
        return

    persona = group.user_persona
    if persona is None:
        with page_layout("ユーザーペルソナが見つかりません"):
            ui.label("このグループにはユーザーペルソナが設定されていません。").classes("text-grey-6")
            ui.button(
                "グループに戻る",
                on_click=lambda: ui.navigate.to(f"/groups/{group.id}"),
            ).props("flat color=primary")
        return

    def _persona_title() -> str:
        return persona.display_name or persona.name or "ユーザー"

    with page_layout(_persona_title()):
        ui.add_head_html(GROUP_CHAT_CSS)
        with ui.row().classes("items-center gap-2 mb-4 flex-wrap"):
            ui.button(
                icon="arrow_back",
                on_click=lambda: ui.navigate.to(f"/groups/{group.id}"),
            ).props("flat round")
            title_label = ui.label(_persona_title()).classes("text-2xl font-bold flex-1")
            ui.badge("グループ内コピー").props("outline color=primary")

        edit_mode = {"active": False}
        basic_container = ui.element("div").classes("w-full")

        def _render_basic_info() -> None:
            basic_container.clear()
            with basic_container:
                with ui.card().classes("w-full mb-4"):
                    with ui.row().classes("gap-6 flex-wrap"):
                        for label, value in [
                            ("グループ", group.name),
                            ("ハンドル", f"@{persona.handle}"),
                            ("表示名", persona.display_name),
                            ("名前", persona.name),
                        ]:
                            if value:
                                with ui.column().classes("gap-0"):
                                    ui.label(label).classes("text-xs text-grey-6")
                                    ui.label(value).classes("text-sm font-medium")

        _render_basic_info()

        with ui.card().classes("w-full"):
            with ui.row().classes("items-center justify-between mb-2"):
                ui.label("ユーザーペルソナ").classes("text-base font-semibold")
                with ui.row().classes("gap-1"):
                    edit_btn = ui.button("編集", icon="edit", on_click=lambda: _enter_edit()).props(
                        "flat size=sm color=primary"
                    )
                    save_btn = ui.button("保存", icon="save", on_click=lambda: _save_edit()).props(
                        "unelevated size=sm color=primary"
                    ).classes("hidden")
                    cancel_btn = ui.button("キャンセル", on_click=lambda: _cancel_edit()).props(
                        "flat size=sm"
                    ).classes("hidden")

            handle_input = {"ref": None}
            name_input = {"ref": None}
            display_name_input = {"ref": None}
            description_input = {"ref": None}
            detail_container = ui.element("div").classes("w-full")

            def _render_view() -> None:
                detail_container.clear()
                with detail_container:
                    with ui.element("div").classes("cs-group-profile-grid"):
                        for label, value in [
                            ("ハンドル", f"@{persona.handle}"),
                            ("表示名", persona.display_name),
                            ("名前", persona.name),
                        ]:
                            ui.label(label).classes("cs-group-profile-label")
                            ui.label(value or "未設定").classes("cs-group-profile-value")
                    ui.label("説明").classes("cs-group-profile-card-title mt-4")
                    ui.label(persona.description or "未設定").classes("cs-group-profile-summary")

            _render_view()

        def _enter_edit() -> None:
            edit_mode["active"] = True
            detail_container.clear()
            with detail_container:
                handle_input["ref"] = ui.input(
                    label="ハンドル",
                    value=persona.handle,
                ).props("outlined dense mask=\"NNNNNNNNNNNN\"").classes("w-full")
                display_name_input["ref"] = ui.input(
                    label="表示名",
                    value=persona.display_name,
                ).props("outlined dense").classes("w-full")
                name_input["ref"] = ui.input(
                    label="名前",
                    value=persona.name,
                ).props("outlined dense").classes("w-full")
                description_input["ref"] = ui.textarea(
                    label="説明",
                    value=persona.description,
                ).props("outlined rows=8").classes("w-full")
            edit_btn.classes("hidden")
            save_btn.classes(remove="hidden")
            cancel_btn.classes(remove="hidden")

        async def _save_edit() -> None:
            nonlocal persona

            handle = str(handle_input["ref"].value if handle_input["ref"] is not None else "").strip()
            display_name = str(
                display_name_input["ref"].value if display_name_input["ref"] is not None else ""
            ).strip()
            name = str(name_input["ref"].value if name_input["ref"] is not None else "").strip()
            description = str(
                description_input["ref"].value if description_input["ref"] is not None else ""
            ).strip()

            sanitized_handle = _sanitize_handle(handle, persona.handle or "User")
            used_handles = {member.handle.lower() for member in group.members}
            if sanitized_handle.lower() in used_handles:
                ui.notify("同じハンドルのメンバーが既にいます", type="warning")
                return
            if not name:
                ui.notify("名前を入力してください", type="warning")
                return

            updated = persona.model_copy(
                update={
                    "handle": sanitized_handle,
                    "name": name,
                    "display_name": display_name or name,
                    "description": description,
                },
                deep=True,
            )
            saved = await ctx.group_chats.update_user_persona(group.id, updated)
            if saved is None:
                ui.notify("ユーザーペルソナが見つかりませんでした", type="warning")
                return

            persona = saved
            title_label.set_text(_persona_title())
            _render_basic_info()
            ui.notify(f"「{_persona_title()}」を保存しました", type="positive")
            _cancel_edit()

        def _cancel_edit() -> None:
            edit_mode["active"] = False
            _render_view()
            edit_btn.classes(remove="hidden")
            save_btn.classes("hidden")
            cancel_btn.classes("hidden")


def open_new_group_dialog(
    ctx,
    refresh_groups: Callable[[], Awaitable[None]],
) -> None:
    profiles = ctx.api_config.get_llm_profiles()
    personas = ctx.api_config.get_user_personas()
    profile_options = _profile_options(ctx, profiles)
    persona_options = {persona.id: persona.display_name for persona in personas}
    page_client = ui.context.client
    selected = {"characters": []}
    handle_inputs: dict[str, Any] = {}
    controls: dict[str, Any] = {}
    state: dict[str, Any] = {
        "step": 0,
        "name": "",
        "profile_id": _default_profile_id(ctx, profile_options),
        "persona_id": _default_persona_id(persona_options),
        "user_handle": "User",
        "handle_values": {},
        "world_source": "new",
        "world_text": "",
        "entry_modes": {},
        "arrival_reasons": {},
        "adaptation_notes": {},
        "adaptation_instructions": {},
        "draft_sheets": {},
        "user_description_draft": "",
        "relationships": [],
        "relationship_sequence": 0,
    }

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-3xl").style(
        "max-width: min(760px, 94vw); height: min(860px, 94vh); "
        "display: flex; flex-direction: column;"
    ):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("新しいグループ").classes("text-lg font-semibold")
            ui.button(icon="close", on_click=dlg.close).props("flat round dense")

        step_head = ui.element("div").classes("w-full")
        with ui.scroll_area().style("flex: 1; min-height: 0; width: 100%;"):
            body = ui.column().classes("w-full gap-3 pr-2")
        nav = ui.row().classes("justify-end gap-2 mt-4")
        busy_state: dict[str, Any] = {"active": False, "job_id": ""}
        with ui.dialog().props("persistent") as busy_dialog, ui.card().classes(
            "items-center gap-3 px-6 py-5"
        ).style("min-width: min(320px, 86vw);"):
            ui.spinner(size="lg")
            busy_label = ui.label("処理中です").classes("text-sm font-semibold text-center")
            busy_cancel_btn = ui.button(
                "キャンセル",
                icon="close",
                on_click=lambda: _cancel_busy_job(),
            ).props("outline color=negative")
            busy_cancel_btn.disable()

        def _begin_busy(label: str) -> None:
            busy_state["active"] = True
            busy_state["job_id"] = ""
            busy_label.set_text(label)
            busy_cancel_btn.disable()
            busy_dialog.open()

        def _set_busy_job(job_id: str) -> None:
            if not busy_state.get("active"):
                return
            busy_state["job_id"] = job_id
            busy_cancel_btn.enable()

        def _end_busy() -> None:
            busy_state["active"] = False
            busy_state["job_id"] = ""
            busy_cancel_btn.disable()
            busy_dialog.close()

        async def _cancel_busy_job() -> None:
            job_id = str(busy_state.get("job_id") or "")
            if not job_id:
                return
            busy_label.set_text("停止要求中...")
            busy_cancel_btn.disable()
            await ctx.ai_jobs.cancel_job(job_id)

        def _selected_persona_obj():
            return _selected_persona(ctx, str(state.get("persona_id") or ""))

        def _current_world_source_character_id() -> str:
            source = str(state.get("world_source") or "new")
            return source.removeprefix("character:") if source.startswith("character:") else ""

        def _current_world_text() -> str:
            source_id = _current_world_source_character_id()
            if source_id:
                source_sheet = next((sheet for sheet in selected["characters"] if sheet.id == source_id), None)
                return (source_sheet.world if source_sheet else "").strip()
            return str(state.get("world_text") or "").strip()

        def _participant_key_for_sheet(sheet: CharacterSheet) -> str:
            return f"character:{sheet.id}"

        def _capture_step() -> None:
            if "name_input" in controls:
                state["name"] = str(controls["name_input"].value or "").strip()
            if "profile_select" in controls:
                state["profile_id"] = str(controls["profile_select"].value or "")
            if "persona_select" in controls:
                persona_id = str(controls["persona_select"].value or "")
                if persona_id != state["persona_id"]:
                    state["user_description_draft"] = ""
                    state["adaptation_notes"].pop("user", None)
                    state["adaptation_instructions"].pop("user", None)
                    state["arrival_reasons"].pop("user", None)
                    state["relationships"] = [
                        relationship for relationship in state["relationships"]
                        if "user" not in {
                            relationship["participant_a_key"],
                            relationship["participant_b_key"],
                        }
                    ]
                state["persona_id"] = persona_id
            if "user_handle_input" in controls:
                state["user_handle"] = str(controls["user_handle_input"].value or "").strip()
            if handle_inputs:
                handle_values = dict(state.get("handle_values", {}))
                for character_id, input_ in handle_inputs.items():
                    handle_values[character_id] = str(input_.value or "")
                state["handle_values"] = handle_values
            if "world_source_select" in controls:
                state["world_source"] = str(controls["world_source_select"].value or "new")
            if "world_input" in controls:
                state["world_text"] = str(controls["world_input"].value or "").strip()
            for key, select in controls.get("entry_selects", {}).items():
                state["entry_modes"][key] = str(select.value or "native")
            for key, input_ in controls.get("arrival_inputs", {}).items():
                state["arrival_reasons"][key] = str(input_.value or "").strip()

        def _validate_step(step: int) -> bool:
            _capture_step()
            if step == 0:
                if not state["profile_id"]:
                    ui.notify("補完用LLMプロファイルを選択してください", type="warning")
                    return False
                if not selected["characters"]:
                    ui.notify("キャラクターを選択してください", type="warning")
                    return False
                if _selected_persona_obj() is None:
                    ui.notify("ユーザーペルソナを選択してください", type="warning")
                    return False
                if _validate_handles_from_values(selected["characters"], state["handle_values"], state["user_handle"]) is None:
                    return False
            if step == 1:
                if not state["name"]:
                    ui.notify("グループ名を入力してください", type="warning")
                    return False
                if not _current_world_text():
                    ui.notify("ワールドを確定してください", type="warning")
                    return False
            if step == 2:
                source_id = _current_world_source_character_id()
                for sheet in selected["characters"]:
                    if sheet.id == source_id:
                        continue
                    key = _participant_key_for_sheet(sheet)
                    if state["entry_modes"].get(key, "native") == "visitor" and not state["arrival_reasons"].get(key, "").strip():
                        ui.notify(f"{sheet.name} の来訪理由を入力してください", type="warning")
                        return False
                if state["entry_modes"].get("user", "native") == "visitor" and not state["arrival_reasons"].get("user", "").strip():
                    ui.notify("ユーザーペルソナの来訪理由を入力してください", type="warning")
                    return False
            return True

        def _render_step_head() -> None:
            labels = ["参加者", "ワールド", "適応", "関係性"]
            step_head.clear()
            with step_head:
                with ui.row().classes("items-center gap-2 flex-wrap"):
                    for index, label in enumerate(labels):
                        color = "primary" if index == state["step"] else "grey"
                        ui.badge(f"{index + 1}. {label}").props(f"outline color={color}")

        def _render_selected_list(container) -> None:
            previous_handles = {
                character_id: str(input_.value or "")
                for character_id, input_ in handle_inputs.items()
            }
            handle_values = dict(state.get("handle_values", {}))
            handle_values.update(previous_handles)
            state["handle_values"] = handle_values
            handle_inputs.clear()
            container.clear()
            with container:
                if not selected["characters"]:
                    ui.label("キャラクター未選択").classes("text-sm text-grey-6")
                    return
                for sheet in selected["characters"]:
                    _render_selected_character_row(
                        ctx,
                        sheet,
                        handle_inputs,
                        value=handle_values.get(sheet.id),
                        remove=lambda character_id=sheet.id: _remove_character(character_id),
                    )

        def _remove_character(character_id: str) -> None:
            selected["characters"] = [
                sheet for sheet in selected["characters"] if sheet.id != character_id
            ]
            handle_inputs.pop(character_id, None)
            state["handle_values"].pop(character_id, None)
            state["entry_modes"].pop(f"character:{character_id}", None)
            state["arrival_reasons"].pop(f"character:{character_id}", None)
            state["adaptation_instructions"].pop(f"character:{character_id}", None)
            state["draft_sheets"].pop(character_id, None)
            if state["world_source"] == f"character:{character_id}":
                state["world_source"] = "new"
            state["relationships"] = [
                relationship for relationship in state["relationships"]
                if f"character:{character_id}" not in {
                    relationship["participant_a_key"],
                    relationship["participant_b_key"],
                }
            ]
            render_step()

        async def _open_picker() -> None:
            async def _add_character(sheet: CharacterSheet) -> None:
                if any(current.id == sheet.id for current in selected["characters"]):
                    ui.notify("このキャラクターは選択済みです", type="warning")
                    return
                selected["characters"].append(sheet)
                state["entry_modes"].setdefault(f"character:{sheet.id}", "native")
                render_step()

            await open_character_picker(
                ctx,
                _add_character,
                title="グループに取り込むキャラクターを選択",
                empty_message="取り込めるキャラクターがありません",
            )

        def _render_setup_step() -> None:
            controls.clear()
            handle_inputs.clear()
            with body:
                controls["profile_select"] = ui.select(
                    options=profile_options,
                    value=state["profile_id"] if state["profile_id"] in profile_options else _default_profile_id(ctx, profile_options),
                    label="補完用LLMプロファイル",
                ).props("outlined dense").classes("w-full")
                with ui.element("div").classes("cs-group-modal-section"):
                    with ui.element("div").classes("cs-group-modal-actions"):
                        with ui.column().classes("gap-0"):
                            ui.label("グループに取り込むキャラクター").classes("text-sm font-semibold")
                            ui.label("選択したキャラクターはグループ内コピーとして保存します。").classes("cs-group-note")
                        ui.button(
                            "キャラクターを追加",
                            icon="person_search",
                            on_click=_open_picker,
                        ).props("color=primary unelevated").style("border-radius: 8px; font-weight: 700;")
                    selected_list = ui.element("div").classes("cs-group-selected-list")
                    _render_selected_list(selected_list)

                with ui.element("div").classes("cs-group-modal-section"):
                    ui.label("ユーザーペルソナ").classes("text-sm font-semibold")
                    with ui.element("div").classes("cs-group-persona-row"):
                        controls["persona_select"] = ui.select(
                            options=persona_options,
                            value=state["persona_id"] if state["persona_id"] in persona_options else _default_persona_id(persona_options),
                            label="ユーザーペルソナ",
                        ).props("outlined dense").classes("w-full")
                        controls["user_handle_input"] = ui.input(
                            label="ユーザーのハンドル",
                            value=state["user_handle"] or "User",
                        ).props("outlined dense mask=\"NNNNNNNNNNNN\"").classes("w-full")

                async def _generate_handles_click() -> None:
                    _capture_step()
                    _begin_busy("ハンドルを生成しています...")
                    try:
                        await _generate_handles(
                            ctx,
                            str(controls["profile_select"].value or ""),
                            selected["characters"],
                            _selected_persona(ctx, str(controls["persona_select"].value or "")),
                            handle_inputs,
                            controls["user_handle_input"],
                            on_job_started=_set_busy_job,
                        )
                        _capture_step()
                    finally:
                        _end_busy()

                ui.button(
                    "一括でハンドル生成",
                    icon="auto_fix_high",
                    on_click=_generate_handles_click,
                ).props("flat color=primary").classes("w-fit")

        def _world_options() -> dict[str, str]:
            return _world_source_options_for_characters(selected["characters"])

        def _render_world_step() -> None:
            controls.clear()
            options = _world_options()
            if state["world_source"] not in options:
                state["world_source"] = "new"
            with body:
                with ui.element("div").classes("cs-group-world-field"):
                    controls["name_input"] = ui.input(
                        label="グループ名",
                        value=state["name"],
                    ).props("outlined clearable").classes("w-full")

                    async def _generate_group_name_click() -> None:
                        _capture_step()
                        _begin_busy("グループ名を補完しています...")
                        try:
                            name = await _generate_group_name_from_world(
                                ctx,
                                str(state["profile_id"] or ""),
                                _current_world_text(),
                                selected["characters"],
                                _selected_persona_obj(),
                                page_client,
                                on_job_started=_set_busy_job,
                            )
                            if name:
                                controls["name_input"].set_value(name)
                                state["name"] = name
                        finally:
                            _end_busy()

                    ui.button(
                        icon="auto_awesome",
                        on_click=_generate_group_name_click,
                    ).props("flat round dense size=sm").classes("cs-group-world-enhance").tooltip("グループ名を補完")

                controls["world_source_select"] = ui.select(
                    options=options,
                    value=state["world_source"],
                    label="ワールドの決め方",
                ).props("outlined dense").classes("w-full")

                def _refresh_world_preview() -> None:
                    _capture_step()
                    render_step()

                controls["world_source_select"].on_value_change(lambda _: _refresh_world_preview())
                if state["world_source"] == "new":
                    with ui.element("div").classes("cs-group-world-field"):
                        controls["world_input"] = ui.textarea(
                            label="新しいワールド",
                            value=state["world_text"],
                            placeholder="グループで共有する舞台、関係性、空気感など",
                        ).props("outlined rows=6").classes("w-full")
                        ui.button(
                            icon="auto_awesome",
                            on_click=lambda: _enhance_world_click_busy(),
                        ).props("flat round dense size=sm").classes("cs-group-world-enhance").tooltip("ワールドを補完")
                else:
                    source_id = _current_world_source_character_id()
                    source_sheet = next((sheet for sheet in selected["characters"] if sheet.id == source_id), None)
                    ui.label(source_sheet.name if source_sheet else "引き継ぎ元").classes("text-sm font-semibold")
                    ui.label((source_sheet.world if source_sheet else "") or "未設定").classes(
                        "cs-group-profile-summary"
                    )

        async def _enhance_world_click_busy() -> None:
            _capture_step()
            world_input = controls.get("world_input")
            name_input = controls.get("name_input")
            if world_input is None or name_input is None:
                return
            _begin_busy("ワールドを補完しています...")
            try:
                await _enhance_world_click(
                    ctx,
                    str(state["profile_id"] or ""),
                    selected["characters"],
                    _selected_persona_obj(),
                    world_input,
                    name_input,
                    on_job_started=_set_busy_job,
                )
                _capture_step()
            finally:
                _end_busy()

        def _render_entry_row(key: str, label: str, summary: str, *, is_character: bool, source_sheet: CharacterSheet | None = None) -> None:
            source_id = _current_world_source_character_id()
            if source_sheet is not None and source_sheet.id == source_id:
                state["entry_modes"][key] = "world_source"
                with ui.element("div").classes("cs-group-selected-row"):
                    if source_sheet is not None:
                        _render_character_face(ctx, source_sheet)
                    with ui.column().classes("gap-0 min-w-0 flex-1"):
                        ui.label(label).classes("text-sm font-semibold")
                        ui.label("ワールド引き継ぎ元").classes("text-xs text-grey-6")
                return

            mode = state["entry_modes"].get(key, "native")
            reason = state["arrival_reasons"].get(key, "")
            with ui.element("div").classes("cs-group-selected-row"):
                if source_sheet is not None:
                    _render_character_face(ctx, source_sheet)
                else:
                    _render_group_user_menu_face(ctx, _group_user_persona_from_selected(_selected_persona_obj(), state["user_handle"]))
                with ui.column().classes("gap-2 min-w-0 flex-1"):
                    ui.label(label).classes("text-sm font-semibold")
                    if summary:
                        ui.label(summary).classes("text-xs text-grey-6")
                    entry_select = ui.select(
                        options={
                            "native": "元々この世界の住人だった",
                            "visitor": "何らかの理由でこの世界に来た",
                        },
                        value=mode if mode in {"native", "visitor"} else "native",
                        label="ワールド参加設定",
                    ).props("outlined dense").classes("w-full")
                    controls.setdefault("entry_selects", {})[key] = entry_select

                    def _refresh_entry_mode() -> None:
                        _capture_step()
                        render_step()

                    entry_select.on_value_change(lambda _: _refresh_entry_mode())
                    if mode == "visitor":
                        controls.setdefault("arrival_inputs", {})[key] = ui.textarea(
                            label="この世界に来た理由",
                            value=reason,
                        ).props("outlined rows=3").classes("w-full")
                        ui.button(
                            "理由を補完",
                            icon="auto_awesome",
                            on_click=lambda participant_key=key, display_name=label, text_summary=summary: _generate_arrival_reason_click(
                                participant_key,
                                display_name,
                                text_summary,
                            ),
                        ).props("flat dense color=primary").classes("w-fit")
                    if mode != "visitor" and is_character and source_sheet is not None:
                        with ui.row().classes("gap-2 flex-wrap"):
                            ui.button(
                                "ワールドに馴染ませる",
                                icon="auto_fix_high",
                                on_click=lambda sheet=source_sheet, participant_key=key, display_name=label: _open_world_adaptation_dialog(
                                    participant_key,
                                    display_name,
                                    lambda instruction, target_sheet=sheet, target_key=participant_key: _adapt_character_click(
                                        target_sheet,
                                        target_key,
                                        instruction,
                                    ),
                                ),
                            ).props("outline dense color=primary")
                    elif mode != "visitor" and not is_character:
                        ui.button(
                            "ワールドに馴染ませる",
                            icon="auto_fix_high",
                            on_click=lambda participant_key=key, display_name=label, text_summary=summary: _adapt_user_persona_click(
                                participant_key,
                                display_name,
                                text_summary,
                            ),
                        ).props("outline dense color=primary").classes("w-fit")
                    note = state["adaptation_notes"].get(key, "")
                    if note:
                        ui.label(note).classes("text-xs text-grey-6")

        async def _adapt_character_click(sheet: CharacterSheet, participant_key: str, instruction: str) -> None:
            _capture_step()
            if state["entry_modes"].get(participant_key, "native") != "native":
                ui.notify("ワールドに馴染ませる改変は「元々この世界の住人だった」設定で使用してください", type="warning")
                return
            world = _current_world_text()
            _begin_busy("キャラクターシートを調整しています...")
            try:
                await _adapt_character_to_world(
                    ctx,
                    str(state["profile_id"] or ""),
                    state["draft_sheets"].get(sheet.id, sheet),
                    world,
                    instruction,
                    lambda updated: _apply_adapted_sheet(sheet.id, participant_key, updated),
                    page_client,
                    on_job_started=_set_busy_job,
                )
            finally:
                _end_busy()

        def _apply_adapted_sheet(sheet_id: str, participant_key: str, updated: CharacterSheet) -> None:
            state["draft_sheets"][sheet_id] = updated
            state["adaptation_notes"][participant_key] = "LLM改変を承認済み"
            render_step()

        async def _adapt_user_persona_click(participant_key: str, display_name: str, summary: str) -> None:
            _open_world_adaptation_dialog(
                participant_key,
                display_name,
                lambda instruction: _adapt_user_persona_with_instruction(
                    participant_key,
                    display_name,
                    summary,
                    instruction,
                ),
            )

        async def _adapt_user_persona_with_instruction(
            participant_key: str,
            display_name: str,
            summary: str,
            instruction: str,
        ) -> None:
            _capture_step()
            if state["entry_modes"].get(participant_key, "native") != "native":
                ui.notify("ワールドに馴染ませる改変は「元々この世界の住人だった」設定で使用してください", type="warning")
                return
            persona = _selected_persona_obj()
            if persona is None:
                ui.notify("ユーザーペルソナを選択してください", type="warning")
                return
            _begin_busy("ユーザーペルソナを調整しています...")
            try:
                await _adapt_user_persona_to_world(
                    ctx,
                    str(state["profile_id"] or ""),
                    display_name,
                    str(state.get("user_description_draft") or summary or ""),
                    _current_world_text(),
                    instruction,
                    lambda updated: _apply_adapted_user_persona(participant_key, updated),
                    page_client,
                    on_job_started=_set_busy_job,
                )
            finally:
                _end_busy()

        def _apply_adapted_user_persona(participant_key: str, updated_description: str) -> None:
            state["user_description_draft"] = updated_description
            state["adaptation_notes"][participant_key] = "LLM改変を承認済み"
            render_step()

        def _open_world_adaptation_dialog(
            participant_key: str,
            display_name: str,
            run_adaptation: Callable[[str], Awaitable[None]],
        ) -> None:
            _capture_step()
            with ui.dialog() as adaptation_dialog, ui.card().classes("w-full max-w-lg"):
                ui.label("ワールドに馴染ませる").classes("text-base font-semibold")
                ui.label(display_name).classes("text-sm text-grey-6")
                instruction_input = ui.textarea(
                    label="追加指示（任意）",
                    value=state["adaptation_instructions"].get(participant_key, ""),
                    placeholder="例: 学園もの寄りにする、職業は変えない、口調は元のままにする",
                ).props("outlined rows=5").classes("w-full")

                async def _run() -> None:
                    instruction = str(instruction_input.value or "").strip()
                    if instruction:
                        state["adaptation_instructions"][participant_key] = instruction
                    else:
                        state["adaptation_instructions"].pop(participant_key, None)
                    adaptation_dialog.close()
                    await run_adaptation(instruction)

                with ui.row().classes("justify-end gap-2 mt-4"):
                    ui.button("キャンセル", on_click=adaptation_dialog.close).props("flat")
                    ui.button("OK", icon="check", on_click=_run).props("color=primary unelevated")
            adaptation_dialog.open()

        async def _generate_arrival_reason_click(participant_key: str, display_name: str, summary: str) -> None:
            _capture_step()
            input_ = controls.get("arrival_inputs", {}).get(participant_key)
            if input_ is None:
                return
            _begin_busy("来訪理由を補完しています...")
            try:
                reason = await _generate_arrival_reason(
                    ctx,
                    str(state["profile_id"] or ""),
                    display_name,
                    _current_world_text(),
                    summary,
                    page_client,
                    on_job_started=_set_busy_job,
                )
                if reason:
                    input_.set_value(reason)
                    state["arrival_reasons"][participant_key] = reason
            finally:
                _end_busy()

        def _render_entry_step() -> None:
            controls.clear()
            controls["entry_selects"] = {}
            controls["arrival_inputs"] = {}
            with body:
                ui.label("参加者ごとのワールド参加設定").classes("text-sm font-semibold")
                for sheet in selected["characters"]:
                    display_sheet = state["draft_sheets"].get(sheet.id, sheet)
                    _render_entry_row(
                        _participant_key_for_sheet(sheet),
                        display_sheet.name,
                        _compact_character_summary(display_sheet),
                        is_character=True,
                        source_sheet=display_sheet,
                    )
                persona = _selected_persona_obj()
                if persona is not None:
                    _render_entry_row(
                        "user",
                        persona.display_name or persona.name or "ユーザー",
                        str(state.get("user_description_draft") or persona.description),
                        is_character=False,
                    )

        def _relationship_options() -> dict[str, str]:
            options = {
                _participant_key_for_sheet(sheet): (
                    f"{state['draft_sheets'].get(sheet.id, sheet).name} "
                    f"(@{state['handle_values'].get(sheet.id, _fallback_handle(sheet, 1))})"
                )
                for sheet in selected["characters"]
            }
            persona = _selected_persona_obj()
            if persona is not None:
                options["user"] = f"{persona.display_name or persona.name or 'ユーザー'} (@{state.get('user_handle') or 'User'})"
            return options

        def _relationship_participants() -> list[dict[str, str]]:
            display_characters = [
                state["draft_sheets"].get(sheet.id, sheet)
                for sheet in selected["characters"]
            ]
            return _relationship_draft_participants(
                display_characters,
                _selected_persona_obj(),
                state,
            )

        def _render_relationship_step() -> None:
            controls.clear()
            with body:
                with ui.row().classes("items-center justify-between gap-2 w-full"):
                    ui.label("関係性").classes("text-sm font-semibold")
                    with ui.row().classes("gap-2"):
                        ui.button(
                            "追加",
                            icon="add",
                            on_click=lambda: _open_relationship_draft_dialog(
                                state,
                                _relationship_options(),
                                None,
                                render_step,
                                ctx=ctx,
                                profile_id=str(state["profile_id"] or ""),
                                world=_current_world_text(),
                                participants=_relationship_participants(),
                                page_client=page_client,
                                begin_busy=_begin_busy,
                                set_busy_job=_set_busy_job,
                                end_busy=_end_busy,
                            ),
                        ).props("outline dense")
                        ui.button(
                            "LLMで自動設定",
                            icon="auto_awesome",
                            on_click=_generate_relationships_click,
                        ).props("flat dense color=primary")
                if not state["relationships"]:
                    ui.label("設定済みの関係性はありません").classes("text-sm text-grey-6")
                labels = _relationship_options()
                for relationship in state["relationships"]:
                    with ui.element("div").classes("cs-group-relationship-row"):
                        with ui.element("div").classes("cs-group-relationship-head"):
                            left = labels.get(relationship["participant_a_key"], "不明な参加者")
                            right = labels.get(relationship["participant_b_key"], "不明な参加者")
                            ui.label(f"{left} ↔ {right}").classes("cs-group-relationship-pair")
                            with ui.row().classes("gap-1"):
                                ui.button(
                                    icon="edit",
                                    on_click=lambda item=relationship: _open_relationship_draft_dialog(
                                        state,
                                        labels,
                                        item,
                                        render_step,
                                        ctx=ctx,
                                        profile_id=str(state["profile_id"] or ""),
                                        world=_current_world_text(),
                                        participants=_relationship_participants(),
                                        page_client=page_client,
                                        begin_busy=_begin_busy,
                                        set_busy_job=_set_busy_job,
                                        end_busy=_end_busy,
                                    ),
                                ).props("flat round dense size=sm").tooltip("編集")
                                ui.button(
                                    icon="delete",
                                    on_click=lambda relationship_id=relationship["id"]: _delete_relationship_draft(
                                        state,
                                        relationship_id,
                                        render_step,
                                    ),
                                ).props("flat round dense size=sm color=negative").tooltip("削除")
                        ui.label(relationship["description"]).classes("cs-group-relationship-text")

        async def _generate_relationships_click() -> None:
            _capture_step()
            _begin_busy("関係性を自動設定しています...")
            try:
                generated = await _generate_relationship_drafts(
                    ctx,
                    str(state["profile_id"] or ""),
                    selected["characters"],
                    _selected_persona_obj(),
                    _current_world_text(),
                    state,
                    page_client,
                    on_job_started=_set_busy_job,
                )
                if generated:
                    _merge_relationship_drafts(state, generated)
                    render_step()
            finally:
                _end_busy()

        async def _create_group() -> None:
            _capture_step()
            for step in range(3):
                if not _validate_step(step):
                    state["step"] = step
                    render_step()
                    return
            validation = _validate_handles_from_values(selected["characters"], state["handle_values"], state["user_handle"])
            if validation is None:
                state["step"] = 0
                render_step()
                return
            member_handles, user_handle = validation
            persona = _selected_persona_obj()
            if persona is None:
                state["step"] = 0
                render_step()
                return
            world = _current_world_text()
            source_id = _current_world_source_character_id()
            members_for_create: list[tuple[CharacterSheet, str]] = []
            member_world_settings: dict[str, dict[str, str]] = {}
            for sheet, handle in zip(selected["characters"], member_handles, strict=True):
                prepared, settings = _prepare_group_character_for_world(
                    state["draft_sheets"].get(sheet.id, sheet),
                    world=world,
                    source_character_id=source_id,
                    entry_type=state["entry_modes"].get(_participant_key_for_sheet(sheet), "native"),
                    arrival_reason=state["arrival_reasons"].get(_participant_key_for_sheet(sheet), ""),
                    adaptation_note=state["adaptation_notes"].get(_participant_key_for_sheet(sheet), ""),
                )
                members_for_create.append((prepared, handle))
                member_world_settings[prepared.id] = settings

            user_world_settings = _prepare_group_user_world_settings(
                persona,
                world=world,
                entry_type=state["entry_modes"].get("user", "native"),
                arrival_reason=state["arrival_reasons"].get("user", ""),
                adaptation_note=state["adaptation_notes"].get("user", ""),
                description_override=str(state.get("user_description_draft") or ""),
            )
            relationships = [
                GroupRelationship(
                    id=str(relationship["id"]),
                    participant_a_key=str(relationship["participant_a_key"]),
                    participant_b_key=str(relationship["participant_b_key"]),
                    description=str(relationship["description"]),
                )
                for relationship in state["relationships"]
            ]
            await ctx.group_chats.create_group(
                name=state["name"],
                world=world,
                completion_profile_id=str(state["profile_id"] or ""),
                members=members_for_create,
                user_persona=persona,
                user_handle=user_handle,
                world_source_type="character" if source_id else "new",
                world_source_character_id=source_id,
                member_world_settings=member_world_settings,
                user_world_settings=user_world_settings,
                relationships=relationships,
            )
            dlg.close()
            ui.notify("グループを作成しました", type="positive")
            await refresh_groups()

        def _next_step() -> None:
            current = int(state["step"])
            if _validate_step(current):
                state["step"] = min(3, current + 1)
                render_step()

        def _prev_step() -> None:
            _capture_step()
            state["step"] = max(0, int(state["step"]) - 1)
            render_step()

        def _render_nav() -> None:
            nav.clear()
            with nav:
                ui.button("キャンセル", on_click=dlg.close).props("flat")
                if state["step"] > 0:
                    ui.button("戻る", icon="arrow_back", on_click=_prev_step).props("flat")
                if state["step"] < 3:
                    ui.button("次へ", icon="arrow_forward", on_click=_next_step).props("color=primary unelevated")
                else:
                    ui.button("作成", icon="save", on_click=_create_group).props("color=primary unelevated")

        def render_step() -> None:
            _render_step_head()
            body.clear()
            with body:
                if state["step"] == 0:
                    _render_setup_step()
                elif state["step"] == 1:
                    _render_world_step()
                elif state["step"] == 2:
                    _render_entry_step()
                else:
                    _render_relationship_step()
            _render_nav()

        render_step()

    dlg.open()


def _validate_handles_from_values(
    characters: list[CharacterSheet],
    handle_values: dict[str, str],
    user_handle_value: str,
) -> tuple[list[str], str] | None:
    handles: list[str] = []
    seen: set[str] = set()
    for sheet in characters:
        handle = str(handle_values.get(sheet.id) or "").strip()
        if not _HANDLE_RE.fullmatch(handle):
            ui.notify(f"{sheet.name} のハンドルは3〜12文字の英数字または_で入力してください", type="warning")
            return None
        if handle.lower() in seen:
            ui.notify("ハンドルが重複しています", type="warning")
            return None
        seen.add(handle.lower())
        handles.append(handle)

    user_handle = str(user_handle_value or "").strip()
    if not _HANDLE_RE.fullmatch(user_handle):
        ui.notify("ユーザーのハンドルは3〜12文字の英数字または_で入力してください", type="warning")
        return None
    if user_handle.lower() in seen:
        ui.notify("ハンドルが重複しています", type="warning")
        return None
    return handles, user_handle


def _group_user_persona_from_selected(persona, handle: str) -> GroupUserPersona | None:
    if persona is None:
        return None
    return GroupUserPersona(
        id=str(getattr(persona, "id", "") or "user"),
        source_persona_id=str(getattr(persona, "id", "") or ""),
        handle=_sanitize_handle(handle or "User", "User"),
        name=str(getattr(persona, "name", "") or ""),
        display_name=str(getattr(persona, "display_name", "") or ""),
        description=str(getattr(persona, "description", "") or ""),
        media=getattr(persona, "media").model_copy(deep=True),
    )


def _world_source_options_for_characters(characters: list[CharacterSheet]) -> dict[str, str]:
    options = {"new": "完全に新しいワールド"}
    for sheet in characters:
        if sheet.world.strip():
            options[f"character:{sheet.id}"] = f"{sheet.name} のワールドを引き継ぐ"
    return options


def _prepare_group_character_for_world(
    sheet: CharacterSheet,
    *,
    world: str,
    source_character_id: str,
    entry_type: str,
    arrival_reason: str,
    adaptation_note: str,
) -> tuple[CharacterSheet, dict[str, str]]:
    if sheet.id == source_character_id:
        markdown = _remove_markdown_section(_base_character_markdown(sheet), "世界観・舞台")
        markdown = _remove_markdown_section(markdown, "この世界に来た理由")
        return _sheet_from_markdown_preserving(sheet, markdown), {
            "world_entry_type": "world_source",
            "arrival_reason": "",
            "world_adaptation_note": adaptation_note.strip(),
        }

    resolved_type = entry_type if entry_type in {"native", "visitor"} else "native"
    markdown = _base_character_markdown(sheet)
    if resolved_type == "native":
        markdown = _remove_markdown_section(markdown, "世界観・舞台")
        markdown = _remove_markdown_section(markdown, "この世界に来た理由")
        note = adaptation_note.strip() or "確定ワールドの住人として設定"
        updated = _sheet_from_markdown_preserving(sheet, markdown)
        return updated, {
            "world_entry_type": "native",
            "arrival_reason": "",
            "world_adaptation_note": note,
        }

    reason = arrival_reason.strip()
    markdown = _replace_markdown_section(markdown, "この世界に来た理由", reason)
    updated = _sheet_from_markdown_preserving(sheet, markdown)
    return updated, {
        "world_entry_type": "visitor",
        "arrival_reason": reason,
        "world_adaptation_note": adaptation_note.strip(),
    }


def _prepare_group_user_world_settings(
    persona,
    *,
    world: str,
    entry_type: str,
    arrival_reason: str,
    adaptation_note: str,
    description_override: str = "",
) -> dict[str, str]:
    resolved_type = entry_type if entry_type in {"native", "visitor"} else "native"
    description = (description_override or str(getattr(persona, "description", "") or "")).strip()
    return {
        "description": description,
        "world_entry_type": resolved_type,
        "arrival_reason": arrival_reason.strip() if resolved_type == "visitor" else "",
        "world_adaptation_note": adaptation_note.strip(),
    }


def _base_character_markdown(sheet: CharacterSheet) -> str:
    markdown = (sheet.raw_markdown or "").strip()
    if markdown:
        return markdown
    return f"# {sheet.name or '名称未設定'}"


def _replace_markdown_section(markdown: str, header: str, body: str) -> str:
    text = (markdown or "").strip()
    section = f"## {header}\n{body.strip()}".rstrip()
    pattern = re.compile(
        rf"(^##\s*{re.escape(header)}\s*\n)(.*?)(?=\n##\s+|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    if pattern.search(text):
        return pattern.sub(section, text, count=1).strip()
    return f"{text}\n\n{section}".strip()


def _remove_markdown_section(markdown: str, header: str) -> str:
    pattern = re.compile(
        rf"\n*##\s*{re.escape(header)}\s*\n.*?(?=\n##\s+|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    return pattern.sub("", markdown or "", count=1).strip()


def _sheet_from_markdown_preserving(original: CharacterSheet, markdown: str) -> CharacterSheet:
    updated = parse_markdown_to_sheet(markdown.strip(), original.id)
    updated.media = original.media.model_copy(deep=True)
    updated.tags = list(original.tags)
    updated.is_favorite = original.is_favorite
    updated.generation_meta = original.generation_meta.model_copy(deep=True)
    updated.created_at = original.created_at
    return updated


def _notify_on_client(page_client, message: str, **kwargs) -> None:
    try:
        if page_client is not None and not getattr(page_client, "_deleted", False):
            with page_client:
                ui.notify(message, **kwargs)
        else:
            ui.notify(message, **kwargs)
    except RuntimeError:
        return


def _format_optional_instruction(instruction: str) -> str:
    text = (instruction or "").strip()
    if not text:
        return ""
    return f"追加指示:\n{text}\n\n"


async def _adapt_character_to_world(
    ctx,
    profile_id: str,
    sheet: CharacterSheet,
    world: str,
    additional_instruction: str,
    apply_callback: Callable[[CharacterSheet], None],
    page_client=None,
    on_job_started: Callable[[str], None] | None = None,
) -> None:
    if not world.strip():
        ui.notify("先にワールドを確定してください", type="warning")
        return
    llm = _configured_llm(ctx, profile_id)
    if llm is None:
        return

    original_markdown = _base_character_markdown(sheet)

    async def _runner() -> str:
        response = await llm.ainvoke([
            SystemMessage(content=(
                "あなたはキャラクターシートを別ワールド向けに調整する編集者です。"
                "出力は更新後のMarkdown全文だけにしてください。"
            )),
            HumanMessage(content=(
                "次のキャラクターが、確定ワールドに元々存在していた人物として自然に成立するように、"
                "キャラクターシートを最小限改変してください。\n"
                "グループ全体のワールドは別途保存されるため、世界観・舞台セクションは削除してください。\n"
                "元の世界観情報も、確定ワールドの本文も、キャラクターシート内には残さないでください。\n"
                "人物の名前、魅力、口調、主要な性格はできるだけ維持してください。\n"
                "Markdownの見出し構造は可能な限り維持し、解説や差分説明は出力しないでください。\n\n"
                f"確定ワールド:\n{world.strip()}\n\n"
                f"{_format_optional_instruction(additional_instruction)}"
                f"現在のキャラクターシートMarkdown:\n{original_markdown}"
            )),
        ])
        return _clean_character_markdown_response(
            message_content_to_text(getattr(response, "content", response))
        )

    job = ctx.ai_jobs.start_job(
        kind=AIJobKind.LLM_ASSIST,
        label="キャラクターシート調整",
        scope="group_setup:world_adapt",
        metadata={"character_id": sheet.id},
        runner=lambda _: _runner(),
    )
    if on_job_started is not None:
        on_job_started(job.id)
    ctx.ai_jobs.set_result_meta(job.id, {"result_url": "/groups"})
    finished = await ctx.ai_jobs.wait(job.id)
    if finished.status == AIJobStatus.CANCELLED:
        _notify_on_client(page_client, "キャラクターシート調整を停止しました", type="info")
        return
    if finished.status != AIJobStatus.SUCCEEDED:
        _notify_on_client(
            page_client,
            f"キャラクターシート調整に失敗しました: {finished.error_message}",
            type="negative",
            timeout=10000,
        )
        return
    updated_markdown = _remove_markdown_section(str(finished.result or "").strip(), "世界観・舞台")
    if not updated_markdown:
        _notify_on_client(page_client, "キャラクターシートを調整できませんでした", type="warning")
        return
    await _open_character_adaptation_preview_dialog(
        sheet,
        original_markdown,
        updated_markdown,
        apply_callback,
        page_client,
    )


def _clean_character_markdown_response(raw: str) -> str:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:markdown|md)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()
    parsed = _try_parse_json_fragment(text)
    if parsed is not None:
        text = _longest_json_string(parsed) or text
    return text.strip()


async def _open_character_adaptation_preview_dialog(
    sheet: CharacterSheet,
    original_markdown: str,
    updated_markdown: str,
    apply_callback: Callable[[CharacterSheet], None],
    page_client=None,
) -> None:
    diff_html = _build_group_diff_html(original_markdown, updated_markdown)
    try:
        if page_client is not None and not getattr(page_client, "_deleted", False):
            with page_client:
                with ui.dialog() as dlg, ui.card().classes("w-full max-w-3xl"):
                    ui.label("キャラクターシート調整の確認").classes("text-base font-semibold")
                    ui.label(f"「{sheet.name}」をワールドに馴染む内容へ変更します。").classes("text-sm text-grey-6")
                    ui.html(diff_html).classes("w-full")

                    def _approve() -> None:
                        updated = _sheet_from_markdown_preserving(sheet, updated_markdown)
                        dlg.close()
                        apply_callback(updated)
                        _notify_on_client(page_client, "キャラクターシート調整を反映しました", type="positive")

                    with ui.row().classes("justify-end gap-2 mt-4"):
                        ui.button("キャンセル", on_click=dlg.close).props("flat")
                        ui.button("反映", icon="check", on_click=_approve).props("color=primary unelevated")
                dlg.open()
        else:
            raise RuntimeError("client is not available")
    except RuntimeError:
        _notify_on_client(page_client, "調整結果の確認画面を開けませんでした", type="warning")


async def _adapt_user_persona_to_world(
    ctx,
    profile_id: str,
    display_name: str,
    description: str,
    world: str,
    additional_instruction: str,
    apply_callback: Callable[[str], None],
    page_client=None,
    on_job_started: Callable[[str], None] | None = None,
) -> None:
    if not world.strip():
        ui.notify("先にワールドを確定してください", type="warning")
        return
    llm = _configured_llm(ctx, profile_id)
    if llm is None:
        return

    current_description = (description or "").strip()

    async def _runner() -> str:
        response = await llm.ainvoke([
            SystemMessage(content=(
                "あなたはユーザーペルソナ設定をグループチャット用に調整する編集者です。"
                "出力は更新後の説明文だけにしてください。"
            )),
            HumanMessage(content=(
                "次のユーザーペルソナが、確定ワールドに元々存在していた人物として自然に成立するように、"
                "説明文を最小限改変してください。\n"
                "ユーザーペルソナはキャラクターシート化しません。見出し、箇条書き、解説、差分説明は出力しないでください。\n"
                "名前、口調、主要な人格や役割はできるだけ維持してください。\n"
                "元の世界観情報がある場合は、確定ワールドの住人として矛盾しない内容に置き換えてください。\n\n"
                f"表示名: {display_name}\n"
                f"確定ワールド:\n{world.strip()}\n\n"
                f"{_format_optional_instruction(additional_instruction)}"
                f"現在のユーザーペルソナ説明:\n{current_description or '未設定'}"
            )),
        ])
        return _clean_persona_description_response(
            message_content_to_text(getattr(response, "content", response))
        )

    job = ctx.ai_jobs.start_job(
        kind=AIJobKind.LLM_ASSIST,
        label="ユーザーペルソナ調整",
        scope="group_setup:user_world_adapt",
        metadata={"display_name": display_name},
        runner=lambda _: _runner(),
    )
    if on_job_started is not None:
        on_job_started(job.id)
    ctx.ai_jobs.set_result_meta(job.id, {"result_url": "/groups"})
    finished = await ctx.ai_jobs.wait(job.id)
    if finished.status == AIJobStatus.CANCELLED:
        _notify_on_client(page_client, "ユーザーペルソナ調整を停止しました", type="info")
        return
    if finished.status != AIJobStatus.SUCCEEDED:
        _notify_on_client(
            page_client,
            f"ユーザーペルソナ調整に失敗しました: {finished.error_message}",
            type="negative",
            timeout=10000,
        )
        return
    updated_description = str(finished.result or "").strip()
    if not updated_description:
        _notify_on_client(page_client, "ユーザーペルソナを調整できませんでした", type="warning")
        return
    await _open_user_persona_adaptation_preview_dialog(
        display_name,
        current_description,
        updated_description,
        apply_callback,
        page_client,
    )


def _clean_persona_description_response(raw: str) -> str:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:markdown|md)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()
    parsed = _try_parse_json_fragment(text)
    if parsed is not None:
        text = _longest_json_string(parsed) or text
    text = re.sub(r"^(?:説明|ユーザーペルソナ|更新後の説明)\s*[:：]\s*", "", text.strip())
    return text.strip(" \t\r\n\"'「」『』")


async def _open_user_persona_adaptation_preview_dialog(
    display_name: str,
    current_description: str,
    updated_description: str,
    apply_callback: Callable[[str], None],
    page_client=None,
) -> None:
    diff_html = _build_group_diff_html(current_description, updated_description)
    try:
        if page_client is not None and not getattr(page_client, "_deleted", False):
            with page_client:
                with ui.dialog() as dlg, ui.card().classes("w-full max-w-3xl"):
                    ui.label("ユーザーペルソナ調整の確認").classes("text-base font-semibold")
                    ui.label(f"「{display_name}」をワールドに馴染む説明へ変更します。").classes("text-sm text-grey-6")
                    ui.html(diff_html).classes("w-full")

                    def _approve() -> None:
                        dlg.close()
                        apply_callback(updated_description)
                        _notify_on_client(page_client, "ユーザーペルソナ調整を反映しました", type="positive")

                    with ui.row().classes("justify-end gap-2 mt-4"):
                        ui.button("キャンセル", on_click=dlg.close).props("flat")
                        ui.button("反映", icon="check", on_click=_approve).props("color=primary unelevated")
                dlg.open()
        else:
            raise RuntimeError("client is not available")
    except RuntimeError:
        _notify_on_client(page_client, "調整結果の確認画面を開けませんでした", type="warning")


def _build_group_diff_html(old_text: str, new_text: str) -> str:
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm="", n=2))
    if not diff:
        return "<p style='color:#6b7280;font-style:italic;padding:8px;'>変更なし</p>"
    parts = [
        "<div style='font-family:monospace;font-size:12px;line-height:1.6;"
        "white-space:pre-wrap;word-break:break-all;'>"
    ]
    for line in diff:
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("@@"):
            parts.append(
                "<div style='color:#6b7280;background:#f3f4f6;"
                f"padding:2px 6px;border-radius:3px;margin:4px 0;'>{_html.escape(line)}</div>"
            )
        elif line.startswith("+"):
            parts.append(
                "<div style='background:#dcfce7;color:#166534;padding:1px 6px;'>"
                f"+ {_html.escape(line[1:])}</div>"
            )
        elif line.startswith("-"):
            parts.append(
                "<div style='background:#fee2e2;color:#991b1b;padding:1px 6px;'>"
                f"- {_html.escape(line[1:])}</div>"
            )
        else:
            text = line[1:] if line.startswith(" ") else line
            parts.append(
                f"<div style='color:#9ca3af;padding:1px 6px;'>&nbsp; {_html.escape(text)}</div>"
            )
    parts.append("</div>")
    return "".join(parts)


async def _generate_arrival_reason(
    ctx,
    profile_id: str,
    display_name: str,
    world: str,
    summary: str,
    page_client=None,
    on_job_started: Callable[[str], None] | None = None,
) -> str:
    if not world.strip():
        ui.notify("先にワールドを確定してください", type="warning")
        return ""
    llm = _configured_llm(ctx, profile_id)
    if llm is None:
        return ""

    async def _runner() -> str:
        response = await llm.ainvoke([
            SystemMessage(content=(
                "あなたはグループチャット用の来訪理由を作る編集者です。"
                "出力は理由本文だけにしてください。"
            )),
            HumanMessage(content=(
                "参加者が次のワールドに来た理由を、短く自然に補完してください。\n"
                "1〜3文で、会話に使いやすい具体性にしてください。"
                "見出し、箇条書き、引用符、解説は出力しないでください。\n\n"
                f"参加者: {display_name}\n"
                f"参加者概要:\n{summary or '未設定'}\n\n"
                f"ワールド:\n{world.strip()}"
            )),
        ])
        return _clean_arrival_reason_response(
            message_content_to_text(getattr(response, "content", response))
        )

    job = ctx.ai_jobs.start_job(
        kind=AIJobKind.LLM_ASSIST,
        label="来訪理由補完",
        scope="group_setup:arrival_reason",
        metadata={"display_name": display_name},
        runner=lambda _: _runner(),
    )
    if on_job_started is not None:
        on_job_started(job.id)
    ctx.ai_jobs.set_result_meta(job.id, {"result_url": "/groups"})
    finished = await ctx.ai_jobs.wait(job.id)
    if finished.status == AIJobStatus.CANCELLED:
        _notify_on_client(page_client, "来訪理由補完を停止しました", type="info")
        return ""
    if finished.status != AIJobStatus.SUCCEEDED:
        _notify_on_client(
            page_client,
            f"来訪理由補完に失敗しました: {finished.error_message}",
            type="negative",
            timeout=10000,
        )
        return ""
    reason = str(finished.result or "").strip()
    if not reason:
        _notify_on_client(page_client, "来訪理由を補完できませんでした", type="warning")
        return ""
    _notify_on_client(page_client, "来訪理由を補完しました", type="positive")
    return reason


def _clean_arrival_reason_response(raw: str) -> str:
    text = clean_short_llm_text(raw)
    text = re.sub(r"^(?:来訪理由|理由|補完結果)\s*[:：]\s*", "", text.strip())
    return text.strip(" \t\r\n\"'「」『』")


def _open_relationship_draft_dialog(
    state: dict[str, Any],
    options: dict[str, str],
    relationship: dict[str, str] | None,
    render_step: Callable[[], None],
    *,
    ctx=None,
    profile_id: str = "",
    world: str = "",
    participants: list[dict[str, str]] | None = None,
    page_client=None,
    begin_busy: Callable[[str], None] | None = None,
    set_busy_job: Callable[[str], None] | None = None,
    end_busy: Callable[[], None] | None = None,
) -> None:
    if len(options) < 2:
        ui.notify("関係性を設定できる参加者が足りません", type="warning")
        return
    keys = list(options)
    first_value = relationship["participant_a_key"] if relationship else keys[0]
    second_value = relationship["participant_b_key"] if relationship else keys[1]

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg"):
        ui.label("関係性を編集" if relationship else "関係性を追加").classes("text-base font-semibold")
        first_select = ui.select(
            options=options,
            value=first_value if first_value in options else keys[0],
            label="参加者1",
        ).props("outlined dense").classes("w-full")
        second_select = ui.select(
            options=options,
            value=second_value if second_value in options else keys[1],
            label="参加者2",
        ).props("outlined dense").classes("w-full")
        with ui.element("div").classes("cs-group-world-field"):
            description_input = ui.textarea(
                label="関係性",
                value=relationship["description"] if relationship else "",
                placeholder="例: 幼なじみだが、現在は互いに距離を測っている。",
            ).props("outlined rows=5").classes("w-full")

            async def _enhance_relationship_click() -> None:
                if ctx is None:
                    return
                if begin_busy is not None:
                    begin_busy("関係性を補完しています...")
                try:
                    enhanced = await _enhance_relationship_description(
                        ctx,
                        profile_id,
                        world,
                        participants or [],
                        str(first_select.value or ""),
                        str(second_select.value or ""),
                        str(description_input.value or ""),
                        page_client,
                        on_job_started=set_busy_job,
                    )
                    if enhanced:
                        description_input.set_value(enhanced)
                finally:
                    if end_busy is not None:
                        end_busy()

            ui.button(
                icon="auto_awesome",
                on_click=_enhance_relationship_click,
            ).props("flat round dense size=sm").classes("cs-group-world-enhance").tooltip(
                "関係性を補完"
            )

        def _save() -> None:
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
            item = {
                "id": relationship["id"] if relationship else _next_relationship_draft_id(state),
                "participant_a_key": first_key,
                "participant_b_key": second_key,
                "description": description,
            }
            _upsert_relationship_draft(state, item)
            dlg.close()
            render_step()

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("保存", icon="save", on_click=_save).props("color=primary unelevated")
    dlg.open()


async def _enhance_relationship_description(
    ctx,
    profile_id: str,
    world: str,
    participants: list[dict[str, str]],
    first_key: str,
    second_key: str,
    current_description: str,
    page_client=None,
    on_job_started: Callable[[str], None] | None = None,
) -> str:
    current = current_description.strip()
    if not current:
        ui.notify("先に関係性を入力してください", type="warning")
        return ""
    if not first_key or not second_key:
        ui.notify("参加者を選択してください", type="warning")
        return ""
    if first_key == second_key:
        ui.notify("異なる2人を選択してください", type="warning")
        return ""
    llm = _configured_llm(ctx, profile_id)
    if llm is None:
        return ""

    participant_map = {str(item.get("key") or ""): item for item in participants}
    first = participant_map.get(first_key, {"key": first_key, "name": first_key})
    second = participant_map.get(second_key, {"key": second_key, "name": second_key})

    async def _runner() -> str:
        response = await llm.ainvoke([
            SystemMessage(content=(
                "あなたはグループチャット用の関係性設定を整える編集者です。"
                "出力は補完後の関係性本文だけにしてください。"
                "箇条書き、解説、前置き、タイトルは禁止です。"
            )),
            HumanMessage(content=(
                "既存の入力内容を核にして、矛盾を増やさず具体性だけ補ってください。"
                "会話中に使いやすい短めの関係性説明にしてください。\n\n"
                f"ワールド:\n{world or '未設定'}\n\n"
                f"参加者1:\n{json.dumps(first, ensure_ascii=False)}\n\n"
                f"参加者2:\n{json.dumps(second, ensure_ascii=False)}\n\n"
                f"現在の関係性:\n{current}"
            )),
        ])
        return message_content_to_text(getattr(response, "content", response))

    job = ctx.ai_jobs.start_job(
        kind=AIJobKind.LLM_ASSIST,
        label="関係性補完",
        scope="group_setup:relationship_enhance",
        metadata={"participant_a_key": first_key, "participant_b_key": second_key},
        runner=lambda _: _runner(),
    )
    if on_job_started is not None:
        on_job_started(job.id)
    ctx.ai_jobs.set_result_meta(job.id, {"result_url": "/groups"})
    finished = await ctx.ai_jobs.wait(job.id)
    if finished.status == AIJobStatus.CANCELLED:
        _notify_on_client(page_client, "関係性補完を停止しました", type="info")
        return ""
    if finished.status != AIJobStatus.SUCCEEDED:
        _notify_on_client(
            page_client,
            f"関係性補完に失敗しました: {finished.error_message}",
            type="negative",
            timeout=10000,
        )
        return ""
    enhanced = _clean_relationship_enhancement(str(finished.result or ""))
    if not enhanced:
        _notify_on_client(page_client, "関係性を補完できませんでした", type="warning")
        return ""
    _notify_on_client(page_client, "関係性を補完しました", type="positive")
    return enhanced


def _clean_relationship_enhancement(raw: str) -> str:
    text = _clean_group_situation_enhancement(raw)
    text = re.sub(r"^(?:関係性|関係|補完結果)\s*[:：]\s*", "", text.strip())
    return text.strip(" \t\r\n\"'「」『』")


def _delete_relationship_draft(
    state: dict[str, Any],
    relationship_id: str,
    render_step: Callable[[], None],
) -> None:
    state["relationships"] = [
        item for item in state.get("relationships", [])
        if str(item.get("id")) != relationship_id
    ]
    render_step()


async def _generate_relationship_drafts(
    ctx,
    profile_id: str,
    characters: list[CharacterSheet],
    persona,
    world: str,
    state: dict[str, Any],
    page_client=None,
    on_job_started: Callable[[str], None] | None = None,
) -> list[dict[str, str]]:
    llm = _configured_llm(ctx, profile_id)
    if llm is None:
        return []

    participants = _relationship_draft_participants(characters, persona, state)
    if len(participants) < 2:
        ui.notify("関係性を自動設定できる参加者が足りません", type="warning")
        return []
    valid_keys = {item["key"] for item in participants}

    async def _runner() -> list[dict[str, str]]:
        response = await llm.ainvoke([
            SystemMessage(content=(
                "あなたはグループチャット用の参加者関係性を設計する編集者です。"
                "出力はJSONのみです。"
            )),
            HumanMessage(content=(
                "参加キャラクターとユーザーペルソナの関係性を設定してください。\n"
                "各参加者につき最大2人までとの関係にしてください。\n"
                "全員を無理に総当たりにせず、会話が動きやすい重要な関係だけを作ってください。\n"
                "重複ペアと自分自身との関係は禁止です。\n"
                "participant_a_key / participant_b_key には入力参加者の key をそのまま使ってください。\n"
                "出力形式: {\"relationships\":[{\"participant_a_key\":\"character:...\","
                "\"participant_b_key\":\"user\",\"description\":\"...\"}]}\n\n"
                f"ワールド:\n{world or '未設定'}\n\n"
                f"参加者:\n{json.dumps(participants, ensure_ascii=False)}"
            )),
        ])
        raw = message_content_to_text(getattr(response, "content", response))
        parsed = _parse_relationship_draft_response(raw, participants)
        return _limit_relationship_drafts(
            parsed,
            valid_keys,
            existing=state.get("relationships", []),
            max_per_participant=2,
        )

    job = ctx.ai_jobs.start_job(
        kind=AIJobKind.LLM_ASSIST,
        label="関係性自動設定",
        scope="group_setup:relationships",
        metadata={"participant_count": len(participants)},
        runner=lambda _: _runner(),
    )
    if on_job_started is not None:
        on_job_started(job.id)
    ctx.ai_jobs.set_result_meta(job.id, {"result_url": "/groups"})
    finished = await ctx.ai_jobs.wait(job.id)
    if finished.status == AIJobStatus.CANCELLED:
        _notify_on_client(page_client, "関係性自動設定を停止しました", type="info")
        return []
    if finished.status != AIJobStatus.SUCCEEDED:
        _notify_on_client(
            page_client,
            f"関係性自動設定に失敗しました: {finished.error_message}",
            type="negative",
            timeout=10000,
        )
        return []
    generated = list(finished.result or [])
    if not generated:
        _notify_on_client(page_client, "関係性を自動設定できませんでした", type="warning")
        return []
    for item in generated:
        item["id"] = _next_relationship_draft_id(state)
    _notify_on_client(page_client, "関係性を自動設定しました", type="positive")
    return generated


def _relationship_draft_participants(
    characters: list[CharacterSheet],
    persona,
    state: dict[str, Any],
) -> list[dict[str, str]]:
    participants = [
        {
            "key": f"character:{sheet.id}",
            "id": sheet.id,
            "name": sheet.name,
            "summary": _compact_character_summary(sheet),
            "kind": "character",
            "world_entry_type": state.get("entry_modes", {}).get(f"character:{sheet.id}", "native"),
            "arrival_reason": state.get("arrival_reasons", {}).get(f"character:{sheet.id}", ""),
            "adaptation_note": state.get("adaptation_notes", {}).get(f"character:{sheet.id}", ""),
        }
        for sheet in characters
    ]
    if persona is not None:
        participants.append({
            "key": "user",
            "id": str(getattr(persona, "id", "") or "user"),
            "name": str(getattr(persona, "display_name", "") or getattr(persona, "name", "") or "ユーザー"),
            "summary": str(state.get("user_description_draft") or getattr(persona, "description", "") or ""),
            "kind": "user_persona",
            "world_entry_type": state.get("entry_modes", {}).get("user", "native"),
            "arrival_reason": state.get("arrival_reasons", {}).get("user", ""),
            "adaptation_note": state.get("adaptation_notes", {}).get("user", ""),
        })
    return participants


def _parse_relationship_draft_response(
    raw: str,
    participants: list[dict[str, str]],
) -> list[dict[str, str]]:
    parsed = _try_parse_json_fragment(raw)
    if parsed is None:
        return []
    items = parsed.get("relationships") if isinstance(parsed, dict) else parsed
    if not isinstance(items, list):
        return []

    key_by_identifier: dict[str, str] = {}
    for item in participants:
        key = item["key"]
        key_by_identifier[key] = key
        key_by_identifier[item["id"]] = key
        key_by_identifier[item["name"]] = key

    drafts: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        first = _relationship_key_from_item(
            item,
            key_by_identifier,
            ("participant_a_key", "a_key", "character_a_key", "participant_a", "a", "character_a_id", "character_a", "from"),
        )
        second = _relationship_key_from_item(
            item,
            key_by_identifier,
            ("participant_b_key", "b_key", "character_b_key", "participant_b", "b", "character_b_id", "character_b", "to"),
        )
        description = str(
            item.get("description")
            or item.get("relationship")
            or item.get("relation")
            or item.get("summary")
            or ""
        ).strip()
        if first and second and description:
            drafts.append({
                "id": "",
                "participant_a_key": first,
                "participant_b_key": second,
                "description": description,
            })
    return drafts


def _relationship_key_from_item(
    item: dict[str, Any],
    key_by_identifier: dict[str, str],
    candidate_keys: tuple[str, ...],
) -> str:
    for key in candidate_keys:
        value = item.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text in key_by_identifier:
            return key_by_identifier[text]
        if text.startswith("character:") and text in key_by_identifier:
            return text
    return ""


def _limit_relationship_drafts(
    drafts: list[dict[str, str]],
    valid_keys: set[str],
    *,
    existing: list[dict[str, str]] | None = None,
    max_per_participant: int = 2,
) -> list[dict[str, str]]:
    counts: dict[str, int] = {key: 0 for key in valid_keys}
    seen_pairs: set[frozenset[str]] = set()
    for item in existing or []:
        first = str(item.get("participant_a_key") or "")
        second = str(item.get("participant_b_key") or "")
        if first not in valid_keys or second not in valid_keys or first == second:
            continue
        seen_pairs.add(frozenset({first, second}))
        counts[first] = counts.get(first, 0) + 1
        counts[second] = counts.get(second, 0) + 1

    result: list[dict[str, str]] = []
    for item in drafts:
        first = str(item.get("participant_a_key") or "")
        second = str(item.get("participant_b_key") or "")
        description = str(item.get("description") or "").strip()
        if first not in valid_keys or second not in valid_keys or first == second or not description:
            continue
        pair_key = frozenset({first, second})
        if pair_key in seen_pairs:
            continue
        if counts.get(first, 0) >= max_per_participant or counts.get(second, 0) >= max_per_participant:
            continue
        seen_pairs.add(pair_key)
        counts[first] = counts.get(first, 0) + 1
        counts[second] = counts.get(second, 0) + 1
        result.append({
            "id": str(item.get("id") or ""),
            "participant_a_key": first,
            "participant_b_key": second,
            "description": description,
        })
    return result


def _merge_relationship_drafts(
    state: dict[str, Any],
    relationships: list[dict[str, str]],
) -> None:
    for relationship in relationships:
        _upsert_relationship_draft(state, relationship)


def _upsert_relationship_draft(state: dict[str, Any], relationship: dict[str, str]) -> None:
    pair_key = frozenset({
        relationship["participant_a_key"],
        relationship["participant_b_key"],
    })
    relationship_id = str(relationship["id"])
    next_items: list[dict[str, str]] = []
    inserted = False
    for item in state.get("relationships", []):
        item_id = str(item.get("id") or "")
        item_pair = frozenset({
            str(item.get("participant_a_key") or ""),
            str(item.get("participant_b_key") or ""),
        })
        if item_id == relationship_id:
            next_items.append(relationship)
            inserted = True
        elif item_pair == pair_key:
            continue
        else:
            next_items.append(item)
    if not inserted:
        next_items.append(relationship)
    state["relationships"] = next_items


def _next_relationship_draft_id(state: dict[str, Any]) -> str:
    state["relationship_sequence"] = int(state.get("relationship_sequence", 0)) + 1
    return f"draft-{state['relationship_sequence']}"


def _render_section_head(icon: str, title: str) -> None:
    with ui.element("div").classes("cs-group-section-head"):
        ui.icon(icon)
        ui.label(title).classes("cs-group-section-title")


def _render_group_card(
    ctx,
    group: GroupChatRecord,
    refresh_groups: Callable[[], Awaitable[None]],
) -> None:
    with ui.element("div").classes("cs-group-card"):
        with ui.element("div").classes("cs-group-card-title-row"):
            ui.label(group.name).classes("cs-group-card-title")
            ui.label(_time_label(group.updated_at)).classes("cs-group-card-meta")
        ui.label(group.world or "世界観は未設定です").classes("cs-group-card-world")
        with ui.row().classes("items-center justify-between gap-2"):
            with ui.element("div").classes("cs-group-avatar-stack"):
                for member in group.members[:4]:
                    _render_face(ctx, member.character.media, "character")
                if group.user_persona is not None:
                    _render_face(ctx, group.user_persona.media, "persona")
            with ui.row().classes("items-center gap-1"):
                ui.button(
                    "開く",
                    icon="open_in_new",
                    on_click=lambda group_id=group.id: ui.navigate.to(f"/groups/{group_id}"),
                ).props("flat color=primary dense")
                ui.button(
                    icon="delete",
                    on_click=lambda: open_delete_group_dialog(ctx, group, refresh_groups),
                ).props("flat round dense color=negative").tooltip("グループ削除")
        ui.label(f"{len(group.members)}人 + @{group.user_persona.handle if group.user_persona else 'User'}").classes(
            "text-xs text-grey-6"
        )


def open_delete_group_dialog(
    ctx,
    group: GroupChatRecord,
    refresh_groups: Callable[[], Awaitable[None]] | None = None,
    after_delete: Callable[[], None] | None = None,
) -> None:
    with ui.dialog() as dlg, ui.card().classes("w-full max-w-md"):
        ui.label("グループを削除").classes("text-lg font-semibold")
        ui.label(f"「{group.name}」を削除します。").classes("text-sm text-grey-6")
        ui.label("この操作は元に戻せません。").classes("text-sm text-grey-6")

        async def _delete() -> None:
            deleted = await ctx.group_chats.delete_group(group.id)
            dlg.close()
            if deleted:
                ui.notify("グループを削除しました", type="positive")
                if refresh_groups is not None:
                    await refresh_groups()
                if after_delete is not None:
                    after_delete()
            else:
                ui.notify("グループが見つかりませんでした", type="warning")

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("削除", icon="delete", on_click=_delete).props(
                "color=negative unelevated"
            )
    dlg.open()


class GroupChatPageController:
    def __init__(self, ctx, group: GroupChatRecord, page_client) -> None:
        self.ctx = ctx
        self.group = group
        self.page_client = page_client
        self.participants = _group_participants(group)
        self.selected = {
            "key": self.participants[0]["key"] if self.participants else "",
            "tab": "profile",
        }
        self.profile_containers: list[tuple[Any, bool]] = []
        self.history_sections: list[Any] = []
        self.messages_container = None
        self.command_palette = None
        self.mention_palette = None
        self.title_label = None
        self.subtitle_label = None
        self.input_box = None
        self.send_button = None
        self.input_mode_icon = None
        self.sessions_by_id: dict[str, GroupChatSessionRecord] = {}
        self.threads: list[ChatThreadPreview] = []
        self.active_session_id: str | None = None
        self.active_title_is_auto = False
        self.title_generation_attempted = False
        self.title = "チャットを開始"
        self.settings: dict[str, Any] | None = None
        self.messages: list[dict[str, Any]] = []
        self.input_mode = "user"
        self.guest_input_name = ""
        self.sending = False
        self.tts_generating_index: int | None = None
        self.last_speaker_debug: ChatDebugInfo | None = None

    async def initialize(self) -> None:
        await self.reload_sessions()
        if self.sessions_by_id:
            await self.apply_session(next(iter(self.sessions_by_id.values())))

    async def reload_sessions(self) -> None:
        sessions = await self.ctx.group_chats.list_sessions_for_group(self.group.id)
        self.sessions_by_id = {session.id: session for session in sessions}
        self.threads = [self.thread_preview(session) for session in sessions]

    def render_shell(self) -> None:
        with ui.element("div").classes("cs-chat-shell cs-group-chat-shell"):
            ui.element("div").classes("cs-chat-mobile-backdrop").on(
                "click", lambda: self.set_mobile_sidebar(False)
            )

            with ui.element("aside").classes("cs-chat-mobile-sidebar cs-chat-panel"):
                with ui.row().classes("items-center justify-between px-3 py-2").style(
                    "border-bottom: 1px solid var(--cs-border);"
                ):
                    ui.label("グループ").classes("text-sm font-semibold")
                    ui.button(icon="close", on_click=lambda: self.set_mobile_sidebar(False)).props(
                        "flat round dense"
                    )
                with ui.element("div").classes("cs-chat-scroll"):
                    mobile_profile = ui.element("div")
                    self.profile_containers.append((mobile_profile, True))
                    self.render_history_section()

            with ui.element("aside").classes("cs-chat-profile-pane cs-chat-panel"):
                profile = ui.element("div")
                self.profile_containers.append((profile, False))

            with ui.element("aside").classes("cs-chat-side-pane cs-chat-panel"):
                with ui.element("div").classes("cs-chat-scroll"):
                    side_profile = ui.element("div")
                    self.profile_containers.append((side_profile, True))
                    self.render_history_section()

            with ui.element("aside").classes("cs-chat-history-pane cs-chat-panel"):
                self.render_history_section()

            with ui.element("section").classes("cs-chat-main cs-chat-panel"):
                self.render_chat_main()

        self.refresh_profiles()
        self.scroll_messages_to_bottom()
        ui.timer(0.1, self.restore_active_ai_job, once=True)

    async def restore_active_ai_job(self) -> None:
        if self.active_session_id is None:
            return
        job = self.ctx.ai_jobs.latest_active_job(scope=self._active_group_chat_scope())
        if job is None:
            return
        await self._wait_for_active_group_job(job.id, failure_message="生成に失敗しました")

    def current_participant(self) -> dict[str, Any] | None:
        for participant in self.participants:
            if participant["key"] == self.selected["key"]:
                return participant
        return self.participants[0] if self.participants else None

    def refresh_profiles(self) -> None:
        current = self.current_participant()
        for container, compact in self.profile_containers:
            container.clear()
            with container:
                _render_group_profile_panel(
                    self.ctx,
                    self.group,
                    self.participants,
                    current,
                    selected_key=self.selected["key"],
                    active_tab=self.selected["tab"],
                    select_profile=self.select_profile,
                    select_tab=self.select_tab,
                    on_group_updated=self.apply_group_update,
                    compact=compact,
                )

    def apply_group_update(self, group: GroupChatRecord) -> None:
        self.group = group
        self.participants = _group_participants(group)
        if self.participants and not any(
            participant["key"] == self.selected["key"]
            for participant in self.participants
        ):
            self.selected["key"] = self.participants[0]["key"]
        self.refresh_profiles()
        self.refresh_mention_palette()

    def mention_participants(self) -> list[dict[str, Any]]:
        active_ids: set[str] | None = None
        if self.settings is not None:
            active_ids = {
                str(member_id)
                for member_id in self.settings.get("participant_ids", [])
            }
        participants: list[dict[str, Any]] = []
        for participant in self.participants:
            if participant.get("kind") == "character" and active_ids is not None:
                member = participant.get("member")
                if not isinstance(member, GroupMember) or member.id not in active_ids:
                    continue
            participants.append(participant)
        return participants

    def render_mention_options(self) -> None:
        for index, participant in enumerate(self.mention_participants()):
            handle = str(participant.get("handle") or "").strip()
            if not _HANDLE_RE.match(handle):
                continue
            name = str(participant.get("name") or "メンバー")
            selected = "true" if index == 0 else "false"
            with ui.element("button").props(
                f"type=button data-handle={handle} aria-selected={selected}"
            ).classes("cs-group-mention-option").on(
                "mousedown",
                js_handler=_GROUP_MENTION_INSERT_JS,
            ):
                _render_participant_face(self.ctx, participant)
                with ui.element("div").classes("cs-group-mention-info"):
                    ui.label(name).classes("cs-group-mention-name")
                    ui.label(f"@{handle}").classes("cs-group-mention-handle")
                kind = "User" if participant.get("kind") == "user" else "Char"
                ui.label(kind).classes("cs-group-mention-kind")

    def refresh_mention_palette(self) -> None:
        if self.mention_palette is None:
            return
        self.mention_palette.clear()
        with self.mention_palette:
            self.render_mention_options()
        self.page_client.run_javascript(
            "document.querySelector('.cs-group-mention-palette')"
            "?.classList.add('cs-group-mention-palette-hidden');"
        )

    def refresh_command_palette(self, value: str) -> None:
        if self.command_palette is None:
            return
        self.command_palette.clear()
        parsed = parse_command_input(value)
        if parsed is None:
            self.command_palette.classes("cs-chat-command-palette-hidden")
            return
        _, query = parsed
        suggestions = command_suggestions(query)
        self.command_palette.classes(remove="cs-chat-command-palette-hidden")
        if not suggestions:
            with self.command_palette:
                ui.label("該当するコマンドがありません").classes("text-xs text-grey-6")
            return
        with self.command_palette:
            for index, command in enumerate(suggestions):
                classes = "cs-chat-command-option"
                if index == 0:
                    classes += " cs-chat-command-option-active"
                with ui.element("button").props(
                    f"type=button data-command={command.name} aria-selected={'true' if index == 0 else 'false'}"
                ).classes(classes).on(
                    "click",
                    self._command_click_handler(command.name),
                ):
                    ui.label(f"/{command.name}").classes("cs-chat-command-name")
                    ui.label(command.description).classes("cs-chat-command-desc")

    def _command_click_handler(self, command: str):
        async def _handler(_) -> None:
            current_text = str(self.input_box.value or "") if self.input_box is not None else ""
            parsed = parse_command_input(current_text)
            left_text = parsed[0] if parsed is not None else ""
            if self.command_palette is not None:
                self.command_palette.clear()
                self.command_palette.classes("cs-chat-command-palette-hidden")
            await self.send_message(False, f"{left_text}/{command}")

        return _handler

    def select_profile(self, key: str) -> None:
        self.selected["key"] = key
        self.refresh_profiles()

    def select_tab(self, tab: str) -> None:
        self.selected["tab"] = tab if tab == "world" else "profile"
        self.refresh_profiles()

    def set_mobile_sidebar(self, open_: bool) -> None:
        action = "add" if open_ else "remove"
        self.page_client.run_javascript(
            "document.querySelector('.cs-chat-shell')"
            f"?.classList.{action}('cs-mobile-sidebar-open');"
        )

    def render_history_section(self) -> None:
        with ui.element("div").classes("cs-chat-history-section") as section:
            self.history_sections.append(section)
            self.render_history()

    def render_history(self) -> None:
        with ui.element("div").classes("cs-chat-history-head"):
            ui.icon("history").style("color: var(--cs-accent);")
            ui.label("チャット履歴").classes("cs-chat-history-title")
            ui.space()
            ui.button(icon="add", on_click=self.open_new_chat_dialog).props(
                "flat round dense"
            ).tooltip("新しいチャット")
        with ui.element("div").classes("cs-chat-scroll"):
            with ui.element("div").classes("cs-chat-thread-list"):
                if not self.threads:
                    ui.label("保存済みチャットはまだありません").classes("cs-chat-history-empty")
                    return
                for thread in self.threads:
                    classes = "cs-chat-thread"
                    if thread.active:
                        classes += " cs-chat-thread-active"
                    with ui.element("div").classes(classes):
                        with ui.element("button").props("type=button").classes(
                            "cs-chat-thread-open"
                        ).on("click", self._select_thread_handler(thread.id)):
                            with ui.element("div").classes("cs-chat-thread-title-row"):
                                ui.label(thread.title).classes("cs-chat-thread-title")
                                ui.label(thread.time_label).classes("cs-chat-thread-time")
                            ui.label(thread.preview).classes("cs-chat-thread-preview")
                        with ui.element("div").classes("cs-chat-thread-actions"):
                            ui.button(
                                icon="edit",
                                on_click=lambda thread_id=thread.id: self.open_rename_chat_dialog(thread_id),
                            ).props("flat round dense size=sm").classes(
                                "cs-chat-thread-action"
                            ).tooltip("タイトル変更")
                            ui.button(
                                icon="delete",
                                on_click=lambda thread_id=thread.id: self.confirm_delete_chat_session(thread_id),
                            ).props("flat round dense size=sm color=negative").classes(
                                "cs-chat-thread-action"
                            ).tooltip("チャット削除")

    def _select_thread_handler(self, session_id: str):
        async def _handler(_) -> None:
            await self.select_chat_session(session_id)

        return _handler

    def refresh_history(self) -> None:
        for section in list(self.history_sections):
            section.clear()
            with section:
                self.render_history()

    def render_chat_main(self) -> None:
        with ui.element("div").classes("cs-chat-main-head"):
            ui.button(icon="menu", on_click=lambda: self.set_mobile_sidebar(True)).props(
                "flat round dense"
            ).classes("cs-chat-mobile-toggle")
            with ui.column().classes("gap-0 cs-chat-main-title"):
                self.title_label = ui.label(self.chat_title()).classes("text-base font-bold")
                self.subtitle_label = ui.label(self.chat_subtitle()).classes("text-xs text-grey-6")
            chat_components.render_chat_header_menu(
                open_new_chat_dialog=self.open_new_chat_dialog,
                open_system_prompt=self.open_system_prompt_dialog,
                open_rename_current_chat=self.open_rename_current_chat_dialog,
                confirm_delete_current_chat=self.confirm_delete_current_chat,
            )

        with ui.element("div").classes("cs-chat-messages") as messages_container:
            self.messages_container = messages_container
            self.render_messages()

        with ui.element("div").classes("cs-chat-composer-shell"):
            with ui.element("div").classes(
                "cs-chat-command-palette cs-chat-command-palette-hidden"
            ) as command_palette:
                self.command_palette = command_palette

            with ui.element("div").classes(
                "cs-group-mention-palette cs-group-mention-palette-hidden"
            ).props("role=listbox") as mention_palette:
                self.mention_palette = mention_palette
                self.render_mention_options()

            swipe_action_menu = ui.element("div").classes(
                "cs-chat-swipe-action-menu cs-chat-swipe-action-menu-hidden"
            )

            async def _apply_swipe_action(command: str) -> None:
                current_text = str(self.input_box.value or "") if self.input_box is not None else ""
                parsed = parse_command_input(current_text)
                left_text = parsed[0] if parsed is not None else current_text
                if self.command_palette is not None:
                    self.command_palette.clear()
                    self.command_palette.classes("cs-chat-command-palette-hidden")
                if self.mention_palette is not None:
                    self.mention_palette.classes("cs-group-mention-palette-hidden")
                swipe_action_menu.classes("cs-chat-swipe-action-menu-hidden")
                await self.send_message(False, f"{left_text.rstrip()}/{command}")

            def _swipe_action_click_handler(command: str):
                async def _handler(_) -> None:
                    await _apply_swipe_action(command)

                return _handler

            with swipe_action_menu:
                for command, label, icon in (
                    ("choices", "選択肢を生成", "format_list_bulleted"),
                    ("fill", "続きを補完", "auto_fix_high"),
                    ("tailor", "書き直す", "edit_note"),
                ):
                    with ui.element("button").props(
                        f"type=button data-swipe-command={command}"
                    ).classes("cs-chat-swipe-action-option").on(
                        "click", _swipe_action_click_handler(command)
                    ):
                        ui.icon(icon).classes("cs-chat-swipe-action-icon")
                        ui.label(f"/{command}").classes("cs-chat-swipe-action-command")
                        ui.label(label).classes("cs-chat-swipe-action-label")

            with ui.element("div").classes("cs-chat-composer"):
                self.render_input_role_selector()
                with ui.element("div").classes("cs-chat-composer-input-wrap"):
                    self.input_box = ui.textarea(placeholder="メッセージを入力").props(
                        "outlined dense rows=1 autogrow"
                    ).classes("cs-chat-composer-input")
                    voice_input_btn = ui.button(icon="mic").props(
                        "round flat dense aria-label=音声入力"
                    ).classes("cs-chat-voice-input").tooltip("音声入力")
                    voice_input_btn.on(
                        "click",
                        js_handler=chat_components.VOICE_INPUT_CLICK_JS,
                    )

                    async def _send_from_enter(e) -> None:
                        if isinstance(e.args, list):
                            value = str(e.args[0] or "") if e.args else ""
                        else:
                            value = str(e.args or "")
                        await self.send_message(False, value)

                    self.input_box.on_value_change(
                        lambda e: self.refresh_command_palette(str(e.value or ""))
                    )
                    self.input_box.on("input", js_handler=_GROUP_MENTION_REFRESH_JS)
                    self.input_box.on("keyup", js_handler=_GROUP_MENTION_REFRESH_JS)
                    self.input_box.on("click", js_handler=_GROUP_MENTION_REFRESH_JS)
                    self.input_box.on("focus", js_handler=_GROUP_MENTION_REFRESH_JS)
                    self.input_box.on(
                        "touchstart",
                        js_handler="""
event => {
  const touch = event.touches && event.touches[0];
  if (!touch) return;
  window.__csComposerSwipeStart = {
    x: touch.clientX,
    y: touch.clientY,
    time: Date.now(),
  };
}
""",
                    )
                    self.input_box.on(
                        "touchend",
                        js_handler="""
event => {
  const start = window.__csComposerSwipeStart;
  const touch = event.changedTouches && event.changedTouches[0];
  window.__csComposerSwipeStart = null;
  if (!start || !touch) return;
  const dx = touch.clientX - start.x;
  const dy = touch.clientY - start.y;
  const elapsed = Date.now() - start.time;
  const isSwipeUp = dy < -42 && Math.abs(dy) > Math.abs(dx) * 1.15 && elapsed < 900;
  if (!isSwipeUp) return;
  const menu = document.querySelector('.cs-chat-swipe-action-menu');
  const commandPalette = document.querySelector('.cs-chat-command-palette');
  const mentionPalette = document.querySelector('.cs-group-mention-palette');
  if (!menu) return;
  event.preventDefault();
  if (commandPalette) commandPalette.classList.add('cs-chat-command-palette-hidden');
  if (mentionPalette) mentionPalette.classList.add('cs-group-mention-palette-hidden');
  menu.classList.remove('cs-chat-swipe-action-menu-hidden');
  if (!window.__csSwipeActionDismiss) {
    window.__csSwipeActionDismiss = dismissEvent => {
      const currentMenu = document.querySelector('.cs-chat-swipe-action-menu');
      if (!currentMenu || currentMenu.classList.contains('cs-chat-swipe-action-menu-hidden')) return;
      const target = dismissEvent.target;
      if (target && typeof target.closest === 'function' && target.closest('.cs-chat-swipe-action-menu')) return;
      currentMenu.classList.add('cs-chat-swipe-action-menu-hidden');
    };
    document.addEventListener('click', window.__csSwipeActionDismiss, true);
    document.addEventListener('touchstart', window.__csSwipeActionDismiss, true);
  }
}
""",
                    )
                    self.input_box.on(
                        "blur",
                        js_handler="""
event => {
  setTimeout(() => {
    document.querySelector('.cs-group-mention-palette')
      ?.classList.add('cs-group-mention-palette-hidden');
  }, 120);
}
""",
                    )
                    self.input_box.on(
                        "keydown",
                        _send_from_enter,
                        js_handler=_GROUP_CHAT_INPUT_KEYDOWN_JS,
                    )

                async def _send_from_button(_) -> None:
                    await self.send_message(True)

                async def _guide_from_long_tap(e) -> None:
                    if isinstance(e.args, list):
                        value = str(e.args[0] or "") if e.args else ""
                    else:
                        value = str(e.args or "")
                    parsed = parse_command_input(value)
                    left_text = parsed[0] if parsed is not None else value
                    await self.send_message(False, f"{left_text.rstrip()}/guide")

                self.send_button = ui.button(icon="send").props("round color=primary unelevated")
                self.send_button.on(
                    "click",
                    _send_from_button,
                    js_handler="""
event => {
  if (window.__csSendLongTapSuppressClick) {
    window.__csSendLongTapSuppressClick = false;
    event.preventDefault();
    event.stopPropagation();
    return;
  }
  emit();
}
""",
                )
                self.send_button.on(
                    "touchstart",
                    _guide_from_long_tap,
                    js_handler="""
event => {
  const touch = event.touches && event.touches[0];
  if (!touch) return;
  clearTimeout(window.__csSendLongTapTimer);
  window.__csSendLongTapStart = {
    x: touch.clientX,
    y: touch.clientY,
  };
  window.__csSendLongTapTriggered = false;
  window.__csSendLongTapTimer = setTimeout(() => {
    window.__csSendLongTapTriggered = true;
    window.__csSendLongTapSuppressClick = true;
    setTimeout(() => {
      window.__csSendLongTapSuppressClick = false;
    }, 1200);
    const input = document.querySelector('.cs-chat-composer-input textarea');
    emit(input && typeof input.value === 'string' ? input.value : '');
  }, 650);
}
""",
                )
                self.send_button.on(
                    "touchmove",
                    js_handler="""
event => {
  const start = window.__csSendLongTapStart;
  const touch = event.touches && event.touches[0];
  if (!start || !touch) return;
  const dx = touch.clientX - start.x;
  const dy = touch.clientY - start.y;
  if (Math.hypot(dx, dy) > 14) {
    clearTimeout(window.__csSendLongTapTimer);
  }
}
""",
                )
                self.send_button.on(
                    "touchend",
                    js_handler="""
event => {
  clearTimeout(window.__csSendLongTapTimer);
  window.__csSendLongTapStart = null;
  if (window.__csSendLongTapTriggered) {
    event.preventDefault();
  }
}
""",
                )
                self.send_button.on(
                    "touchcancel",
                    js_handler="""
event => {
  clearTimeout(window.__csSendLongTapTimer);
  window.__csSendLongTapStart = null;
  window.__csSendLongTapTriggered = false;
}
""",
                )
        self.refresh_input_mode_indicator()

    def render_input_role_selector(self) -> None:
        with ui.button().props("flat dense unelevated aria-label=入力ロールを変更").classes(
            "cs-chat-mode-icon"
        ):
            self.input_mode_icon = ui.element("div").classes("cs-chat-mode-icon-display")
            with self.input_mode_icon:
                ui.icon(_group_input_mode_icon(self.input_mode))
            with ui.menu().classes("cs-chat-mode-menu"):
                with ui.element("button").props("type=button").classes("cs-group-menu-option").on(
                    "click",
                    lambda _: self.set_input_mode("user"),
                ):
                    _render_group_user_menu_face(self.ctx, self.group.user_persona)
                    ui.label("ユーザー").classes("cs-group-menu-option-label")
                    ui.element("span")
                with ui.element("button").props("type=button").classes("cs-group-menu-parent"):
                    _render_group_role_icon("character")
                    ui.label("キャラクター").classes("cs-group-menu-option-label")
                    ui.icon("chevron_right").classes("text-grey-6")
                    with ui.menu().props('anchor="top end" self="top start"').classes(
                        "cs-chat-mode-menu cs-group-character-submenu"
                    ):
                        active = self.active_members()
                        if not active:
                            ui.label("参加キャラがいません").classes("text-xs text-grey-6 px-3 py-2")
                        for member in active:
                            with ui.element("button").props("type=button").classes(
                                "cs-group-menu-option"
                            ).on(
                                "click",
                                lambda _, member=member: self.set_character_input_member(member),
                            ):
                                _render_group_member_menu_face(self.ctx, member)
                                ui.label(
                                    f"{member.character.name} / @{member.handle}"
                                ).classes("cs-group-menu-option-label")
                                ui.element("span")
                        with ui.element("button").props("type=button").classes(
                            "cs-group-menu-option"
                        ).on(
                            "click",
                            lambda _: self.open_guest_input_mode_dialog(),
                        ):
                            _render_group_role_icon("guest")
                            ui.label("ゲスト").classes("cs-group-menu-option-label")
                            ui.element("span")
                with ui.element("button").props("type=button").classes("cs-group-menu-option").on(
                    "click",
                    lambda _: self.set_input_mode("narration"),
                ):
                    _render_group_role_icon("narration")
                    ui.label("ナラティブ").classes("cs-group-menu-option-label")
                    ui.element("span")
                with ui.element("button").props("type=button").classes("cs-group-menu-option").on(
                    "click",
                    lambda _: self.set_input_mode("memo"),
                ):
                    _render_group_role_icon("memo")
                    ui.label("コメント").classes("cs-group-menu-option-label")
                    ui.element("span")

    def set_input_mode(self, mode: str) -> None:
        self.input_mode = mode if mode in {"user", "character", "guest", "narration", "memo"} else "user"
        if self.input_mode != "guest":
            self.guest_input_name = ""
        self.refresh_input_mode_indicator()

    def set_character_input_member(self, member: GroupMember) -> None:
        self.selected["key"] = f"member:{member.id}"
        self.set_input_mode("character")
        self.refresh_profiles()

    def set_guest_input_mode(self, guest_name: str) -> None:
        name = _clean_guest_name(guest_name)
        if not name:
            ui.notify("ゲスト名を入力してください", type="warning")
            return
        self.guest_input_name = name
        self.input_mode = "guest"
        self.refresh_input_mode_indicator()

    def open_guest_input_mode_dialog(self, left_text: str = "") -> None:
        with ui.dialog() as dlg, ui.card().classes("w-full max-w-sm"):
            ui.label("ゲスト入力").classes("text-base font-semibold")
            name_input = ui.input(
                label="ゲスト名",
                value=self.guest_input_name,
                placeholder="例: 酒場のマスター",
            ).props("outlined dense clearable").classes("w-full")

            def _apply() -> None:
                name = _clean_guest_name(str(name_input.value or ""))
                if not name:
                    ui.notify("ゲスト名を入力してください", type="warning")
                    return
                self.set_guest_input_mode(name)
                if left_text:
                    self.set_input_value(left_text.rstrip())
                self.focus_chat_input_at_end()
                dlg.close()
                ui.notify(f"{_guest_display_name(name)}入力モードにしました", type="info")

            with ui.row().classes("justify-end gap-2 mt-4"):
                ui.button("キャンセル", on_click=dlg.close).props("flat")
                ui.button("選択", icon="person_add", on_click=_apply).props(
                    "color=primary unelevated"
                )
        dlg.open()
        ui.timer(0.1, lambda: name_input.run_method("focus"), once=True)

    def refresh_input_mode_indicator(self) -> None:
        if self.input_mode_icon is None:
            return
        self.input_mode_icon.clear()
        with self.input_mode_icon:
            ui.icon(_group_input_mode_icon(self.input_mode))

    def chat_title(self) -> str:
        return self.title or "チャットを開始"

    def chat_subtitle(self) -> str:
        if self.settings is None:
            return "新しいチャットを開始してください"
        profile = self.ctx.api_config.get_llm_profile(str(self.settings.get("profile_id", "")))
        profile_name = profile.name if profile else "不明なプロファイル"
        active_names = [
            member.character.name
            for member in self.active_members()
        ]
        members = "、".join(active_names) if active_names else "参加キャラなし"
        return f"{self.group.name} / {members} / {profile_name}"

    def refresh_chat_header(self) -> None:
        if self.title_label is not None:
            self.title_label.set_text(self.chat_title())
        if self.subtitle_label is not None:
            self.subtitle_label.set_text(self.chat_subtitle())

    def render_messages(self) -> None:
        if not self.messages:
            with ui.element("div").classes("cs-group-chat-empty"):
                ui.label("チャットはまだありません")
            return
        for index, message in enumerate(self.messages):
            _render_group_chat_message(
                self.ctx,
                message,
                self.participants,
                index=index,
                rewind_message=self.confirm_rewind_to_message,
                rewrite_message=self.open_rewrite_message_dialog,
                regenerate_message=self.confirm_or_regenerate_character_message,
                play_tts_message=self.play_tts_message,
                tts_playable=self.message_tts_playable(message),
                tts_generating=self.tts_generating_index == index,
            )

    def refresh_messages(self, *, scroll_to_bottom: bool = False) -> None:
        if self.messages_container is None:
            return
        self.messages_container.clear()
        with self.messages_container:
            self.render_messages()
        if scroll_to_bottom:
            self.scroll_messages_to_bottom()

    def scroll_messages_to_bottom(self) -> None:
        self.page_client.run_javascript(
            "(() => {"
            "const scroll = () => {"
            "const el = document.querySelector('.cs-chat-messages');"
            "if (el) el.scrollTop = el.scrollHeight;"
            "};"
            "setTimeout(scroll, 0);"
            "setTimeout(scroll, 50);"
            "})();"
        )

    def set_sending(self, sending: bool) -> None:
        self.sending = sending
        if self.send_button is not None:
            self.send_button.disable() if sending else self.send_button.enable()
        if self.input_box is not None:
            self.input_box.disable() if sending else self.input_box.enable()

    def set_input_value(self, value: str) -> None:
        if self.input_box is not None:
            self.input_box.set_value(value)

    def focus_chat_input_at_end(self) -> None:
        self.page_client.run_javascript(
            "setTimeout(() => {"
            "const el = document.querySelector('.cs-chat-composer-input textarea');"
            "if (!el) return;"
            "el.focus();"
            "const end = el.value.length;"
            "if (typeof el.setSelectionRange === 'function') el.setSelectionRange(end, end);"
            "}, 0);"
        )

    def clear_input(self) -> None:
        if self.input_box is not None:
            self.input_box.set_value("")
        self.page_client.run_javascript(
            "(() => {"
            "const clear = () => {"
            "const el = document.querySelector('.cs-chat-composer-input textarea');"
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

    def thread_preview(self, session: GroupChatSessionRecord) -> ChatThreadPreview:
        return ChatThreadPreview(
            id=session.id,
            title=session.title or DEFAULT_GROUP_CHAT_TITLE,
            preview=_latest_group_message_preview(session.messages),
            time_label=_time_label(session.updated_at),
            active=session.id == self.active_session_id,
        )

    async def apply_session(self, session: GroupChatSessionRecord) -> None:
        self.active_session_id = session.id
        self.active_title_is_auto = session.title_is_auto
        self.title_generation_attempted = False
        self.title = session.title or DEFAULT_GROUP_CHAT_TITLE
        self.settings = dict(session.settings or {})
        self.messages = [dict(message) for message in session.messages if isinstance(message, dict)]
        self.input_mode = "user"
        self.guest_input_name = ""
        self.sending = False
        self.tts_generating_index = None
        self.threads = [self.thread_preview(current) for current in self.sessions_by_id.values()]
        self.refresh_mention_palette()

    def clear_active_session(self) -> None:
        self.active_session_id = None
        self.active_title_is_auto = False
        self.title_generation_attempted = False
        self.title = "チャットを開始"
        self.settings = None
        self.messages = []
        self.input_mode = "user"
        self.guest_input_name = ""
        self.sending = False
        self.tts_generating_index = None
        self.threads = [self.thread_preview(current) for current in self.sessions_by_id.values()]
        self.refresh_mention_palette()

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
            self.refresh_history()

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
        self.refresh_input_mode_indicator()
        self.refresh_chat_header()
        self.refresh_messages(scroll_to_bottom=True)
        await self.reload_sessions()
        self.refresh_history()

    def _active_group_chat_scope(self) -> str:
        return f"group_chat:{self.active_session_id or 'none'}"

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

    async def _run_group_llm_assist_job(self, *, label: str, runner, failure_message: str):
        job = self.ctx.ai_jobs.start_job(
            kind=AIJobKind.LLM_ASSIST,
            label=label,
            scope=f"group_assist:{self.active_session_id or self.group.id}",
            metadata={"group_id": self.group.id, "session_id": self.active_session_id or ""},
            runner=lambda _: runner(),
        )
        if self.active_session_id:
            self.ctx.ai_jobs.set_result_meta(job.id, {"result_url": f"/groups/{self.group.id}"})
        self.set_sending(True)
        try:
            finished = await self.ctx.ai_jobs.wait(job.id)
            if finished.status == AIJobStatus.SUCCEEDED:
                return finished.result
            if finished.status == AIJobStatus.CANCELLED:
                ui.notify("生成を停止しました", type="info")
                return None
            ui.notify(f"{failure_message}: {finished.error_message}", type="negative", timeout=10000)
            return None
        finally:
            self.set_sending(False)

    async def rewind_to_message(self, index: int) -> None:
        if index < 0 or index >= len(self.messages):
            return
        message = self.messages[index]
        role = str(message.get("role", ""))
        if role not in {"character", "guest", "user", "narration", "memo"}:
            return
        self.messages = self.messages[:index]
        if self.input_box is not None:
            self.input_box.set_value(str(message.get("text", "")))
            self.input_box.enable()
        if role == "guest":
            self.guest_input_name = _clean_guest_name(str(message.get("guest_name") or message.get("speaker_name") or ""))
        self.set_input_mode(_group_input_mode_for_role(role))
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
        role = str(message.get("role", ""))
        if role not in {"character", "guest", "user", "narration", "memo"}:
            return

        target_label = _group_message_target_label(role)
        with ui.dialog() as dlg, ui.card().classes("w-full max-w-sm"):
            ui.label(f"この{target_label}まで戻りますか？").classes("text-base font-semibold")
            ui.label(f"この{target_label}以降の会話を削除し、本文を入力欄に戻します。").classes(
                "text-sm text-grey-6"
            )
            ui.label(str(message.get("text", ""))).classes("text-sm").style(
                "white-space: pre-wrap; overflow-wrap: anywhere;"
            )

            async def _do_rewind() -> None:
                dlg.close()
                await self.rewind_to_message(index)

            with ui.row().classes("justify-end gap-2 mt-4"):
                ui.button("キャンセル", on_click=dlg.close).props("flat")
                ui.button("OK", icon="undo", on_click=_do_rewind).props(
                    "color=primary unelevated"
                )
        dlg.open()

    def open_rewrite_message_dialog(self, index: int) -> None:
        if self.sending:
            ui.notify("生成中は書き換えできません", type="warning")
            return
        if index < 0 or index >= len(self.messages):
            return
        message = self.messages[index]
        role = str(message.get("role", ""))
        if role not in {"character", "guest", "user", "narration", "memo"}:
            return
        speaker_label = _group_message_target_label(role)

        with ui.dialog() as dlg, ui.card().classes("w-full max-w-xl"):
            ui.label(f"{speaker_label}を書き換え").classes("text-base font-semibold")
            ui.label("保存しても、この後の会話は削除されません。").classes("text-sm text-grey-6")
            rewrite_input = ui.textarea(
                value=str(message.get("text", "")),
                placeholder="書き換え後の本文",
            ).props("outlined rows=5 autogrow").classes("w-full")

            async def _save_rewrite() -> None:
                next_text = (rewrite_input.value or "").strip()
                if not next_text:
                    ui.notify("本文を入力してください", type="warning")
                    return
                if index >= len(self.messages):
                    dlg.close()
                    return
                self.messages[index]["text"] = next_text
                dlg.close()
                self.refresh_messages()
                await self.save_current_session()

            with ui.row().classes("justify-end gap-2 mt-4"):
                ui.button("キャンセル", on_click=dlg.close).props("flat")
                ui.button("保存", icon="save", on_click=_save_rewrite).props(
                    "color=primary unelevated"
                )
        dlg.open()

    async def regenerate_character_message(self, index: int) -> None:
        if self.sending:
            ui.notify("生成中は再生成できません", type="warning")
            return
        if self.settings is None:
            ui.notify("先に「新しいチャット」を作成してください", type="warning")
            self.open_new_chat_dialog()
            return
        if index < 0 or index >= len(self.messages):
            return
        message = self.messages[index]
        if message.get("role") != "character":
            return
        active = self.active_members()
        if not active:
            ui.notify("参加キャラがいません", type="warning")
            return
        llm = _configured_group_chat_llm(self.ctx, str(self.settings.get("profile_id", "")))
        if llm is None:
            return
        if self.active_session_id is None:
            return

        original_messages = [dict(item) for item in self.messages]
        prior_messages = [dict(item) for item in self.messages[:index]]
        rollback_messages = original_messages if index == len(original_messages) - 1 else prior_messages
        self.last_speaker_debug = None

        display_speaker = self._member_by_id(str(message.get("speaker_id", ""))) or active[0]
        self.messages = prior_messages + [_group_message("character", "…", member=display_speaker)]
        self.refresh_messages()
        session_id = self.active_session_id
        title = self.title
        title_is_auto = self.active_title_is_auto
        settings_snapshot = dict(self.settings)
        await self.save_current_session(refresh_history=False)

        async def _runner(job) -> list[dict[str, Any]]:
            try:
                self.messages = [dict(item) for item in prior_messages]
                self.last_speaker_debug = None
                speaker = await self.choose_next_speaker(llm, active)
                speaker_debug = self.last_speaker_debug
                generated = await self.build_character_message(
                    llm,
                    speaker,
                    speaker_debug=speaker_debug,
                    prior_messages=prior_messages,
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
                    messages=rollback_messages,
                )
                raise

        job = self.ctx.ai_jobs.start_job(
            kind=AIJobKind.LLM_GROUP_CHAT,
            label=f"{self.group.name or 'グループ'}の再生成",
            scope=self._active_group_chat_scope(),
            metadata={"session_id": session_id, "group_id": self.group.id},
            runner=_runner,
        )
        self.ctx.ai_jobs.set_result_meta(job.id, {"result_url": f"/groups/{self.group.id}"})
        generated_successfully = await self._wait_for_active_group_job(
            job.id,
            failure_message="再生成に失敗しました",
        )
        if generated_successfully:
            await self.maybe_generate_auto_title(llm)

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

        with ui.dialog() as dlg, ui.card().classes("w-full max-w-sm"):
            ui.label("この台詞から再生成しますか？").classes("text-base font-semibold")
            ui.label("この台詞以降の会話を削除してから、新しい台詞を生成します。").classes(
                "text-sm text-grey-6"
            )
            ui.label(str(self.messages[index].get("text", ""))).classes("text-sm").style(
                "white-space: pre-wrap; overflow-wrap: anywhere;"
            )

            async def _do_regenerate() -> None:
                dlg.close()
                await self.regenerate_character_message(index)

            with ui.row().classes("justify-end gap-2 mt-4"):
                ui.button("キャンセル", on_click=dlg.close).props("flat")
                ui.button("再生成", icon="refresh", on_click=_do_regenerate).props(
                    "color=primary unelevated"
                )
        dlg.open()

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
                    "result_url": f"/groups/{self.group.id}",
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
            self.page_client.run_javascript(
                "(() => {"
                f"const audio = new Audio({json.dumps(audio_url)});"
                "audio.play().catch(() => {});"
                "})();"
            )
        except TTSServiceError as err:
            ui.notify(f"読み上げに失敗しました: {err}", type="negative", timeout=10000)
        except Exception as err:
            ui.notify(f"読み上げに失敗しました: {err}", type="negative", timeout=10000)
        finally:
            self.tts_generating_index = None
            self.refresh_messages()

    def _member_by_id(self, member_id: str) -> GroupMember | None:
        return next((member for member in self.group.members if member.id == member_id), None)

    def _character_tts_configured(self, member: GroupMember) -> bool:
        voice = member.character.media.primary_voice()
        voice_path = self.ctx.characters.media_path(voice.path) if voice else None
        return bool(
            voice
            and voice_path
            and self.ctx.tts.has_voice_playback_api(
                member.character.media.tts.api_type,
                member.character.media.tts.endpoint_id,
            )
        )

    def _user_persona_tts_configured(self, persona: GroupUserPersona) -> bool:
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
        voice_path = self.ctx.api_config.media_path(voice.path) if voice else None
        return bool(
            voice
            and voice_path
            and self.ctx.tts.has_voice_playback_api(settings.api_type, settings.endpoint_id)
        )

    def _narrator_tts_configured(self, tts_settings=None) -> bool:
        config = self.ctx.api_config.get_tts_config()
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
        voice_path = self.ctx.api_config.media_path(voice.path) if voice else None
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
            config = self.ctx.api_config.get_tts_config()
            settings = config.narrator
            if not self._narrator_tts_configured(settings):
                ui.notify("ナレーターTTS設定を確認してください", type="warning")
                return None
            voice = config.narrator_voice
            voice_path = self.ctx.api_config.media_path(voice.path) if voice else None
            return {
                "target_id": "narrator",
                "settings": settings,
                "voice": voice,
                "voice_path": voice_path,
                "playback_save": self.ctx.api_config.save_narrator_tts_playback,
            }
        if role == "character":
            member = self._member_by_id(str(message.get("speaker_id", "")))
            if member is None or not self._character_tts_configured(member):
                ui.notify("TTS設定を確認してください", type="warning")
                return None
            voice = member.character.media.primary_voice()
            voice_path = self.ctx.characters.media_path(voice.path) if voice else None
            character_id = member.character.id or member.source_character_id
            return {
                "target_id": character_id,
                "settings": member.character.media.tts,
                "voice": voice,
                "voice_path": voice_path,
                "playback_save": lambda audio, target_id=character_id: self.ctx.characters.save_tts_playback(
                    target_id,
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
            voice_path = self.ctx.api_config.media_path(voice.path) if voice else None
            if voice_path is None and not self._voice_design_ready(settings):
                ui.notify("ユーザーペルソナのTTS設定を確認してください", type="warning")
                return None
            persona_id = persona.id
            return {
                "target_id": _group_user_persona_tts_id(persona_id),
                "settings": settings,
                "voice": voice,
                "voice_path": voice_path,
                "playback_save": lambda audio, target_id=persona_id: self.ctx.api_config.save_user_persona_tts_playback(
                    target_id,
                    audio,
                ),
            }
        return None

    async def select_chat_session(self, session_id: str) -> None:
        if self.sending:
            ui.notify("生成中はチャットを切り替えられません", type="warning")
            return
        session = await self.ctx.group_chats.get_session(session_id)
        if session is None or session.group_id != self.group.id:
            ui.notify("チャットが見つかりません", type="warning")
            await self.reload_sessions()
            self.refresh_history()
            return
        self.sessions_by_id[session.id] = session
        await self.apply_session(session)
        self.refresh_input_mode_indicator()
        self.refresh_chat_header()
        self.refresh_messages(scroll_to_bottom=True)
        self.refresh_history()
        self.refresh_mention_palette()
        self.set_mobile_sidebar(False)

    def active_members(self) -> list[GroupMember]:
        if self.settings is None:
            return []
        ids = {
            str(member_id)
            for member_id in self.settings.get("participant_ids", [])
        }
        return [member for member in self.group.members if member.id in ids]

    async def post_narration(self, text: str) -> None:
        self.messages.append(_group_message("narration", text))
        self.refresh_messages(scroll_to_bottom=True)
        await self.save_current_session()

    async def post_memo(self, text: str) -> None:
        self.messages.append(_group_message("memo", text))
        self.refresh_messages(scroll_to_bottom=True)
        await self.save_current_session()

    async def post_character_input(self, text: str, member: GroupMember | None = None) -> None:
        member = member or self._manual_character_speaker()
        if member is None:
            ui.notify("参加キャラがいません", type="warning")
            self.set_input_mode("user")
            return
        self.messages.append(_group_message("character", text, member=member))
        self.refresh_messages(scroll_to_bottom=True)
        await self.save_current_session()

    async def post_guest_input(self, text: str, guest_name: str | None = None) -> None:
        name = _clean_guest_name(guest_name or self.guest_input_name)
        if not name:
            ui.notify("ゲスト名を入力してください", type="warning")
            self.open_guest_input_mode_dialog(text)
            return
        self.messages.append(_group_message("guest", text, guest_name=name))
        self.refresh_messages(scroll_to_bottom=True)
        await self.save_current_session()

    async def post_hold_user_text(self, text: str) -> None:
        self.messages.append(_group_message("user", text, user=self.group.user_persona))
        self.refresh_messages(scroll_to_bottom=True)
        await self.save_current_session()

    async def post_command_left_text(self, left_text: str) -> None:
        text = left_text.strip()
        if not text:
            return
        self.clear_input()
        if self.input_mode == "narration":
            await self.post_narration(text)
            self.set_input_mode("user")
            return
        if self.input_mode == "memo":
            await self.post_memo(text)
            self.set_input_mode("user")
            return
        if self.input_mode == "character":
            await self.post_character_input(text)
            self.set_input_mode("user")
            return
        if self.input_mode == "guest":
            await self.post_guest_input(text)
            self.set_input_mode("user")
            return
        await self.post_hold_user_text(text)

    async def send_user_turn(self, text: str) -> None:
        self.clear_input()
        self.messages.append(_group_message("user", text.strip(), user=self.group.user_persona))
        self.set_input_mode("user")
        self.refresh_messages(scroll_to_bottom=True)
        await self.save_current_session(refresh_history=False)
        await self.append_character_turn()

    async def generate_scene(self, *, instruction: str = "") -> None:
        if self.settings is None:
            return
        llm = _configured_group_chat_llm(self.ctx, str(self.settings.get("profile_id", "")))
        if llm is None:
            return
        if self.active_session_id is None:
            return

        prior_messages = [dict(message) for message in self.messages]
        self.messages.append(_group_message("narration", "…"))
        self.refresh_messages(scroll_to_bottom=True)
        session_id = self.active_session_id
        title = self.title
        title_is_auto = self.active_title_is_auto
        settings_snapshot = dict(self.settings)
        await self.save_current_session(refresh_history=False)

        async def _runner(job) -> list[dict[str, Any]]:
            llm_messages = _build_group_narration_messages(
                self.group,
                settings_snapshot,
                prior_messages,
                instruction=instruction,
            )
            debug_input = format_llm_input(llm_messages)
            response = await llm.ainvoke(llm_messages)
            raw = message_content_to_text(getattr(response, "content", response))
            narration = _sanitize_group_narration(raw)
            if not narration:
                narration = "場面は静かに次の言葉を待っている。"
            messages = prior_messages + [_group_message(
                "narration",
                narration,
                debug=build_debug_info(debug_input, raw, response),
            )]
            await self._save_session_messages_snapshot(
                session_id=session_id,
                title=title,
                title_is_auto=title_is_auto,
                settings=settings_snapshot,
                messages=messages,
            )
            return messages

        async def _safe_runner(job) -> list[dict[str, Any]]:
            try:
                return await _runner(job)
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
            scope=self._active_group_chat_scope(),
            metadata={"session_id": session_id, "group_id": self.group.id},
            runner=_safe_runner,
        )
        self.ctx.ai_jobs.set_result_meta(job.id, {"result_url": f"/groups/{self.group.id}"})
        await self._wait_for_active_group_job(
            job.id,
            failure_message="地の文生成に失敗しました",
        )

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

    async def fill_input_text(self, left_text: str) -> None:
        if self.settings is None:
            return
        if not left_text.strip():
            ui.notify("補完する文を /fill の左側に入力してください", type="warning")
            return
        llm = _configured_group_chat_llm(self.ctx, str(self.settings.get("profile_id", "")))
        if llm is None:
            return

        async def _runner() -> str:
            response = await llm.ainvoke(
                _build_group_input_completion_messages(
                    self.group,
                    self.settings,
                    self.messages,
                    left_text,
                    input_mode=self.input_mode,
                    speaker=self._manual_character_speaker(),
                    guest_name=self.guest_input_name,
                )
            )
            return message_content_to_text(getattr(response, "content", response))

        raw = await self._run_group_llm_assist_job(
            label="グループ入力補完",
            runner=_runner,
            failure_message="補完に失敗しました",
        )
        if raw is None:
            return
        self.set_input_value(merge_completion(left_text, raw))
        ui.notify("続きを補完しました", type="positive")
        self.focus_chat_input_at_end()

    async def tailor_input_text(self, left_text: str) -> None:
        if self.settings is None:
            return
        if not left_text.strip():
            ui.notify("書き換える文を /tailor の左側に入力してください", type="warning")
            return
        llm = _configured_group_chat_llm(self.ctx, str(self.settings.get("profile_id", "")))
        if llm is None:
            return

        async def _runner() -> str:
            response = await llm.ainvoke(
                _build_group_tailored_input_messages(
                    self.group,
                    self.settings,
                    self.messages,
                    left_text,
                    input_mode=self.input_mode,
                    speaker=self._manual_character_speaker(),
                    guest_name=self.guest_input_name,
                )
            )
            return message_content_to_text(getattr(response, "content", response))

        raw = await self._run_group_llm_assist_job(
            label="グループ入力書き換え",
            runner=_runner,
            failure_message="書き換えに失敗しました",
        )
        if raw is None:
            return
        tailored = clean_short_llm_text(raw)
        if not tailored:
            ui.notify("書き換え結果が空でした", type="warning")
            return
        self.set_input_value(tailored)
        ui.notify("現在のロール向けに書き換えました", type="positive")
        self.focus_chat_input_at_end()

    async def show_response_choices(self, left_text: str) -> None:
        if self.settings is None:
            return
        llm = _configured_group_chat_llm(self.ctx, str(self.settings.get("profile_id", "")))
        if llm is None:
            return
        input_mode = self.input_mode
        speaker = self._manual_character_speaker()
        guest_name = self.guest_input_name

        async def _runner() -> list[str]:
            response = await llm.ainvoke(
                _build_group_response_choice_messages(
                    self.group,
                    self.settings,
                    self.messages,
                    left_text,
                    input_mode=input_mode,
                    speaker=speaker,
                    guest_name=guest_name,
                )
            )
            raw = message_content_to_text(getattr(response, "content", response))
            choices = parse_response_choices(raw)
            if left_text.strip():
                choices = [merge_completion(left_text, choice) for choice in choices]
            return choices

        choices = await self._run_group_llm_assist_job(
            label="グループ応答候補生成",
            runner=_runner,
            failure_message="選択肢生成に失敗しました",
        )
        if choices is None:
            return

        if not choices:
            ui.notify("選択肢を生成できませんでした", type="warning")
            return

        with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg cs-chat-choice-dialog"):
            ui.label("応答を選択").classes("text-base font-semibold")
            target_label = _group_message_target_label(input_mode)
            ui.label(f"選ぶとその{target_label}を入力欄に入れます。").classes("text-sm text-grey-6")

            def _choose(choice: str) -> None:
                dlg.close()
                self.set_input_value(choice)
                self.focus_chat_input_at_end()

            def _choice_click_handler(choice: str):
                def _handler() -> None:
                    _choose(choice)

                return _handler

            with ui.column().classes("w-full gap-2 mt-2"):
                for index, choice in enumerate(choices[:3]):
                    classes = "w-full cs-chat-choice-option"
                    if index == 0:
                        classes += " cs-chat-choice-option-active"
                    ui.button(choice, on_click=_choice_click_handler(choice)).props(
                        f"outline color=primary align=left data-choice-index={index} aria-selected={'true' if index == 0 else 'false'}"
                    ).classes(classes)
            with ui.row().classes("justify-end mt-2"):
                ui.button("閉じる", on_click=dlg.close).props(
                    "flat data-choice-index=close aria-selected=false"
                ).classes("cs-chat-choice-close")
        dlg.open()
        self.install_choice_keyboard_handler()

    def install_choice_keyboard_handler(self) -> None:
        self.page_client.run_javascript(
            """
setTimeout(() => {
  const root = document.querySelector('.cs-chat-choice-dialog');
  if (!root) return;
  const options = Array.from(root.querySelectorAll('.cs-chat-choice-option, .cs-chat-choice-close'));
  if (!options.length) return;
  const activeIndex = () => Math.max(0, options.findIndex(option => option.classList.contains('cs-chat-choice-option-active')));
  const setActive = index => {
    options.forEach((option, optionIndex) => {
      const active = optionIndex === index;
      option.classList.toggle('cs-chat-choice-option-active', active);
      option.setAttribute('aria-selected', active ? 'true' : 'false');
      if (active && typeof option.scrollIntoView === 'function') {
        option.scrollIntoView({ block: 'nearest' });
      }
    });
  };
  setActive(0);
  if (window.__csChoiceKeydown) {
    document.removeEventListener('keydown', window.__csChoiceKeydown, true);
  }
  window.__csChoiceKeydown = event => {
    if (!document.body.contains(root)) {
      document.removeEventListener('keydown', window.__csChoiceKeydown, true);
      window.__csChoiceKeydown = null;
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
  document.addEventListener('keydown', window.__csChoiceKeydown, true);
}, 0);
"""
        )

    async def open_guide_next_turn_dialog(self, left_text: str = "") -> None:
        if left_text.strip():
            self.set_input_value(left_text)
        else:
            self.clear_input()

        active = self.active_members()
        active_ids = {member.id for member in active}
        inactive = [member for member in self.group.members if member.id not in active_ids]
        departure_state = {"value": False}
        departure_checkbox: dict[str, Any] = {"ref": None}
        actor_value_syncing = {"active": False}
        guide_targets = {
            "character": ("キャラクター（自動）", "character", "theater_comedy"),
            "narrative": ("地の文", "narration", "auto_stories"),
            "user": ("ユーザー", "user", "person"),
        }

        def _resolve_actor_input(value: str) -> dict[str, Any] | None:
            raw = (value or "").strip()
            lowered = raw.lower()
            guest_name = _guest_name_from_actor_text(raw)
            if guest_name:
                return {
                    "kind": "guest",
                    "active": False,
                    "member": None,
                    "guest_name": guest_name,
                    "label": _guest_display_name(guest_name),
                }
            if lowered in {"character", "char", "キャラ", "キャラクター", "キャラクター（自動）"}:
                return {"kind": "auto", "active": False, "member": None, "label": "キャラクター（自動）"}
            if lowered in {"narrative", "narration", "地の文", "ナラティブ"}:
                return {"kind": "narration", "active": False, "member": None, "label": "地の文"}
            if lowered in {"user", "ユーザー"}:
                return {"kind": "user", "active": False, "member": None, "label": "ユーザー"}
            identifier = lowered.removeprefix("@")
            for member in self.group.members:
                if member.handle.lower() == identifier:
                    return {
                        "kind": "member",
                        "active": member.id in active_ids,
                        "member": member,
                        "label": f"{member.character.name} / @{member.handle}",
                    }
                if raw and member.character.name == raw:
                    return {
                        "kind": "member",
                        "active": member.id in active_ids,
                        "member": member,
                        "label": f"{member.character.name} / @{member.handle}",
                    }
            return None

        def _actor_display_value(resolved: dict[str, Any]) -> str:
            member = resolved.get("member")
            if isinstance(member, GroupMember):
                return member.character.name
            if resolved.get("kind") == "guest":
                return _guest_display_name(str(resolved.get("guest_name") or ""))
            return str(resolved.get("label") or "")

        def _actor_suggestions(value: str) -> list[dict[str, Any]]:
            raw = (value or "").strip()
            if not raw:
                return []
            resolved = _resolve_actor_input(raw)
            if resolved is not None:
                return []
            query = raw.lower().removeprefix("@")
            suggestions: list[dict[str, Any]] = []
            if not raw.startswith("@"):
                guest_suggestion = _guest_prefix_completion(raw)
                if guest_suggestion is not None:
                    suggestions.append(guest_suggestion)
                for token, (label, kind, icon) in guide_targets.items():
                    if token.startswith(query):
                        suggestions.append({
                            "value": token,
                            "label": label,
                            "state": "ロール",
                            "kind": kind,
                            "icon": icon,
                            "member": None,
                        })
            if raw.startswith("@"):
                for member in self.group.members:
                    if (
                        not query
                        or member.handle.lower().startswith(query)
                        or member.character.name.lower().startswith(query)
                    ):
                        suggestions.append({
                            "value": f"@{member.handle}",
                            "label": f"{member.character.name} / @{member.handle}",
                            "state": "参加済み" if member.id in active_ids else "未参加",
                            "kind": "member",
                            "icon": "",
                            "member": member,
                        })
            return suggestions[:8]

        with ui.dialog() as dlg, ui.card().classes("w-full max-w-2xl"):
            ui.label("次の行動").classes("text-base font-semibold")
            ui.label("行動者").classes("text-xs font-semibold text-grey-6")
            with ui.element("div").classes("cs-group-guide-actor-row"):
                with ui.button().props(
                    "flat dense unelevated aria-label=行動者を選択"
                ).classes("cs-group-guide-actor-icon"):
                    actor_icon = ui.element("div").classes("cs-group-guide-actor-icon-content")
                    with ui.menu().classes("cs-chat-mode-menu") as target_menu:
                        with ui.element("button").props("type=button").classes("cs-group-menu-parent"):
                            _render_group_role_icon("character")
                            ui.label("キャラ").classes("cs-group-menu-option-label")
                            ui.icon("chevron_right").classes("text-grey-6")
                            with ui.menu().props('anchor="top end" self="top start"').classes(
                                "cs-chat-mode-menu cs-group-character-submenu"
                            ) as active_menu:
                                with ui.element("button").props("type=button").classes(
                                    "cs-group-menu-option"
                                ).on("click", lambda _: _choose_actor("character", active_menu)):
                                    _render_group_role_icon("character")
                                    ui.label("自動").classes("cs-group-menu-option-label")
                                    ui.element("span")
                                if not active:
                                    ui.label("参加済みキャラクターはいません").classes(
                                        "text-xs text-grey-6 px-3 py-2"
                                    )
                                for member in active:
                                    with ui.element("button").props("type=button").classes(
                                        "cs-group-menu-option"
                                    ).on(
                                        "click",
                                        lambda _, member=member: _choose_actor(
                                            f"@{member.handle}",
                                            active_menu,
                                        ),
                                    ):
                                        _render_group_member_menu_face(self.ctx, member)
                                        ui.label(
                                            f"{member.character.name} / @{member.handle}"
                                        ).classes("cs-group-menu-option-label")
                                        ui.element("span")
                                with ui.element("button").props("type=button").classes(
                                    "cs-group-menu-option"
                                ).on("click", lambda _: _open_guest_actor_dialog(active_menu)):
                                    _render_group_role_icon("guest")
                                    ui.label("ゲスト").classes("cs-group-menu-option-label")
                                    ui.element("span")
                        with ui.element("button").props("type=button").classes("cs-group-menu-parent"):
                            _render_group_role_icon("character")
                            ui.label("未参加キャラ").classes("cs-group-menu-option-label")
                            ui.icon("chevron_right").classes("text-grey-6")
                            with ui.menu().props('anchor="top end" self="top start"').classes(
                                "cs-chat-mode-menu cs-group-character-submenu"
                            ) as inactive_menu:
                                if not inactive:
                                    ui.label("未参加キャラクターはいません").classes(
                                        "text-xs text-grey-6 px-3 py-2"
                                    )
                                for member in inactive:
                                    with ui.element("button").props("type=button").classes(
                                        "cs-group-menu-option"
                                    ).on(
                                        "click",
                                        lambda _, member=member: _choose_actor(
                                            f"@{member.handle}",
                                            inactive_menu,
                                        ),
                                    ):
                                        _render_group_member_menu_face(self.ctx, member)
                                        ui.label(
                                            f"{member.character.name} / @{member.handle}"
                                        ).classes("cs-group-menu-option-label")
                                        ui.element("span")
                        with ui.element("button").props("type=button").classes(
                            "cs-group-menu-option"
                        ).on("click", lambda _: _choose_actor("narrative")):
                            _render_group_role_icon("narration")
                            ui.label("地の文").classes("cs-group-menu-option-label")
                            ui.element("span")
                        with ui.element("button").props("type=button").classes(
                            "cs-group-menu-option"
                        ).on("click", lambda _: _choose_actor("user")):
                            _render_group_user_menu_face(self.ctx, self.group.user_persona)
                            ui.label("ユーザー").classes("cs-group-menu-option-label")
                            ui.element("span")
                with ui.element("div").classes("cs-group-guide-actor-wrap"):
                    actor_input = ui.input(
                        value="",
                        placeholder="@handle / character / narrative / user / guest:",
                    ).props("outlined dense clearable").classes("w-full")
                    suggestion_box = ui.element("div").classes("cs-group-guide-suggestions hidden")
            direction_input = ui.textarea(
                label="指示",
                placeholder="キャラまたは地の文にだけ反映する任意の指示",
            ).props("outlined rows=4 autogrow").classes("w-full")
            departure_container = ui.element("div").classes("w-full")

            def _choose_actor(value: str, menu_to_close=None) -> None:
                resolved = _resolve_actor_input(value)
                actor_input.set_value(_actor_display_value(resolved) if resolved is not None else value)
                suggestion_box.classes("hidden")
                if menu_to_close is not None:
                    menu_to_close.close()
                target_menu.close()
                _sync_actor_controls()

            def _open_guest_actor_dialog(menu_to_close=None) -> None:
                with ui.dialog() as guest_dialog, ui.card().classes("w-full max-w-sm"):
                    ui.label("ゲストを指定").classes("text-base font-semibold")
                    guest_name_input = ui.input(
                        label="ゲスト名",
                        placeholder="例: 酒場のマスター",
                    ).props("outlined dense clearable").classes("w-full")

                    def _apply_guest() -> None:
                        name = _clean_guest_name(str(guest_name_input.value or ""))
                        if not name:
                            ui.notify("ゲスト名を入力してください", type="warning")
                            return
                        guest_dialog.close()
                        _choose_actor(_guest_display_name(name), menu_to_close)

                    with ui.row().classes("justify-end gap-2 mt-4"):
                        ui.button("キャンセル", on_click=guest_dialog.close).props("flat")
                        ui.button("選択", icon="person_add", on_click=_apply_guest).props(
                            "color=primary unelevated"
                        )
                guest_dialog.open()
                ui.timer(0.1, lambda: guest_name_input.run_method("focus"), once=True)

            def _render_suggestions() -> None:
                suggestions = _actor_suggestions(str(actor_input.value or ""))
                suggestion_box.clear()
                if not suggestions:
                    suggestion_box.classes("hidden")
                    return
                suggestion_box.classes(remove="hidden")
                with suggestion_box:
                    for index, suggestion in enumerate(suggestions):
                        classes = "cs-group-guide-suggestion"
                        if index == 0:
                            classes += " cs-group-guide-suggestion-active"
                        with ui.element("button").props("type=button").classes(
                            classes
                        ).on(
                            "click",
                            lambda _, value=suggestion["value"]: _choose_actor(value),
                        ):
                            member = suggestion.get("member")
                            if isinstance(member, GroupMember):
                                _render_group_member_menu_face(self.ctx, member)
                            else:
                                _render_group_role_icon(str(suggestion.get("kind") or "user"))
                            ui.label(str(suggestion["label"])).classes(
                                "cs-group-guide-suggestion-label"
                            )
                            ui.label(str(suggestion["state"])).classes(
                                "cs-group-guide-suggestion-state"
                            )
                _position_group_actor_suggestions()

            def _render_actor_icon(resolved: dict[str, Any] | None) -> None:
                actor_icon.clear()
                with actor_icon:
                    if resolved is None:
                        ui.icon("help_outline").classes("text-sm")
                        return
                    member = resolved.get("member")
                    if isinstance(member, GroupMember):
                        _render_group_member_menu_face(self.ctx, member)
                        return
                    kind = str(resolved.get("kind") or "")
                    if kind == "auto":
                        _render_group_role_icon("character")
                    elif kind == "guest":
                        _render_group_role_icon("guest")
                    elif kind == "narration":
                        _render_group_role_icon("narration")
                    elif kind == "user":
                        _render_group_user_menu_face(self.ctx, self.group.user_persona)
                    else:
                        ui.icon("help_outline").classes("text-sm")

            def _sync_actor_controls() -> None:
                if actor_value_syncing["active"]:
                    return
                raw_actor_value = str(actor_input.value or "")
                resolved = _resolve_actor_input(raw_actor_value)
                if resolved is not None:
                    display_value = _actor_display_value(resolved)
                    is_typing_guest_prefix = (
                        resolved.get("kind") == "guest"
                        and re.match(r"^\s*guest\s*[:：]", raw_actor_value, flags=re.IGNORECASE) is not None
                    )
                    if not is_typing_guest_prefix and raw_actor_value.strip() != display_value:
                        actor_value_syncing["active"] = True
                        actor_input.set_value(display_value)
                        actor_value_syncing["active"] = False
                _render_actor_icon(resolved)
                departure_container.clear()
                if resolved is None:
                    departure_state["value"] = False
                    direction_input.enable()
                    _render_suggestions()
                    return
                if resolved["kind"] == "user":
                    departure_state["value"] = False
                    direction_input.set_value("")
                    direction_input.disable()
                else:
                    direction_input.enable()
                if resolved["kind"] == "member" and resolved["active"]:
                    with departure_container:
                        checkbox = ui.checkbox(
                            "退場させる",
                            value=departure_state["value"],
                        )
                        departure_checkbox["ref"] = checkbox
                        checkbox.on_value_change(
                            lambda e: departure_state.update({"value": bool(e.value)})
                        )
                else:
                    departure_state["value"] = False
                    departure_checkbox["ref"] = None
                _render_suggestions()

            actor_input.on_value_change(lambda _: _sync_actor_controls())
            actor_input.on(
                "keydown",
                js_handler="""
event => {
  const root = event.target.closest('.cs-group-guide-actor-wrap');
  const box = root ? root.querySelector('.cs-group-guide-suggestions:not(.hidden)') : null;
  const options = box ? Array.from(box.querySelectorAll('.cs-group-guide-suggestion')) : [];
  if (!options.length) return;
  const activeIndex = () => Math.max(0, options.findIndex(option => option.classList.contains('cs-group-guide-suggestion-active')));
  const setActive = index => {
    options.forEach((option, current) => {
      const active = current === index;
      option.classList.toggle('cs-group-guide-suggestion-active', active);
      option.setAttribute('aria-selected', active ? 'true' : 'false');
      if (active) option.scrollIntoView({ block: 'nearest' });
    });
  };
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault();
    const delta = event.key === 'ArrowDown' ? 1 : -1;
    setActive((activeIndex() + delta + options.length) % options.length);
    return;
  }
  if (event.key === 'Enter') {
    event.preventDefault();
    (options[activeIndex()] || options[0]).click();
    return;
  }
  if (event.key === 'Escape') {
    box.classList.add('hidden');
  }
}
""",
            )

            async def _run_directed_turn() -> None:
                direction = (direction_input.value or "").strip()
                resolved = _resolve_actor_input(str(actor_input.value or ""))
                if resolved is None:
                    ui.notify("行動者を指定してください", type="warning")
                    return
                dlg.close()
                if resolved["kind"] == "user":
                    if left_text.strip():
                        self.clear_input()
                        await self.post_hold_user_text(left_text.strip())
                    else:
                        self.clear_input()
                        self.set_input_mode("user")
                    return
                if resolved["kind"] == "narration":
                    await self.run_describe_action(left_text, instruction=direction)
                    return
                if left_text.strip():
                    await self.post_command_left_text(left_text)
                else:
                    self.clear_input()
                if resolved["kind"] == "auto":
                    await self.append_character_turn(turn_instruction=direction)
                    return
                if resolved["kind"] == "guest":
                    await self.append_guest_turn(
                        str(resolved.get("guest_name") or ""),
                        turn_instruction=direction,
                    )
                    return
                member = resolved.get("member")
                if not isinstance(member, GroupMember):
                    ui.notify("行動者を指定してください", type="warning")
                    return
                if not resolved["active"]:
                    await self.append_guided_member_turn(
                        member,
                        turn_instruction=direction,
                        membership_action="join",
                    )
                    return
                if departure_state["value"]:
                    await self.append_guided_member_turn(
                        member,
                        turn_instruction=direction,
                        membership_action="leave",
                    )
                    return
                await self.append_character_turn(
                    speaker=member,
                    turn_instruction=direction,
                )

            _sync_actor_controls()
            with ui.row().classes("justify-end gap-2 mt-4"):
                ui.button("キャンセル", on_click=dlg.close).props("flat")
                ui.button("実行", icon="play_arrow", on_click=_run_directed_turn).props(
                    "color=primary unelevated"
                )
        dlg.open()
        ui.timer(0.1, lambda: actor_input.run_method("focus"), once=True)

    def open_imitate_character_dialog(self, left_text: str = "") -> None:
        active = self.active_members()
        active_ids = {member.id for member in active}
        inactive = [member for member in self.group.members if member.id not in active_ids]
        actor_value_syncing = {"active": False}

        def _resolve_actor_input(value: str) -> dict[str, Any] | None:
            raw = (value or "").strip()
            guest_name = _guest_name_from_actor_text(raw)
            if guest_name:
                return {
                    "kind": "guest",
                    "member": None,
                    "active": False,
                    "guest_name": guest_name,
                    "label": _guest_display_name(guest_name),
                }
            identifier = raw.lower().removeprefix("@")
            for member in self.group.members:
                if member.handle.lower() == identifier or member.character.name == raw:
                    return {
                        "kind": "member",
                        "member": member,
                        "active": member.id in active_ids,
                        "label": f"{member.character.name} / @{member.handle}",
                    }
            return None

        def _actor_display_value(resolved: dict[str, Any]) -> str:
            member = resolved.get("member")
            if isinstance(member, GroupMember):
                return member.character.name
            if resolved.get("kind") == "guest":
                return _guest_display_name(str(resolved.get("guest_name") or ""))
            return str(resolved.get("label") or "")

        def _actor_suggestions(value: str) -> list[dict[str, Any]]:
            raw = (value or "").strip()
            if not raw or _resolve_actor_input(raw) is not None:
                return []
            query = raw.lower().removeprefix("@")
            suggestions: list[dict[str, Any]] = []
            if not raw.startswith("@"):
                guest_suggestion = _guest_prefix_completion(raw)
                if guest_suggestion is not None:
                    suggestions.append(guest_suggestion)
            if raw.startswith("@"):
                for member in self.group.members:
                    if (
                        not query
                        or member.handle.lower().startswith(query)
                        or member.character.name.lower().startswith(query)
                    ):
                        suggestions.append({
                            "value": f"@{member.handle}",
                            "label": f"{member.character.name} / @{member.handle}",
                            "state": "参加済み" if member.id in active_ids else "未参加",
                            "kind": "member",
                            "member": member,
                        })
            return suggestions[:8]

        with ui.dialog() as dlg, ui.card().classes("w-full max-w-2xl"):
            ui.label("キャラクター入力").classes("text-base font-semibold")
            ui.label("発言者").classes("text-xs font-semibold text-grey-6")
            with ui.element("div").classes("cs-group-guide-actor-row"):
                with ui.button().props(
                    "flat dense unelevated aria-label=発言者を選択"
                ).classes("cs-group-guide-actor-icon"):
                    actor_icon = ui.element("div").classes("cs-group-guide-actor-icon-content")
                    with ui.menu().classes("cs-chat-mode-menu") as actor_menu:
                        with ui.element("button").props("type=button").classes("cs-group-menu-parent"):
                            _render_group_role_icon("character")
                            ui.label("キャラ").classes("cs-group-menu-option-label")
                            ui.icon("chevron_right").classes("text-grey-6")
                            with ui.menu().props('anchor="top end" self="top start"').classes(
                                "cs-chat-mode-menu cs-group-character-submenu"
                            ) as character_menu:
                                if not active:
                                    ui.label("参加済みキャラクターはいません").classes(
                                        "text-xs text-grey-6 px-3 py-2"
                                    )
                                for member in active:
                                    with ui.element("button").props("type=button").classes(
                                        "cs-group-menu-option"
                                    ).on(
                                        "click",
                                        lambda _, member=member: _choose_actor(
                                            f"@{member.handle}",
                                            character_menu,
                                        ),
                                    ):
                                        _render_group_member_menu_face(self.ctx, member)
                                        ui.label(
                                            f"{member.character.name} / @{member.handle}"
                                        ).classes("cs-group-menu-option-label")
                                        ui.element("span")
                                if inactive:
                                    for member in inactive:
                                        with ui.element("button").props("type=button").classes(
                                            "cs-group-menu-option"
                                        ).on(
                                            "click",
                                            lambda _, member=member: _choose_actor(
                                                f"@{member.handle}",
                                                character_menu,
                                            ),
                                        ):
                                            _render_group_member_menu_face(self.ctx, member)
                                            ui.label(
                                                f"{member.character.name} / @{member.handle}"
                                            ).classes("cs-group-menu-option-label")
                                            ui.label("未参加").classes("text-xs text-grey-6")
                                with ui.element("button").props("type=button").classes(
                                    "cs-group-menu-option"
                                ).on("click", lambda _: _open_guest_actor_dialog(character_menu)):
                                    _render_group_role_icon("guest")
                                    ui.label("ゲスト").classes("cs-group-menu-option-label")
                                    ui.element("span")
                with ui.element("div").classes("cs-group-guide-actor-wrap"):
                    actor_input = ui.input(
                        value="",
                        placeholder="@handle / guest:酒場のマスター",
                    ).props("outlined dense clearable").classes("w-full")
                    suggestion_box = ui.element("div").classes("cs-group-guide-suggestions hidden")

            def _choose_actor(value: str, menu_to_close=None) -> None:
                resolved = _resolve_actor_input(value)
                actor_input.set_value(_actor_display_value(resolved) if resolved is not None else value)
                suggestion_box.classes("hidden")
                if menu_to_close is not None:
                    menu_to_close.close()
                actor_menu.close()
                _sync_actor_controls()

            def _open_guest_actor_dialog(menu_to_close=None) -> None:
                with ui.dialog() as guest_dialog, ui.card().classes("w-full max-w-sm"):
                    ui.label("ゲストを指定").classes("text-base font-semibold")
                    guest_name_input = ui.input(
                        label="ゲスト名",
                        placeholder="例: 酒場のマスター",
                    ).props("outlined dense clearable").classes("w-full")

                    def _apply_guest() -> None:
                        name = _clean_guest_name(str(guest_name_input.value or ""))
                        if not name:
                            ui.notify("ゲスト名を入力してください", type="warning")
                            return
                        guest_dialog.close()
                        _choose_actor(_guest_display_name(name), menu_to_close)

                    with ui.row().classes("justify-end gap-2 mt-4"):
                        ui.button("キャンセル", on_click=guest_dialog.close).props("flat")
                        ui.button("選択", icon="person_add", on_click=_apply_guest).props(
                            "color=primary unelevated"
                        )
                guest_dialog.open()
                ui.timer(0.1, lambda: guest_name_input.run_method("focus"), once=True)

            def _render_suggestions() -> None:
                suggestions = _actor_suggestions(str(actor_input.value or ""))
                suggestion_box.clear()
                if not suggestions:
                    suggestion_box.classes("hidden")
                    return
                suggestion_box.classes(remove="hidden")
                with suggestion_box:
                    for index, suggestion in enumerate(suggestions):
                        classes = "cs-group-guide-suggestion"
                        if index == 0:
                            classes += " cs-group-guide-suggestion-active"
                        with ui.element("button").props("type=button").classes(classes).on(
                            "click",
                            lambda _, value=suggestion["value"]: _choose_actor(value),
                        ):
                            member = suggestion.get("member")
                            if isinstance(member, GroupMember):
                                _render_group_member_menu_face(self.ctx, member)
                            else:
                                _render_group_role_icon("guest")
                            ui.label(str(suggestion["label"])).classes(
                                "cs-group-guide-suggestion-label"
                            )
                            ui.label(str(suggestion["state"])).classes(
                                "cs-group-guide-suggestion-state"
                            )
                _position_group_actor_suggestions()

            def _render_actor_icon(resolved: dict[str, Any] | None) -> None:
                actor_icon.clear()
                with actor_icon:
                    if resolved is None:
                        ui.icon("help_outline").classes("text-sm")
                        return
                    member = resolved.get("member")
                    if isinstance(member, GroupMember):
                        _render_group_member_menu_face(self.ctx, member)
                    elif resolved.get("kind") == "guest":
                        _render_group_role_icon("guest")
                    else:
                        ui.icon("help_outline").classes("text-sm")

            def _sync_actor_controls() -> None:
                if actor_value_syncing["active"]:
                    return
                raw_actor_value = str(actor_input.value or "")
                resolved = _resolve_actor_input(raw_actor_value)
                if resolved is not None:
                    display_value = _actor_display_value(resolved)
                    is_typing_guest_prefix = (
                        resolved.get("kind") == "guest"
                        and re.match(r"^\s*guest\s*[:：]", raw_actor_value, flags=re.IGNORECASE) is not None
                    )
                    if not is_typing_guest_prefix and raw_actor_value.strip() != display_value:
                        actor_value_syncing["active"] = True
                        actor_input.set_value(display_value)
                        actor_value_syncing["active"] = False
                _render_actor_icon(resolved)
                _render_suggestions()

            actor_input.on_value_change(lambda _: _sync_actor_controls())
            actor_input.on(
                "keydown",
                js_handler="""
event => {
  const root = event.target.closest('.cs-group-guide-actor-wrap');
  const box = root ? root.querySelector('.cs-group-guide-suggestions:not(.hidden)') : null;
  const options = box ? Array.from(box.querySelectorAll('.cs-group-guide-suggestion')) : [];
  if (!options.length) return;
  const activeIndex = () => Math.max(0, options.findIndex(option => option.classList.contains('cs-group-guide-suggestion-active')));
  const setActive = index => {
    options.forEach((option, current) => {
      const active = current === index;
      option.classList.toggle('cs-group-guide-suggestion-active', active);
      option.setAttribute('aria-selected', active ? 'true' : 'false');
      if (active) option.scrollIntoView({ block: 'nearest' });
    });
  };
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault();
    const delta = event.key === 'ArrowDown' ? 1 : -1;
    setActive((activeIndex() + delta + options.length) % options.length);
    return;
  }
  if (event.key === 'Enter') {
    event.preventDefault();
    (options[activeIndex()] || options[0]).click();
    return;
  }
  if (event.key === 'Escape') {
    box.classList.add('hidden');
  }
}
""",
            )

            async def _apply() -> None:
                resolved = _resolve_actor_input(str(actor_input.value or ""))
                if resolved is None:
                    ui.notify("発言者を指定してください", type="warning")
                    return
                if resolved["kind"] == "guest":
                    self.set_guest_input_mode(str(resolved.get("guest_name") or ""))
                else:
                    member = resolved.get("member")
                    if not isinstance(member, GroupMember):
                        ui.notify("発言者を指定してください", type="warning")
                        return
                    if self.settings is not None and member.id not in _group_participant_ids(self.settings):
                        self.settings = _settings_with_participant(self.settings, member.id)
                        self.messages.append(_group_system_event_message(f"{member.character.name}が入場しました"))
                        self.refresh_messages(scroll_to_bottom=True)
                        await self.save_current_session(refresh_history=False)
                        self.refresh_mention_palette()
                        self.refresh_chat_header()
                    self.set_character_input_member(member)
                self.set_input_value(left_text.rstrip())
                self.focus_chat_input_at_end()
                dlg.close()
                ui.notify("入力モードにしました", type="info")

            _sync_actor_controls()
            with ui.row().classes("justify-end gap-2 mt-4"):
                ui.button("キャンセル", on_click=dlg.close).props("flat")
                ui.button("選択", icon="theater_comedy", on_click=_apply).props(
                    "color=primary unelevated"
                )
        dlg.open()
        ui.timer(0.1, lambda: actor_input.run_method("focus"), once=True)

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
            self.set_input_mode("narration")
            ui.notify("ナラティブ入力モードにしました", type="info")
            return
        if command == "memo":
            self.set_input_value(left_text)
            self.set_input_mode("memo")
            ui.notify("コメント入力モードにしました", type="info")
            return
        if command == "imitate":
            self.open_imitate_character_dialog(left_text)
            return
        if command == "user":
            self.set_input_value(left_text)
            self.set_input_mode("user")
            ui.notify("ユーザー入力モードに戻しました", type="info")
            return
        if command == "describe":
            await self.run_describe_action(left_text)
            return

    async def send_message(self, allow_skip: bool = False, submitted_text: str | None = None) -> None:
        if self.sending:
            return
        if self.settings is None:
            ui.notify("先に「新しいチャット」を作成してください", type="warning")
            self.open_new_chat_dialog()
            return

        raw_text = submitted_text if submitted_text is not None else (
            self.input_box.value if self.input_box is not None else ""
        )
        parsed_command = parse_command_input(raw_text or "")
        if parsed_command is not None:
            left_text, query = parsed_command
            await self.execute_chat_command(left_text, query)
            return

        text = (raw_text or "").strip()
        if text == "/skip":
            self.clear_input()
            await self.append_character_turn()
            return
        if not text:
            if not allow_skip:
                ui.notify("メッセージを入力してください", type="warning")
                return
            await self.append_character_turn()
            return

        self.clear_input()
        if self.input_mode == "narration":
            self.messages.append(_group_message("narration", text))
            self.set_input_mode("user")
            self.refresh_messages(scroll_to_bottom=True)
            await self.save_current_session()
            return
        if self.input_mode == "memo":
            self.messages.append(_group_message("memo", text))
            self.set_input_mode("user")
            self.refresh_messages(scroll_to_bottom=True)
            await self.save_current_session()
            return
        if self.input_mode == "character":
            member = self._manual_character_speaker()
            if member is None:
                ui.notify("参加キャラがいません", type="warning")
                self.set_input_mode("user")
                return
            self.messages.append(_group_message("character", text, member=member))
            self.set_input_mode("user")
            self.refresh_messages(scroll_to_bottom=True)
            await self.save_current_session()
            return
        if self.input_mode == "guest":
            name = _clean_guest_name(self.guest_input_name)
            if not name:
                ui.notify("ゲスト名を入力してください", type="warning")
                self.open_guest_input_mode_dialog(text)
                return
            self.messages.append(_group_message("guest", text, guest_name=name))
            self.set_input_mode("user")
            self.refresh_messages(scroll_to_bottom=True)
            await self.save_current_session()
            return

        self.messages.append(_group_message("user", text, user=self.group.user_persona))
        self.set_input_mode("user")
        self.refresh_messages(scroll_to_bottom=True)
        await self.save_current_session(refresh_history=False)
        await self.append_character_turn()

    def _manual_character_speaker(self) -> GroupMember | None:
        current = self.current_participant()
        if current is not None and current.get("kind") == "character":
            member = current.get("member")
            if isinstance(member, GroupMember) and member in self.active_members():
                return member
        active = self.active_members()
        return active[0] if active else None

    async def append_character_turn(
        self,
        *,
        speaker: GroupMember | None = None,
        turn_instruction: str = "",
    ) -> None:
        if self.settings is None:
            ui.notify("先に「新しいチャット」を作成してください", type="warning")
            self.open_new_chat_dialog()
            return
        active = self.active_members()
        if not active:
            ui.notify("参加キャラがいません", type="warning")
            return

        llm = _configured_group_chat_llm(self.ctx, str(self.settings.get("profile_id", "")))
        if llm is None:
            return
        if self.active_session_id is None:
            return

        prior_messages = [dict(message) for message in self.messages]
        placeholder_index = len(self.messages)
        self.last_speaker_debug = None
        display_speaker = speaker or active[0]
        self.messages.append(_group_message("character", "…", member=display_speaker))
        self.refresh_messages(scroll_to_bottom=True)
        session_id = self.active_session_id
        title = self.title
        title_is_auto = self.active_title_is_auto
        settings_snapshot = dict(self.settings)
        await self.save_current_session(refresh_history=False)

        async def _runner(job) -> list[dict[str, Any]]:
            self.messages = [dict(message) for message in prior_messages]
            self.last_speaker_debug = None
            try:
                selected_speaker = speaker or await self.choose_next_speaker(llm, active)
                speaker_debug = self.last_speaker_debug
                generated = await self.build_character_message(
                    llm,
                    selected_speaker,
                    speaker_debug=speaker_debug,
                    prior_messages=prior_messages,
                    turn_instruction=turn_instruction,
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
            kind=AIJobKind.LLM_GROUP_CHAT,
            label=f"{self.group.name or 'グループ'}の発言生成",
            scope=self._active_group_chat_scope(),
            metadata={"session_id": session_id, "group_id": self.group.id},
            runner=_runner,
        )
        self.ctx.ai_jobs.set_result_meta(job.id, {"result_url": f"/groups/{self.group.id}"})
        generated_successfully = await self._wait_for_active_group_job(
            job.id,
            failure_message="グループチャット生成に失敗しました",
        )
        self.set_input_mode("user")
        if generated_successfully:
            await self.maybe_generate_auto_title(llm)

    async def append_guided_member_turn(
        self,
        speaker: GroupMember,
        *,
        turn_instruction: str = "",
        membership_action: str = "",
    ) -> None:
        if self.settings is None:
            ui.notify("先に「新しいチャット」を作成してください", type="warning")
            self.open_new_chat_dialog()
            return
        if self.active_session_id is None:
            return

        current_settings = dict(self.settings)
        current_ids = _group_participant_ids(current_settings)
        if membership_action == "join":
            if speaker.id in current_ids:
                await self.append_character_turn(
                    speaker=speaker,
                    turn_instruction=turn_instruction,
                )
                return
            generation_settings = _settings_with_participant(current_settings, speaker.id)
            final_settings = dict(generation_settings)
            pre_events = [_group_system_event_message(f"{speaker.character.name}が入場しました")]
            post_events: list[dict[str, Any]] = []
        elif membership_action == "leave":
            if speaker.id not in current_ids:
                ui.notify("退場させるキャラクターが現在のチャットに参加していません", type="warning")
                return
            if len(current_ids) <= 1:
                ui.notify("参加キャラクターがいなくなるため退場できません", type="warning")
                return
            generation_settings = dict(current_settings)
            final_settings = _settings_without_participant(current_settings, speaker.id)
            pre_events = []
            post_events = [_group_system_event_message(f"{speaker.character.name}が退場しました")]
        else:
            await self.append_character_turn(
                speaker=speaker,
                turn_instruction=turn_instruction,
            )
            return

        llm = _configured_group_chat_llm(self.ctx, str(current_settings.get("profile_id", "")))
        if llm is None:
            return

        original_messages = [dict(message) for message in self.messages]
        original_settings = dict(current_settings)
        prior_messages = [dict(message) for message in self.messages] + [
            dict(message) for message in pre_events
        ]
        self.messages = prior_messages + [_group_message("character", "…", member=speaker)]
        self.settings = dict(generation_settings)
        self.refresh_messages(scroll_to_bottom=True)
        self.refresh_mention_palette()

        session_id = self.active_session_id
        title = self.title
        title_is_auto = self.active_title_is_auto
        await self.save_current_session(refresh_history=False)

        async def _runner(job) -> list[dict[str, Any]]:
            base_messages = [dict(message) for message in prior_messages]
            try:
                self.messages = base_messages
                generated = await self.build_character_message(
                    llm,
                    speaker,
                    prior_messages=base_messages,
                    turn_instruction=turn_instruction,
                    settings=generation_settings,
                )
                messages = base_messages + [generated] + [
                    dict(message) for message in post_events
                ]
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
            scope=self._active_group_chat_scope(),
            metadata={"session_id": session_id, "group_id": self.group.id},
            runner=_runner,
        )
        self.ctx.ai_jobs.set_result_meta(job.id, {"result_url": f"/groups/{self.group.id}"})
        generated_successfully = await self._wait_for_active_group_job(
            job.id,
            failure_message="グループチャット生成に失敗しました",
        )
        self.set_input_mode("user")
        if generated_successfully:
            await self.maybe_generate_auto_title(llm)

    async def append_guest_turn(
        self,
        guest_name: str,
        *,
        turn_instruction: str = "",
    ) -> None:
        name = _clean_guest_name(guest_name)
        if not name:
            ui.notify("ゲスト名を入力してください", type="warning")
            return
        if self.settings is None:
            ui.notify("先に「新しいチャット」を作成してください", type="warning")
            self.open_new_chat_dialog()
            return
        llm = _configured_group_chat_llm(self.ctx, str(self.settings.get("profile_id", "")))
        if llm is None:
            return
        if self.active_session_id is None:
            return

        prior_messages = [dict(message) for message in self.messages]
        self.messages.append(_group_message("guest", "…", guest_name=name))
        self.refresh_messages(scroll_to_bottom=True)
        session_id = self.active_session_id
        title = self.title
        title_is_auto = self.active_title_is_auto
        settings_snapshot = dict(self.settings)
        await self.save_current_session(refresh_history=False)

        async def _runner(job) -> list[dict[str, Any]]:
            try:
                llm_messages = _build_group_guest_messages(
                    self.group,
                    settings_snapshot,
                    prior_messages,
                    name,
                    turn_instruction=turn_instruction,
                )
                debug_input = format_llm_input(llm_messages)
                response = await llm.ainvoke(llm_messages)
                raw = message_content_to_text(getattr(response, "content", response))
                reply = _sanitize_group_guest_reply(raw, name)
                if not reply:
                    reply = "……。"
                messages = prior_messages + [_group_message(
                    "guest",
                    reply,
                    guest_name=name,
                    debug=build_debug_info(debug_input, raw, response),
                )]
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
            kind=AIJobKind.LLM_GROUP_CHAT,
            label=f"{self.group.name or 'グループ'}のゲスト発言生成",
            scope=self._active_group_chat_scope(),
            metadata={"session_id": session_id, "group_id": self.group.id},
            runner=_runner,
        )
        self.ctx.ai_jobs.set_result_meta(job.id, {"result_url": f"/groups/{self.group.id}"})
        generated_successfully = await self._wait_for_active_group_job(
            job.id,
            failure_message="ゲスト発言生成に失敗しました",
        )
        self.set_input_mode("user")
        if generated_successfully:
            await self.maybe_generate_auto_title(llm)

    async def choose_next_speaker(self, llm, active: list[GroupMember]) -> GroupMember:
        last = _last_dialog_message(self.messages)
        if last is not None and last.get("role") == "user":
            mentioned = _mentioned_member(last.get("text", ""), active)
            if mentioned is not None:
                return mentioned
            if len(active) == 1:
                return active[0]
            return await self.choose_speaker_with_llm(llm, active)

        if last is not None and last.get("role") == "character":
            previous_id = str(last.get("speaker_id", ""))
            others = [member for member in active if member.id != previous_id]
            if not others:
                return next((member for member in active if member.id == previous_id), active[0])
            if len(others) == 1:
                return others[0]
            return await self.choose_speaker_with_llm(llm, others)

        if len(active) == 1:
            return active[0]
        return await self.choose_speaker_with_llm(llm, active)

    async def choose_speaker_with_llm(self, llm, candidates: list[GroupMember]) -> GroupMember:
        candidate_lines = "\n".join(
            f"- @{member.handle}: {member.character.name} / {member.character.occupation or '役割未設定'}"
            for member in candidates
        )
        relationship_section = _format_group_relationship_section(self.group, self.settings or {})
        llm_messages = [
            SystemMessage(
                content=(
                    "あなたはグループチャットの次の発言者候補の発言可能性を見積もる進行役です。"
                    "候補全員について、次に発言する自然さを0以上の比率で出してください。"
                    "合計は100を目安にし、固定ローテーションを避けてください。"
                    "出力はJSONのみ。形式は {\"weights\":[{\"handle\":\"...\",\"weight\":50}]} です。"
                )
            ),
            HumanMessage(
                content=(
                    f"世界観:\n{self.group.world or '未設定'}\n\n"
                    f"参加候補:\n{candidate_lines}\n\n"
                    f"{relationship_section}"
                    f"会話履歴:\n{_format_group_history(self.messages)}\n\n"
                    "候補ごとの発言可能性を比率で出力してください。"
                    "明確に特定キャラへ向けた発言なら、そのキャラを高めにしてください。"
                )
            ),
        ]
        debug_input = format_llm_input(llm_messages)
        response = await llm.ainvoke(llm_messages)
        raw = message_content_to_text(getattr(response, "content", response))
        weights = _speaker_weights_from_llm_output(raw, candidates)
        selected, normalized_weights, roll = _choose_weighted_speaker(weights, candidates)
        self.last_speaker_debug = build_debug_info(
            debug_input,
            _format_speaker_selection_debug(raw, normalized_weights, selected, roll),
            response,
        )
        return selected

    async def build_character_message(
        self,
        llm,
        speaker: GroupMember,
        *,
        speaker_debug: ChatDebugInfo | None = None,
        prior_messages: list[dict[str, Any]] | None = None,
        turn_instruction: str = "",
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        llm_messages = _build_group_character_messages(
            self.group,
            settings or self.settings or {},
            self.messages if prior_messages is None else prior_messages,
            speaker,
            turn_instruction=turn_instruction,
        )
        debug_input = format_llm_input(llm_messages)
        response = await llm.ainvoke(llm_messages)
        raw = message_content_to_text(getattr(response, "content", response))
        reply = _sanitize_group_character_reply(raw, speaker)
        if not reply:
            reply = "……ごめん、今はうまく言葉にできなかった。"
        return _group_message(
            "character",
            reply,
            member=speaker,
            debug=build_debug_info(debug_input, raw, response),
            speaker_debug=speaker_debug,
        )

    async def maybe_generate_auto_title(self, llm) -> None:
        if self.active_session_id is None or not self.active_title_is_auto:
            return
        if self.title_generation_attempted:
            return
        dialog_turns = [
            message for message in self.messages
            if message.get("role") in {"user", "character"}
        ]
        if len(dialog_turns) < 4:
            return
        self.title_generation_attempted = True
        try:
            response = await llm.ainvoke(_build_group_title_messages(self.group, self.messages))
            title = sanitize_chat_title(message_content_to_text(getattr(response, "content", response)))
        except Exception:
            return
        if not title:
            return
        self.title = title
        self.active_title_is_auto = False
        self.refresh_chat_header()
        await self.save_current_session()

    def open_new_chat_dialog(self) -> None:
        profile_options = _profile_options(self.ctx, self.ctx.api_config.get_llm_profiles())
        default_profile = (
            self.group.completion_profile_id
            if self.group.completion_profile_id in profile_options
            else _default_profile_id(self.ctx, profile_options)
        )
        member_checks: dict[str, Any] = {}

        with ui.dialog() as dlg, ui.card().classes("w-full max-w-2xl"):
            ui.label("新しいチャット").classes("text-lg font-semibold")
            if not profile_options:
                ui.label("LLMプロファイルが登録されていません。設定画面で追加してください。").classes(
                    "text-sm text-negative"
                )
            profile_select = ui.select(
                options=profile_options,
                value=default_profile,
                label="LLMプロファイル",
            ).props("outlined dense").classes("w-full")
            title_input = ui.input(
                label="タイトル（任意）",
                placeholder="未入力なら自動タイトル",
            ).props("outlined clearable").classes("w-full")

            ui.label("参加キャラクター").classes("text-sm font-semibold")
            with ui.element("div").classes("cs-group-selected-list"):
                if not self.group.members:
                    ui.label("参加できるキャラクターがいません").classes("text-sm text-grey-6")
                for member in self.group.members:
                    with ui.row().classes("items-center gap-2 w-full"):
                        _render_face(self.ctx, member.character.media, "character")
                        with ui.column().classes("gap-0 min-w-0 flex-1"):
                            ui.label(member.character.name).classes("text-sm font-semibold")
                            ui.label(f"@{member.handle}").classes("text-xs text-grey-6")
                        member_checks[member.id] = ui.checkbox(value=True)

            with ui.element("div").classes("cs-group-world-field"):
                situation_input = ui.textarea(label="シチュエーション").props(
                    "outlined rows=4"
                ).classes("w-full")

                async def _enhance_situation_click() -> None:
                    participant_ids = [
                        member_id
                        for member_id, checkbox in member_checks.items()
                        if bool(checkbox.value)
                    ]
                    enhanced = await self.enhance_situation(
                        str(profile_select.value or ""),
                        participant_ids,
                        str(situation_input.value or ""),
                    )
                    if enhanced is not None:
                        situation_input.set_value(enhanced)

                ui.button(
                    icon="auto_awesome",
                    on_click=_enhance_situation_click,
                ).props("flat round dense size=sm").classes("cs-group-world-enhance").tooltip(
                    "シチュエーションを補完"
                )

            async def _start() -> None:
                profile_id = str(profile_select.value or "")
                if not profile_id:
                    ui.notify("LLMプロファイルを選択してください", type="warning")
                    return
                participant_ids = [
                    member_id
                    for member_id, checkbox in member_checks.items()
                    if bool(checkbox.value)
                ]
                if not participant_ids:
                    ui.notify("参加キャラクターを1人以上選択してください", type="warning")
                    return
                title = str(title_input.value or "").strip()
                await self.start_chat_session(
                    {
                        "profile_id": profile_id,
                        "participant_ids": participant_ids,
                        "situation": str(situation_input.value or "").strip(),
                    },
                    title=title,
                )
                dlg.close()

            with ui.row().classes("justify-end gap-2 mt-4"):
                ui.button("キャンセル", on_click=dlg.close).props("flat")
                ui.button("開始", icon="chat", on_click=_start).props(
                    "color=primary unelevated"
                )
        dlg.open()

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
        llm = _configured_group_chat_llm(self.ctx, profile_id)
        if llm is None:
            return None
        active = [
            member for member in self.group.members
            if member.id in set(participant_ids)
        ] or self.group.members
        member_lines = "\n".join(
            f"- @{member.handle} / {member.character.name}: {_compact_character_summary(member.character)}"
            for member in active
        )
        relationship_section = _format_group_relationship_section(
            self.group,
            {"participant_ids": participant_ids},
        )

        async def _runner() -> str:
            response = await llm.ainvoke([
                SystemMessage(
                    content=(
                        "あなたはグループチャット開始時のシチュエーションを整える編集者です。"
                        "出力は補強後のシチュエーション本文だけにしてください。"
                        "箇条書き、解説、前置き、タイトルは禁止です。"
                    )
                ),
                HumanMessage(
                    content=(
                        "既存の入力内容を、矛盾を増やさず具体性だけ補ってください。"
                        "会話を始めやすい短めの場面説明にしてください。\n\n"
                        f"グループ名: {self.group.name}\n"
                        f"世界観:\n{self.group.world or '未設定'}\n\n"
                        f"参加キャラクター:\n{member_lines or 'なし'}\n\n"
                        f"{relationship_section}"
                        f"現在のシチュエーション:\n{current}"
                    )
                ),
            ])
            return message_content_to_text(getattr(response, "content", response))

        raw = await self._run_group_llm_assist_job(
            label="グループシチュエーション補完",
            runner=_runner,
            failure_message="シチュエーション補完に失敗しました",
        )
        if raw is None:
            return None
        enhanced = _clean_group_situation_enhancement(
            raw
        )
        if not enhanced:
            ui.notify("シチュエーションを補完できませんでした", type="warning")
            return None
        ui.notify("シチュエーションを補完しました", type="positive")
        return enhanced

    async def start_chat_session(self, settings: dict[str, Any], *, title: str = "") -> None:
        title = title.strip()
        self.settings = settings
        self.title = title or DEFAULT_GROUP_CHAT_TITLE
        self.active_title_is_auto = not title
        self.title_generation_attempted = False
        self.messages = []
        self.input_mode = "user"
        if self.input_box is not None:
            self.input_box.set_value("")
        situation = str(settings.get("situation", "") or "").strip()
        if situation:
            self.messages.append(_group_message("narration", situation))
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
        self.refresh_input_mode_indicator()
        self.refresh_chat_header()
        self.refresh_messages(scroll_to_bottom=True)
        self.refresh_history()

    def open_rename_current_chat_dialog(self) -> None:
        if self.active_session_id is None:
            ui.notify("先にチャットを開始してください", type="warning")
            return
        self.open_rename_chat_dialog(self.active_session_id)

    def open_rename_chat_dialog(self, session_id: str) -> None:
        session = self.sessions_by_id.get(session_id)
        if session is None:
            ui.notify("チャットが見つかりません", type="warning")
            return
        with ui.dialog() as dlg, ui.card().classes("w-full max-w-md"):
            ui.label("タイトル変更").classes("text-base font-semibold")
            title_input = ui.input(
                label="タイトル",
                value=session.title or DEFAULT_GROUP_CHAT_TITLE,
            ).props("outlined clearable").classes("w-full")

            async def _save_title() -> None:
                title = str(title_input.value or "").strip()
                if not title:
                    ui.notify("タイトルを入力してください", type="warning")
                    return
                saved = await self.ctx.group_chats.rename_session(session_id, title)
                if saved is None:
                    dlg.close()
                    ui.notify("チャットが見つかりません", type="warning")
                    await self.reload_sessions()
                    self.refresh_history()
                    return
                self.sessions_by_id[saved.id] = saved
                if saved.id == self.active_session_id:
                    self.title = saved.title
                    self.active_title_is_auto = False
                    self.refresh_chat_header()
                await self.reload_sessions()
                self.refresh_history()
                dlg.close()

            with ui.row().classes("justify-end gap-2 mt-4"):
                ui.button("キャンセル", on_click=dlg.close).props("flat")
                ui.button("保存", icon="save", on_click=_save_title).props(
                    "color=primary unelevated"
                )
        dlg.open()

    def confirm_delete_current_chat(self) -> None:
        if self.active_session_id is None:
            ui.notify("削除するチャットがありません", type="warning")
            return
        self.confirm_delete_chat_session(self.active_session_id)

    def confirm_delete_chat_session(self, session_id: str) -> None:
        if self.sending:
            ui.notify("生成中は削除できません", type="warning")
            return
        session = self.sessions_by_id.get(session_id)
        if session is None:
            ui.notify("チャットが見つかりません", type="warning")
            return
        with ui.dialog() as dlg, ui.card().classes("w-full max-w-sm"):
            ui.label("チャットを削除しますか？").classes("text-base font-semibold")
            ui.label("この操作は元に戻せません。").classes("text-sm text-grey-6")
            ui.label(session.title or DEFAULT_GROUP_CHAT_TITLE).classes("text-sm font-semibold")

            async def _delete() -> None:
                dlg.close()
                was_active = session_id == self.active_session_id
                await self.ctx.group_chats.delete_session(session_id)
                await self.reload_sessions()
                if was_active:
                    if self.sessions_by_id:
                        await self.apply_session(next(iter(self.sessions_by_id.values())))
                    else:
                        self.clear_active_session()
                    self.refresh_input_mode_indicator()
                    self.refresh_chat_header()
                    self.refresh_messages(scroll_to_bottom=True)
                self.refresh_history()

            with ui.row().classes("justify-end gap-2 mt-4"):
                ui.button("キャンセル", on_click=dlg.close).props("flat")
                ui.button("削除", icon="delete", on_click=_delete).props(
                    "color=negative unelevated"
                )
        dlg.open()

    def open_system_prompt_dialog(self) -> None:
        if self.settings is None:
            ui.notify("先にチャットを開始してください", type="warning")
            return
        active = self.active_members()
        if not active:
            ui.notify("参加キャラがいません", type="warning")
            return
        prompt = _build_group_system_prompt(self.group, self.settings, active, active[0])
        with ui.dialog() as dlg, ui.card().classes("w-full max-w-3xl"):
            ui.label("システムプロンプト").classes("text-base font-semibold")
            ui.code(prompt, language="markdown").classes("w-full text-xs")
            with ui.row().classes("justify-end mt-3"):
                ui.button("閉じる", on_click=dlg.close).props("flat")
        dlg.open()


def _group_input_mode_icon(mode: str) -> str:
    return {
        "character": "theater_comedy",
        "guest": "person_add",
        "narration": "auto_stories",
        "memo": "sticky_note_2",
        "user": "person",
    }.get(mode, "person")


def _group_input_mode_for_role(role: str) -> str:
    if role == "character":
        return "character"
    if role == "guest":
        return "guest"
    if role == "narration":
        return "narration"
    if role == "memo":
        return "memo"
    return "user"


def _group_message_target_label(role: str) -> str:
    if role == "character":
        return "キャラクターの台詞"
    if role == "guest":
        return "ゲストの台詞"
    if role == "narration":
        return "地の文"
    if role == "memo":
        return "コメント"
    return "発言"


def _group_participant_ids(settings: dict[str, Any]) -> list[str]:
    return [str(member_id) for member_id in settings.get("participant_ids", [])]


def _settings_with_participant(settings: dict[str, Any], member_id: str) -> dict[str, Any]:
    next_settings = dict(settings)
    ids = _group_participant_ids(next_settings)
    if member_id not in ids:
        ids.append(member_id)
    next_settings["participant_ids"] = ids
    return next_settings


def _settings_without_participant(settings: dict[str, Any], member_id: str) -> dict[str, Any]:
    next_settings = dict(settings)
    next_settings["participant_ids"] = [
        current_id for current_id in _group_participant_ids(next_settings)
        if current_id != member_id
    ]
    return next_settings


def _group_system_event_message(text: str) -> dict[str, Any]:
    return _group_message("system", text)


def _clean_guest_name(value: str) -> str:
    text = (value or "").strip()
    text = re.sub(r"^guest\s*[:：]\s*", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\s*【ゲスト】\s*$", "", text).strip()
    return text


def _guest_name_from_actor_text(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if re.match(r"^guest\s*[:：]", text, flags=re.IGNORECASE):
        return _clean_guest_name(text)
    if text.endswith("【ゲスト】"):
        return _clean_guest_name(text)
    return ""


def _guest_display_name(name: str) -> str:
    clean = _clean_guest_name(name)
    return f"{clean}【ゲスト】" if clean else "ゲスト【ゲスト】"


def _guest_prefix_completion(value: str) -> dict[str, Any] | None:
    query = (value or "").strip().lower()
    if not query or query.startswith("@"):
        return None
    if query == "guest:" or not "guest:".startswith(query):
        return None
    return {
        "value": "guest:",
        "label": "guest:",
        "state": "ゲスト",
        "kind": "guest",
        "icon": "person_add",
        "member": None,
    }


def _position_group_actor_suggestions() -> None:
    ui.run_javascript(
        """
requestAnimationFrame(() => {
  document.querySelectorAll('.cs-group-guide-actor-wrap').forEach(root => {
    const box = root.querySelector('.cs-group-guide-suggestions:not(.hidden)');
    const field = root.querySelector('.q-field');
    if (!box || !field) return;
    const rect = field.getBoundingClientRect();
    const margin = 8;
    const width = Math.max(220, Math.min(rect.width, window.innerWidth - margin * 2));
    const left = Math.max(margin, Math.min(rect.left, window.innerWidth - width - margin));
    const top = Math.min(rect.bottom + 4, window.innerHeight - margin);
    box.style.setProperty('--cs-guide-suggestion-left', `${left}px`);
    box.style.setProperty('--cs-guide-suggestion-top', `${top}px`);
    box.style.setProperty('--cs-guide-suggestion-width', `${width}px`);
  });
});
"""
    )


def _group_user_persona_tts_id(persona_id: str) -> str:
    return f"user-persona-{persona_id}"


def _group_message(
    role: str,
    text: str,
    *,
    member: GroupMember | None = None,
    user: GroupUserPersona | None = None,
    guest_name: str = "",
    debug: ChatDebugInfo | None = None,
    speaker_debug: ChatDebugInfo | None = None,
) -> dict[str, Any]:
    message = {
        "role": role,
        "text": text,
        "time_label": time_label(),
    }
    if member is not None:
        message.update({
            "speaker_id": member.id,
            "speaker_name": member.character.name,
            "handle": member.handle,
        })
    elif user is not None:
        message.update({
            "speaker_id": user.id,
            "speaker_name": user.display_name or user.name or "ユーザー",
            "handle": user.handle,
        })
    elif role == "guest":
        clean_guest_name = _clean_guest_name(guest_name)
        message.update({
            "speaker_id": f"guest:{clean_guest_name}",
            "speaker_name": _guest_display_name(clean_guest_name),
            "guest_name": clean_guest_name,
            "handle": "",
        })
    if debug is not None:
        message["debug"] = {
            "llm_input": debug.llm_input,
            "raw_output": debug.raw_output,
            "reasoning_output": debug.reasoning_output,
            "input_tokens": debug.input_tokens,
            "output_tokens": debug.output_tokens,
            "total_tokens": debug.total_tokens,
        }
    if speaker_debug is not None:
        message["speaker_debug"] = {
            "llm_input": speaker_debug.llm_input,
            "raw_output": speaker_debug.raw_output,
            "reasoning_output": speaker_debug.reasoning_output,
            "input_tokens": speaker_debug.input_tokens,
            "output_tokens": speaker_debug.output_tokens,
            "total_tokens": speaker_debug.total_tokens,
        }
    return message


def _debug_from_dict(value: Any) -> ChatDebugInfo | None:
    if not isinstance(value, dict):
        return None
    return ChatDebugInfo(
        llm_input=str(value.get("llm_input", "")),
        raw_output=str(value.get("raw_output", "")),
        reasoning_output=str(value.get("reasoning_output", "")),
        input_tokens=_optional_int(value.get("input_tokens")),
        output_tokens=_optional_int(value.get("output_tokens")),
        total_tokens=_optional_int(value.get("total_tokens")),
    )


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _render_group_chat_message(
    ctx,
    message: dict[str, Any],
    participants: list[dict[str, Any]],
    *,
    index: int,
    rewind_message=None,
    rewrite_message=None,
    regenerate_message=None,
    play_tts_message=None,
    tts_playable: bool = False,
    tts_generating: bool = False,
) -> None:
    role = str(message.get("role", ""))
    text = str(message.get("text", ""))
    speaker_name = str(message.get("speaker_name", ""))
    handle = str(message.get("handle", ""))

    if role == "narration":
        with ui.element("div").classes("cs-chat-message-row cs-chat-message-row-narration"):
            with ui.element("div").classes("cs-chat-bubble"):
                ui.label(text).classes("cs-chat-message-text")
                _render_group_message_meta(
                    message,
                    index=index,
                    rewind_message=rewind_message,
                    rewrite_message=rewrite_message,
                    play_tts_message=play_tts_message,
                    tts_playable=tts_playable,
                    tts_generating=tts_generating,
                )
        return
    if role == "memo":
        with ui.element("div").classes("cs-chat-message-row cs-chat-message-row-memo"):
            with ui.element("div").classes("cs-chat-bubble"):
                ui.label("コメント").classes("cs-chat-message-kind")
                ui.label(text).classes("cs-chat-message-text")
                _render_group_message_meta(
                    message,
                    index=index,
                    rewind_message=rewind_message,
                    rewrite_message=rewrite_message,
                )
        return
    if role == "system":
        with ui.element("div").classes(
            "cs-chat-message-row cs-chat-message-row-narration cs-group-system-message"
        ):
            with ui.element("div").classes("cs-chat-bubble"):
                ui.label("システム").classes("cs-chat-message-kind")
                ui.label(text).classes("cs-chat-message-text")
                _render_group_message_meta(
                    message,
                    index=index,
                    rewind_message=rewind_message,
                    rewrite_message=rewrite_message,
                )
        return

    row_class = "cs-chat-message-row-user" if role == "user" else "cs-chat-message-row-character"
    with ui.element("div").classes(f"cs-chat-message-row {row_class}"):
        participant = _participant_by_speaker_id(participants, str(message.get("speaker_id", "")))
        if role == "character" and participant is not None:
            _render_participant_face(ctx, participant)
        elif role == "guest":
            _render_group_guest_face()
        with ui.element("div").classes("cs-chat-bubble"):
            if speaker_name or handle:
                speaker_label = speaker_name
                if handle:
                    speaker_label = f"{speaker_label} / @{handle}" if speaker_label else f"@{handle}"
                ui.label(speaker_label).classes("cs-group-speaker")
            ui.label(text).classes("cs-chat-message-text")
            _render_group_message_meta(
                message,
                index=index,
                rewind_message=rewind_message,
                rewrite_message=rewrite_message,
                regenerate_message=regenerate_message,
                play_tts_message=play_tts_message,
                tts_playable=tts_playable,
                tts_generating=tts_generating,
            )
        if role == "user" and participant is not None:
            _render_participant_face(ctx, participant)
        elif role == "user":
            ui.element("div").classes("cs-group-face")


def _render_group_message_meta(
    message: dict[str, Any],
    *,
    index: int,
    rewind_message=None,
    rewrite_message=None,
    regenerate_message=None,
    play_tts_message=None,
    tts_playable: bool = False,
    tts_generating: bool = False,
) -> None:
    role = str(message.get("role", ""))
    text = str(message.get("text", ""))
    with ui.element("div").classes("cs-chat-message-meta"):
        with ui.element("div").classes("cs-chat-message-actions"):
            if tts_playable and play_tts_message is not None and text.strip():
                play_tip = {
                    "character": "この台詞を読み上げ",
                    "narration": "この地の文を読み上げ",
                }.get(role, "この発言を読み上げ")
                play_btn = ui.button(
                    icon="play_arrow",
                    on_click=lambda i=index: play_tts_message(i),
                ).props("flat round dense size=sm").classes("cs-chat-message-action").tooltip(
                    play_tip
                )
                if tts_generating:
                    play_btn.props("loading")
                    play_btn.disable()
            if role == "character" and regenerate_message is not None:
                ui.button(
                    icon="refresh",
                    on_click=lambda i=index: regenerate_message(i),
                ).props("flat round dense size=sm").classes("cs-chat-message-action").tooltip(
                    "この台詞を再生成"
                )
            debug = _debug_from_dict(message.get("debug"))
            if debug is not None:
                ui.button(
                    icon="bug_report",
                    on_click=lambda d=debug: chat_components.open_llm_debug_dialog(d),
                ).props("flat round dense size=sm").classes("cs-chat-message-action").tooltip(
                    "LLM入出力"
                )
            speaker_debug = _debug_from_dict(message.get("speaker_debug"))
            if speaker_debug is not None:
                ui.button(
                    icon="manage_search",
                    on_click=lambda d=speaker_debug: chat_components.open_llm_debug_dialog(d),
                ).props("flat round dense size=sm").classes("cs-chat-message-action").tooltip(
                    "発言者決定ログ"
                )
            if role in {"character", "guest", "user", "narration", "memo"} and rewrite_message is not None:
                ui.button(
                    icon="edit",
                    on_click=lambda i=index: rewrite_message(i),
                ).props("flat round dense size=sm").classes("cs-chat-message-action").tooltip(
                    "この内容を書き換え"
                )
            if role in {"character", "guest", "user", "narration", "memo"} and rewind_message is not None:
                rewind_tip = {
                    "character": "この台詞まで戻る",
                    "guest": "この台詞まで戻る",
                    "narration": "この地の文まで戻る",
                    "memo": "このコメントまで戻る",
                }.get(role, "この発言まで戻る")
                ui.button(
                    icon="undo",
                    on_click=lambda i=index: rewind_message(i),
                ).props("flat round dense size=sm").classes("cs-chat-message-action").tooltip(
                    rewind_tip
                )
        ui.label(str(message.get("time_label", ""))).classes("cs-chat-message-time")


def _participant_by_speaker_id(
    participants: list[dict[str, Any]],
    speaker_id: str,
) -> dict[str, Any] | None:
    for participant in participants:
        if participant.get("kind") == "character":
            member = participant.get("member")
            if isinstance(member, GroupMember) and member.id == speaker_id:
                return participant
        if participant.get("kind") == "user":
            persona = participant.get("persona")
            if isinstance(persona, GroupUserPersona) and persona.id == speaker_id:
                return participant
    return None


def _latest_group_message_preview(messages: list[dict[str, Any]], *, limit: int = 56) -> str:
    if not messages:
        return "まだ発言がありません"
    latest = messages[-1]
    text = str(latest.get("text", "")) if isinstance(latest, dict) else ""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return "まだ発言がありません"
    name = str(latest.get("speaker_name", "") or "")
    prefix = f"{name}: " if name else ""
    preview = f"{prefix}{text}"
    return preview if len(preview) <= limit else f"{preview[:limit - 1]}…"


def _last_dialog_message(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for message in reversed(messages):
        if message.get("role") in {"user", "character", "guest"}:
            return message
    return None


def _mentioned_member(text: str, members: list[GroupMember]) -> GroupMember | None:
    handles = re.findall(r"@([A-Za-z0-9_]{3,12})", text or "")
    if not handles:
        return None
    by_handle = {member.handle.lower(): member for member in members}
    for handle in handles:
        member = by_handle.get(handle.lower())
        if member is not None:
            return member
    return None


def _member_from_llm_choice(raw: str, members: list[GroupMember]) -> GroupMember | None:
    text = (raw or "").strip()
    if not text:
        return None
    lowered = text.lower()
    for member in members:
        if re.search(rf"@?{re.escape(member.handle.lower())}\b", lowered):
            return member
    for member in members:
        if member.character.name and member.character.name in text:
            return member
    return None


def _speaker_weights_from_llm_output(raw: str, members: list[GroupMember]) -> dict[str, float]:
    weights: dict[str, float] = {}
    parsed = _try_parse_json_fragment(raw)
    if parsed is not None:
        for identifier, weight in _collect_speaker_weight_entries(parsed):
            member = _member_from_identifier(identifier, members)
            if member is not None and weight > 0:
                weights[member.id] = max(weights.get(member.id, 0.0), weight)
    if weights:
        return weights

    for line in (raw or "").splitlines():
        member = _member_from_llm_choice(line, members)
        if member is None:
            continue
        scrubbed = line
        for candidate in members:
            scrubbed = re.sub(rf"@?{re.escape(candidate.handle)}\b", "", scrubbed, flags=re.IGNORECASE)
            if candidate.character.name:
                scrubbed = scrubbed.replace(candidate.character.name, "")
        numbers = re.findall(r"(?<![A-Za-z0-9_])(\d+(?:\.\d+)?)\s*%?", scrubbed)
        if numbers:
            weights[member.id] = max(weights.get(member.id, 0.0), float(numbers[-1]))
    if weights:
        return weights

    selected = _member_from_llm_choice(raw, members)
    if selected is not None:
        return {member.id: 2.0 if member.id == selected.id else 1.0 for member in members}
    return {}


def _try_parse_json_fragment(raw: str):
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()
    parsed = _try_parse_json(text)
    if parsed is not None:
        return parsed
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        return value
    return None


def _collect_speaker_weight_entries(value) -> list[tuple[str, float]]:
    entries: list[tuple[str, float]] = []
    if isinstance(value, dict):
        identifier = _speaker_identifier_from_dict(value)
        weight = _speaker_weight_from_dict(value)
        if identifier and weight is not None:
            entries.append((identifier, weight))
        for key, item in value.items():
            direct = _number_from_weight_value(item)
            if direct is not None:
                entries.append((str(key), direct))
            elif isinstance(item, (dict, list)):
                entries.extend(_collect_speaker_weight_entries(item))
        return entries
    if isinstance(value, list):
        if len(value) >= 2 and not isinstance(value[0], (dict, list)):
            weight = _number_from_weight_value(value[1])
            if weight is not None:
                entries.append((str(value[0]), weight))
            return entries
        for item in value:
            if isinstance(item, (dict, list)):
                entries.extend(_collect_speaker_weight_entries(item))
            elif isinstance(item, tuple) and len(item) >= 2:
                weight = _number_from_weight_value(item[1])
                if weight is not None:
                    entries.append((str(item[0]), weight))
        return entries
    return entries


def _speaker_identifier_from_dict(value: dict) -> str:
    for key in ("handle", "id", "member_id", "speaker_id", "name", "character", "candidate"):
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            return item.strip()
    return ""


def _speaker_weight_from_dict(value: dict) -> float | None:
    for key in ("weight", "ratio", "probability", "possibility", "score", "percent", "chance"):
        number = _number_from_weight_value(value.get(key))
        if number is not None:
            return number
    return None


def _number_from_weight_value(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        number = float(value)
    elif isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value)
        if not match:
            return None
        number = float(match.group(0))
    else:
        return None
    if number <= 0 or number == float("inf") or number == float("-inf") or number != number:
        return None
    return number


def _member_from_identifier(identifier: str, members: list[GroupMember]) -> GroupMember | None:
    text = (identifier or "").strip()
    if not text:
        return None
    normalized = text.lstrip("@").lower()
    for member in members:
        if normalized in {
            member.id.lower(),
            member.handle.lower(),
            member.character.name.lower(),
        }:
            return member
    return _member_from_llm_choice(text, members)


def _choose_weighted_speaker(
    weights: dict[str, float],
    candidates: list[GroupMember],
) -> tuple[GroupMember, list[tuple[GroupMember, float, float]], float]:
    if not candidates:
        raise ValueError("発言候補がありません")
    weighted = [
        (member, max(0.0, float(weights.get(member.id, 0.0))))
        for member in candidates
    ]
    total = sum(weight for _, weight in weighted)
    if total <= 0:
        weighted = [(member, 1.0) for member in candidates]
        total = float(len(candidates))

    roll = random.random()
    threshold = roll * total
    current = 0.0
    selected = weighted[-1][0]
    for member, weight in weighted:
        current += weight
        if threshold <= current:
            selected = member
            break
    normalized = [
        (member, weight, (weight / total) * 100 if total > 0 else 0.0)
        for member, weight in weighted
    ]
    return selected, normalized, roll


def _format_speaker_selection_debug(
    raw: str,
    weights: list[tuple[GroupMember, float, float]],
    selected: GroupMember,
    roll: float,
) -> str:
    lines = [(raw or "").strip() or "（空の応答）", "", "--- 内部抽選 ---"]
    lines.append(f"乱数: {roll:.4f}")
    lines.append("発言可能性:")
    for member, weight, percent in weights:
        lines.append(f"- @{member.handle} / {member.character.name}: {weight:g} ({percent:.1f}%)")
    lines.append(f"選択: @{selected.handle} / {selected.character.name}")
    return "\n".join(lines)


def _configured_group_chat_llm(ctx, profile_id: str):
    profile = ctx.api_config.get_llm_profile(profile_id)
    if profile is None:
        ui.notify("LLMプロファイルを選択してください", type="warning")
        return None
    if not profile.model_id:
        ui.notify("LLMプロファイルのモデルIDが未設定です", type="negative")
        return None
    endpoint = ctx.api_config.get_endpoint(profile.endpoint_id)
    if endpoint is None:
        ui.notify("LLMプロファイルのエンドポイントが見つかりません", type="negative")
        return None
    api_key = ctx.api_config.get_api_key(profile.endpoint_id, get_vault_password())
    if ctx.api_config.is_api_key_locked(profile.endpoint_id, api_key):
        ui.notify("APIキーがロックされています。設定画面で解除してください。", type="warning")
        return None
    return create_llm(profile, endpoint, api_key)


def _format_group_history(messages: list[dict[str, Any]], *, limit: int | None = None) -> str:
    visible = [
        message for message in messages
        if message.get("role") in {"user", "character", "guest", "narration", "system"}
    ]
    if not visible:
        return "（まだ会話はありません）"
    lines: list[str] = []
    target_messages = visible if limit is None else visible[-limit:]
    for message in target_messages:
        role = message.get("role")
        if role == "narration":
            label = "地の文"
        elif role == "system":
            label = "システム"
        else:
            label = str(message.get("speaker_name") or "")
            handle = str(message.get("handle") or "")
            if handle:
                label = f"{label}(@{handle})" if label else f"@{handle}"
            if not label:
                if role == "user":
                    label = "ユーザー"
                elif role == "guest":
                    label = "ゲスト"
                else:
                    label = "キャラクター"
        lines.append(f"{label}: {message.get('text', '')}")
    return "\n".join(lines)


def _build_group_system_prompt(
    group: GroupChatRecord,
    settings: dict[str, Any],
    active_members: list[GroupMember],
    speaker: GroupMember,
) -> str:
    user = group.user_persona
    active_overview = "\n".join(
        f"- @{member.handle} / {member.character.name}: {_compact_character_summary(member.character)}"
        for member in active_members
    )
    return (
        "あなたはグループチャットの参加キャラクターを演じます。\n"
        "指定された次の発言者だけとして発言してください。話者名、ハンドル、引用符、前置き、解説は出力しないでください。\n"
        "特別な理由がない限り、キャラクター発言にメンションは含めないでください。\n\n"
        "発言は通常の1対1チャットと同じくらい短くしてください。1〜3文程度で短く返し、相手が返しやすい余白を残してください。\n\n"
        f"グループ名: {group.name}\n"
        f"世界観:\n{group.world or '未設定'}\n\n"
        f"ユーザー:\n@{user.handle if user else 'User'} / "
        f"{(user.display_name or user.name) if user else 'ユーザー'}\n"
        f"{_group_user_persona_context(user)}\n\n"
        f"参加キャラクター:\n{active_overview or 'なし'}\n\n"
        f"{_format_group_relationship_section(group, settings)}"
        f"今回の発言者:\n@{speaker.handle} / {speaker.character.name}\n"
        f"{character_summary(speaker.character)}\n\n"
        f"シチュエーション:\n{settings.get('situation', '') or '未設定'}"
    )


def _build_group_character_messages(
    group: GroupChatRecord,
    settings: dict[str, Any],
    messages: list[dict[str, Any]],
    speaker: GroupMember,
    *,
    turn_instruction: str = "",
) -> list:
    participant_ids = {str(member_id) for member_id in settings.get("participant_ids", [])}
    active = [member for member in group.members if member.id in participant_ids] or group.members
    instruction = turn_instruction.strip()
    instruction_text = (
        "\n\n次の返答だけに適用するメタ指示です。"
        "この指示を作中で説明せず、返答本文にだけ反映してください。\n"
        f"{instruction}"
        if instruction
        else ""
    )
    return [
        SystemMessage(content=_build_group_system_prompt(group, settings, active, speaker)),
        HumanMessage(
            content=(
                f"会話履歴:\n{_format_group_history(messages)}\n\n"
                f"次の発言者は @{speaker.handle} / {speaker.character.name} です。"
                "このキャラクターの自然な次の発言を、本文だけで返してください。"
                "通常チャットと同じくらい短く、1〜3文程度で相手が返しやすい余白を残してください。"
                f"{instruction_text}"
            )
        ),
    ]


def _build_group_guest_messages(
    group: GroupChatRecord,
    settings: dict[str, Any],
    messages: list[dict[str, Any]],
    guest_name: str,
    *,
    turn_instruction: str = "",
) -> list:
    name = _clean_guest_name(guest_name)
    instruction = turn_instruction.strip()
    instruction_text = (
        "\n\n次の返答だけに適用するメタ指示です。"
        "この指示を作中で説明せず、返答本文にだけ反映してください。\n"
        f"{instruction}"
        if instruction
        else ""
    )
    return [
        SystemMessage(
            content=(
                "あなたはグループチャットの一時的なゲスト発言者を演じます。"
                "指定されたゲスト本人の自然な発言本文だけを出力してください。"
                "話者名、ハンドル、引用符、前置き、解説は出力しないでください。"
                "発言は短く、1〜3文程度で場面に自然につながる内容にしてください。"
            )
        ),
        HumanMessage(
            content=(
                f"グループ名: {group.name}\n"
                f"世界観:\n{group.world or '未設定'}\n\n"
                f"シチュエーション:\n{settings.get('situation', '') or '未設定'}\n\n"
                f"参加者:\n{_format_group_participant_overview(group, settings)}\n\n"
                f"{_format_group_relationship_section(group, settings)}"
                f"会話履歴:\n{_format_group_history(messages)}\n\n"
                f"今回のゲスト発言者: {_guest_display_name(name)}\n"
                "このゲストの自然な次の発言を、本文だけで返してください。"
                f"{instruction_text}"
            )
        ),
    ]


def _build_group_narration_messages(
    group: GroupChatRecord,
    settings: dict[str, Any],
    messages: list[dict[str, Any]],
    *,
    instruction: str = "",
) -> list:
    instruction_line = instruction.strip() or "現在の会話を受けて、次に自然につながる地の文を書く。"
    return [
        SystemMessage(
            content=(
                "あなたはグループチャットの地の文を書くナレーターです。"
                "セリフ、話者名、箇条書き、解説、メタ発言は出力しないでください。"
                "1〜3文で、場面・空気・動きだけを簡潔に描写してください。"
            )
        ),
        HumanMessage(
            content=(
                f"グループ名: {group.name}\n"
                f"世界観:\n{group.world or '未設定'}\n\n"
                f"シチュエーション:\n{settings.get('situation', '') or '未設定'}\n\n"
                f"参加者:\n{_format_group_participant_overview(group, settings)}\n\n"
                f"{_format_group_relationship_section(group, settings)}"
                f"会話履歴:\n{_format_group_history(messages)}\n\n"
                f"指示: {instruction_line}\n"
                "出力は地の文だけ。"
            )
        ),
    ]


def _build_group_input_completion_messages(
    group: GroupChatRecord,
    settings: dict[str, Any],
    messages: list[dict[str, Any]],
    left_text: str,
    *,
    input_mode: str,
    speaker: GroupMember | None = None,
    guest_name: str = "",
) -> list:
    target_label, system_instruction, character_context = _group_input_target_context(
        group,
        input_mode,
        speaker,
        guest_name=guest_name,
    )
    return [
        SystemMessage(content=system_instruction),
        HumanMessage(
            content=(
                f"現在話そうとしているもの: {target_label}\n"
                f"グループ名: {group.name}\n"
                f"世界観:\n{group.world or '未設定'}\n"
                f"シチュエーション:\n{settings.get('situation', '') or '未設定'}\n\n"
                f"参加者:\n{_format_group_participant_overview(group, settings)}\n\n"
                f"{_format_group_relationship_section(group, settings)}"
                f"{character_context}"
                f"会話履歴:\n{_format_group_history(messages)}\n\n"
                f"未完の文:\n{left_text.rstrip()}\n\n"
                "未完の文の続きを出力してください。前置き、引用符、元の文の繰り返しは禁止です。"
            )
        ),
    ]


def _build_group_tailored_input_messages(
    group: GroupChatRecord,
    settings: dict[str, Any],
    messages: list[dict[str, Any]],
    text: str,
    *,
    input_mode: str,
    speaker: GroupMember | None = None,
    guest_name: str = "",
) -> list:
    target_label, system_instruction, character_context = _group_input_target_context(
        group,
        input_mode,
        speaker,
        guest_name=guest_name,
        tailor=True,
    )
    return [
        SystemMessage(content=system_instruction),
        HumanMessage(
            content=(
                f"現在の入力ロール: {target_label}\n"
                f"グループ名: {group.name}\n"
                f"世界観:\n{group.world or '未設定'}\n"
                f"シチュエーション:\n{settings.get('situation', '') or '未設定'}\n\n"
                f"参加者:\n{_format_group_participant_overview(group, settings)}\n\n"
                f"{_format_group_relationship_section(group, settings)}"
                f"{character_context}"
                f"会話履歴:\n{_format_group_history(messages)}\n\n"
                f"書き換える文:\n{text.strip()}\n\n"
                "現在の入力ロールに合う自然な本文へ書き換えてください。"
                "出力は書き換え後の本文だけ。前置き、引用符、話者名、解説は禁止です。"
            )
        ),
    ]


def _build_group_response_choice_messages(
    group: GroupChatRecord,
    settings: dict[str, Any],
    messages: list[dict[str, Any]],
    left_text: str,
    *,
    input_mode: str,
    speaker: GroupMember | None = None,
    guest_name: str = "",
) -> list:
    target_label, system_instruction, character_context = _group_input_target_context(
        group,
        input_mode,
        speaker,
        guest_name=guest_name,
        choices=True,
    )
    prefix = left_text.strip()
    prefix_line = f"各候補は次の書き出しに自然につなげる: {prefix}" if prefix else "各候補は独立した短い返答にする。"
    return [
        SystemMessage(content=system_instruction),
        HumanMessage(
            content=(
                f"現在話そうとしているもの: {target_label}\n"
                f"グループ名: {group.name}\n"
                f"世界観:\n{group.world or '未設定'}\n"
                f"シチュエーション:\n{settings.get('situation', '') or '未設定'}\n\n"
                f"参加者:\n{_format_group_participant_overview(group, settings)}\n\n"
                f"{_format_group_relationship_section(group, settings)}"
                f"{character_context}"
                f"会話履歴:\n{_format_group_history(messages)}\n\n"
                f"{prefix_line}\n"
                "出力は3行だけ。番号や箇条書き記号は付けず、候補本文だけを書いてください。"
            )
        ),
    ]


def _group_input_target_context(
    group: GroupChatRecord,
    input_mode: str,
    speaker: GroupMember | None,
    *,
    guest_name: str = "",
    tailor: bool = False,
    choices: bool = False,
) -> tuple[str, str, str]:
    action = "候補を作る" if choices else "書き換える" if tailor else "続きを補完する"
    if input_mode == "narration":
        return (
            "地の文",
            f"あなたはグループチャットの地の文を{action}編集者です。セリフではなく、状況描写として自然な本文だけを短く出力してください。",
            "",
        )
    if input_mode == "memo":
        return (
            "コメント",
            f"あなたはグループチャットログ上に残すコメントを{action}編集者です。会話本文ではなく、作者向けの短いメモとして自然な本文だけを出力してください。",
            "",
        )
    if input_mode == "guest":
        clean_guest_name = _clean_guest_name(guest_name)
        guest_label = _guest_display_name(clean_guest_name) if clean_guest_name else "ゲスト"
        return (
            f"ゲスト（{guest_label}）",
            f"あなたはゲスト発言を{action}編集者です。指定されたゲスト本人の自然なセリフだけを短く出力してください。",
            f"ゲスト発言者:\n{guest_label}\n\n",
        )
    if input_mode == "character":
        member = speaker or (group.members[0] if group.members else None)
        if member is None:
            return (
                "キャラクター",
                f"あなたはキャラクター発言を{action}編集者です。キャラクター本人の自然なセリフだけを短く出力してください。",
                "",
            )
        return (
            f"キャラクター（{member.character.name} / @{member.handle}）",
            f"あなたはキャラクター発言を{action}編集者です。指定キャラクター本人の自然なセリフだけを短く出力してください。",
            f"対象キャラクター:\n@{member.handle} / {member.character.name}\n{character_summary(member.character)}\n\n",
        )
    user = group.user_persona
    return (
        f"ユーザー（{(user.display_name or user.name) if user else 'ユーザー'}）",
        f"あなたはユーザー発言を{action}編集者です。ユーザー本人の口調として自然につながる本文だけを短く出力してください。",
        f"ユーザー設定:\n@{user.handle if user else 'User'} / {(user.display_name or user.name) if user else 'ユーザー'}\n{_group_user_persona_context(user)}\n\n",
    )


def _format_group_participant_overview(group: GroupChatRecord, settings: dict[str, Any]) -> str:
    participant_ids = {str(member_id) for member_id in settings.get("participant_ids", [])}
    active = [member for member in group.members if member.id in participant_ids] or group.members
    lines = [
        f"- @{member.handle} / {member.character.name}: {_compact_character_summary(member.character)}"
        for member in active
    ]
    if group.user_persona is not None:
        user = group.user_persona
        lines.append(f"- @{user.handle} / {user.display_name or user.name or 'ユーザー'}: {_group_user_persona_context(user)}")
    return "\n".join(lines) if lines else "なし"


def _group_user_persona_context(user: GroupUserPersona | None) -> str:
    if user is None:
        return ""
    lines = [(user.description or "ユーザー").strip()]
    if user.world_entry_type == "visitor" and user.arrival_reason.strip():
        lines.append(f"この世界に来た理由: {user.arrival_reason.strip()}")
    return "\n".join(line for line in lines if line)


def _format_group_relationship_section(group: GroupChatRecord, settings: dict[str, Any]) -> str:
    relationships = _active_group_relationship_lines(group, settings)
    if not relationships:
        return ""
    return "関係性:\n" + "\n".join(relationships) + "\n\n"


def _active_group_relationship_lines(group: GroupChatRecord, settings: dict[str, Any]) -> list[str]:
    active_keys = _active_group_participant_keys(group, settings)
    labels = _group_participant_labels(group)
    lines: list[str] = []
    for relationship in group.relationships:
        if relationship.participant_a_key not in active_keys:
            continue
        if relationship.participant_b_key not in active_keys:
            continue
        description = relationship.description.strip()
        if not description:
            continue
        left = labels.get(relationship.participant_a_key)
        right = labels.get(relationship.participant_b_key)
        if not left or not right:
            continue
        lines.append(f"- {left} ↔ {right}: {description}")
    return lines


def _active_group_participant_keys(group: GroupChatRecord, settings: dict[str, Any]) -> set[str]:
    participant_ids = {str(member_id) for member_id in settings.get("participant_ids", [])}
    active_members = [member for member in group.members if member.id in participant_ids] or group.members
    keys = {f"member:{member.id}" for member in active_members}
    if group.user_persona is not None:
        keys.add(f"user:{group.user_persona.id}")
    return keys


def _build_group_title_messages(group: GroupChatRecord, messages: list[dict[str, Any]]) -> list:
    return [
        SystemMessage(
            content=(
                "あなたはグループチャット履歴に短いタイトルを付ける編集者です。"
                "出力はタイトル本文だけにしてください。引用符、句点、解説、前置きは禁止です。"
                "12〜24文字程度で、会話の中心が分かる自然な日本語にしてください。"
            )
        ),
        HumanMessage(
            content=(
                f"グループ名: {group.name}\n"
                f"世界観:\n{group.world or '未設定'}\n\n"
                f"{_format_group_relationship_section(group, {})}"
                f"会話履歴:\n{_format_group_history(messages)}"
            )
        ),
    ]


def _sanitize_group_character_reply(raw: str, speaker: GroupMember) -> str:
    text = sanitize_character_reply(raw, speaker.character.name)
    text = re.sub(rf"^\s*@?{re.escape(speaker.handle)}\s*[：:\-]\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(rf"^\s*{re.escape(speaker.character.name)}\s*[：:\-]\s*", "", text)
    text = text.strip(" \t\r\n\"'「」『』")
    return text


def _sanitize_group_guest_reply(raw: str, guest_name: str) -> str:
    name = _clean_guest_name(guest_name)
    text = sanitize_character_reply(raw, name)
    text = re.sub(rf"^\s*{re.escape(_guest_display_name(name))}\s*[：:\-]\s*", "", text)
    text = re.sub(rf"^\s*{re.escape(name)}\s*[：:\-]\s*", "", text)
    text = text.strip(" \t\r\n\"'「」『』")
    return text


def _sanitize_group_narration(raw: str) -> str:
    text = clean_short_llm_text(raw)
    text = re.sub(r"^(?:地の文|ナラティブ|描写)\s*[:：]\s*", "", text.strip())
    return text.strip(" \t\r\n\"'「」『』")


def _render_group_profile_panel(
    ctx,
    group: GroupChatRecord,
    participants: list[dict[str, Any]],
    current: dict[str, Any] | None,
    *,
    selected_key: str,
    active_tab: str,
    select_profile: Callable[[str], None],
    select_tab: Callable[[str], None],
    on_group_updated: Callable[[GroupChatRecord], None] | None = None,
    compact: bool = False,
) -> None:
    if current is None:
        with ui.element("div").classes("cs-group-profile-shell"):
            ui.label("メンバーがいません").classes("cs-group-profile-summary")
        return

    classes = "cs-group-profile-shell"
    if compact:
        classes += " cs-group-profile-compact"

    with ui.element("div").classes(classes):
        with ui.element("div").classes("cs-group-profile-switch"):
            profile_classes = "cs-group-profile-switch-item"
            if active_tab == "profile":
                profile_classes += " cs-group-profile-switch-item-active"
            profile_tab = ui.element("button").props("type=button").classes(profile_classes)
            profile_tab.on("click", lambda _: select_tab("profile"))
            with profile_tab:
                ui.icon("groups").classes("text-sm")
                ui.label("プロフィール")
            world_classes = "cs-group-profile-switch-item"
            if active_tab == "world":
                world_classes += " cs-group-profile-switch-item-active"
            world_tab = ui.element("button").props("type=button").classes(world_classes)
            world_tab.on("click", lambda _: select_tab("world"))
            with world_tab:
                ui.icon("menu_book").classes("text-sm")
                ui.label("ワールド")

        if active_tab == "world":
            _render_group_world_panel(ctx, group, on_group_updated)
            return

        style = _participant_media_style(ctx, current, rect_kind="bust")
        with ui.element("div").classes("cs-group-portrait").style(style):
            if not style:
                with ui.element("div").classes("cs-group-portrait-placeholder"):
                    ui.icon("person").classes("text-4xl")

        with ui.element("div").classes("cs-group-face-strip"):
            for participant in participants:
                button_classes = "cs-group-avatar-button"
                if participant["key"] == selected_key:
                    button_classes += " cs-group-avatar-selected"
                button = ui.element("button").props("type=button").classes(button_classes)
                button.on("click", lambda _, key=participant["key"]: select_profile(key))
                with button:
                    _render_participant_face(ctx, participant, large=True)

        ui.label(current["name"]).classes("cs-group-profile-name")
        with ui.element("div").classes("cs-group-handle"):
            ui.icon("alternate_email").classes("text-sm")
            ui.label(current["handle"])
        with ui.element("div").classes("cs-group-profile-actions"):
            current_member = current.get("member")
            if isinstance(current_member, GroupMember):
                ui.button(
                    "キャラクターシートを開く",
                    icon="description",
                    on_click=lambda member_id=current_member.id: ui.navigate.to(
                        f"/groups/{group.id}/members/{member_id}"
                    ),
                ).props("outline dense").classes("cs-group-profile-action")
            elif current.get("kind") == "user" and group.user_persona is not None:
                ui.button(
                    "ユーザーペルソナを開く",
                    icon="badge",
                    on_click=lambda: ui.navigate.to(f"/groups/{group.id}/persona"),
                ).props("outline dense").classes("cs-group-profile-action")
            ui.button(
                "キャラクターを追加",
                icon="person_add",
                on_click=lambda: open_add_group_character_dialog(ctx, group),
            ).props("outline dense").classes("cs-group-profile-action")

        with ui.element("div").classes("cs-group-profile-card"):
            is_user_profile = current.get("kind") == "user"
            ui.label("ユーザーペルソナ概要" if is_user_profile else "キャラクター概要").classes(
                "cs-group-profile-card-title"
            )
            with ui.element("div").classes("cs-group-profile-grid"):
                for label, value in _participant_profile_rows(current):
                    ui.label(label).classes("cs-group-profile-label")
                    ui.label(value or "未設定").classes("cs-group-profile-value")
            ui.label("説明" if is_user_profile else "人物像").classes("cs-group-profile-card-title")
            ui.label(_participant_profile_text(current)).classes("cs-group-profile-summary")


def _render_group_world_panel(
    ctx,
    group: GroupChatRecord,
    on_group_updated: Callable[[GroupChatRecord], None] | None = None,
) -> None:
    with ui.element("div").classes("cs-group-profile-card"):
        ui.label("ワールド").classes("cs-group-profile-card-title")
        ui.label(group.world or "未設定").classes("cs-group-profile-summary")

    with ui.element("div").classes("cs-group-profile-card"):
        with ui.row().classes("items-center justify-between gap-2"):
            ui.label("関係性").classes("cs-group-profile-card-title")
            ui.button(
                "追加",
                icon="add",
                on_click=lambda: _open_group_relationship_dialog(
                    ctx,
                    group,
                    None,
                    on_group_updated,
                ),
            ).props("outline dense").classes("cs-group-profile-action")

        participants = _group_participants(group)
        if len(participants) < 2:
            ui.label("関係性を設定できる参加者が足りません").classes("cs-group-profile-summary")
            return

        labels = _group_participant_labels(group)
        with ui.element("div").classes("cs-group-relationship-list"):
            if not group.relationships:
                ui.label("設定済みの関係性はありません").classes("cs-group-profile-summary")
            for relationship in group.relationships:
                _render_group_relationship_row(
                    ctx,
                    group,
                    relationship,
                    labels,
                    on_group_updated,
                )


def _render_group_relationship_row(
    ctx,
    group: GroupChatRecord,
    relationship: GroupRelationship,
    labels: dict[str, str],
    on_group_updated: Callable[[GroupChatRecord], None] | None,
) -> None:
    left = labels.get(relationship.participant_a_key, "不明な参加者")
    right = labels.get(relationship.participant_b_key, "不明な参加者")
    with ui.element("div").classes("cs-group-relationship-row"):
        with ui.element("div").classes("cs-group-relationship-head"):
            ui.label(f"{left} ↔ {right}").classes("cs-group-relationship-pair")
            with ui.row().classes("items-center gap-1 shrink-0"):
                ui.button(
                    icon="edit",
                    on_click=lambda: _open_group_relationship_dialog(
                        ctx,
                        group,
                        relationship,
                        on_group_updated,
                    ),
                ).props("flat round dense size=sm").tooltip("編集")
                ui.button(
                    icon="delete",
                    on_click=lambda: _delete_group_relationship(
                        ctx,
                        group,
                        relationship.id,
                        on_group_updated,
                    ),
                ).props("flat round dense size=sm color=negative").tooltip("削除")
        ui.label(relationship.description or "未設定").classes("cs-group-relationship-text")


def _group_participant_labels(group: GroupChatRecord) -> dict[str, str]:
    labels: dict[str, str] = {}
    for participant in _group_participants(group):
        name = str(participant.get("name") or "参加者")
        handle = str(participant.get("handle") or "")
        label = f"{name} (@{handle})" if handle else name
        labels[str(participant["key"])] = label
    return labels


def _group_relationship_options(group: GroupChatRecord) -> dict[str, str]:
    return _group_participant_labels(group)


def _group_relationship_enhancement_participants(group: GroupChatRecord) -> list[dict[str, str]]:
    participants = [
        {
            "key": f"member:{member.id}",
            "id": member.id,
            "name": member.character.name,
            "summary": _compact_character_summary(member.character),
            "kind": "character",
            "world_entry_type": member.world_entry_type,
            "arrival_reason": member.arrival_reason,
            "adaptation_note": member.world_adaptation_note,
        }
        for member in group.members
    ]
    if group.user_persona is not None:
        user = group.user_persona
        participants.append({
            "key": f"user:{user.id}",
            "id": user.id,
            "name": user.display_name or user.name or "ユーザー",
            "summary": _group_user_persona_context(user),
            "kind": "user_persona",
            "world_entry_type": user.world_entry_type,
            "arrival_reason": user.arrival_reason,
            "adaptation_note": user.world_adaptation_note,
        })
    return participants


def _open_group_relationship_dialog(
    ctx,
    group: GroupChatRecord,
    relationship: GroupRelationship | None,
    on_group_updated: Callable[[GroupChatRecord], None] | None,
) -> None:
    options = _group_relationship_options(group)
    if len(options) < 2:
        ui.notify("関係性を設定できる参加者が足りません", type="warning")
        return
    default_keys = list(options)
    first_value = relationship.participant_a_key if relationship else default_keys[0]
    second_value = relationship.participant_b_key if relationship else default_keys[1]

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-lg"):
        ui.label("関係性を編集" if relationship else "関係性を追加").classes("text-base font-semibold")
        first_select = ui.select(
            options=options,
            value=first_value if first_value in options else default_keys[0],
            label="参加者1",
        ).props("outlined dense").classes("w-full")
        second_select = ui.select(
            options=options,
            value=second_value if second_value in options else default_keys[1],
            label="参加者2",
        ).props("outlined dense").classes("w-full")
        with ui.element("div").classes("cs-group-world-field"):
            description_input = ui.textarea(
                label="関係性",
                value=relationship.description if relationship else "",
                placeholder="例: 幼なじみだが、現在は互いに距離を測っている。",
            ).props("outlined rows=5").classes("w-full")

            async def _enhance_relationship_click() -> None:
                enhanced = await _enhance_relationship_description(
                    ctx,
                    group.completion_profile_id,
                    group.world,
                    _group_relationship_enhancement_participants(group),
                    str(first_select.value or ""),
                    str(second_select.value or ""),
                    str(description_input.value or ""),
                )
                if enhanced:
                    description_input.set_value(enhanced)

            ui.button(
                icon="auto_awesome",
                on_click=_enhance_relationship_click,
            ).props("flat round dense size=sm").classes("cs-group-world-enhance").tooltip(
                "関係性を補完"
            )

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
                group.id,
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
            if on_group_updated is not None:
                on_group_updated(saved)

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("保存", icon="save", on_click=_save).props("color=primary unelevated")
    dlg.open()


async def _delete_group_relationship(
    ctx,
    group: GroupChatRecord,
    relationship_id: str,
    on_group_updated: Callable[[GroupChatRecord], None] | None,
) -> None:
    saved = await ctx.group_chats.delete_relationship(group.id, relationship_id)
    if saved is None:
        ui.notify("グループが見つかりませんでした", type="warning")
        return
    ui.notify("関係性を削除しました", type="positive")
    if on_group_updated is not None:
        on_group_updated(saved)


def open_add_group_character_dialog(ctx, group: GroupChatRecord) -> None:
    profiles = ctx.api_config.get_llm_profiles()
    profile_options = _profile_options(ctx, profiles)
    default_profile_id = (
        group.completion_profile_id
        if group.completion_profile_id in profile_options
        else _default_profile_id(ctx, profile_options)
    )
    page_client = ui.context.client
    selected = {"characters": []}
    handle_inputs: dict[str, Any] = {}
    controls: dict[str, Any] = {}
    state: dict[str, Any] = {
        "profile_id": default_profile_id,
        "handle_values": {},
        "entry_modes": {},
        "arrival_reasons": {},
        "adaptation_notes": {},
        "adaptation_instructions": {},
        "draft_sheets": {},
    }
    existing_source_ids = {
        member.source_character_id or member.character.id
        for member in group.members
        if member.source_character_id or member.character.id
    }
    existing_handles = {member.handle.lower() for member in group.members}
    if group.user_persona is not None:
        existing_handles.add(group.user_persona.handle.lower())

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-2xl").style(
        "max-width: min(760px, 94vw); height: min(820px, 94vh); "
        "display: flex; flex-direction: column;"
    ):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("キャラクター追加").classes("text-lg font-semibold")
            ui.button(icon="close", on_click=dlg.close).props("flat round dense")

        ui.label("追加したキャラクターはグループ内コピーとして保存します。").classes(
            "cs-group-note"
        )

        with ui.scroll_area().style("flex: 1; min-height: 0; width: 100%;"):
            body = ui.column().classes("w-full gap-3 pr-2")
        nav = ui.row().classes("justify-end gap-2 mt-4")
        busy_state: dict[str, Any] = {"active": False, "job_id": ""}
        with ui.dialog().props("persistent") as busy_dialog, ui.card().classes(
            "items-center gap-3 px-6 py-5"
        ).style("min-width: min(320px, 86vw);"):
            ui.spinner(size="lg")
            busy_label = ui.label("処理中です").classes("text-sm font-semibold text-center")
            busy_cancel_btn = ui.button(
                "キャンセル",
                icon="close",
                on_click=lambda: _cancel_busy_job(),
            ).props("outline color=negative")
            busy_cancel_btn.disable()

        def _participant_key(sheet: CharacterSheet) -> str:
            return f"character:{sheet.id}"

        def _world_text() -> str:
            return (group.world or "").strip()

        def _capture_inputs() -> None:
            if "profile_select" in controls:
                state["profile_id"] = str(controls["profile_select"].value or "")
            previous_handles = {
                character_id: str(input_.value or "")
                for character_id, input_ in handle_inputs.items()
            }
            if previous_handles:
                handle_values = dict(state.get("handle_values", {}))
                handle_values.update(previous_handles)
                state["handle_values"] = handle_values
            for key, select in controls.get("entry_selects", {}).items():
                next_mode = str(select.value or "native")
                state["entry_modes"][key] = next_mode
                if next_mode == "visitor":
                    state["adaptation_notes"].pop(key, None)
            for key, input_ in controls.get("arrival_inputs", {}).items():
                state["arrival_reasons"][key] = str(input_.value or "").strip()

        def _begin_busy(label: str) -> None:
            busy_state["active"] = True
            busy_state["job_id"] = ""
            busy_label.set_text(label)
            busy_cancel_btn.disable()
            busy_dialog.open()

        def _set_busy_job(job_id: str) -> None:
            if not busy_state.get("active"):
                return
            busy_state["job_id"] = job_id
            busy_cancel_btn.enable()

        def _end_busy() -> None:
            busy_state["active"] = False
            busy_state["job_id"] = ""
            busy_cancel_btn.disable()
            busy_dialog.close()

        async def _cancel_busy_job() -> None:
            job_id = str(busy_state.get("job_id") or "")
            if not job_id:
                return
            busy_label.set_text("停止要求中...")
            busy_cancel_btn.disable()
            await ctx.ai_jobs.cancel_job(job_id)

        def _refresh_selected_list() -> None:
            _capture_inputs()
            handle_inputs.clear()
            controls["entry_selects"] = {}
            controls["arrival_inputs"] = {}
            selected_list.clear()
            with selected_list:
                if not selected["characters"]:
                    ui.label("追加するキャラクターを選択してください").classes("text-sm text-grey-6")
                    return
                for sheet in selected["characters"]:
                    _render_character_entry_row(sheet)

        def _render_character_entry_row(sheet: CharacterSheet) -> None:
            key = _participant_key(sheet)
            mode = state["entry_modes"].get(key, "native")
            display_sheet = state["draft_sheets"].get(sheet.id, sheet) if mode != "visitor" else sheet
            with ui.element("div").classes("cs-group-selected-row").style(
                "grid-template-columns: 48px minmax(0, 1fr) 32px; align-items: start;"
            ):
                _render_character_face(ctx, display_sheet)
                with ui.column().classes("gap-2 min-w-0 w-full"):
                    with ui.column().classes("gap-0 min-w-0"):
                        ui.label(display_sheet.name).classes("cs-group-selected-name")
                        meta = " / ".join(filter(None, [sheet.world, display_sheet.occupation]))
                        ui.label(meta or "キャラクター").classes("cs-group-selected-meta")
                    handle_inputs[sheet.id] = ui.input(
                        label="ハンドル",
                        value=state["handle_values"].get(
                            sheet.id,
                            _fallback_handle(sheet, len(handle_inputs) + 1),
                        ),
                    ).props("outlined dense mask=\"NNNNNNNNNNNN\"").classes("w-full")
                    entry_select = ui.select(
                        options={
                            "native": "元々この世界の住人だった",
                            "visitor": "何らかの理由でこの世界に来た",
                        },
                        value=mode if mode in {"native", "visitor"} else "native",
                        label="ワールド参加設定",
                    ).props("outlined dense").classes("w-full")
                    controls["entry_selects"][key] = entry_select

                    def _refresh_entry_mode() -> None:
                        _capture_inputs()
                        _refresh_selected_list()

                    entry_select.on_value_change(lambda _: _refresh_entry_mode())
                    if mode == "visitor":
                        reason_input = ui.textarea(
                            label="この世界に来た理由",
                            value=state["arrival_reasons"].get(key, ""),
                        ).props("outlined rows=3").classes("w-full")
                        controls["arrival_inputs"][key] = reason_input
                        ui.button(
                            "理由を補完",
                            icon="auto_awesome",
                            on_click=lambda target_sheet=sheet: _generate_arrival_reason_click(target_sheet),
                        ).props("flat dense color=primary").classes("w-fit")
                    else:
                        ui.button(
                            "ワールドに馴染ませる",
                            icon="auto_fix_high",
                            on_click=lambda target_sheet=display_sheet, original_id=sheet.id: _open_world_adaptation_dialog(
                                _participant_key(sheet),
                                target_sheet.name,
                                lambda instruction, target_sheet=target_sheet, original_id=original_id: _adapt_character_click(
                                    target_sheet,
                                    original_id,
                                    instruction,
                                ),
                            ),
                        ).props("outline dense color=primary").classes("w-fit")
                        if state["adaptation_notes"].get(key):
                            ui.label("調整済み").classes("text-xs text-grey-6")
                ui.button(
                    icon="close",
                    on_click=lambda character_id=sheet.id: _remove_character(character_id),
                ).props("flat round dense").tooltip("リストから外す")

        def _remove_character(character_id: str) -> None:
            _capture_inputs()
            selected["characters"] = [
                sheet for sheet in selected["characters"] if sheet.id != character_id
            ]
            handle_inputs.pop(character_id, None)
            state["handle_values"].pop(character_id, None)
            state["entry_modes"].pop(f"character:{character_id}", None)
            state["arrival_reasons"].pop(f"character:{character_id}", None)
            state["adaptation_notes"].pop(f"character:{character_id}", None)
            state["adaptation_instructions"].pop(f"character:{character_id}", None)
            state["draft_sheets"].pop(character_id, None)
            _refresh_selected_list()

        async def _open_picker() -> None:
            async def _add_character(sheet: CharacterSheet) -> None:
                if sheet.id in existing_source_ids:
                    ui.notify("このキャラクターは既にグループにいます", type="warning")
                    return
                if any(current.id == sheet.id for current in selected["characters"]):
                    ui.notify("このキャラクターは選択済みです", type="warning")
                    return
                selected["characters"].append(sheet)
                state["entry_modes"].setdefault(_participant_key(sheet), "native")
                _refresh_selected_list()

            await open_character_picker(
                ctx,
                _add_character,
                title="グループに追加するキャラクターを選択",
                empty_message="追加できるキャラクターがありません",
            )

        async def _generate_handles_click() -> None:
            _capture_inputs()
            _begin_busy("ハンドルを生成しています...")
            try:
                await _generate_handles(
                    ctx,
                    str(state.get("profile_id") or ""),
                    [
                        state["draft_sheets"].get(sheet.id, sheet)
                        for sheet in selected["characters"]
                    ],
                    group.user_persona,
                    handle_inputs,
                    None,
                    on_job_started=_set_busy_job,
                    reserved_handles=existing_handles,
                )
                _capture_inputs()
            finally:
                _end_busy()

        def _open_world_adaptation_dialog(
            participant_key: str,
            display_name: str,
            run_adaptation: Callable[[str], Awaitable[None]],
        ) -> None:
            _capture_inputs()
            with ui.dialog() as adaptation_dialog, ui.card().classes("w-full max-w-lg"):
                ui.label("ワールドに馴染ませる").classes("text-base font-semibold")
                ui.label(display_name).classes("text-sm text-grey-6")
                instruction_input = ui.textarea(
                    label="追加指示（任意）",
                    value=state["adaptation_instructions"].get(participant_key, ""),
                    placeholder="例: 職業は変えない、口調は元のままにする",
                ).props("outlined rows=5").classes("w-full")

                async def _run() -> None:
                    instruction = str(instruction_input.value or "").strip()
                    if instruction:
                        state["adaptation_instructions"][participant_key] = instruction
                    else:
                        state["adaptation_instructions"].pop(participant_key, None)
                    adaptation_dialog.close()
                    await run_adaptation(instruction)

                with ui.row().classes("justify-end gap-2 mt-4"):
                    ui.button("キャンセル", on_click=adaptation_dialog.close).props("flat")
                    ui.button("OK", icon="check", on_click=_run).props("color=primary unelevated")
            adaptation_dialog.open()

        async def _adapt_character_click(
            sheet: CharacterSheet,
            source_character_id: str,
            instruction: str,
        ) -> None:
            _capture_inputs()
            key = f"character:{source_character_id}"
            if state["entry_modes"].get(key, "native") != "native":
                ui.notify("ワールドに馴染ませる改変は「元々この世界の住人だった」設定で使用してください", type="warning")
                return
            _begin_busy("キャラクターシートを調整しています...")
            try:
                await _adapt_character_to_world(
                    ctx,
                    str(state.get("profile_id") or ""),
                    sheet,
                    _world_text(),
                    instruction,
                    lambda updated: _apply_adapted_sheet(source_character_id, key, updated),
                    page_client,
                    on_job_started=_set_busy_job,
                )
            finally:
                _end_busy()

        def _apply_adapted_sheet(
            source_character_id: str,
            participant_key: str,
            updated: CharacterSheet,
        ) -> None:
            state["draft_sheets"][source_character_id] = updated
            state["adaptation_notes"][participant_key] = "LLM改変を承認済み"
            _refresh_selected_list()

        async def _generate_arrival_reason_click(sheet: CharacterSheet) -> None:
            _capture_inputs()
            key = _participant_key(sheet)
            input_ = controls.get("arrival_inputs", {}).get(key)
            if input_ is None:
                return
            _begin_busy("来訪理由を補完しています...")
            try:
                reason = await _generate_arrival_reason(
                    ctx,
                    str(state.get("profile_id") or ""),
                    sheet.name,
                    _world_text(),
                    _compact_character_summary(sheet),
                    page_client,
                    on_job_started=_set_busy_job,
                )
                if reason:
                    input_.set_value(reason)
                    state["arrival_reasons"][key] = reason
            finally:
                _end_busy()

        async def _add_members() -> None:
            _capture_inputs()
            if not selected["characters"]:
                ui.notify("キャラクターを選択してください", type="warning")
                return
            handles = _validate_member_handles(
                selected["characters"],
                handle_inputs,
                existing_handles,
            )
            if handles is None:
                return
            prepared_members: list[tuple[CharacterSheet, str]] = []
            member_world_settings: dict[str, dict[str, str]] = {}
            for sheet, handle in zip(selected["characters"], handles, strict=True):
                key = _participant_key(sheet)
                entry_type = state["entry_modes"].get(key, "native")
                if entry_type == "visitor" and not state["arrival_reasons"].get(key, "").strip():
                    ui.notify(f"{sheet.name} の来訪理由を入力してください", type="warning")
                    return
                source_sheet = state["draft_sheets"].get(sheet.id, sheet) if entry_type == "native" else sheet
                prepared_sheet, settings = _prepare_group_character_for_world(
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
                group.id,
                prepared_members,
                member_world_settings=member_world_settings,
            )
            if saved is None:
                ui.notify("グループが見つかりませんでした", type="warning")
                return
            dlg.close()
            ui.notify("キャラクターを追加しました", type="positive")
            ui.navigate.to(f"/groups/{saved.id}")

        with body:
            controls["profile_select"] = ui.select(
                options=profile_options,
                value=state["profile_id"] if state["profile_id"] in profile_options else _default_profile_id(ctx, profile_options),
                label="補完用LLMプロファイル",
            ).props("outlined dense").classes("w-full")
            with ui.element("div").classes("cs-group-modal-section"):
                with ui.element("div").classes("cs-group-modal-actions"):
                    with ui.column().classes("gap-0"):
                        ui.label("追加するキャラクター").classes("text-sm font-semibold")
                        ui.label(f"ワールド: {group.world or '未設定'}").classes("cs-group-note")
                    ui.button(
                        "キャラクターを選択",
                        icon="person_search",
                        on_click=_open_picker,
                    ).props("color=primary unelevated").style("border-radius: 8px; font-weight: 700;")
                selected_list = ui.element("div").classes("cs-group-selected-list").style(
                    "max-height: none;"
                )
                _refresh_selected_list()
            ui.button(
                "一括でハンドル生成",
                icon="auto_fix_high",
                on_click=_generate_handles_click,
            ).props("flat color=primary").classes("w-fit")

        with nav:
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button("追加", icon="person_add", on_click=_add_members).props(
                "color=primary unelevated"
            )

    dlg.open()


def _group_participants(group: GroupChatRecord) -> list[dict[str, Any]]:
    participants: list[dict[str, Any]] = []
    for member in group.members:
        participants.append({
            "key": f"member:{member.id}",
            "kind": "character",
            "name": member.character.name,
            "handle": member.handle,
            "member": member,
            "media": member.character.media,
        })
    if group.user_persona is not None:
        participants.append({
            "key": f"user:{group.user_persona.id}",
            "kind": "user",
            "name": group.user_persona.display_name or group.user_persona.name or "ユーザー",
            "handle": group.user_persona.handle,
            "persona": group.user_persona,
            "media": group.user_persona.media,
        })
    return participants


def _render_participant_face(ctx, participant: dict[str, Any], *, large: bool = False) -> None:
    classes = "cs-group-face"
    if large:
        classes += " cs-group-face-large"
    style = _participant_media_style(ctx, participant, rect_kind="face")
    with ui.element("div").classes(classes).style(style):
        if not style:
            ui.icon("person").classes("text-sm")


def _render_group_member_menu_face(ctx, member: GroupMember) -> None:
    participant = {
        "kind": "character",
        "media": member.character.media,
    }
    _render_participant_face(ctx, participant)


def _render_group_user_menu_face(ctx, persona: GroupUserPersona | None) -> None:
    if persona is None:
        with ui.element("div").classes("cs-group-face"):
            ui.icon("person").classes("text-sm")
        return
    participant = {
        "kind": "user",
        "media": persona.media,
    }
    _render_participant_face(ctx, participant)


def _render_group_guest_face() -> None:
    with ui.element("div").classes("cs-group-face cs-group-face-guest"):
        ui.icon(_group_input_mode_icon("guest")).classes("text-sm")


def _render_group_role_icon(mode: str) -> None:
    with ui.element("div").classes("cs-group-select-role-icon"):
        ui.icon(_group_input_mode_icon(mode)).classes("text-sm")


def _participant_media_style(ctx, participant: dict[str, Any], *, rect_kind: str) -> str:
    media = participant.get("media")
    if not isinstance(media, CharacterMedia):
        return ""
    image = media.primary_image()
    if image is None:
        return ""
    if participant.get("kind") == "user":
        image_path = ctx.api_config.media_path(image.path)
    else:
        image_path = ctx.characters.media_path(image.path)
    rect = image.bust_rect if rect_kind == "bust" else image.face_rect
    return cropped_background_style(image, image_path, rect, 1.0) if image_path else ""


def _participant_profile_rows(participant: dict[str, Any]) -> list[tuple[str, str]]:
    if participant.get("kind") == "user":
        persona: GroupUserPersona | None = participant.get("persona")
        return [
            ("区分", "ユーザー"),
            ("表示名", persona.display_name if persona else ""),
            ("名前", persona.name if persona else ""),
            ("ハンドル", f"@{participant['handle']}"),
        ]

    member: GroupMember | None = participant.get("member")
    sheet = member.character if member else None
    return [
        ("年齢", sheet.age if sheet else ""),
        ("性別", sheet.gender if sheet else ""),
        ("職業・役割", sheet.occupation if sheet else ""),
        ("出身・所属", sheet.origin if sheet else ""),
    ]


def _participant_profile_text(participant: dict[str, Any]) -> str:
    if participant.get("kind") == "user":
        persona: GroupUserPersona | None = participant.get("persona")
        return (persona.description if persona else "") or "未設定"

    member: GroupMember | None = participant.get("member")
    if member is None:
        return "未設定"
    sheet = member.character
    values = [
        sheet.personality,
        sheet.motivation,
        sheet.background,
        sheet.self_intro,
        sheet.sample_dialogues,
    ]
    return "\n".join(value for value in values if value).strip() or "未設定"


def _render_recent_group(group: GroupChatRecord) -> None:
    with ui.element("div").classes("cs-group-recent-item"):
        with ui.element("div").classes("cs-group-recent-title-row"):
            ui.label(group.name).classes("cs-group-recent-title")
            ui.label(_time_label(group.updated_at)).classes("cs-group-recent-time")
        ui.label("最近のチャットはまだありません").classes("cs-group-recent-preview")


def _render_selected_character_row(
    ctx,
    sheet: CharacterSheet,
    handle_inputs: dict[str, Any],
    *,
    value: str | None = None,
    remove,
) -> None:
    with ui.element("div").classes("cs-group-selected-row"):
        _render_character_face(ctx, sheet)
        with ui.column().classes("gap-0 cs-group-selected-info"):
            ui.label(sheet.name).classes("cs-group-selected-name")
            meta = " / ".join(filter(None, [sheet.world, sheet.occupation]))
            ui.label(meta or "キャラクター").classes("cs-group-selected-meta")
        handle_inputs[sheet.id] = ui.input(
            label="ハンドル",
            value=value or _fallback_handle(sheet, len(handle_inputs) + 1),
        ).props("outlined dense mask=\"NNNNNNNNNNNN\"").classes("w-full")
        ui.button(icon="close", on_click=remove).props("flat round dense").tooltip("リストから外す")


def _render_character_face(ctx, sheet: CharacterSheet) -> None:
    image = sheet.media.primary_image()
    image_path = ctx.characters.media_path(image.path) if image else None
    style = cropped_background_style(image, image_path, image.face_rect, 1.0) if image and image_path else ""
    with ui.element("div").classes("cs-group-selected-face").style(style):
        if not style:
            ui.icon("person")


def _render_face(ctx, media: CharacterMedia, source: str) -> None:
    image = media.primary_image()
    if source == "persona":
        image_path = ctx.api_config.media_path(image.path) if image else None
    else:
        image_path = ctx.characters.media_path(image.path) if image else None
    style = cropped_background_style(image, image_path, image.face_rect, 1.0) if image and image_path else ""
    with ui.element("div").classes("cs-group-face").style(style):
        if not style:
            ui.icon("person").classes("text-sm")


async def _generate_handles(
    ctx,
    profile_id: str,
    characters: list[CharacterSheet],
    persona,
    handle_inputs: dict[str, Any],
    user_handle_input=None,
    on_job_started: Callable[[str], None] | None = None,
    reserved_handles: set[str] | None = None,
) -> None:
    if not characters:
        ui.notify("キャラクターを選択してください", type="warning")
        return
    if persona is None:
        ui.notify("ユーザーペルソナを選択してください", type="warning")
        return
    llm = _configured_llm(ctx, profile_id)
    if llm is None:
        return

    payload = {
        "characters": [
            {
                "id": sheet.id,
                "name": sheet.name,
                "role": sheet.occupation,
                "summary": _compact_character_summary(sheet),
            }
            for sheet in characters
        ],
        "user": {
            "id": "user",
            "name": persona.name,
            "display_name": persona.display_name,
            "persona_name": getattr(persona, "persona_name", ""),
            "description": persona.description[:1000],
        },
    }
    async def _runner() -> dict[str, str]:
        response = await llm.ainvoke([
            SystemMessage(content="あなたはグループチャット用のメンションハンドルを作る編集者です。"),
            HumanMessage(content=(
                "次の参加者に似合う、重複しないハンドルを作ってください。\n"
                "制約: 3〜12文字、英数字と_のみ、全員で重複禁止。\n"
                "ユーザーのハンドルもペルソナ名・説明・役割に寄せ、User、Player、Me のような汎用名は避けてください。\n"
                "出力はJSONのみ。形式は {\"characters\":[{\"id\":\"...\",\"handle\":\"...\"}],\"user\":\"...\"}。\n\n"
                f"{json.dumps(payload, ensure_ascii=False)}"
            )),
        ])
        raw = message_content_to_text(getattr(response, "content", response))
        return _parse_handle_response(raw)

    job = ctx.ai_jobs.start_job(
        kind=AIJobKind.LLM_ASSIST,
        label="グループハンドル生成",
        scope="group_setup:handles",
        metadata={"character_count": len(characters)},
        runner=lambda _: _runner(),
    )
    if on_job_started is not None:
        on_job_started(job.id)
    ctx.ai_jobs.set_result_meta(job.id, {"result_url": "/groups"})
    finished = await ctx.ai_jobs.wait(job.id)
    if finished.status == AIJobStatus.CANCELLED:
        ui.notify("ハンドル生成を停止しました", type="info")
        return
    if finished.status != AIJobStatus.SUCCEEDED:
        ui.notify(
            f"ハンドル生成に失敗しました: {finished.error_message}",
            type="negative",
            timeout=10000,
        )
        return
    suggested = finished.result or {}

    used: set[str] = {handle.lower() for handle in reserved_handles or set()}
    for index, sheet in enumerate(characters, start=1):
        candidate = suggested.get(sheet.id) or suggested.get(sheet.name) or _fallback_handle(sheet, index)
        handle = _unique_handle(_sanitize_handle(candidate, _fallback_handle(sheet, index)), used)
        used.add(handle.lower())
        handle_inputs[sheet.id].set_value(handle)
    user_fallback = _fallback_persona_handle(persona)
    user_candidate = suggested.get("user") or suggested.get(persona.display_name) or user_fallback
    user_handle = _unique_handle(_sanitize_handle(user_candidate, user_fallback), used)
    if user_handle_input is not None:
        user_handle_input.set_value(user_handle)
    ui.notify("ハンドルを生成しました", type="positive")


async def _enhance_world_click(
    ctx,
    profile_id: str,
    characters: list[CharacterSheet],
    persona,
    world_input,
    name_input,
    on_job_started: Callable[[str], None] | None = None,
) -> None:
    current_world = (world_input.value or "").strip()
    if not current_world:
        ui.notify("先に世界観を入力してください", type="warning")
        return
    llm = _configured_llm(ctx, profile_id)
    if llm is None:
        return

    async def _runner() -> str:
        response = await llm.ainvoke([
            SystemMessage(content=(
                "あなたはグループチャットの世界観設定を膨らませる編集者です。"
                "出力には世界観本文以外を絶対に含めません。"
            )),
            HumanMessage(content=(
                "既存の世界観入力を、核を変えずに具体化してください。\n"
                "通常チャットのシチュエーション補完や/tailorのように、入力済みの内容を広げるだけにしてください。\n"
                "新しい固有名詞や重大設定を増やしすぎず、会話開始時に使いやすい密度にしてください。\n"
                "参加者紹介、ユーザー説明、グループ名、見出し、ラベル、箇条書き、解説、前置き、引用符は出力しないでください。\n"
                "出力は補完後の世界観本文だけにしてください。\n\n"
                "補完対象の世界観本文:\n"
                f"{current_world}"
            )),
        ])
        return message_content_to_text(getattr(response, "content", response))

    job = ctx.ai_jobs.start_job(
        kind=AIJobKind.LLM_ASSIST,
        label="グループ世界観補完",
        scope="group_setup:world",
        metadata={"character_count": len(characters)},
        runner=lambda _: _runner(),
    )
    if on_job_started is not None:
        on_job_started(job.id)
    ctx.ai_jobs.set_result_meta(job.id, {"result_url": "/groups"})
    finished = await ctx.ai_jobs.wait(job.id)
    if finished.status == AIJobStatus.CANCELLED:
        ui.notify("世界観補完を停止しました", type="info")
        return
    if finished.status != AIJobStatus.SUCCEEDED:
        ui.notify(
            f"世界観補完に失敗しました: {finished.error_message}",
            type="negative",
            timeout=10000,
        )
        return
    enhanced = _clean_world_enhancement(
        str(finished.result or ""),
        current_world=current_world,
        group_name=str(name_input.value or ""),
        characters=characters,
        persona=persona,
    )
    if not enhanced:
        ui.notify("世界観を補完できませんでした", type="warning")
        return
    world_input.set_value(enhanced)
    ui.notify("世界観を補完しました", type="positive")


async def _generate_group_name_from_world(
    ctx,
    profile_id: str,
    world: str,
    characters: list[CharacterSheet],
    persona,
    page_client=None,
    on_job_started: Callable[[str], None] | None = None,
) -> str:
    current_world = (world or "").strip()
    if not current_world:
        ui.notify("先にワールドを入力してください", type="warning")
        return ""
    llm = _configured_llm(ctx, profile_id)
    if llm is None:
        return ""

    participant_lines = "\n".join(
        f"- {sheet.name}: {_compact_character_summary(sheet)}"
        for sheet in characters
    )
    if persona is not None:
        participant_lines += (
            f"\n- {persona.display_name or persona.name or 'ユーザー'}: "
            f"{getattr(persona, 'description', '') or 'ユーザー'}"
        )

    async def _runner() -> str:
        response = await llm.ainvoke([
            SystemMessage(content=(
                "あなたはグループチャットの短いグループ名を作る編集者です。"
                "出力はグループ名本文だけにしてください。"
            )),
            HumanMessage(content=(
                "次のワールド説明から、グループチャットの名前を1つだけ作ってください。\n"
                "制約: 8〜20文字程度、会話一覧で見分けやすい自然な日本語、引用符・句点・解説・前置きは禁止。\n"
                "参加者名をそのまま並べるだけの名前は避け、ワールドの雰囲気や場を反映してください。\n\n"
                f"ワールド:\n{current_world}\n\n"
                f"参加者:\n{participant_lines or '未設定'}"
            )),
        ])
        return message_content_to_text(getattr(response, "content", response))

    job = ctx.ai_jobs.start_job(
        kind=AIJobKind.LLM_ASSIST,
        label="グループ名補完",
        scope="group_setup:name",
        metadata={"character_count": len(characters)},
        runner=lambda _: _runner(),
    )
    if on_job_started is not None:
        on_job_started(job.id)
    ctx.ai_jobs.set_result_meta(job.id, {"result_url": "/groups"})
    finished = await ctx.ai_jobs.wait(job.id)
    if finished.status == AIJobStatus.CANCELLED:
        _notify_on_client(page_client, "グループ名補完を停止しました", type="info")
        return ""
    if finished.status != AIJobStatus.SUCCEEDED:
        _notify_on_client(
            page_client,
            f"グループ名補完に失敗しました: {finished.error_message}",
            type="negative",
            timeout=10000,
        )
        return ""
    name = _clean_generated_group_name(str(finished.result or ""))
    if not name:
        _notify_on_client(page_client, "グループ名を補完できませんでした", type="warning")
        return ""
    _notify_on_client(page_client, "グループ名を補完しました", type="positive")
    return name


def _clean_generated_group_name(raw: str) -> str:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:\w+)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    parsed = _try_parse_json(text)
    if parsed is not None:
        text = _longest_json_string(parsed) or text
    text = _strip_possible_label_prefix(text.strip())
    return sanitize_chat_title(text, max_chars=24)


def _clean_world_enhancement(
    raw: str,
    *,
    current_world: str,
    group_name: str,
    characters: list[CharacterSheet],
    persona,
) -> str:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:\w+)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()

    parsed = _try_parse_json(text)
    if parsed is not None:
        text = _longest_json_string(parsed) or text

    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            lines.append("")
            continue
        line = _strip_possible_label_prefix(line)
        if not line:
            continue
        if _looks_like_non_world_line(line):
            continue
        lines.append(line)

    cleaned = "\n".join(lines).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = cleaned.strip(" \t\r\n\"'「」『』")

    if _contains_known_non_world_content(
        cleaned,
        current_world=current_world,
        group_name=group_name,
        characters=characters,
        persona=persona,
    ):
        return ""
    return cleaned


def _clean_group_situation_enhancement(raw: str) -> str:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:\w+)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()

    parsed = _try_parse_json(text)
    if parsed is not None:
        text = _longest_json_string(parsed) or text

    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            lines.append("")
            continue
        line = _strip_possible_label_prefix(line)
        if not line:
            continue
        if re.match(r"^[#>\[\]{}]+", line):
            continue
        line = re.sub(r"^[-*・]\s+", "", line).strip()
        if line:
            lines.append(line)

    cleaned = "\n".join(lines).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip(" \t\r\n\"'「」『』")


def _try_parse_json(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _longest_json_string(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        values = [_longest_json_string(item) for item in value.values()]
        return max(values, key=len, default="")
    if isinstance(value, list):
        values = [_longest_json_string(item) for item in value]
        return max(values, key=len, default="")
    return ""


def _looks_like_non_world_line(line: str) -> bool:
    normalized = line.strip()
    if not normalized:
        return False
    if re.match(r"^[-*・]\s+", normalized):
        return True
    if len(normalized) <= 40 and re.match(r"^[^。.!?！？]{1,40}[：:]\s*.*$", normalized):
        return True
    if re.match(r"^[#>\[\]{}]+", normalized):
        return True
    return False


def _strip_possible_label_prefix(line: str) -> str:
    match = re.match(r"^([^。.!?！？\n]{1,24})[：:]\s*(.+)$", line)
    if not match:
        return line
    prefix, body = match.groups()
    if re.search(r"\s", prefix) and not re.search(r"[A-Za-z0-9_]", prefix):
        return line
    return body.strip()


def _contains_known_non_world_content(
    text: str,
    *,
    current_world: str,
    group_name: str,
    characters: list[CharacterSheet],
    persona,
) -> bool:
    if not text:
        return False
    allowed = current_world or ""
    fragments = [group_name.strip()]
    fragments.extend(sheet.name.strip() for sheet in characters)
    if persona is not None:
        fragments.extend([
            str(getattr(persona, "name", "") or "").strip(),
            str(getattr(persona, "persona_name", "") or "").strip(),
            str(getattr(persona, "display_name", "") or "").strip(),
        ])
    for fragment in fragments:
        if len(fragment) < 3:
            continue
        if fragment in text and fragment not in allowed:
            return True
    return False


def _validate_member_handles(
    characters: list[CharacterSheet],
    handle_inputs: dict[str, Any],
    existing_handles: set[str] | None = None,
) -> list[str] | None:
    handles: list[str] = []
    seen: set[str] = set(existing_handles or set())
    for sheet in characters:
        handle = str(handle_inputs[sheet.id].value or "").strip()
        if not _HANDLE_RE.fullmatch(handle):
            ui.notify(f"{sheet.name} のハンドルは3〜12文字の英数字または_で入力してください", type="warning")
            return None
        key = handle.lower()
        if key in seen:
            ui.notify("ハンドルが重複しています", type="warning")
            return None
        seen.add(key)
        handles.append(handle)
    return handles


def _validate_handles(
    characters: list[CharacterSheet],
    handle_inputs: dict[str, Any],
    user_handle_input,
) -> tuple[list[str], str] | None:
    handles = _validate_member_handles(characters, handle_inputs)
    if handles is None:
        return None
    seen = {handle.lower() for handle in handles}
    user_handle = str(user_handle_input.value or "").strip()
    if not _HANDLE_RE.fullmatch(user_handle):
        ui.notify("ユーザーのハンドルは3〜12文字の英数字または_で入力してください", type="warning")
        return None
    if user_handle.lower() in seen:
        ui.notify("ハンドルが重複しています", type="warning")
        return None
    return handles, user_handle


def _configured_llm(ctx, profile_id: str):
    profile = ctx.api_config.get_llm_profile(profile_id)
    if profile is None:
        ui.notify("補完用LLMプロファイルを選択してください", type="warning")
        return None
    if not profile.model_id:
        ui.notify("補完用LLMプロファイルのモデルIDが未設定です", type="negative")
        return None
    endpoint = ctx.api_config.get_endpoint(profile.endpoint_id)
    if endpoint is None:
        ui.notify("補完用LLMプロファイルのエンドポイントが見つかりません", type="negative")
        return None
    api_key = ctx.api_config.get_api_key(profile.endpoint_id, get_vault_password())
    if ctx.api_config.is_api_key_locked(profile.endpoint_id, api_key):
        ui.notify("APIキーボルトをロック解除してください", type="warning", timeout=8000)
        return None
    try:
        return create_llm(profile, endpoint, api_key)
    except Exception as err:
        ui.notify(f"LLMの初期化に失敗しました: {err}", type="negative", timeout=10000)
        return None


def _profile_options(ctx, profiles) -> dict[str, str]:
    endpoints = {endpoint.id: endpoint for endpoint in ctx.api_config.get_endpoints()}
    options: dict[str, str] = {}
    for profile in profiles:
        endpoint = endpoints.get(profile.endpoint_id)
        endpoint_name = endpoint.name if endpoint else "不明"
        model = profile.model_id or "未設定"
        options[profile.id] = f"{profile.name} [{endpoint_name} / {model}]"
    return options


def _default_profile_id(ctx, options: dict[str, str]) -> str:
    config = ctx.api_config.get_app_llm_config()
    for profile_id in (config.chat_profile_id, config.generation_profile_id):
        if profile_id in options:
            return profile_id
    return next(iter(options), "")


def _default_persona_id(options: dict[str, str]) -> str:
    return next(iter(options), "")


def _selected_persona(ctx, persona_id: str):
    return ctx.api_config.get_user_persona(persona_id) if persona_id else None


def _parse_handle_response(raw: str) -> dict[str, str]:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    result: dict[str, str] = {}
    if isinstance(data, dict):
        for item in data.get("characters", []):
            if isinstance(item, dict):
                key = str(item.get("id") or item.get("name") or "")
                value = str(item.get("handle") or "")
                if key and value:
                    result[key] = value
        user = data.get("user")
        if isinstance(user, str):
            result["user"] = user
        elif isinstance(user, dict):
            result["user"] = str(user.get("handle") or "")
        for key, value in data.items():
            if isinstance(value, str):
                result.setdefault(str(key), value)
    return result


def _sanitize_handle(value: str, fallback: str) -> str:
    candidate = re.sub(r"[^A-Za-z0-9_]", "", value or "")
    if len(candidate) < 3:
        candidate = fallback
    candidate = re.sub(r"[^A-Za-z0-9_]", "", candidate)
    if len(candidate) < 3:
        candidate = "User"
    return candidate[:12]


def _unique_handle(candidate: str, used: set[str]) -> str:
    base = candidate[:12] or "User"
    if len(base) < 3:
        base = (base + "___")[:3]
    if base.lower() not in used:
        return base
    for index in range(2, 100):
        suffix = str(index)
        prefix = base[: 12 - len(suffix)]
        handle = f"{prefix}{suffix}"
        if len(handle) >= 3 and handle.lower() not in used:
            return handle
    return uuid_like_handle(used)


def uuid_like_handle(used: set[str]) -> str:
    index = len(used) + 1
    while True:
        handle = f"User{index}"
        if handle.lower() not in used:
            return handle
        index += 1


def _fallback_handle(sheet: CharacterSheet, index: int) -> str:
    return f"Char{index}"


def _fallback_persona_handle(persona) -> str:
    for value in (
        getattr(persona, "persona_name", ""),
        getattr(persona, "name", ""),
        getattr(persona, "display_name", ""),
    ):
        candidate = _ascii_outside_parentheses(str(value or ""))
        if len(candidate) >= 3:
            return candidate[:12]
    return "Persona"


def _ascii_outside_parentheses(value: str) -> str:
    text = re.sub(r"（[^）]*）", "", value)
    text = re.sub(r"\([^)]*\)", "", text)
    return re.sub(r"[^A-Za-z0-9_]", "", text)


def _compact_character_summary(sheet: CharacterSheet) -> str:
    summary = character_summary(sheet)
    summary = re.sub(r"\s+", " ", summary).strip()
    return summary[:420]


def _time_label(value: datetime) -> str:
    now = datetime.now()
    if value.date() == now.date():
        return value.strftime("%H:%M")
    if value.year == now.year:
        return f"{value.month}/{value.day}"
    return value.strftime("%Y/%m/%d")
