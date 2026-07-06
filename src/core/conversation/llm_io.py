"""LLM 入出力のデバッグ情報整形と短い応答の後処理。"""

from __future__ import annotations

import re
from typing import Any

from .sanitize import clean_short_llm_text
from .schemas import ChatDebugInfo


def format_llm_input(messages: list[Any]) -> str:
    parts: list[str] = []
    for message in messages:
        role = getattr(message, "type", message.__class__.__name__)
        content = message_content_to_text(getattr(message, "content", message))
        parts.append(f"--- {role} ---\n{content}")
    return "\n\n".join(parts)


def build_debug_info(llm_input: str, raw_output: str, response: Any) -> ChatDebugInfo:
    input_tokens, output_tokens, total_tokens = extract_token_usage(response)
    return ChatDebugInfo(
        llm_input=llm_input,
        raw_output=raw_output,
        reasoning_output=extract_reasoning_output(response),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


def extract_token_usage(response: Any) -> tuple[int | None, int | None, int | None]:
    candidates: list[dict[Any, Any]] = []
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


def extract_reasoning_output(response: Any) -> str:
    candidates: list[Any] = []
    additional_kwargs = getattr(response, "additional_kwargs", None)
    if isinstance(additional_kwargs, dict):
        candidates.extend(additional_kwargs.get(key) for key in ("reasoning_content", "thinking"))

    response_metadata = getattr(response, "response_metadata", None)
    if isinstance(response_metadata, dict):
        message = response_metadata.get("message")
        if isinstance(message, dict):
            candidates.extend(message.get(key) for key in ("thinking", "reasoning_content"))
        candidates.extend(response_metadata.get(key) for key in ("thinking", "reasoning_content"))

    for candidate in candidates:
        text = message_content_to_text(candidate).strip() if candidate else ""
        if text:
            return text
    return ""


def first_int(values: dict[Any, Any], *keys: str) -> int | None:
    for key in keys:
        value = values.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
    return None


def message_content_to_text(content: Any) -> str:
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
