import asyncio

import pytest

from src.batch import BoundedBatchProcessor


@pytest.mark.asyncio
async def test_batch_limits_concurrency_and_preserves_input_order():
    active = 0
    maximum = 0

    async def handle(value: int) -> int:
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.01)
        active -= 1
        return value * 2

    execution = await BoundedBatchProcessor[int, int](2).process(range(6), handle)

    assert [item.value for item in execution.items] == [0, 2, 4, 6, 8, 10]
    assert maximum <= 2
    assert execution.statistics.total == 6
    assert execution.statistics.succeeded == 6
    assert execution.statistics.failed == 0
    assert execution.statistics.skipped == 0
    assert execution.statistics.duration_seconds >= 0


@pytest.mark.asyncio
async def test_batch_isolates_failures_and_counts_skips():
    async def handle(value: str) -> str:
        if value == "bad":
            raise RuntimeError("failed item")
        return value.upper()

    execution = await BoundedBatchProcessor[str, str](2).process(
        ["ok", "bad", "skip"],
        handle,
        skip_if=lambda value: value == "skip",
    )

    assert [item.value for item in execution.items] == ["OK", None, None]
    assert execution.statistics == execution.statistics.__class__(
        total=3,
        succeeded=1,
        failed=1,
        skipped=1,
        duration_seconds=execution.statistics.duration_seconds,
    )
    assert isinstance(execution.items[1].error, RuntimeError)


@pytest.mark.asyncio
async def test_empty_batch_has_zero_deterministic_counts():
    async def handle(value: int) -> int:
        return value

    execution = await BoundedBatchProcessor[int, int](3).process([], handle)

    assert execution.items == []
    assert execution.statistics.total == 0
    assert execution.statistics.succeeded == 0
    assert execution.statistics.failed == 0
    assert execution.statistics.skipped == 0


def test_batch_rejects_invalid_concurrency():
    with pytest.raises(ValueError, match="concurrency"):
        BoundedBatchProcessor(0)