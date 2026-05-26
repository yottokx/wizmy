"""
キャラ生成エージェント用 LangChain ツール群。

各ツールは乱数による選択を行い、LLM自身のバイアスを排除する目的で使用される。
record_resolution のみ乱数を使用しない（LLMの推論結果を記録する）。
"""

from __future__ import annotations

import random

from langchain_core.tools import tool
from pydantic import BaseModel, Field


class RandomSelectInput(BaseModel):
    options: list[str] = Field(description="選択候補のリスト（3〜8個推奨）")
    label: str = Field(default="", description="選択対象の説明（例: 世界観、職業）")


@tool("random_select", args_schema=RandomSelectInput)
def random_select(options: list[str], label: str = "") -> str:
    """候補リストから乱数でひとつを選択する。LLMのバイアスを排除するために必ず使用すること。"""
    if not options:
        return "エラー: 選択肢がありません"
    idx = random.randint(0, len(options) - 1)
    label_str = f"[{label}] " if label else ""
    return f"{label_str}🎲 選択: 「{options[idx]}」 ({idx + 1}/{len(options)}番目)"


class RandomIntInput(BaseModel):
    min_val: int = Field(description="最小値（含む）")
    max_val: int = Field(description="最大値（含む）")
    label: str = Field(default="", description="何の数値か（例: 年齢）")


@tool("random_int", args_schema=RandomIntInput)
def random_int(min_val: int, max_val: int, label: str = "") -> str:
    """整数乱数を生成する。年齢など数値的な属性の決定に使用する。"""
    if min_val > max_val:
        min_val, max_val = max_val, min_val
    val = random.randint(min_val, max_val)
    label_str = f"[{label}] " if label else ""
    return f"{label_str}🎲 値: {val} (範囲: {min_val}〜{max_val})"


class RandomMultiSelectInput(BaseModel):
    options: list[str] = Field(description="選択候補のリスト（5個以上推奨）")
    count: int = Field(description="選択する個数", ge=1, le=8)
    label: str = Field(default="", description="選択対象の説明（例: 外見特徴、スキル）")


@tool("random_multi_select", args_schema=RandomMultiSelectInput)
def random_multi_select(options: list[str], count: int, label: str = "") -> str:
    """候補リストから乱数で複数を選択する。スキル・特徴など複数要素の決定に使用する。"""
    if not options:
        return "エラー: 選択肢がありません"
    count = min(count, len(options))
    selected = random.sample(options, count)
    label_str = f"[{label}] " if label else ""
    return f"{label_str}🎲 選択: " + "、".join(f"「{s}」" for s in selected)


class RecordResolutionInput(BaseModel):
    issue: str = Field(description="発見した矛盾・整合性の問題の概要")
    resolution: str = Field(description="LLMが推論した最適な解決策")


@tool("record_resolution", args_schema=RecordResolutionInput)
def record_resolution(issue: str, resolution: str) -> str:
    """整合性チェックで発見した矛盾の解決策を記録する。
    乱数ではなく、LLMが論理的に推論した最適解を記録するためのツール。
    矛盾がある場合にのみ呼び出すこと。"""
    return f"[矛盾解決] 問題: {issue} → 解決策: {resolution}"


GENERATION_TOOLS = [random_select, random_int, random_multi_select, record_resolution]
