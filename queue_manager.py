import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class JobStatus(Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ConversionJob:
    job_id: str
    user_id: int
    input_path: Path
    output_path: Path
    filename: str
    status: JobStatus = JobStatus.QUEUED
    error: Optional[str] = None
    duration: float = 0.0
    _event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)


class ConversionQueue:
    def __init__(self, max_workers: int = 2):
        self.max_workers = max_workers
        self._queue: asyncio.Queue = asyncio.Queue()
        self._jobs: dict[str, ConversionJob] = {}
        self._workers: list[asyncio.Task] = []
        self._stats = {"done": 0, "failed": 0}

    async def start(self):
        for i in range(self.max_workers):
            task = asyncio.create_task(self._worker(i), name=f"worker-{i}")
            self._workers.append(task)
        logger.info(f"Очередь запущена, воркеров: {self.max_workers}")

    async def stop(self):
        for task in self._workers:
            task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        logger.info("Очередь остановлена")

    def add_job(
        self,
        job_id: str,
        user_id: int,
        input_path: Path,
        output_path: Path,
        filename: str,
    ) -> int:
        job = ConversionJob(
            job_id=job_id,
            user_id=user_id,
            input_path=input_path,
            output_path=output_path,
            filename=filename,
        )
        self._jobs[job_id] = job
        self._queue.put_nowait(job)
        position = self._queue.qsize()
        logger.info(f"Задача {job_id} добавлена, позиция {position}")
        return position

    async def wait_for_job(self, job_id: str, timeout: float = 7200.0) -> ConversionJob:
        job = self._jobs[job_id]
        try:
            await asyncio.wait_for(job._event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            job.status = JobStatus.FAILED
            job.error = "Превышено время ожидания (2 часа)"
            job._event.set()
        return job

    def cancel_user_jobs(self, user_id: int) -> int:
        cancelled = 0
        for job in self._jobs.values():
            if job.user_id == user_id and job.status == JobStatus.QUEUED:
                job.status = JobStatus.CANCELLED
                job._event.set()
                cancelled += 1
        return cancelled

    def get_user_jobs(self, user_id: int) -> list[ConversionJob]:
        return [
            j for j in self._jobs.values()
            if j.user_id == user_id and j.status in (JobStatus.QUEUED, JobStatus.PROCESSING)
        ]

    def get_stats(self) -> dict:
        statuses = [j.status for j in self._jobs.values()]
        return {
            "queued": statuses.count(JobStatus.QUEUED),
            "processing": statuses.count(JobStatus.PROCESSING),
            "done": self._stats["done"],
            "failed": self._stats["failed"],
        }

    async def _worker(self, worker_id: int):
        from converter import convert_mts_to_mp4

        logger.info(f"Воркер {worker_id} запущен")
        while True:
            try:
                job: ConversionJob = await self._queue.get()

                if job.status == JobStatus.CANCELLED:
                    self._queue.task_done()
                    continue

                logger.info(f"Воркер {worker_id} берёт задачу {job.job_id}: {job.filename}")
                job.status = JobStatus.PROCESSING

                try:
                    duration = await convert_mts_to_mp4(
                        input_path=job.input_path,
                        output_path=job.output_path,
                    )
                    job.duration = duration
                    job.status = JobStatus.DONE
                    self._stats["done"] += 1
                    logger.info(f"Задача {job.job_id} выполнена за {duration:.1f}с")

                except Exception as e:
                    job.status = JobStatus.FAILED
                    job.error = str(e)
                    self._stats["failed"] += 1
                    logger.error(f"Задача {job.job_id} провалилась: {e}")

                finally:
                    job._event.set()
                    self._queue.task_done()

            except asyncio.CancelledError:
                logger.info(f"Воркер {worker_id} остановлен")
                break
            except Exception as e:
                logger.exception(f"Воркер {worker_id} — неожиданная ошибка: {e}")
