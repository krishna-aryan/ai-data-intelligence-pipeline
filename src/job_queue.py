from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import monotonic
from typing import Any, Awaitable, Callable, Generic, Iterable, TypeVar
from uuid import uuid4


PayloadT = TypeVar("PayloadT")
ValueT = TypeVar("ValueT")


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class PipelineJob(Generic[PayloadT]):
    job_id: str
    source_url: str
    entity_type: str
    payload: PayloadT
    created_at: datetime = field(default_factory=_now)

    @classmethod
    def create(cls, *, source_url: str, entity_type: str, payload: PayloadT) -> "PipelineJob[PayloadT]":
        return cls(job_id=str(uuid4()), source_url=source_url, entity_type=entity_type, payload=payload)


@dataclass(frozen=True)
class JobResult(Generic[PayloadT, ValueT]):
    job: PipelineJob[PayloadT]
    status: str
    attempt_count: int
    error_category: str | None = None
    error_message: str | None = None
    error_details: dict[str, Any] | None = None
    value: ValueT | None = None
    started_at: datetime | None = None
    finished_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class QueueMetrics:
    queued: int = 0
    started: int = 0
    succeeded: int = 0
    failed: int = 0
    retried: int = 0
    skipped: int = 0
    cancelled: int = 0
    duration_seconds: float = 0.0


@dataclass(frozen=True)
class QueueExecutionResult(Generic[PayloadT, ValueT]):
    results: list[JobResult[PayloadT, ValueT]]
    metrics: QueueMetrics


class JobExecutionError(RuntimeError):
    def __init__(self, message: str, *, category: str = "job_failure", retryable: bool = False, details: dict[str, Any] | None = None) -> None:
        self.category = category
        self.retryable = retryable
        self.details = details or {}
        super().__init__(message)


class AsyncJobQueueExecutor(Generic[PayloadT, ValueT]):
    """Bounded in-process executor with a replaceable job/handler boundary."""

    def __init__(self, concurrency: int, *, queue_size: int | None = None) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be >= 1")
        self.concurrency = concurrency
        self.queue_size = queue_size if queue_size is not None else concurrency * 2
        if self.queue_size < 1:
            raise ValueError("queue_size must be >= 1")

    async def run(
        self,
        jobs: Iterable[PipelineJob[PayloadT]],
        handler: Callable[[PipelineJob[PayloadT]], Awaitable[ValueT]],
        *,
        max_retries: int = 0,
        skip_if: Callable[[PipelineJob[PayloadT]], bool] | None = None,
    ) -> QueueExecutionResult[PayloadT, ValueT]:
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        job_list = list(jobs)
        queue: asyncio.Queue[tuple[PipelineJob[PayloadT], int] | None] = asyncio.Queue(maxsize=self.queue_size)
        pending_retries: deque[tuple[PipelineJob[PayloadT], int]] = deque()
        retry_event = asyncio.Event()
        result_slots: dict[str, JobResult[PayloadT, ValueT]] = {}
        started_clock = monotonic()
        metrics = {"queued": 0, "started": 0, "succeeded": 0, "failed": 0, "retried": 0, "skipped": 0, "cancelled": 0}
        outstanding = len(job_list)
        all_done = asyncio.Event()
        if outstanding == 0:
            all_done.set()

        async def enqueue() -> None:
            for job in job_list:
                await queue.put((job, 0))
                metrics["queued"] += 1

        async def dispatch_retries() -> None:
            while True:
                await retry_event.wait()
                retry_event.clear()
                while pending_retries:
                    await queue.put(pending_retries.popleft())
                if all_done.is_set():
                    return

        async def worker() -> None:
            nonlocal outstanding
            while True:
                entry = await queue.get()
                try:
                    if entry is None:
                        return
                    job, attempt = entry
                    if skip_if is not None and skip_if(job):
                        result_slots[job.job_id] = JobResult(job=job, status="skipped", attempt_count=attempt, started_at=None)
                        metrics["skipped"] += 1
                        outstanding -= 1
                        if outstanding == 0:
                            all_done.set()
                        continue
                    start_time = _now()
                    metrics["started"] += 1
                    try:
                        value = await handler(job)
                    except asyncio.CancelledError:
                        result_slots[job.job_id] = JobResult(job=job, status="cancelled", attempt_count=attempt + 1, error_category="cancelled", started_at=start_time)
                        metrics["cancelled"] += 1
                        outstanding -= 1
                        if outstanding == 0:
                            all_done.set()
                        raise
                    except Exception as exc:
                        retryable = bool(getattr(exc, "retryable", False))
                        category = str(getattr(exc, "category", "job_failure"))
                        if retryable and attempt < max_retries:
                            metrics["retried"] += 1
                            pending_retries.append((job, attempt + 1))
                            retry_event.set()
                            continue
                        result_slots[job.job_id] = JobResult(job=job, status="failed", attempt_count=attempt + 1, error_category=category, error_message=str(exc), error_details=getattr(exc, "details", None), started_at=start_time)
                        metrics["failed"] += 1
                        outstanding -= 1
                        if outstanding == 0:
                            all_done.set()
                    else:
                        result_slots[job.job_id] = JobResult(job=job, status="succeeded", attempt_count=attempt + 1, value=value, started_at=start_time)
                        metrics["succeeded"] += 1
                        outstanding -= 1
                        if outstanding == 0:
                            all_done.set()
                finally:
                    queue.task_done()

        producer = asyncio.create_task(enqueue())
        retry_dispatcher = asyncio.create_task(dispatch_retries())
        workers = [asyncio.create_task(worker()) for _ in range(self.concurrency)]
        try:
            await producer
            await all_done.wait()
            await queue.join()
            for task in workers:
                task.cancel()
            retry_dispatcher.cancel()
            await asyncio.gather(*workers, retry_dispatcher, return_exceptions=True)
        except BaseException:
            producer.cancel()
            retry_dispatcher.cancel()
            for task in workers:
                task.cancel()
            await asyncio.gather(producer, retry_dispatcher, *workers, return_exceptions=True)
            raise

        results = [result_slots[job.job_id] for job in job_list if job.job_id in result_slots]
        return QueueExecutionResult(
            results=results,
            metrics=QueueMetrics(**metrics, duration_seconds=max(0.0, monotonic() - started_clock)),
        )


__all__ = [
    "AsyncJobQueueExecutor",
    "JobExecutionError",
    "JobResult",
    "PipelineJob",
    "QueueExecutionResult",
    "QueueMetrics",
]