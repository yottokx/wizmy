"""
キャラ生成エージェント — 2段階生成ロジック。

Stage 1: LangChain エージェントでツールを使ってブレインストーミング
Stage 2: LLM への直接呼び出しでキャラクターシートを組み立て

このモジュールは LangChain にのみ依存し、
UIフレームワーク・スレッド管理・ファイルI/O には依存しない。
"""

from __future__ import annotations

import re
from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from ..character.markdown import extract_character_name_from_markdown
from .prompts import (
    ASSEMBLY_SYSTEM,
    ASSEMBLY_USER_TEMPLATE,
    BRAINSTORM_PROMPT,
    MODIFY_ASSEMBLY_SYSTEM,
    MODIFY_ASSEMBLY_USER_TEMPLATE,
    MODIFY_BRAINSTORM_PROMPT,
    MODIFY_USER_TEMPLATE,
    PHASE_KEYWORDS,
    PHASE_LABELS,
    RELATED_ASSEMBLY_SYSTEM,
    RELATED_BRAINSTORM_PROMPT,
    REQUIRED_SHEET_HEADERS,
)
from .schemas import (
    GenerationMode,
    GenerationPreferences,
    GenerationRequest,
    GenerationResult,
    ProgressEvent,
    ProgressEventType,
    ToolCallRecord,
)
from .tools import GENERATION_TOOLS


def _extract_text(content: Any) -> str:
    """AIMessage.content が str / list のどちらでも文字列として返す。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        return "\n".join(p for p in parts if p)
    return str(content) if content else ""


def _classify_phase(text: str) -> str | None:
    """ツール結果テキストをフェーズに分類する。"""
    for phase, keywords in PHASE_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return phase
    return None


def _parse_base_sheet(base_sheet: str) -> dict:
    """元シートから主人公名と人間関係欄の情報を抽出する。"""
    main_char_name = extract_character_name_from_markdown(base_sheet, default="")
    relationships: dict[str, str] = {}

    in_relations = False
    for line in base_sheet.splitlines():
        if re.match(r"##\s*人間関係", line):
            in_relations = True
            continue
        if in_relations:
            if line.startswith("## "):
                break
            rel_m = re.match(
                r"[-*]\s*\*{0,2}([^*\n:：]+?)\*{0,2}\s*[:：]\s*(.+)",
                line.strip(),
            )
            if rel_m:
                relationships[rel_m.group(1).strip()] = rel_m.group(2).strip()

    return {"main_char_name": main_char_name, "relationships": relationships}


def _build_user_prompt(prefs: GenerationPreferences) -> str:
    d = prefs.to_dict()
    lines = ["以下の希望に基づいてキャラクターをブレインストーミングしてください。\n"]
    world = d.get("world", "おまかせ")
    gender = d.get("gender", "おまかせ")
    age = d.get("age", "おまかせ")
    theme = d.get("theme", "").strip()
    extra = d.get("extra", "").strip()

    lines.append(f"- 世界観: {world if world != 'おまかせ' else 'おまかせ（自由に決めてください）'}")
    lines.append(f"- 性別: {gender if gender != 'おまかせ' else 'おまかせ（乱数で決めてください）'}")
    lines.append(f"- 年齢帯: {age if age != 'おまかせ' else 'おまかせ（乱数で決めてください）'}")
    if theme:
        lines.append(f"- テーマ・雰囲気: {theme}")
    if extra:
        lines.append(f"- その他の要望: {extra}")
    lines.append("\nフェーズA〜Dを順番に実行し、必ずツールで乱数選択してください。全完了後は[GENERATION_COMPLETE]を出力してください。")
    return "\n".join(lines)


def _build_related_user_prompt(
    prefs: GenerationPreferences, base_sheet: str, new_char_name: str
) -> str:
    parsed = _parse_base_sheet(base_sheet)
    main_char = parsed["main_char_name"]
    relationships = parsed["relationships"]
    role_in_base = relationships.get(new_char_name, "") if new_char_name else ""

    d = prefs.to_dict()
    gender = d.get("gender", "おまかせ")
    age = d.get("age", "おまかせ")
    theme = d.get("theme", "").strip()
    extra = d.get("extra", "").strip()

    lines = ["以下の既存シートと同じ世界観に登場する新しいキャラクターをブレインストーミングしてください。\n"]
    lines.append("## 新規キャラクターの指定情報")
    if new_char_name:
        lines.append(f"- 名前（固定・変更禁止）: {new_char_name}")
    else:
        lines.append("- 名前: 指定なし（フェーズDで乱数選択）")
    lines.append(
        f"- 性別: {gender if gender != 'おまかせ' else 'おまかせ（キャラクター名から推測した重み付き候補で random_select）'}"
    )
    lines.append(f"- 年齢帯: {age if age != 'おまかせ' else 'おまかせ（乱数で決めてください）'}")
    if theme:
        lines.append(f"- テーマ・雰囲気: {theme}")
    if extra:
        lines.append(f"- その他の要望: {extra}")

    if role_in_base:
        lines.append(
            f"\n## 元シートでのこのキャラクターの記述\n"
            f"元シートの「{main_char}」のシートには、このキャラクターについて以下のように書かれています：\n"
            f"「{role_in_base}」\n"
            f"→ この役割・職業設定をフェーズAの職業決定の基礎として使用してください（候補の1番目に置き、ツールで確定させること）。"
        )

    if main_char:
        lines.append(
            f"\n## 人間関係に必ず含めるキャラクター\n"
            f"「{main_char}」（元シートの主人公）は、このキャラクターの人間関係に **必ず** 含めてください。\n"
            f"フェーズDで人間関係の候補を作成する際、「{main_char}」を候補の1番目に置いてください。\n"
            f"元シートの他の登場人物（{main_char}以外）との関係は任意です。"
        )

    lines.append(f"\n## 参照する既存キャラクターシート（世界観・登場人物の把握に使用）\n{base_sheet}")
    lines.append("\nフェーズA〜Dを順番に実行してください。")
    if new_char_name:
        lines.append(f"名前は「{new_char_name}」で固定です。フェーズDの名前選択はスキップしてください。")
    if gender != "おまかせ":
        lines.append(f"性別は「{gender}」で固定です。フェーズAの性別選択はスキップしてください。")
    lines.append("全完了後は[GENERATION_COMPLETE]を出力してください。")
    return "\n".join(lines)


def _build_assembly_user(
    primary_results: list[str],
    resolution_results: list[str],
    prefs: GenerationPreferences,
) -> str:
    d = prefs.to_dict()
    pref_lines = "\n".join(
        f"- {k}: {v}" for k, v in d.items() if v and v not in ("おまかせ", "")
    ) or "（特に指定なし）"
    primary_text = "\n".join(f"- {r}" for r in primary_results)
    resolution_text = (
        "\n".join(f"- {r}" for r in resolution_results) if resolution_results else "（矛盾解決なし）"
    )
    return ASSEMBLY_USER_TEMPLATE.format(
        pref_lines=pref_lines,
        primary_text=primary_text,
        resolution_text=resolution_text,
    )


def _build_modify_assembly_user(
    base_sheet: str,
    modification_results: list[str],
    modify_request: str,
) -> str:
    results_text = "\n".join(f"- {r}" for r in modification_results)
    return MODIFY_ASSEMBLY_USER_TEMPLATE.format(
        modify_request=modify_request,
        base_sheet=base_sheet,
        results_text=results_text,
    )


def _build_related_assembly_user(
    primary_results: list[str],
    resolution_results: list[str],
    prefs: GenerationPreferences,
    base_sheet: str,
    new_char_name: str,
) -> str:
    parsed = _parse_base_sheet(base_sheet)
    main_char = parsed["main_char_name"]
    role_in_base = parsed["relationships"].get(new_char_name, "") if new_char_name else ""

    d = prefs.to_dict()
    pref_lines = "\n".join(
        f"- {k}: {v}" for k, v in d.items() if v and v not in ("おまかせ", "")
    ) or "（特に指定なし）"
    primary_text = "\n".join(f"- {r}" for r in primary_results)
    resolution_text = (
        "\n".join(f"- {r}" for r in resolution_results) if resolution_results else "（矛盾解決なし）"
    )

    name_note = f"\n**名前は「{new_char_name}」で固定してください（変更禁止）**\n" if new_char_name else ""
    name_in_header = new_char_name if new_char_name else "「キャラクター名」の選択結果から"

    constraints: list[str] = []
    if role_in_base:
        constraints.append(
            f"- 「職業・役割」欄には、元シートで定義された役割「{role_in_base}」の内容を必ず反映させること"
            f"（ブレインストーミングで選ばれた職業と合わせて自然に記述してよい）"
        )
    if main_char:
        constraints.append(
            f"- 「## 人間関係」セクションには「{main_char}」（元シートの主人公）を **必ず** 含めること"
            f"（元シートの他の登場人物との関係は任意）"
        )
    constraint_text = "\n".join(constraints) if constraints else "（特になし）"

    return f"""\
## ユーザーの要望（参考情報）
{pref_lines}

## 参照する既存キャラクターシート（世界観・登場人物把握のみに使用すること）
{base_sheet}

## 新規キャラクター属性（このキャラクターのシートを作成する素材・これのみ使用すること）
{name_note}{primary_text}

## 矛盾解決メモ（「過去・背景」か「物語のフック」への補足としてのみ使用可）
{resolution_text}

## 必須制約（以下を必ず守ること）
{constraint_text}

## 出力フォーマット
上記の「新規キャラクター属性」と「必須制約」に従い、以下の形式で**新規キャラクター**のシートを作成してください。
既存シートの設定・ストーリー・物語のフックを流用することは禁止。{name_note}
---
# [{name_in_header}]

## 基本情報
| 項目 | 内容 |
|------|------|
| 名前 | |
| 年齢 | |
| 性別 | |
| 職業・役割 | |
| 出身・所属 | |

## 世界観・舞台
（既存シートと同じ世界観を踏まえ、このキャラクターの舞台・場所の選択結果を基に2〜3文）

## 外見
（外見特徴の選択結果のみを使って描写）

## 性格・内面
（性格タイプ・弱点の選択結果を基に説明）

## 動機・目標
（動機・目標の選択結果を基に）

## 弱点・コンプレックス
（選択結果をそのまま具体化）

## 過去・背景
（転機・秘密の選択結果を基に。矛盾解決メモがあれば自然な形で組み込む）

## スキル・能力
（スキル・能力の選択結果をリスト形式で）

## 人間関係
（人間関係の選択結果を基に、1人1行の箇条書きで。形式: `- **名前**: 関係の説明`
 元シートの主人公が選択結果に含まれない場合でも、必ずこのセクションに追加すること）

## 個性・クセ・口癖
（口癖・クセの選択結果のみ記載）

## 物語のフック
（このキャラクター固有の設定から自然に導かれる物語の種を2〜3個）

## 自己紹介台詞
（初対面の相手に自己紹介するセリフを1〜3文。一人称・口調・話し方を性格・職業・世界観・性別に合わせる）

## 声のイメージ
（プレーンテキスト1行・見出し記号「#」不使用。「男性話者」「女性話者」「中性的な話者」と
 年齢層を表す語（幼い・若い・大人の・中年の・年老いた 等）を必ず含め、15〜30字で記述）

---
"""


def _assemble_sheet(
    llm: BaseChatModel,
    primary_results: list[str],
    resolution_results: list[str],
    prefs: GenerationPreferences,
) -> str:
    response = llm.invoke([
        SystemMessage(content=ASSEMBLY_SYSTEM),
        HumanMessage(content=_build_assembly_user(primary_results, resolution_results, prefs)),
    ])
    return _extract_text(response.content)


def _assemble_modify_sheet(
    llm: BaseChatModel,
    base_sheet: str,
    modification_results: list[str],
    modify_request: str,
) -> str:
    response = llm.invoke([
        SystemMessage(content=MODIFY_ASSEMBLY_SYSTEM),
        HumanMessage(content=_build_modify_assembly_user(base_sheet, modification_results, modify_request)),
    ])
    return _extract_text(response.content)


def _assemble_related_sheet(
    llm: BaseChatModel,
    primary_results: list[str],
    resolution_results: list[str],
    prefs: GenerationPreferences,
    base_sheet: str,
    new_char_name: str,
) -> str:
    response = llm.invoke([
        SystemMessage(content=RELATED_ASSEMBLY_SYSTEM),
        HumanMessage(
            content=_build_related_assembly_user(
                primary_results, resolution_results, prefs, base_sheet, new_char_name
            )
        ),
    ])
    return _extract_text(response.content)


def score_completion(
    tool_calls: list[ToolCallRecord], sheet: str, mode: GenerationMode
) -> dict:
    """ツール結果数・フェーズカバレッジ・必須ヘッダーから品質スコアを算出する。"""
    tool_count = len(tool_calls)
    header_score = sum(1 for h in REQUIRED_SHEET_HEADERS if h in sheet) / len(REQUIRED_SHEET_HEADERS)

    if mode == GenerationMode.MODIFY:
        quality = min(tool_count / 4, 1.0) * 0.6 + header_score * 0.4
        if tool_count >= 1 and header_score >= 0.6:
            quality_status = "complete"
        elif tool_count >= 1:
            quality_status = "partial"
        else:
            quality_status = "failed"
        phase_coverage: dict[str, bool] = {p: False for p in PHASE_LABELS}
        phases_covered = 0
    else:
        phase_coverage = {p: False for p in PHASE_LABELS}
        for tc in tool_calls:
            phase = _classify_phase(tc.result)
            if phase:
                phase_coverage[phase] = True
        phases_covered = sum(phase_coverage.values())

        tool_score = min(tool_count / 14, 1.0)
        phase_score = phases_covered / len(PHASE_LABELS)
        quality = tool_score * 0.35 + phase_score * 0.40 + header_score * 0.25

        if quality >= 0.75 and phases_covered >= 3 and header_score >= 0.6:
            quality_status = "complete"
        elif quality >= 0.40 and tool_count >= 4:
            quality_status = "partial"
        else:
            quality_status = "failed"

    return {
        "tool_count": tool_count,
        "phase_coverage": phase_coverage,
        "phases_covered": phases_covered,
        "header_score": round(header_score, 2),
        "quality": round(quality, 2),
        "quality_status": quality_status,
    }


def run_generation(
    llm: BaseChatModel,
    request: GenerationRequest,
    progress_callback=None,
    stop_check=None,
) -> GenerationResult:
    """
    キャラ生成を実行する（同期・ブロッキング）。

    Args:
        llm: LangChain BaseChatModel
        request: 生成リクエスト
        progress_callback: ProgressEvent を受け取るコールバック（省略可）
        stop_check: bool を返す関数（Trueで停止、省略可）

    Returns:
        GenerationResult
    """
    mode = request.mode

    if mode == GenerationMode.NEW:
        system_prompt = BRAINSTORM_PROMPT
        user_message = _build_user_prompt(request.preferences)
        complete_marker = "[GENERATION_COMPLETE]"
    elif mode == GenerationMode.MODIFY:
        system_prompt = MODIFY_BRAINSTORM_PROMPT
        user_message = MODIFY_USER_TEMPLATE.format(
            base_sheet=request.base_sheet,
            modify_request=request.modify_request,
        )
        complete_marker = "[MODIFICATION_COMPLETE]"
    else:  # RELATED
        system_prompt = RELATED_BRAINSTORM_PROMPT
        user_message = _build_related_user_prompt(
            request.preferences, request.base_sheet, request.new_char_name
        )
        complete_marker = "[GENERATION_COMPLETE]"

    graph = create_agent(llm, GENERATION_TOOLS, system_prompt=system_prompt)
    graph_config = {"recursion_limit": request.recursion_limit}

    tool_calls: list[ToolCallRecord] = []
    complete_seen = False
    # AIMessage の tool_calls args を ToolMessage と紐付けるための一時バッファ
    _pending_inputs: dict[str, dict] = {}

    try:
        for chunk in graph.stream(
            {"messages": [HumanMessage(content=user_message)]},
            stream_mode="updates",
            config=graph_config,
        ):
            if stop_check and stop_check():
                if progress_callback:
                    progress_callback(ProgressEvent(type=ProgressEventType.STOPPED))
                return GenerationResult(success=False, error_message="生成を停止しました。", mode=mode)

            for node_output in chunk.values():
                for msg in node_output.get("messages", []):
                    if isinstance(msg, AIMessage):
                        content = _extract_text(msg.content)
                        if complete_marker in content:
                            complete_seen = True
                        # tool_calls の引数を記録（全候補を詳細ログに使う）
                        for tc_call in getattr(msg, "tool_calls", []) or []:
                            if isinstance(tc_call, dict):
                                cid = tc_call.get("id", "")
                                args = tc_call.get("args", {})
                            else:
                                cid = getattr(tc_call, "id", "")
                                args = getattr(tc_call, "args", {})
                            if cid:
                                _pending_inputs[cid] = args if isinstance(args, dict) else {}
                    elif isinstance(msg, ToolMessage):
                        result = _extract_text(msg.content)
                        if result and "エラー" not in result:
                            is_resolution = "[矛盾解決]" in result
                            tc_id = getattr(msg, "tool_call_id", "")
                            tc_args = _pending_inputs.pop(tc_id, {})
                            all_opts: list[str] = []
                            if isinstance(tc_args, dict):
                                raw_opts = tc_args.get("options") or []
                                all_opts = [str(o) for o in raw_opts] if isinstance(raw_opts, list) else []
                            tc = ToolCallRecord(
                                tool_name=msg.name if hasattr(msg, "name") else "",
                                result=result,
                                is_resolution=is_resolution,
                                all_options=all_opts,
                            )
                            tool_calls.append(tc)
                            if progress_callback:
                                progress_callback(ProgressEvent(
                                    type=ProgressEventType.TOOL_CALLED, data=tc
                                ))

    except Exception as exc:
        error_msg = f"Stage 1 エラー: {exc}"
        if progress_callback:
            progress_callback(ProgressEvent(type=ProgressEventType.ERROR, data=error_msg))
        return GenerationResult(success=False, error_message=error_msg, mode=mode)

    if stop_check and stop_check():
        if progress_callback:
            progress_callback(ProgressEvent(type=ProgressEventType.STOPPED))
        return GenerationResult(success=False, error_message="生成を停止しました。", mode=mode)

    primary_results = [tc.result for tc in tool_calls if not tc.is_resolution]
    resolution_results = [tc.result for tc in tool_calls if tc.is_resolution]
    all_results = primary_results + resolution_results

    if progress_callback:
        progress_callback(ProgressEvent(
            type=ProgressEventType.STAGE1_DONE,
            data={"tool_count": len(all_results), "complete_seen": complete_seen},
        ))

    if not all_results:
        error_msg = "ツール呼び出し結果が0件のためシートを生成できません。ツール対応モデルを確認してください。"
        if progress_callback:
            progress_callback(ProgressEvent(type=ProgressEventType.ERROR, data=error_msg))
        return GenerationResult(success=False, error_message=error_msg, tool_calls=tool_calls, mode=mode)

    if mode in (GenerationMode.NEW, GenerationMode.RELATED):
        phase_set: set[str] = set()
        for tc in tool_calls:
            p = _classify_phase(tc.result)
            if p:
                phase_set.add(p)
        if len(phase_set) < 3:
            marker_note = "" if complete_seen else "（[GENERATION_COMPLETE] マーカーも未検出）"
            error_msg = (
                f"フェーズカバレッジ不足（{len(phase_set)}/4 フェーズ完了）のためシート生成をスキップしました。"
                f"生成が途中で終了した可能性があります。{marker_note}"
            )
            if progress_callback:
                progress_callback(ProgressEvent(type=ProgressEventType.ERROR, data=error_msg))
            return GenerationResult(
                success=False, error_message=error_msg, tool_calls=tool_calls, mode=mode
            )

    if progress_callback:
        progress_callback(ProgressEvent(type=ProgressEventType.STAGE2_START))

    try:
        if mode == GenerationMode.MODIFY:
            sheet = _assemble_modify_sheet(
                llm, request.base_sheet, all_results, request.modify_request
            )
        elif mode == GenerationMode.RELATED:
            sheet = _assemble_related_sheet(
                llm, primary_results, resolution_results,
                request.preferences, request.base_sheet, request.new_char_name,
            )
        else:
            sheet = _assemble_sheet(llm, primary_results, resolution_results, request.preferences)
    except Exception as exc:
        error_msg = f"Stage 2 エラー: {exc}"
        if progress_callback:
            progress_callback(ProgressEvent(type=ProgressEventType.ERROR, data=error_msg))
        return GenerationResult(
            success=False, error_message=error_msg, tool_calls=tool_calls, mode=mode
        )

    score = score_completion(tool_calls, sheet, mode)

    if progress_callback:
        progress_callback(ProgressEvent(type=ProgressEventType.SHEET_READY, data=sheet))

    return GenerationResult(
        success=True,
        sheet_markdown=sheet,
        tool_calls=tool_calls,
        quality_status=score["quality_status"],
        quality_score=score["quality"],
        mode=mode,
    )
