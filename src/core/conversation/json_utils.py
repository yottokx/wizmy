"""LLM 応答に含まれる JSON 断片の取り出し。"""

from __future__ import annotations

import json
import re
from typing import Any


def try_parse_json(text: str) -> Any | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def try_parse_json_fragment(raw: str) -> Any | None:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()
    parsed = try_parse_json(text)
    if parsed is not None:
        return parsed
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        return value
    return None


def longest_json_string(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        values = [longest_json_string(item) for item in value.values()]
        return max(values, key=len, default="")
    if isinstance(value, list):
        values = [longest_json_string(item) for item in value]
        return max(values, key=len, default="")
    return ""
