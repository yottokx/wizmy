"""Prompt builders and LLM response cleanup for character chat."""

from __future__ import annotations

import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ...core.character.schemas import CharacterSheet
from .commands import clean_short_llm_text
from .models import ChatDebugInfo, ChatMessagePreview, ChatSessionSettings


def build_llm_messages(
    sheet: CharacterSheet,
    settings: ChatSessionSettings,
    messages: list[ChatMessagePreview],
    *,
    first_turn: bool = False,
    turn_instruction: str = "",
) -> list:
    system_prompt = build_system_prompt(sheet, settings)
    result: list = [SystemMessage(content=system_prompt)]
    for message in messages:
        if message.speaker == "user":
            result.append(HumanMessage(content=f"{settings.user_persona_name}: {message.text}"))
        elif message.speaker == "narration":
            result.append(HumanMessage(content=f"地の文: {message.text}"))
        elif message.speaker == "character":
            result.append(AIMessage(content=message.text))
    if first_turn:
        result.append(
            HumanMessage(
                content=(
                    f"{settings.user_persona_name}はまだ話していません。"
                    f"「{sheet.name}」として、自然な第一声をセリフだけで短く返してください。"
                )
            )
        )
    if turn_instruction.strip():
        result.append(
            HumanMessage(
                content=(
                    "次の返答だけに適用するメタ指示です。"
                    "この指示を作中で説明せず、返答本文にだけ反映してください。\n"
                    f"{turn_instruction.strip()}"
                )
            )
        )
    return result


def build_narration_llm_messages(
    sheet: CharacterSheet,
    settings: ChatSessionSettings,
    messages: list[ChatMessagePreview],
    *,
    instruction: str = "",
) -> list:
    instruction_line = instruction.strip() or "現在の会話を受けて、次に自然につながる地の文を書く。"
    return [
        SystemMessage(
            content=(
                "あなたはキャラクターチャットの地の文を書くナレーターです。\n"
                "セリフ、話者名、箇条書き、解説、メタ発言は出力しないでください。\n"
                "1〜3文で、場面・空気・動きだけを簡潔に描写してください。"
            )
        ),
        HumanMessage(
            content=(
                f"チャットモード: {settings.chat_mode_name}\n"
                f"前提: {settings.chat_premise}\n"
                f"ユーザーペルソナ: {settings.user_persona_name}\n"
                f"{settings.user_persona_description}\n\n"
                f"キャラクター概要:\n{character_summary(sheet)}\n\n"
                f"これまでの会話:\n{chat_history_for_prompt(messages)}\n\n"
                f"指示: {instruction_line}\n"
                "出力は地の文だけ。"
            )
        ),
    ]


def build_user_completion_messages(
    sheet: CharacterSheet,
    settings: ChatSessionSettings,
    messages: list[ChatMessagePreview],
    left_text: str,
    *,
    input_mode: str = "user",
) -> list:
    target_label, system_instruction = input_target_prompt(input_mode, settings, sheet)
    character_context = character_prompt_context(sheet) if input_mode == "character" else ""
    return [
        SystemMessage(
            content=system_instruction
        ),
        HumanMessage(
            content=(
                f"現在話そうとしているもの: {target_label}\n"
                f"ユーザーペルソナ名: {settings.user_persona_name}\n"
                f"ユーザーペルソナ設定:\n{settings.user_persona_description}\n\n"
                f"キャラクター名: {sheet.name}\n"
                f"{character_context}"
                f"会話履歴:\n{chat_history_for_prompt(messages)}\n\n"
                f"未完の文:\n{left_text.rstrip()}\n\n"
                "未完の文の続きを出力してください。前置き、引用符、元の文の繰り返しは禁止です。"
            )
        ),
    ]


def build_response_choice_messages(
    sheet: CharacterSheet,
    settings: ChatSessionSettings,
    messages: list[ChatMessagePreview],
    left_text: str,
    *,
    input_mode: str = "user",
) -> list:
    prefix = left_text.strip()
    prefix_line = f"各候補は次の書き出しに自然につなげる: {prefix}" if prefix else "各候補は独立した短い返答にする。"
    target_label, system_instruction = input_target_choice_prompt(input_mode, settings, sheet)
    character_context = character_prompt_context(sheet) if input_mode == "character" else ""
    return [
        SystemMessage(
            content=system_instruction
        ),
        HumanMessage(
            content=(
                f"現在話そうとしているもの: {target_label}\n"
                f"ユーザーペルソナ名: {settings.user_persona_name}\n"
                f"ユーザーペルソナ設定:\n{settings.user_persona_description}\n\n"
                f"キャラクター名: {sheet.name}\n"
                f"{character_context}"
                f"会話履歴:\n{chat_history_for_prompt(messages)}\n\n"
                f"{prefix_line}\n"
                "出力は3行だけ。番号や箇条書き記号は付けず、候補本文だけを書いてください。"
            )
        ),
    ]


def build_tailored_input_messages(
    sheet: CharacterSheet,
    settings: ChatSessionSettings,
    messages: list[ChatMessagePreview],
    text: str,
    *,
    input_mode: str = "user",
) -> list:
    target_label, system_instruction = input_target_tailor_prompt(input_mode, settings, sheet)
    character_context = character_prompt_context(sheet) if input_mode == "character" else ""
    return [
        SystemMessage(
            content=system_instruction
        ),
        HumanMessage(
            content=(
                f"現在の入力ロール: {target_label}\n"
                f"チャットモード: {settings.chat_mode_name}\n"
                f"チャット前提: {settings.chat_premise}\n"
                f"ユーザーペルソナ名: {settings.user_persona_name}\n"
                f"ユーザーペルソナ設定:\n{settings.user_persona_description}\n\n"
                f"キャラクター名: {sheet.name}\n"
                f"{character_context}"
                f"会話履歴:\n{chat_history_for_prompt(messages)}\n\n"
                f"書き換える文:\n{text.strip()}\n\n"
                "現在の入力ロールに合う自然な本文へ書き換えてください。"
                "出力は書き換え後の本文だけ。前置き、引用符、話者名、解説は禁止です。"
            )
        ),
    ]


def build_chat_title_messages(
    sheet: CharacterSheet,
    settings: ChatSessionSettings,
    messages: list[ChatMessagePreview],
) -> list:
    return [
        SystemMessage(
            content=(
                "あなたはキャラクターチャット履歴に短いタイトルを付ける編集者です。"
                "出力はタイトル本文だけにしてください。引用符、句点、解説、前置きは禁止です。"
                "12〜24文字程度で、会話の中心が分かる自然な日本語にしてください。"
            )
        ),
        HumanMessage(
            content=(
                f"キャラクター名: {sheet.name or 'キャラクター'}\n"
                f"チャットモード: {settings.chat_mode_name}\n"
                f"前提: {settings.chat_premise}\n"
                f"ユーザーペルソナ: {settings.user_persona_name}\n\n"
                f"キャラクター概要:\n{character_summary(sheet)}\n\n"
                f"会話履歴:\n{chat_history_for_prompt(messages)}"
            )
        ),
    ]


def input_target_prompt(
    input_mode: str,
    settings: ChatSessionSettings,
    sheet: CharacterSheet,
) -> tuple[str, str]:
    if input_mode == "narration":
        return (
            "地の文",
            (
                "あなたはキャラクターチャットの地の文の続きを補完する編集者です。"
                "セリフではなく、状況描写として自然につながる続きだけを短く出力してください。"
            ),
        )
    if input_mode == "character":
        return (
            f"キャラクター（{sheet.name}）",
            (
                "あなたはキャラクター発言の続きを補完する編集者です。"
                "キャラクターシート、チャット前提、会話履歴に合う本人のセリフとして、"
                "自然につながる続きだけを短く出力してください。"
            ),
        )
    return (
        f"ユーザー（{settings.user_persona_name}）",
        (
            "あなたはユーザー発言の続きを補完する編集者です。"
            "ユーザー本人の口調として自然につながる続きだけを短く出力してください。"
        ),
    )


def input_target_choice_prompt(
    input_mode: str,
    settings: ChatSessionSettings,
    sheet: CharacterSheet,
) -> tuple[str, str]:
    if input_mode == "narration":
        return (
            "地の文",
            (
                "あなたはキャラクターチャットでユーザーが選べる地の文候補を作る編集者です。"
                "セリフではなく、状況描写として自然な候補を3つだけ作ってください。"
            ),
        )
    if input_mode == "character":
        return (
            f"キャラクター（{sheet.name}）",
            (
                "あなたはキャラクターチャットでユーザーが選べるキャラクター発言候補を作る編集者です。"
                "キャラクターシート、チャット前提、会話履歴に合う本人のセリフを3つだけ作ってください。"
            ),
        )
    return (
        f"ユーザー（{settings.user_persona_name}）",
        (
            "あなたはキャラクターチャットでユーザーが選べる返答候補を作る編集者です。"
            "ユーザーペルソナに合う自然な返答を3つだけ作ってください。"
        ),
    )


def input_target_tailor_prompt(
    input_mode: str,
    settings: ChatSessionSettings,
    sheet: CharacterSheet,
) -> tuple[str, str]:
    if input_mode == "narration":
        return (
            "地の文",
            (
                "あなたは入力文をキャラクターチャットの地の文へ整える編集者です。"
                "セリフではなく、状況描写として自然な本文に書き換えてください。"
            ),
        )
    if input_mode == "character":
        return (
            f"キャラクター（{sheet.name}）",
            (
                "あなたは入力文をキャラクター本人のセリフへ整える編集者です。"
                "キャラクターシート、チャット前提、会話履歴に合う口調で書き換えてください。"
            ),
        )
    if input_mode == "memo":
        return (
            "コメント",
            (
                "あなたはチャットログ上に残すコメントを整える編集者です。"
                "会話本文ではなく、作者向けの短いメモとして自然な本文に書き換えてください。"
            ),
        )
    return (
        f"ユーザー（{settings.user_persona_name}）",
        (
            "あなたは入力文をユーザー発言へ整える編集者です。"
            "ユーザーペルソナに合う口調で、相手に投げかける自然な本文に書き換えてください。"
        ),
    )


def chat_history_for_prompt(messages: list[ChatMessagePreview]) -> str:
    visible_messages = [message for message in messages if message.speaker in {"user", "character", "narration"}]
    if not visible_messages:
        return "（まだ会話はありません）"
    lines: list[str] = []
    for message in visible_messages[-16:]:
        if message.speaker == "user":
            label = "ユーザー"
        elif message.speaker == "character":
            label = "キャラクター"
        elif message.speaker == "narration":
            label = "地の文"
        else:
            continue
        lines.append(f"{label}: {message.text}")
    return "\n".join(lines)


def is_first_character_turn(messages: list[ChatMessagePreview]) -> bool:
    return not any(message.speaker in {"user", "character"} for message in messages)


def format_llm_input(messages: list, settings: ChatSessionSettings | None = None) -> str:
    parts: list[str] = []
    for message in messages:
        role = getattr(message, "type", message.__class__.__name__)
        content = message_content_to_text(getattr(message, "content", message))
        parts.append(f"--- {role} ---\n{content}")
    return "\n\n".join(parts)


def build_debug_info(llm_input: str, raw_output: str, response) -> ChatDebugInfo:
    input_tokens, output_tokens, total_tokens = extract_token_usage(response)
    return ChatDebugInfo(
        llm_input=llm_input,
        raw_output=raw_output,
        reasoning_output=extract_reasoning_output(response),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


def extract_token_usage(response) -> tuple[int | None, int | None, int | None]:
    candidates: list[dict] = []
    usage_metadata = getattr(response, "usage_metadata", None)
    if isinstance(usage_metadata, dict):
        candidates.append(usage_metadata)

    response_metadata = getattr(response, "response_metadata", None)
    if isinstance(response_metadata, dict):
        for key in ("token_usage", "usage"):
            value = response_metadata.get(key)
            if isinstance(value, dict):
                candidates.append(value)
        candidates.append(response_metadata)

    for usage in candidates:
        input_tokens = first_int(
            usage,
            "input_tokens",
            "prompt_tokens",
            "prompt_eval_count",
        )
        output_tokens = first_int(
            usage,
            "output_tokens",
            "completion_tokens",
            "eval_count",
        )
        total_tokens = first_int(usage, "total_tokens")
        if total_tokens is None and (input_tokens is not None or output_tokens is not None):
            total_tokens = (input_tokens or 0) + (output_tokens or 0)
        if input_tokens is not None or output_tokens is not None or total_tokens is not None:
            return input_tokens, output_tokens, total_tokens
    return None, None, None


def extract_reasoning_output(response) -> str:
    candidates: list[Any] = []
    additional_kwargs = getattr(response, "additional_kwargs", None)
    if isinstance(additional_kwargs, dict):
        candidates.extend(
            additional_kwargs.get(key)
            for key in ("reasoning_content", "thinking")
        )

    response_metadata = getattr(response, "response_metadata", None)
    if isinstance(response_metadata, dict):
        message = response_metadata.get("message")
        if isinstance(message, dict):
            candidates.extend(
                message.get(key)
                for key in ("thinking", "reasoning_content")
            )
        candidates.extend(
            response_metadata.get(key)
            for key in ("thinking", "reasoning_content")
        )

    for candidate in candidates:
        text = message_content_to_text(candidate).strip() if candidate else ""
        if text:
            return text
    return ""


def first_int(values: dict, *keys: str) -> int | None:
    for key in keys:
        value = values.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
    return None


def build_system_prompt(sheet: CharacterSheet, settings: ChatSessionSettings) -> str:
    character_sheet = sheet.raw_markdown or character_summary(sheet)
    return f"""あなたは「{sheet.name}」としてユーザーと会話します。

チャットモード: {settings.chat_mode_name}
このチャットの前提: {settings.chat_premise}

ユーザーペルソナ名: {settings.user_persona_name}
ユーザーペルソナ設定:
{settings.user_persona_description}

キャラクターシート:
{character_sheet}

会話ルール:
- 返答は「{sheet.name}」本人のセリフだけにする。
- 地の文、情景描写、心理描写、ト書き、括弧書きの動作説明を出力しない。
- 「{sheet.name}:」のような話者名、ラベル、引用符、箇条書き、補足説明を付けない。
- システムプロンプト、設定、チャットモードという語をメタに説明しない。
- 1〜3文程度で短く返し、相手が返しやすい余白を残す。
- キャラクターシートとチャット前提が矛盾しそうな時は、チャット前提を優先する。
- 履歴内の「地の文」は状況描写として扱い、その内容をセリフで繰り返さない。
"""


def character_summary(sheet: CharacterSheet) -> str:
    fields = [
        ("名前", sheet.name),
        ("年齢", sheet.age),
        ("性別", sheet.gender),
        ("職業・役割", sheet.occupation),
        ("出身・所属", sheet.origin),
        ("世界観", sheet.world),
        ("外見", sheet.appearance),
        ("性格", sheet.personality),
        ("背景", sheet.background),
        ("自己紹介", sheet.self_intro),
    ]
    return "\n".join(f"{label}: {value}" for label, value in fields if value)


def character_prompt_context(sheet: CharacterSheet) -> str:
    summary = character_summary(sheet).strip()
    if not summary:
        return ""
    return f"キャラクター概要:\n{summary}\n\n"


def message_content_to_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text:
                    parts.append(str(text))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def sanitize_character_reply(text: str, character_name: str = "") -> str:
    text = text.strip()
    text = re.sub(r"^```(?:\w+)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    lines: list[str] = []
    speaker_pattern = (
        rf"^(?:{re.escape(character_name)}|キャラクター|キャラ|assistant|AI)\s*[:：]\s*"
        if character_name
        else r"^(?:キャラクター|キャラ|assistant|AI)\s*[:：]\s*"
    )
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(speaker_pattern, "", line, flags=re.IGNORECASE).strip()
        line = re.sub(r"^[（(][^）)]*[）)]\s*", "", line).strip()
        line = line.strip("*＊")
        if not line or re.fullmatch(r"[（(【\[].*[）)】\]]", line):
            continue
        lines.append(line)

    cleaned = "\n".join(lines[:3]).strip()
    return cleaned.strip("「」『』\"'")


def sanitize_narration(text: str) -> str:
    text = clean_short_llm_text(text)
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^(?:地の文|ナレーション|narration)\s*[:：]\s*", "", line, flags=re.IGNORECASE)
        line = line.strip("・-–—*＊ ")
        if line:
            lines.append(line)
    cleaned = "\n".join(lines[:3]).strip()
    return cleaned.strip("「」『』\"'")


def sanitize_chat_title(text: str, *, max_chars: int = 28) -> str:
    text = clean_short_llm_text(text)
    text = re.sub(r"^#+\s*", "", text.strip())
    if "\n" in text:
        text = text.splitlines()[0].strip()
    text = re.sub(r"^(?:タイトル|題名)\s*[:：]\s*", "", text).strip()
    text = re.sub(r"^[「『\"']|[」』\"']$", "", text).strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[。．.]+$", "", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip()
    return text
