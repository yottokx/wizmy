from src.ui.chat.commands import (
    command_suggestions,
    input_mode_icon,
    input_mode_label,
    parse_command_input,
    resolve_chat_command,
)


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


def test_parse_command_input_returns_current_values() -> None:
    assert parse_command_input("本文 /TaIlOr  ") == ("本文 ", "tailor")
    assert parse_command_input("/memo") == ("", "memo")
    assert parse_command_input("本文 /") == ("本文 ", "")
    assert parse_command_input("本文 /memo 続き") is None
    assert parse_command_input("本文だけ") is None


def test_command_suggestions_filter_by_prefix() -> None:
    assert [command.name for command in command_suggestions("ta")] == ["tailor"]
    assert [command.name for command in command_suggestions("D")] == ["describe"]
    assert command_suggestions("unknown") == []


def test_resolve_chat_command_returns_current_values_for_prefixes() -> None:
    assert resolve_chat_command("") is None
    assert resolve_chat_command("ta") == "tailor"
    assert resolve_chat_command("D") == "describe"
    assert resolve_chat_command("unknown") is None


def test_input_mode_labels_and_icons_return_current_values() -> None:
    assert input_mode_label("user") == "ユーザー"
    assert input_mode_label("narration") == "ナラティブ"
    assert input_mode_label("memo") == "コメント"
    assert input_mode_label("character") == "キャラクター"
    assert input_mode_label("unknown") == "ユーザー"

    assert input_mode_icon("user") == "person"
    assert input_mode_icon("narration") == "notes"
    assert input_mode_icon("memo") == "comment"
    assert input_mode_icon("character") == "face"
    assert input_mode_icon("unknown") == "person"
