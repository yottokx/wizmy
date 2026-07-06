from __future__ import annotations

from src.core.conversation.schemas import ChatMessagePreview
from src.ui.chat import controller as controller_module
from src.ui.chat.controller import ChatPageController
from tests.chat_test_helpers import make_chat_settings, make_chat_sheet


async def test_send_user_turn_keeps_input_state_when_session_is_missing(monkeypatch) -> None:
    controller = ChatPageController(object(), make_chat_sheet(), None)
    controller.state.settings = make_chat_settings()
    controller.state.messages = [ChatMessagePreview("character", "先の発言", "22:00")]

    calls: list[str] = []
    monkeypatch.setattr(controller_module.ui, "notify", lambda *args, **kwargs: calls.append("notify"))
    monkeypatch.setattr(controller, "open_new_chat_dialog", lambda: calls.append("open_dialog"))
    monkeypatch.setattr(controller, "clear_input", lambda: calls.append("clear_input"))
    monkeypatch.setattr(controller, "configured_llm", lambda settings: calls.append("configured_llm"))

    await controller.send_user_turn("消えない発言")

    assert [message.text for message in controller.state.messages] == ["先の発言"]
    assert calls == ["notify", "open_dialog"]
