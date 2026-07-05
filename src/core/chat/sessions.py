"""Persisted chat session records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

DEFAULT_CHAT_TITLE = "新しいチャット"


@dataclass(frozen=True)
class ChatSessionRecord:
    id: str
    character_id: str
    title: str = DEFAULT_CHAT_TITLE
    title_is_auto: bool = True
    settings: dict[str, Any] = field(default_factory=dict)
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
