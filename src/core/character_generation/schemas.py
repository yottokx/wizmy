"""
キャラ生成エージェントの入出力スキーマ。

GenerationRequest: 生成に必要な入力情報
GenerationResult: 生成結果（シートテキスト + メタ情報）
GenerationProgress: 進捗イベント（UIへのストリーミング用）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class GenerationMode(str, Enum):
    NEW = "generate"
    MODIFY = "modify"
    RELATED = "related"


@dataclass
class GenerationPreferences:
    """ユーザーが指定する生成の好み。"""
    world: str = "おまかせ"
    gender: str = "おまかせ"
    age: str = "おまかせ"
    theme: str = ""
    extra: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "world": self.world,
            "gender": self.gender,
            "age": self.age,
            "theme": self.theme,
            "extra": self.extra,
        }


@dataclass
class GenerationBaseSheet:
    """関連キャラ生成で参照するベースキャラクター情報。"""
    id: str = ""
    name: str = ""
    handle: str = ""
    sheet_markdown: str = ""


@dataclass
class GenerationRequest:
    """生成エージェントへの入力。"""
    preferences: GenerationPreferences
    mode: GenerationMode = GenerationMode.NEW
    base_sheet: str = ""
    modify_request: str = ""
    new_char_name: str = ""
    group_world: str = ""
    related_base_sheets: list[GenerationBaseSheet] = field(default_factory=list)
    omit_group_sections: bool = False
    recursion_limit: int = 100


@dataclass
class ToolCallRecord:
    """ツール呼び出しの記録（ログ・UI表示用）。"""
    tool_name: str
    result: str
    is_resolution: bool = False
    all_options: list[str] = field(default_factory=list)  # 全候補（詳細ログ用）


@dataclass
class GenerationResult:
    """生成エージェントの出力。"""
    success: bool
    sheet_markdown: str = ""
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    quality_status: str = ""
    quality_score: float = 0.0
    error_message: str = ""
    mode: GenerationMode = GenerationMode.NEW

    @property
    def tool_count(self) -> int:
        return len(self.tool_calls)


class ProgressEventType(str, Enum):
    STARTED = "started"
    TOOL_CALLED = "tool_called"
    STAGE1_DONE = "stage1_done"
    STAGE2_START = "stage2_start"
    SHEET_READY = "sheet_ready"
    DONE = "done"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass
class ProgressEvent:
    """生成進捗のストリーミングイベント。"""
    type: ProgressEventType
    data: Any = None
