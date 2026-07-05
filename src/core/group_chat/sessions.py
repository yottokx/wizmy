"""グループチャットの仮セッション保存モデル。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

DEFAULT_GROUP_CHAT_TITLE = "新しいグループチャット"


@dataclass(frozen=True)
class GroupChatSessionRecord:
    id: str
    group_id: str
    title: str = DEFAULT_GROUP_CHAT_TITLE
    title_is_auto: bool = True
    settings: dict[str, Any] = field(default_factory=dict)
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
