import asyncio

import pytest

from src.job_queue import AsyncJobQueueExecutor, JobExecutionError, PipelineJob


def make_jobs(count=4):
    return [PipelineJob(job_id=f"job-{index}", source_url=f"https://example.com/{index}", entity_type="STARTUP", payload=index) for index in range(count)]


@pytest.mark.asyncio
async def test_bounded_worker_concurrency_and_success_metrics():
    active = 0
    maximum = 0

    async def handle(job):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.01)
        active -= 1
        return job.payload * 2

    execution = await AsyncJobQueueExecutor[int, int](2).run(make_jobs(6), handle)

    assert maximum <= 2
    assert [result.value for result in execution.results] == [0, 2, 4, 6, 8, 10]
    assert execution.metrics.queued == 6
    assert execution.metrics.started == 6
    assert execution.metrics.succeeded == 6
    assert execution.metrics.failed == 0
    assert execution.metrics.retried == 0
    assert execution.metrics.cancelled == 0


@pytest.mark.asyncio
async def test_retryable_failure_retries_and_succeeds():
    calls = {"job-0": 0}

    async def handle(job):
        calls[job.job_id] += 1
        if calls[job.job_id] == 1:
            raise JobExecutionError("temporary", category="timeout", retryable=True)
        return "ok"

    execution = await AsyncJobQueueExecutor[int, str](1).run(make_jobs(1), handle, max_retries=2)

    assert execution.results[0].status == "succeeded"
    assert execution.results[0].attempt_count == 2
    assert execution.metrics.retried == 1
    assert execution.metrics.started == 2


@pytest.mark.asyncio
async def test_full_queue_with_simultaneous_retries_eventually_drains():
    first_attempts = 0
    first_attempts_ready = asyncio.Event()
    release_failures = asyncio.Event()

    async def handle(job):
        nonlocal first_attempts
        if job.job_id in {"job-0", "job-1"} and first_attempts < 2:
            first_attempts += 1
            if first_attempts == 2:
                first_attempts_ready.set()
            await first_attempts_ready.wait()
            await release_failures.wait()
            raise JobExecutionError("temporary", category="rate_limited", retryable=True)
        return job.payload

    async def run_jobs():
        task = asyncio.create_task(
            AsyncJobQueueExecutor[int, int](2, queue_size=1).run(make_jobs(4), handle, max_retries=1)
        )
        await first_attempts_ready.wait()
        release_failures.set()
        return await task

    execution = await asyncio.wait_for(run_jobs(), timeout=2)

    assert all(result.status == "succeeded" for result in execution.results)
    assert execution.metrics.retried == 2


@pytest.mark.asyncio
async def test_permanent_failure_does_not_stop_other_jobs():
    async def handle(job):
        if job.payload == 1:
            raise JobExecutionError("bad input", category="validation")
        return job.payload

    execution = await AsyncJobQueueExecutor[int, int](2).run(make_jobs(3), handle, max_retries=2)

    assert [result.status for result in execution.results] == ["succeeded", "failed", "succeeded"]
    assert execution.metrics.failed == 1
    assert execution.metrics.succeeded == 2
    assert execution.metrics.retried == 0


@pytest.mark.asyncio
async def test_skipped_and_empty_queue_metrics_are_deterministic():
    async def handle(job):
        return job.payload

    skipped = await AsyncJobQueueExecutor[int, int](2).run(make_jobs(2), handle, skip_if=lambda job: job.payload == 1)
    empty = await AsyncJobQueueExecutor[int, int](2).run([], handle)

    assert skipped.metrics.skipped == 1
    assert skipped.results[1].status == "skipped"
    assert empty.results == []
    assert empty.metrics.queued == 0
    assert empty.metrics.duration_seconds >= 0


@pytest.mark.asyncio
async def test_shutdown_drains_queue_without_background_workers():
    active = 0

    async def handle(job):
        nonlocal active
        active += 1
        await asyncio.sleep(0.001)
        active -= 1
        return job.payload

    await AsyncJobQueueExecutor[int, int](2).run(make_jobs(10), handle)
    await asyncio.sleep(0)
    assert active == 0
    assert not [task for task in asyncio.all_tasks() if task is not asyncio.current_task() and not task.done()]


@pytest.mark.asyncio
async def test_cancellation_cleans_up_workers_and_handler():
    started = asyncio.Event()
    active = 0

    async def handle(job):
        nonlocal active
        active += 1
        started.set()
        try:
            await asyncio.sleep(10)
        finally:
            active -= 1

    task = asyncio.create_task(AsyncJobQueueExecutor[int, int](2).run(make_jobs(10), handle))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0)
    assert active == 0
    assert not [worker for worker in asyncio.all_tasks() if worker is not asyncio.current_task() and not worker.done()]


def test_job_metadata_is_deterministic_and_traceable():
    job = PipelineJob(job_id="fixed-id", source_url="https://example.com/a", entity_type="PRODUCT", payload={"x": 1})

    assert job.job_id == "fixed-id"
    assert job.source_url == "https://example.com/a"
    assert job.entity_type == "PRODUCT"
    assert job.created_at.tzinfo is not None
