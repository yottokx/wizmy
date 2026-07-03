"""グループチャット UI のスタイル定義。"""

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
