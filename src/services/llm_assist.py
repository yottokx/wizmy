"""補助 LLM ユースケースを ai_jobs 経由で実行する共通基盤。

solo(`chat_assist`)/ group(`group_chat_assist`)の両サービスが共有する、
ジョブ完了結果の型とジョブ実行ヘルパーを提供する。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .ai_jobs import AIJobKind, AIJobService, AIJobStatus


@dataclass(frozen=True)
class AssistJobResult:
    """補助 LLM ジョブの完了状態と結果。"""

    job_id: str
    status: AIJobStatus
    value: Any = None
    error_message: str = ""

    @property
    def succeeded(self) -> bool:
        return self.status == AIJobStatus.SUCCEEDED


class LLMAssistService:
    """補助 LLM ジョブを ai_jobs 経由で実行する基底サービス。"""

    def __init__(self, ai_jobs: AIJobService) -> None:
        self._ai_jobs = ai_jobs

    async def run_assist_job(
        self,
        *,
        label: str,
        scope: str,
        metadata: dict[str, Any],
        runner,
        result_url: str = "",
        on_job_started=None,
    ) -> AssistJobResult:
        job = self._ai_jobs.start_job(
            kind=AIJobKind.LLM_ASSIST,
            label=label,
            scope=scope,
            metadata=metadata,
            runner=lambda _: runner(),
        )
        if result_url:
            self._ai_jobs.set_result_meta(job.id, {"result_url": result_url})
        if on_job_started is not None:
            on_job_started(job.id)
        finished = await self._ai_jobs.wait(job.id)
        return AssistJobResult(
            job_id=job.id,
            status=finished.status,
            value=finished.result,
            error_message=finished.error_message,
        )
