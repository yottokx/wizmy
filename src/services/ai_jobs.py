"""AIジョブの共通追跡サービス。"""

from __future__ import annotations

import asyncio
import inspect
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any


class AIJobStatus(str, Enum):
    """AIジョブの状態。"""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AIJobKind(str, Enum):
    """主要なAIジョブ種別。"""

    LLM_CHAT = "llm.chat"
    LLM_GROUP_CHAT = "llm.group_chat"
    LLM_NARRATION = "llm.narration"
    LLM_ASSIST = "llm.assist"
    LLM_PROMPT = "llm.prompt"
    TTS_SYNTHESIS = "tts.synthesis"
    TTS_DESIGN = "tts.design"
    IMAGE_SDXL = "image.sdxl"


TERMINAL_STATUSES = {
    AIJobStatus.SUCCEEDED,
    AIJobStatus.FAILED,
    AIJobStatus.CANCELLED,
}


@dataclass(frozen=True)
class AIJobEvent:
    """ジョブ状態変化をUIへ再送するイベント。"""

    index: int
    type: str
    status: AIJobStatus
    message: str = ""
    data: Any = None
    created_at: datetime = field(default_factory=datetime.now)


AIJobRunner = Callable[["AIJobRecord"], Awaitable[Any] | Any]
AIJobCancelCallback = Callable[["AIJobRecord"], Awaitable[None] | None]


@dataclass
class AIJobRecord:
    """プロセス内で保持するAIジョブ台帳。"""

    id: str
    kind: str
    label: str
    scope: str = ""
    status: AIJobStatus = AIJobStatus.QUEUED
    progress_message: str = "待機中"
    metadata: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    result_meta: dict[str, Any] = field(default_factory=dict)
    result_url: str = ""
    external_jobs: list[dict[str, Any]] = field(default_factory=list)
    error_message: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    updated_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None
    events: list[AIJobEvent] = field(default_factory=list)
    _listeners: set[asyncio.Queue[None]] = field(
        default_factory=set, repr=False, compare=False
    )
    _task: asyncio.Task | None = field(default=None, repr=False, compare=False)
    _cancel_callbacks: list[AIJobCancelCallback] = field(
        default_factory=list, repr=False, compare=False
    )

    @property
    def is_active(self) -> bool:
        return self.status not in TERMINAL_STATUSES

    @property
    def can_cancel(self) -> bool:
        return self.is_active and bool(self._cancel_callbacks or self._task)

    def add_cancel_callback(self, callback: AIJobCancelCallback) -> None:
        self._cancel_callbacks.append(callback)

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "scope": self.scope,
            "status": self.status.value,
            "progress_message": self.progress_message,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result_url": self.result_url,
            "external_jobs": list(self.external_jobs),
            "error_message": self.error_message,
            "can_cancel": self.can_cancel,
        }


class AIJobService:
    """LLM/TTS/画像生成などのAI処理をプロセス内で追跡する。"""

    def __init__(
        self,
        *,
        max_completed_jobs: int = 80,
        completed_ttl_minutes: int = 120,
    ) -> None:
        self._jobs: dict[str, AIJobRecord] = {}
        self._max_completed_jobs = max_completed_jobs
        self._completed_ttl = timedelta(minutes=completed_ttl_minutes)

    def start_job(
        self,
        *,
        kind: str | AIJobKind,
        label: str,
        runner: AIJobRunner,
        scope: str = "",
        metadata: dict[str, Any] | None = None,
        job_id: str | None = None,
        cancel_callback: AIJobCancelCallback | None = None,
    ) -> AIJobRecord:
        """バックグラウンドジョブを開始し、台帳レコードを返す。"""
        self._prune_completed_jobs()
        resolved_id = job_id or f"ai-{uuid.uuid4().hex[:12]}"
        job = AIJobRecord(
            id=resolved_id,
            kind=kind.value if isinstance(kind, AIJobKind) else str(kind),
            label=label,
            scope=scope,
            metadata=dict(metadata or {}),
        )
        if cancel_callback is not None:
            job.add_cancel_callback(cancel_callback)
        self._jobs[job.id] = job
        self._record_event(job, "queued", "待機中")
        job._task = asyncio.create_task(self._run_job(job, runner))
        return job

    def get_job(self, job_id: str | None) -> AIJobRecord | None:
        if not job_id:
            return None
        self._prune_completed_jobs()
        return self._jobs.get(job_id)

    def list_jobs(
        self,
        *,
        scope: str = "",
        active_only: bool = False,
        limit: int = 30,
    ) -> list[AIJobRecord]:
        self._prune_completed_jobs()
        jobs = list(self._jobs.values())
        if scope:
            jobs = [job for job in jobs if job.scope == scope]
        if active_only:
            jobs = [job for job in jobs if job.is_active]
        jobs.sort(key=lambda item: item.created_at, reverse=True)
        return jobs[: max(1, limit)]

    def latest_active_job(self, *, scope: str = "") -> AIJobRecord | None:
        jobs = self.list_jobs(scope=scope, active_only=True, limit=1)
        return jobs[0] if jobs else None

    def has_active_jobs(self, *, scope: str = "") -> bool:
        return self.latest_active_job(scope=scope) is not None

    async def stream_events(
        self,
        job_id: str,
        from_index: int = 0,
    ):
        """蓄積済みイベントを再送し、その後の更新を待つ。"""
        job = self._jobs.get(job_id)
        if job is None:
            yield AIJobEvent(
                index=0,
                type="missing",
                status=AIJobStatus.FAILED,
                message="AIジョブが見つかりません。",
            )
            return

        next_index = max(0, from_index)
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

    async def wait(self, job_id: str) -> AIJobRecord:
        """ジョブが終端状態になるまで待つ。"""
        job = self._jobs[job_id]
        if job._task is not None:
            try:
                await asyncio.shield(job._task)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
        return job

    async def cancel_job(self, job_id: str) -> AIJobRecord | None:
        """可能な範囲でジョブを停止する。"""
        job = self._jobs.get(job_id)
        if job is None or not job.is_active:
            return job

        self.update_progress(job.id, "停止要求中...")
        for callback in list(job._cancel_callbacks):
            try:
                result = callback(job)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:  # noqa: BLE001
                self._record_event(
                    job,
                    "cancel_warning",
                    f"停止要求に失敗しました: {exc}",
                    data={"error": str(exc)},
                )

        if job._task is not None and not job._task.done():
            job._task.cancel()
        self._mark_cancelled(job, "停止しました")
        return job

    def update_progress(
        self,
        job_id: str,
        message: str,
        *,
        data: Any = None,
    ) -> None:
        job = self._jobs.get(job_id)
        if job is None or not job.is_active:
            return
        job.progress_message = message
        job.updated_at = datetime.now()
        self._record_event(job, "progress", message, data=data)

    def add_external_job(
        self,
        job_id: str,
        external: dict[str, Any],
    ) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.external_jobs.append(dict(external))
        job.updated_at = datetime.now()
        self._record_event(job, "external_job", "外部ジョブを開始しました", data=external)

    def set_result_meta(
        self,
        job_id: str,
        metadata: dict[str, Any],
    ) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.result_meta.update(metadata)
        if "result_url" in metadata:
            job.result_url = str(metadata["result_url"] or "")
        job.updated_at = datetime.now()
        self._record_event(job, "result_meta", "結果情報を更新しました", data=metadata)

    async def _run_job(self, job: AIJobRecord, runner: AIJobRunner) -> None:
        job.status = AIJobStatus.RUNNING
        job.started_at = datetime.now()
        job.updated_at = job.started_at
        job.progress_message = "実行中"
        self._record_event(job, "started", "開始しました")
        try:
            result = runner(job)
            if inspect.isawaitable(result):
                result = await result
            if job.status == AIJobStatus.CANCELLED:
                return
            job.result = result
            job.status = AIJobStatus.SUCCEEDED
            job.progress_message = "完了"
            job.completed_at = datetime.now()
            job.updated_at = job.completed_at
            self._record_event(job, "succeeded", "完了しました", data=result)
            self._prune_completed_jobs()
        except asyncio.CancelledError:
            self._mark_cancelled(job, "停止しました")
        except Exception as exc:  # noqa: BLE001
            if job.status != AIJobStatus.CANCELLED:
                job.status = AIJobStatus.FAILED
                job.error_message = str(exc)
                job.progress_message = "失敗"
                job.completed_at = datetime.now()
                job.updated_at = job.completed_at
                self._record_event(
                    job,
                    "failed",
                    str(exc),
                    data={"error": str(exc)},
                )
                self._prune_completed_jobs()

    def _mark_cancelled(self, job: AIJobRecord, message: str) -> None:
        if job.status in TERMINAL_STATUSES:
            return
        job.status = AIJobStatus.CANCELLED
        job.progress_message = message
        job.completed_at = datetime.now()
        job.updated_at = job.completed_at
        self._record_event(job, "cancelled", message)
        self._prune_completed_jobs()

    def _record_event(
        self,
        job: AIJobRecord,
        event_type: str,
        message: str = "",
        *,
        data: Any = None,
    ) -> None:
        event = AIJobEvent(
            index=len(job.events),
            type=event_type,
            status=job.status,
            message=message,
            data=data,
        )
        job.events.append(event)
        for listener in list(job._listeners):
            listener.put_nowait(None)

    def _prune_completed_jobs(self) -> None:
        now = datetime.now()
        completed = [
            job for job in self._jobs.values()
            if not job.is_active and job.completed_at is not None
        ]
        for job in completed:
            completed_at = job.completed_at
            if completed_at is not None and now - completed_at > self._completed_ttl:
                self._jobs.pop(job.id, None)

        completed = [
            job for job in self._jobs.values()
            if not job.is_active and job.completed_at is not None
        ]
        completed.sort(key=lambda item: item.completed_at or item.created_at, reverse=True)
        for job in completed[self._max_completed_jobs:]:
            self._jobs.pop(job.id, None)
