"""ui2 生成ページの純ロジック(generation_logic)のテスト。"""

from __future__ import annotations

from src.core.character_generation.schemas import (
    GenerationMode,
    GenerationPreferences,
    GenerationRequest,
    GenerationResult,
    ToolCallRecord,
)
from src.ui2.generation_logic import (
    CHAPTER_NAMES,
    ChapterProgress,
    build_generation_log,
    classify_phase,
    fact_chips,
    quality_label,
    shorten,
)


def test_chapter_names_cover_stage1_phases_and_stage2() -> None:
    assert CHAPTER_NAMES == ["世界観・基本", "外見・性格", "背景・スキル", "名前・整合性", "シート執筆"]


def test_classify_phase_matches_keywords() -> None:
    assert classify_phase("世界観を「和風幻想」に決定") == "A: 世界観・基本"
    assert classify_phase("性格の候補から「生真面目」を選択") == "B: 外見・性格"
    assert classify_phase("スキルを検討") == "C: 背景・スキル"
    assert classify_phase("キャラクター名を「灯里」に決定") == "D: 名前・整合性"
    assert classify_phase("該当しないテキスト") is None


def test_shorten_truncates_and_collapses_whitespace() -> None:
    assert shorten("あ　い\nう", 10) == "あ い う"
    assert shorten("x" * 60, 10) == "x" * 9 + "…"


def test_chapter_progress_flow() -> None:
    progress = ChapterProgress()
    progress.start()
    assert progress.rows[0].status == "now"

    progress.apply_tool("世界観を「精霊の王国」に決定")
    assert progress.rows[0].status == "now"
    assert "精霊の王国" in progress.rows[0].detail

    progress.apply_tool("性格を「生真面目」に決定")
    assert progress.rows[0].status == "done"
    assert progress.rows[1].status == "now"

    progress.start_stage2()
    assert progress.rows[1].status == "done"
    assert progress.rows[-1].status == "now"

    progress.finish()
    assert all(row.status in {"done", "todo"} for row in progress.rows)
    assert progress.rows[-1].status == "done"
    assert progress.rows[-1].detail == "執筆完了"


def test_chapter_progress_unclassified_tool_updates_current_row() -> None:
    progress = ChapterProgress()
    progress.start()
    progress.apply_tool("分類できない結果テキスト")
    assert progress.rows[0].status == "now"
    assert progress.rows[0].detail == "分類できない結果テキスト"


def test_chapter_progress_halt_stops_running_row() -> None:
    progress = ChapterProgress()
    progress.start()
    progress.apply_tool("世界観を「王国」に決定")
    progress.halt()
    assert all(row.status != "now" for row in progress.rows)


def test_fact_chips_composition() -> None:
    chips = fact_chips(
        world="精霊と契約した者だけが力を得る、中世の王国\n二行目は使わない",
        occupation="宮廷魔導師見習い",
        age="青年期（16〜25歳）",
        voice_image="透明感のある若い女性",
        quality_status="complete",
    )
    assert chips[0].startswith("精霊と契約した者")
    assert "宮廷魔導師見習い" in chips
    assert "青年期（16〜25歳）" in chips
    assert any(chip.startswith("声: ") for chip in chips)
    assert "品質: 良好" in chips


def test_fact_chips_skips_empty_values() -> None:
    assert fact_chips() == []
    assert fact_chips(quality_status="partial") == ["品質: 部分的"]


def test_quality_label_mapping() -> None:
    assert quality_label("complete") == "品質: 良好"
    assert quality_label("partial") == "品質: 部分的"
    assert quality_label("failed") == "品質: 低"
    assert quality_label("unknown") == ""


class _Profile:
    name = "テスト"
    model_id = "model-x"
    temperature = 0.7
    reasoning_enabled = False
    max_tokens = None


def test_build_generation_log_includes_request_and_candidates() -> None:
    result = GenerationResult(
        success=True,
        sheet_markdown="# 灯里\n## 基本情報\n| 項目 | 内容 |\n| 名前 | 灯里 |",
        tool_calls=[
            ToolCallRecord(
                tool_name="choose_world",
                result="世界観を「王国」に決定",
                is_resolution=True,
                all_options=["王国", "港町"],
            )
        ],
        quality_status="complete",
        quality_score=0.9,
        mode=GenerationMode.NEW,
    )
    request = GenerationRequest(
        preferences=GenerationPreferences(world="ハイファンタジー", theme="孤独な戦士"),
        mode=GenerationMode.NEW,
    )
    log = build_generation_log(result, "generate", result.sheet_markdown, request, _Profile())
    assert "モード  : 新規生成" in log
    assert "モデルID     : model-x" in log
    assert "ハイファンタジー" in log
    assert "孤独な戦士" in log
    assert "全候補 (2 件)" in log
    assert "◀ 選択" in log
    assert "# 灯里" in log
