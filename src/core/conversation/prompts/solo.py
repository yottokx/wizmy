"""1:1チャット用プロンプト構築。"""

from __future__ import annotations

import re
from typing import Protocol

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ...character.schemas import CharacterSheet
from ..sanitize import clean_short_llm_text
from .common import character_summary


class SoloChatSettings(Protocol):
    chat_mode_name: str
    chat_premise: str
    user_persona_name: str
    user_persona_description: str


class SoloChatMessagePreview(Protocol):
    speaker: str
    text: str


def build_llm_messages(
    sheet: CharacterSheet,
    settings: SoloChatSettings,
    messages: list[SoloChatMessagePreview],
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
    settings: SoloChatSettings,
    messages: list[SoloChatMessagePreview],
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
    settings: SoloChatSettings,
    messages: list[SoloChatMessagePreview],
    left_text: str,
    *,
    input_mode: str = "user",
) -> list:
    target_label, system_instruction = input_target_prompt(input_mode, settings, sheet)
    character_context = character_prompt_context(sheet) if input_mode == "character" else ""
    return [
        SystemMessage(content=system_instruction),
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
    settings: SoloChatSettings,
    messages: list[SoloChatMessagePreview],
    left_text: str,
    *,
    input_mode: str = "user",
) -> list:
    prefix = left_text.strip()
    prefix_line = f"各候補は次の書き出しに自然につなげる: {prefix}" if prefix else "各候補は独立した短い返答にする。"
    target_label, system_instruction = input_target_choice_prompt(input_mode, settings, sheet)
    character_context = character_prompt_context(sheet) if input_mode == "character" else ""
    return [
        SystemMessage(content=system_instruction),
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
    settings: SoloChatSettings,
    messages: list[SoloChatMessagePreview],
    text: str,
    *,
    input_mode: str = "user",
) -> list:
    target_label, system_instruction = input_target_tailor_prompt(input_mode, settings, sheet)
    character_context = character_prompt_context(sheet) if input_mode == "character" else ""
    return [
        SystemMessage(content=system_instruction),
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
    settings: SoloChatSettings,
    messages: list[SoloChatMessagePreview],
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
    settings: SoloChatSettings,
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
    settings: SoloChatSettings,
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
    settings: SoloChatSettings,
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


def chat_history_for_prompt(messages: list[SoloChatMessagePreview]) -> str:
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


def is_first_character_turn(messages: list[SoloChatMessagePreview]) -> bool:
    return not any(message.speaker in {"user", "character"} for message in messages)


def build_system_prompt(sheet: CharacterSheet, settings: SoloChatSettings) -> str:
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


def character_prompt_context(sheet: CharacterSheet) -> str:
    summary = character_summary(sheet).strip()
    if not summary:
        return ""
    return f"キャラクター概要:\n{summary}\n\n"


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
