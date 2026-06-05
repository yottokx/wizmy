from src.ui.chat.commands import command_suggestions, resolve_chat_command


def test_chat_commands_use_new_names() -> None:
    names = [command.name for command in command_suggestions("")]

    assert "guide" in names
    assert "describe" in names
    assert "memo" in names
    assert "imitate" in names
    assert "tailor" in names
    assert "direct" not in names
    assert "scene" not in names
    assert "transit" not in names


def test_removed_chat_commands_do_not_resolve() -> None:
    assert resolve_chat_command("direct") is None
    assert resolve_chat_command("scene") is None
    assert resolve_chat_command("transit") is None


def test_new_chat_commands_resolve() -> None:
    assert resolve_chat_command("guide") == "guide"
    assert resolve_chat_command("describe") == "describe"
    assert resolve_chat_command("memo") == "memo"
    assert resolve_chat_command("imitate") == "imitate"
    assert resolve_chat_command("tailor") == "tailor"
