from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import monotonic
from typing import Awaitable, Callable, Generic, Iterable, TypeVar

ItemT = TypeVar("ItemT")
ValueT = TypeVar("ValueT")


@dataclass(frozen=True)
class BatchItemResult(Generic[ItemT, ValueT]):
    index: int
    item: ItemT
    ok: bool
    skipped: bool = False
    value: ValueT | None = None
    error: Exception | None = None


@dataclass(frozen=True)
class BatchStatistics:
    total: int
    succeeded: int
    failed: int
    skipped: int
    duration_seconds: float


@dataclass(frozen=True)
class BatchExecutionResult(Generic[ItemT, ValueT]):
    items: list[BatchItemResult[ItemT, ValueT]]
    statistics: BatchStatistics


class BoundedBatchProcessor(Generic[ItemT, ValueT]):
    """Run async handlers with a fixed number of workers and a bounded queue."""

    def __init__(self, concurrency: int) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be >= 1")
        self.concurrency = concurrency

    async def process(
        self,
        items: Iterable[ItemT],
        handler: Callable[[ItemT], Awaitable[ValueT]],
        *,
        skip_if: Callable[[ItemT], bool] | None = None,
    ) -> BatchExecutionResult[ItemT, ValueT]:
        started = monotonic()
        queue: asyncio.Queue[tuple[int, ItemT] | None] = asyncio.Queue(maxsize=self.concurrency * 2)
        semaphore = asyncio.Semaphore(self.concurrency)
        results: list[BatchItemResult[ItemT, ValueT] | None] = []

        async def produce() -> None:
            for index, item in enumerate(items):
                results.append(None)
                await queue.put((index, item))
            for _ in range(self.concurrency):
                await queue.put(None)

        async def worker() -> None:
            while True:
                entry = await queue.get()
                try:
                    if entry is None:
                        return
                    index, item = entry
                    if skip_if is not None and skip_if(item):
                        results[index] = BatchItemResult(index=index, item=item, ok=False, skipped=True)
                        continue
                    try:
                        async with semaphore:
                            value = await handler(item)
                    except Exception as exc:
                        results[index] = BatchItemResult(index=index, item=item, ok=False, error=exc)
                    else:
                        results[index] = BatchItemResult(index=index, item=item, ok=True, value=value)
                finally:
                    queue.task_done()

        producer = asyncio.create_task(produce())
        workers = [asyncio.create_task(worker()) for _ in range(self.concurrency)]
        try:
            await producer
            await queue.join()
            await asyncio.gather(*workers)
        except BaseException:
            producer.cancel()
            for worker_task in workers:
                worker_task.cancel()
            await asyncio.gather(producer, *workers, return_exceptions=True)
            raise

        completed = [item for item in results if item is not None]
        statistics = BatchStatistics(
            total=len(completed),
            succeeded=sum(item.ok for item in completed),
            failed=sum(not item.ok and not item.skipped for item in completed),
            skipped=sum(item.skipped for item in completed),
            duration_seconds=max(0.0, monotonic() - started),
        )
        return BatchExecutionResult(items=completed, statistics=statistics)


__all__ = ["BatchExecutionResult", "BatchItemResult", "BatchStatistics", "BoundedBatchProcessor"]