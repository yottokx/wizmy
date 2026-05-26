"""
キャラ生成サービス。

asyncio を使ったバックグラウンド実行と進捗ストリーミングを提供する。
生成コアロジック (core/character_generation/agent.py) の
asyncio ラッパーとして機能する。
"""

from __future__ import annotations

import asyncio
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import AsyncIterator

from ..core.character.markdown import extract_character_name_from_markdown
from ..core.character.schemas import CharacterSheet, GenerationMeta, Relationship
from ..core.character_generation.agent import run_generation
from ..core.character_generation.schemas import (
    GenerationMode,
    GenerationRequest,
    GenerationResult,
    ProgressEvent,
    ProgressEventType,
)
from ..core.llm.factory import create_llm
from ..core.llm.schemas import Endpoint, LLMProfile
from .character import CharacterService

_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="chargen")


class GenerationJobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


_TERMINAL_STATUSES = {
    GenerationJobStatus.COMPLETED,
    GenerationJobStatus.FAILED,
    GenerationJobStatus.CANCELLED,
}


@dataclass
class GenerationJob:
    id: str
    request: GenerationRequest
    profile: LLMProfile
    endpoint: Endpoint
    status: GenerationJobStatus = GenerationJobStatus.QUEUED
    base_character_id: str = ""
    events: list[ProgressEvent] = field(default_factory=list)
    sheet_markdown: str = ""
    result: GenerationResult | None = None
    error_message: str = ""
    save_error_message: str = ""
    saved_character_id: str = ""
    saved_character_name: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    updated_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None
    _listeners: set[asyncio.Queue[None]] = field(
        default_factory=set, repr=False, compare=False
    )
    _task: asyncio.Task | None = field(default=None, repr=False, compare=False)

    @property
    def is_active(self) -> bool:
        return self.status not in _TERMINAL_STATUSES


def parse_markdown_to_sheet(sheet_md: str, sheet_id: str) -> CharacterSheet:
    """Markdown テキストから構造化 CharacterSheet を生成する（公開 API）。"""
    return _parse_sheet_to_structured(sheet_md, sheet_id)


def _parse_sheet_to_structured(sheet_md: str, sheet_id: str) -> CharacterSheet:
    """
    Markdown シートから構造化された CharacterSheet を生成する。
    フィールドが取れない場合は空文字を設定する（パースエラーで失敗しない）。
    """

    def extract_section(md: str, header: str) -> str:
        pattern = rf"##\s*{re.escape(header)}\s*\n(.*?)(?=\n##|\Z)"
        m = re.search(pattern, md, re.DOTALL)
        return m.group(1).strip() if m else ""

    def extract_table_field(md: str, field_name: str) -> str:
        pattern = rf"\|\s*{re.escape(field_name)}\s*\|\s*(.+?)\s*\|"
        m = re.search(pattern, md)
        return m.group(1).strip() if m else ""

    def parse_relationships(section_text: str) -> list[Relationship]:
        rels: list[Relationship] = []
        for line in section_text.splitlines():
            m = re.match(r"[-*]\s*\*{0,2}([^*\n:：]+?)\*{0,2}\s*[:：]\s*(.+)", line.strip())
            if m:
                rels.append(Relationship(name=m.group(1).strip(), description=m.group(2).strip()))
        return rels

    name = extract_character_name_from_markdown(sheet_md)

    return CharacterSheet(
        id=sheet_id,
        name=name,
        age=extract_table_field(sheet_md, "年齢"),
        gender=extract_table_field(sheet_md, "性別"),
        occupation=extract_table_field(sheet_md, "職業・役割"),
        origin=extract_table_field(sheet_md, "出身・所属"),
        world=extract_section(sheet_md, "世界観・舞台"),
        appearance=extract_section(sheet_md, "外見"),
        personality=extract_section(sheet_md, "性格・内面"),
        motivation=extract_section(sheet_md, "動機・目標"),
        weakness=extract_section(sheet_md, "弱点・コンプレックス"),
        background=extract_section(sheet_md, "過去・背景"),
        skills=extract_section(sheet_md, "スキル・能力"),
        relationships=parse_relationships(extract_section(sheet_md, "人間関係")),
        quirks=extract_section(sheet_md, "個性・クセ・口癖"),
        story_hooks=extract_section(sheet_md, "物語のフック"),
        self_intro=extract_section(sheet_md, "自己紹介台詞"),
        voice_image=extract_section(sheet_md, "声のイメージ"),
        raw_markdown=sheet_md,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


class CharacterGenerationService:
    """
    キャラ生成のオーケストレーション。

    生成はバックグラウンドスレッドで実行され、
    進捗は AsyncIterator[ProgressEvent] でストリーミングされる。
    """

    def __init__(self, character_service: CharacterService) -> None:
        self._character_service = character_service
        self._stop_flag: dict[str, bool] = {}
        self._jobs: dict[str, GenerationJob] = {}

    def start_job(
        self,
        request: GenerationRequest,
        profile: LLMProfile,
        endpoint: Endpoint,
        api_key: str | None = None,
        generation_id: str | None = None,
        base_character_id: str = "",
    ) -> GenerationJob:
        """生成ジョブをバックグラウンドで開始する。"""
        gen_id = generation_id or f"gen-{uuid.uuid4().hex[:12]}"
        job = GenerationJob(
            id=gen_id,
            request=request,
            profile=profile,
            endpoint=endpoint,
            base_character_id=base_character_id,
        )
        self._jobs[job.id] = job
        self._stop_flag[job.id] = False
        job._task = asyncio.create_task(self._run_job(job, api_key))
        return job

    def get_job(self, generation_id: str | None) -> GenerationJob | None:
        if not generation_id:
            return None
        return self._jobs.get(generation_id)

    def get_latest_active_job(self) -> GenerationJob | None:
        active = [job for job in self._jobs.values() if job.is_active]
        if not active:
            return None
        return max(active, key=lambda job: job.created_at)

    def has_active_jobs(self) -> bool:
        return any(job.is_active for job in self._jobs.values())

    def mark_job_saved(
        self,
        generation_id: str,
        character_id: str,
        character_name: str = "",
    ) -> None:
        job = self._jobs.get(generation_id)
        if not job:
            return
        job.saved_character_id = character_id
        job.saved_character_name = character_name
        job.updated_at = datetime.now()

    async def stream_events(
        self,
        generation_id: str,
        from_index: int = 0,
    ) -> AsyncIterator[ProgressEvent]:
        """蓄積済みイベントを再送し、実行中なら新規イベントを待つ。"""
        job = self._jobs.get(generation_id)
        if not job:
            yield ProgressEvent(
                type=ProgressEventType.ERROR,
                data="生成ジョブが見つかりません。",
            )
            return

        next_index = max(from_index, 0)
        notify_queue: asyncio.Queue[None] = asyncio.Queue()
        job._listeners.add(notify_queue)
        try:
            while True:
                while next_index < len(job.events):
                    event = job.events[next_index]
                    next_index += 1
                    yield event

                if not job.is_active:
                    break

                await notify_queue.get()
        finally:
            job._listeners.discard(notify_queue)

    async def generate_stream(
        self,
        request: GenerationRequest,
        profile: LLMProfile,
        endpoint: Endpoint,
        api_key: str | None = None,
        generation_id: str | None = None,
    ) -> AsyncIterator[ProgressEvent]:
        """
        生成を実行し、進捗イベントを非同期ストリームで返す。

        生成 ID を指定すると stop() で途中停止できる。
        """
        job = self.start_job(request, profile, endpoint, api_key, generation_id)
        async for event in self.stream_events(job.id):
            yield event

    async def _run_job(self, job: GenerationJob, api_key: str | None) -> None:
        job.status = GenerationJobStatus.RUNNING
        job.started_at = datetime.now()
        job.updated_at = job.started_at
        loop = asyncio.get_event_loop()
        self._record_event(job.id, ProgressEvent(
            type=ProgressEventType.STARTED,
            data={"profile": job.profile.name, "model": job.profile.model_id},
        ))

        def on_progress(event: ProgressEvent) -> None:
            loop.call_soon_threadsafe(self._record_event, job.id, event)

        def stop_check() -> bool:
            return self._stop_flag.get(job.id, False)

        def run_in_thread() -> GenerationResult:
            llm = create_llm(job.profile, job.endpoint, api_key)
            return run_generation(llm, job.request, on_progress, stop_check)

        try:
            result = await loop.run_in_executor(_EXECUTOR, run_in_thread)
            if result.success:
                job.result = result
                job.sheet_markdown = result.sheet_markdown
                if job.request.mode != GenerationMode.MODIFY:
                    try:
                        saved = await self.save_result(result, job.profile)
                        job.saved_character_id = saved.id
                        job.saved_character_name = saved.name
                    except Exception as exc:
                        job.save_error_message = str(exc)
                self._record_event(job.id, ProgressEvent(
                    type=ProgressEventType.DONE,
                    data=result,
                ))
            elif job.status not in _TERMINAL_STATUSES:
                self._record_event(job.id, ProgressEvent(
                    type=ProgressEventType.ERROR,
                    data=result.error_message or "生成に失敗しました。",
                ))
        except Exception as exc:
            self._record_event(job.id, ProgressEvent(
                type=ProgressEventType.ERROR,
                data=str(exc),
            ))
        finally:
            self._stop_flag.pop(job.id, None)

    def _record_event(self, generation_id: str, event: ProgressEvent) -> None:
        job = self._jobs.get(generation_id)
        if not job:
            return

        if event.type == ProgressEventType.SHEET_READY:
            job.sheet_markdown = str(event.data or "")
        elif event.type == ProgressEventType.DONE:
            if isinstance(event.data, GenerationResult):
                job.result = event.data
                job.sheet_markdown = event.data.sheet_markdown
            job.status = GenerationJobStatus.COMPLETED
            job.completed_at = datetime.now()
        elif event.type == ProgressEventType.ERROR:
            job.status = GenerationJobStatus.FAILED
            job.error_message = str(event.data or "不明なエラー")
            job.completed_at = datetime.now()
        elif event.type == ProgressEventType.STOPPED:
            job.status = GenerationJobStatus.CANCELLED
            job.error_message = str(event.data or "生成を停止しました。")
            job.completed_at = datetime.now()

        job.events.append(event)
        job.updated_at = datetime.now()

        for listener in list(job._listeners):
            listener.put_nowait(None)

    def stop(self, generation_id: str = "default") -> None:
        self._stop_flag[generation_id] = True

    async def save_result(
        self,
        result: GenerationResult,
        profile: LLMProfile,
        tags: list[str] | None = None,
    ) -> CharacterSheet:
        """生成結果をキャラクターとして保存する。"""
        sheet_id = self._character_service.new_id()
        sheet = _parse_sheet_to_structured(result.sheet_markdown, sheet_id)
        sheet.tags = tags or []
        sheet.generation_meta = GenerationMeta(
            llm_profile_name=profile.name,
            model_id=profile.model_id,
            temperature=profile.temperature if not profile.reasoning_enabled else None,
            reasoning_enabled=profile.reasoning_enabled,
            mode=result.mode.value,
            tool_count=result.tool_count,
            quality_status=result.quality_status,
            quality_score=result.quality_score,
        )
        return await self._character_service.save(sheet)
