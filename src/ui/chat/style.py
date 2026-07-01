"""CSS for the character chat page."""

CHAT_CSS = """
<style>
.nicegui-content:has(.cs-chat-shell) {
  height: 100% !important;
  min-height: 0 !important;
  box-sizing: border-box !important;
  overflow: hidden !important;
  padding: 0 !important;
}
.nicegui-content:has(.cs-chat-shell) > .nicegui-column {
  height: 100% !important;
  min-height: 0 !important;
  padding: 0 !important;
}
.q-page-container:has(.cs-chat-shell) {
  height: 100dvh !important;
  min-height: 0 !important;
  box-sizing: border-box !important;
  overflow: hidden !important;
}
.q-page-container:has(.cs-chat-shell) .q-page {
  height: 100% !important;
  min-height: 0 !important;
  overflow: hidden !important;
}
.cs-chat-shell {
  position: relative;
  display: grid;
  grid-template-columns: minmax(240px, 280px) minmax(250px, 320px) minmax(380px, 1fr);
  gap: 0;
  width: 100%;
  height: 100%;
  margin: 0;
  min-height: 0;
  overflow: hidden;
  background: var(--cs-surface);
}
.cs-chat-panel {
  min-height: 0;
  overflow: hidden;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
  color: var(--cs-text);
}
.cs-chat-profile-pane,
.cs-chat-side-pane,
.cs-chat-history-pane {
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--cs-border);
  background: var(--cs-surface);
}
.cs-chat-profile-pane {
  overflow: auto;
}
.cs-chat-side-pane,
.cs-chat-mobile-sidebar,
.cs-chat-mobile-backdrop {
  display: none;
}
.cs-chat-scroll {
  min-height: 0;
  overflow: auto;
}
.cs-chat-history-pane > .cs-chat-scroll,
.cs-chat-side-pane > .cs-chat-scroll,
.cs-chat-mobile-sidebar > .cs-chat-scroll {
  flex: 1;
}
.cs-chat-profile-content {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 14px;
}
.cs-chat-bust {
  width: 100%;
  aspect-ratio: 3 / 4;
  overflow: hidden;
  border-radius: 8px;
  border: 1px solid var(--cs-border);
  background: var(--cs-surface-soft);
}
.cs-chat-bust-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--cs-muted);
}
.cs-chat-name {
  font-size: 1.25rem;
  font-weight: 700;
  line-height: 1.25;
  overflow-wrap: anywhere;
}
.cs-chat-profile-title,
.cs-chat-history-title {
  font-size: 0.76rem;
  font-weight: 700;
  color: var(--cs-muted);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.cs-chat-profile-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.cs-chat-profile-row {
  display: grid;
  gap: 2px;
}
.cs-chat-profile-label {
  font-size: 0.72rem;
  color: var(--cs-muted);
  font-weight: 600;
}
.cs-chat-profile-value {
  font-size: 0.86rem;
  line-height: 1.55;
  overflow-wrap: anywhere;
}
.cs-chat-history-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--cs-border);
}
.cs-chat-history-section {
  min-height: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
}
.cs-chat-thread-list {
  display: flex;
  flex-direction: column;
  padding: 8px;
  gap: 6px;
}
.cs-chat-thread {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 56px;
  align-items: start;
  gap: 4px;
  padding: 10px;
  border-radius: 8px;
  border: 1px solid transparent;
}
.cs-chat-thread-open {
  grid-column: 1;
  min-width: 0;
  width: 100%;
  display: grid;
  gap: 3px;
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}
.cs-chat-thread-actions {
  grid-column: 2;
  width: 56px;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 1px;
}
.cs-chat-thread-action {
  width: 26px !important;
  min-width: 26px !important;
  height: 26px !important;
  min-height: 26px !important;
  padding: 0 !important;
  color: var(--cs-muted);
}
.cs-chat-history-empty {
  padding: 10px 8px;
  font-size: 0.82rem;
  color: var(--cs-muted);
}
.cs-chat-thread-active {
  background: var(--cs-accent-bg);
  border-color: var(--cs-accent-border);
}
.cs-chat-thread-title-row {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}
.cs-chat-thread-title {
  min-width: 0;
  flex: 1;
  font-size: 0.9rem;
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cs-chat-thread-time {
  flex: 0 0 auto;
  font-size: 0.72rem;
  color: var(--cs-muted);
}
.cs-chat-thread-preview {
  font-size: 0.78rem;
  color: var(--cs-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cs-chat-main {
  display: flex;
  flex-direction: column;
  background: var(--cs-surface);
}
.cs-chat-main-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--cs-border);
}
.cs-chat-mobile-toggle {
  display: none;
}
.cs-chat-main-title {
  min-width: 0;
  flex: 1;
  overflow-wrap: anywhere;
}
.cs-chat-main-menu-trigger {
  flex: 0 0 auto;
  border-radius: 8px !important;
  color: var(--cs-muted) !important;
}
.cs-chat-main-menu-trigger:hover {
  background: var(--cs-accent-bg) !important;
  color: var(--cs-accent) !important;
}
.cs-chat-main-menu {
  width: min(240px, calc(100vw - 24px));
  padding: 6px;
  border: 1px solid var(--cs-border);
  border-radius: 10px;
  background: var(--cs-surface);
  box-shadow: 0 14px 32px rgba(0,0,0,0.18);
  box-sizing: border-box;
  overflow-x: hidden !important;
}
.cs-chat-main-menu .q-list {
  min-width: 0;
  overflow-x: hidden;
}
.cs-chat-main-menu-item {
  width: 100%;
  max-width: 100%;
  min-height: 40px;
  border-radius: 7px;
  color: var(--cs-text);
  box-sizing: border-box;
  overflow: hidden;
}
.cs-chat-main-menu-item:hover {
  background: var(--cs-accent-bg);
  background: color-mix(in srgb, var(--cs-accent-bg) 76%, transparent);
}
.cs-chat-main-menu-item .q-item__section--avatar {
  min-width: 30px;
  padding-right: 8px;
}
.cs-chat-main-menu-item .q-item__section {
  min-width: 0;
}
.cs-chat-main-menu-icon {
  color: var(--cs-muted);
  font-size: 19px;
}
.cs-chat-main-menu-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.86rem;
  font-weight: 700;
}
.cs-chat-main-menu-item-danger,
.cs-chat-main-menu-item-danger .cs-chat-main-menu-icon {
  color: #b23a48;
}
.cs-chat-main-menu-separator {
  margin: 6px 8px;
}
.cs-chat-messages {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px;
  background: linear-gradient(180deg, var(--cs-surface) 0%, var(--cs-surface-soft) 100%);
}
.cs-chat-message-row {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  max-width: 82%;
}
.cs-chat-message-row-character {
  align-self: flex-start;
}
.cs-chat-message-row-user {
  align-self: flex-end;
  justify-content: flex-end;
}
.cs-chat-message-row-narration {
  align-self: center;
  justify-content: center;
  max-width: min(720px, 92%);
}
.cs-chat-message-row-memo {
  align-self: center;
  justify-content: center;
  max-width: min(680px, 90%);
}
.cs-chat-face {
  width: 56px;
  height: 56px;
  flex: 0 0 56px;
  border-radius: 999px;
  border: 1px solid var(--cs-border);
  background: var(--cs-surface-soft);
  overflow: hidden;
}
.cs-chat-face-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--cs-muted);
}
.cs-chat-face-placeholder .q-icon {
  font-size: 1.45rem;
}
.cs-chat-bubble {
  position: relative;
  display: grid;
  gap: 6px;
  padding: 10px 12px;
  border: 1px solid var(--cs-border);
  border-radius: 8px;
  background: var(--cs-surface);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.cs-chat-message-row-character .cs-chat-bubble::before {
  content: "";
  position: absolute;
  left: -7px;
  bottom: 18px;
  width: 12px;
  height: 12px;
  background: var(--cs-surface);
  border-left: 1px solid var(--cs-border);
  border-bottom: 1px solid var(--cs-border);
  transform: rotate(45deg);
}
.cs-chat-message-row-user .cs-chat-bubble {
  background: var(--cs-accent);
  border-color: var(--cs-accent);
  color: #fff;
}
.cs-chat-message-row-narration .cs-chat-bubble {
  width: 100%;
  background: var(--cs-surface-soft);
  background: color-mix(in srgb, var(--cs-surface-soft) 72%, transparent);
  border-style: dashed;
  border-color: var(--cs-accent-border);
  color: var(--cs-text);
  box-shadow: none;
}
.cs-chat-message-row-narration .cs-chat-message-text {
  color: var(--cs-text);
}
.cs-chat-message-row-memo .cs-chat-bubble {
  width: 100%;
  background: color-mix(in srgb, var(--cs-surface) 82%, var(--cs-accent-bg));
  border-style: dotted;
  border-color: var(--cs-border);
  color: var(--cs-muted);
  box-shadow: none;
}
.cs-chat-message-row-memo .cs-chat-message-text {
  color: var(--cs-muted);
}
.cs-chat-message-kind {
  font-size: 0.7rem;
  font-weight: 700;
  color: var(--cs-accent);
}
.cs-chat-message-text {
  font-size: 0.93rem;
  line-height: 1.65;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.cs-chat-message-time {
  font-size: 0.68rem;
  color: var(--cs-muted);
}
.cs-chat-message-row-user .cs-chat-message-time {
  color: rgba(255,255,255,0.78);
}
.cs-chat-message-meta {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 4px;
}
.cs-chat-message-actions {
  display: flex;
  align-items: center;
  gap: 2px;
}
.cs-chat-message-action {
  min-width: 24px !important;
  min-height: 24px !important;
  color: var(--cs-muted);
}
.cs-chat-message-row-user .cs-chat-message-action {
  background: rgba(255,255,255,0.92) !important;
  color: var(--cs-accent) !important;
  border: 1px solid rgba(255,255,255,0.8);
}
.cs-chat-message-row-user .cs-chat-message-action:hover {
  background: #fff !important;
}
.cs-chat-composer-shell {
  position: relative;
  border-top: 1px solid var(--cs-border);
  background: var(--cs-surface);
}
.cs-chat-command-palette {
  position: absolute;
  left: 56px;
  right: 64px;
  bottom: calc(100% - 4px);
  z-index: 15;
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: min(42vh, 320px);
  overflow: auto;
  padding: 6px;
  border: 1px solid var(--cs-border);
  border-radius: 8px;
  background: var(--cs-surface);
  background: color-mix(in srgb, var(--cs-surface) 86%, transparent);
  box-shadow: 0 10px 28px rgba(0,0,0,0.18);
  backdrop-filter: blur(12px);
}
.cs-chat-command-palette:empty {
  display: none;
}
.cs-chat-command-palette-hidden {
  display: none !important;
}
.cs-chat-swipe-action-menu {
  position: absolute;
  left: 56px;
  right: 64px;
  bottom: calc(100% - 4px);
  z-index: 16;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 6px;
  border: 1px solid var(--cs-border);
  border-radius: 8px;
  background: var(--cs-surface);
  background: color-mix(in srgb, var(--cs-surface) 90%, transparent);
  box-shadow: 0 10px 28px rgba(0,0,0,0.18);
  backdrop-filter: blur(12px);
}
.cs-chat-swipe-action-menu-hidden {
  display: none !important;
}
.cs-chat-swipe-action-option {
  width: 100%;
  display: grid;
  grid-template-columns: 28px minmax(86px, auto) 1fr;
  align-items: center;
  gap: 9px;
  padding: 8px 9px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--cs-text);
  text-align: left;
  cursor: pointer;
}
.cs-chat-swipe-action-option:hover {
  background: var(--cs-accent-bg);
  background: color-mix(in srgb, var(--cs-accent-bg) 76%, transparent);
}
.cs-chat-swipe-action-icon {
  color: var(--cs-accent);
  font-size: 18px;
}
.cs-chat-swipe-action-command {
  font-size: 0.82rem;
  font-weight: 700;
  color: var(--cs-accent);
  font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
}
.cs-chat-swipe-action-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.8rem;
  color: var(--cs-muted);
}
.cs-chat-command-option {
  width: 100%;
  display: grid;
  grid-template-columns: minmax(84px, auto) 1fr;
  align-items: center;
  gap: 10px;
  padding: 7px 9px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--cs-text);
  text-align: left;
  cursor: pointer;
}
.cs-chat-command-option:hover,
.cs-chat-command-option-active {
  background: var(--cs-accent-bg);
  background: color-mix(in srgb, var(--cs-accent-bg) 76%, transparent);
}
.cs-chat-command-name {
  font-size: 0.82rem;
  font-weight: 700;
  color: var(--cs-accent);
  font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
}
.cs-chat-command-desc {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.75rem;
  color: var(--cs-muted);
}
.cs-chat-choice-option {
  position: relative;
  justify-content: flex-start !important;
  text-align: left !important;
  padding-left: 18px !important;
  padding-right: 42px !important;
  border-width: 1px !important;
  transition: background 0.12s ease, border-color 0.12s ease, box-shadow 0.12s ease;
}
.cs-chat-choice-option-active {
  background: var(--cs-accent-bg) !important;
  border-color: var(--cs-accent) !important;
  color: var(--cs-text) !important;
  box-shadow:
    inset 5px 0 0 var(--cs-accent),
    0 0 0 2px var(--cs-accent-border) !important;
  font-weight: 700 !important;
}
.cs-chat-choice-option-active .q-btn__content {
  color: var(--cs-text) !important;
  font-weight: 700 !important;
}
.cs-chat-choice-close {
  position: relative;
  border-width: 1px !important;
}
.cs-chat-guide-preset {
  max-width: 100%;
}
.cs-chat-guide-preset .q-btn__content {
  white-space: normal;
  line-height: 1.35;
  text-align: left;
}
.cs-chat-situation-field {
  position: relative;
  width: 100%;
}
.cs-chat-situation-field .q-field__control {
  padding-right: 44px;
}
.cs-chat-situation-field textarea {
  resize: none;
  scrollbar-width: thin;
  scrollbar-color: color-mix(in srgb, var(--cs-muted) 52%, transparent) transparent;
}
.cs-chat-situation-field textarea::-webkit-resizer {
  display: none;
}
.cs-chat-situation-field textarea::-webkit-scrollbar {
  width: 8px;
}
.cs-chat-situation-field textarea::-webkit-scrollbar-track {
  background: transparent;
  margin-block: 8px;
}
.cs-chat-situation-field textarea::-webkit-scrollbar-thumb {
  min-height: 28px;
  border: 2px solid transparent;
  border-radius: 999px;
  background: color-mix(in srgb, var(--cs-muted) 52%, transparent);
  background-clip: content-box;
}
.cs-chat-situation-field textarea::-webkit-scrollbar-thumb:hover {
  background: color-mix(in srgb, var(--cs-muted) 72%, transparent);
  background-clip: content-box;
}
.cs-chat-situation-enhance {
  position: absolute;
  top: 10px;
  right: 10px;
  z-index: 2;
  width: 32px !important;
  height: 32px !important;
  min-height: 32px !important;
  color: var(--cs-muted) !important;
  background: color-mix(in srgb, var(--cs-surface) 78%, transparent) !important;
  border: 1px solid transparent !important;
}
.cs-chat-situation-enhance:hover {
  color: var(--cs-accent) !important;
  background: var(--cs-accent-bg) !important;
  border-color: var(--cs-accent-border) !important;
}
.cs-chat-mode-icon {
  flex: 0 0 auto;
  width: 34px;
  height: 34px;
  min-width: 34px !important;
  min-height: 34px !important;
  padding: 0 !important;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  border: 1px solid var(--cs-border) !important;
  color: var(--cs-muted) !important;
  background: var(--cs-surface-soft) !important;
}
.cs-chat-mode-icon:hover {
  color: var(--cs-accent) !important;
  border-color: var(--cs-accent-border) !important;
  background: var(--cs-accent-bg) !important;
}
.cs-chat-mode-icon .q-btn__content,
.cs-chat-mode-icon-display {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}
.cs-chat-mode-icon .q-icon {
  font-size: 20px;
}
.cs-chat-mode-face {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 7px;
  overflow: hidden;
  background: var(--cs-surface);
}
.cs-chat-mode-face .q-icon {
  font-size: 19px;
}
.q-notifications__list--bottom,
.q-notifications__list--bottom-left,
.q-notifications__list--bottom-right {
  bottom: 96px !important;
}
.cs-chat-composer {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  padding: 12px;
}
.cs-chat-composer-input-wrap {
  flex: 1;
  min-width: 0;
  position: relative;
}
.cs-chat-composer-input {
  width: 100%;
  min-width: 0;
}
.cs-chat-composer-input-wrap:not(.cs-chat-composer-input-has-text):not(:has(.cs-chat-composer-input textarea:not(:placeholder-shown))) .cs-chat-composer-input textarea {
  padding-right: 44px !important;
}
.cs-chat-voice-input {
  position: absolute;
  right: 7px;
  bottom: 6px;
  z-index: 3;
  width: 30px !important;
  height: 30px !important;
  min-width: 30px !important;
  min-height: 30px !important;
  color: var(--cs-muted) !important;
  background: transparent !important;
  border: 1px solid transparent !important;
}
.cs-chat-voice-input:hover,
.cs-chat-voice-input-recording {
  color: var(--cs-accent) !important;
  background: var(--cs-accent-bg) !important;
  border-color: var(--cs-accent-border) !important;
}
.cs-chat-composer-input-has-text .cs-chat-voice-input,
.cs-chat-composer-input-wrap:has(.cs-chat-composer-input textarea:not(:placeholder-shown)) .cs-chat-voice-input {
  display: none !important;
}
@media (max-width: 1279px) and (min-width: 768px) {
  .cs-chat-shell {
    grid-template-columns: minmax(260px, 340px) minmax(380px, 1fr);
  }
  .cs-chat-profile-pane,
  .cs-chat-history-pane {
    display: none;
  }
  .cs-chat-side-pane {
    display: flex;
  }
}
@media (max-width: 767px) {
  .cs-chat-shell {
    display: block;
    height: 100%;
    min-height: 0;
  }
  .cs-chat-profile-pane,
  .cs-chat-side-pane,
  .cs-chat-history-pane {
    display: none;
  }
  .cs-chat-main {
    height: 100%;
  }
  .cs-chat-mobile-toggle {
    display: inline-flex;
  }
  .cs-chat-message-row {
    max-width: 92%;
  }
  .cs-chat-command-palette {
    left: 12px;
    right: 12px;
  }
  .cs-chat-swipe-action-menu {
    left: 12px;
    right: 12px;
  }
  .cs-chat-mobile-backdrop {
    display: block;
    position: absolute;
    inset: 0;
    z-index: 20;
    opacity: 0;
    pointer-events: none;
    background: rgba(0,0,0,0.34);
    transition: opacity 0.18s ease;
  }
  .cs-chat-mobile-sidebar {
    position: absolute;
    top: 0;
    bottom: 0;
    left: 0;
    z-index: 30;
    display: flex;
    flex-direction: column;
    width: min(86vw, 340px);
    visibility: hidden;
    pointer-events: none;
    background: var(--cs-surface);
    border-right: 1px solid var(--cs-border);
    transform: translateX(-110%);
    transition: transform 0.2s ease;
    box-shadow: 8px 0 18px rgba(0,0,0,0.14);
  }
  .cs-chat-shell.cs-mobile-sidebar-open .cs-chat-mobile-backdrop {
    opacity: 1;
    pointer-events: auto;
  }
  .cs-chat-shell.cs-mobile-sidebar-open .cs-chat-mobile-sidebar {
    visibility: visible;
    pointer-events: auto;
    transform: translateX(0);
  }
}
</style>
"""
