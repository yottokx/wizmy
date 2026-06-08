"""
グループチャット UI モックアップ。

本実装前に画面構成を確認するため、静的なサンプルデータだけで表示する。
"""

from __future__ import annotations

from nicegui import ui

from ...app_context import get_context
from ..components.character_picker import open_character_picker
from ..chat.media import cropped_background_style
from ..chat.style import CHAT_CSS
from ..layout import page_layout


GROUP_CHAT_MOCK_CSS = """
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
.cs-group-section {
  min-width: 0;
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
.cs-group-card {
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
.cs-group-card-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.cs-group-card-title {
  min-width: 0;
  font-size: 1rem;
  font-weight: 800;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cs-group-card-meta {
  flex: 0 0 auto;
  font-size: 0.72rem;
  color: var(--cs-muted);
}
.cs-group-card-world {
  min-height: 44px;
  font-size: 0.82rem;
  line-height: 1.55;
  color: var(--cs-muted);
  overflow-wrap: anywhere;
}
.cs-group-avatar-stack {
  display: flex;
  align-items: center;
  min-height: 32px;
}
.cs-group-avatar-stack .cs-group-avatar {
  margin-right: -7px;
}
.cs-group-avatar {
  width: 34px;
  height: 34px;
  flex: 0 0 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--cs-border);
  border-radius: 999px;
  background: var(--cs-surface-soft);
  color: var(--cs-text);
  font-size: 0.72rem;
  font-weight: 800;
  overflow: hidden;
}
.cs-group-avatar-large {
  width: 44px;
  height: 44px;
  flex-basis: 44px;
  font-size: 0.82rem;
}
.cs-group-avatar-button {
  padding: 0;
  border: 0;
  background: transparent;
  cursor: pointer;
}
.cs-group-avatar-button .cs-group-avatar {
  transition: border-color 0.12s ease, box-shadow 0.12s ease, transform 0.12s ease;
}
.cs-group-avatar-button:hover .cs-group-avatar,
.cs-group-avatar-button.cs-group-avatar-selected .cs-group-avatar {
  border-color: var(--cs-accent);
  box-shadow: 0 0 0 3px var(--cs-accent-bg);
  transform: translateY(-1px);
}
.cs-group-recent-list {
  display: grid;
  gap: 8px;
}
.cs-group-recent-item {
  display: grid;
  gap: 4px;
  padding: 11px;
  border: 1px solid var(--cs-border);
  border-radius: 8px;
  background: var(--cs-surface);
}
.cs-group-recent-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.cs-group-recent-title {
  flex: 1;
  min-width: 0;
  font-size: 0.9rem;
  font-weight: 800;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cs-group-recent-time {
  flex: 0 0 auto;
  font-size: 0.72rem;
  color: var(--cs-muted);
}
.cs-group-recent-preview {
  font-size: 0.78rem;
  color: var(--cs-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cs-group-modal-section {
  display: grid;
  gap: 8px;
}
.cs-group-modal-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.cs-group-selected-list {
  display: grid;
  gap: 8px;
  width: 100%;
  max-height: 280px;
  overflow: auto;
  padding: 8px;
  border: 1px solid var(--cs-border);
  border-radius: 8px;
  background: var(--cs-surface-soft);
}
.cs-group-selected-row {
  display: grid;
  grid-template-columns: 48px minmax(0, 1fr) minmax(120px, 170px) 32px;
  gap: 10px;
  align-items: center;
  padding: 9px;
  border: 1px solid var(--cs-border);
  border-radius: 8px;
  background: var(--cs-surface);
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
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cs-group-persona-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(140px, 190px);
  gap: 10px;
  align-items: end;
  width: 100%;
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
  background:
    linear-gradient(180deg, rgba(20, 48, 53, 0.96), rgba(7, 18, 24, 0.98));
  color: #eef8f5;
}
.cs-group-profile-switch {
  display: grid;
  grid-template-columns: 1fr 1fr;
  border: 1px solid rgba(102, 197, 188, 0.25);
  border-radius: 8px 8px 0 0;
  overflow: hidden;
  background: rgba(2, 10, 17, 0.45);
}
.cs-group-profile-switch-item {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-height: 40px;
  color: rgba(238, 248, 245, 0.72);
  font-size: 0.83rem;
  font-weight: 800;
}
.cs-group-profile-switch-item-active {
  color: #6fd4cc;
  background: rgba(31, 115, 112, 0.22);
  border-bottom: 2px solid #56c7bd;
}
.cs-group-portrait {
  position: relative;
  width: 100%;
  aspect-ratio: 4 / 5;
  min-height: 0;
  border: 1px solid rgba(129, 205, 198, 0.3);
  border-radius: 8px;
  overflow: hidden;
  background-color: #dfeef8;
  background-size: cover;
  background-position: center;
}
.cs-group-portrait-status {
  position: absolute;
  top: 8px;
  left: 8px;
  padding: 4px 8px;
  border-radius: 7px;
  background: rgba(15, 92, 88, 0.86);
  color: #bff8ef;
  font-size: 0.72rem;
  font-weight: 800;
}
.cs-group-face-strip {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-top: -2px;
}
.cs-group-face-strip .cs-group-avatar {
  border-color: rgba(181, 231, 226, 0.5);
  box-shadow: 0 0 0 2px rgba(6, 18, 24, 0.72);
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
  border: 1px solid rgba(111, 212, 204, 0.48);
  border-radius: 999px;
  background: rgba(31, 115, 112, 0.22);
  color: #8fe2db;
  font-size: 0.75rem;
  font-weight: 800;
}
.cs-group-profile-edit {
  width: fit-content;
  margin: 0 auto;
  border-color: rgba(111, 212, 204, 0.42) !important;
  color: #9fe8df !important;
}
.cs-group-profile-card {
  display: grid;
  gap: 8px;
  padding: 10px;
  border: 1px solid rgba(129, 205, 198, 0.2);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.035);
}
.cs-group-profile-card-title {
  color: #6fd4cc;
  font-size: 0.78rem;
  font-weight: 800;
  letter-spacing: 0.02em;
}
.cs-group-profile-grid {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 7px 14px;
}
.cs-group-profile-label {
  color: rgba(238, 248, 245, 0.66);
  font-size: 0.76rem;
  font-weight: 700;
}
.cs-group-profile-value {
  color: #eef8f5;
  font-size: 0.8rem;
  overflow-wrap: anywhere;
}
.cs-group-profile-summary {
  color: #d8e8e4;
  font-size: 0.82rem;
  line-height: 1.62;
  overflow-wrap: anywhere;
}
.cs-group-message-row {
  display: flex;
  align-items: flex-end;
  gap: 9px;
  max-width: 82%;
}
.cs-group-message-row-user {
  align-self: flex-end;
  justify-content: flex-end;
}
.cs-group-message-row-character {
  align-self: flex-start;
}
.cs-group-message-row-narration {
  align-self: center;
  justify-content: center;
  max-width: min(720px, 92%);
}
.cs-group-message-row-user .cs-chat-bubble {
  background: var(--cs-accent);
  border-color: var(--cs-accent);
  color: #fff;
}
.cs-group-speaker {
  font-size: 0.74rem;
  font-weight: 800;
  color: var(--cs-accent);
}
.cs-group-message-row-user .cs-group-speaker,
.cs-group-message-row-user .cs-chat-message-time {
  color: rgba(255,255,255,0.78);
}
.cs-group-message-row-narration .cs-chat-bubble {
  width: 100%;
  background: var(--cs-surface-soft);
  border-style: dashed;
  border-color: var(--cs-accent-border);
  box-shadow: none;
}
@media (max-width: 1023px) {
  .cs-group-home-grid {
    grid-template-columns: 1fr;
  }
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
  .cs-group-page-head {
    flex-direction: column;
    align-items: stretch;
  }
  .cs-group-selected-row {
    grid-template-columns: 48px minmax(0, 1fr) 32px;
  }
  .cs-group-selected-row .q-field {
    grid-column: 1 / -1;
  }
  .cs-group-persona-row {
    grid-template-columns: 1fr;
  }
  .cs-group-message-row {
    max-width: 92%;
  }
}
</style>
"""


MOCK_CHARACTERS = [
    {
        "name": "ミナ",
        "handle": "Mina",
        "initial": "Mi",
        "color": "#e7c9d1",
        "portrait": "radial-gradient(circle at 50% 37%, #ffe3dc 0 18%, transparent 19%), radial-gradient(circle at 42% 38%, #6aa6ff 0 2.7%, transparent 3.4%), radial-gradient(circle at 58% 38%, #6aa6ff 0 2.7%, transparent 3.4%), radial-gradient(circle at 50% 30%, #f6a9c7 0 26%, transparent 27%), radial-gradient(circle at 32% 28%, #ffd1dd 0 18%, transparent 19%), linear-gradient(155deg, #bde6ff 0%, #f6d8ef 45%, #9f80e8 100%)",
        "role": "記録係",
        "age": "22歳",
        "gender": "女性",
        "origin": "風の都",
        "profile": "冷静に状況を整理し、会話の抜けや矛盾をやわらかく補う。細かな観察を短い言葉にまとめるのが得意。",
    },
    {
        "name": "ルイ",
        "handle": "Rui",
        "initial": "Ru",
        "color": "#c9d9e7",
        "portrait": "radial-gradient(circle at 50% 38%, #f2dfd6 0 17%, transparent 18%), radial-gradient(circle at 43% 38%, #7e9fc8 0 2.4%, transparent 3.2%), radial-gradient(circle at 57% 38%, #7e9fc8 0 2.4%, transparent 3.2%), radial-gradient(circle at 50% 28%, #bcc9d9 0 25%, transparent 26%), linear-gradient(150deg, #d8edf5 0%, #c5d2e6 50%, #7b95bb 100%)",
        "role": "交渉役",
        "age": "24歳",
        "gender": "男性",
        "origin": "旧市街",
        "profile": "軽口を交えながら空気を動かすムードメーカー。相手の本音を引き出す質問がうまい。",
    },
    {
        "name": "セラ",
        "handle": "Sera",
        "initial": "Se",
        "color": "#d9ddbd",
        "portrait": "radial-gradient(circle at 50% 38%, #ffe1ce 0 17%, transparent 18%), radial-gradient(circle at 43% 38%, #7ca0e8 0 2.5%, transparent 3.2%), radial-gradient(circle at 57% 38%, #7ca0e8 0 2.5%, transparent 3.2%), radial-gradient(circle at 50% 28%, #f0cc7e 0 25%, transparent 26%), linear-gradient(150deg, #f9e6a6 0%, #d8ddbd 48%, #99b986 100%)",
        "role": "分析役",
        "age": "21歳",
        "gender": "女性",
        "origin": "時計塔区",
        "profile": "仮説を立てて話を前へ進める参謀役。慎重だが、決めるべき場面では迷いを残さない。",
    },
]

MOCK_USER = {
    "name": "ユーザー",
    "handle": "Player",
    "initial": "Me",
    "color": "#d6cce6",
    "portrait": "radial-gradient(circle at 50% 38%, #eadbd8 0 17%, transparent 18%), radial-gradient(circle at 43% 38%, #8276b8 0 2.5%, transparent 3.2%), radial-gradient(circle at 57% 38%, #8276b8 0 2.5%, transparent 3.2%), radial-gradient(circle at 50% 28%, #b7a9dc 0 25%, transparent 26%), linear-gradient(150deg, #eee5f6 0%, #d6cce6 48%, #9c8fbe 100%)",
    "role": "進行役",
    "age": "",
    "gender": "",
    "origin": "",
    "profile": "グループの視点人物。メンバーへ質問し、必要に応じてシーンの方向を決める。",
}

MOCK_GROUPS = [
    {
        "title": "星灯りの作戦室",
        "world": "夜だけ開く古い図書館を拠点に、街で起きる小さな不可思議を調べるチーム。",
        "members": MOCK_CHARACTERS,
        "updated": "18:42",
        "chats": 8,
    },
    {
        "title": "放課後アトリエ",
        "world": "文化祭前の美術室。未完成の展示をめぐって、相談と寄り道が同じくらい起きる。",
        "members": MOCK_CHARACTERS[:2],
        "updated": "昨日",
        "chats": 3,
    },
    {
        "title": "蒸気街の案内所",
        "world": "蒸気機関の音が響く港町で、依頼人を迎えて事件の糸口を探す。",
        "members": MOCK_CHARACTERS[1:],
        "updated": "6/5",
        "chats": 5,
    },
]

MOCK_THREADS = [
    {
        "title": "消えた栞の件",
        "preview": "ミナ: 入口の貸出帳だけ、インクの乾き方が違います。",
        "time": "18:42",
        "active": True,
    },
    {
        "title": "閉架書庫の聞き込み",
        "preview": "ルイ: 司書さん、さっきから視線が同じ棚に戻ってる。",
        "time": "15:10",
        "active": False,
    },
    {
        "title": "初回ミーティング",
        "preview": "セラ: まず調査範囲を三つに分けましょう。",
        "time": "昨日",
        "active": False,
    },
]


@ui.page("/groups")
async def group_chat_page() -> None:
    with page_layout("グループチャット"):
        ui.add_head_html(GROUP_CHAT_MOCK_CSS)

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
                    on_click=open_new_group_dialog,
                ).props("color=primary unelevated").style("border-radius: 8px; font-weight: 700;")

            with ui.element("div").classes("cs-group-home-grid"):
                with ui.element("section").classes("cs-group-section"):
                    _render_section_head("groups", "グループ一覧")
                    with ui.element("div").classes("cs-group-card-grid"):
                        for group in MOCK_GROUPS:
                            _render_group_card(group)

                with ui.element("section").classes("cs-group-section"):
                    _render_section_head("forum", "最近のチャット")
                    with ui.element("div").classes("cs-group-recent-list"):
                        for thread in MOCK_THREADS:
                            _render_recent_item(thread)


@ui.page("/groups/demo")
async def group_chat_demo_page() -> None:
    selected = {"handle": MOCK_CHARACTERS[0]["handle"]}

    with page_layout("星灯りの作戦室"):
        ui.add_head_html(CHAT_CSS)
        ui.add_head_html(GROUP_CHAT_MOCK_CSS)

        def set_mobile_sidebar(open_: bool) -> None:
            action = "add" if open_ else "remove"
            ui.context.client.run_javascript(
                "document.querySelector('.cs-chat-shell')"
                f"?.classList.{action}('cs-mobile-sidebar-open');"
            )

        with ui.element("div").classes("cs-chat-shell cs-group-chat-shell"):
            ui.element("div").classes("cs-chat-mobile-backdrop").on(
                "click", lambda: set_mobile_sidebar(False)
            )

            with ui.element("aside").classes("cs-chat-mobile-sidebar cs-chat-panel"):
                with ui.row().classes("items-center justify-between px-3 py-2").style(
                    "border-bottom: 1px solid var(--cs-border);"
                ):
                    ui.label("グループ").classes("text-sm font-semibold")
                    ui.button(icon="close", on_click=lambda: set_mobile_sidebar(False)).props(
                        "flat round dense"
                    )
                with ui.element("div").classes("cs-chat-scroll"):
                    _render_group_profile_panel(MOCK_CHARACTERS[0], compact=True)
                    _render_group_history()

            with ui.element("aside").classes("cs-chat-profile-pane cs-chat-panel"):
                profile_container = ui.element("div")

                def refresh_profile() -> None:
                    current = _character_by_handle(selected["handle"])
                    profile_container.clear()
                    with profile_container:
                        _render_group_profile_panel(
                            current,
                            selected_handle=selected["handle"],
                            select_profile=select_profile,
                        )

                def select_profile(handle: str) -> None:
                    selected["handle"] = handle
                    refresh_profile()

                refresh_profile()

            with ui.element("aside").classes("cs-chat-side-pane cs-chat-panel"):
                with ui.element("div").classes("cs-chat-scroll"):
                    _render_group_profile_panel(MOCK_CHARACTERS[0], compact=True)
                    _render_group_history()

            with ui.element("aside").classes("cs-chat-history-pane cs-chat-panel"):
                _render_group_history()

            with ui.element("section").classes("cs-chat-main cs-chat-panel"):
                _render_group_chat_main(set_mobile_sidebar)


def open_new_group_dialog() -> None:
    ctx = get_context()
    handle_inputs = {}
    selected_entries = {"items": [_entry_from_mock(character) for character in MOCK_CHARACTERS]}

    with ui.dialog() as dlg, ui.card().classes("w-full max-w-3xl").style(
        "max-width: min(760px, 94vw);"
    ):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("新しいグループ").classes("text-lg font-semibold")
            ui.button(icon="close", on_click=dlg.close).props("flat round dense")

        with ui.scroll_area().style("max-height: 84vh; width: 100%;"):
            with ui.column().classes("w-full gap-3 pr-2"):
                ui.input(label="グループ名", value="星灯りの作戦室").props(
                    "outlined clearable"
                ).classes("w-full")

                with ui.element("div").classes("cs-group-modal-section"):
                    with ui.element("div").classes("cs-group-modal-actions"):
                        with ui.column().classes("gap-0"):
                            ui.label("グループに取り込むキャラクター").classes("text-sm font-semibold")
                            ui.label("選択したキャラクターは参照ではなく、グループ内コピーとして保持します。").classes(
                                "cs-group-note"
                            )

                        async def _open_picker() -> None:
                            async def _add_character(sheet) -> None:
                                selected_entries["items"].append(
                                    _entry_from_sheet(sheet, len(selected_entries["items"]) + 1)
                                )
                                _refresh_selected_list()

                            await open_character_picker(
                                ctx,
                                _add_character,
                                title="グループに取り込むキャラクターを選択",
                                empty_message="取り込めるキャラクターがありません",
                            )

                        ui.button(
                            "キャラクターを追加",
                            icon="person_search",
                            on_click=_open_picker,
                        ).props("color=primary unelevated").style("border-radius: 8px; font-weight: 700;")

                    selected_list = ui.element("div").classes("cs-group-selected-list")

                    def _refresh_selected_list() -> None:
                        selected_list.clear()
                        with selected_list:
                            for index, entry in enumerate(selected_entries["items"]):
                                _render_selected_character_row(
                                    ctx,
                                    entry,
                                    handle_inputs,
                                    remove=lambda idx=index: _remove_selected(idx),
                                )

                    def _remove_selected(index: int) -> None:
                        if 0 <= index < len(selected_entries["items"]):
                            selected_entries["items"].pop(index)
                            _refresh_selected_list()

                    _refresh_selected_list()

                ui.separator()

                with ui.element("div").classes("cs-group-modal-section"):
                    ui.label("ユーザーペルソナ").classes("text-sm font-semibold")
                    with ui.element("div").classes("cs-group-persona-row"):
                        ui.select(
                            options={"persona": "探索者ペルソナ", "character": "キャラクターをユーザー役にする"},
                            value="persona",
                            label="ユーザーペルソナ",
                        ).props("outlined dense").classes("w-full")
                        handle_inputs[MOCK_USER["handle"]] = ui.input(
                            label="ユーザーのハンドル",
                            value=MOCK_USER["handle"],
                        ).props("outlined dense mask=\"NNNNNNNNNNNN\"").classes("w-full")

                ui.button(
                    "一括で自動生成",
                    icon="auto_fix_high",
                    on_click=lambda: _fill_mock_handles(handle_inputs),
                ).props("flat color=primary").classes("w-fit")

                with ui.element("div").classes("cs-group-world-field"):
                    world_input = ui.textarea(
                        label="世界観",
                        value="夜だけ開く古い図書館を拠点に、街で起きる小さな不可思議を調べるチーム。",
                    ).props("outlined rows=5").classes("w-full")
                    ui.button(
                        icon="auto_awesome",
                        on_click=lambda: _enhance_mock_world(world_input),
                    ).props("flat round dense size=sm").classes("cs-group-world-enhance").tooltip(
                        "世界観を補完"
                    )

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button(
                "作成",
                icon="save",
                on_click=lambda: _close_mock_dialog(dlg, "グループ作成UIを確認しました"),
            ).props("color=primary unelevated")

    dlg.open()


def open_new_group_chat_dialog() -> None:
    with ui.dialog() as dlg, ui.card().classes("w-full max-w-2xl"):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("新しいチャット").classes("text-lg font-semibold")
            ui.button(icon="close", on_click=dlg.close).props("flat round dense")
        ui.select(
            options={
                "creative": "創作メイン [local / creative-model]",
                "balanced": "会話バランス [local / balanced-model]",
            },
            value="creative",
            label="LLMプロファイル",
        ).props("outlined dense").classes("w-full")
        ui.input(label="タイトル（任意）", placeholder="未入力なら自動タイトル").props(
            "outlined clearable"
        ).classes("w-full")
        ui.select(
            options={
                "group_roleplay": "グループロールプレイ",
                "round_robin": "順番に発言",
                "facilitated": "進行役あり",
            },
            value="group_roleplay",
            label="チャットモード",
        ).props("outlined dense").classes("w-full")
        ui.textarea(
            label="シチュエーション",
            value="閉館後の図書館。貸出帳から一枚だけ破られたページの行方を、全員で推理する。",
        ).props("outlined rows=4").classes("w-full")
        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("キャンセル", on_click=dlg.close).props("flat")
            ui.button(
                "開始",
                icon="chat",
                on_click=lambda: _close_mock_dialog(dlg, "新しいチャットUIを確認しました"),
            ).props("color=primary unelevated")
    dlg.open()


def _render_section_head(icon: str, title: str) -> None:
    with ui.element("div").classes("cs-group-section-head"):
        ui.icon(icon)
        ui.label(title).classes("cs-group-section-title")


def _render_group_card(group: dict) -> None:
    with ui.element("div").classes("cs-group-card"):
        with ui.element("div").classes("cs-group-card-title-row"):
            ui.label(group["title"]).classes("cs-group-card-title")
            ui.label(f"{group['chats']}件").classes("cs-group-card-meta")
        ui.label(group["world"]).classes("cs-group-card-world")
        with ui.row().classes("items-center justify-between gap-2"):
            with ui.element("div").classes("cs-group-avatar-stack"):
                for character in group["members"]:
                    _render_avatar(character)
                _render_avatar(MOCK_USER)
            ui.button(
                "開く",
                icon="open_in_new",
                on_click=lambda: ui.navigate.to("/groups/demo"),
            ).props("flat color=primary dense")
        ui.label(f"更新: {group['updated']}").classes("text-xs text-grey-6")


def _render_recent_item(thread: dict) -> None:
    with ui.element("div").classes("cs-group-recent-item"):
        with ui.element("div").classes("cs-group-recent-title-row"):
            ui.label(thread["title"]).classes("cs-group-recent-title")
            ui.label(thread["time"]).classes("cs-group-recent-time")
        ui.label(thread["preview"]).classes("cs-group-recent-preview")


def _render_group_profile_panel(
    current: dict,
    *,
    selected_handle: str = "",
    select_profile=None,
    compact: bool = False,
) -> None:
    classes = "cs-group-profile-shell"
    if compact:
        classes += " cs-group-profile-compact"
    with ui.element("div").classes(classes):
        with ui.element("div").classes("cs-group-profile-switch"):
            with ui.element("div").classes("cs-group-profile-switch-item cs-group-profile-switch-item-active"):
                ui.icon("groups").classes("text-sm")
                ui.label("プロフィール")
            with ui.element("div").classes("cs-group-profile-switch-item"):
                ui.icon("menu_book").classes("text-sm")
                ui.label("世界観")

        with ui.element("div").classes("cs-group-portrait").style(
            f"background-image: {current['portrait']};"
        ):
            ui.label("フォーカス中").classes("cs-group-portrait-status")

        with ui.element("div").classes("cs-group-face-strip"):
            for character in MOCK_CHARACTERS:
                classes = "cs-group-avatar-button"
                if character["handle"] == (selected_handle or current["handle"]):
                    classes += " cs-group-avatar-selected"
                button = ui.element("button").props("type=button").classes(classes)
                if select_profile is not None:
                    button.on("click", lambda _, handle=character["handle"]: select_profile(handle))
                with button:
                    _render_avatar(character, large=True)

        ui.label(f"{current['name']}").classes("cs-group-profile-name")
        with ui.element("div").classes("cs-group-handle"):
            ui.icon("alternate_email").classes("text-sm")
            ui.label(current["handle"])
        ui.button("プロフィールを編集", icon="edit").props("outline dense").classes(
            "cs-group-profile-edit"
        )

        with ui.element("div").classes("cs-group-profile-card"):
            ui.label("キャラクター概要").classes("cs-group-profile-card-title")
            with ui.element("div").classes("cs-group-profile-grid"):
                for label, value in (
                    ("年齢", current.get("age") or "未設定"),
                    ("性別", current.get("gender") or "未設定"),
                    ("職業・役割", current.get("role") or "未設定"),
                    ("出身・所属", current.get("origin") or "未設定"),
                ):
                    ui.label(label).classes("cs-group-profile-label")
                    ui.label(value).classes("cs-group-profile-value")
            ui.label("世界観").classes("cs-group-profile-card-title")
            ui.label(
                "夜だけ開く古い図書館を拠点に、街で起きる小さな不可思議を調べるチーム。"
            ).classes("cs-group-profile-summary")
            ui.label("人物像").classes("cs-group-profile-card-title")
            ui.label(current["profile"]).classes("cs-group-profile-summary")


def _entry_from_mock(character: dict) -> dict:
    return {
        "key": f"mock-{character['handle']}",
        "name": character["name"],
        "handle": character["handle"],
        "meta": character["role"],
        "portrait": character["portrait"],
        "initial": character["initial"],
        "sheet": None,
    }


def _entry_from_sheet(sheet, index: int) -> dict:
    return {
        "key": f"sheet-{getattr(sheet, 'id', index)}",
        "name": getattr(sheet, "name", "") or "キャラクター",
        "handle": f"Char{index}",
        "meta": "選択済みキャラクター",
        "portrait": "",
        "initial": "Ch",
        "sheet": sheet,
    }


def _render_selected_character_row(ctx, entry: dict, handle_inputs: dict, *, remove) -> None:
    with ui.element("div").classes("cs-group-selected-row"):
        _render_entry_face(ctx, entry)
        with ui.column().classes("gap-0 min-w-0"):
            ui.label(entry["name"]).classes("cs-group-selected-name")
            ui.label(entry["meta"]).classes("cs-group-selected-meta")
        handle_inputs[entry["handle"]] = ui.input(
            label="ハンドル",
            value=entry["handle"],
        ).props("outlined dense mask=\"NNNNNNNNNNNN\"").classes("w-full")
        ui.button(icon="close", on_click=remove).props("flat round dense").tooltip("リストから外す")


def _render_entry_face(ctx, entry: dict) -> None:
    style = ""
    sheet = entry.get("sheet")
    if sheet is not None:
        image = sheet.media.primary_image()
        image_path = ctx.characters.media_path(image.path) if image else None
        if image and image_path:
            style = cropped_background_style(image, image_path, image.face_rect, 1.0)
    elif entry.get("portrait"):
        style = f"background-image: {entry['portrait']}; background-size: cover; background-position: center;"

    with ui.element("div").classes("cs-group-selected-face").style(style):
        if not style:
            ui.label(entry.get("initial") or "Ch")


def _render_group_history() -> None:
    with ui.element("div").classes("cs-chat-history-head"):
        ui.icon("history").style("color: var(--cs-accent);")
        ui.label("チャット履歴").classes("cs-chat-history-title")
        ui.space()
        ui.button(icon="add", on_click=open_new_group_chat_dialog).props("flat round dense").tooltip(
            "新しいチャット"
        )
    with ui.element("div").classes("cs-chat-scroll"):
        with ui.element("div").classes("cs-chat-thread-list"):
            for thread in MOCK_THREADS:
                classes = "cs-chat-thread"
                if thread["active"]:
                    classes += " cs-chat-thread-active"
                with ui.element("div").classes(classes):
                    with ui.element("button").props("type=button").classes("cs-chat-thread-open"):
                        with ui.element("div").classes("cs-chat-thread-title-row"):
                            ui.label(thread["title"]).classes("cs-chat-thread-title")
                            ui.label(thread["time"]).classes("cs-chat-thread-time")
                        ui.label(thread["preview"]).classes("cs-chat-thread-preview")
                    with ui.element("div").classes("cs-chat-thread-actions"):
                        ui.button(icon="edit").props("flat round dense size=sm").classes(
                            "cs-chat-thread-action"
                        ).tooltip("タイトル変更")
                        ui.button(icon="delete").props("flat round dense size=sm color=negative").classes(
                            "cs-chat-thread-action"
                        ).tooltip("チャット削除")


def _render_group_chat_main(set_mobile_sidebar) -> None:
    with ui.element("div").classes("cs-chat-main-head"):
        ui.button(icon="menu", on_click=lambda: set_mobile_sidebar(True)).props(
            "flat round dense"
        ).classes("cs-chat-mobile-toggle")
        with ui.column().classes("gap-0 cs-chat-main-title"):
            ui.label("消えた栞の件").classes("text-base font-bold")
            ui.label("星灯りの作戦室 / グループロールプレイ / 創作メイン").classes(
                "text-xs text-grey-6"
            )
        with ui.row().classes("items-center gap-1"):
            ui.button(icon="article").props("flat round dense").tooltip("システムプロンプト")
            ui.button(icon="edit").props("flat round dense").tooltip("タイトル変更")
            ui.button(icon="delete").props("flat round dense color=negative").tooltip("チャット削除")
            ui.button(icon="add", on_click=open_new_group_chat_dialog).props("flat round dense").tooltip(
                "新しいチャット"
            )

    with ui.element("div").classes("cs-chat-messages"):
        _render_group_message("narration", "Narrator", "", "閉館後の図書館。貸出帳から一枚だけ破られたページの行方を、全員で推理する。")
        _render_group_message("character", "Mina", "ミナ", "入口の貸出帳だけ、インクの乾き方が違います。ページを破った人は、直前に何かを書き足したのかも。")
        _render_group_message("character", "Rui", "ルイ", "じゃあ、犯人は慌てて隠したってより、誰かに読ませたくなかった感じかな。")
        _render_group_message("user", "Player", "あなた", "@Sera この場合、まず何を照合する？")
        _render_group_message("character", "Sera", "セラ", "貸出帳、書架の入退室記録、そして栞が挟まれていた本の三つです。順番に崩せば、意図が見えます。")

    with ui.element("div").classes("cs-chat-composer-shell"):
        with ui.element("div").classes("cs-chat-composer"):
            _render_group_input_role_selector()
            ui.textarea(placeholder="メッセージを入力").props("outlined dense rows=1 autogrow").classes(
                "cs-chat-composer-input"
            )
            ui.button(icon="send").props("round color=primary unelevated")


def _render_group_message(kind: str, handle: str, speaker: str, text: str) -> None:
    row_class = {
        "user": "cs-group-message-row-user",
        "narration": "cs-group-message-row-narration",
    }.get(kind, "cs-group-message-row-character")
    with ui.element("div").classes(f"cs-group-message-row {row_class}"):
        character = _character_by_handle(handle)
        if kind == "character":
            _render_avatar(character)
        with ui.element("div").classes("cs-chat-bubble"):
            if speaker:
                ui.label(f"{speaker} / @{handle}").classes("cs-group-speaker")
            ui.label(text).classes("cs-chat-message-text")
            with ui.element("div").classes("cs-chat-message-meta"):
                ui.label("18:42").classes("cs-chat-message-time")
        if kind == "user":
            _render_avatar(MOCK_USER)


def _render_group_input_role_selector() -> None:
    with ui.button().props("flat dense unelevated aria-label=入力ロールを変更").classes(
        "cs-chat-mode-icon"
    ):
        with ui.element("div").classes("cs-chat-mode-icon-display"):
            ui.icon("person")
        with ui.menu().classes("cs-chat-mode-menu"):
            ui.menu_item("ユーザー")
            ui.menu_item("キャラクター")
            ui.menu_item("ナラティブ")
            ui.menu_item("コメント")


def _render_avatar(character: dict, *, large: bool = False) -> None:
    classes = "cs-group-avatar"
    if large:
        classes += " cs-group-avatar-large"
    portrait = character.get("portrait", "")
    with ui.element("div").classes(classes).style(
        f"background-color: {character['color']}; "
        f"background-image: {portrait}; "
        "background-size: cover; background-position: center;"
    ):
        if not portrait:
            ui.label(character["initial"])


def _character_by_handle(handle: str) -> dict:
    if handle == MOCK_USER["handle"]:
        return MOCK_USER
    for character in MOCK_CHARACTERS:
        if character["handle"] == handle:
            return character
    return MOCK_CHARACTERS[0]


def _fill_mock_handles(handle_inputs: dict) -> None:
    for handle, input_ in handle_inputs.items():
        input_.set_value(handle)
    ui.notify("英数字ハンドルを一括生成しました", type="positive")


def _enhance_mock_world(world_input) -> None:
    current = (world_input.value or "").strip()
    addition = "各メンバーは別々の得意分野を持ち、調査中はメンションで発言先を指定できる。"
    if addition not in current:
        world_input.set_value(f"{current}\n{addition}".strip())
    ui.notify("世界観を補完しました", type="positive")


def _close_mock_dialog(dlg, message: str) -> None:
    dlg.close()
    ui.notify(message, type="positive")
