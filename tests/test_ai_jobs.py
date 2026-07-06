from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timedelta

from src.services.ai_jobs import AIJobKind, AIJobService, AIJobStatus


class AIJobServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_success_records_result_and_replays_events(self) -> None:
        service = AIJobService()

        async def runner(job):
            service.update_progress(job.id, "処理中", data={"step": 1})
            return {"value": "ok"}

        job = service.start_job(
            kind=AIJobKind.LLM_ASSIST,
            label="テストジョブ",
            scope="scope-a",
            runner=runner,
        )

        finished = await service.wait(job.id)

        self.assertEqual(finished.status, AIJobStatus.SUCCEEDED)
        self.assertEqual(finished.result, {"value": "ok"})
        self.assertEqual(finished.progress_message, "完了")
        replayed = [event async for event in service.stream_events(job.id, from_index=0)]
        self.assertEqual(
            [event.status for event in replayed],
            [
                AIJobStatus.QUEUED,
                AIJobStatus.RUNNING,
                AIJobStatus.RUNNING,
                AIJobStatus.SUCCEEDED,
            ],
        )
        self.assertIn("処理中", [event.message for event in replayed])

    async def test_failure_records_error(self) -> None:
        service = AIJobService()

        async def runner(_job):
            raise RuntimeError("synthetic failure")

        job = service.start_job(
            kind=AIJobKind.LLM_CHAT,
            label="失敗ジョブ",
            scope="scope-a",
            runner=runner,
        )

        finished = await service.wait(job.id)

        self.assertEqual(finished.status, AIJobStatus.FAILED)
        self.assertIn("synthetic failure", finished.error_message or "")
        self.assertFalse(service.has_active_jobs())

    async def test_cancel_invokes_callback_and_marks_cancelled(self) -> None:
        service = AIJobService()
        started = asyncio.Event()
        cancelled: list[str] = []

        async def runner(_job):
            started.set()
            await asyncio.sleep(60)

        async def cancel_callback(job):
            cancelled.append(job.id)

        job = service.start_job(
            kind=AIJobKind.TTS_SYNTHESIS,
            label="停止ジョブ",
            scope="scope-a",
            runner=runner,
            cancel_callback=cancel_callback,
        )
        await started.wait()

        await service.cancel_job(job.id)
        finished = await service.wait(job.id)

        self.assertEqual(finished.status, AIJobStatus.CANCELLED)
        self.assertEqual(cancelled, [job.id])
        self.assertFalse(service.has_active_jobs(scope="scope-a"))

    async def test_latest_active_job_filters_scope(self) -> None:
        service = AIJobService()
        release_a = asyncio.Event()
        release_b = asyncio.Event()

        async def runner_a(_job):
            await release_a.wait()

        async def runner_b(_job):
            await release_b.wait()

        first = service.start_job(
            kind=AIJobKind.IMAGE_SDXL,
            label="画像A",
            scope="image:a",
            runner=runner_a,
        )
        second = service.start_job(
            kind=AIJobKind.IMAGE_SDXL,
            label="画像B",
            scope="image:b",
            runner=runner_b,
        )

        self.assertEqual(service.latest_active_job(scope="image:a").id, first.id)
        self.assertEqual(service.latest_active_job(scope="image:b").id, second.id)
        self.assertEqual(service.latest_active_job().id, second.id)

        release_a.set()
        release_b.set()
        await service.wait(first.id)
        await service.wait(second.id)

    async def test_completed_jobs_are_pruned_by_count(self) -> None:
        service = AIJobService(max_completed_jobs=1, completed_ttl_minutes=60)

        async def runner(job):
            return job.label

        first = service.start_job(
            kind=AIJobKind.LLM_ASSIST,
            label="first",
            runner=runner,
        )
        await service.wait(first.id)
        second = service.start_job(
            kind=AIJobKind.LLM_ASSIST,
            label="second",
            runner=runner,
        )
        await service.wait(second.id)

        jobs = service.list_jobs()

        self.assertEqual([job.label for job in jobs], ["second"])
        self.assertIsNone(service.get_job(first.id))
        self.assertIsNotNone(service.get_job(second.id))

    async def test_completed_jobs_are_pruned_by_ttl(self) -> None:
        service = AIJobService(max_completed_jobs=10, completed_ttl_minutes=1)

        async def runner(_job):
            return "done"

        job = service.start_job(
            kind=AIJobKind.LLM_ASSIST,
            label="ttl",
            runner=runner,
        )
        await service.wait(job.id)
        job.completed_at = datetime.now() - timedelta(minutes=2)

        self.assertEqual(service.list_jobs(), [])
        self.assertIsNone(service.get_job(job.id))

    async def test_wait_returns_failed_record_when_job_was_pruned(self) -> None:
        service = AIJobService(max_completed_jobs=10, completed_ttl_minutes=1)

        async def runner(_job):
            return "done"

        job = service.start_job(
            kind=AIJobKind.LLM_ASSIST,
            label="ttl",
            runner=runner,
        )
        await service.wait(job.id)
        job.completed_at = datetime.now() - timedelta(minutes=2)

        finished = await service.wait(job.id)

        self.assertEqual(finished.id, job.id)
        self.assertEqual(finished.status, AIJobStatus.FAILED)
        self.assertEqual(finished.error_message, "AIジョブが見つかりません。")
        self.assertEqual([event.type for event in finished.events], ["missing"])


if __name__ == "__main__":
    unittest.main()
