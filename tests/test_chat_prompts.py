from src.ui.chat.models import ChatMessagePreview
from src.ui.chat.prompts import (
    build_llm_messages,
    build_response_choice_messages,
    build_tailored_input_messages,
    build_user_completion_messages,
    chat_history_for_prompt,
)
from tests.chat_test_helpers import make_chat_settings as make_settings
from tests.chat_test_helpers import make_chat_sheet as make_sheet


def test_memo_messages_are_not_in_chat_history_prompt() -> None:
    messages = [
        ChatMessagePreview("user", "これは発言です", "12:00"),
        ChatMessagePreview("memo", "これはコメントです", "12:01"),
        ChatMessagePreview("narration", "これは地の文です", "12:02"),
    ]

    history = chat_history_for_prompt(messages)

    assert "これは発言です" in history
    assert "これは地の文です" in history
    assert "これはコメントです" not in history


def test_only_memo_history_is_empty_for_prompt() -> None:
    history = chat_history_for_prompt([
        ChatMessagePreview("memo", "LLMに渡さないコメント", "12:00"),
    ])

    assert history == "（まだ会話はありません）"


def test_memo_messages_are_not_in_character_llm_messages() -> None:
    sheet = make_sheet()
    settings = make_settings()
    messages = [
        ChatMessagePreview("user", "LLMに渡す発言", "12:00"),
        ChatMessagePreview("memo", "LLMに渡さないコメント", "12:01"),
        ChatMessagePreview("character", "LLMに渡す返答", "12:02"),
    ]

    llm_messages = build_llm_messages(sheet, settings, messages)
    joined_content = "\n".join(str(message.content) for message in llm_messages)

    assert "LLMに渡す発言" in joined_content
    assert "LLMに渡す返答" in joined_content
    assert "LLMに渡さないコメント" not in joined_content


def test_character_mode_completion_prompt_targets_character() -> None:
    llm_messages = build_user_completion_messages(
        make_sheet(),
        make_settings(),
        [ChatMessagePreview("user", "少し聞いてもいい？", "12:00")],
        "もちろん",
        input_mode="character",
    )
    joined_content = "\n".join(str(message.content) for message in llm_messages)

    assert "キャラクター発言の続きを補完" in joined_content
    assert "キャラクター（テストキャラ）" in joined_content
    assert "キャラクター概要" in joined_content
    assert "もちろん" in joined_content


def test_character_mode_choice_prompt_targets_character() -> None:
    llm_messages = build_response_choice_messages(
        make_sheet(),
        make_settings(),
        [ChatMessagePreview("user", "どうする？", "12:00")],
        "",
        input_mode="character",
    )
    joined_content = "\n".join(str(message.content) for message in llm_messages)

    assert "キャラクター発言候補" in joined_content
    assert "キャラクター（テストキャラ）" in joined_content
    assert "キャラクター概要" in joined_content


def test_character_mode_tailor_prompt_targets_character() -> None:
    llm_messages = build_tailored_input_messages(
        make_sheet(),
        make_settings(),
        [ChatMessagePreview("user", "どうする？", "12:00")],
        "いくよ",
        input_mode="character",
    )
    joined_content = "\n".join(str(message.content) for message in llm_messages)

    assert "キャラクター本人のセリフ" in joined_content
    assert "キャラクター（テストキャラ）" in joined_content
    assert "キャラクター概要" in joined_content
    assert "いくよ" in joined_content


def test_memo_mode_tailor_prompt_targets_comment() -> None:
    llm_messages = build_tailored_input_messages(
        make_sheet(),
        make_settings(),
        [ChatMessagePreview("memo", "LLMに渡さないコメント", "12:00")],
        "ここはあとで直す",
        input_mode="memo",
    )
    joined_content = "\n".join(str(message.content) for message in llm_messages)

    assert "コメント" in joined_content
    assert "作者向けの短いメモ" in joined_content
    assert "ここはあとで直す" in joined_content
    assert "LLMに渡さないコメント" not in joined_content
