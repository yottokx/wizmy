"""
生成ページ(/v2/generation・グループ内生成)の純ロジック。

- 進捗イベント → 「章立て」表示(モック generation.html 状態B)の状態機械
- 完成表示(状態C)の facts チップ・品質ラベル
- 詳細ログ生成(旧 `ui/components/generation_result.py::build_generation_log` の
  ui2 複製。依存規則により import せず複製し、旧UI削除時に旧側を消す)
"""

from __future__ import annotations

import re as _re
from dataclasses import dataclass, field
from datetime import datetime

from ..core.character_generation.prompts import PHASE_KEYWORDS, PHASE_LABELS

# 章立て(モックの「名前/世界観/…」は演出例。実パイプラインの Stage1 4フェーズ+
# Stage2 執筆を章として見せる)
STAGE2_CHAPTER = "シート執筆"
CHAPTER_NAMES: list[str] = [label.split(": ", 1)[1] for label in PHASE_LABELS] + [STAGE2_CHAPTER]

_DETAIL_LIMIT = 46

# 「まだ実結果が入っていない」プレースホルダ詳細(done 判定から除外する)
_PLACEHOLDER_DETAILS = {"", "…", "候補を考えています…", "キャラクターシートを執筆しています…"}


def classify_phase(text: str) -> str | None:
    """ツール結果テキストを Stage1 フェーズ(PHASE_LABELS)に分類する。"""
    for phase, keywords in PHASE_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return phase
    return None


def shorten(text: str, limit: int = _DETAIL_LIMIT) -> str:
    value = " ".join((text or "").split())
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


@dataclass
class ChapterRow:
    """章1行分の表示状態。status は "todo" / "now" / "done"。"""

    no: int
    name: str
    status: str = "todo"
    detail: str = "…"


@dataclass
class ChapterProgress:
    """進捗イベント列を章立て表示へ写像する状態機械(純ロジック・テスト可能)。"""

    rows: list[ChapterRow] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.rows:
            self.reset()

    def reset(self) -> None:
        self.rows = [ChapterRow(no=index + 1, name=name) for index, name in enumerate(CHAPTER_NAMES)]

    def start(self) -> None:
        """STARTED: 最初の章を「進行中」にする。"""
        self.reset()
        self.rows[0].status = "now"
        self.rows[0].detail = "候補を考えています…"

    def apply_tool(self, result_text: str) -> None:
        """TOOL_CALLED: フェーズ分類した章へ最新結果を書き、以前の章を確定させる。"""
        phase = classify_phase(result_text)
        detail = shorten(result_text)
        if phase is None:
            for row in self.rows:
                if row.status == "now":
                    row.detail = detail or row.detail
                    return
            return
        index = PHASE_LABELS.index(phase)
        for row in self.rows[:index]:
            if row.status != "done" and row.detail not in _PLACEHOLDER_DETAILS:
                row.status = "done"
        for row in self.rows:
            if row.status == "now" and row.no - 1 != index:
                row.status = "done" if row.detail not in _PLACEHOLDER_DETAILS else "todo"
        target = self.rows[index]
        target.status = "now"
        target.detail = detail or target.detail

    def stage1_done(self) -> None:
        for row in self.rows[:-1]:
            if row.detail not in _PLACEHOLDER_DETAILS:
                row.status = "done"
            elif row.status == "now":
                row.status = "todo"

    def start_stage2(self) -> None:
        self.stage1_done()
        last = self.rows[-1]
        last.status = "now"
        last.detail = "キャラクターシートを執筆しています…"

    def finish(self) -> None:
        self.stage1_done()
        last = self.rows[-1]
        last.status = "done"
        last.detail = "執筆完了"

    def halt(self) -> None:
        """エラー/停止: 進行中の章を止める(確定済みはそのまま)。"""
        for row in self.rows:
            if row.status == "now":
                row.status = "todo"


def fact_chips(
    *,
    world: str = "",
    occupation: str = "",
    age: str = "",
    voice_image: str = "",
    quality_status: str = "",
) -> list[str]:
    """状態C(誕生)の facts チップ列を組み立てる。"""
    chips: list[str] = []
    world_line = (world or "").strip().splitlines()[0].strip() if (world or "").strip() else ""
    if world_line:
        chips.append(shorten(world_line, 30))
    if (occupation or "").strip():
        chips.append(occupation.strip())
    if (age or "").strip():
        chips.append(age.strip())
    if (voice_image or "").strip():
        chips.append(f"声: {shorten(voice_image.strip(), 24)}")
    quality = quality_label(quality_status)
    if quality:
        chips.append(quality)
    return chips


def quality_label(status: str) -> str:
    return {
        "complete": "品質: 良好",
        "partial": "品質: 部分的",
        "failed": "品質: 低",
    }.get(status, "")


def build_generation_log(result, mode_str: str, sheet_md: str = "", request=None, profile=None) -> str:
    """全候補・モデル情報・ユーザー指示を含む詳細ログテキストを生成する。"""
    _mode_names = {"generate": "新規生成", "modify": "修正", "related": "関連キャラ生成"}
    lines = [
        "=== キャラクター生成 詳細ログ ===",
        f"生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"モード  : {_mode_names.get(mode_str, mode_str)}",
        f"品質    : {result.quality_status}  スコア: {result.quality_score:.2f}",
        f"ツール呼び出し: {result.tool_count} 件",
        "",
    ]

    if profile:
        lines += [
            "━" * 60,
            "使用モデル",
            "━" * 60,
            f"プロファイル : {profile.name}",
            f"モデルID     : {profile.model_id}",
        ]
        if profile.reasoning_enabled:
            lines.append("推論モード   : 有効")
        else:
            lines.append(f"Temperature  : {profile.temperature}")
        if getattr(profile, "max_tokens", None):
            lines.append(f"最大トークン : {profile.max_tokens}")
        lines.append("")

    if request:
        lines += [
            "━" * 60,
            "ユーザー指示",
            "━" * 60,
        ]
        p = request.preferences
        for label, val in [
            ("世界観", p.world),
            ("年齢帯", p.age),
            ("性別", p.gender),
            ("テーマ", p.theme),
            ("追加要望", p.extra),
        ]:
            if val and val != "おまかせ":
                lines.append(f"{label:6s}: {val}")
        if request.modify_request:
            lines.append(f"修正指示: {request.modify_request}")
        if request.base_sheet:
            lines.append("ベースキャラクター: あり（ベースシートは省略）")
        lines.append("")

    lines += [
        "━" * 60,
        "Stage 1: ブレインストーミング詳細",
        "━" * 60,
        "",
    ]
    for i, tc in enumerate(result.tool_calls, 1):
        lines.append(f"[{i:02d}] {tc.tool_name}")
        lines.append(f"  結果: {tc.result}")
        if tc.all_options:
            m = _re.search(r"「(.+?)」", tc.result)
            selected = m.group(1) if m else ""
            lines.append(f"  全候補 ({len(tc.all_options)} 件):")
            for j, opt in enumerate(tc.all_options, 1):
                marker = " ◀ 選択" if opt == selected else ""
                lines.append(f"    {j:2d}. {opt}{marker}")
        lines.append("")

    if sheet_md:
        lines += [
            "━" * 60,
            "生成されたシート",
            "━" * 60,
            "",
            sheet_md,
        ]
    return "\n".join(lines)
